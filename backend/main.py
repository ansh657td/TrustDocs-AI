"""
FastAPI Application Entry Point — Document Fraud Detection System
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import router as v1_router
from app.core.config import settings
# from app.infrastructure.database.models import create_all_tables

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("docfraud.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup + shutdown."""
    logger.info("Starting Document Fraud Detection System v%s", settings.app_version)
    settings.ensure_dirs()
    # create_all_tables(settings.database_url)
    # logger.info("Database initialized at %s", settings.database_url)
    yield
    logger.info("Shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Production-grade document fraud detection using multi-layer forensic analysis.",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── Middleware ─────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Request ID + latency logging
    @app.middleware("http")
    async def request_logger(request: Request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()
        request.state.request_id = request_id

        response = await call_next(request)

        elapsed = int((time.perf_counter() - start) * 1000)
        logger.info(
            "REQ %s %s %s → %d [%dms]",
            request_id, request.method, request.url.path,
            response.status_code, elapsed,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed}ms"
        return response

    # ── Exception handlers ────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)},
        )

    # ── Routes ────────────────────────────────────────────────
    app.include_router(v1_router, prefix="/api/v1")

    @app.get("/health", tags=["System"])
    async def health_check():
        return {
            "status": "healthy",
            "version": settings.app_version,
            "service": settings.app_name,
        }

    @app.get("/", tags=["System"])
    async def root():
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
        }

    return app


app = create_app()