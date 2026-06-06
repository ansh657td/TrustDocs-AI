"""
Document Analysis Service — Pipeline Orchestrator

Responsibilities:
1. Accept document + job metadata
2. Run preprocessor
3. Execute forensic modules in dependency-aware order
4. Generate composite heatmap
5. Invoke fraud scoring engine
6. Persist results to database
7. Return FraudVerdict
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.domain.entities.document import (
    AnalysisStatus,
    ForensicContext,
    FraudVerdict,
)
from app.domain.services.fraud_scoring import FraudScoringEngine
from app.infrastructure.forensics.preprocessor import DocumentPreprocessor, PreprocessorError

# Import all modules
from app.modules.ela.ela_module import ELAModule
from app.modules.noise.noise_module import NoiseAnalysisModule
from app.modules.copymove.copymove_module import CopyMoveModule
from app.modules.edge.edge_module import EdgeArtifactModule
from app.modules.color.color_font_metadata_modules import (
    ColorConsistencyModule,
    FontAnalysisModule,
    MetadataAnalysisModule,
)
from app.modules.ai_detection.ai_gan_frequency_modules import (
    AIArtifactDetectionModule,
    FrequencyAnalysisModule,
    GANDetectionModule,
)
from app.modules.pdf_analysis.pdf_layout_heatmap_modules import (
    HeatmapGenerator,
    LayoutConsistencyModule,
    PDFStructureModule,
)
from app.modules.text_forensics.text_forensics_module import TextForensicsModule

logger = logging.getLogger("docfraud.service")


class AnalysisError(Exception):
    """Raised when analysis pipeline fails unrecoverably."""
    pass


class DocumentAnalysisService:
    """
    Main orchestrator for document fraud detection pipeline.

    Thread safety: each call creates a fresh ForensicContext and
    module instances — fully isolated per request.
    """

    def __init__(self):
        self.preprocessor = DocumentPreprocessor()
        self.scoring_engine = FraudScoringEngine()
        self.heatmap_generator = HeatmapGenerator()

    def analyze(
        self,
        file_path: Path,
        original_filename: str,
        document_id: Optional[str] = None,
        job_id: Optional[str] = None,
        requested_by: Optional[str] = None,
    ) -> FraudVerdict:
        """
        Execute the full forensic analysis pipeline.

        Args:
            file_path: Path to uploaded document
            original_filename: User-provided filename
            document_id: Pre-assigned document UUID (or generated)
            job_id: Pre-assigned job UUID (or generated)
            requested_by: IP / user identifier for audit

        Returns:
            FraudVerdict with full analysis results

        Raises:
            AnalysisError: On unrecoverable pipeline failure
        """
        start_time = datetime.utcnow()
        job_id = job_id or str(uuid.uuid4())
        document_id = document_id or str(uuid.uuid4())

        logger.info(
            "Starting analysis job_id=%s file=%s", job_id, original_filename
        )

        # ── Phase 1: Preprocess ───────────────────────────────────
        try:
            ctx = self.preprocessor.prepare(
                file_path=file_path,
                job_id=job_id,
                document_id=document_id,
                original_filename=original_filename,
                requested_by=requested_by,
            )
        except PreprocessorError as e:
            raise AnalysisError(f"Preprocessing failed: {e}") from e

        # ── Phase 2: Build module pipeline ───────────────────────
        modules = self._build_pipeline(ctx)

        # ── Phase 3: Execute modules ──────────────────────────────
        logger.info("Executing %d forensic modules", len(modules))

        # Run modules in parallel where safe; sequential where order matters
        # Metadata and PDF structure first (no image dependency)
        independent_modules = [
            m for m in modules
            if m.MODULE_NAME in ("metadata", "pdf_structure")
        ]
        image_modules = [
            m for m in modules
            if m.MODULE_NAME not in ("metadata", "pdf_structure")
        ]

        # Execute independent modules sequentially (fast)
        for module in independent_modules:
            result = module.run(ctx)
            ctx.add_module_result(result)

        # Execute image modules in thread pool
        max_workers = min(settings.max_workers, len(image_modules))
        if max_workers > 0 and image_modules:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(module.run, ctx): module.MODULE_NAME
                    for module in image_modules
                }
                for future in as_completed(futures):
                    module_name = futures[future]
                    try:
                        result = future.result(timeout=settings.worker_timeout_seconds)
                        ctx.add_module_result(result)
                        logger.debug(
                            "Module %s: score=%.3f confidence=%.3f",
                            module_name, result.score, result.confidence,
                        )
                    except Exception as e:
                        logger.error("Module %s raised exception: %s", module_name, e)

        # ── Phase 4: Generate heatmap ─────────────────────────────
        heatmap_path: Optional[str] = None
        if ctx.page_images:
            heatmap_path = self.heatmap_generator.generate(
                original_image=ctx.page_images[0],
                ctx=ctx,
                job_id=job_id,
            )

        # ── Phase 5: Compute fraud verdict ────────────────────────
        verdict = self.scoring_engine.compute(
            ctx=ctx,
            heatmap_path=heatmap_path,
            processing_start=start_time,
        )

        logger.info(
            "Analysis complete: job=%s score=%.1f risk=%s time=%dms",
            job_id,
            verdict.fraud_score,
            verdict.risk_level.value,
            verdict.processing_time_ms,
        )

        return verdict

    def _build_pipeline(self, ctx: ForensicContext) -> list:
        """
        Construct the list of modules to run based on document type.

        PDF-only modules: PDFStructureModule
        Image-only modules: ELA, Noise, CopyMove, etc.
        Universal: Metadata, Layout, AI, GAN, Frequency
        """
        pipeline = [MetadataAnalysisModule()]

        if ctx.is_pdf:
            pipeline.append(PDFStructureModule())

        if ctx.page_images:
            pipeline.extend([
                ELAModule(),
                NoiseAnalysisModule(),
                CopyMoveModule(),
                EdgeArtifactModule(),
                ColorConsistencyModule(),
                FontAnalysisModule(),
                AIArtifactDetectionModule(),
                GANDetectionModule(),
                FrequencyAnalysisModule(),
                LayoutConsistencyModule(),
                TextForensicsModule(),   # ← text-level manipulation detection
            ])

        return pipeline