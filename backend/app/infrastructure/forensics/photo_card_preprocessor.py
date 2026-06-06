"""
photo_card_preprocessor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROBLEM SOLVED
━━━━━━━━━━━━━━
When a physical ID card is photographed (rather than flatbed-scanned),
the forensic modules produce systematic false positives:

  MODULE          SCORE  ROOT CAUSE
  ─────────────────────────────────────────────────────
  Font            0.70   Holographic strip micro-patterns
                         flagged as "mixed font sources"
  Frequency       0.67   QR code grid + hologram create
                         legitimate FFT checkerboard peaks
  GAN             0.47   Bokeh (out-of-focus) background
                         mimics AI-generated smooth texture
  Color           0.55   Intentional card color zones (orange
                         header, teal footer) + background
  Edge            0.40   Physical hologram creates optical
                         double-edge artifacts
  ─────────────────────────────────────────────────────
  Result: score=30, genuine=false on a REAL Aadhaar card

Fix: add this preprocessor to the pipeline. When it detects a
"photo-of-card" input, it:
  1. Segments the card body from the background (bokeh mask)
  2. Masks the holographic strip from font/frequency/edge analysis
  3. Masks the QR code region from frequency analysis
  4. Returns an adjusted ForensicContext with photo_mode=True

Then each affected module checks ctx.photo_mode and uses the
masked image for analysis instead of the full frame.
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
from PIL import Image
from scipy import ndimage

logger = logging.getLogger("docfraud.preprocessor.photo")


class PhotoCardDetector:
    """
    Detects whether the input is a photograph of a physical card
    (vs a flat scanner output or digital document).

    Signals:
    - Non-white background in corners (card not edge-to-edge)
    - Smooth corner regions (bokeh blur from camera focus)
    - High overall tonal dynamic range (camera exposure curve)
    """

    CORNER_SAMPLE_FRACTION = 0.08   # sample this fraction of min(H,W)
    WHITE_THRESHOLD = 200           # corners above this = likely scanner/plain bg
    BOKEH_STD_THRESHOLD = 60        # corners below this std = smooth/blurred bg
    PHOTO_GLOBAL_STD_THRESHOLD = 55 # overall image std above this = photo

    def detect(self, image_arr: np.ndarray) -> Tuple[bool, dict]:
        """
        Returns (is_photo: bool, signals: dict)
        """
        h, w = image_arr.shape[:2]
        cs = int(min(h, w) * self.CORNER_SAMPLE_FRACTION)

        corners = [
            image_arr[:cs, :cs],
            image_arr[:cs, w - cs:],
            image_arr[h - cs:, :cs],
            image_arr[h - cs:, w - cs:],
        ]

        corner_means = [float(c.mean()) for c in corners]
        corner_stds  = [float(c.std())  for c in corners]

        has_non_white_bg = any(m < self.WHITE_THRESHOLD for m in corner_means)
        has_smooth_bg    = float(np.mean(corner_stds)) < self.BOKEH_STD_THRESHOLD
        high_dr          = float(image_arr.std()) > self.PHOTO_GLOBAL_STD_THRESHOLD

        is_photo = has_non_white_bg and has_smooth_bg and high_dr

        signals = {
            "corner_means":      [round(m) for m in corner_means],
            "corner_stds":       [round(s, 1) for s in corner_stds],
            "has_non_white_bg":  has_non_white_bg,
            "has_smooth_bg":     has_smooth_bg,
            "high_dynamic_range": high_dr,
            "overall_std":       round(float(image_arr.std()), 2),
        }
        return is_photo, signals


class CardRegionSegmenter:
    """
    Produces masks for the three regions that cause false positives:

    1. bokeh_mask      — background pixels (blurry/out-of-focus)
                         → exclude from GAN, Color, AI modules
    2. hologram_mask   — holographic strip (right ~15% of card)
                         → exclude from Font, Edge modules
    3. qr_mask         — QR code bounding box
                         → exclude from Frequency module
    """

    BOKEH_SHARPNESS_PERCENTILE  = 25    # bottom quartile = background
    BOKEH_PATCH_SIZE            = 128   # px — Laplacian patch side
    HOLOGRAM_FRACTION           = 0.15  # rightmost fraction of card
    QR_SEARCH_PATCH             = 32    # px — grid search patch size
    QR_MIN_VARIANCE             = 80.0  # minimum std to call a region QR

    def compute_masks(
        self, image_arr: np.ndarray
    ) -> dict[str, Optional[np.ndarray]]:
        """
        Returns dict of binary masks (True = include, False = exclude).
        All masks are same shape as image_arr (H, W).
        """
        h, w = image_arr.shape[:2]
        gray = np.mean(image_arr, axis=2).astype(np.float32)

        return {
            "bokeh_mask":    self._bokeh_mask(gray, h, w),
            "hologram_mask": self._hologram_mask(h, w),
            "qr_mask":       self._qr_mask(gray, h, w),
        }

    def _bokeh_mask(
        self, gray: np.ndarray, h: int, w: int
    ) -> np.ndarray:
        """
        True = sharp (card content) / False = blurry (background).
        Uses Laplacian variance per patch; blurry patches get excluded.
        """
        p = self.BOKEH_PATCH_SIZE
        sharp_map = np.zeros((h // p, w // p), dtype=np.float32)
        for i, y in enumerate(range(0, h - p, p)):
            for j, x in enumerate(range(0, w - p, p)):
                lap = ndimage.laplace(gray[y : y + p, x : x + p])
                sharp_map[i, j] = float(lap.var())

        threshold = float(np.percentile(sharp_map, self.BOKEH_SHARPNESS_PERCENTILE))

        # Upscale to full resolution
        full_mask = np.kron(sharp_map >= threshold,
                            np.ones((p, p), dtype=bool))
        # Pad/crop to exact size
        full_mask = full_mask[:h, :w]
        if full_mask.shape != (h, w):
            pad_h = h - full_mask.shape[0]
            pad_w = w - full_mask.shape[1]
            full_mask = np.pad(full_mask, ((0, pad_h), (0, pad_w)),
                               mode="edge")
        return full_mask

    def _hologram_mask(self, h: int, w: int) -> np.ndarray:
        """
        True = card body / False = holographic strip region.
        The Aadhaar holographic strip is on the right ~15% of the card.
        """
        mask = np.ones((h, w), dtype=bool)
        holo_start = int(w * (1.0 - self.HOLOGRAM_FRACTION))
        mask[:, holo_start:] = False
        return mask

    def _qr_mask(
        self, gray: np.ndarray, h: int, w: int
    ) -> np.ndarray:
        """
        True = non-QR region / False = QR code bounding box.
        Detects by finding the highest-variance grid region.
        """
        p = self.QR_SEARCH_PATCH
        mask = np.ones((h, w), dtype=bool)

        max_var = 0.0
        best_loc = None

        for y in range(0, h - p * 4, p):
            for x in range(0, w - p * 4, p):
                region = gray[y : y + p * 4, x : x + p * 4]
                var = float(region.std())
                if var > max_var:
                    max_var = var
                    best_loc = (x, y)

        if best_loc and max_var >= self.QR_MIN_VARIANCE:
            bx, by = best_loc
            qr_size = p * 4
            # Add 20px margin
            y0 = max(0, by - 20)
            y1 = min(h, by + qr_size + 20)
            x0 = max(0, bx - 20)
            x1 = min(w, bx + qr_size + 20)
            mask[y0:y1, x0:x1] = False
            logger.debug("QR code masked at (%d,%d) var=%.1f", bx, by, max_var)

        return mask


class PhotoAwareImagePreparer:
    """
    High-level entry point.  Call prepare() before passing the image
    to any forensic module.

    Usage in analysis_service.py:
    ─────────────────────────────
    from app.infrastructure.forensics.photo_card_preprocessor import PhotoAwareImagePreparer

    preparer = PhotoAwareImagePreparer()

    # In analyze(), after preprocessing but before running modules:
    photo_result = preparer.prepare(ctx.page_images[0])
    ctx.photo_mode = photo_result["is_photo"]
    ctx.photo_masks = photo_result["masks"]   # store on context
    ctx.analysis_image = photo_result["card_only"]  # cropped/masked image

    Then in each module's _analyze():
        image = ctx.analysis_image if hasattr(ctx, 'analysis_image') else ctx.page_images[0]
    """

    def __init__(self):
        self.detector   = PhotoCardDetector()
        self.segmenter  = CardRegionSegmenter()

    def prepare(self, image_arr: np.ndarray) -> dict:
        is_photo, signals = self.detector.detect(image_arr)
        masks = {}
        card_only = image_arr

        if is_photo:
            logger.info(
                "Photo-of-card detected (std=%.1f). Applying bokeh/hologram/QR masks.",
                signals["overall_std"],
            )
            masks = self.segmenter.compute_masks(image_arr)

            # card_only: apply bokeh mask (zero out background)
            bokeh = masks["bokeh_mask"]
            card_only = image_arr.copy()
            card_only[~bokeh] = 128   # neutral gray for background pixels

        return {
            "is_photo":  is_photo,
            "signals":   signals,
            "masks":     masks,
            "card_only": card_only,
        }


# ──────────────────────────────────────────────────────────────────
# MODULE-LEVEL INTEGRATION GUIDE
# ──────────────────────────────────────────────────────────────────
#
# 1. FONT MODULE  (app/modules/color/color_font_metadata_modules.py)
#    In FontAnalysisModule._analyze():
#
#      if getattr(ctx, 'photo_mode', False) and 'hologram_mask' in getattr(ctx, 'photo_masks', {}):
#          holo_mask = ctx.photo_masks['hologram_mask']
#          image = ctx.page_images[0].copy()
#          image[~holo_mask] = 128   # mask holographic strip
#      else:
#          image = ctx.page_images[0]
#
# 2. FREQUENCY MODULE  (app/modules/ai_detection/ai_gan_frequency_modules.py)
#    In FrequencyAnalysisModule._analyze():
#
#      if getattr(ctx, 'photo_mode', False):
#          image = ctx.analysis_image   # bokeh-masked
#          if 'qr_mask' in getattr(ctx, 'photo_masks', {}):
#              qr_mask = ctx.photo_masks['qr_mask']
#              image = image.copy()
#              image[~qr_mask] = int(image[qr_mask].mean())  # fill QR region with mean
#
# 3. GAN MODULE  (same file as Frequency)
#    In GANDetectionModule._analyze():
#
#      if getattr(ctx, 'photo_mode', False):
#          image = ctx.analysis_image   # bokeh-masked already
#      else:
#          image = ctx.page_images[0]
#
# 4. COLOR MODULE  (app/modules/color/color_font_metadata_modules.py)
#    In ColorConsistencyModule._analyze():
#
#      if getattr(ctx, 'photo_mode', False):
#          # Only compare illumination within the card body, not full frame
#          image = ctx.analysis_image
#      else:
#          image = ctx.page_images[0]
#
# 5. EDGE MODULE  (app/modules/edge/edge_module.py)
#    In EdgeArtifactModule._analyze():
#
#      if getattr(ctx, 'photo_mode', False) and 'hologram_mask' in getattr(ctx, 'photo_masks', {}):
#          image = ctx.page_images[0].copy()
#          image[~ctx.photo_masks['hologram_mask']] = 128
#      else:
#          image = ctx.page_images[0]
#
# ──────────────────────────────────────────────────────────────────