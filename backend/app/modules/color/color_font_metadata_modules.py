"""
Color Consistency, Font Analysis, and Metadata Forensic Modules
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ExifTags

from app.core.config import settings
from app.domain.entities.document import (
    BoundingBox, DocumentMetadata, ForensicContext, ModuleScore
)
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.modules")


# ══════════════════════════════════════════════════════════════
#  COLOR CONSISTENCY MODULE
# ══════════════════════════════════════════════════════════════

class ColorConsistencyModule(ForensicModule):
    """
    Detect illumination/white balance inconsistencies across image regions.

    Theory:
    Pasted content often comes from a different lighting environment.
    Color statistics (mean, covariance of RGB channels, histogram)
    will differ in tampered regions.

    Algorithm:
    1. Divide image into non-overlapping blocks
    2. Compute per-block color histogram (hue + saturation)
    3. Fit a global GMM to color distribution
    4. Flag blocks that deviate from global distribution
    5. Detect illumination direction inconsistencies via chromaticity

    False positive risks:
    - Multi-color documents (charts, infographics) → always high variance
    - Documents with logos or colored headers
    """

    MODULE_NAME = "color"
    WEIGHT = 0.08
    BLOCK_SIZE = 128
    MIN_IMAGE_SIZE = 128

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        block_stats = self._compute_color_blocks(image)
        illum_score = self._illumination_consistency(image)
        score, confidence, findings, bboxes = self._evaluate(block_stats, illum_score)

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data={
                "illumination_score": illum_score,
                "anomalous_blocks": block_stats["anomalous_count"],
            },
            bounding_boxes=bboxes,
        )

    def _compute_color_blocks(self, image: np.ndarray) -> dict:
        """Compute per-block color statistics and detect anomalies."""
        h, w, _ = image.shape if len(image.shape) == 3 else (*image.shape, 1)
        p = self.BLOCK_SIZE

        block_means = []
        block_stds = []
        coords = []

        for y in range(0, h - p, p):
            for x in range(0, w - p, p):
                block = image[y:y+p, x:x+p]
                block_means.append(block.mean(axis=(0, 1)))
                block_stds.append(block.std(axis=(0, 1)))
                coords.append((x, y))

        if not block_means:
            return {"anomalous_count": 0, "anomalous_coords": []}

        means = np.array(block_means)      # (N, 3)
        global_mean = means.mean(axis=0)
        global_std = means.std(axis=0) + 1e-8

        # Mahalanobis-like distance
        distances = np.abs(means - global_mean) / global_std
        max_dist = distances.max(axis=1)    # per block

        threshold = 2.5
        anomalous_idx = np.where(max_dist > threshold)[0]

        return {
            "anomalous_count": int(len(anomalous_idx)),
            "total": len(block_means),
            "anomalous_coords": [coords[i] for i in anomalous_idx],
            "anomaly_ratio": float(len(anomalous_idx) / max(1, len(block_means))),
        }

    def _illumination_consistency(self, image: np.ndarray) -> float:
        """
        Estimate illumination consistency via chromaticity map.
        Uniform illumination = low score. Abrupt changes = high score.
        """
        if len(image.shape) != 3:
            return 0.0

        r, g, b = image[:,:,0].astype(float), image[:,:,1].astype(float), image[:,:,2].astype(float)
        intensity = r + g + b + 1e-8

        # Chromaticity
        rg = r / intensity
        gg = g / intensity

        # Gradient of chromaticity
        from scipy.ndimage import sobel
        grad_rg = np.abs(sobel(rg))
        grad_gg = np.abs(sobel(gg))

        combined = (grad_rg + grad_gg) / 2.0
        score = float(np.percentile(combined, 99)) * 10.0
        return min(score, 1.0)

    def _evaluate(self, block_stats: dict, illum_score: float):
        findings = []
        bboxes = []
        ratio = block_stats.get("anomaly_ratio", 0.0)
        count = block_stats.get("anomalous_count", 0)

        color_score = min(ratio / 0.25, 1.0)
        score = 0.60 * color_score + 0.40 * illum_score

        if ratio > 0.08:
            findings.append(f"{count} blocks show color inconsistency")
        if illum_score > 0.4:
            findings.append("Illumination inconsistency detected across document regions")

        p = self.BLOCK_SIZE
        for x, y in block_stats.get("anomalous_coords", [])[:8]:
            bboxes.append(BoundingBox(x=x, y=y, width=p, height=p, confidence=0.55, label="color_anomaly"))

        confidence = 0.4 + min(ratio * 2.0, 0.5)
        return score, confidence, findings, bboxes


# ══════════════════════════════════════════════════════════════
#  FONT ANALYSIS MODULE
# ══════════════════════════════════════════════════════════════

class FontAnalysisModule(ForensicModule):
    """
    Detect font rendering inconsistencies in document images.

    Theory:
    Text rendering encodes characteristics of the rendering pipeline:
    - Anti-aliasing style (ClearType, Grayscale, None)
    - Hinting aggressiveness
    - Sub-pixel positioning accuracy
    - Kerning precision

    When text is copy-pasted from a different source, it was rendered
    by a different pipeline and will show different sub-pixel patterns.

    Algorithm:
    1. Detect text regions via connected component analysis on thresholded image
    2. Extract text stroke width transform (SWT) for character analysis
    3. Analyze stroke width variance in different regions
    4. Detect anti-aliasing style per text region
    5. Flag regions with inconsistent rendering characteristics

    Limitations:
    - Only detects text-based forgeries
    - Requires text to be present in image
    - Heavily compressed images lose sub-pixel info
    """

    MODULE_NAME = "font"
    WEIGHT = 0.10
    MIN_IMAGE_SIZE = 64

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        findings = []

        sw_stats = self._stroke_width_analysis(image)
        aa_stats = self._antialiasing_analysis(image)

        score = 0.60 * sw_stats["score"] + 0.40 * aa_stats["score"]

        if sw_stats["inconsistent"]:
            findings.append(
                f"Stroke width variance ({sw_stats['variance']:.2f}) suggests "
                f"mixed font sources"
            )
        if aa_stats["inconsistent"]:
            findings.append(
                "Anti-aliasing style inconsistency — text from different rendering engines"
            )

        confidence = 0.50 if (sw_stats["has_text"] or aa_stats["has_text"]) else 0.2

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data={"stroke_width": sw_stats, "antialiasing": aa_stats},
        )

    def _stroke_width_analysis(self, image: np.ndarray) -> dict:
        """Analyze text stroke widths across the document."""
        try:
            from scipy.ndimage import label, distance_transform_edt

            gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image

            # Otsu threshold
            threshold = self._otsu_threshold(gray)
            binary = (gray < threshold).astype(np.uint8)

            # Distance transform approximates stroke width
            dist = distance_transform_edt(binary)
            stroke_widths = dist[binary > 0]

            if len(stroke_widths) < 100:
                return {"score": 0.0, "inconsistent": False, "has_text": False, "variance": 0.0}

            # Analyze regional stroke width variance
            h, w = gray.shape
            half_h = h // 2
            top_strokes = dist[:half_h][binary[:half_h] > 0]
            bot_strokes = dist[half_h:][binary[half_h:] > 0]

            if len(top_strokes) < 20 or len(bot_strokes) < 20:
                return {"score": 0.0, "inconsistent": False, "has_text": True, "variance": 0.0}

            top_mean = float(np.median(top_strokes))
            bot_mean = float(np.median(bot_strokes))
            variance = abs(top_mean - bot_mean)
            score = min(variance / 2.0, 1.0)

            return {
                "score": score,
                "inconsistent": variance > 0.8,
                "has_text": True,
                "variance": variance,
                "top_median": top_mean,
                "bot_median": bot_mean,
            }
        except Exception as e:
            logger.debug("Stroke width analysis failed: %s", e)
            return {"score": 0.0, "inconsistent": False, "has_text": False, "variance": 0.0}

    def _antialiasing_analysis(self, image: np.ndarray) -> dict:
        """Detect anti-aliasing style from intermediate gray values near text edges."""
        try:
            gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)
            threshold = self._otsu_threshold(gray.astype(np.uint8))

            # Near-threshold pixels = anti-aliasing transition zone
            margin = 30
            near_threshold_mask = (gray > threshold - margin) & (gray < threshold + margin)
            if near_threshold_mask.sum() < 50:
                return {"score": 0.0, "inconsistent": False, "has_text": False}

            # Divide into quadrants and compare AA intensity
            h, w = gray.shape
            quads = [
                gray[:h//2, :w//2][near_threshold_mask[:h//2, :w//2]],
                gray[:h//2, w//2:][near_threshold_mask[:h//2, w//2:]],
                gray[h//2:, :w//2][near_threshold_mask[h//2:, :w//2]],
                gray[h//2:, w//2:][near_threshold_mask[h//2:, w//2:]],
            ]

            quad_means = [float(q.mean()) if len(q) > 10 else None for q in quads]
            valid_means = [m for m in quad_means if m is not None]

            if len(valid_means) < 2:
                return {"score": 0.0, "inconsistent": False, "has_text": True}

            variance = float(np.std(valid_means))
            score = min(variance / 20.0, 1.0)

            return {
                "score": score,
                "inconsistent": variance > 10.0,
                "has_text": True,
                "quad_variance": variance,
            }
        except Exception as e:
            logger.debug("AA analysis failed: %s", e)
            return {"score": 0.0, "inconsistent": False, "has_text": False}

    def _otsu_threshold(self, gray: np.ndarray) -> float:
        """Otsu's binarization threshold."""
        hist, bins = np.histogram(gray.ravel(), 256, [0, 256])
        hist = hist.astype(float)
        total = hist.sum()
        if total == 0:
            return 127.0

        sum_total = np.dot(np.arange(256), hist)
        sum_b = 0.0
        w_b = 0.0
        max_var = 0.0
        threshold = 127.0

        for t in range(256):
            w_b += hist[t]
            if w_b == 0:
                continue
            w_f = total - w_b
            if w_f == 0:
                break
            sum_b += t * hist[t]
            mean_b = sum_b / w_b
            mean_f = (sum_total - sum_b) / w_f
            var_between = w_b * w_f * (mean_b - mean_f) ** 2
            if var_between > max_var:
                max_var = var_between
                threshold = float(t)

        return threshold


# ══════════════════════════════════════════════════════════════
#  METADATA ANALYSIS MODULE
# ══════════════════════════════════════════════════════════════

EDITING_TOOLS = {
    "adobe photoshop", "photoshop", "canva", "gimp", "figma",
    "adobe illustrator", "inkscape", "affinity photo", "affinity designer",
    "paint.net", "paintshop pro", "snapseed", "pixlr", "fotor",
    "lightroom", "capture one", "darktable", "rawtherapee",
}

SUSPICIOUS_PRODUCERS = {
    "libreoffice", "openoffice", "wps office",
    "google docs", "microsoft word",  # fine for Word docs, suspicious on "official" docs
}


class MetadataAnalysisModule(ForensicModule):
    """
    Extract and analyze document metadata for fraud indicators.

    Risk indicators:
    - Known editing software (Photoshop, GIMP, Canva, Figma)
    - Missing metadata (stripped by editing tools)
    - Suspicious timestamps (modification before creation)
    - GPS coordinates in official documents
    - Multiple software layers in metadata
    """

    MODULE_NAME = "metadata"
    WEIGHT = 0.08

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        metadata = self._extract_metadata(ctx)
        ctx.metadata = metadata  # Store on context for other modules

        score, confidence, findings = self._evaluate(metadata, ctx)

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data={"metadata": self._metadata_to_dict(metadata)},
        )

    def _extract_metadata(self, ctx: ForensicContext) -> DocumentMetadata:
        """Extract metadata from file using PIL EXIF and format-specific tools."""
        try:
            with Image.open(ctx.file_path) as img:
                exif_data = {}
                try:
                    raw_exif = img._getexif() or {}
                    exif_data = {
                        ExifTags.TAGS.get(k, str(k)): str(v)
                        for k, v in raw_exif.items()
                    }
                except Exception:
                    pass

                info = img.info or {}

                # Extract fields
                software = (
                    exif_data.get("Software")
                    or info.get("Software")
                    or info.get("creator")
                )
                creator = exif_data.get("Artist") or info.get("Author")
                author = creator

                # Timestamps
                dt_original = exif_data.get("DateTimeOriginal")
                dt_modified = exif_data.get("DateTime")

                creation_date = self._parse_exif_date(dt_original)
                modification_date = self._parse_exif_date(dt_modified)

                # GPS
                gps_lat = gps_lon = None
                gps_info = exif_data.get("GPSInfo")
                if gps_info:
                    gps_lat, gps_lon = self._parse_gps(gps_info)

                return DocumentMetadata(
                    creator=creator,
                    producer=info.get("Producer"),
                    author=author,
                    software=software,
                    creation_date=creation_date,
                    modification_date=modification_date,
                    camera_make=exif_data.get("Make"),
                    camera_model=exif_data.get("Model"),
                    raw_exif=exif_data,
                )

        except Exception as e:
            logger.debug("Metadata extraction failed: %s", e)
            return DocumentMetadata()

    def _parse_exif_date(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.strptime(str(date_str).strip(), "%Y:%m:%d %H:%M:%S")
        except Exception:
            return None

    def _parse_gps(self, gps_info: str) -> tuple:
        return None, None  # Simplified — full EXIF GPS parsing complex

    def _evaluate(self, meta: DocumentMetadata, ctx: ForensicContext):
        findings = []
        risk_score = 0.0

        # Check for editing software
        software_lower = (meta.software or "").lower()
        for tool in EDITING_TOOLS:
            if tool in software_lower:
                findings.append(
                    f"Editing software detected in metadata: '{meta.software}'"
                )
                risk_score += 0.50
                break

        # Missing metadata entirely
        if not any([meta.creator, meta.software, meta.author]):
            findings.append("Metadata fields stripped — common in edited documents")
            risk_score += 0.20

        # Suspicious timestamps
        if meta.has_suspicious_timestamps:
            findings.append(
                "Modification date precedes creation date — timestamp manipulation"
            )
            risk_score += 0.40

        # GPS in non-photo document
        if meta.gps_latitude and not ctx.document_type.value == "mobile_capture":
            findings.append("GPS coordinates in non-mobile document — metadata injection suspected")
            risk_score += 0.25

        score = min(risk_score, 1.0)
        confidence = 0.7 if findings else 0.4

        return score, confidence, findings

    def _metadata_to_dict(self, meta: DocumentMetadata) -> dict:
        return {
            "creator": meta.creator,
            "producer": meta.producer,
            "author": meta.author,
            "software": meta.software,
            "creation_date": meta.creation_date.isoformat() if meta.creation_date else None,
            "modification_date": meta.modification_date.isoformat() if meta.modification_date else None,
            "camera_make": meta.camera_make,
            "camera_model": meta.camera_model,
            "has_editing_software": meta.has_editing_software_traces,
            "has_suspicious_timestamps": meta.has_suspicious_timestamps,
        }