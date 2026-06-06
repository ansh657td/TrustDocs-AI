# # """
# # ELA — Error Level Analysis Module

# # ═══════════════════════════════════════════════════════════════
# # FORENSIC THEORY
# # ═══════════════════════════════════════════════════════════════
# # JPEG images store pixel data through lossy compression. When a JPEG
# # is saved, each 8×8 block is independently compressed to a target quality.
# # Crucially, every save cycle pushes ALL blocks toward the compression
# # equilibrium for that quality level.

# # ELA exploits this:
# # - Re-save the image at a fixed quality (e.g., 75%)
# # - Compute pixel-wise difference between original and re-saved
# # - Original uniform regions → small difference (already at equilibrium)
# # - Tampered regions (pasted from another source) → large difference
# #   because they were at a different compression state

# # ═══════════════════════════════════════════════════════════════
# # ALGORITHM CHOICE
# # ═══════════════════════════════════════════════════════════════
# # 1. Save image at quality Q=75 (our recompression target)
# # 2. Load recompressed image back
# # 3. Compute: ELA_map = |original - recompressed| * amplification
# # 4. Analyze statistical distribution of ELA values
# # 5. Detect high-variance regions as tampered candidates

# # Why Q=75? Empirically the best discriminator. Too high = small
# # differences everywhere. Too low = noise dominates.

# # ═══════════════════════════════════════════════════════════════
# # LIMITATIONS
# # ═══════════════════════════════════════════════════════════════
# # - Only reliable on JPEG inputs (PNG/WebP require conversion first)
# # - Double-saved JEPGs may show uniform ELA (adversarial resave)
# # - Large flat regions always show low ELA (sky, walls) — false negative
# # - Text on white background always shows some ELA — false positive risk
# # - PDF-embedded images must be extracted for accurate ELA

# # ═══════════════════════════════════════════════════════════════
# # FALSE POSITIVE RISKS
# # ═══════════════════════════════════════════════════════════════
# # HIGH: High-contrast edges (text borders, logos) always produce
# #       elevated ELA — use edge masking to suppress.
# # MEDIUM: High-frequency textures (fabric, grass) produce moderate ELA
# # LOW: Smooth gradients, solid colors — very reliable

# # ═══════════════════════════════════════════════════════════════
# # COMPUTATIONAL COMPLEXITY
# # ═══════════════════════════════════════════════════════════════
# # O(W*H) for image processing — typically 100-500ms for HD documents
# # Memory: 3 × W × H × 4 bytes (original + recompressed + ELA map)

# # ═══════════════════════════════════════════════════════════════
# # """

# # from __future__ import annotations

# # import io
# # import logging
# # from pathlib import Path
# # from typing import Optional

# # import numpy as np
# # from PIL import Image

# # from app.core.config import settings
# # from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
# # from app.domain.services.base_module import ForensicModule

# # logger = logging.getLogger("docfraud.module.ela")


# # class ELAModule(ForensicModule):
# #     """
# #     Error Level Analysis for detecting JPEG tampering.
# #     """

# #     MODULE_NAME = "ela"
# #     WEIGHT = 0.20
# #     VERSION = "1.0.0"
# #     MIN_IMAGE_SIZE = 64
# #     REQUIRES_IMAGE = True

# #     def __init__(
# #         self,
# #         quality: int = None,
# #         amplification: float = None,
# #         threshold: float = None,
# #     ):
# #         super().__init__()
# #         self.quality = quality or settings.ela_quality
# #         self.amplification = amplification or settings.ela_amplification
# #         self.threshold = threshold or settings.ela_threshold

# #     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
# #         if not ctx.page_images:
# #             return self._make_score(0.0, 0.0, findings=["No image data"])

# #         # Analyze first page / primary image
# #         image_arr = ctx.page_images[0]
# #         ela_map, diff_stats = self._compute_ela(image_arr)

# #         score, confidence, findings, bboxes = self._evaluate(
# #             ela_map, diff_stats, image_arr
# #         )

# #         # Save ELA heatmap artifact
# #         artifact_path = self._save_ela_map(ela_map, ctx.job_id)

# #         return self._make_score(
# #             score=score,
# #             confidence=confidence,
# #             findings=findings,
# #             raw_data=diff_stats,
# #             artifact_path=artifact_path,
# #             bounding_boxes=bboxes,
# #         )

# #     def _compute_ela(
# #         self, image_arr: np.ndarray
# #     ) -> tuple[np.ndarray, dict]:
# #         """
# #         Core ELA computation.

# #         Steps:
# #         1. Convert to PIL Image
# #         2. Save as JPEG at target quality
# #         3. Reload
# #         4. Compute absolute pixel difference
# #         5. Amplify for visibility

# #         Returns:
# #             (ela_map: ndarray uint8, stats: dict)
# #         """
# #         # Convert numpy to PIL
# #         pil_img = Image.fromarray(image_arr.astype(np.uint8), mode="RGB")

# #         # Save to buffer at target quality
# #         buf = io.BytesIO()
# #         pil_img.save(buf, format="JPEG", quality=self.quality)
# #         buf.seek(0)

# #         # Reload recompressed
# #         recompressed = Image.open(buf).convert("RGB")
# #         recomp_arr = np.array(recompressed, dtype=np.float32)
# #         orig_arr = image_arr.astype(np.float32)

# #         # Pixel-wise absolute difference
# #         diff = np.abs(orig_arr - recomp_arr)

# #         # Amplify
# #         ela_map = np.clip(diff * self.amplification, 0, 255).astype(np.uint8)

# #         # Compute per-channel and overall statistics
# #         diff_gray = diff.mean(axis=2)  # luminance difference
# #         stats = {
# #             "mean_diff": float(diff_gray.mean()),
# #             "std_diff": float(diff_gray.std()),
# #             "max_diff": float(diff_gray.max()),
# #             "p95_diff": float(np.percentile(diff_gray, 95)),
# #             "p99_diff": float(np.percentile(diff_gray, 99)),
# #             "ela_quality": self.quality,
# #             "ela_amplification": self.amplification,
# #             # Region-level: divide into 8x8 blocks
# #             "block_mean": float(self._block_statistics(diff_gray, 8).mean()),
# #             "block_std": float(self._block_statistics(diff_gray, 8).std()),
# #         }

# #         return ela_map, stats

# #     def _block_statistics(
# #         self, diff_map: np.ndarray, block_size: int
# #     ) -> np.ndarray:
# #         """
# #         Compute mean ELA per non-overlapping block.
# #         Returned as flat array of block means.
# #         """
# #         h, w = diff_map.shape
# #         bh = h // block_size
# #         bw = w // block_size
# #         if bh == 0 or bw == 0:
# #             return np.array([diff_map.mean()])

# #         truncated = diff_map[: bh * block_size, : bw * block_size]
# #         blocks = truncated.reshape(bh, block_size, bw, block_size)
# #         block_means = blocks.mean(axis=(1, 3))  # (bh, bw)
# #         return block_means.ravel()

# #     def _evaluate(
# #         self,
# #         ela_map: np.ndarray,
# #         stats: dict,
# #         original: np.ndarray,
# #     ) -> tuple[float, float, list[str], list[BoundingBox]]:
# #         """
# #         Convert raw ELA statistics into a fraud score + findings.

# #         Scoring logic:
# #         - High std_diff → regional inconsistency → high tamper signal
# #         - High p99_diff → extreme outlier regions → definite anomaly
# #         - Compare block mean to global mean → localized anomaly detection
# #         """
# #         findings: list[str] = []
# #         bboxes: list[BoundingBox] = []

# #         mean = stats["mean_diff"]
# #         std = stats["std_diff"]
# #         p95 = stats["p95_diff"]
# #         p99 = stats["p99_diff"]
# #         block_std = stats["block_std"]

# #         # Scoring components (each 0–1)
# #         # 1. Global mean: normalized against expected range (0-30)
# #         mean_score = min(mean / 30.0, 1.0)

# #         # 2. Standard deviation: high std = regional inconsistency
# #         std_score = min(std / 20.0, 1.0)

# #         # 3. P99 outlier: extreme high values
# #         p99_score = min(p99 / 50.0, 1.0)

# #         # 4. Block variance: inter-block inconsistency
# #         block_score = min(block_std / 15.0, 1.0)

# #         # Weighted combination
# #         raw_score = (
# #             0.15 * mean_score +
# #             0.25 * std_score +
# #             0.15 * p99_score +
# #             0.15 * block_score +
# #             0.30 * region_score
# #         )

# #         # Threshold-based findings
# #         if mean > 8.0:
# #             findings.append(
# #                 f"Elevated ELA mean ({mean:.1f}) suggests compression inconsistency"
# #             )
# #         if std > 10.0:
# #             findings.append(
# #                 f"High ELA standard deviation ({std:.1f}) indicates regional editing"
# #             )
# #         if p99 > 30.0:
# #             findings.append(
# #                 f"P99 ELA value ({p99:.1f}) indicates extreme outlier regions"
# #             )
# #         if block_std > 8.0:
# #             findings.append(
# #                 "Block-level ELA variance suggests localized modifications"
# #             )

# #         # Detect anomalous regions and build bounding boxes
# #         bboxes = self._detect_anomalous_regions(ela_map, threshold_percentile=95)

# #         region_count = len(bboxes)

# #         region_score = min(region_count / 8.0, 1.0)





# #         if bboxes:
# #             findings.append(
# #                 f"Detected {len(bboxes)} spatially distinct high-ELA region(s)"
# #             )

# #         # Confidence: higher when std is large (we're more certain of a signal)
# #         confidence = min(0.5 + std / 40.0, 0.95)

# #         if len(bboxes) >= 5:
# #             raw_score = max(raw_score, 0.75)

# #         if len(bboxes) >= 8:
# #             raw_score = max(raw_score, 0.85)

# #         return raw_score, confidence, findings, bboxes

# #     def _detect_anomalous_regions(
# #         self,
# #         ela_map: np.ndarray,
# #         threshold_percentile: float = 92,
# #         min_area: int = 500,
# #     ) -> list[BoundingBox]:
# #         """
# #         Find spatially localized high-ELA regions using connected components.

# #         Args:
# #             ela_map: RGB ELA map (uint8)
# #             threshold_percentile: pixels above this percentile are candidates
# #             min_area: minimum area in pixels to report

# #         Returns:
# #             List of BoundingBox objects
# #         """
# #         try:
# #             from skimage.measure import label, regionprops

# #             # Convert to grayscale ELA
# #             ela_gray = ela_map.mean(axis=2).astype(np.float32)
# #             threshold = np.percentile(ela_gray, threshold_percentile)

# #             # Binary mask of anomalous pixels
# #             mask = (ela_gray > threshold).astype(np.uint8)

# #             # Label connected components
# #             labeled = label(mask)
# #             regions = regionprops(labeled)

# #             bboxes = []
# #             for region in regions:
# #                 if region.area < min_area:
# #                     continue

# #                 min_row, min_col, max_row, max_col = region.bbox
# #                 h = max_row - min_row
# #                 w = max_col - min_col

# #                 # Confidence from mean ELA in this region
# #                 region_ela = ela_gray[min_row:max_row, min_col:max_col]
# #                 region_mean = float(region_ela.mean())
# #                 conf = min(region_mean / 50.0, 1.0)

# #                 bboxes.append(
# #                     BoundingBox(
# #                         x=int(min_col),
# #                         y=int(min_row),
# #                         width=int(w),
# #                         height=int(h),
# #                         confidence=conf,
# #                         label="ELA_anomaly",
# #                     )
# #                 )

# #             return sorted(bboxes, key=lambda b: b.confidence, reverse=True)[:10]

# #         except ImportError:
# #             logger.warning("skimage not available; skipping bounding box detection")
# #             return []
# #         except Exception as e:
# #             logger.warning("Bounding box detection failed: %s", e)
# #             return []

# #     def _save_ela_map(
# #         self, ela_map: np.ndarray, job_id: str
# #     ) -> Optional[str]:
# #         """Persist ELA heatmap to disk for API response."""
# #         try:
# #             out_dir = settings.heatmap_dir
# #             out_dir.mkdir(parents=True, exist_ok=True)
# #             out_path = out_dir / f"{job_id}_ela.png"
# #             Image.fromarray(ela_map, mode="RGB").save(str(out_path))
# #             return str(out_path)
# #         except Exception as e:
# #             logger.warning("Failed to save ELA map: %s", e)
# #             return None


# """
# ELA — Error Level Analysis Module

# ═══════════════════════════════════════════════════════════════
# FORENSIC THEORY
# ═══════════════════════════════════════════════════════════════
# JPEG images store pixel data through lossy compression. When a JPEG
# is saved, each 8×8 block is independently compressed to a target quality.
# Crucially, every save cycle pushes ALL blocks toward the compression
# equilibrium for that quality level.

# ELA exploits this:
# - Re-save the image at a fixed quality (e.g., 75%)
# - Compute pixel-wise difference between original and re-saved
# - Original uniform regions → small difference (already at equilibrium)
# - Tampered regions (pasted from another source) → large difference
#   because they were at a different compression state

# ═══════════════════════════════════════════════════════════════
# ALGORITHM CHOICE
# ═══════════════════════════════════════════════════════════════
# 1. Save image at quality Q=75 (our recompression target)
# 2. Load recompressed image back
# 3. Compute: ELA_map = |original - recompressed| * amplification
# 4. Analyze statistical distribution of ELA values
# 5. Detect high-variance regions as tampered candidates

# Why Q=75? Empirically the best discriminator. Too high = small
# differences everywhere. Too low = noise dominates.

# ═══════════════════════════════════════════════════════════════
# LIMITATIONS
# ═══════════════════════════════════════════════════════════════
# - Only reliable on JPEG inputs (PNG/WebP require conversion first)
# - Double-saved JEPGs may show uniform ELA (adversarial resave)
# - Large flat regions always show low ELA (sky, walls) — false negative
# - Text on white background always shows some ELA — false positive risk
# - PDF-embedded images must be extracted for accurate ELA

# ═══════════════════════════════════════════════════════════════
# FALSE POSITIVE RISKS
# ═══════════════════════════════════════════════════════════════
# HIGH: High-contrast edges (text borders, logos) always produce
#       elevated ELA — use edge masking to suppress.
# MEDIUM: High-frequency textures (fabric, grass) produce moderate ELA
# LOW: Smooth gradients, solid colors — very reliable

# ═══════════════════════════════════════════════════════════════
# COMPUTATIONAL COMPLEXITY
# ═══════════════════════════════════════════════════════════════
# O(W*H) for image processing — typically 100-500ms for HD documents
# Memory: 3 × W × H × 4 bytes (original + recompressed + ELA map)

# ═══════════════════════════════════════════════════════════════
# """

# from __future__ import annotations

# import io
# import logging
# from pathlib import Path
# from typing import Optional, Sequence

# import numpy as np
# from PIL import Image

# from app.core.config import settings
# from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
# from app.domain.services.base_module import ForensicModule

# logger = logging.getLogger("docfraud.module.ela")


# class ELAModule(ForensicModule):
#     """
#     Error Level Analysis for detecting JPEG tampering.
#     """

#     MODULE_NAME = "ela"
#     WEIGHT = 0.20
#     VERSION = "1.0.0"
#     MIN_IMAGE_SIZE = 64
#     REQUIRES_IMAGE = True

#     def __init__(
#         self,
#         quality: int = None,
#         amplification: float = None,
#         threshold: float = None,
#     ):
#         super().__init__()
#         self.quality = quality or settings.ela_quality
#         self.amplification = amplification or settings.ela_amplification
#         self.threshold = threshold or settings.ela_threshold

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0, findings=["No image data"])

#         # Analyze first page / primary image
#         image_arr = ctx.page_images[0]
#         ela_map, diff_stats = self._compute_ela(image_arr)

#         score, confidence, findings, bboxes = self._evaluate(
#             ela_map, diff_stats, image_arr
#         )

#         # Save ELA heatmap artifact
#         artifact_path = self._save_ela_map(ela_map, ctx.job_id)

#         return self._make_score(
#             score=score,
#             confidence=confidence,
#             findings=findings,
#             raw_data=diff_stats,
#             artifact_path=artifact_path,
#             bounding_boxes=bboxes,
#         )

#     def _compute_ela(
#         self, image_arr: np.ndarray
#     ) -> tuple[np.ndarray, dict]:
#         """
#         Core ELA computation.

#         Steps:
#         1. Convert to PIL Image
#         2. Save as JPEG at target quality
#         3. Reload
#         4. Compute absolute pixel difference
#         5. Amplify for visibility

#         Returns:
#             (ela_map: ndarray uint8, stats: dict)
#         """
#         # Convert numpy to PIL
#         pil_img = Image.fromarray(image_arr.astype(np.uint8), mode="RGB")

#         # Save to buffer at target quality
#         buf = io.BytesIO()
#         pil_img.save(buf, format="JPEG", quality=self.quality)
#         buf.seek(0)

#         # Reload recompressed
#         recompressed = Image.open(buf).convert("RGB")
#         recomp_arr = np.array(recompressed, dtype=np.float32)
#         orig_arr = image_arr.astype(np.float32)

#         # Pixel-wise absolute difference
#         diff = np.abs(orig_arr - recomp_arr)

#         # Amplify
#         ela_map = np.clip(diff * self.amplification, 0, 255).astype(np.uint8)

#         # Compute per-channel and overall statistics
#         diff_gray = diff.mean(axis=2)  # luminance difference
#         stats = {
#             "mean_diff": float(diff_gray.mean()),
#             "std_diff": float(diff_gray.std()),
#             "max_diff": float(diff_gray.max()),
#             "p95_diff": float(np.percentile(diff_gray, 95)),
#             "p99_diff": float(np.percentile(diff_gray, 99)),
#             "ela_quality": self.quality,
#             "ela_amplification": self.amplification,
#             # Region-level: divide into 8x8 blocks
#             "block_mean": float(self._block_statistics(diff_gray, 8).mean()),
#             "block_std": float(self._block_statistics(diff_gray, 8).std()),
#         }

#         return ela_map, stats

#     def _block_statistics(
#         self, diff_map: np.ndarray, block_size: int
#     ) -> np.ndarray:
#         """
#         Compute mean ELA per non-overlapping block.
#         Returned as flat array of block means.
#         """
#         h, w = diff_map.shape
#         bh = h // block_size
#         bw = w // block_size
#         if bh == 0 or bw == 0:
#             return np.array([diff_map.mean()])

#         truncated = diff_map[: bh * block_size, : bw * block_size]
#         blocks = truncated.reshape(bh, block_size, bw, block_size)
#         block_means = blocks.mean(axis=(1, 3))  # (bh, bw)
#         return block_means.ravel()

#     def _evaluate(
#         self,
#         ela_map: np.ndarray,
#         stats: dict,
#         original: np.ndarray,
#     ) -> tuple[float, float, list[str], list[BoundingBox]]:
#         """
#         Convert raw ELA statistics into a fraud score + findings.

#         Scoring logic:
#         - High std_diff → regional inconsistency → high tamper signal
#         - High p99_diff → extreme outlier regions → definite anomaly
#         - Compare block mean to global mean → localized anomaly detection
#         """
#         findings: list[str] = []
#         bboxes: list[BoundingBox] = []

#         mean = stats["mean_diff"]
#         std = stats["std_diff"]
#         p95 = stats["p95_diff"]
#         p99 = stats["p99_diff"]
#         block_std = stats["block_std"]

#         # Scoring components (each 0–1)
#         # 1. Global mean: normalized against expected range (0-30)
#         mean_score = min(mean / 30.0, 1.0)

#         # 2. Standard deviation: high std = regional inconsistency
#         std_score = min(std / 20.0, 1.0)

#         # 3. P99 outlier: extreme high values
#         p99_score = min(p99 / 50.0, 1.0)

#         # 4. Block variance: inter-block inconsistency
#         block_score = min(block_std / 15.0, 1.0)

#         # Weighted combination
#         raw_score = (
#             0.20 * mean_score
#             + 0.35 * std_score
#             + 0.25 * p99_score
#             + 0.20 * block_score
#         )

#         # Threshold-based findings
#         if mean > 8.0:
#             findings.append(
#                 f"Elevated ELA mean ({mean:.1f}) suggests compression inconsistency"
#             )
#         if std > 10.0:
#             findings.append(
#                 f"High ELA standard deviation ({std:.1f}) indicates regional editing"
#             )
#         if p99 > 30.0:
#             findings.append(
#                 f"P99 ELA value ({p99:.1f}) indicates extreme outlier regions"
#             )
#         if block_std > 8.0:
#             findings.append(
#                 "Block-level ELA variance suggests localized modifications"
#             )

#         # Detect anomalous regions and build bounding boxes
#         bboxes = self._detect_anomalous_regions(ela_map, threshold_percentile=95)

#         if bboxes:
#             findings.append(
#                 f"Detected {len(bboxes)} spatially distinct high-ELA region(s)"
#             )

#         # ── ELA score assembly (fixed) ────────────────────────────────────────
#         detected_regions = bboxes
#         region_count = len(detected_regions)

#         if region_count == 0:
#             ela_score = 0.0
#         else:
#             image_h, image_w = original.shape[:2]
#             image_total_pixels = image_h * image_w

#             count_component = min(region_count / 10.0, 1.0)

#             total_area = sum(b.width * b.height for b in detected_regions)
#             area_ratio = (
#                 min(total_area / image_total_pixels, 1.0)
#                 if image_total_pixels > 0
#                 else 0.0
#             )

#             avg_confidence = sum(b.confidence for b in detected_regions) / region_count

#             ela_score = (
#                 0.4 * count_component
#                 + 0.4 * area_ratio
#                 + 0.2 * avg_confidence
#             )

#             # Hard floor: 5+ regions is unambiguous editing
#             if region_count >= 5:
#                 ela_score = max(ela_score, 0.75)

#             ela_score = round(min(ela_score, 1.0), 4)

#         # ── Expose for scoring engine ─────────────────────────────────────────
#         self._region_count = region_count   # ← scoring engine reads this

#         # Confidence: higher when std is large (we're more certain of a signal)
#         confidence = min(0.5 + std / 40.0, 0.95)

#         return ela_score, confidence, findings, bboxes

#     def _detect_anomalous_regions(
#         self,
#         ela_map: np.ndarray,
#         threshold_percentile: float = 95,
#         min_area: int = 500,
#     ) -> list[BoundingBox]:
#         """
#         Find spatially localized high-ELA regions using connected components.

#         Args:
#             ela_map: RGB ELA map (uint8)
#             threshold_percentile: pixels above this percentile are candidates
#             min_area: minimum area in pixels to report

#         Returns:
#             List of BoundingBox objects
#         """
#         try:
#             from skimage.measure import label, regionprops

#             # Convert to grayscale ELA
#             ela_gray = ela_map.mean(axis=2).astype(np.float32)
#             threshold = np.percentile(ela_gray, threshold_percentile)

#             # Binary mask of anomalous pixels
#             mask = (ela_gray > threshold).astype(np.uint8)

#             # Label connected components
#             labeled = label(mask)
#             regions = regionprops(labeled)

#             bboxes = []
#             for region in regions:
#                 if region.area < min_area:
#                     continue

#                 min_row, min_col, max_row, max_col = region.bbox
#                 h = max_row - min_row
#                 w = max_col - min_col

#                 # Confidence from mean ELA in this region
#                 region_ela = ela_gray[min_row:max_row, min_col:max_col]
#                 region_mean = float(region_ela.mean())
#                 conf = min(region_mean / 50.0, 1.0)

#                 bboxes.append(
#                     BoundingBox(
#                         x=int(min_col),
#                         y=int(min_row),
#                         width=int(w),
#                         height=int(h),
#                         confidence=conf,
#                         label="ELA_anomaly",
#                     )
#                 )

#             return sorted(bboxes, key=lambda b: b.confidence, reverse=True)[:10]

#         except ImportError:
#             logger.warning("skimage not available; skipping bounding box detection")
#             return []
#         except Exception as e:
#             logger.warning("Bounding box detection failed: %s", e)
#             return []

#     def _save_ela_map(
#         self, ela_map: np.ndarray, job_id: str
#     ) -> Optional[str]:
#         """Persist ELA heatmap to disk for API response."""
#         try:
#             out_dir = settings.heatmap_dir
#             out_dir.mkdir(parents=True, exist_ok=True)
#             out_path = out_dir / f"{job_id}_ela.png"
#             Image.fromarray(ela_map, mode="RGB").save(str(out_path))
#             return str(out_path)
#         except Exception as e:
#             logger.warning("Failed to save ELA map: %s", e)
#             return None


"""
ELA — Error Level Analysis Module

═══════════════════════════════════════════════════════════════
FORENSIC THEORY
═══════════════════════════════════════════════════════════════
JPEG images store pixel data through lossy compression. When a JPEG
is saved, each 8×8 block is independently compressed to a target quality.
Crucially, every save cycle pushes ALL blocks toward the compression
equilibrium for that quality level.

ELA exploits this:
- Re-save the image at a fixed quality (e.g., 75%)
- Compute pixel-wise difference between original and re-saved
- Original uniform regions → small difference (already at equilibrium)
- Tampered regions (pasted from another source) → large difference
  because they were at a different compression state

═══════════════════════════════════════════════════════════════
ALGORITHM CHOICE
═══════════════════════════════════════════════════════════════
1. Save image at quality Q=75 (our recompression target)
2. Load recompressed image back
3. Compute: ELA_map = |original - recompressed| * amplification
4. Analyze statistical distribution of ELA values
5. Detect high-variance regions as tampered candidates

Why Q=75? Empirically the best discriminator. Too high = small
differences everywhere. Too low = noise dominates.

═══════════════════════════════════════════════════════════════
LIMITATIONS
═══════════════════════════════════════════════════════════════
- Only reliable on JPEG inputs (PNG/WebP require conversion first)
- Double-saved JEPGs may show uniform ELA (adversarial resave)
- Large flat regions always show low ELA (sky, walls) — false negative
- Text on white background always shows some ELA — false positive risk
- PDF-embedded images must be extracted for accurate ELA

═══════════════════════════════════════════════════════════════
FALSE POSITIVE RISKS
═══════════════════════════════════════════════════════════════
HIGH: High-contrast edges (text borders, logos) always produce
      elevated ELA — use edge masking to suppress.
MEDIUM: High-frequency textures (fabric, grass) produce moderate ELA
LOW: Smooth gradients, solid colors — very reliable

═══════════════════════════════════════════════════════════════
COMPUTATIONAL COMPLEXITY
═══════════════════════════════════════════════════════════════
O(W*H) for image processing — typically 100-500ms for HD documents
Memory: 3 × W × H × 4 bytes (original + recompressed + ELA map)

═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
from PIL import Image

from app.core.config import settings
from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.module.ela")


class ELAModule(ForensicModule):
    """
    Error Level Analysis for detecting JPEG tampering.
    """

    MODULE_NAME = "ela"
    WEIGHT = 0.20
    VERSION = "1.0.0"
    MIN_IMAGE_SIZE = 64
    REQUIRES_IMAGE = True

    def __init__(
        self,
        quality: int = None,
        amplification: float = None,
        threshold: float = None,
    ):
        super().__init__()
        self.quality = quality or settings.ela_quality
        self.amplification = amplification or settings.ela_amplification
        self.threshold = threshold or settings.ela_threshold

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0, findings=["No image data"])

        # Analyze first page / primary image
        image_arr = ctx.page_images[0]
        ela_map, diff_stats = self._compute_ela(image_arr)

        score, confidence, findings, bboxes = self._evaluate(
            ela_map, diff_stats, image_arr
        )

        # Save ELA heatmap artifact
        artifact_path = self._save_ela_map(ela_map, ctx.job_id)

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data=diff_stats,
            artifact_path=artifact_path,
            bounding_boxes=bboxes,
        )

    def _compute_ela(
        self, image_arr: np.ndarray
    ) -> tuple[np.ndarray, dict]:
        """
        Core ELA computation.

        Steps:
        1. Convert to PIL Image
        2. Save as JPEG at target quality
        3. Reload
        4. Compute absolute pixel difference
        5. Amplify for visibility

        Returns:
            (ela_map: ndarray uint8, stats: dict)
        """
        # Convert numpy to PIL
        pil_img = Image.fromarray(image_arr.astype(np.uint8), mode="RGB")

        # Save to buffer at target quality
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=self.quality)
        buf.seek(0)

        # Reload recompressed
        recompressed = Image.open(buf).convert("RGB")
        recomp_arr = np.array(recompressed, dtype=np.float32)
        orig_arr = image_arr.astype(np.float32)

        # Pixel-wise absolute difference
        diff = np.abs(orig_arr - recomp_arr)

        # Amplify
        ela_map = np.clip(diff * self.amplification, 0, 255).astype(np.uint8)

        # Compute per-channel and overall statistics
        diff_gray = diff.mean(axis=2)  # luminance difference
        stats = {
            "mean_diff": float(diff_gray.mean()),
            "std_diff": float(diff_gray.std()),
            "max_diff": float(diff_gray.max()),
            "p95_diff": float(np.percentile(diff_gray, 95)),
            "p99_diff": float(np.percentile(diff_gray, 99)),
            "ela_quality": self.quality,
            "ela_amplification": self.amplification,
            # Region-level: divide into 8x8 blocks
            "block_mean": float(self._block_statistics(diff_gray, 8).mean()),
            "block_std": float(self._block_statistics(diff_gray, 8).std()),
        }

        return ela_map, stats

    def _block_statistics(
        self, diff_map: np.ndarray, block_size: int
    ) -> np.ndarray:
        """
        Compute mean ELA per non-overlapping block.
        Returned as flat array of block means.
        """
        h, w = diff_map.shape
        bh = h // block_size
        bw = w // block_size
        if bh == 0 or bw == 0:
            return np.array([diff_map.mean()])

        truncated = diff_map[: bh * block_size, : bw * block_size]
        blocks = truncated.reshape(bh, block_size, bw, block_size)
        block_means = blocks.mean(axis=(1, 3))  # (bh, bw)
        return block_means.ravel()

    def _evaluate(
        self,
        ela_map: np.ndarray,
        stats: dict,
        original: np.ndarray,
    ) -> tuple[float, float, list[str], list[BoundingBox]]:
        """
        Convert raw ELA statistics into a fraud score + findings.

        Scoring logic:
        - High std_diff → regional inconsistency → high tamper signal
        - High p99_diff → extreme outlier regions → definite anomaly
        - Compare block mean to global mean → localized anomaly detection
        - Region count and confidence → spatial tamper evidence
        - Area ratio → proportion of image affected
        """
        findings: list[str] = []
        bboxes: list[BoundingBox] = []

        mean = stats["mean_diff"]
        std = stats["std_diff"]
        p95 = stats["p95_diff"]
        p99 = stats["p99_diff"]
        block_std = stats["block_std"]

        # Scoring components (each 0–1)
        # 1. Global mean: normalized against expected range (0-30)
        mean_score = min(mean / 30.0, 1.0)

        # 2. Standard deviation: high std = regional inconsistency
        std_score = min(std / 20.0, 1.0)

        # 3. P99 outlier: extreme high values
        p99_score = min(p99 / 50.0, 1.0)

        # 4. Block variance: inter-block inconsistency
        block_score = min(block_std / 15.0, 1.0)

        # ── Fix #1: Region-count scoring ─────────────────────────────────────
        # Detect anomalous regions first so region_count feeds into raw_score.
        # Fix #4: Lower threshold_percentile from 95 → 92 for better tampered
        #         text capture in document forensics.
        bboxes = self._detect_anomalous_regions(ela_map, threshold_percentile=92)
        region_count = len(bboxes)
        region_score = min(region_count / 8.0, 1.0)

        # ── Fix #2: Average region confidence ────────────────────────────────
        # bbox.confidence was computed but never fed back into raw_score.
        avg_region_conf = (
            float(np.mean([b.confidence for b in bboxes])) if bboxes else 0.0
        )

        # ── Fix #5: Area-ratio score ──────────────────────────────────────────
        # Measures how much of the image is flagged, not just how many regions.
        image_h, image_w = original.shape[:2]
        image_total_pixels = image_h * image_w

        # Re-derive total anomaly area from bboxes (already filtered by min_area).
        total_anomaly_area = sum(b.width * b.height for b in bboxes)
        area_ratio = (
            total_anomaly_area / image_total_pixels if image_total_pixels > 0 else 0.0
        )
        area_score = min(area_ratio * 10.0, 1.0)

        # Weighted combination — updated weights (Fix #1 + #2 + #5)
        raw_score = (
            0.15 * mean_score
            + 0.20 * std_score
            + 0.10 * p99_score
            + 0.10 * block_score
            + 0.25 * region_score       # Fix #1
            + 0.20 * avg_region_conf    # Fix #2
        )

        # Additive area bonus (Fix #5)
        raw_score += 0.15 * area_score

        # Renormalise to [0, 1] after the additive bonus
        raw_score = min(raw_score, 1.0)

        # ── Fix #3: Strong override for high region counts ────────────────────
        # 5+ regions is unambiguous editing; 8+ is near-certain fraud.



        if region_count >= 5:
            raw_score = max(raw_score, 0.45)

        if region_count >= 8:
            raw_score = max(raw_score, 0.55)

        # ── Threshold-based findings ──────────────────────────────────────────
        if mean > 8.0:
            findings.append(
                f"Elevated ELA mean ({mean:.1f}) suggests compression inconsistency"
            )
        if std > 10.0:
            findings.append(
                f"High ELA standard deviation ({std:.1f}) indicates regional editing"
            )
        if p99 > 30.0:
            findings.append(
                f"P99 ELA value ({p99:.1f}) indicates extreme outlier regions"
            )
        if block_std > 8.0:
            findings.append(
                "Block-level ELA variance suggests localized modifications"
            )

        if bboxes:
            findings.append(
                f"Detected {region_count} spatially distinct high-ELA region(s)"
            )

        # ── ELA score assembly ────────────────────────────────────────────────
        ela_score = round(raw_score, 4)

        # ── Expose for scoring engine ─────────────────────────────────────────
        self._region_count = region_count   # ← scoring engine reads this

        # Confidence: higher when std is large (we're more certain of a signal)
        confidence = min(0.5 + std / 40.0, 0.95)

        return ela_score, confidence, findings, bboxes

    def _detect_anomalous_regions(
        self,
        ela_map: np.ndarray,
        threshold_percentile: float = 92,   # Fix #4: was 95
        min_area: int = 500,
    ) -> list[BoundingBox]:
        """
        Find spatially localized high-ELA regions using connected components.

        Args:
            ela_map: RGB ELA map (uint8)
            threshold_percentile: pixels above this percentile are candidates.
                                  Lowered to 92 (was 95) to capture more
                                  tampered text regions in document forensics.
            min_area: minimum area in pixels to report

        Returns:
            List of BoundingBox objects
        """
        try:
            from skimage.measure import label, regionprops

            # Convert to grayscale ELA
            ela_gray = ela_map.mean(axis=2).astype(np.float32)
            threshold = np.percentile(ela_gray, threshold_percentile)

            # Binary mask of anomalous pixels
            mask = (ela_gray > threshold).astype(np.uint8)

            # Label connected components
            labeled = label(mask)
            regions = regionprops(labeled)

            bboxes = []
            for region in regions:
                if region.area < min_area:
                    continue

                min_row, min_col, max_row, max_col = region.bbox
                h = max_row - min_row
                w = max_col - min_col

                # Confidence from mean ELA in this region (Fix #2: now used)
                region_ela = ela_gray[min_row:max_row, min_col:max_col]
                region_mean = float(region_ela.mean())
                conf = min(region_mean / 50.0, 1.0)

                bboxes.append(
                    BoundingBox(
                        x=int(min_col),
                        y=int(min_row),
                        width=int(w),
                        height=int(h),
                        confidence=conf,
                        label="ELA_anomaly",
                    )
                )

            return sorted(bboxes, key=lambda b: b.confidence, reverse=True)[:10]

        except ImportError:
            logger.warning("skimage not available; skipping bounding box detection")
            return []
        except Exception as e:
            logger.warning("Bounding box detection failed: %s", e)
            return []

    def _save_ela_map(
        self, ela_map: np.ndarray, job_id: str
    ) -> Optional[str]:
        """Persist ELA heatmap to disk for API response."""
        try:
            out_dir = settings.heatmap_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{job_id}_ela.png"
            Image.fromarray(ela_map, mode="RGB").save(str(out_path))
            return str(out_path)
        except Exception as e:
            logger.warning("Failed to save ELA map: %s", e)
            return None