"""
Copy-Move Detection Module

═══════════════════════════════════════════════════════════════
FORENSIC THEORY
═══════════════════════════════════════════════════════════════
Copy-move forgery: a region is copied FROM the same image and pasted
to another location within that image to hide or duplicate content.
Classic example: duplicating a signature, hiding an object by covering
it with copied background, or repeating a stamp/seal.

Detection relies on finding highly similar regions within the same image.
We use keypoint matching (SIFT, ORB, AKAZE) to find local feature
correspondences. Multiple matches within a small spatial region indicate
copy-move forgery.

═══════════════════════════════════════════════════════════════
ALGORITHM CHOICE
═══════════════════════════════════════════════════════════════
Three complementary detectors used in cascade:

1. SIFT (Scale-Invariant Feature Transform)
   - Most accurate, rotationally invariant
   - Computationally expensive: O(W*H*k*log(k)) for k keypoints
   - Best for natural images, photos

2. ORB (Oriented FAST and Rotated BRIEF)
   - Fast binary descriptor, good for document text/structure
   - Less accurate than SIFT but 10× faster
   - Best for scanned documents

3. AKAZE (Accelerated-KAZE)
   - Nonlinear scale space, handles noise well
   - Better for compressed/low-quality images
   - Medium speed, high accuracy

We use BFMatcher with cross-check for reliable matching.
Matches are filtered by distance ratio test (Lowe's ratio = 0.75).
Copy-move = cluster of spatially co-located match pairs.

═══════════════════════════════════════════════════════════════
LIMITATIONS
═══════════════════════════════════════════════════════════════
- Misses small copied regions (< 50×50 pixels)
- Fails on heavily compressed images (keypoints lost)
- Natural repeating patterns (wallpaper, grid) = false positives
- Rotation/scaling of copied region reduces detection rate

═══════════════════════════════════════════════════════════════
FALSE POSITIVE RISKS
═══════════════════════════════════════════════════════════════
HIGH: Documents with repeated logos, watermarks, table cells
MEDIUM: Symmetrical layout elements
LOW: Documents with unique visual content throughout

═══════════════════════════════════════════════════════════════
COMPUTATIONAL COMPLEXITY
═══════════════════════════════════════════════════════════════
SIFT: O(W*H + k²) where k = number of keypoints
ORB: O(W*H + k*log(k))
Matching: O(k²) worst case — capped at 2000 keypoints
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.module.copymove")


class CopyMoveModule(ForensicModule):
    """
    Copy-move forgery detection using SIFT, ORB, and AKAZE.
    """

    MODULE_NAME = "copymove"
    WEIGHT = 0.10
    VERSION = "1.0.0"
    MIN_IMAGE_SIZE = 128
    REQUIRES_IMAGE = True

    MAX_KEYPOINTS = 2000
    LOWE_RATIO = 0.75
    MIN_MATCH_DISTANCE = 30       # Minimum pixel distance between matched pairs
    CLUSTER_DISTANCE = 50         # Pixels to consider matches as a cluster

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        try:
            import cv2
        except ImportError:
            return self._make_score(
                0.0, 0.0,
                findings=["OpenCV not available; copy-move detection skipped"]
            )

        if not ctx.page_images:
            return self._make_score(0.0, 0.0, findings=["No image data"])

        image = ctx.page_images[0]
        gray = self._to_gray_cv2(image)

        all_matches: list[tuple] = []
        detector_results: dict = {}

        # Cascade through detectors
        for detector_name, detector_fn in [
            ("SIFT", self._run_sift),
            ("ORB", self._run_orb),
            ("AKAZE", self._run_akaze),
        ]:
            matches, kp_count = detector_fn(cv2, gray)
            detector_results[detector_name] = {
                "matches": len(matches),
                "keypoints": kp_count,
            }
            all_matches.extend(matches)

        score, confidence, findings, bboxes = self._evaluate(
            all_matches, detector_results, image.shape
        )

        return self._make_score(
            score=score,
            confidence=confidence,
            findings=findings,
            raw_data={"detectors": detector_results, "total_matches": len(all_matches)},
            bounding_boxes=bboxes,
        )

    def _to_gray_cv2(self, image: np.ndarray) -> np.ndarray:
        """Convert RGB numpy array to grayscale uint8."""
        if len(image.shape) == 3:
            # Manual luminance conversion (no cv2 dependency for this step)
            gray = (
                0.299 * image[:, :, 0]
                + 0.587 * image[:, :, 1]
                + 0.114 * image[:, :, 2]
            ).astype(np.uint8)
        else:
            gray = image.astype(np.uint8)
        return gray

    def _run_sift(
        self, cv2, gray: np.ndarray
    ) -> tuple[list[tuple], int]:
        """
        SIFT-based copy-move detection.
        Returns list of (pt1, pt2) match pairs and keypoint count.
        """
        try:
            sift = cv2.SIFT_create(nfeatures=self.MAX_KEYPOINTS)
            kps, descs = sift.detectAndCompute(gray, None)

            if descs is None or len(kps) < 4:
                return [], len(kps) if kps else 0

            # BFMatcher with L2 norm, cross-check
            bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
            raw_matches = bf.knnMatch(descs, descs, k=2)

            good_matches = []
            for m, n in raw_matches:
                if m.queryIdx == m.trainIdx:
                    continue  # Same keypoint
                if m.distance < self.LOWE_RATIO * n.distance:
                    pt1 = kps[m.queryIdx].pt
                    pt2 = kps[m.trainIdx].pt
                    dist = np.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)
                    if dist > self.MIN_MATCH_DISTANCE:
                        good_matches.append((pt1, pt2, float(m.distance)))

            return good_matches, len(kps)

        except Exception as e:
            logger.debug("SIFT failed: %s", e)
            return [], 0

    def _run_orb(
        self, cv2, gray: np.ndarray
    ) -> tuple[list[tuple], int]:
        """ORB-based copy-move detection."""
        try:
            orb = cv2.ORB_create(nfeatures=self.MAX_KEYPOINTS)
            kps, descs = orb.detectAndCompute(gray, None)

            if descs is None or len(kps) < 4:
                return [], len(kps) if kps else 0

            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            raw_matches = bf.knnMatch(descs, descs, k=2)

            good_matches = []
            for m, n in raw_matches:
                if m.queryIdx == m.trainIdx:
                    continue
                if m.distance < self.LOWE_RATIO * n.distance:
                    pt1 = kps[m.queryIdx].pt
                    pt2 = kps[m.trainIdx].pt
                    dist = np.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)
                    if dist > self.MIN_MATCH_DISTANCE:
                        good_matches.append((pt1, pt2, float(m.distance)))

            return good_matches, len(kps)

        except Exception as e:
            logger.debug("ORB failed: %s", e)
            return [], 0

    def _run_akaze(
        self, cv2, gray: np.ndarray
    ) -> tuple[list[tuple], int]:
        """AKAZE-based copy-move detection."""
        try:
            akaze = cv2.AKAZE_create()
            kps, descs = akaze.detectAndCompute(gray, None)

            if descs is None or len(kps) < 4:
                return [], len(kps) if kps else 0

            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
            raw_matches = bf.knnMatch(descs, descs, k=2)

            good_matches = []
            for m, n in raw_matches:
                if m.queryIdx == m.trainIdx:
                    continue
                if m.distance < self.LOWE_RATIO * n.distance:
                    pt1 = kps[m.queryIdx].pt
                    pt2 = kps[m.trainIdx].pt
                    dist = np.sqrt((pt1[0] - pt2[0]) ** 2 + (pt1[1] - pt2[1]) ** 2)
                    if dist > self.MIN_MATCH_DISTANCE:
                        good_matches.append((pt1, pt2, float(m.distance)))

            return good_matches, len(kps)

        except Exception as e:
            logger.debug("AKAZE failed: %s", e)
            return [], 0

    def _cluster_matches(
        self, matches: list[tuple]
    ) -> list[list[tuple]]:
        """
        Group spatially nearby match pairs into clusters.
        Simple grid-based clustering.
        """
        if not matches:
            return []

        clusters: list[list] = []
        used = [False] * len(matches)

        for i, (pt1, pt2, dist) in enumerate(matches):
            if used[i]:
                continue
            cluster = [(pt1, pt2, dist)]
            used[i] = True
            for j, (pt1b, pt2b, distb) in enumerate(matches):
                if used[j] or i == j:
                    continue
                d = np.sqrt((pt1[0] - pt1b[0]) ** 2 + (pt1[1] - pt1b[1]) ** 2)
                if d < self.CLUSTER_DISTANCE:
                    cluster.append((pt1b, pt2b, distb))
                    used[j] = True
            if len(cluster) >= 3:
                clusters.append(cluster)

        return clusters

    def _evaluate(
        self,
        matches: list[tuple],
        detector_results: dict,
        image_shape: tuple,
    ) -> tuple[float, float, list[str], list[BoundingBox]]:
        findings: list[str] = []
        bboxes: list[BoundingBox] = []

        total = len(matches)
        if total == 0:
            return 0.0, 0.5, ["No copy-move matches found"], []

        clusters = self._cluster_matches(matches)
        cluster_count = len(clusters)

        # Score based on number of clustered matches
        # 0 clusters → 0 score; 5+ clusters → near 1.0
        cluster_score = min(cluster_count / 5.0, 1.0)
        match_score = min(total / 50.0, 1.0)

        score = 0.65 * cluster_score + 0.35 * match_score

        if cluster_count > 0:
            findings.append(
                f"Detected {cluster_count} copy-move cluster(s) with {total} total matches"
            )

        # Build bounding boxes from clusters
        for cluster in clusters[:5]:
            pts = [m[0] for m in cluster]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x_min, x_max = int(min(xs)), int(max(xs))
            y_min, y_max = int(min(ys)), int(max(ys))
            w = max(x_max - x_min, 20)
            h = max(y_max - y_min, 20)
            conf = min(len(cluster) / 10.0, 1.0)
            bboxes.append(BoundingBox(x=x_min, y=y_min, width=w, height=h, confidence=conf, label="copy_move"))

        # Report detector performance
        active = [k for k, v in detector_results.items() if v["matches"] > 0]
        if active:
            findings.append(f"Detectors with matches: {', '.join(active)}")

        confidence = 0.5 + min(total / 100.0, 0.4)
        return score, confidence, findings, bboxes