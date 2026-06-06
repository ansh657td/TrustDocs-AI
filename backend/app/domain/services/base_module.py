"""
Base Forensic Module — Abstract Interface

All forensic analysis modules implement this interface.
Enforces: type hints, logging, timing, error isolation, test hooks.

Design pattern: Strategy + Template Method
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

from app.domain.entities.document import ForensicContext, ModuleScore


logger = logging.getLogger(__name__)


class ForensicModuleError(Exception):
    """Raised when a forensic module encounters a non-recoverable error."""
    pass


class ForensicModule(ABC):
    """
    Abstract base for all forensic analysis modules.

    Template method pattern:
      run() → _validate() → _analyze() → ModuleScore

    Each subclass implements _analyze() only.
    run() handles timing, logging, error isolation.
    """

    # Subclasses must define these
    MODULE_NAME: str = ""
    WEIGHT: float = 0.0         # contribution to final fraud score
    VERSION: str = "1.0.0"
    MIN_IMAGE_SIZE: int = 64    # skip if image smaller than this in any dimension
    REQUIRES_PDF: bool = False
    REQUIRES_IMAGE: bool = False

    def __init__(self):
        if not self.MODULE_NAME:
            raise NotImplementedError("MODULE_NAME must be defined.")
        self.logger = logging.getLogger(
            f"docfraud.module.{self.MODULE_NAME}"
        )

    def run(self, ctx: ForensicContext) -> ModuleScore:
        """
        Execute this module safely.

        Returns a ModuleScore — never raises.
        All exceptions are caught and returned as error scores.
        """
        start = time.perf_counter()
        self.logger.info(
            "Starting module %s for job %s", self.MODULE_NAME, ctx.job_id
        )

        try:
            skip, reason = self._should_skip(ctx)
            if skip:
                self.logger.info(
                    "Skipping module %s: %s", self.MODULE_NAME, reason
                )
                elapsed = int((time.perf_counter() - start) * 1000)
                return ModuleScore(
                    module_name=self.MODULE_NAME,
                    score=0.0,
                    confidence=0.0,
                    skipped=True,
                    skip_reason=reason,
                    processing_time_ms=elapsed,
                )

            result = self._analyze(ctx)
            elapsed = int((time.perf_counter() - start) * 1000)

            self.logger.info(
                "Module %s complete: score=%.3f confidence=%.3f time=%dms",
                self.MODULE_NAME, result.score, result.confidence, elapsed,
            )

            # Return result with updated timing
            return ModuleScore(
                module_name=result.module_name,
                score=result.score,
                confidence=result.confidence,
                findings=result.findings,
                bounding_boxes=result.bounding_boxes,
                artifact_path=result.artifact_path,
                raw_data=result.raw_data,
                processing_time_ms=elapsed,
                error=result.error,
                skipped=result.skipped,
                skip_reason=result.skip_reason,
            )

        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            self.logger.exception(
                "Module %s FAILED for job %s: %s",
                self.MODULE_NAME, ctx.job_id, exc,
            )
            return ModuleScore(
                module_name=self.MODULE_NAME,
                score=0.0,
                confidence=0.0,
                error=str(exc),
                processing_time_ms=elapsed,
            )

    def _should_skip(self, ctx: ForensicContext) -> tuple[bool, str]:
        """
        Determine whether this module should be skipped.

        Returns (should_skip: bool, reason: str)
        """
        if self.REQUIRES_PDF and not ctx.is_pdf:
            return True, "Module requires PDF input"

        if self.REQUIRES_IMAGE and not ctx.is_image and not ctx.page_images:
            return True, "No image data available"

        if ctx.image_properties:
            w, h = ctx.image_properties.width, ctx.image_properties.height
            if w < self.MIN_IMAGE_SIZE or h < self.MIN_IMAGE_SIZE:
                return (
                    True,
                    f"Image too small ({w}x{h}), minimum {self.MIN_IMAGE_SIZE}px",
                )

        return False, ""

    @abstractmethod
    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        """
        Core forensic analysis logic.

        Must return a ModuleScore.
        May raise ForensicModuleError for unrecoverable failures
        (caught and handled by run()).
        """
        ...

    def _make_score(
        self,
        score: float,
        confidence: float,
        findings: Optional[list[str]] = None,
        raw_data: Optional[dict] = None,
        artifact_path: Optional[str] = None,
        bounding_boxes: Optional[list] = None,
    ) -> ModuleScore:
        """Convenience factory for building ModuleScore objects."""
        return ModuleScore(
            module_name=self.MODULE_NAME,
            score=max(0.0, min(1.0, score)),
            confidence=max(0.0, min(1.0, confidence)),
            findings=findings or [],
            raw_data=raw_data or {},
            artifact_path=artifact_path,
            bounding_boxes=bounding_boxes or [],
        )