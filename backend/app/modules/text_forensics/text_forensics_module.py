# # """
# # Text Forensics Module — No-OCR Text Manipulation Detection

# # ═══════════════════════════════════════════════════════════════
# # THEORY
# # ═══════════════════════════════════════════════════════════════
# # Detects text-level forgeries (e.g. name/amount substitutions) by
# # treating characters purely as blobs — no OCR required.

# # Five sub-analyses, each targeting a different forensic signal:

# #   A. Baseline Shift Detection
# #      Genuine text lines share a common baseline (±1-2px).
# #      Inserted/replaced text often sits 1-5px higher or lower due to
# #      different line-height, DPI, or copy-paste origin.

# #   B. Kerning / Inter-character Gap Analysis
# #      In authentic typeset text the gaps between adjacent characters
# #      follow a consistent distribution for a given font and size.
# #      Inserted characters from a different source disturb that
# #      distribution — the coefficient of variation (CV) spikes.

# #   C. Character Spacing Consistency
# #      Compares the mean inter-character gap of a candidate region
# #      against reference regions on the same document.
# #      A large absolute difference flags the region as anomalous.

# #   D. Font Mismatch via Glyph Morphology
# #      Each connected component (blob) is described by four shape
# #      features: aspect ratio, fill ratio, stroke width (via distance
# #      transform), and solidity (area / convex-hull area).
# #      Regions are compared with cosine similarity; similarity < 0.7
# #      is flagged as a likely font/source mismatch.

# #   E. Anti-Aliasing / Sharpness Inconsistency
# #      Inserted text is often rendered at a different resolution or with
# #      a different resampling filter, leaving behind measurable
# #      differences in edge sharpness (Laplacian variance) and gradient
# #      energy distribution (Sobel magnitude statistics).

# # Composite formula (matching the weights in the specification):
# #     text_fraud_score = (
# #         baseline_score   * 0.20
# #       + kerning_score    * 0.20
# #       + spacing_score    * 0.20
# #       + font_score       * 0.25
# #       + antialias_score  * 0.15
# #     )
# # """

# # from __future__ import annotations

# # import logging
# # from typing import Optional

# # import cv2
# # import numpy as np

# # from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
# # from app.domain.services.base_module import ForensicModule

# # logger = logging.getLogger("docfraud.module.text_forensics")


# # # ─────────────────────────────────────────────────────────────
# # # Helpers
# # # ─────────────────────────────────────────────────────────────

# # def _to_gray(image: np.ndarray) -> np.ndarray:
# #     """Convert BGR/RGB image to uint8 grayscale."""
# #     if len(image.shape) == 2:
# #         return image.astype(np.uint8)
# #     if image.shape[2] == 4:
# #         image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
# #     else:
# #         image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
# #     return image.astype(np.uint8)


# # def _binarize(gray: np.ndarray) -> np.ndarray:
# #     """Otsu binarization — returns inverted binary (text pixels = 255)."""
# #     _, binary = cv2.threshold(
# #         gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
# #     )
# #     return binary


# # def _extract_char_blobs(
# #     binary: np.ndarray,
# #     min_h: int = 8,
# #     max_h: int = 80,
# #     min_area: int = 15,
# # ) -> list[tuple[int, int, int, int]]:
# #     """
# #     Return list of (x, y, w, h) for character-like connected components.
# #     Filters by height and area to exclude noise and large blocks.
# #     """
# #     num_labels, _, stats, _ = cv2.connectedComponentsWithStats(
# #         binary, connectivity=8
# #     )
# #     components: list[tuple[int, int, int, int]] = []
# #     for i in range(1, num_labels):  # skip background label 0
# #         x = int(stats[i, cv2.CC_STAT_LEFT])
# #         y = int(stats[i, cv2.CC_STAT_TOP])
# #         w = int(stats[i, cv2.CC_STAT_WIDTH])
# #         h = int(stats[i, cv2.CC_STAT_HEIGHT])
# #         area = int(stats[i, cv2.CC_STAT_AREA])
# #         if min_h < h < max_h and area > min_area:
# #             components.append((x, y, w, h))
# #     return components


# # def _extract_text_regions(binary):
    
# #     kernel = cv2.getStructuringElement(
# #         cv2.MORPH_RECT,
# #         (35, 7)
# #     )

# #     merged = cv2.morphologyEx(
# #         binary,
# #         cv2.MORPH_CLOSE,
# #         kernel,
# #         iterations=3
# #     )

# #     contours, _ = cv2.findContours(
# #         merged,
# #         cv2.RETR_EXTERNAL,
# #         cv2.CHAIN_APPROX_SIMPLE
# #     )

# #     regions = []

# #     for c in contours:

# #         x, y, w, h = cv2.boundingRect(c)

# #         if w > 60 and h > 15:
# #             regions.append((x, y, w, h))

# #     return regions

# # def _group_into_rows(
# #     components: list[tuple[int, int, int, int]],
# #     row_gap: int = 15,
# # ) -> list[list[tuple[int, int, int, int]]]:
# #     """
# #     Cluster blobs into text rows by y-center proximity.
# #     Returns a list of rows, each row sorted left-to-right.
# #     """
# #     if not components:
# #         return []

# #     def y_center(c: tuple) -> float:
# #         return c[1] + c[3] / 2.0

# #     sorted_by_y = sorted(components, key=y_center)
# #     rows: list[list[tuple[int, int, int, int]]] = []
# #     current_row = [sorted_by_y[0]]

# #     for comp in sorted_by_y[1:]:
# #         if abs(y_center(comp) - y_center(current_row[-1])) < row_gap:
# #             current_row.append(comp)
# #         else:
# #             rows.append(sorted(current_row, key=lambda c: c[0]))
# #             current_row = [comp]
# #     rows.append(sorted(current_row, key=lambda c: c[0]))
# #     return rows


# # # ─────────────────────────────────────────────────────────────
# # # Sub-analysis A: Baseline Shift
# # # ─────────────────────────────────────────────────────────────

# # def _analyze_baseline_shift(
# #     binary: np.ndarray,
# # ) -> dict:
# #     """
# #     Compute per-row baseline consistency.

# #     The 'baseline' of a glyph is the bottom edge: y + h.
# #     Within a genuine text row every glyph shares the same baseline ± noise.
# #     Inserted text disturbs this uniformity.

# #     Returns:
# #         score        – 0.0 (clean) … 1.0 (manipulated)
# #         variance     – mean std-dev of baseline across rows
# #         suspicious_rows – count of rows with high baseline variance
# #         findings     – human-readable descriptions
# #     """
# #     components = _extract_char_blobs(binary)
# #     if len(components) < 5:
# #         return {"score": 0.0, "variance": 0.0, "suspicious_rows": 0,
# #                 "findings": [], "has_text": False}

# #     rows = _group_into_rows(components)
# #     row_variances: list[float] = []

# #     for row in rows:
# #         if len(row) < 3:
# #             continue
# #         baselines = [c[1] + c[3] for c in row]  # y + h
# #         row_variances.append(float(np.std(baselines)))

# #     if not row_variances:
# #         return {"score": 0.0, "variance": 0.0, "suspicious_rows": 0,
# #                 "findings": [], "has_text": True}

# #     mean_variance = float(np.mean(row_variances))
# #     # Score: variance of 5px → score 1.0; linear interpolation
# #     if mean_variance <= 2:
# #         score = 0.0

# #     elif mean_variance >= 5:
# #         score = 1.0

# #     else:
# #         score = (mean_variance - 2) / 3
# #     suspicious = sum(v > 3.0 for v in row_variances)

# #     findings: list[str] = []
# #     if suspicious > 0:
# #         findings.append(
# #             f"Baseline shift detected in {suspicious} text row(s) "
# #             f"(mean variance {mean_variance:.1f}px) — possible text insertion"
# #         )

# #     return {
# #         "score": score,
# #         "variance": mean_variance,
# #         "suspicious_rows": suspicious,
# #         "findings": findings,
# #         "has_text": True,
# #     }


# # # ─────────────────────────────────────────────────────────────
# # # Sub-analysis B: Kerning / Inter-character Gap
# # # ─────────────────────────────────────────────────────────────

# # def _analyze_kerning(
# #     binary: np.ndarray,
# # ) -> dict:
# #     """
# #     Measure inter-character gap coefficient of variation per text row.

# #     Authentic typeset text: gaps follow a tight distribution (CV ≈ 0.10-0.20).
# #     Inserted text breaks that pattern (CV > 0.25).

# #     Returns:
# #         score – 0.0 (clean) … 1.0 (manipulated)
# #         cv    – mean coefficient of variation across rows
# #     """
# #     components = _extract_char_blobs(binary)
# #     if len(components) < 6:
# #         return {"score": 0.0, "cv": 0.0, "findings": [], "has_text": False}

# #     rows = _group_into_rows(components)
# #     cvs: list[float] = []

# #     for row in rows:
# #         if len(row) < 4:
# #             continue
# #         # Sort left-to-right, compute gaps between successive blobs
# #         row_sorted = sorted(row, key=lambda c: c[0])
# #         gaps = []
# #         for i in range(1, len(row_sorted)):
# #             prev_x, prev_w = row_sorted[i - 1][0], row_sorted[i - 1][2]
# #             curr_x = row_sorted[i][0]
# #             gap = curr_x - (prev_x + prev_w)
# #             if gap >= 0:  # ignore overlapping blobs
# #                 gaps.append(gap)
# #         if len(gaps) < 3:
# #             continue
# #         mean_gap = float(np.mean(gaps))
# #         std_gap = float(np.std(gaps))
# #         if mean_gap > 0:
# #             cvs.append(std_gap / mean_gap)

# #     if not cvs:
# #         return {"score": 0.0, "cv": 0.0, "findings": [], "has_text": True}

# #     mean_cv = float(np.mean(cvs))
# #     # CV > 0.25 → suspicious; normalize to 0-1
# #     if mean_cv <= 0.15:
# #         score = 0

# #     elif mean_cv >= 0.25:
# #         score = 1

# #     else:
# #         score = (mean_cv - 0.15) / 0.10

# #     findings: list[str] = []
# #     if mean_cv > 0.25:
# #         findings.append(
# #             f"Irregular character spacing detected (kerning CV={mean_cv:.3f} > 0.25) "
# #             "— possible character or word substitution"
# #         )

# #     return {"score": score, "cv": mean_cv, "findings": findings, "has_text": True}


# # # ─────────────────────────────────────────────────────────────
# # # Sub-analysis C: Character Spacing Consistency
# # # ─────────────────────────────────────────────────────────────

# # # def _analyze_spacing_consistency(
# # #     binary: np.ndarray,
# # # ) -> dict:
# # #     """
# # #     Compare mean character spacing across horizontal halves of the document.

# # #     A genuine document shows consistent mean gap throughout.
# # #     Edited sections often have a noticeably different mean gap.

# # #     Returns:
# # #         score – 0.0 (consistent) … 1.0 (inconsistent)
# # #         diff  – absolute difference in mean gap (pixels)
# # #     """
# # #     components = _extract_char_blobs(binary)
# # #     if len(components) < 10:
# # #         return {"score": 0.0, "diff": 0.0, "findings": [], "has_text": False}

# # #     h_img = binary.shape[0]
# # #     top_half = [c for c in components if (c[1] + c[3] / 2) < h_img / 2]
# # #     bot_half = [c for c in components if (c[1] + c[3] / 2) >= h_img / 2]

# # #     def mean_row_gap(blobs: list) -> Optional[float]:
# # #         rows = _group_into_rows(blobs)
# # #         all_gaps: list[float] = []
# # #         for row in rows:
# # #             if len(row) < 3:
# # #                 continue
# # #             row_sorted = sorted(row, key=lambda c: c[0])
# # #             for i in range(1, len(row_sorted)):
# # #                 gap = row_sorted[i][0] - (row_sorted[i-1][0] + row_sorted[i-1][2])
# # #                 if gap >= 0:
# # #                     all_gaps.append(gap)
# # #         return float(np.mean(all_gaps)) if all_gaps else None

# # #     top_gap = mean_row_gap(top_half)
# # #     bot_gap = mean_row_gap(bot_half)

# # #     if top_gap is None or bot_gap is None:
# # #         return {"score": 0.0, "diff": 0.0, "findings": [], "has_text": True}

# # #     diff = abs(top_gap - bot_gap)
# # #     # 3px difference → score 1.0
# # #     score = float(min(1.0, diff / 3.0))

# # #     findings: list[str] = []
# # #     if diff > 2.0:
# # #         findings.append(
# # #             f"Character spacing inconsistency between document regions "
# # #             f"(top={top_gap:.1f}px vs bottom={bot_gap:.1f}px, diff={diff:.1f}px)"
# # #         )

# # #     return {
# # #         "score": score,
# # #         "diff": diff,
# # #         "top_gap": top_gap,
# # #         "bot_gap": bot_gap,
# # #         "findings": findings,
# # #         "has_text": True,
# # #     }


# # # ─────────────────────────────────────────────────────────────
# # # Sub-analysis D: Font Mismatch via Glyph Morphology
# # # ─────────────────────────────────────────────────────────────

# # def _glyph_feature_vector(
# #     binary: np.ndarray,
# #     blobs: list[tuple[int, int, int, int]],
# # ) -> Optional[np.ndarray]:
# #     """
# #     Build a 4-D morphological feature vector from a set of blobs:
# #       [mean_aspect_ratio, mean_fill_ratio, mean_stroke_width, mean_solidity]
# #     Returns None if not enough blobs for reliable statistics.
# #     """
# #     if len(blobs) < 5:
# #         return None

# #     aspects: list[float] = []
# #     fills: list[float] = []
# #     strokes: list[float] = []
# #     solidities: list[float] = []

# #     for x, y, w, h in blobs:
# #         if w == 0 or h == 0:
# #             continue

# #         roi = binary[y: y + h, x: x + w]
# #         area = float(np.sum(roi > 0))
# #         bbox_area = float(w * h)

# #         if bbox_area == 0:
# #             continue

# #         # Aspect ratio
# #         aspects.append(w / h)

# #         # Fill ratio (pixel density inside bounding box)
# #         fills.append(area / bbox_area)

# #         # Stroke width via distance transform (capped to avoid fp overflow)
# #         dist = cv2.distanceTransform(roi, cv2.DIST_L2, 5)
# #         dist = np.clip(dist, 0, 255)   # guard against overflow
# #         stroke = float(dist[roi > 0].mean()) if area > 0 else 0.0
# #         stroke = min(stroke, 50.0)     # cap at 50px — wider is not meaningful
# #         strokes.append(stroke)

# #         # Solidity (area / convex hull area)
# #         contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
# #         if contours:
# #             hull = cv2.convexHull(contours[0])
# #             hull_area = float(cv2.contourArea(hull))
# #             if hull_area > 0:
# #                 solidities.append(area / hull_area)

# #     if not aspects:
# #         return None

# #     return np.array([
# #         float(np.mean(aspects)),
# #         float(np.mean(fills)),
# #         float(np.mean(strokes)),
# #         float(np.mean(solidities)) if solidities else 0.5,
# #     ], dtype=np.float32)


# # def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
# #     norm_a = float(np.linalg.norm(a))
# #     norm_b = float(np.linalg.norm(b))
# #     if norm_a < 1e-9 or norm_b < 1e-9:
# #         return 1.0  # treat as identical if either vector is effectively zero
# #     sim = float(np.dot(a, b) / (norm_a * norm_b))
# #     # Clamp to [-1, 1] to guard against fp rounding outside the valid range
# #     return float(np.clip(sim, -1.0, 1.0))


# # # def _analyze_font_mismatch(
# # #     binary: np.ndarray,
# # # ) -> dict:
# # #     """
# # #     Split document into N horizontal bands and compare glyph morphology
# # #     vectors using cosine similarity.

# # #     Similarity < 0.70 between any pair of bands flags a font mismatch.

# # #     Returns:
# # #         score           – 0.0 (consistent) … 1.0 (mismatched)
# # #         min_similarity  – lowest pairwise cosine similarity
# # #         findings        – human-readable descriptions
# # #     """
# # #     components = _extract_char_blobs(binary)
# # #     if len(components) < 15:
# # #         return {
# # #             "score": 0.0, "min_similarity": 1.0,
# # #             "findings": [], "has_text": False
# # #         }

# # #     h_img = binary.shape[0]
# # #     n_bands = 3
# # #     band_h = h_img / n_bands

# # #     band_blobs = [[] for _ in range(n_bands)]
# # #     for blob in components:
# # #         y_center = blob[1] + blob[3] / 2.0
# # #         band_idx = min(int(y_center / band_h), n_bands - 1)
# # #         band_blobs[band_idx].append(blob)

# # #     vectors: list[tuple[int, np.ndarray]] = []
# # #     for i, blobs in enumerate(band_blobs):
# # #         vec = _glyph_feature_vector(binary, blobs)
# # #         if vec is not None:
# # #             vectors.append((i, vec))

# # #     if len(vectors) < 2:
# # #         return {
# # #             "score": 0.0, "min_similarity": 1.0,
# # #             "findings": [], "has_text": True
# # #         }

# # #     similarities: list[float] = []
# # #     mismatch_pairs: list[str] = []
# # #     for i in range(len(vectors)):
# # #         for j in range(i + 1, len(vectors)):
# # #             sim = _cosine_similarity(vectors[i][1], vectors[j][1])
# # #             similarities.append(sim)
# # #             if sim < 0.70:
# # #                 mismatch_pairs.append(
# # #                     f"bands {vectors[i][0]+1}/{vectors[j][0]+1} "
# # #                     f"(similarity={sim:.3f})"
# # #                 )

# # #     min_sim = float(min(similarities)) if similarities else 1.0
# # #     # score: similarity 0.70 → 0.5; similarity 0.50 → 1.0
# # #     score = float(min(1.0, max(0.0, (0.70 - min_sim) / 0.40)))

# # #     findings: list[str] = []
# # #     if mismatch_pairs:
# # #         findings.append(
# # #             f"Font/glyph mismatch detected between document regions: "
# # #             + ", ".join(mismatch_pairs)
# # #         )

# # #     return {
# # #         "score": score,
# # #         "min_similarity": min_sim,
# # #         "mismatch_pairs": mismatch_pairs,
# # #         "findings": findings,
# # #         "has_text": True,
# # #     }


# # # ─────────────────────────────────────────────────────────────
# # # Sub-analysis E: Anti-Aliasing / Sharpness Inconsistency
# # # ─────────────────────────────────────────────────────────────

# # def _region_sharpness(gray: np.ndarray, region: np.ndarray) -> dict:
# #     """
# #     Compute sharpness metrics for a grayscale region:
# #       - Laplacian variance (overall sharpness)
# #       - Sobel edge magnitude mean and std (edge energy distribution)
# #     """
# #     lap = cv2.Laplacian(region, cv2.CV_64F)
# #     lap_var = float(lap.var())

# #     gx = cv2.Sobel(region, cv2.CV_64F, 1, 0, ksize=3)
# #     gy = cv2.Sobel(region, cv2.CV_64F, 0, 1, ksize=3)
# #     mag = np.sqrt(gx ** 2 + gy ** 2)

# #     return {
# #         "sharpness": lap_var,
# #         "edge_mean": float(mag.mean()),
# #         "edge_std": float(mag.std()),
# #     }


# # def _analyze_antialiasing(
# #     gray: np.ndarray,
# # ) -> dict:
# #     """
# #     Compare sharpness of the top half versus the bottom half of the document.

# #     Inserted text that was rendered at a different DPI or with a different
# #     resampling filter produces a measurable sharpness difference.

# #     Returns:
# #         score              – 0.0 (consistent) … 1.0 (inconsistent)
# #         sharpness_diff     – absolute difference in Laplacian variance
# #         findings           – human-readable descriptions
# #     """
# #     h = gray.shape[0]
# #     if h < 40:
# #         return {"score": 0.0, "sharpness_diff": 0.0,
# #                 "findings": [], "has_text": False}

# #     top = gray[: h // 2, :]
# #     bot = gray[h // 2:, :]

# #     top_metrics = _region_sharpness(gray, top)
# #     bot_metrics = _region_sharpness(gray, bot)

# #     sharpness_diff = abs(top_metrics["sharpness"] - bot_metrics["sharpness"])
# #     edge_mean_diff = abs(top_metrics["edge_mean"] - bot_metrics["edge_mean"])

# #     # Normalize: sharpness diff of 500 → score ≈ 1.0
# #     sharpness_score = float(min(1.0, sharpness_diff / 500.0))
# #     edge_score = float(min(1.0, edge_mean_diff / 20.0))
# #     score = 0.6 * sharpness_score + 0.4 * edge_score

# #     findings: list[str] = []
# #     if sharpness_diff > 200 or edge_mean_diff > 10:
# #         findings.append(
# #             f"Anti-aliasing / sharpness inconsistency detected between document regions "
# #             f"(Laplacian diff={sharpness_diff:.1f}, edge-mean diff={edge_mean_diff:.2f}) "
# #             "— possible text inserted from a different rendering source"
# #         )

# #     return {
# #         "score": score,
# #         "sharpness_diff": sharpness_diff,
# #         "edge_mean_diff": edge_mean_diff,
# #         "top_sharpness": top_metrics["sharpness"],
# #         "bot_sharpness": bot_metrics["sharpness"],
# #         "findings": findings,
# #         "has_text": True,
# #     }


# # # ─────────────────────────────────────────────────────────────
# # # Main Module Class
# # # ─────────────────────────────────────────────────────────────

# # class TextForensicsModule(ForensicModule):
# #     """
# #     Text manipulation forensics using five complementary no-OCR techniques.

# #     Integrated into the pipeline as module name "text_forensics".
# #     Contributes to the 'edited' flag (text-level edits are a form of
# #     regional modification) and uses the 'EDITED_MODULES' group in scoring.

# #     Sub-analyses:
# #       A. Baseline shift detection
# #       B. Kerning / inter-character gap analysis
# #       C. Character spacing consistency
# #       D. Font mismatch via glyph morphology
# #       E. Anti-aliasing / sharpness inconsistency

# #     Final score (specification weights):
# #       text_fraud_score = (
# #           baseline_score   * 0.20
# #         + kerning_score    * 0.20
# #         + spacing_score    * 0.20
# #         + font_score       * 0.25
# #         + antialias_score  * 0.15
# #       )
# #     """

# #     MODULE_NAME = "text_forensics"
# #     WEIGHT = 0.05          # weight in FraudScoringEngine.MODULE_WEIGHTS
# #     VERSION = "1.0.0"
# #     MIN_IMAGE_SIZE = 64
# #     REQUIRES_IMAGE = True

# #     # Sub-analysis weights (must sum to 1.0)
# #     SUB_WEIGHTS = {
# #         "baseline":  0.13,
# #         "kerning":   0.10,
# #         "spacing":   0.05,
# #         "font":      0.10,
# #         "antialias": 0.08,
# #     }

# #     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
# #         if not ctx.page_images:
# #             return self._make_score(0.0, 0.0)

# #         image = ctx.page_images[0]
# #         gray = _to_gray(image)
# #         binary = _binarize(gray)
# #         regions = _extract_text_regions(binary)

# #         region_scores = []
# #         suspicious_boxes = []
# #         all_findings = []

# #         for x, y, w, h in regions:

# #             roi_binary = binary[y:y+h, x:x+w]

# #             baseline_result = _analyze_baseline_shift(roi_binary)
# #             kerning_result = _analyze_kerning(roi_binary)

# #             region_score = (
# #                 baseline_result["score"] * 0.20
# #                 + kerning_result["score"] * 0.20
# #             )


# #             region_score = (
# #       ela_score        * 0.35
# #     + font_score       * 0.25
# #     + antialias_score  * 0.15
# #     + baseline_score   * 0.10
# #     + kerning_score    * 0.10
# #     + spacing_score    * 0.05
# # )



# #             region_scores.append(region_score)

# #             all_findings.extend(
# #                 baseline_result["findings"]
# #                 + kerning_result["findings"]
# #             )

# #             if region_score > 0.30:
# #                 suspicious_boxes.append(
# #                     BoundingBox(
# #                         x=x,
# #                         y=y,
# #                         width=w,
# #                         height=h,
# #                         confidence=float(region_score),
# #                         label="text_forensics"
# #                     )
# #                 )

# #         if region_scores:
# #             composite = float(max(region_scores))
# #         else:
# #             composite = 0.0

# #         confidence = min(
# #             0.95,
# #             0.35 + len(region_scores) * 0.01
# #         )

# #         raw_data = {
# #             "regions_analyzed": len(regions),
# #             "suspicious_regions": len(suspicious_boxes),
# #             "max_region_score": round(composite, 4)
# #         }

# #         logger.info(
# #             "[text_forensics] score=%.3f regions=%d suspicious=%d",
# #             composite,
# #             len(regions),
# #             len(suspicious_boxes)
# #         )

# #         return self._make_score(
# #             score=composite,
# #             confidence=confidence,
# #             findings=all_findings,
# #             raw_data=raw_data,
# #             bounding_boxes=suspicious_boxes,
# #         )

# """
# Text Forensics Module — No-OCR Text Manipulation Detection

# ═══════════════════════════════════════════════════════════════
# THEORY
# ═══════════════════════════════════════════════════════════════
# Detects text-level forgeries (e.g. name/amount substitutions) by
# treating characters purely as blobs — no OCR required.

# Five sub-analyses, each targeting a different forensic signal:

#   A. Baseline Shift Detection
#      Genuine text lines share a common baseline (±1-2px).
#      Inserted/replaced text often sits 1-5px higher or lower due to
#      different line-height, DPI, or copy-paste origin.

#   B. Kerning / Inter-character Gap Analysis
#      In authentic typeset text the gaps between adjacent characters
#      follow a consistent distribution for a given font and size.
#      Inserted characters from a different source disturb that
#      distribution — the coefficient of variation (CV) spikes.

#   C. Character Spacing Consistency
#      Compares the mean inter-character gap of a candidate region
#      against reference regions on the same document.
#      A large absolute difference flags the region as anomalous.

#   D. Font Mismatch via Glyph Morphology
#      Each connected component (blob) is described by four shape
#      features: aspect ratio, fill ratio, stroke width (via distance
#      transform), and solidity (area / convex-hull area).
#      Regions are compared with cosine similarity; similarity < 0.7
#      is flagged as a likely font/source mismatch.

#   E. Anti-Aliasing / Sharpness Inconsistency
#      Inserted text is often rendered at a different resolution or with
#      a different resampling filter, leaving behind measurable
#      differences in edge sharpness (Laplacian variance) and gradient
#      energy distribution (Sobel magnitude statistics).

# Composite formula (matching the weights in the specification):
#     text_fraud_score = (
#         baseline_score   * 0.20
#       + kerning_score    * 0.20
#       + spacing_score    * 0.20
#       + font_score       * 0.25
#       + antialias_score  * 0.15
#     )
# """

# from __future__ import annotations

# import logging
# from typing import Optional

# import cv2
# import numpy as np

# from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
# from app.domain.services.base_module import ForensicModule

# logger = logging.getLogger("docfraud.module.text_forensics")


# # ─────────────────────────────────────────────────────────────
# # Helpers
# # ─────────────────────────────────────────────────────────────

# def _to_gray(image: np.ndarray) -> np.ndarray:
#     """Convert BGR/RGB image to uint8 grayscale."""
#     if len(image.shape) == 2:
#         return image.astype(np.uint8)
#     if image.shape[2] == 4:
#         image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
#     else:
#         image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
#     return image.astype(np.uint8)


# def _binarize(gray: np.ndarray) -> np.ndarray:
#     """Otsu binarization — returns inverted binary (text pixels = 255)."""
#     _, binary = cv2.threshold(
#         gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
#     )
#     return binary


# def _extract_char_blobs(
#     binary: np.ndarray,
#     min_h: int = 8,
#     max_h: int = 80,
#     min_area: int = 15,
# ) -> list[tuple[int, int, int, int]]:
#     """
#     Return list of (x, y, w, h) for character-like connected components.
#     Filters by height and area to exclude noise and large blocks.
#     """
#     num_labels, _, stats, _ = cv2.connectedComponentsWithStats(
#         binary, connectivity=8
#     )
#     components: list[tuple[int, int, int, int]] = []
#     for i in range(1, num_labels):  # skip background label 0
#         x = int(stats[i, cv2.CC_STAT_LEFT])
#         y = int(stats[i, cv2.CC_STAT_TOP])
#         w = int(stats[i, cv2.CC_STAT_WIDTH])
#         h = int(stats[i, cv2.CC_STAT_HEIGHT])
#         area = int(stats[i, cv2.CC_STAT_AREA])
#         if min_h < h < max_h and area > min_area:
#             components.append((x, y, w, h))
#     return components


# def _extract_text_regions(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
#     """
#     Merge nearby character blobs into text-line regions using morphological
#     closing, then return (x, y, w, h) for each region large enough to analyze.
#     """
#     kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 7))
#     merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=3)
#     contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

#     regions: list[tuple[int, int, int, int]] = []
#     for c in contours:
#         x, y, w, h = cv2.boundingRect(c)
#         if w > 60 and h > 15:
#             regions.append((x, y, w, h))
#     return regions


# def _group_into_rows(
#     components: list[tuple[int, int, int, int]],
#     row_gap: int = 15,
# ) -> list[list[tuple[int, int, int, int]]]:
#     """
#     Cluster blobs into text rows by y-center proximity.
#     Returns a list of rows, each row sorted left-to-right.
#     """
#     if not components:
#         return []

#     def y_center(c: tuple) -> float:
#         return c[1] + c[3] / 2.0

#     sorted_by_y = sorted(components, key=y_center)
#     rows: list[list[tuple[int, int, int, int]]] = []
#     current_row = [sorted_by_y[0]]

#     for comp in sorted_by_y[1:]:
#         if abs(y_center(comp) - y_center(current_row[-1])) < row_gap:
#             current_row.append(comp)
#         else:
#             rows.append(sorted(current_row, key=lambda c: c[0]))
#             current_row = [comp]
#     rows.append(sorted(current_row, key=lambda c: c[0]))
#     return rows


# # ─────────────────────────────────────────────────────────────
# # Sub-analysis A: Baseline Shift
# # ─────────────────────────────────────────────────────────────

# def _analyze_baseline_shift(binary: np.ndarray) -> dict:
#     """
#     Compute per-row baseline consistency.

#     The 'baseline' of a glyph is the bottom edge: y + h.
#     Within a genuine text row every glyph shares the same baseline ± noise.
#     Inserted text disturbs this uniformity.

#     Returns:
#         score        – 0.0 (clean) … 1.0 (manipulated)
#         variance     – mean std-dev of baseline across rows
#         suspicious_rows – count of rows with high baseline variance
#         findings     – human-readable descriptions
#     """
#     components = _extract_char_blobs(binary)
#     if len(components) < 5:
#         return {"score": 0.0, "variance": 0.0, "suspicious_rows": 0,
#                 "findings": [], "has_text": False}

#     rows = _group_into_rows(components)
#     row_variances: list[float] = []

#     for row in rows:
#         if len(row) < 3:
#             continue
#         baselines = [c[1] + c[3] for c in row]  # y + h
#         row_variances.append(float(np.std(baselines)))

#     if not row_variances:
#         return {"score": 0.0, "variance": 0.0, "suspicious_rows": 0,
#                 "findings": [], "has_text": True}

#     mean_variance = float(np.mean(row_variances))
#     # Score: variance of 5px → score 1.0; linear interpolation
#     if mean_variance <= 2:
#         score = 0.0
#     elif mean_variance >= 5:
#         score = 1.0
#     else:
#         score = (mean_variance - 2) / 3.0

#     suspicious = sum(v > 3.0 for v in row_variances)

#     findings: list[str] = []
#     if suspicious > 0:
#         findings.append(
#             f"Baseline shift detected in {suspicious} text row(s) "
#             f"(mean variance {mean_variance:.1f}px) — possible text insertion"
#         )

#     return {
#         "score": score,
#         "variance": mean_variance,
#         "suspicious_rows": suspicious,
#         "findings": findings,
#         "has_text": True,
#     }


# # ─────────────────────────────────────────────────────────────
# # Sub-analysis B: Kerning / Inter-character Gap
# # ─────────────────────────────────────────────────────────────

# def _analyze_kerning(binary: np.ndarray) -> dict:
#     """
#     Measure inter-character gap coefficient of variation per text row.

#     Authentic typeset text: gaps follow a tight distribution (CV ≈ 0.10-0.20).
#     Inserted text breaks that pattern (CV > 0.25).

#     Returns:
#         score – 0.0 (clean) … 1.0 (manipulated)
#         cv    – mean coefficient of variation across rows
#     """
#     components = _extract_char_blobs(binary)
#     if len(components) < 6:
#         return {"score": 0.0, "cv": 0.0, "findings": [], "has_text": False}

#     rows = _group_into_rows(components)
#     cvs: list[float] = []

#     for row in rows:
#         if len(row) < 4:
#             continue
#         row_sorted = sorted(row, key=lambda c: c[0])
#         gaps = []
#         for i in range(1, len(row_sorted)):
#             prev_x, prev_w = row_sorted[i - 1][0], row_sorted[i - 1][2]
#             curr_x = row_sorted[i][0]
#             gap = curr_x - (prev_x + prev_w)
#             if gap >= 0:
#                 gaps.append(gap)
#         if len(gaps) < 3:
#             continue
#         mean_gap = float(np.mean(gaps))
#         std_gap = float(np.std(gaps))
#         if mean_gap > 0:
#             cvs.append(std_gap / mean_gap)

#     if not cvs:
#         return {"score": 0.0, "cv": 0.0, "findings": [], "has_text": True}

#     mean_cv = float(np.mean(cvs))
#     if mean_cv <= 0.15:
#         score = 0.0
#     elif mean_cv >= 0.25:
#         score = 1.0
#     else:
#         score = (mean_cv - 0.15) / 0.10

#     findings: list[str] = []
#     if mean_cv > 0.25:
#         findings.append(
#             f"Irregular character spacing detected (kerning CV={mean_cv:.3f} > 0.25) "
#             "— possible character or word substitution"
#         )

#     return {"score": score, "cv": mean_cv, "findings": findings, "has_text": True}


# # ─────────────────────────────────────────────────────────────
# # Sub-analysis C: Character Spacing Consistency
# # ─────────────────────────────────────────────────────────────

# def _analyze_spacing_consistency(binary: np.ndarray) -> dict:
#     """
#     Compare mean character spacing across horizontal halves of the document.

#     A genuine document shows consistent mean gap throughout.
#     Edited sections often have a noticeably different mean gap.

#     Returns:
#         score – 0.0 (consistent) … 1.0 (inconsistent)
#         diff  – absolute difference in mean gap (pixels)
#     """
#     components = _extract_char_blobs(binary)
#     if len(components) < 10:
#         return {"score": 0.0, "diff": 0.0, "findings": [], "has_text": False}

#     h_img = binary.shape[0]
#     top_half = [c for c in components if (c[1] + c[3] / 2) < h_img / 2]
#     bot_half = [c for c in components if (c[1] + c[3] / 2) >= h_img / 2]

#     def mean_row_gap(blobs: list) -> Optional[float]:
#         rows = _group_into_rows(blobs)
#         all_gaps: list[float] = []
#         for row in rows:
#             if len(row) < 3:
#                 continue
#             row_sorted = sorted(row, key=lambda c: c[0])
#             for i in range(1, len(row_sorted)):
#                 gap = row_sorted[i][0] - (row_sorted[i - 1][0] + row_sorted[i - 1][2])
#                 if gap >= 0:
#                     all_gaps.append(gap)
#         return float(np.mean(all_gaps)) if all_gaps else None

#     top_gap = mean_row_gap(top_half)
#     bot_gap = mean_row_gap(bot_half)

#     if top_gap is None or bot_gap is None:
#         return {"score": 0.0, "diff": 0.0, "findings": [], "has_text": True}

#     diff = abs(top_gap - bot_gap)
#     # 3px difference → score 1.0
#     score = float(min(1.0, diff / 3.0))

#     findings: list[str] = []
#     if diff > 2.0:
#         findings.append(
#             f"Character spacing inconsistency between document regions "
#             f"(top={top_gap:.1f}px vs bottom={bot_gap:.1f}px, diff={diff:.1f}px)"
#         )

#     return {
#         "score": score,
#         "diff": diff,
#         "top_gap": top_gap,
#         "bot_gap": bot_gap,
#         "findings": findings,
#         "has_text": True,
#     }


# # ─────────────────────────────────────────────────────────────
# # Sub-analysis D: Font Mismatch via Glyph Morphology
# # ─────────────────────────────────────────────────────────────

# def _glyph_feature_vector(
#     binary: np.ndarray,
#     blobs: list[tuple[int, int, int, int]],
# ) -> Optional[np.ndarray]:
#     """
#     Build a 4-D morphological feature vector from a set of blobs:
#       [mean_aspect_ratio, mean_fill_ratio, mean_stroke_width, mean_solidity]
#     Returns None if not enough blobs for reliable statistics.
#     """
#     if len(blobs) < 5:
#         return None

#     aspects: list[float] = []
#     fills: list[float] = []
#     strokes: list[float] = []
#     solidities: list[float] = []

#     for x, y, w, h in blobs:
#         if w == 0 or h == 0:
#             continue

#         roi = binary[y: y + h, x: x + w]
#         area = float(np.sum(roi > 0))
#         bbox_area = float(w * h)

#         if bbox_area == 0:
#             continue

#         aspects.append(w / h)
#         fills.append(area / bbox_area)

#         dist = cv2.distanceTransform(roi, cv2.DIST_L2, 5)
#         dist = np.clip(dist, 0, 255)
#         stroke = float(dist[roi > 0].mean()) if area > 0 else 0.0
#         stroke = min(stroke, 50.0)
#         strokes.append(stroke)

#         contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
#         if contours:
#             hull = cv2.convexHull(contours[0])
#             hull_area = float(cv2.contourArea(hull))
#             if hull_area > 0:
#                 solidities.append(area / hull_area)

#     if not aspects:
#         return None

#     return np.array([
#         float(np.mean(aspects)),
#         float(np.mean(fills)),
#         float(np.mean(strokes)),
#         float(np.mean(solidities)) if solidities else 0.5,
#     ], dtype=np.float32)


# def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
#     norm_a = float(np.linalg.norm(a))
#     norm_b = float(np.linalg.norm(b))
#     if norm_a < 1e-9 or norm_b < 1e-9:
#         return 1.0
#     sim = float(np.dot(a, b) / (norm_a * norm_b))
#     return float(np.clip(sim, -1.0, 1.0))


# def _analyze_font_mismatch(binary: np.ndarray) -> dict:
#     """
#     Split document into N horizontal bands and compare glyph morphology
#     vectors using cosine similarity.

#     Similarity < 0.70 between any pair of bands flags a font mismatch.

#     Returns:
#         score           – 0.0 (consistent) … 1.0 (mismatched)
#         min_similarity  – lowest pairwise cosine similarity
#         findings        – human-readable descriptions
#     """
#     components = _extract_char_blobs(binary)
#     if len(components) < 15:
#         return {
#             "score": 0.0, "min_similarity": 1.0,
#             "findings": [], "has_text": False,
#         }

#     h_img = binary.shape[0]
#     n_bands = 3
#     band_h = h_img / n_bands

#     band_blobs: list[list] = [[] for _ in range(n_bands)]
#     for blob in components:
#         y_center = blob[1] + blob[3] / 2.0
#         band_idx = min(int(y_center / band_h), n_bands - 1)
#         band_blobs[band_idx].append(blob)

#     vectors: list[tuple[int, np.ndarray]] = []
#     for i, blobs in enumerate(band_blobs):
#         vec = _glyph_feature_vector(binary, blobs)
#         if vec is not None:
#             vectors.append((i, vec))

#     if len(vectors) < 2:
#         return {
#             "score": 0.0, "min_similarity": 1.0,
#             "findings": [], "has_text": True,
#         }

#     similarities: list[float] = []
#     mismatch_pairs: list[str] = []
#     for i in range(len(vectors)):
#         for j in range(i + 1, len(vectors)):
#             sim = _cosine_similarity(vectors[i][1], vectors[j][1])
#             similarities.append(sim)
#             if sim < 0.70:
#                 mismatch_pairs.append(
#                     f"bands {vectors[i][0] + 1}/{vectors[j][0] + 1} "
#                     f"(similarity={sim:.3f})"
#                 )

#     min_sim = float(min(similarities)) if similarities else 1.0
#     # score: similarity 0.70 → 0.5; similarity 0.50 → 1.0
#     score = float(min(1.0, max(0.0, (0.70 - min_sim) / 0.40)))

#     findings: list[str] = []
#     if mismatch_pairs:
#         findings.append(
#             "Font/glyph mismatch detected between document regions: "
#             + ", ".join(mismatch_pairs)
#         )

#     return {
#         "score": score,
#         "min_similarity": min_sim,
#         "mismatch_pairs": mismatch_pairs,
#         "findings": findings,
#         "has_text": True,
#     }


# # ─────────────────────────────────────────────────────────────
# # Sub-analysis E: Anti-Aliasing / Sharpness Inconsistency
# # ─────────────────────────────────────────────────────────────

# def _region_sharpness(gray: np.ndarray, region: np.ndarray) -> dict:
#     """
#     Compute sharpness metrics for a grayscale region:
#       - Laplacian variance (overall sharpness)
#       - Sobel edge magnitude mean and std (edge energy distribution)
#     """
#     lap = cv2.Laplacian(region, cv2.CV_64F)
#     lap_var = float(lap.var())

#     gx = cv2.Sobel(region, cv2.CV_64F, 1, 0, ksize=3)
#     gy = cv2.Sobel(region, cv2.CV_64F, 0, 1, ksize=3)
#     mag = np.sqrt(gx ** 2 + gy ** 2)

#     return {
#         "sharpness": lap_var,
#         "edge_mean": float(mag.mean()),
#         "edge_std": float(mag.std()),
#     }


# def _analyze_antialiasing(gray: np.ndarray) -> dict:
#     """
#     Compare sharpness of the top half versus the bottom half of the document.

#     Inserted text that was rendered at a different DPI or with a different
#     resampling filter produces a measurable sharpness difference.

#     Returns:
#         score              – 0.0 (consistent) … 1.0 (inconsistent)
#         sharpness_diff     – absolute difference in Laplacian variance
#         findings           – human-readable descriptions
#     """
#     h = gray.shape[0]
#     if h < 40:
#         return {"score": 0.0, "sharpness_diff": 0.0,
#                 "findings": [], "has_text": False}

#     top = gray[: h // 2, :]
#     bot = gray[h // 2:, :]

#     top_metrics = _region_sharpness(gray, top)
#     bot_metrics = _region_sharpness(gray, bot)

#     sharpness_diff = abs(top_metrics["sharpness"] - bot_metrics["sharpness"])
#     edge_mean_diff = abs(top_metrics["edge_mean"] - bot_metrics["edge_mean"])

#     sharpness_score = float(min(1.0, sharpness_diff / 500.0))
#     edge_score = float(min(1.0, edge_mean_diff / 20.0))
#     score = 0.6 * sharpness_score + 0.4 * edge_score

#     findings: list[str] = []
#     if sharpness_diff > 200 or edge_mean_diff > 10:
#         findings.append(
#             f"Anti-aliasing / sharpness inconsistency detected between document regions "
#             f"(Laplacian diff={sharpness_diff:.1f}, edge-mean diff={edge_mean_diff:.2f}) "
#             "— possible text inserted from a different rendering source"
#         )

#     return {
#         "score": score,
#         "sharpness_diff": sharpness_diff,
#         "edge_mean_diff": edge_mean_diff,
#         "top_sharpness": top_metrics["sharpness"],
#         "bot_sharpness": bot_metrics["sharpness"],
#         "findings": findings,
#         "has_text": True,
#     }


# # ─────────────────────────────────────────────────────────────
# # Main Module Class
# # ─────────────────────────────────────────────────────────────

# class TextForensicsModule(ForensicModule):
#     """
#     Text manipulation forensics using five complementary no-OCR techniques.

#     Integrated into the pipeline as module name "text_forensics".
#     Contributes to the 'edited' flag (text-level edits are a form of
#     regional modification) and uses the 'EDITED_MODULES' group in scoring.

#     Sub-analyses:
#       A. Baseline shift detection
#       B. Kerning / inter-character gap analysis
#       C. Character spacing consistency
#       D. Font mismatch via glyph morphology
#       E. Anti-aliasing / sharpness inconsistency

#     Final score (specification weights):
#       text_fraud_score = (
#           baseline_score   * 0.20
#         + kerning_score    * 0.20
#         + spacing_score    * 0.20
#         + font_score       * 0.25
#         + antialias_score  * 0.15
#       )
#     """

#     MODULE_NAME = "text_forensics"
#     WEIGHT = 0.05          # weight in FraudScoringEngine.MODULE_WEIGHTS
#     VERSION = "1.0.0"
#     MIN_IMAGE_SIZE = 64
#     REQUIRES_IMAGE = True

#     # FIX 6: weights now match the module docstring formula and sum to 1.0
#     # (was: baseline=0.13, kerning=0.10, spacing=0.05, font=0.10, antialias=0.08 → sum 0.46)
#     SUB_WEIGHTS = {
#         "baseline":  0.15,
#         "kerning":   0.15,
#         "spacing":   0.15,
#         "font":      0.35,
#         "antialias": 0.20,
#     }

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         gray = _to_gray(image)
#         binary = _binarize(gray)
#         regions = _extract_text_regions(binary)

#         region_scores: list[float] = []
#         suspicious_boxes: list[BoundingBox] = []
#         all_findings: list[str] = []

#         for x, y, w, h in regions:
#             roi_binary = binary[y: y + h, x: x + w]
#             roi_gray = gray[y: y + h, x: x + w]   # needed for antialiasing

#             # FIX 1 & 2: call the previously commented-out sub-analyses
#             # FIX 3: call _analyze_antialiasing (was defined but never invoked)
#             baseline_result   = _analyze_baseline_shift(roi_binary)
#             kerning_result    = _analyze_kerning(roi_binary)
#             spacing_result    = _analyze_spacing_consistency(roi_binary)
#             font_result       = _analyze_font_mismatch(roi_binary)
#             antialias_result  = _analyze_antialiasing(roi_gray)

#             # FIX 4: single composite formula using the spec weights
#             # (was: two assignments — first partial, second overwrote with
#             #  undefined variables ela_score / font_score / antialias_score /
#             #  spacing_score causing a NameError at runtime)
#             region_score = (
#                 baseline_result["score"]  * self.SUB_WEIGHTS["baseline"]
#                 + kerning_result["score"]   * self.SUB_WEIGHTS["kerning"]
#                 + spacing_result["score"]   * self.SUB_WEIGHTS["spacing"]
#                 + font_result["score"]      * self.SUB_WEIGHTS["font"]
#                 + antialias_result["score"] * self.SUB_WEIGHTS["antialias"]
#             )

#             region_scores.append(region_score)

#             # FIX 5: collect findings from ALL five sub-analyses
#             # (was: only baseline + kerning findings were collected)
#             all_findings.extend(
#                 baseline_result["findings"]
#                 + kerning_result["findings"]
#                 + spacing_result["findings"]
#                 + font_result["findings"]
#                 + antialias_result["findings"]
#             )

#             if region_score > 0.30:
#                 suspicious_boxes.append(
#                     BoundingBox(
#                         x=x,
#                         y=y,
#                         width=w,
#                         height=h,
#                         confidence=float(region_score),
#                         label="text_forensics",
#                     )
#                 )

#         composite = float(max(region_scores)) if region_scores else 0.0

#         confidence = min(0.95, 0.35 + len(region_scores) * 0.01)

#         raw_data = {
#             "regions_analyzed": len(regions),
#             "suspicious_regions": len(suspicious_boxes),
#             "max_region_score": round(composite, 4),
#         }

#         logger.info(
#             "[text_forensics] score=%.3f regions=%d suspicious=%d",
#             composite,
#             len(regions),
#             len(suspicious_boxes),
#         )

#         return self._make_score(
#             score=composite,
#             confidence=confidence,
#             findings=all_findings,
#             raw_data=raw_data,
#             bounding_boxes=suspicious_boxes,
#         )


"""
Text Forensics Module — No-OCR Text Manipulation Detection

═══════════════════════════════════════════════════════════════
THEORY
═══════════════════════════════════════════════════════════════
Detects text-level forgeries (e.g. name/amount substitutions) by
treating characters purely as blobs — no OCR required.

Five sub-analyses, each targeting a different forensic signal:

  A. Baseline Shift Detection
     Genuine text lines share a common baseline (±1-2px).
     Inserted/replaced text often sits 1-5px higher or lower due to
     different line-height, DPI, or copy-paste origin.

  B. Kerning / Inter-character Gap Analysis
     In authentic typeset text the gaps between adjacent characters
     follow a consistent distribution for a given font and size.
     Inserted characters from a different source disturb that
     distribution — the coefficient of variation (CV) spikes.

  C. Character Spacing Consistency
     Compares the mean inter-character gap of a candidate region
     against reference regions on the same document.
     A large absolute difference flags the region as anomalous.

  D. Font Mismatch via Glyph Morphology
     Each connected component (blob) is described by four shape
     features: aspect ratio, fill ratio, stroke width (via distance
     transform), and solidity (area / convex-hull area).
     Regions are compared with cosine similarity; similarity < 0.7
     is flagged as a likely font/source mismatch.

  E. Anti-Aliasing / Sharpness Inconsistency
     Inserted text is often rendered at a different resolution or with
     a different resampling filter, leaving behind measurable
     differences in edge sharpness (Laplacian variance) and gradient
     energy distribution (Sobel magnitude statistics).

Composite formula (matching the weights in the specification):
    text_fraud_score = (
        baseline_score   * 0.20
      + kerning_score    * 0.20
      + spacing_score    * 0.20
      + font_score       * 0.25
      + antialias_score  * 0.15
    )
"""

from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.module.text_forensics")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _to_gray(image: np.ndarray) -> np.ndarray:
    """Convert BGR/RGB image to uint8 grayscale."""
    if len(image.shape) == 2:
        return image.astype(np.uint8)
    if image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
    else:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image.astype(np.uint8)


def _binarize(gray: np.ndarray) -> np.ndarray:
    """Otsu binarization — returns inverted binary (text pixels = 255)."""
    _, binary = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    return binary


def _extract_char_blobs(
    binary: np.ndarray,
    min_h: int = 8,
    max_h: int = 80,
    min_area: int = 15,
) -> list[tuple[int, int, int, int]]:
    """
    Return list of (x, y, w, h) for character-like connected components.
    Filters by height and area to exclude noise and large blocks.
    """
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8
    )
    components: list[tuple[int, int, int, int]] = []
    for i in range(1, num_labels):  # skip background label 0
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        area = int(stats[i, cv2.CC_STAT_AREA])
        if min_h < h < max_h and area > min_area:
            components.append((x, y, w, h))
    return components


def _extract_text_regions(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """
    Merge nearby character blobs into text-line regions using morphological
    closing, then return (x, y, w, h) for each region large enough to analyze.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (35, 7))
    merged = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=3)
    contours, _ = cv2.findContours(merged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[tuple[int, int, int, int]] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 60 and h > 15:
            regions.append((x, y, w, h))
    return regions


def _group_into_rows(
    components: list[tuple[int, int, int, int]],
    row_gap: int = 15,
) -> list[list[tuple[int, int, int, int]]]:
    """
    Cluster blobs into text rows by y-center proximity.
    Returns a list of rows, each row sorted left-to-right.
    """
    if not components:
        return []

    def y_center(c: tuple) -> float:
        return c[1] + c[3] / 2.0

    sorted_by_y = sorted(components, key=y_center)
    rows: list[list[tuple[int, int, int, int]]] = []
    current_row = [sorted_by_y[0]]

    for comp in sorted_by_y[1:]:
        if abs(y_center(comp) - y_center(current_row[-1])) < row_gap:
            current_row.append(comp)
        else:
            rows.append(sorted(current_row, key=lambda c: c[0]))
            current_row = [comp]
    rows.append(sorted(current_row, key=lambda c: c[0]))
    return rows


# ─────────────────────────────────────────────────────────────
# Sub-analysis A: Baseline Shift
# ─────────────────────────────────────────────────────────────

def _analyze_baseline_shift(binary: np.ndarray) -> dict:
    """
    Compute per-row baseline consistency.

    The 'baseline' of a glyph is the bottom edge: y + h.
    Within a genuine text row every glyph shares the same baseline ± noise.
    Inserted text disturbs this uniformity.

    Returns:
        score        – 0.0 (clean) … 1.0 (manipulated)
        variance     – mean std-dev of baseline across rows
        suspicious_rows – count of rows with high baseline variance
        findings     – human-readable descriptions
    """
    components = _extract_char_blobs(binary)
    if len(components) < 5:
        return {"score": 0.0, "variance": 0.0, "suspicious_rows": 0,
                "findings": [], "has_text": False}

    rows = _group_into_rows(components)
    row_variances: list[float] = []

    for row in rows:
        if len(row) < 3:
            continue
        baselines = [c[1] + c[3] for c in row]  # y + h
        row_variances.append(float(np.std(baselines)))

    if not row_variances:
        return {"score": 0.0, "variance": 0.0, "suspicious_rows": 0,
                "findings": [], "has_text": True}

    mean_variance = float(np.mean(row_variances))
    # Score: variance of 5px → score 1.0; linear interpolation
    if mean_variance <= 2:
        score = 0.0
    elif mean_variance >= 5:
        score = 1.0
    else:
        score = (mean_variance - 2) / 3.0

    suspicious = sum(v > 3.0 for v in row_variances)

    findings: list[str] = []
    if suspicious > 0:
        findings.append(
            f"Baseline shift detected in {suspicious} text row(s) "
            f"(mean variance {mean_variance:.1f}px) — possible text insertion"
        )

    return {
        "score": score,
        "variance": mean_variance,
        "suspicious_rows": suspicious,
        "findings": findings,
        "has_text": True,
    }


# ─────────────────────────────────────────────────────────────
# Sub-analysis B: Kerning / Inter-character Gap
# ─────────────────────────────────────────────────────────────

def _analyze_kerning(binary: np.ndarray) -> dict:
    """
    Measure inter-character gap coefficient of variation per text row.

    Authentic typeset text: gaps follow a tight distribution (CV ≈ 0.10-0.20).
    Inserted text breaks that pattern (CV > 0.25).

    Returns:
        score – 0.0 (clean) … 1.0 (manipulated)
        cv    – mean coefficient of variation across rows
    """
    components = _extract_char_blobs(binary)
    if len(components) < 6:
        return {"score": 0.0, "cv": 0.0, "findings": [], "has_text": False}

    rows = _group_into_rows(components)
    cvs: list[float] = []

    for row in rows:
        if len(row) < 4:
            continue
        row_sorted = sorted(row, key=lambda c: c[0])
        gaps = []
        for i in range(1, len(row_sorted)):
            prev_x, prev_w = row_sorted[i - 1][0], row_sorted[i - 1][2]
            curr_x = row_sorted[i][0]
            gap = curr_x - (prev_x + prev_w)
            if gap >= 0:
                gaps.append(gap)
        if len(gaps) < 3:
            continue
        mean_gap = float(np.mean(gaps))
        std_gap = float(np.std(gaps))
        if mean_gap > 0:
            cvs.append(std_gap / mean_gap)

    if not cvs:
        return {"score": 0.0, "cv": 0.0, "findings": [], "has_text": True}

    mean_cv = float(np.mean(cvs))
    if mean_cv <= 0.15:
        score = 0.0
    elif mean_cv >= 0.25:
        score = 1.0
    else:
        score = (mean_cv - 0.15) / 0.10

    findings: list[str] = []
    if mean_cv > 0.25:
        findings.append(
            f"Irregular character spacing detected (kerning CV={mean_cv:.3f} > 0.25) "
            "— possible character or word substitution"
        )

    return {"score": score, "cv": mean_cv, "findings": findings, "has_text": True}


# ─────────────────────────────────────────────────────────────
# Sub-analysis C: Character Spacing Consistency
# ─────────────────────────────────────────────────────────────

def _analyze_spacing_consistency(binary: np.ndarray) -> dict:
    """
    Compare mean character spacing across horizontal halves of the document.

    A genuine document shows consistent mean gap throughout.
    Edited sections often have a noticeably different mean gap.

    Returns:
        score – 0.0 (consistent) … 1.0 (inconsistent)
        diff  – absolute difference in mean gap (pixels)
    """
    components = _extract_char_blobs(binary)
    if len(components) < 10:
        return {"score": 0.0, "diff": 0.0, "findings": [], "has_text": False}

    h_img = binary.shape[0]
    top_half = [c for c in components if (c[1] + c[3] / 2) < h_img / 2]
    bot_half = [c for c in components if (c[1] + c[3] / 2) >= h_img / 2]

    def mean_row_gap(blobs: list) -> Optional[float]:
        rows = _group_into_rows(blobs)
        all_gaps: list[float] = []
        for row in rows:
            if len(row) < 3:
                continue
            row_sorted = sorted(row, key=lambda c: c[0])
            for i in range(1, len(row_sorted)):
                gap = row_sorted[i][0] - (row_sorted[i - 1][0] + row_sorted[i - 1][2])
                if gap >= 0:
                    all_gaps.append(gap)
        return float(np.mean(all_gaps)) if all_gaps else None

    top_gap = mean_row_gap(top_half)
    bot_gap = mean_row_gap(bot_half)

    if top_gap is None or bot_gap is None:
        return {"score": 0.0, "diff": 0.0, "findings": [], "has_text": True}

    diff = abs(top_gap - bot_gap)
    # 3px difference → score 1.0
    score = float(min(1.0, diff / 3.0))

    findings: list[str] = []
    if diff > 2.0:
        findings.append(
            f"Character spacing inconsistency between document regions "
            f"(top={top_gap:.1f}px vs bottom={bot_gap:.1f}px, diff={diff:.1f}px)"
        )

    return {
        "score": score,
        "diff": diff,
        "top_gap": top_gap,
        "bot_gap": bot_gap,
        "findings": findings,
        "has_text": True,
    }


# ─────────────────────────────────────────────────────────────
# Sub-analysis D: Font Mismatch via Glyph Morphology
# ─────────────────────────────────────────────────────────────

def _glyph_feature_vector(
    binary: np.ndarray,
    blobs: list[tuple[int, int, int, int]],
) -> Optional[np.ndarray]:
    """
    Build a 4-D morphological feature vector from a set of blobs:
      [mean_aspect_ratio, mean_fill_ratio, mean_stroke_width, mean_solidity]
    Returns None if not enough blobs for reliable statistics.
    """
    if len(blobs) < 5:
        return None

    aspects: list[float] = []
    fills: list[float] = []
    strokes: list[float] = []
    solidities: list[float] = []

    for x, y, w, h in blobs:
        if w == 0 or h == 0:
            continue

        roi = binary[y: y + h, x: x + w]
        area = float(np.sum(roi > 0))
        bbox_area = float(w * h)

        if bbox_area == 0:
            continue

        aspects.append(w / h)
        fills.append(area / bbox_area)

        dist = cv2.distanceTransform(roi, cv2.DIST_L2, 5)
        dist = np.clip(dist, 0, 255)
        stroke = float(dist[roi > 0].mean()) if area > 0 else 0.0
        stroke = min(stroke, 50.0)
        strokes.append(stroke)

        contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            hull = cv2.convexHull(contours[0])
            hull_area = float(cv2.contourArea(hull))
            if hull_area > 0:
                solidities.append(area / hull_area)

    if not aspects:
        return None

    return np.array([
        float(np.mean(aspects)),
        float(np.mean(fills)),
        float(np.mean(strokes)),
        float(np.mean(solidities)) if solidities else 0.5,
    ], dtype=np.float32)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 1.0
    sim = float(np.dot(a, b) / (norm_a * norm_b))
    return float(np.clip(sim, -1.0, 1.0))


def _analyze_font_mismatch(binary: np.ndarray) -> dict:
    """
    Split document into N horizontal bands and compare glyph morphology
    vectors using cosine similarity.

    Similarity < 0.70 between any pair of bands flags a font mismatch.

    Returns:
        score           – 0.0 (consistent) … 1.0 (mismatched)
        min_similarity  – lowest pairwise cosine similarity
        findings        – human-readable descriptions
    """
    components = _extract_char_blobs(binary)
    if len(components) < 15:
        return {
            "score": 0.0, "min_similarity": 1.0,
            "findings": [], "has_text": False,
        }

    h_img = binary.shape[0]
    n_bands = 3
    band_h = h_img / n_bands

    band_blobs: list[list] = [[] for _ in range(n_bands)]
    for blob in components:
        y_center = blob[1] + blob[3] / 2.0
        band_idx = min(int(y_center / band_h), n_bands - 1)
        band_blobs[band_idx].append(blob)

    vectors: list[tuple[int, np.ndarray]] = []
    for i, blobs in enumerate(band_blobs):
        vec = _glyph_feature_vector(binary, blobs)
        if vec is not None:
            vectors.append((i, vec))

    if len(vectors) < 2:
        return {
            "score": 0.0, "min_similarity": 1.0,
            "findings": [], "has_text": True,
        }

    similarities: list[float] = []
    mismatch_pairs: list[str] = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            sim = _cosine_similarity(vectors[i][1], vectors[j][1])
            similarities.append(sim)
            if sim < 0.70:
                mismatch_pairs.append(
                    f"bands {vectors[i][0] + 1}/{vectors[j][0] + 1} "
                    f"(similarity={sim:.3f})"
                )

    min_sim = float(min(similarities)) if similarities else 1.0
    # score: similarity 0.70 → 0.5; similarity 0.50 → 1.0
    score = float(min(1.0, max(0.0, (0.70 - min_sim) / 0.40)))

    findings: list[str] = []
    if mismatch_pairs:
        findings.append(
            "Font/glyph mismatch detected between document regions: "
            + ", ".join(mismatch_pairs)
        )

    return {
        "score": score,
        "min_similarity": min_sim,
        "mismatch_pairs": mismatch_pairs,
        "findings": findings,
        "has_text": True,
    }


# ─────────────────────────────────────────────────────────────
# Sub-analysis E: Anti-Aliasing / Sharpness Inconsistency
# ─────────────────────────────────────────────────────────────

def _region_sharpness(gray: np.ndarray, region: np.ndarray) -> dict:
    """
    Compute sharpness metrics for a grayscale region:
      - Laplacian variance (overall sharpness)
      - Sobel edge magnitude mean and std (edge energy distribution)
    """
    lap = cv2.Laplacian(region, cv2.CV_64F)
    lap_var = float(lap.var())

    gx = cv2.Sobel(region, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(region, cv2.CV_64F, 0, 1, ksize=3)
    mag = np.sqrt(gx ** 2 + gy ** 2)

    return {
        "sharpness": lap_var,
        "edge_mean": float(mag.mean()),
        "edge_std": float(mag.std()),
    }


def _analyze_antialiasing(gray: np.ndarray) -> dict:
    """
    Compare sharpness of the top half versus the bottom half of the document.

    Inserted text that was rendered at a different DPI or with a different
    resampling filter produces a measurable sharpness difference.

    Returns:
        score              – 0.0 (consistent) … 1.0 (inconsistent)
        sharpness_diff     – absolute difference in Laplacian variance
        findings           – human-readable descriptions
    """
    h = gray.shape[0]
    if h < 40:
        return {"score": 0.0, "sharpness_diff": 0.0,
                "findings": [], "has_text": False}

    top = gray[: h // 2, :]
    bot = gray[h // 2:, :]

    top_metrics = _region_sharpness(gray, top)
    bot_metrics = _region_sharpness(gray, bot)

    sharpness_diff = abs(top_metrics["sharpness"] - bot_metrics["sharpness"])
    edge_mean_diff = abs(top_metrics["edge_mean"] - bot_metrics["edge_mean"])

    sharpness_score = float(min(1.0, sharpness_diff / 500.0))
    edge_score = float(min(1.0, edge_mean_diff / 20.0))
    score = 0.6 * sharpness_score + 0.4 * edge_score

    findings: list[str] = []
    if sharpness_diff > 200 or edge_mean_diff > 10:
        findings.append(
            f"Anti-aliasing / sharpness inconsistency detected between document regions "
            f"(Laplacian diff={sharpness_diff:.1f}, edge-mean diff={edge_mean_diff:.2f}) "
            "— possible text inserted from a different rendering source"
        )

    return {
        "score": score,
        "sharpness_diff": sharpness_diff,
        "edge_mean_diff": edge_mean_diff,
        "top_sharpness": top_metrics["sharpness"],
        "bot_sharpness": bot_metrics["sharpness"],
        "findings": findings,
        "has_text": True,
    }


# ─────────────────────────────────────────────────────────────
# Main Module Class
# ─────────────────────────────────────────────────────────────

class TextForensicsModule(ForensicModule):
    """
    Text manipulation forensics using five complementary no-OCR techniques.

    Integrated into the pipeline as module name "text_forensics".
    Contributes to the 'edited' flag (text-level edits are a form of
    regional modification) and uses the 'EDITED_MODULES' group in scoring.

    Sub-analyses:
      A. Baseline shift detection
      B. Kerning / inter-character gap analysis
      C. Character spacing consistency
      D. Font mismatch via glyph morphology
      E. Anti-aliasing / sharpness inconsistency

    Final score (specification weights):
      text_fraud_score = (
          baseline_score   * 0.15
        + kerning_score    * 0.15
        + spacing_score    * 0.15
        + font_score       * 0.35
        + antialias_score  * 0.20
      )
    """

    MODULE_NAME = "text_forensics"
    WEIGHT = 0.05          # weight in FraudScoringEngine.MODULE_WEIGHTS
    VERSION = "1.0.0"
    MIN_IMAGE_SIZE = 64
    REQUIRES_IMAGE = True

    SUB_WEIGHTS = {
        "baseline":  0.15,
        "kerning":   0.15,
        "spacing":   0.15,
        "font":      0.35,
        "antialias": 0.20,
    }

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        gray = _to_gray(image)
        binary = _binarize(gray)
        regions = _extract_text_regions(binary)

        region_scores: list[float] = []
        suspicious_boxes: list[BoundingBox] = []
        all_findings: list[str] = []

        for x, y, w, h in regions:
            roi_binary = binary[y: y + h, x: x + w]
            roi_gray = gray[y: y + h, x: x + w]   # needed for antialiasing

            baseline_result   = _analyze_baseline_shift(roi_binary)
            kerning_result    = _analyze_kerning(roi_binary)
            spacing_result    = _analyze_spacing_consistency(roi_binary)
            font_result       = _analyze_font_mismatch(roi_binary)
            antialias_result  = _analyze_antialiasing(roi_gray)

            # ── Text forensics score assembly (fixed) ────────────────────────────
            # Per-signal normalization with calibrated denominators:
            #
            #   baseline_variance  / 10.0  → genuine scans land 0.10-0.40
            #   kerning_cv         /  2.0  → genuine scans land 0.40-0.75
            #   spacing_cv         /  2.0  → similar to kerning
            #   antialias_diff     / 400.0 → genuine scans land 0.05-0.20
            #   font_score                 → pass-through (already 0-1)
            #
            baseline_score_norm = min(baseline_result.get("variance", 0.0) / 10.0, 1.0)
            kerning_score_norm  = min(kerning_result.get("cv", 0.0)         /  2.0, 1.0)
            spacing_score_norm  = min(spacing_result.get("diff", 0.0)       /  2.0, 1.0)
            aa_score_norm       = min(antialias_result.get("sharpness_diff", 0.0) / 400.0, 1.0)
            font_score_norm     = max(0.0, min(font_result.get("score", 0.0), 1.0))

            # Weighted combination — font and AA carry the most weight because
            # they are reliable edit signals; baseline/kerning/spacing are noisy
            # on genuine scanned documents and serve as support only.
            region_score = (
                0.15 * baseline_score_norm
                + 0.15 * kerning_score_norm
                + 0.15 * spacing_score_norm
                + 0.35 * font_score_norm
                + 0.20 * aa_score_norm
            )

            region_scores.append(region_score)

            # Collect findings from ALL five sub-analyses
            all_findings.extend(
                baseline_result["findings"]
                + kerning_result["findings"]
                + spacing_result["findings"]
                + font_result["findings"]
                + antialias_result["findings"]
            )

            if region_score > 0.30:
                suspicious_boxes.append(
                    BoundingBox(
                        x=x,
                        y=y,
                        width=w,
                        height=h,
                        confidence=float(region_score),
                        label="text_forensics",
                    )
                )

        composite = round(float(max(region_scores)) if region_scores else 0.0, 4)

        confidence = min(0.95, 0.35 + len(region_scores) * 0.01)

        raw_data = {
            "regions_analyzed": len(regions),
            "suspicious_regions": len(suspicious_boxes),
            "max_region_score": composite,
        }

        logger.info(
            "[text_forensics] score=%.3f regions=%d suspicious=%d",
            composite,
            len(regions),
            len(suspicious_boxes),
        )

        return self._make_score(
            score=composite,
            confidence=confidence,
            findings=all_findings,
            raw_data=raw_data,
            bounding_boxes=suspicious_boxes,
        )