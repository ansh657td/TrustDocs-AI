"""
Edge Artifact Detection Module

═══════════════════════════════════════════════════════════════
FORENSIC THEORY
═══════════════════════════════════════════════════════════════
When content is pasted into an image, the boundary between the
pasted region and the host image rarely blends perfectly. The
splice boundary manifests as:

1. Abnormal gradient discontinuities (sharp paste edges)
2. Double-edge artifacts from clumsy blending
3. Halo effects from feathering/soft-edge tools
4. Anti-aliasing inconsistency (pasted content from different DPI)
5. Mismatched edge sharpness across the image

Natural images have edge distributions that follow specific
statistical laws (Weibull distribution of gradient magnitudes).
Tampering disrupts this, creating outlier edge configurations.

═══════════════════════════════════════════════════════════════
ALGORITHM
═══════════════════════════════════════════════════════════════
1. Compute image gradient magnitudes (Canny + Sobel)
2. Detect abnormal gradient discontinuities
3. Analyze edge orientation histogram for unnatural peaks
4. Compute edge density map in blocks
5. Detect blocks with statistically anomalous edge density
6. Look for double-edge patterns (parallel edges ~2-5px apart)

═══════════════════════════════════════════════════════════════
LIMITATIONS
═══════════════════════════════════════════════════════════════
- Text documents always have strong edges — not indicative of tampering
- Good blending tools can remove paste boundaries
- Low-quality images: edge detection unreliable

═══════════════════════════════════════════════════════════════
FALSE POSITIVE RISKS
═══════════════════════════════════════════════════════════════
HIGH: Documents with tables, boxes, borders, watermarks
MEDIUM: Scanned documents with ink bleed artifacts
LOW: Clean photographic images
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.module.edge")


class EdgeArtifactModule(ForensicModule):
    MODULE_NAME = "edge"
    WEIGHT = 0.08
    VERSION = "1.0.0"
    MIN_IMAGE_SIZE = 64
    REQUIRES_IMAGE = True

    BLOCK_SIZE = 64
    CANNY_LOW = 50
    CANNY_HIGH = 150

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        try:
            import cv2
        except ImportError:
            return self._make_score(0.0, 0.0, findings=["OpenCV unavailable"])

        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

        # Canny edges
        edges = cv2.Canny(gray, self.CANNY_LOW, self.CANNY_HIGH)

        # Sobel gradients
        sobelx = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
        magnitude = np.sqrt(sobelx ** 2 + sobely ** 2)
        orientation = np.arctan2(sobely, sobelx)

        block_stats = self._analyze_edge_blocks(edges, magnitude)
        double_edge_score = self._detect_double_edges(edges)
        orientation_score = self._analyze_orientation_distribution(orientation, edges)

        score, confidence, findings, bboxes = self._evaluate(
            block_stats, double_edge_score, orientation_score
        )

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data={
                "double_edge_score": double_edge_score,
                "orientation_score": orientation_score,
                "anomalous_blocks": block_stats["anomalous_count"],
                "total_blocks": block_stats["total"],
            },
            bounding_boxes=bboxes,
        )

    def _analyze_edge_blocks(
        self, edges: np.ndarray, magnitude: np.ndarray
    ) -> dict:
        """Compute per-block edge density and detect anomalous blocks."""
        h, w = edges.shape
        p = self.BLOCK_SIZE

        densities = []
        mag_means = []
        coords = []

        for y in range(0, h - p, p):
            for x in range(0, w - p, p):
                block_edges = edges[y : y + p, x : x + p]
                block_mag = magnitude[y : y + p, x : x + p]
                density = float(block_edges.sum()) / (p * p * 255)
                mag_mean = float(block_mag.mean())
                densities.append(density)
                mag_means.append(mag_mean)
                coords.append((x, y))

        if not densities:
            return {"anomalous_count": 0, "total": 0, "anomalous_coords": []}

        dens = np.array(densities)
        mean_d = dens.mean()
        std_d = dens.std()

        anomalous = [
            coords[i] for i, d in enumerate(densities)
            if abs(d - mean_d) > 2.5 * std_d
        ]

        return {
            "anomalous_count": len(anomalous),
            "total": len(densities),
            "anomalous_coords": anomalous,
            "mean_density": float(mean_d),
            "std_density": float(std_d),
        }

    def _detect_double_edges(self, edges: np.ndarray) -> float:
        """
        Detect parallel/double edge patterns (hallmark of paste boundaries).

        Method: Horizontal/vertical dilation + XOR to find doubled edges.
        Score 0=none, 1=many double edges.
        """
        try:
            from scipy.ndimage import binary_dilation, binary_erosion

            # Look for two parallel edges 2-4 pixels apart
            dilated = binary_dilation(edges > 0, iterations=3)
            eroded = binary_erosion(edges > 0, iterations=1)
            double_region = dilated & ~eroded & (edges == 0)
            double_ratio = float(double_region.sum()) / max(1, (edges > 0).sum())
            return min(double_ratio * 5.0, 1.0)
        except Exception:
            return 0.0

    def _analyze_orientation_distribution(
        self, orientation: np.ndarray, edges: np.ndarray
    ) -> float:
        """
        Analyze gradient orientation histogram for unnatural peaks.

        Natural images have smooth orientation histograms.
        Sharp isolated peaks suggest artificial straight-line paste edges.
        """
        edge_mask = edges > 0
        if edge_mask.sum() < 100:
            return 0.0

        angles = orientation[edge_mask]
        hist, _ = np.histogram(angles, bins=36, range=(-np.pi, np.pi))
        hist_norm = hist / (hist.sum() + 1e-8)

        # Kurtosis of histogram — high kurtosis = unnaturally peaked
        mean = hist_norm.mean()
        std = hist_norm.std()
        if std < 1e-8:
            return 0.0

        excess_kurtosis = float(
            np.mean(((hist_norm - mean) / std) ** 4) - 3.0
        )

        # Normalize: kurtosis > 5 is suspicious
        return min(max(excess_kurtosis, 0.0) / 10.0, 1.0)

    def _evaluate(
        self,
        block_stats: dict,
        double_edge_score: float,
        orientation_score: float,
    ) -> tuple[float, float, list[str], list[BoundingBox]]:
        findings: list[str] = []
        bboxes: list[BoundingBox] = []

        total = block_stats.get("total", 1)
        anomalous = block_stats.get("anomalous_count", 0)
        anomaly_ratio = anomalous / max(total, 1)

        block_score = min(anomaly_ratio / 0.20, 1.0)
        score = (
            0.50 * block_score
            + 0.30 * double_edge_score
            + 0.20 * orientation_score
        )

        if anomaly_ratio > 0.05:
            findings.append(
                f"{anomalous}/{total} blocks have anomalous edge density"
            )
        if double_edge_score > 0.3:
            findings.append(
                f"Double-edge artifacts detected (score={double_edge_score:.2f})"
            )
        if orientation_score > 0.4:
            findings.append(
                "Abnormal gradient orientation distribution — possible paste boundary"
            )

        # Bounding boxes for anomalous edge blocks
        p = self.BLOCK_SIZE
        for x, y in block_stats.get("anomalous_coords", [])[:8]:
            bboxes.append(BoundingBox(x=x, y=y, width=p, height=p, confidence=0.6, label="edge_anomaly"))

        confidence = 0.45 + min(anomaly_ratio * 2.0, 0.45)
        return score, confidence, findings, bboxes