"""
Application Configuration — Pydantic Settings
Reads from environment variables and .env file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "Document Fraud Detection System"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "sqlite:///./docfraud.db"

    # Storage
    upload_dir: Path = Path("./uploads")
    output_dir: Path = Path("./outputs")
    heatmap_dir: Path = Path("./outputs/heatmaps")
    max_upload_mb: int = 50

    # Security
    api_key: Optional[str] = None
    rate_limit_per_minute: int = 60

    # Forensic Pipeline
    ela_quality: int = 75       # JPEG recompression quality for ELA
    ela_amplification: float = 10.0
    ela_threshold: float = 0.15

    noise_patch_size: int = 96
    copymove_min_keypoints: int = 50
    frequency_fft_threshold: float = 0.3

    # AI Detection
    ai_detection_threshold: float = 0.5
    gan_detection_threshold: float = 0.5

    # Score Weights (must sum to 1.0)
    weight_ela: float = 0.20
    weight_noise: float = 0.12
    weight_copymove: float = 0.10
    weight_edge: float = 0.08
    weight_color: float = 0.08
    weight_font: float = 0.10
    weight_ai: float = 0.15
    weight_gan: float = 0.07
    weight_frequency: float = 0.05
    weight_layout: float = 0.05

    # Thresholds
    edited_threshold: float = 0.40
    ai_generated_threshold: float = 0.50
    ai_assisted_threshold: float = 0.35
    tampered_threshold: float = 0.45

    # Performance
    max_workers: int = 4
    cache_results: bool = True
    cache_ttl_hours: int = 24

    # Worker
    worker_timeout_seconds: int = 120

    @property
    def weight_sum(self) -> float:
        return sum([
            self.weight_ela, self.weight_noise, self.weight_copymove,
            self.weight_edge, self.weight_color, self.weight_font,
            self.weight_ai, self.weight_gan, self.weight_frequency,
            self.weight_layout,
        ])

    def ensure_dirs(self) -> None:
        for d in [self.upload_dir, self.output_dir, self.heatmap_dir]:
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()