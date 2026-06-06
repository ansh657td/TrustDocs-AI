"""
Domain Entities — Document Fraud Detection System

Design: Rich domain model with value objects, invariants, and domain events.
All entities are immutable after construction where possible.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


# ─────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────


class RiskLevel(str, Enum):
    GENUINE = "genuine"       # 0-20
    LOW = "low"               # 21-40
    MEDIUM = "medium"         # 41-60
    HIGH = "high"             # 61-80
    CRITICAL = "critical"     # 81-100

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        if score <= 20:
            return cls.GENUINE
        elif score <= 40:
            return cls.LOW
        elif score <= 60:
            return cls.MEDIUM
        elif score <= 80:
            return cls.HIGH
        else:
            return cls.CRITICAL


class DocumentType(str, Enum):
    PDF = "pdf"
    IMAGE = "image"
    SCAN = "scan"
    MOBILE_CAPTURE = "mobile_capture"
    SCREENSHOT = "screenshot"
    COMPUTER_GENERATED = "computer_generated"
    UNKNOWN = "unknown"


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ─────────────────────────────────────────────
# Value Objects
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class FileHash:
    """SHA-256 hash of a document file."""
    value: str

    def __post_init__(self):
        if len(self.value) != 64:
            raise ValueError(f"Invalid SHA-256 hash length: {len(self.value)}")

    @classmethod
    def from_bytes(cls, data: bytes) -> "FileHash":
        return cls(value=hashlib.sha256(data).hexdigest())

    @classmethod
    def from_path(cls, path: Path) -> "FileHash":
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return cls(value=h.hexdigest())


@dataclass(frozen=True)
class BoundingBox:
    """Spatial region of interest on a document."""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    label: str = ""

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be in [0,1]: {self.confidence}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Width and height must be positive.")

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def as_dict(self) -> dict:
        return {
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "confidence": self.confidence, "label": self.label,
        }


@dataclass(frozen=True)
class ModuleScore:
    """Result from a single forensic analysis module."""
    module_name: str
    score: float          # 0.0 = clean, 1.0 = maximum fraud signal
    confidence: float     # how confident the module is in its score
    findings: list[str] = field(default_factory=list)
    bounding_boxes: list[BoundingBox] = field(default_factory=list)
    artifact_path: Optional[str] = None
    raw_data: dict = field(default_factory=dict)
    processing_time_ms: int = 0
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None

    def __post_init__(self):
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"Score must be in [0,1]: {self.score}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be in [0,1]: {self.confidence}")


@dataclass(frozen=True)
class DocumentMetadata:
    """Extracted metadata from a document."""
    creator: Optional[str] = None
    producer: Optional[str] = None
    author: Optional[str] = None
    software: Optional[str] = None
    creation_date: Optional[datetime] = None
    modification_date: Optional[datetime] = None
    title: Optional[str] = None
    subject: Optional[str] = None
    keywords: Optional[str] = None
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    raw_exif: dict = field(default_factory=dict)

    @property
    def has_editing_software_traces(self) -> bool:
        """Detect known editing tools in metadata."""
        editing_tools = {
            "photoshop", "canva", "gimp", "figma",
            "illustrator", "inkscape", "affinity",
            "paint.net", "snapseed", "lightroom",
        }
        values = [
            str(v).lower()
            for v in [self.creator, self.producer, self.software]
            if v
        ]
        return any(tool in val for tool in editing_tools for val in values)

    @property
    def has_suspicious_timestamps(self) -> bool:
        """Detect modification date before creation date."""
        if self.creation_date and self.modification_date:
            return self.modification_date < self.creation_date
        return False


@dataclass(frozen=True)
class ImageProperties:
    """Low-level properties of the image/document representation."""
    width: int
    height: int
    channels: int
    color_mode: str      # RGB, RGBA, L, CMYK
    bit_depth: int
    dpi: Optional[float]
    format: str
    has_alpha: bool
    is_progressive: bool = False
    compression_quality: Optional[int] = None


# ─────────────────────────────────────────────
# Aggregate: ForensicContext
# ─────────────────────────────────────────────


@dataclass
class ForensicContext:
    """
    Central context object passed through the entire forensic pipeline.

    Mutable aggregate that accumulates results from each module.
    Thread-local per analysis job — never shared between jobs.
    """
    job_id: str
    document_id: str
    file_path: Path
    file_hash: FileHash
    file_size: int
    mime_type: str
    original_filename: str
    document_type: DocumentType = DocumentType.UNKNOWN
    image_properties: Optional[ImageProperties] = None
    metadata: Optional[DocumentMetadata] = None
    module_scores: dict[str, ModuleScore] = field(default_factory=dict)
    page_images: list[Any] = field(default_factory=list)  # numpy arrays
    started_at: datetime = field(default_factory=datetime.utcnow)

    def add_module_result(self, result: ModuleScore) -> None:
        self.module_scores[result.module_name] = result

    def get_score(self, module_name: str) -> Optional[float]:
        r = self.module_scores.get(module_name)
        return r.score if r else None

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == "application/pdf"

    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith("image/")


# ─────────────────────────────────────────────
# Aggregate: FraudVerdict
# ─────────────────────────────────────────────


@dataclass(frozen=True)
class FraudVerdict:
    """
    Final fraud determination — immutable once produced.
    """
    document_id: str
    job_id: str
    fraud_score: float
    risk_level: RiskLevel
    edited: bool
    ai_generated: bool
    ai_assisted: bool
    tampered: bool
    genuine: bool
    confidence: float
    findings: list[str]
    heatmap_path: Optional[str]
    module_scores: dict[str, float]
    bounding_boxes: list[dict]
    recommendation: str
    metadata: dict
    processing_time_ms: int

    def to_api_response(self) -> dict:
        return {
            "document_id": self.document_id,
            "job_id": self.job_id,
            "fraud_score": round(self.fraud_score, 2),
            "risk_level": self.risk_level.value,
            "edited": self.edited,
            "ai_generated": self.ai_generated,
            "ai_assisted": self.ai_assisted,
            "tampered": self.tampered,
            "genuine": self.genuine,
            "confidence": round(self.confidence, 4),
            "findings": self.findings,
            "heatmap_path": self.heatmap_path,
            "module_scores": {k: round(v, 4) for k, v in self.module_scores.items()},
            "bounding_boxes": self.bounding_boxes,
            "recommendation": self.recommendation,
            "metadata": self.metadata,
            "processing_time_ms": self.processing_time_ms,
        }