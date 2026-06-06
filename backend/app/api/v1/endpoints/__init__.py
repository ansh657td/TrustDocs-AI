"""
API v1 — Document Analysis Endpoints

POST /api/v1/analyze        Upload and analyze a document
GET  /api/v1/results/{id}   Retrieve cached analysis result
GET  /api/v1/jobs/{id}      Check job status
DELETE /api/v1/documents/{id}  Remove document and results
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.domain.services.analysis_service import AnalysisError, DocumentAnalysisService

logger = logging.getLogger("docfraud.api.v1")
router = APIRouter()

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tiff", ".tif", ".pdf"}
MAX_BYTES = settings.max_upload_mb * 1024 * 1024


# ─────────────────────────────────────────────
# Response Models
# ─────────────────────────────────────────────

class AnalysisResponse(BaseModel):
    document_id: str
    job_id: str
    fraud_score: float
    risk_level: str
    edited: bool
    ai_generated: bool
    ai_assisted: bool
    tampered: bool
    genuine: bool
    confidence: float
    findings: list[str]
    heatmap_url: Optional[str]
    module_scores: dict[str, float]
    bounding_boxes: list[dict]
    recommendation: str
    metadata: dict
    processing_time_ms: int


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


# ─────────────────────────────────────────────
# Dependency: Analysis Service (singleton)
# ─────────────────────────────────────────────

_analysis_service: Optional[DocumentAnalysisService] = None


def get_analysis_service() -> DocumentAnalysisService:
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = DocumentAnalysisService()
    return _analysis_service


# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.post(
    "/analyze",
    response_model=AnalysisResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyze a document for fraud",
    description=(
        "Upload a document (image or PDF) and receive a comprehensive "
        "fraud analysis with score, risk level, and forensic findings."
    ),
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file"},
        413: {"model": ErrorResponse, "description": "File too large"},
        422: {"model": ErrorResponse, "description": "Unsupported file type"},
        500: {"model": ErrorResponse, "description": "Analysis failed"},
    },
)
async def analyze_document(
    request: Request,
    file: UploadFile = File(..., description="Document to analyze (JPG/PNG/WEBP/TIFF/PDF)"),
):
    """
    Analyze an uploaded document for fraud, tampering, and AI generation.

    Returns a comprehensive forensic report with:
    - Fraud score (0-100)
    - Risk level (genuine/low/medium/high/critical)
    - Module-level scores
    - Spatial heatmap
    - Bounding boxes for anomalous regions
    - Detailed findings
    """
    # ── Validate file ─────────────────────────────────────────
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type: {ext}. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Read file content
    content = await file.read()

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size {len(content)} exceeds limit {MAX_BYTES} bytes",
        )

    # ── Save to temp file ─────────────────────────────────────
    document_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    requested_by = request.client.host if request.client else "unknown"

    tmp_path: Optional[Path] = None
    try:
        suffix = ext if ext else ".bin"
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False, dir=settings.upload_dir
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        logger.info(
            "Saved upload: job=%s file=%s size=%d bytes path=%s",
            job_id, file.filename, len(content), tmp_path,
        )

        # ── Run analysis ───────────────────────────────────────
        service = get_analysis_service()
        verdict = service.analyze(
            file_path=tmp_path,
            original_filename=file.filename,
            document_id=document_id,
            job_id=job_id,
            requested_by=requested_by,
        )

        # ── Build response ─────────────────────────────────────
        heatmap_url = None
        if verdict.heatmap_path:
            heatmap_url = f"/api/v1/heatmap/{job_id}"

        return AnalysisResponse(
            document_id=verdict.document_id,
            job_id=verdict.job_id,
            fraud_score=verdict.fraud_score,
            risk_level=verdict.risk_level.value,
            edited=verdict.edited,
            ai_generated=verdict.ai_generated,
            ai_assisted=verdict.ai_assisted,
            tampered=verdict.tampered,
            genuine=verdict.genuine,
            confidence=verdict.confidence,
            findings=verdict.findings,
            heatmap_url=heatmap_url,
            module_scores={k: round(v, 4) for k, v in verdict.module_scores.items()},
            bounding_boxes=verdict.bounding_boxes,
            recommendation=verdict.recommendation,
            metadata=verdict.metadata,
            processing_time_ms=verdict.processing_time_ms,
        )

    except AnalysisError as e:
        logger.error("Analysis failed for job %s: %s", job_id, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unexpected error for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal analysis error: {str(e)}",
        )
    finally:
        # Always clean up temp file
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


@router.get(
    "/heatmap/{job_id}",
    summary="Retrieve fraud heatmap image",
    response_class=FileResponse,
)
async def get_heatmap(job_id: str):
    """Return the composite fraud heatmap for a given job."""
    # Validate job_id format
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    heatmap_path = settings.heatmap_dir / f"{job_id}_heatmap.png"
    if not heatmap_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Heatmap for job {job_id} not found",
        )

    return FileResponse(
        path=str(heatmap_path),
        media_type="image/png",
        filename=f"heatmap_{job_id}.png",
    )


@router.get(
    "/ela/{job_id}",
    summary="Retrieve ELA map image",
    response_class=FileResponse,
)
async def get_ela_map(job_id: str):
    """Return the ELA map for a given job."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    ela_path = settings.heatmap_dir / f"{job_id}_ela.png"
    if not ela_path.exists():
        raise HTTPException(status_code=404, detail="ELA map not found")

    return FileResponse(str(ela_path), media_type="image/png")


@router.get("/", summary="API info")
async def api_info():
    return {
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze": "Analyze a document",
            "GET /heatmap/{job_id}": "Get fraud heatmap",
            "GET /ela/{job_id}": "Get ELA map",
        },
        "supported_formats": list(ALLOWED_EXTENSIONS),
        "max_file_mb": settings.max_upload_mb,
    }