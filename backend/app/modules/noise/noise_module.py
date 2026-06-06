"""
Noise Analysis Module

═══════════════════════════════════════════════════════════════
FORENSIC THEORY
═══════════════════════════════════════════════════════════════
Every imaging sensor introduces characteristic noise patterns — called
Photo Response Non-Uniformity (PRNU). This fingerprint is as unique as
a serial number. When an image region is copy-pasted from another source,
it carries a DIFFERENT sensor noise signature than the host image.

We approximate PRNU consistency analysis by:
1. Extracting noise residual via wavelet denoising
2. Analyzing statistical consistency across spatial regions
3. Detecting localized noise anomalies (paste regions)

Additionally, natural images follow specific noise distributions:
- Camera images: spatially correlated Gaussian + Poisson shot noise
- Scanned docs: structured CCD readout noise
- AI-generated images: unnaturally smooth or periodic noise
- Edited regions: noise discontinuity at splice boundary

═══════════════════════════════════════════════════════════════
ALGORITHM
═══════════════════════════════════════════════════════════════
1. Denoise image with wavelet denoising (BM3D approximation via skimage)
2. Compute noise residual: R = I - Denoise(I)
3. Analyze spatial statistics of R in overlapping patches
4. Detect blocks with anomalous noise variance or distribution
5. Compute inter-block noise correlation matrix
6. Flag regions with low correlation to global noise pattern

═══════════════════════════════════════════════════════════════
LIMITATIONS
═══════════════════════════════════════════════════════════════
- True PRNU requires 50+ images from same device — not feasible here
- We use a single-image approximation (less accurate)
- Highly compressed images lose noise residual information
- AI-generated image detection via noise is effective but not definitive

═══════════════════════════════════════════════════════════════
FALSE POSITIVE RISKS
═══════════════════════════════════════════════════════════════
HIGH: Low-texture regions (sky, walls) naturally have low noise
MEDIUM: JPEG compression smears noise making residuals unreliable
LOW: High-frequency texture areas — noise analysis is reliable

═══════════════════════════════════════════════════════════════
COMPUTATIONAL COMPLEXITY
═══════════════════════════════════════════════════════════════
O(W*H*log(W*H)) for wavelet denoising
Patch analysis: O(W*H/P²) for patch size P
Typical: 200-800ms for HD document
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from app.core.config import settings
from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.module.noise")


class NoiseAnalysisModule(ForensicModule):
    """
    Sensor noise residual analysis for detecting spliced/pasted regions.
    """

    MODULE_NAME = "noise"
    WEIGHT = 0.12
    VERSION = "1.0.0"
    MIN_IMAGE_SIZE = 128
    REQUIRES_IMAGE = True

    def __init__(self, patch_size: int | None = None):
        super().__init__()
        self.patch_size = patch_size or settings.noise_patch_size

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0, findings=["No image data"])

        image = ctx.page_images[0]
        gray = self._to_grayscale(image)

        import cv2

        MAX_SIDE = 1200

        h, w = gray.shape

        if max(h, w) > MAX_SIDE:
            scale = MAX_SIDE / max(h, w)

            gray = cv2.resize(
                gray,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA
            )

        noise_residual = self._extract_noise_residual(gray)
        patch_stats = self._analyze_patches(noise_residual)
        score, confidence, findings, bboxes = self._evaluate(
            noise_residual, patch_stats, ctx.job_id
        )

        artifact_path = self._save_noise_map(noise_residual, ctx.job_id)

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data=patch_stats,
            artifact_path=artifact_path,
            bounding_boxes=bboxes,
        )

    def _to_grayscale(self, image: np.ndarray) -> np.ndarray:
        """Convert RGB to grayscale, normalized to [0, 1]."""
        if len(image.shape) == 3:
            gray = (
                0.299 * image[:, :, 0]
                + 0.587 * image[:, :, 1]
                + 0.114 * image[:, :, 2]
            )
        else:
            gray = image.astype(np.float64)
        return (gray / 255.0).astype(np.float64)

    def _extract_noise_residual(self, gray: np.ndarray) -> np.ndarray:
        """
        Extract noise residual using wavelet denoising.

        Noise residual = Original - Denoised

        The residual contains sensor noise, compression artifacts,
        and any inconsistencies introduced by editing.
        """
        try:
            from skimage.restoration import denoise_wavelet, estimate_sigma

            sigma_est = estimate_sigma(gray, average_sigmas=True)
            denoised = denoise_wavelet(
                gray,
                sigma=sigma_est,
                mode="soft",
                wavelet_levels=4,
                wavelet="db8",
                rescale_sigma=True,
            )
            residual = gray - denoised
            return residual.astype(np.float64)

        except Exception as e:
            logger.exception(
                "Noise extraction failed: %s",
                e
            )
            logger.exception(
                "Full skimage error:"
            )
            raise
            return self._gaussian_noise_residual(gray)





    def _gaussian_noise_residual(self, gray: np.ndarray) -> np.ndarray:
        """Fallback: Gaussian blur subtraction as noise extraction."""
        from scipy.ndimage import gaussian_filter
        smoothed = gaussian_filter(gray, sigma=2.0)
        return gray - smoothed

    def _analyze_patches(self, residual: np.ndarray) -> dict:
        """
        Divide residual map into patches; compute per-patch statistics.
        Detect outlier patches (anomalous noise).
        """
        h, w = residual.shape
        p = self.patch_size

        # Compute stats per patch
        patch_variances = []
        patch_means = []
        patch_coords = []

        for y in range(0, h - p, p):
            for x in range(0, w - p, p):
                patch = residual[y : y + p, x : x + p]
                patch_variances.append(float(np.var(patch)))
                patch_means.append(float(np.mean(patch)))
                patch_coords.append((x, y))

        if not patch_variances:
            return {
                "global_mean": 0.0,
                "global_std": 0.0,
                "patch_variance_std": 0.0,
                "anomalous_patch_count": 0,
                "anomalous_patch_ratio": 0.0,
                "patch_coords": [],
                "patch_variances": [],
            }

        variances = np.array(patch_variances)
        global_mean_var = float(variances.mean())
        global_std_var = float(variances.std())

        # Anomalous = variance > mean + 2.5*std  OR  < mean - 2.5*std
        threshold_high = global_mean_var + 2.5 * global_std_var
        threshold_low = max(0.0, global_mean_var - 2.5 * global_std_var)

        anomalous_indices = np.where(
            (variances > threshold_high) | (variances < threshold_low)
        )[0]

        return {
            "global_mean_var": global_mean_var,
            "global_std_var": global_std_var,
            "patch_variance_std": float(global_std_var),
            "anomalous_patch_count": int(len(anomalous_indices)),
            "anomalous_patch_ratio": float(len(anomalous_indices) / max(1, len(variances))),
            "patch_coords": [patch_coords[i] for i in anomalous_indices],
            "patch_variances": [patch_variances[i] for i in anomalous_indices],
        }

    def _evaluate(
        self,
        residual: np.ndarray,
        stats: dict,
        job_id: str,
    ) -> tuple[float, float, list[str], list[BoundingBox]]:
        findings: list[str] = []
        bboxes: list[BoundingBox] = []

        ratio = stats.get("anomalous_patch_ratio", 0.0)
        count = stats.get("anomalous_patch_count", 0)
        patch_std = stats.get("patch_variance_std", 0.0)

        # Noise uniformity score: high variance inconsistency = high fraud
        # ratio: 0% anomalous = clean, 30%+ = definite issue
        ratio_score = min(ratio / 0.30, 1.0)
        std_score = min(patch_std / 0.01, 1.0)

        # AI-generated images have unnaturally low noise variance
        global_mean_var = stats.get("global_mean_var", 0.0)
        too_clean = global_mean_var < 1e-5
        if too_clean:
            findings.append(
                "Extremely low noise residual — consistent with AI/synthetic generation"
            )

        score = 0.60 * ratio_score + 0.40 * std_score
        if too_clean:
            score = max(score, 0.55)

        if ratio > 0.05:
            findings.append(
                f"{count} patches ({ratio*100:.1f}%) show noise anomalies"
            )
        if patch_std > 0.005:
            findings.append("Spatial noise variance inconsistency detected")

        # Build bounding boxes for anomalous patches
        p = self.patch_size
        for (x, y), var in zip(
            stats.get("patch_coords", []),
            stats.get("patch_variances", []),
        ):
            conf = min(abs(var - stats["global_mean_var"]) / (stats["global_std_var"] + 1e-8) / 3.0, 1.0)
            if conf > 0.3:
                bboxes.append(
                    BoundingBox(x=x, y=y, width=p, height=p, confidence=conf, label="noise_anomaly")
                )

        confidence = max(
            0.5,
            min(0.5 + ratio * 2.0, 0.9)
        )
        return score, confidence, findings, bboxes[:10]

    def _save_noise_map(self, residual: np.ndarray, job_id: str) -> Optional[str]:
        """Save amplified noise residual as PNG artifact."""
        try:
            out_dir = settings.heatmap_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{job_id}_noise.png"
            normalized = np.clip(
                (residual - residual.min()) / (residual.max() - residual.min() + 1e-8) * 255,
                0, 255
            ).astype(np.uint8)
            Image.fromarray(normalized, mode="L").save(str(out_path))
            return str(out_path)
        except Exception as e:
            logger.warning("Failed to save noise map: %s", e)
            return None