"""
Database Schema - Document Fraud Detection System

Design principles:
- Normalized schema for auditability
- JSONB for flexible module result storage
- Immutable audit trail
- Soft deletes
- Full indexing for query performance
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base model with audit fields."""

    __abstract__ = True

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class RiskLevel(str, PyEnum):
    GENUINE = "genuine"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DocumentType(str, PyEnum):
    PDF = "pdf"
    IMAGE = "image"
    SCAN = "scan"
    MOBILE_CAPTURE = "mobile_capture"
    SCREENSHOT = "screenshot"
    COMPUTER_GENERATED = "computer_generated"


class AnalysisStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    QUEUED = "queued"


# ─────────────────────────────────────────────
# Core Tables
# ─────────────────────────────────────────────


class Document(Base):
    """Uploaded document record - immutable after creation."""

    __tablename__ = "documents"

    filename = Column(String(512), nullable=False)
    original_filename = Column(String(512), nullable=False)
    file_size = Column(Integer, nullable=False)
    mime_type = Column(String(128), nullable=False)
    sha256_hash = Column(String(64), nullable=False, index=True, unique=True)
    storage_path = Column(String(1024), nullable=False)
    document_type = Column(String(32), nullable=True)
    page_count = Column(Integer, default=1)
    width_px = Column(Integer, nullable=True)
    height_px = Column(Integer, nullable=True)
    color_mode = Column(String(16), nullable=True)
    dpi = Column(Float, nullable=True)
    is_deleted = Column(Boolean, default=False, nullable=False)

    analyses = relationship("AnalysisJob", back_populates="document")

    __table_args__ = (
        Index("ix_documents_sha256", "sha256_hash"),
        Index("ix_documents_mime", "mime_type"),
    )


class AnalysisJob(Base):
    """Tracks lifecycle of a forensic analysis run."""

    __tablename__ = "analysis_jobs"

    document_id = Column(String(36), ForeignKey("documents.id"), nullable=False)
    status = Column(String(32), default=AnalysisStatus.PENDING, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    processing_time_ms = Column(Integer, nullable=True)
    pipeline_version = Column(String(32), default="1.0.0", nullable=False)
    requested_by = Column(String(128), nullable=True)  # IP or user identifier

    document = relationship("Document", back_populates="analyses")
    result = relationship("AnalysisResult", back_populates="job", uselist=False)
    module_results = relationship("ModuleResult", back_populates="job")

    __table_args__ = (
        Index("ix_jobs_document", "document_id"),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created", "created_at"),
    )


class AnalysisResult(Base):
    """Final aggregated fraud verdict for a job."""

    __tablename__ = "analysis_results"

    job_id = Column(String(36), ForeignKey("analysis_jobs.id"), nullable=False, unique=True)
    fraud_score = Column(Float, nullable=False)
    risk_level = Column(String(32), nullable=False)
    edited = Column(Boolean, nullable=False)
    ai_generated = Column(Boolean, nullable=False)
    ai_assisted = Column(Boolean, nullable=False)
    tampered = Column(Boolean, nullable=False)
    genuine = Column(Boolean, nullable=False)
    confidence = Column(Float, nullable=False)
    recommendation = Column(Text, nullable=True)
    heatmap_path = Column(String(1024), nullable=True)
    findings = Column(JSON, default=list)
    module_scores = Column(JSON, default=dict)
    metadata_extracted = Column(JSON, default=dict)
    bounding_boxes = Column(JSON, default=list)

    job = relationship("AnalysisJob", back_populates="result")

    __table_args__ = (
        Index("ix_results_job", "job_id"),
        Index("ix_results_risk", "risk_level"),
        Index("ix_results_score", "fraud_score"),
    )


class ModuleResult(Base):
    """Per-module forensic analysis output."""

    __tablename__ = "module_results"

    job_id = Column(String(36), ForeignKey("analysis_jobs.id"), nullable=False)
    module_name = Column(String(64), nullable=False)
    score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    processing_time_ms = Column(Integer, nullable=True)
    findings = Column(JSON, default=list)
    raw_data = Column(JSON, default=dict)
    artifact_path = Column(String(1024), nullable=True)  # ELA map, noise map etc.
    error = Column(Text, nullable=True)
    skipped = Column(Boolean, default=False)
    skip_reason = Column(Text, nullable=True)

    job = relationship("AnalysisJob", back_populates="module_results")

    __table_args__ = (
        Index("ix_module_job", "job_id"),
        Index("ix_module_name", "module_name"),
        Index("ix_module_job_name", "job_id", "module_name", unique=True),
    )


class AuditLog(Base):
    """Immutable audit trail for all API interactions."""

    __tablename__ = "audit_logs"

    event_type = Column(String(64), nullable=False)
    entity_type = Column(String(64), nullable=True)
    entity_id = Column(String(36), nullable=True)
    actor = Column(String(128), nullable=True)
    ip_address = Column(String(45), nullable=True)
    payload = Column(JSON, default=dict)
    outcome = Column(String(32), nullable=True)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_event", "event_type"),
        Index("ix_audit_created", "created_at"),
    )


class DocumentCache(Base):
    """Cache prior analysis results by document hash."""

    __tablename__ = "document_cache"

    sha256_hash = Column(String(64), nullable=False, unique=True, index=True)
    result_id = Column(String(36), ForeignKey("analysis_results.id"), nullable=False)
    expires_at = Column(DateTime, nullable=True)
    hit_count = Column(Integer, default=0)

    __table_args__ = (Index("ix_cache_hash", "sha256_hash"),)


# ─────────────────────────────────────────────
# Schema Creation Utility
# ─────────────────────────────────────────────


# def create_all_tables(engine_url: str = "sqlite:///./docfraud.db") -> None:
#     """Create all tables in the database."""
#     engine = create_engine(engine_url, echo=False)
#     Base.metadata.create_all(bind=engine)
#     return engine