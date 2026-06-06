# # # """
# # # Fraud Scoring Engine

# # # ═══════════════════════════════════════════════════════════════
# # # THEORY
# # # ═══════════════════════════════════════════════════════════════
# # # The scoring engine aggregates signals from all forensic modules
# # # into a single fraud score (0-100) and categorical risk level.

# # # Design decisions:
# # # 1. Weighted linear combination as the base
# # # 2. Evidence amplification: when multiple modules agree, score amplified
# # # 3. Evidence dampening: when only one module fires, confidence reduced
# # # 4. Module confidence weighting: low-confidence modules contribute less
# # # 5. Outlier handling: a single module at 0.95 triggers minimum HIGH risk
# # # 6. PDF-specific and image-specific boosting

# # # Risk Levels:
# # #   0-20  → GENUINE        (very likely authentic)
# # #   21-40 → LOW RISK       (minor anomalies, likely clean)
# # #   41-60 → MEDIUM RISK    (multiple signals, review recommended)
# # #   61-80 → HIGH RISK      (strong tampering indicators)
# # #   81-100→ CRITICAL RISK  (definite manipulation detected)

# # # Verdict Flags:
# # #   edited        = any regional modification (ELA/CopyMove/Edge high)
# # #   ai_generated  = full AI synthesis (AI+GAN+Frequency all high)
# # #   ai_assisted   = partial AI (AI high but other modules low)
# # #   tampered      = structural changes (PDF/Metadata high)
# # #   genuine       = all modules low, high confidence
# # # """

# # # from __future__ import annotations

# # # import logging
# # # from datetime import datetime
# # # from typing import Optional

# # # from app.core.config import settings
# # # from app.domain.entities.document import (
# # #     ForensicContext,
# # #     FraudVerdict,
# # #     ModuleScore,
# # #     RiskLevel,
# # # )

# # # logger = logging.getLogger("docfraud.scoring")


# # # class FraudScoringEngine:
# # #     """
# # #     Aggregates forensic module results into a final FraudVerdict.
# # #     """

# # #     # Module weights — must sum to 1.0
# # #     MODULE_WEIGHTS: dict[str, float] = {
# # #         "ela":            0.20,
# # #         "noise":          0.12,
# # #         "copymove":       0.10,
# # #         "edge":           0.08,
# # #         "color":          0.08,
# # #         "font":           0.10,
# # #         "ai_detection":   0.15,
# # #         "gan":            0.07,
# # #         "frequency":      0.05,
# # #         "layout":         0.05,
# # #         # Supplementary modules (not in weighted sum, but affect flags)
# # #         "metadata":       0.00,
# # #         "pdf_structure":  0.00,
# # #     }

# # #     # Thresholds for boolean flags
# # #     EDITED_MODULES = {"ela", "copymove", "edge", "noise"}
# # #     AI_MODULES = {"ai_detection", "gan", "frequency"}
# # #     TAMPER_MODULES = {"metadata", "pdf_structure", "ela"}

# # #     def compute(
# # #         self,
# # #         ctx: ForensicContext,
# # #         heatmap_path: Optional[str],
# # #         processing_start: datetime,
# # #     ) -> FraudVerdict:
# # #         """
# # #         Compute the final fraud verdict from all module scores.
# # #         """
# # #         scores = ctx.module_scores
# # #         active_scores = {
# # #             name: result
# # #             for name, result in scores.items()
# # #             if not result.skipped and result.error is None
# # #         }

# # #         # ── Step 1: Weighted base score ──────────────────────────
# # #         weighted_sum = 0.0
# # #         total_weight = 0.0

# # #         for module_name, weight in self.MODULE_WEIGHTS.items():
# # #             if weight == 0.0:
# # #                 continue
# # #             result = active_scores.get(module_name)
# # #             if result is None:
# # #                 continue
# # #             # Scale contribution by module confidence
# # #             effective_weight = weight * result.confidence
# # #             weighted_sum += effective_weight * result.score
# # #             total_weight += effective_weight

# # #         base_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

# # #         # ── Step 2: Evidence amplification ───────────────────────
# # #         # If 3+ modules score > 0.5: boost by 10%
# # #         high_modules = [
# # #             r for r in active_scores.values()
# # #             if r.score > 0.5 and r.module_name in self.MODULE_WEIGHTS
# # #         ]
# # #         if len(high_modules) >= 3:
# # #             base_score = min(base_score * 1.12, 1.0)
# # #         elif len(high_modules) >= 5:
# # #             base_score = min(base_score * 1.20, 1.0)

# # #         # ── Step 3: Critical single-module override ───────────────
# # #         # If any module scores >= 0.85 (strong signal), enforce minimum HIGH
# # #         max_single = max(
# # #             (r.score for r in active_scores.values()
# # #              if r.module_name in self.MODULE_WEIGHTS),
# # #             default=0.0
# # #         )
# # #         if max_single >= 0.85:
# # #             base_score = max(base_score, 0.65)  # Minimum HIGH

# # #         # ── Step 4: Supplementary module boosting ─────────────────
# # #         meta_result = active_scores.get("metadata")
# # #         pdf_result = active_scores.get("pdf_structure")

# # #         if meta_result and meta_result.score > 0.5:
# # #             base_score = min(base_score + 0.08, 1.0)
# # #         if pdf_result and pdf_result.score > 0.5:
# # #             base_score = min(base_score + 0.10, 1.0)

# # #         # ── Step 5: Convert to 0-100 scale ────────────────────────
# # #         fraud_score = base_score * 100.0

# # #         # ── Step 6: Risk level ────────────────────────────────────
# # #         risk_level = RiskLevel.from_score(fraud_score)

# # #         # ── Step 7: Boolean verdicts ──────────────────────────────
# # #         edited = self._flag_edited(active_scores)
# # #         ai_generated = self._flag_ai_generated(active_scores)
# # #         ai_assisted = self._flag_ai_assisted(active_scores, ai_generated)
# # #         tampered = self._flag_tampered(active_scores)
# # #         genuine = self._flag_genuine(fraud_score, active_scores)

# # #         # ── Step 8: Overall confidence ────────────────────────────
# # #         confidences = [
# # #             r.confidence for r in active_scores.values()
# # #             if r.module_name in self.MODULE_WEIGHTS
# # #         ]
# # #         overall_confidence = float(sum(confidences) / len(confidences)) if confidences else 0.5

# # #         # ── Step 9: Collect findings ──────────────────────────────
# # #         findings = self._collect_findings(active_scores)

# # #         # ── Step 10: Module score summary ────────────────────────
# # #         module_score_map = {
# # #             name: result.score
# # #             for name, result in scores.items()
# # #         }

# # #         # ── Step 11: Collect bounding boxes ──────────────────────
# # #         all_bboxes = []
# # #         for result in scores.values():
# # #             for bbox in result.bounding_boxes:
# # #                 all_bboxes.append(bbox.as_dict)

# # #         # ── Step 12: Recommendation ───────────────────────────────
# # #         recommendation = self._generate_recommendation(
# # #             fraud_score, risk_level, edited, ai_generated, tampered, findings
# # #         )

# # #         # ── Step 13: Metadata extract ─────────────────────────────
# # #         metadata_dict = {}
# # #         if ctx.metadata:
# # #             meta = ctx.metadata
# # #             metadata_dict = {
# # #                 "creator": meta.creator,
# # #                 "producer": meta.producer,
# # #                 "author": meta.author,
# # #                 "software": meta.software,
# # #                 "creation_date": meta.creation_date.isoformat() if meta.creation_date else None,
# # #                 "modification_date": meta.modification_date.isoformat() if meta.modification_date else None,
# # #                 "camera_make": meta.camera_make,
# # #                 "camera_model": meta.camera_model,
# # #             }

# # #         processing_ms = int(
# # #             (datetime.utcnow() - processing_start).total_seconds() * 1000
# # #         )

# # #         verdict = FraudVerdict(
# # #             document_id=ctx.document_id,
# # #             job_id=ctx.job_id,
# # #             fraud_score=round(fraud_score, 2),
# # #             risk_level=risk_level,
# # #             edited=edited,
# # #             ai_generated=ai_generated,
# # #             ai_assisted=ai_assisted,
# # #             tampered=tampered,
# # #             genuine=genuine,
# # #             confidence=round(overall_confidence, 4),
# # #             findings=findings,
# # #             heatmap_path=heatmap_path,
# # #             module_scores=module_score_map,
# # #             bounding_boxes=all_bboxes,
# # #             recommendation=recommendation,
# # #             metadata=metadata_dict,
# # #             processing_time_ms=processing_ms,
# # #         )

# # #         logger.info(
# # #             "Verdict: score=%.2f risk=%s edited=%s ai=%s tampered=%s genuine=%s [%dms]",
# # #             fraud_score, risk_level.value, edited, ai_generated, tampered, genuine, processing_ms,
# # #         )

# # #         return verdict

# # #     # ─────────────────────────────────────────────
# # #     # Boolean flag logic
# # #     # ─────────────────────────────────────────────

# # #     def _flag_edited(self, scores: dict[str, ModuleScore]) -> bool:
# # #         """Edited = strong signal from regional-modification modules."""
# # #         editing_scores = [
# # #             scores[m].score
# # #             for m in self.EDITED_MODULES
# # #             if m in scores and not scores[m].skipped
# # #         ]
# # #         if not editing_scores:
# # #             return False
# # #         # At least 2 editing modules > threshold, OR 1 module very high
# # #         above_thresh = sum(s > settings.edited_threshold for s in editing_scores)
# # #         max_score = max(editing_scores)
# # #         return above_thresh >= 2 or max_score > 0.75

# # #     def _flag_ai_generated(self, scores: dict[str, ModuleScore]) -> bool:
# # #         """AI generated = strong signal from all AI-specific modules."""
# # #         ai_scores = [
# # #             scores[m].score
# # #             for m in self.AI_MODULES
# # #             if m in scores and not scores[m].skipped
# # #         ]
# # #         if not ai_scores:
# # #             return False
# # #         above = sum(s > settings.ai_generated_threshold for s in ai_scores)
# # #         return above >= 2

# # #     def _flag_ai_assisted(
# # #         self, scores: dict[str, ModuleScore], ai_generated: bool
# # #     ) -> bool:
# # #         """AI assisted = at least 2 AI-specific modules show elevated signal."""
# # #         if ai_generated:
# # #             return False
# # #         ai_scores = [
# # #             scores[m].score
# # #             for m in self.AI_MODULES
# # #             if m in scores and not scores[m].skipped
# # #         ]
# # #         if not ai_scores:
# # #             return False
# # #         above_thresh = sum(s > settings.ai_assisted_threshold for s in ai_scores)
# # #         return above_thresh >= 2


# # #     def _flag_tampered(self, scores: dict[str, ModuleScore]) -> bool:
# # #         """Tampered = structural modification detected."""
# # #         for m in self.TAMPER_MODULES:
# # #             if m in scores and not scores[m].skipped:
# # #                 if scores[m].score > settings.tampered_threshold:
# # #                     return True
# # #         return False

# # #     def _flag_genuine(
# # #         self, fraud_score: float, scores: dict[str, ModuleScore]
# # #     ) -> bool:
# # #         """Genuine = score in GENUINE band AND no single weighted module is strongly elevated."""
# # #         if fraud_score > 20:
# # #             return False
# # #         weighted_modules = {
# # #             name for name, w in self.MODULE_WEIGHTS.items() if w > 0.0
# # #         }
# # #         max_score = max(
# # #             (r.score for name, r in scores.items()
# # #              if name in weighted_modules and not r.skipped),
# # #             default=0.0,
# # #         )
# # #         return max_score < 0.45

# # #     # ─────────────────────────────────────────────
# # #     # Helpers
# # #     # ─────────────────────────────────────────────

# # #     def _collect_findings(self, scores: dict[str, ModuleScore]) -> list[str]:
# # #         """Collect all findings from modules, deduplicated, sorted by module."""
# # #         all_findings = []
# # #         for result in scores.values():
# # #             for finding in result.findings:
# # #                 entry = f"[{result.module_name.upper()}] {finding}"
# # #                 if entry not in all_findings:
# # #                     all_findings.append(entry)
# # #         return all_findings

# # #     def _generate_recommendation(
# # #         self,
# # #         score: float,
# # #         risk: RiskLevel,
# # #         edited: bool,
# # #         ai_generated: bool,
# # #         tampered: bool,
# # #         findings: list[str],
# # #     ) -> str:
# # #         """Generate a human-readable recommendation based on verdict."""
# # #         if risk == RiskLevel.GENUINE:
# # #             return (
# # #                 "Document appears authentic. No significant manipulation indicators detected. "
# # #                 "Standard acceptance procedures apply."
# # #             )
# # #         elif risk == RiskLevel.LOW:
# # #             return (
# # #                 "Minor anomalies detected. Document is likely authentic but warrants a "
# # #                 "secondary review of flagged regions before acceptance."
# # #             )
# # #         elif risk == RiskLevel.MEDIUM:
# # #             parts = ["Multiple forensic signals detected."]
# # #             if edited:
# # #                 parts.append("Evidence of regional editing found.")
# # #             if ai_generated:
# # #                 parts.append("AI generation artifacts present.")
# # #             parts.append(
# # #                 "Manual verification of document origin and a comparison with "
# # #                 "original source is strongly recommended."
# # #             )
# # #             return " ".join(parts)
# # #         elif risk == RiskLevel.HIGH:
# # #             parts = ["Significant manipulation indicators."]
# # #             if edited:
# # #                 parts.append("Document has been edited.")
# # #             if tampered:
# # #                 parts.append("Structural tampering detected.")
# # #             if ai_generated:
# # #                 parts.append("Document is likely AI-generated.")
# # #             parts.append(
# # #                 "Reject document and request original. Escalate to fraud team if needed."
# # #             )
# # #             return " ".join(parts)
# # #         else:  # CRITICAL
# # #             parts = ["CRITICAL: High-confidence manipulation detected."]
# # #             if ai_generated:
# # #                 parts.append("Document is AI-generated or AI-assisted.")
# # #             if edited:
# # #                 parts.append("Extensive editing detected across multiple regions.")
# # #             if tampered:
# # #                 parts.append("PDF structure shows clear tampering.")
# # #             parts.append(
# # #                 "REJECT immediately. Do not process. Escalate to security/fraud team "
# # #                 "for investigation. Preserve original file as evidence."
# # #             )
# # #             return " ".join(parts)


# # # # """
# # # # Fraud Scoring Engine

# # # # ═══════════════════════════════════════════════════════════════
# # # # THEORY
# # # # ═══════════════════════════════════════════════════════════════
# # # # The scoring engine aggregates signals from all forensic modules
# # # # into a single fraud score (0-100) and categorical risk level.

# # # # Design decisions:
# # # # 1. Weighted linear combination as the base
# # # # 2. Evidence amplification: when multiple modules agree, score amplified
# # # # 3. Evidence dampening: when only one module fires, confidence reduced
# # # # 4. Module confidence weighting: low-confidence modules contribute less
# # # # 5. Outlier handling: a single module at 0.85 triggers minimum HIGH risk
# # # # 6. PDF-specific and image-specific boosting
# # # # 7. Screenshot/PNG-aware: ELA and AI-detection weights redistributed
# # # #    when those modules produce near-zero scores on non-JPEG inputs.

# # # # Risk Levels:
# # # #   0-20  → GENUINE        (very likely authentic)
# # # #   21-40 → LOW RISK       (minor anomalies, likely clean)
# # # #   41-60 → MEDIUM RISK    (multiple signals, review recommended)
# # # #   61-80 → HIGH RISK      (strong tampering indicators)
# # # #   81-100→ CRITICAL RISK  (definite manipulation detected)

# # # # Verdict Flags:
# # # #   edited        = any regional modification (ELA/CopyMove/Edge high)
# # # #   ai_generated  = full AI synthesis (AI+GAN+Frequency all high)
# # # #   ai_assisted   = partial AI (AI high but other modules low)
# # # #   tampered      = structural changes (PDF/Metadata high)
# # # #   genuine       = all modules low, high confidence
# # # # """

# # # # from __future__ import annotations

# # # # import logging
# # # # from datetime import datetime
# # # # from typing import Optional

# # # # from app.core.config import settings
# # # # from app.domain.entities.document import (
# # # #     ForensicContext,
# # # #     FraudVerdict,
# # # #     ModuleScore,
# # # #     RiskLevel,
# # # # )

# # # # logger = logging.getLogger("docfraud.scoring")


# # # # class FraudScoringEngine:
# # # #     """
# # # #     Aggregates forensic module results into a final FraudVerdict.
# # # #     """

# # # #     # ── Base module weights ─────────────────────────────────────
# # # #     # These are STARTING weights — the engine may redistribute them
# # # #     # dynamically based on document type and module reliability.
# # # #     MODULE_WEIGHTS: dict[str, float] = {
# # # #         "ela":            0.10,   # ↓ from 0.20: unreliable on PNG/screenshots
# # # #         "noise":          0.08,   # ↓ from 0.12: low confidence on screenshots
# # # #         "copymove":       0.07,   # ↓ from 0.10: low confidence on clean images
# # # #         "edge":           0.07,   # ↓ from 0.08
# # # #         "color":          0.10,   # ↑ from 0.08: good signal on composites
# # # #         "font":           0.18,   # ↑ from 0.10: strong indicator for doc forgery
# # # #         "ai_detection":   0.15,   # ↓ from 0.15: statistical-only, no CNN model
# # # #         "gan":            0.10,   # ↑ from 0.07: reliable spectral signal
# # # #         "frequency":      0.10,   # ↑ from 0.05: reliable on all image types
# # # #         "layout":         0.10,   # ↑ from 0.05: strong indicator for doc forgery
# # # #         # Supplementary — affect flags but not weighted sum
# # # #         "metadata":       0.05,
# # # #         "pdf_structure":  0.05,
# # # #     }

# # # #     # Threshold for a module to be considered "effectively dead"
# # # #     # (too low to contribute meaningful signal — e.g. ELA on PNG)
# # # #     DEAD_MODULE_THRESHOLD = 0.05

# # # #     # Thresholds for boolean flags
# # # #     EDITED_MODULES = {"ela", "copymove", "edge", "noise"}
# # # #     AI_MODULES = {"ai_detection", "gan", "frequency"}
# # # #     TAMPER_MODULES = {"metadata", "pdf_structure", "ela"}

# # # #     def compute(
# # # #         self,
# # # #         ctx: ForensicContext,
# # # #         heatmap_path: Optional[str],
# # # #         processing_start: datetime,
# # # #     ) -> FraudVerdict:
# # # #         """
# # # #         Compute the final fraud verdict from all module scores.
# # # #         """
# # # #         scores = ctx.module_scores
# # # #         active_scores = {
# # # #             name: result
# # # #             for name, result in scores.items()
# # # #             if not result.skipped and result.error is None
# # # #         }

# # # #         # ── Step 1: Compute effective weights ────────────────────
# # # #         # If a "heavy" module is effectively dead (e.g. ELA on PNG,
# # # #         # ai_detection without a CNN model), redistribute its weight
# # # #         # to the remaining modules proportionally so the denominator
# # # #         # isn't dragged down by dead weight.
# # # #         effective_weights = self._compute_effective_weights(active_scores)

# # # #         # ── Step 2: Weighted base score ──────────────────────────
# # # #         weighted_sum = 0.0
# # # #         total_weight = 0.0

# # # #         for module_name, weight in effective_weights.items():
# # # #             if weight == 0.0:
# # # #                 continue
# # # #             result = active_scores.get(module_name)
# # # #             if result is None:
# # # #                 continue
# # # #             # Scale contribution by module confidence
# # # #             effective_weight = weight * result.confidence
# # # #             weighted_sum += effective_weight * result.score
# # # #             total_weight += effective_weight

# # # #         base_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

# # # #         # ── Step 3: Evidence amplification ───────────────────────
# # # #         # Count modules with score > 0.5 (meaningful signal)
# # # #         high_modules = [
# # # #             r for r in active_scores.values()
# # # #             if r.score > 0.5 and r.module_name in effective_weights
# # # #         ]
# # # #         # IMPORTANT: check larger threshold first to avoid dead-code bug
# # # #         if len(high_modules) >= 5:
# # # #             base_score = min(base_score * 1.25, 1.0)
# # # #         elif len(high_modules) >= 3:
# # # #             base_score = min(base_score * 1.15, 1.0)

# # # #         # ── Step 4: Critical single-module override ───────────────
# # # #         # If any module scores >= 0.80 (strong signal), enforce minimum MEDIUM
# # # #         max_single = max(
# # # #             (r.score for r in active_scores.values()
# # # #              if r.module_name in effective_weights),
# # # #             default=0.0
# # # #         )
# # # #         if max_single >= 0.85:
# # # #             base_score = max(base_score, 0.65)   # Minimum HIGH
# # # #         elif max_single >= 0.70:
# # # #             base_score = max(base_score, 0.42)   # Minimum MEDIUM

# # # #         # ── Step 5: Multi-module convergence boost ────────────────
# # # #         # When document-specific modules (font + layout) both fire strongly,
# # # #         # this is a very reliable forgery signal regardless of image type.
# # # #         font_r = active_scores.get("font")
# # # #         layout_r = active_scores.get("layout")
# # # #         freq_r = active_scores.get("frequency")
# # # #         if (font_r and layout_r
# # # #                 and font_r.score > 0.55 and layout_r.score > 0.55):
# # # #             base_score = min(base_score + 0.08, 1.0)
# # # #             if freq_r and freq_r.score > 0.55:
# # # #                 base_score = min(base_score + 0.05, 1.0)  # triple convergence

# # # #         # ── Step 6: Supplementary module boosting ─────────────────
# # # #         meta_result = active_scores.get("metadata")
# # # #         pdf_result = active_scores.get("pdf_structure")

# # # #         if meta_result and meta_result.score > 0.5:
# # # #             base_score = min(base_score + 0.08, 1.0)
# # # #         if pdf_result and pdf_result.score > 0.5:
# # # #             base_score = min(base_score + 0.10, 1.0)

# # # #         # ── Step 7: Convert to 0-100 scale ────────────────────────
# # # #         fraud_score = base_score * 100.0

# # # #         # ── Step 8: Risk level ────────────────────────────────────
# # # #         risk_level = RiskLevel.from_score(fraud_score)

# # # #         # ── Step 9: Boolean verdicts ──────────────────────────────
# # # #         edited = self._flag_edited(active_scores)
# # # #         ai_generated = self._flag_ai_generated(active_scores)
# # # #         ai_assisted = self._flag_ai_assisted(active_scores, ai_generated)
# # # #         tampered = self._flag_tampered(active_scores)
# # # #         genuine = self._flag_genuine(fraud_score, active_scores)

# # # #         # ── Step 10: Overall confidence ────────────────────────────
# # # #         confidences = [
# # # #             r.confidence for r in active_scores.values()
# # # #             if r.module_name in effective_weights
# # # #         ]
# # # #         overall_confidence = float(sum(confidences) / len(confidences)) if confidences else 0.5

# # # #         # ── Step 11: Collect findings ──────────────────────────────
# # # #         findings = self._collect_findings(active_scores)

# # # #         # ── Step 12: Module score summary ────────────────────────
# # # #         module_score_map = {
# # # #             name: result.score
# # # #             for name, result in scores.items()
# # # #         }

# # # #         # ── Step 13: Collect bounding boxes ──────────────────────
# # # #         all_bboxes = []
# # # #         for result in scores.values():
# # # #             for bbox in result.bounding_boxes:
# # # #                 all_bboxes.append(bbox.as_dict)

# # # #         # ── Step 14: Recommendation ───────────────────────────────
# # # #         recommendation = self._generate_recommendation(
# # # #             fraud_score, risk_level, edited, ai_generated, ai_assisted,
# # # #             tampered, findings
# # # #         )

# # # #         # ── Step 15: Metadata extract ─────────────────────────────
# # # #         metadata_dict = {}
# # # #         if ctx.metadata:
# # # #             meta = ctx.metadata
# # # #             metadata_dict = {
# # # #                 "creator": meta.creator,
# # # #                 "producer": meta.producer,
# # # #                 "author": meta.author,
# # # #                 "software": meta.software,
# # # #                 "creation_date": meta.creation_date.isoformat() if meta.creation_date else None,
# # # #                 "modification_date": meta.modification_date.isoformat() if meta.modification_date else None,
# # # #                 "camera_make": meta.camera_make,
# # # #                 "camera_model": meta.camera_model,
# # # #             }

# # # #         processing_ms = int(
# # # #             (datetime.utcnow() - processing_start).total_seconds() * 1000
# # # #         )

# # # #         verdict = FraudVerdict(
# # # #             document_id=ctx.document_id,
# # # #             job_id=ctx.job_id,
# # # #             fraud_score=round(fraud_score, 2),
# # # #             risk_level=risk_level,
# # # #             edited=edited,
# # # #             ai_generated=ai_generated,
# # # #             ai_assisted=ai_assisted,
# # # #             tampered=tampered,
# # # #             genuine=genuine,
# # # #             confidence=round(overall_confidence, 4),
# # # #             findings=findings,
# # # #             heatmap_path=heatmap_path,
# # # #             module_scores=module_score_map,
# # # #             bounding_boxes=all_bboxes,
# # # #             recommendation=recommendation,
# # # #             metadata=metadata_dict,
# # # #             processing_time_ms=processing_ms,
# # # #         )

# # # #         logger.info(
# # # #             "Verdict: score=%.2f risk=%s edited=%s ai=%s tampered=%s genuine=%s [%dms]",
# # # #             fraud_score, risk_level.value, edited, ai_generated, tampered, genuine, processing_ms,
# # # #         )

# # # #         return verdict

# # # #     # ─────────────────────────────────────────────
# # # #     # Weight redistribution
# # # #     # ─────────────────────────────────────────────

# # # #     def _compute_effective_weights(
# # # #         self, active_scores: dict[str, ModuleScore]
# # # #     ) -> dict[str, float]:
# # # #         """
# # # #         Return adjusted weights that redistribute weight away from modules
# # # #         that are effectively dead (score < DEAD_MODULE_THRESHOLD) on this
# # # #         document type.

# # # #         This prevents near-zero ELA or ai_detection scores from silently
# # # #         eating 35% of the weight budget and dragging the aggregate score down
# # # #         when those modules simply cannot fire on PNG/screenshot inputs.
# # # #         """
# # # #         weights = dict(self.MODULE_WEIGHTS)  # start from base

# # # #         # Identify dead modules: present, not skipped, but near-zero score
# # # #         dead_modules: list[str] = []
# # # #         for name, w in weights.items():
# # # #             if w == 0.0:
# # # #                 continue
# # # #             r = active_scores.get(name)
# # # #             if r is not None and r.score < self.DEAD_MODULE_THRESHOLD:
# # # #                 dead_modules.append(name)

# # # #         if not dead_modules:
# # # #             return weights

# # # #         # Total weight to redistribute
# # # #         freed_weight = sum(weights[m] for m in dead_modules)
# # # #         for m in dead_modules:
# # # #             weights[m] = 0.0

# # # #         # Remaining active weighted modules
# # # #         active_weighted = [
# # # #             n for n, w in weights.items()
# # # #             if w > 0.0 and active_scores.get(n) is not None
# # # #         ]

# # # #         if not active_weighted:
# # # #             return weights

# # # #         # Distribute freed weight proportionally to active modules
# # # #         total_active_w = sum(weights[n] for n in active_weighted)
# # # #         for n in active_weighted:
# # # #             weights[n] += freed_weight * (weights[n] / total_active_w)

# # # #         logger.debug(
# # # #             "Redistributed %.3f weight from dead modules %s",
# # # #             freed_weight, dead_modules
# # # #         )
# # # #         return weights

# # # #     # ─────────────────────────────────────────────
# # # #     # Boolean flag logic
# # # #     # ─────────────────────────────────────────────

# # # #     def _flag_edited(self, scores: dict[str, ModuleScore]) -> bool:
# # # #         """Edited = strong signal from regional-modification modules."""
# # # #         editing_scores = [
# # # #             scores[m].score
# # # #             for m in self.EDITED_MODULES
# # # #             if m in scores and not scores[m].skipped
# # # #         ]
# # # #         if not editing_scores:
# # # #             return False
# # # #         # At least 2 editing modules > threshold, OR 1 module very high
# # # #         above_thresh = sum(s > settings.edited_threshold for s in editing_scores)
# # # #         max_score = max(editing_scores)
# # # #         return above_thresh >= 2 or max_score > 0.75

# # # #     def _flag_ai_generated(self, scores: dict[str, ModuleScore]) -> bool:
# # # #         """AI generated = strong signal from all AI-specific modules."""
# # # #         ai_scores = [
# # # #             scores[m].score
# # # #             for m in self.AI_MODULES
# # # #             if m in scores and not scores[m].skipped
# # # #         ]
# # # #         if not ai_scores:
# # # #             return False
# # # #         above = sum(s > settings.ai_generated_threshold for s in ai_scores)
# # # #         return above >= 2

# # # #     def _flag_ai_assisted(
# # # #         self, scores: dict[str, ModuleScore], ai_generated: bool
# # # #     ) -> bool:
# # # #         """AI assisted = at least 2 AI-specific modules show elevated signal."""
# # # #         if ai_generated:
# # # #             return False
# # # #         ai_scores = [
# # # #             scores[m].score
# # # #             for m in self.AI_MODULES
# # # #             if m in scores and not scores[m].skipped
# # # #         ]
# # # #         if not ai_scores:
# # # #             return False
# # # #         above_thresh = sum(s > settings.ai_assisted_threshold for s in ai_scores)
# # # #         return above_thresh >= 2

# # # #     def _flag_tampered(self, scores: dict[str, ModuleScore]) -> bool:
# # # #         """Tampered = structural modification detected."""
# # # #         for m in self.TAMPER_MODULES:
# # # #             if m in scores and not scores[m].skipped:
# # # #                 if scores[m].score > settings.tampered_threshold:
# # # #                     return True
# # # #         return False

# # # #     def _flag_genuine(
# # # #         self, fraud_score: float, scores: dict[str, ModuleScore]
# # # #     ) -> bool:
# # # #         """Genuine = score in GENUINE band AND no single weighted module is strongly elevated."""
# # # #         if fraud_score > 20:
# # # #             return False
# # # #         weighted_modules = {
# # # #             name for name, w in self.MODULE_WEIGHTS.items() if w > 0.0
# # # #         }
# # # #         max_score = max(
# # # #             (r.score for name, r in scores.items()
# # # #              if name in weighted_modules and not r.skipped),
# # # #             default=0.0,
# # # #         )
# # # #         return max_score < 0.45

# # # #     # ─────────────────────────────────────────────
# # # #     # Helpers
# # # #     # ─────────────────────────────────────────────

# # # #     def _collect_findings(self, scores: dict[str, ModuleScore]) -> list[str]:
# # # #         """Collect all findings from modules, deduplicated, sorted by module."""
# # # #         all_findings = []
# # # #         for result in scores.values():
# # # #             for finding in result.findings:
# # # #                 entry = f"[{result.module_name.upper()}] {finding}"
# # # #                 if entry not in all_findings:
# # # #                     all_findings.append(entry)
# # # #         return all_findings

# # # #     def _generate_recommendation(
# # # #         self,
# # # #         score: float,
# # # #         risk: RiskLevel,
# # # #         edited: bool,
# # # #         ai_generated: bool,
# # # #         ai_assisted: bool,
# # # #         tampered: bool,
# # # #         findings: list[str],
# # # #     ) -> str:
# # # #         """Generate a human-readable recommendation based on verdict."""
# # # #         if risk == RiskLevel.GENUINE:
# # # #             return (
# # # #                 "Document appears authentic. No significant manipulation indicators detected. "
# # # #                 "Standard acceptance procedures apply."
# # # #             )
# # # #         elif risk == RiskLevel.LOW:
# # # #             finding_count = len(findings)
# # # #             if finding_count == 0:
# # # #                 return (
# # # #                     "No significant anomalies detected. Document appears consistent with "
# # # #                     "a legitimate source."
# # # #                 )
# # # #             return (
# # # #                 f"{finding_count} minor anomal{'y' if finding_count == 1 else 'ies'} detected "
# # # #                 f"(score {score:.0f}/100). These may reflect normal image processing artefacts. "
# # # #                 "A secondary review of the flagged regions is recommended before acceptance."
# # # #             )
# # # #         elif risk == RiskLevel.MEDIUM:
# # # #             parts = [f"Multiple forensic signals detected (score {score:.0f}/100)."]
# # # #             if edited:
# # # #                 parts.append("Evidence of regional editing found.")
# # # #             if ai_assisted:
# # # #                 parts.append("Possible AI-assisted content detected.")
# # # #             if ai_generated:
# # # #                 parts.append("AI generation artifacts present.")
# # # #             parts.append(
# # # #                 "Manual verification of document origin and a comparison with "
# # # #                 "the original source is strongly recommended before acceptance."
# # # #             )
# # # #             return " ".join(parts)
# # # #         elif risk == RiskLevel.HIGH:
# # # #             parts = [f"Significant manipulation indicators detected (score {score:.0f}/100)."]
# # # #             if edited:
# # # #                 parts.append("Document shows signs of regional editing.")
# # # #             if tampered:
# # # #                 parts.append("Structural tampering detected.")
# # # #             if ai_generated:
# # # #                 parts.append("Document is likely AI-generated.")
# # # #             elif ai_assisted:
# # # #                 parts.append("AI-assisted content is likely present.")
# # # #             parts.append(
# # # #                 "Reject document and request the original. Escalate to the fraud team if needed."
# # # #             )
# # # #             return " ".join(parts)
# # # #         else:  # CRITICAL
# # # #             parts = [f"CRITICAL: High-confidence manipulation detected (score {score:.0f}/100)."]
# # # #             if ai_generated:
# # # #                 parts.append("Document is AI-generated or AI-assisted.")
# # # #             if edited:
# # # #                 parts.append("Extensive editing detected across multiple regions.")
# # # #             if tampered:
# # # #                 parts.append("Document structure shows clear tampering.")
# # # #             parts.append(
# # # #                 "REJECT immediately. Do not process. Escalate to the security/fraud team "
# # # #                 "for investigation and preserve the original file as evidence."
# # # #             )
# # # #             return " ".join(parts)



# # """
# # Fraud Scoring Engine

# # ═══════════════════════════════════════════════════════════════
# # THEORY
# # ═══════════════════════════════════════════════════════════════
# # The scoring engine aggregates signals from all forensic modules
# # into a single fraud score (0-100) and categorical risk level.

# # Design decisions:
# # 1. Weighted linear combination as the base
# # 2. Evidence amplification: when multiple modules agree, score is amplified
# # 3. Evidence dampening: when only one module fires, confidence is reduced
# # 4. Module confidence weighting: low-confidence modules contribute less
# # 5. Outlier handling: a single module at 0.85+ triggers minimum HIGH risk
# # 6. Tamper/flag override: any positive flag enforces a score floor so that
# #    fraud_score is ALWAYS consistent with the boolean verdict flags —
# #    i.e. tampered=True can never coexist with risk=GENUINE/LOW.
# # 7. Confidence penalty: when flags and raw score diverge, confidence is
# #    reduced to signal that the weighted score underestimates the real risk.

# # Risk Levels:
# #   0-20  → GENUINE        (very likely authentic)
# #   21-40 → LOW RISK       (minor anomalies, likely clean)
# #   41-60 → MEDIUM RISK    (multiple signals, review recommended)
# #   61-80 → HIGH RISK      (strong tampering indicators)
# #   81-100→ CRITICAL RISK  (definite manipulation detected)

# # Verdict Flags:
# #   edited        = any regional modification (ELA/CopyMove/Edge high)
# #   ai_generated  = full AI synthesis (AI+GAN+Frequency all high)
# #   ai_assisted   = partial AI (AI high but other modules low)
# #   tampered      = structural changes (PDF/Metadata/ELA high)
# #   genuine       = ALL flags False AND score ≤ 20 AND no module elevated
# # """

# # from __future__ import annotations

# # import logging
# # from datetime import datetime
# # from typing import Optional

# # from app.core.config import settings
# # from app.domain.entities.document import (
# #     ForensicContext,
# #     FraudVerdict,
# #     ModuleScore,
# #     RiskLevel,
# # )

# # logger = logging.getLogger("docfraud.scoring")


# # class FraudScoringEngine:
# #     """
# #     Aggregates forensic module results into a final FraudVerdict.
# #     """

# #     # # Module weights — weighted modules must sum to 1.0
# #     # MODULE_WEIGHTS: dict[str, float] = {
# #     #     "ela":              0.18,   # ↓ slightly to accommodate text_forensics
# #     #     "noise":            0.11,   # ↓ slightly
# #     #     "copymove":         0.09,   # ↓ slightly
# #     #     "edge":             0.07,   # ↓ slightly
# #     #     "color":            0.07,   # ↓ slightly
# #     #     "font":             0.08,   # ↓ slightly (text_forensics also covers font)
# #     #     "ai_detection":     0.08,   # ↓ slightly
# #     #     "gan":              0.15,
# #     #     "frequency":        0.05,
# #     #     "layout":           0.08,   # ↓ slightly
# #     #     "text_forensics":   0.10,   # ← new: text-level manipulation detection
# #     #     # Supplementary — zero weight in sum, but drive flag + score floor
# #     #     "metadata":         0.00,
# #     #     "pdf_structure":    0.00,
# #     # }


# #     MODULE_WEIGHTS = {
# #         "ela":            0.22,
# #         "noise":          0.07,
# #         "copymove":       0.08,
# #         "edge":           0.04,
# #         "color":          0.04,
# #         "font":           0.08,
# #         "ai_detection":   0.08,
# #         "gan":            0.15,
# #         "frequency":      0.08,
# #         "layout":         0.08,
# #         "text_forensics": 0.16,

# #         "metadata":       0.00,
# #         "pdf_structure":  0.00,
# #     }

# #     # Score floor enforced when a flag fires — ensures fraud_score is
# #     # always semantically consistent with the boolean verdict flags.
# #     FLAG_SCORE_FLOORS: dict[str, float] = {
# #         "tampered":     0.45,   # tampered=True  → minimum MEDIUM (45)
# #         "edited":       0.40,   # edited=True    → minimum MEDIUM (42)
# #         "ai_generated": 0.55,   # ai_generated   → minimum HIGH   (55)
# #         "ai_assisted":  0.42,   # ai_assisted    → minimum MEDIUM (42)
# #     }

# #     # Module groups used for flag logic
# #     # EDITED_MODULES = {"ela", "copymove", "edge", "noise", "text_forensics"}

# #     STRONG_EDIT = {
# #         "ela",
# #         "copymove",
# #         "layout"
# #     }

# #     WEAK_EDIT = {
# #         "edge",
# #         "noise",
# #         "text_forensics"
# #     }
    
# #     EDITED_MODULES =(strong_count >= 1) or (weak_count >= 3)




# #     AI_MODULES     = {"ai_detection", "gan", "frequency"}
# #     # TAMPER_MODULES = {"metadata", "pdf_structure", "ela"}


# #     TAMPER_MODULES =("pdf_structure" > threshold) or ("ela" > threshold) or ("metadata" > threshold and "pdf_structure" > threshold)

# #     def compute(
# #         self,
# #         ctx: ForensicContext,
# #         heatmap_path: Optional[str],
# #         processing_start: datetime,
# #     ) -> FraudVerdict:
# #         """
# #         Compute the final fraud verdict from all module scores.
# #         """
# #         scores = ctx.module_scores
# #         active_scores = {
# #             name: result
# #             for name, result in scores.items()
# #             if not result.skipped and result.error is None
# #         }

# #         # ── Step 1: Weighted base score ──────────────────────────
# #         weighted_sum = 0.0
# #         total_weight = 0.0

# #         for module_name, weight in self.MODULE_WEIGHTS.items():
# #             if weight == 0.0:
# #                 continue
# #             result = active_scores.get(module_name)
# #             if result is None:
# #                 continue
# #             effective_weight = weight * result.confidence
# #             weighted_sum    += effective_weight * result.score
# #             total_weight    += effective_weight

# #         base_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

# #         # ── Step 2: Evidence amplification ───────────────────────
# #         # Count weighted modules with score > 0.5 (meaningful signal).
# #         # BUG FIX: check >=5 FIRST — otherwise the >=3 branch always wins
# #         # and the >=5 branch is dead code.
# #         high_modules = [
# #             r for r in active_scores.values()
# #             if r.score > 0.5 and r.module_name in self.MODULE_WEIGHTS
# #         ]
# #         if len(high_modules) >= 5:
# #             base_score = min(base_score * 1.20, 1.0)
# #         elif len(high_modules) >= 3:
# #             base_score = min(base_score * 1.12, 1.0)

# #         # ── Step 3: Critical single-module override ───────────────
# #         # A single very strong signal is itself evidence of fraud.
# #         max_single = max(
# #             (r.score for r in active_scores.values()
# #              if r.module_name in self.MODULE_WEIGHTS),
# #             default=0.0,
# #         )
# #         if max_single >= 0.85:
# #             base_score = max(base_score, 0.65)   # → minimum HIGH
# #         elif max_single >= 0.70:
# #             base_score = max(base_score, 0.42)   # → minimum MEDIUM

# #         # ── Step 4: Supplementary module boosting ─────────────────
# #         # metadata and pdf_structure are zero-weight (they don't participate
# #         # in the weighted average) but are strong structural signals when they
# #         # fire, so we add an additive boost to the already-computed score.
# #         meta_result = active_scores.get("metadata")
# #         pdf_result  = active_scores.get("pdf_structure")

# #         if meta_result and meta_result.score > 0.5:
# #             base_score = min(base_score + 0.08, 1.0)
# #         if pdf_result and pdf_result.score > 0.5:
# #             base_score = min(base_score + 0.10, 1.0)

# #         # ── Step 5: Convert to 0-100 scale ────────────────────────
# #         fraud_score = base_score * 100.0

# #         # ── Step 6: Boolean verdict flags ─────────────────────────
# #         edited       = self._flag_edited(active_scores)
# #         ai_generated = self._flag_ai_generated(active_scores)
# #         ai_assisted  = self._flag_ai_assisted(active_scores, ai_generated)
# #         tampered     = self._flag_tampered(active_scores)

# #         # ── Step 7: Flag-score consistency enforcement ────────────
# #         # CORE FIX: the weighted score can underestimate fraud when a
# #         # supplementary module (weight=0) drives a flag.  Enforce floors
# #         # so fraud_score is always semantically consistent with the flags.
# #         # E.g. tampered=True must never produce risk=GENUINE or risk=LOW.
# #         flag_states = {
# #             "tampered":     tampered,
# #             "edited":       edited,
# #             "ai_generated": ai_generated,
# #             "ai_assisted":  ai_assisted,
# #         }
# #         for flag_name, flag_value in flag_states.items():
# #             if flag_value:
# #                 floor = self.FLAG_SCORE_FLOORS[flag_name] * 100.0
# #                 if fraud_score < floor:
# #                     logger.debug(
# #                         "Flag %s=True overrides score %.1f → %.1f",
# #                         flag_name, fraud_score, floor,
# #                     )
# #                     fraud_score = floor

# #         # ── Step 8: Risk level ────────────────────────────────────
# #         risk_level = RiskLevel.from_score(fraud_score)

# #         # ── Step 9: Genuine flag ──────────────────────────────────
# #         # genuine = True ONLY when every other flag is False AND the
# #         # score is in the GENUINE band.  Any positive flag disqualifies.
# #         genuine = self._flag_genuine(
# #             fraud_score, active_scores,
# #             any_flag_set=(edited or ai_generated or ai_assisted or tampered),
# #         )

# #         # ── Step 10: Confidence ───────────────────────────────────
# #         confidences = [
# #             r.confidence for r in active_scores.values()
# #             if r.module_name in self.MODULE_WEIGHTS
# #         ]
# #         raw_confidence = float(sum(confidences) / len(confidences)) if confidences else 0.5

# #         # Penalise confidence when flags required a score floor uplift —
# #         # it means the weighted modules disagreed with the structural
# #         # signals, which is genuine analytical uncertainty.
# #         any_flag = edited or ai_generated or ai_assisted or tampered
# #         if any_flag and (fraud_score / 100.0) > (base_score + 0.05):
# #             # Score was lifted; reflect the disagreement in confidence
# #             uplift_ratio = (fraud_score / 100.0) - base_score   # 0..1
# #             penalty = min(uplift_ratio * 0.6, 0.25)             # cap at −25 pp
# #             overall_confidence = max(raw_confidence - penalty, 0.30)
# #             logger.debug(
# #                 "Confidence penalised by %.3f (uplift=%.3f): %.3f → %.3f",
# #                 penalty, uplift_ratio, raw_confidence, overall_confidence,
# #             )
# #         else:
# #             overall_confidence = raw_confidence

# #         # ── Step 11: Collect findings ──────────────────────────────
# #         findings = self._collect_findings(active_scores)

# #         # ── Step 12: Module score summary ─────────────────────────
# #         module_score_map = {
# #             name: result.score
# #             for name, result in scores.items()
# #         }

# #         # ── Step 13: Collect bounding boxes ───────────────────────
# #         all_bboxes = []
# #         for result in scores.values():
# #             for bbox in result.bounding_boxes:
# #                 all_bboxes.append(bbox.as_dict)

# #         # ── Step 14: Recommendation ────────────────────────────────
# #         recommendation = self._generate_recommendation(
# #             fraud_score, risk_level,
# #             edited, ai_generated, ai_assisted, tampered,
# #             findings,
# #         )

# #         # ── Step 15: Metadata extract ──────────────────────────────
# #         metadata_dict: dict = {}
# #         if ctx.metadata:
# #             meta = ctx.metadata
# #             metadata_dict = {
# #                 "creator":           meta.creator,
# #                 "producer":          meta.producer,
# #                 "author":            meta.author,
# #                 "software":          meta.software,
# #                 "creation_date":     meta.creation_date.isoformat() if meta.creation_date else None,
# #                 "modification_date": meta.modification_date.isoformat() if meta.modification_date else None,
# #                 "camera_make":       meta.camera_make,
# #                 "camera_model":      meta.camera_model,
# #             }

# #         processing_ms = int(
# #             (datetime.utcnow() - processing_start).total_seconds() * 1000
# #         )

# #         verdict = FraudVerdict(
# #             document_id=ctx.document_id,
# #             job_id=ctx.job_id,
# #             fraud_score=round(fraud_score, 2),
# #             risk_level=risk_level,
# #             edited=edited,
# #             ai_generated=ai_generated,
# #             ai_assisted=ai_assisted,
# #             tampered=tampered,
# #             genuine=genuine,
# #             confidence=round(overall_confidence, 4),
# #             findings=findings,
# #             heatmap_path=heatmap_path,
# #             module_scores=module_score_map,
# #             bounding_boxes=all_bboxes,
# #             recommendation=recommendation,
# #             metadata=metadata_dict,
# #             processing_time_ms=processing_ms,
# #         )

# #         logger.info(
# #             "Verdict: score=%.2f risk=%s edited=%s ai=%s ai_assisted=%s "
# #             "tampered=%s genuine=%s confidence=%.3f [%dms]",
# #             fraud_score, risk_level.value,
# #             edited, ai_generated, ai_assisted, tampered, genuine,
# #             overall_confidence, processing_ms,
# #         )

# #         return verdict

# #     # ─────────────────────────────────────────────
# #     # Boolean flag logic
# #     # ─────────────────────────────────────────────

# #     def _flag_edited(self, scores: dict[str, ModuleScore]) -> bool:
# #         """Edited = strong signal from regional-modification modules."""
# #         editing_scores = [
# #             scores[m].score
# #             for m in self.EDITED_MODULES
# #             if m in scores and not scores[m].skipped
# #         ]
# #         if not editing_scores:
# #             return False
# #         above_thresh = sum(s > settings.edited_threshold for s in editing_scores)
# #         max_score = max(editing_scores)
# #         return above_thresh >= 2 or max_score > 0.75

# #     def _flag_ai_generated(self, scores: dict[str, ModuleScore]) -> bool:
# #         """AI generated = strong signal from 2+ AI-specific modules."""
# #         ai_scores = [
# #             scores[m].score
# #             for m in self.AI_MODULES
# #             if m in scores and not scores[m].skipped
# #         ]
# #         if not ai_scores:
# #             return False
# #         above = sum(s > settings.ai_generated_threshold for s in ai_scores)
# #         return above >= 2

# #     def _flag_ai_assisted(
# #         self, scores: dict[str, ModuleScore], ai_generated: bool
# #     ) -> bool:
# #         """AI assisted = elevated signal in AI modules but below full-generation threshold."""
# #         if ai_generated:
# #             return False
# #         ai_scores = [
# #             scores[m].score
# #             for m in self.AI_MODULES
# #             if m in scores and not scores[m].skipped
# #         ]
# #         if not ai_scores:
# #             return False
# #         above_thresh = sum(s > settings.ai_assisted_threshold for s in ai_scores)
# #         return above_thresh >= 2

# #     def _flag_tampered(self, scores: dict[str, ModuleScore]) -> bool:
# #         """Tampered = structural modification detected in metadata, PDF structure, or ELA."""
# #         for m in self.TAMPER_MODULES:
# #             if m in scores and not scores[m].skipped:
# #                 if scores[m].score > settings.tampered_threshold:
# #                     return True
# #         return False

# #     def _flag_genuine(
# #         self,
# #         fraud_score: float,
# #         scores: dict[str, ModuleScore],
# #         any_flag_set: bool,
# #     ) -> bool:
# #         """
# #         Genuine = score in GENUINE band AND no positive flags AND
# #         no single weighted module is meaningfully elevated.

# #         BUG FIX: previously this could return True even when tampered=True
# #         because it only checked fraud_score, not the flag state.
# #         """
# #         # Any positive verdict flag disqualifies genuine immediately
# #         if any_flag_set:
# #             return False
# #         if fraud_score > 20:
# #             return False
# #         weighted_modules = {
# #             name for name, w in self.MODULE_WEIGHTS.items() if w > 0.0
# #         }
# #         max_score = max(
# #             (r.score for name, r in scores.items()
# #              if name in weighted_modules and not r.skipped),
# #             default=0.0,
# #         )
# #         return max_score < 0.45

# #     # ─────────────────────────────────────────────
# #     # Helpers
# #     # ─────────────────────────────────────────────

# #     def _collect_findings(self, scores: dict[str, ModuleScore]) -> list[str]:
# #         """Collect all findings from modules, deduplicated."""
# #         all_findings: list[str] = []
# #         for result in scores.values():
# #             for finding in result.findings:
# #                 entry = f"[{result.module_name.upper()}] {finding}"
# #                 if entry not in all_findings:
# #                     all_findings.append(entry)
# #         return all_findings

# #     def _generate_recommendation(
# #         self,
# #         score: float,
# #         risk: RiskLevel,
# #         edited: bool,
# #         ai_generated: bool,
# #         ai_assisted: bool,
# #         tampered: bool,
# #         findings: list[str],
# #     ) -> str:
# #         """Generate a human-readable recommendation based on the final verdict."""
# #         if risk == RiskLevel.GENUINE:
# #             return (
# #                 "Document appears authentic. No significant manipulation indicators detected. "
# #                 "Standard acceptance procedures apply."
# #             )
# #         elif risk == RiskLevel.LOW:
# #             finding_count = len(findings)
# #             if finding_count == 0:
# #                 return (
# #                     "No significant anomalies detected. Document appears consistent with "
# #                     "a legitimate source."
# #                 )
# #             return (
# #                 f"{finding_count} minor anomal{'y' if finding_count == 1 else 'ies'} detected "
# #                 f"(score {score:.0f}/100). These may reflect normal image processing artefacts. "
# #                 "A secondary review of flagged regions is recommended before acceptance."
# #             )
# #         elif risk == RiskLevel.MEDIUM:
# #             parts = [f"Multiple forensic signals detected (score {score:.0f}/100)."]
# #             if edited:
# #                 parts.append("Evidence of regional editing found.")
# #             if tampered:
# #                 parts.append("Structural tampering detected.")
# #             if ai_assisted:
# #                 parts.append("Possible AI-assisted content detected.")
# #             if ai_generated:
# #                 parts.append("AI generation artifacts present.")
# #             parts.append(
# #                 "Manual verification of document origin and comparison with "
# #                 "the original source is strongly recommended before acceptance."
# #             )
# #             return " ".join(parts)
# #         elif risk == RiskLevel.HIGH:
# #             parts = [f"Significant manipulation indicators detected (score {score:.0f}/100)."]
# #             if edited:
# #                 parts.append("Document shows signs of regional editing.")
# #             if tampered:
# #                 parts.append("Structural tampering detected.")
# #             if ai_generated:
# #                 parts.append("Document is likely AI-generated.")
# #             elif ai_assisted:
# #                 parts.append("AI-assisted content is likely present.")
# #             parts.append(
# #                 "Reject document and request the original. Escalate to the fraud team if needed."
# #             )
# #             return " ".join(parts)
# #         else:  # CRITICAL
# #             parts = [f"CRITICAL: High-confidence manipulation detected (score {score:.0f}/100)."]
# #             if ai_generated:
# #                 parts.append("Document is AI-generated or AI-assisted.")
# #             if edited:
# #                 parts.append("Extensive editing detected across multiple regions.")
# #             if tampered:
# #                 parts.append("Document structure shows clear tampering.")
# #             parts.append(
# #                 "REJECT immediately. Do not process. Escalate to the security/fraud team "
# #                 "for investigation and preserve the original file as evidence."
# #             )
# #             return " ".join(parts)

# """
# Fraud Scoring Engine

# ═══════════════════════════════════════════════════════════════
# THEORY
# ═══════════════════════════════════════════════════════════════
# The scoring engine aggregates signals from all forensic modules
# into a single fraud score (0-100) and categorical risk level.

# Design decisions:
# 1. Weighted linear combination as the base
# 2. Evidence amplification: when multiple modules agree, score is amplified
# 3. Evidence dampening: when only one module fires, confidence is reduced
# 4. Module confidence weighting: low-confidence modules contribute less
# 5. Outlier handling: a single module at 0.85+ triggers minimum HIGH risk
# 6. Tamper/flag override: any positive flag enforces a score floor so that
#    fraud_score is ALWAYS consistent with the boolean verdict flags —
#    i.e. tampered=True can never coexist with risk=GENUINE/LOW.
# 7. Confidence penalty: when flags and raw score diverge, confidence is
#    reduced to signal that the weighted score underestimates the real risk.

# Tier-gated HIGH/CRITICAL risk:
#    HIGH and CRITICAL risk levels require at least one Tier A signal to fire.
#    This prevents weak/noisy modules (edge, noise, baseline, kerning) from
#    inflating risk on genuine documents such as salary slips, Aadhaar cards,
#    PAN cards, offer letters, and bank statements.

# Evidence tiers:
#    Tier A (Very Strong) : ela, gan, copymove  — direct manipulation evidence
#    Tier B (Strong)      : layout, font         — structural/content indicators
#    Tier C (Weak)        : noise, edge, metadata, color, frequency,
#                           text_forensics       — supportive only

# Risk Levels:
#   0-20  → GENUINE        (very likely authentic)
#   21-40 → LOW RISK       (minor anomalies, likely clean)
#   41-60 → MEDIUM RISK    (multiple signals, review recommended)
#   61-80 → HIGH RISK      (strong tampering indicators)
#   81-100→ CRITICAL RISK  (definite manipulation detected)

# Verdict Flags:
#   edited        = strong signal from regional-modification modules
#                   (strong_count >= 1  OR  weak_count >= 3)
#   ai_generated  = GAN fires AND at least one of ai_detection / frequency
#                   fires above threshold
#   ai_assisted   = not ai_generated AND ai_detection fires alone at a
#                   lower threshold
#   tampered      = pdf_structure fires  OR  ela fires  OR
#                   (metadata AND pdf_structure both fire)
#   genuine       = ALL flags False AND score ≤ 20 AND no module elevated
# """

# from __future__ import annotations

# import logging
# from datetime import datetime
# from typing import Optional

# from app.core.config import settings
# from app.domain.entities.document import (
#     ForensicContext,
#     FraudVerdict,
#     ModuleScore,
#     RiskLevel,
# )

# logger = logging.getLogger("docfraud.scoring")


# class FraudScoringEngine:
#     """
#     Aggregates forensic module results into a final FraudVerdict.
#     """

#     # Module weights — weighted modules must sum to 1.0
#     MODULE_WEIGHTS: dict[str, float] = {
#         "ela":            0.22,
#         "noise":          0.07,
#         "copymove":       0.08,
#         "edge":           0.04,
#         "color":          0.04,
#         "font":           0.08,
#         "ai_detection":   0.08,
#         "gan":            0.15,
#         "frequency":      0.08,
#         "layout":         0.08,
#         "text_forensics": 0.16,
#         # Supplementary — zero weight in sum, but drive flag + score floor
#         "metadata":       0.00,
#         "pdf_structure":  0.00,
#     }

#     # Score floor enforced when a flag fires — ensures fraud_score is
#     # always semantically consistent with the boolean verdict flags.
#     FLAG_SCORE_FLOORS: dict[str, float] = {
#         "tampered":     0.45,   # tampered=True  → minimum MEDIUM (45)
#         "edited":       0.35,   # edited=True    → minimum MEDIUM (40)
#         "ai_generated": 0.55,   # ai_generated   → minimum HIGH   (55)
#         "ai_assisted":  0.42,   # ai_assisted    → minimum MEDIUM (42)
#     }

#     # ── FIX #1: Split EDITED_MODULES into strong / weak sets ─────────────
#     #
#     # Old behaviour:  any 2 modules from the flat set above threshold → edited=True
#     # Problem:        noise + edge + text_forensics all fire on genuine scanned
#     #                 documents (WhatsApp forwards, scanner apps, mobile cameras),
#     #                 producing systematic false positives.
#     #
#     # New behaviour:
#     #   STRONG_EDIT: direct pixel-level manipulation evidence (copymove, ELA,
#     #                layout shift).  One strong signal is sufficient.
#     #   WEAK_EDIT:   texture/noise/text signals that fire on genuine docs too.
#     #                Three weak signals required before edited=True.
#     #
#     STRONG_EDIT: set[str] = {
#         "ela",
#         "copymove",
#         "layout",
#     }

#     WEAK_EDIT: set[str] = {
#         "edge",
#         "noise",
#         "text_forensics",
#     }

#     # AI detection modules (unchanged)
#     AI_MODULES: set[str] = {"ai_detection", "gan", "frequency"}

#     # ── FIX #2 / FIX #3: Tier-based evidence classification ──────────────
#     #
#     # HIGH and CRITICAL risk levels are only reachable when at least one
#     # Tier A signal fires.  This prevents weak modules (Tier C) from
#     # escalating genuine documents to HIGH/CRITICAL.
#     #
#     # Tier A — very strong, direct manipulation evidence
#     TIER_A: set[str] = {"ela", "gan", "copymove"}

#     # Tier B — strong structural / content indicators
#     TIER_B: set[str] = {"layout", "font"}

#     # Tier C — weak / noisy; supportive only
#     TIER_C: set[str] = {
#         "noise", "edge", "metadata", "color",
#         "frequency", "text_forensics",
#     }

#     def compute(
#         self,
#         ctx: ForensicContext,
#         heatmap_path: Optional[str],
#         processing_start: datetime,
#     ) -> FraudVerdict:
#         """
#         Compute the final fraud verdict from all module scores.
#         """
#         scores = ctx.module_scores
#         active_scores = {
#             name: result
#             for name, result in scores.items()
#             if not result.skipped and result.error is None
#         }

#         # ── Step 1: Weighted base score ──────────────────────────
#         weighted_sum = 0.0
#         total_weight = 0.0

#         for module_name, weight in self.MODULE_WEIGHTS.items():
#             if weight == 0.0:
#                 continue
#             result = active_scores.get(module_name)
#             if result is None:
#                 continue
#             effective_weight = weight * result.confidence
#             weighted_sum    += effective_weight * result.score
#             total_weight    += effective_weight

#         base_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

#         # ── Step 2: Evidence amplification ───────────────────────
#         # Count weighted modules with score > 0.5 (meaningful signal).
#         # Check >=5 FIRST — otherwise the >=3 branch always wins and the
#         # >=5 branch becomes unreachable dead code.
#         high_modules = [
#             r for r in active_scores.values()
#             if r.score > 0.5 and r.module_name in self.MODULE_WEIGHTS
#         ]
#         if len(high_modules) >= 5:
#             base_score = min(base_score * 1.20, 1.0)
#         elif len(high_modules) >= 3:
#             base_score = min(base_score * 1.12, 1.0)

#         # ── Step 3: Critical single-module override ───────────────
#         # A single very strong signal is itself evidence of fraud.
#         max_single = max(
#             (r.score for r in active_scores.values()
#              if r.module_name in self.MODULE_WEIGHTS),
#             default=0.0,
#         )
#         if max_single >= 0.85:
#             base_score = max(base_score, 0.65)   # → minimum HIGH
#         elif max_single >= 0.70:
#             base_score = max(base_score, 0.42)   # → minimum MEDIUM

#         # ── Step 4: Supplementary module boosting ─────────────────
#         # metadata and pdf_structure carry zero weight (they don't
#         # participate in the weighted average) but are strong structural
#         # signals when they fire, so we add an additive boost.
#         meta_result = active_scores.get("metadata")
#         pdf_result  = active_scores.get("pdf_structure")

#         if meta_result and meta_result.score > 0.5:
#             base_score = min(base_score + 0.08, 1.0)
#         if pdf_result and pdf_result.score > 0.5:
#             base_score = min(base_score + 0.10, 1.0)

#         # ── Step 5: FIX #4 — Strong-signal gating ─────────────────
#         #
#         # Count how many Tier A modules produced a meaningful signal.
#         # When ZERO Tier A signals fire, the document is unlikely to be
#         # genuinely manipulated; dampen the score by 30 %.
#         #
#         # This single rule is the primary defence against false positives
#         # on real salary slips, Aadhaar cards, PAN cards, offer letters,
#         # and bank statements — all of which routinely trigger weak/noisy
#         # Tier C modules (noise, edge, text_forensics) without any hard
#         # manipulation evidence.
#         strong_signals = sum(
#             1
#             for name in self.TIER_A
#             if name in active_scores
#             and not active_scores[name].skipped
#             and active_scores[name].score > settings.tampered_threshold
#         )
#         if strong_signals == 0:
#             base_score *= 0.70

#         # ── Step 6: Convert to 0-100 scale ────────────────────────
#         fraud_score = base_score * 100.0

#         # ── Step 7: Boolean verdict flags ─────────────────────────
#         edited       = self._flag_edited(active_scores)
#         ai_generated = self._flag_ai_generated(active_scores)
#         ai_assisted  = self._flag_ai_assisted(active_scores, ai_generated)
#         tampered     = self._flag_tampered(active_scores)

#         # ── Step 8: Flag-score consistency enforcement ────────────
#         # The weighted score can underestimate fraud when a supplementary
#         # module (weight=0) drives a flag.  Enforce floors so fraud_score
#         # is always semantically consistent with the flags.
#         # e.g. tampered=True must never produce risk=GENUINE or risk=LOW.
#         flag_states = {
#             "tampered":     tampered,
#             "edited":       edited,
#             "ai_generated": ai_generated,
#             "ai_assisted":  ai_assisted,
#         }
#         for flag_name, flag_value in flag_states.items():
#             if flag_value:
#                 floor = self.FLAG_SCORE_FLOORS[flag_name] * 100.0
#                 if fraud_score < floor:
#                     logger.debug(
#                         "Flag %s=True overrides score %.1f → %.1f",
#                         flag_name, fraud_score, floor,
#                     )
#                     fraud_score = floor

#         # ── Step 9: Tier-A gate for HIGH / CRITICAL ───────────────
#         #
#         # HIGH (61-80) and CRITICAL (81-100) risk levels require at least
#         # one Tier A module to have fired above threshold.  If no Tier A
#         # signal exists, cap the risk at MEDIUM (score capped at 60).
#         #
#         # This prevents a cluster of weak signals (noise + edge +
#         # text_forensics) from producing a HIGH or CRITICAL verdict on a
#         # genuine document — a common false-positive pattern observed in
#         # real-world BGV document forensics.
#         if strong_signals == 0 and fraud_score > 60.0:
#             logger.debug(
#                 "No Tier A signal fired — capping HIGH/CRITICAL score %.1f → 60.0",
#                 fraud_score,
#             )
#             fraud_score = 60.0

#         # ── Step 10: Risk level ───────────────────────────────────
#         risk_level = RiskLevel.from_score(fraud_score)

#         # ── Step 11: Genuine flag ─────────────────────────────────
#         # genuine = True ONLY when every other flag is False AND the
#         # score is in the GENUINE band.  Any positive flag disqualifies.
#         genuine = self._flag_genuine(
#             fraud_score, active_scores,
#             any_flag_set=(edited or ai_generated or ai_assisted or tampered),
#         )

#         # ── Step 12: Confidence ───────────────────────────────────
#         confidences = [
#             r.confidence for r in active_scores.values()
#             if r.module_name in self.MODULE_WEIGHTS
#         ]
#         raw_confidence = float(sum(confidences) / len(confidences)) if confidences else 0.5

#         # Penalise confidence when flags required a score floor uplift —
#         # it means the weighted modules disagreed with the structural
#         # signals, which is genuine analytical uncertainty.
#         any_flag = edited or ai_generated or ai_assisted or tampered
#         if any_flag and (fraud_score / 100.0) > (base_score + 0.05):
#             uplift_ratio = (fraud_score / 100.0) - base_score   # 0..1
#             penalty = min(uplift_ratio * 0.6, 0.25)             # cap at −25 pp
#             overall_confidence = max(raw_confidence - penalty, 0.30)
#             logger.debug(
#                 "Confidence penalised by %.3f (uplift=%.3f): %.3f → %.3f",
#                 penalty, uplift_ratio, raw_confidence, overall_confidence,
#             )
#         else:
#             overall_confidence = raw_confidence

#         # ── Step 13: Collect findings ──────────────────────────────
#         findings = self._collect_findings(active_scores)

#         # ── Step 14: Module score summary ─────────────────────────
#         module_score_map = {
#             name: result.score
#             for name, result in scores.items()
#         }

#         # ── Step 15: Collect bounding boxes ───────────────────────
#         all_bboxes = []
#         for result in scores.values():
#             for bbox in result.bounding_boxes:
#                 all_bboxes.append(bbox.as_dict)

#         # ── Step 16: Recommendation ────────────────────────────────
#         recommendation = self._generate_recommendation(
#             fraud_score, risk_level,
#             edited, ai_generated, ai_assisted, tampered,
#             findings,
#         )

#         # ── Step 17: Metadata extract ──────────────────────────────
#         metadata_dict: dict = {}
#         if ctx.metadata:
#             meta = ctx.metadata
#             metadata_dict = {
#                 "creator":           meta.creator,
#                 "producer":          meta.producer,
#                 "author":            meta.author,
#                 "software":          meta.software,
#                 "creation_date":     meta.creation_date.isoformat() if meta.creation_date else None,
#                 "modification_date": meta.modification_date.isoformat() if meta.modification_date else None,
#                 "camera_make":       meta.camera_make,
#                 "camera_model":      meta.camera_model,
#             }

#         processing_ms = int(
#             (datetime.utcnow() - processing_start).total_seconds() * 1000
#         )

#         verdict = FraudVerdict(
#             document_id=ctx.document_id,
#             job_id=ctx.job_id,
#             fraud_score=round(fraud_score, 2),
#             risk_level=risk_level,
#             edited=edited,
#             ai_generated=ai_generated,
#             ai_assisted=ai_assisted,
#             tampered=tampered,
#             genuine=genuine,
#             confidence=round(overall_confidence, 4),
#             findings=findings,
#             heatmap_path=heatmap_path,
#             module_scores=module_score_map,
#             bounding_boxes=all_bboxes,
#             recommendation=recommendation,
#             metadata=metadata_dict,
#             processing_time_ms=processing_ms,
#         )

#         logger.info(
#             "Verdict: score=%.2f risk=%s edited=%s ai=%s ai_assisted=%s "
#             "tampered=%s genuine=%s confidence=%.3f tier_a_signals=%d [%dms]",
#             fraud_score, risk_level.value,
#             edited, ai_generated, ai_assisted, tampered, genuine,
#             overall_confidence, strong_signals, processing_ms,
#         )

#         return verdict

#     # ─────────────────────────────────────────────
#     # Boolean flag logic
#     # ─────────────────────────────────────────────

#     def _flag_edited(self, scores: dict[str, ModuleScore]) -> bool:
#         """
#         Edited = strong signal from regional-modification modules.

#         FIX #1: Split into strong (ela, copymove, layout) and weak (edge,
#         noise, text_forensics) sets.  One strong signal suffices; three
#         weak signals are required.  This prevents noise + edge +
#         text_forensics from falsely flagging genuine scanned documents.
#         """
#         strong_scores = [
#             scores[m].score
#             for m in self.STRONG_EDIT
#             if m in scores and not scores[m].skipped
#         ]
#         weak_scores = [
#             scores[m].score
#             for m in self.WEAK_EDIT
#             if m in scores and not scores[m].skipped
#         ]

#         strong_count = sum(s > settings.edited_threshold for s in strong_scores)
#         weak_count   = sum(s > settings.edited_threshold for s in weak_scores)

#         return (strong_count >= 1) or (weak_count >= 3)

#     def _flag_ai_generated(self, scores: dict[str, ModuleScore]) -> bool:
#         """
#         AI generated = GAN fires AND at least one of ai_detection /
#         frequency fires above threshold.

#         FIX #3: GAN is now required.  Previously, ai_detection + frequency
#         was sufficient, which caused false positives because ai_detection
#         fires readily on genuine documents.  GAN score was the strongest
#         separator in real-world sample data.
#         """
#         gan_result = scores.get("gan")
#         if gan_result is None or gan_result.skipped:
#             return False
#         if gan_result.score <= settings.ai_generated_threshold:
#             return False

#         # GAN fired — check for corroboration from ai_detection or frequency
#         for module in ("ai_detection", "frequency"):
#             result = scores.get(module)
#             if result and not result.skipped:
#                 if result.score > settings.ai_generated_threshold:
#                     return True

#         return False

#     def _flag_ai_assisted(
#         self, scores: dict[str, ModuleScore], ai_generated: bool
#     ) -> bool:
#         """
#         AI assisted = elevated signal in AI modules but below full-
#         generation threshold.

#         Unchanged logic; relies on ai_generated being resolved first so
#         the two flags are mutually exclusive.
#         """
#         if ai_generated:
#             return False
#         ai_scores = [
#             scores[m].score
#             for m in self.AI_MODULES
#             if m in scores and not scores[m].skipped
#         ]
#         if not ai_scores:
#             return False
#         above_thresh = sum(s > settings.ai_assisted_threshold for s in ai_scores)
#         return above_thresh >= 2

#     def _flag_tampered(self, scores: dict[str, ModuleScore]) -> bool:
#         """
#         Tampered = structural modification detected.

#         FIX #2: Metadata alone no longer triggers tampered=True.
#         Rationale: metadata is routinely stripped by WhatsApp, scanner
#         apps, Adobe export, and mobile screenshots — all legitimate
#         sources.  Allowing metadata alone to set tampered=True would
#         produce pervasive false positives on genuine documents with
#         a score floor of 45 applied.

#         Rules (evaluated in priority order):
#           1. pdf_structure > threshold           → tampered
#           2. ela > threshold                     → tampered
#           3. metadata > threshold
#              AND pdf_structure > threshold       → tampered
#         """
#         thresh = settings.tampered_threshold

#         pdf_result  = scores.get("pdf_structure")
#         ela_result  = scores.get("ela")
#         meta_result = scores.get("metadata")

#         pdf_fired  = (
#             pdf_result is not None
#             and not pdf_result.skipped
#             and pdf_result.score > thresh
#         )
#         ela_fired  = (
#             ela_result is not None
#             and not ela_result.skipped
#             and ela_result.score > thresh
#         )
#         meta_fired = (
#             meta_result is not None
#             and not meta_result.skipped
#             and meta_result.score > thresh
#         )

#         # Rule 1 — pdf_structure alone is sufficient
#         if pdf_fired:
#             return True

#         # Rule 2 — ELA alone is sufficient (direct pixel-level evidence)
#         if ela_fired:
#             return True

#         # Rule 3 — metadata only counts when corroborated by pdf_structure
#         if meta_fired and pdf_fired:
#             return True

#         return False

#     def _flag_genuine(
#         self,
#         fraud_score: float,
#         scores: dict[str, ModuleScore],
#         any_flag_set: bool,
#     ) -> bool:
#         """
#         Genuine = score in GENUINE band AND no positive flags AND
#         no single weighted module is meaningfully elevated.

#         BUG FIX (carried forward): previously this could return True even
#         when tampered=True because it only checked fraud_score, not the
#         flag state.
#         """
#         if any_flag_set:
#             return False
#         if fraud_score > 20:
#             return False
#         weighted_modules = {
#             name for name, w in self.MODULE_WEIGHTS.items() if w > 0.0
#         }
#         max_score = max(
#             (r.score for name, r in scores.items()
#              if name in weighted_modules and not r.skipped),
#             default=0.0,
#         )
#         return max_score < 0.45

#     # ─────────────────────────────────────────────
#     # Helpers
#     # ─────────────────────────────────────────────

#     def _collect_findings(self, scores: dict[str, ModuleScore]) -> list[str]:
#         """Collect all findings from modules, deduplicated."""
#         all_findings: list[str] = []
#         for result in scores.values():
#             for finding in result.findings:
#                 entry = f"[{result.module_name.upper()}] {finding}"
#                 if entry not in all_findings:
#                     all_findings.append(entry)
#         return all_findings

#     def _generate_recommendation(
#         self,
#         score: float,
#         risk: RiskLevel,
#         edited: bool,
#         ai_generated: bool,
#         ai_assisted: bool,
#         tampered: bool,
#         findings: list[str],
#     ) -> str:
#         """Generate a human-readable recommendation based on the final verdict."""
#         if risk == RiskLevel.GENUINE:
#             return (
#                 "Document appears authentic. No significant manipulation indicators detected. "
#                 "Standard acceptance procedures apply."
#             )
#         elif risk == RiskLevel.LOW:
#             finding_count = len(findings)
#             if finding_count == 0:
#                 return (
#                     "No significant anomalies detected. Document appears consistent with "
#                     "a legitimate source."
#                 )
#             return (
#                 f"{finding_count} minor anomal{'y' if finding_count == 1 else 'ies'} detected "
#                 f"(score {score:.0f}/100). These may reflect normal image processing artefacts. "
#                 "A secondary review of flagged regions is recommended before acceptance."
#             )
#         elif risk == RiskLevel.MEDIUM:
#             parts = [f"Multiple forensic signals detected (score {score:.0f}/100)."]
#             if edited:
#                 parts.append("Evidence of regional editing found.")
#             if tampered:
#                 parts.append("Structural tampering detected.")
#             if ai_assisted:
#                 parts.append("Possible AI-assisted content detected.")
#             if ai_generated:
#                 parts.append("AI generation artifacts present.")
#             parts.append(
#                 "Manual verification of document origin and comparison with "
#                 "the original source is strongly recommended before acceptance."
#             )
#             return " ".join(parts)
#         elif risk == RiskLevel.HIGH:
#             parts = [f"Significant manipulation indicators detected (score {score:.0f}/100)."]
#             if edited:
#                 parts.append("Document shows signs of regional editing.")
#             if tampered:
#                 parts.append("Structural tampering detected.")
#             if ai_generated:
#                 parts.append("Document is likely AI-generated.")
#             elif ai_assisted:
#                 parts.append("AI-assisted content is likely present.")
#             parts.append(
#                 "Reject document and request the original. Escalate to the fraud team if needed."
#             )
#             return " ".join(parts)
#         else:  # CRITICAL
#             parts = [f"CRITICAL: High-confidence manipulation detected (score {score:.0f}/100)."]
#             if ai_generated:
#                 parts.append("Document is AI-generated or AI-assisted.")
#             if edited:
#                 parts.append("Extensive editing detected across multiple regions.")
#             if tampered:
#                 parts.append("Document structure shows clear tampering.")
#             parts.append(
#                 "REJECT immediately. Do not process. Escalate to the security/fraud team "
#                 "for investigation and preserve the original file as evidence."
#             )
#             return " ".join(parts)


"""
Fraud Scoring Engine

═══════════════════════════════════════════════════════════════
THEORY
═══════════════════════════════════════════════════════════════
The scoring engine aggregates signals from all forensic modules
into a single fraud score (0-100) and categorical risk level.

Design decisions:
1. Weighted linear combination as the base
2. Evidence amplification: when multiple modules agree, score is amplified
3. Evidence dampening: when only one module fires, confidence is reduced
4. Module confidence weighting: low-confidence modules contribute less
5. Outlier handling: a single module at 0.85+ triggers minimum HIGH risk
6. Tamper/flag override: any positive flag enforces a score floor so that
   fraud_score is ALWAYS consistent with the boolean verdict flags —
   i.e. tampered=True can never coexist with risk=GENUINE/LOW.
7. Confidence penalty: when flags and raw score diverge, confidence is
   reduced to signal that the weighted score underestimates the real risk.

Tier-gated HIGH/CRITICAL risk:
   HIGH and CRITICAL risk levels require at least one Tier A signal to fire.
   This prevents weak/noisy modules (edge, noise, baseline, kerning) from
   inflating risk on genuine documents such as salary slips, Aadhaar cards,
   PAN cards, offer letters, and bank statements.

Evidence tiers:
   Tier A (Very Strong) : ela, gan, copymove  — direct manipulation evidence
   Tier B (Strong)      : layout, font         — structural/content indicators
   Tier C (Weak)        : noise, edge, metadata, color, frequency,
                          text_forensics       — supportive only

Risk Levels:
  0-20  → GENUINE        (very likely authentic)
  21-40 → LOW RISK       (minor anomalies, likely clean)
  41-60 → MEDIUM RISK    (multiple signals, review recommended)
  61-80 → HIGH RISK      (strong tampering indicators)
  81-100→ CRITICAL RISK  (definite manipulation detected)

Verdict Flags:
  edited        = strong signal from regional-modification modules
                  (strong_count >= 1  OR  weak_count >= 3)
  ai_generated  = GAN fires AND at least one of ai_detection / frequency
                  fires above threshold
  ai_assisted   = not ai_generated AND ai_detection fires alone at a
                  lower threshold
  tampered      = pdf_structure fires  OR  ela fires  OR
                  (metadata AND pdf_structure both fire)
  genuine       = ALL flags False AND score ≤ 20 AND no module elevated
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from app.core.config import settings
from app.domain.entities.document import (
    ForensicContext,
    FraudVerdict,
    ModuleScore,
    RiskLevel,
)

logger = logging.getLogger("docfraud.scoring")


class FraudScoringEngine:
    """
    Aggregates forensic module results into a final FraudVerdict.
    """

    # Module weights — weighted modules must sum to 1.0
    MODULE_WEIGHTS: dict[str, float] = {
        "ela":            0.22,
        "noise":          0.07,
        "copymove":       0.08,
        "edge":           0.04,
        "color":          0.04,
        "font":           0.08,
        "ai_detection":   0.08,
        "gan":            0.15,
        "frequency":      0.08,
        "layout":         0.06,
        "text_forensics": 0.16,
        # Supplementary — zero weight in sum, but drive flag + score floor
        "metadata":       0.00,
        "pdf_structure":  0.00,
    }

    # Score floor enforced when a flag fires — ensures fraud_score is
    # always semantically consistent with the boolean verdict flags.
    FLAG_SCORE_FLOORS: dict[str, float] = {
        "tampered":     0.35,   # tampered=True  → minimum MEDIUM (45)
        "edited":       0.30,   # edited=True    → minimum MEDIUM (40)
        "ai_generated": 0.55,   # ai_generated   → minimum HIGH   (55)
        "ai_assisted":  0.30,   # ai_assisted    → minimum MEDIUM (42)
    }

    # ── Split EDITED_MODULES into strong / weak sets ─────────────────────
    #
    # STRONG_EDIT — direct pixel-level manipulation evidence.
    #   One signal above its individual threshold is sufficient for edited=True.
    #   Thresholds: ela > 0.40 | copymove > 0.40 | layout > 0.50
    #
    # WEAK_EDIT — noisy signals that fire on genuine scanned / forwarded docs.
    #   All three must fire above their RAISED thresholds before edited=True.
    #   Thresholds: noise > 0.60 | edge > 0.60 | text_forensics > 0.70
    #
    #   The text_forensics threshold (0.70) is deliberately high because
    #   baseline wobble, kerning CV, and character spacing all fire at
    #   0.20-0.40 on ordinary scanned documents.  A score of 0.70+ means
    #   text was actually replaced or edited, not merely scanned.
    #   If text_forensics is scoring 0.62+ on genuine docs the module itself
    #   needs recalibration — the 0.70 guard here is a band-aid, not a fix.
    #
    STRONG_EDIT: set[str] = {
        "ela",
        "copymove",
        "layout",
    }

    WEAK_EDIT: set[str] = {
        "edge",
        "noise",
        "text_forensics",
    }

    # AI detection modules (unchanged)
    AI_MODULES: set[str] = {"ai_detection", "gan", "frequency"}

    # ── FIX #2 / FIX #3: Tier-based evidence classification ──────────────
    #
    # HIGH and CRITICAL risk levels are only reachable when at least one
    # Tier A signal fires.  This prevents weak modules (Tier C) from
    # escalating genuine documents to HIGH/CRITICAL.
    #
    # Tier A — very strong, direct manipulation evidence
    TIER_A: set[str] = {"ela", "gan", "copymove"}

    # Tier B — strong structural / content indicators
    TIER_B: set[str] = {"layout", "font"}

    # Tier C — weak / noisy; supportive only
    TIER_C: set[str] = {
        "noise", "edge", "metadata", "color",
        "frequency", "text_forensics",
    }

    def compute(
        self,
        ctx: ForensicContext,
        heatmap_path: Optional[str],
        processing_start: datetime,
    ) -> FraudVerdict:
        """
        Compute the final fraud verdict from all module scores.
        """
        scores = ctx.module_scores
        active_scores = {
            name: result
            for name, result in scores.items()
            if not result.skipped and result.error is None
        }

        # ── Step 1: Weighted base score ──────────────────────────
        weighted_sum = 0.0
        total_weight = 0.0

        for module_name, weight in self.MODULE_WEIGHTS.items():
            if weight == 0.0:
                continue
            result = active_scores.get(module_name)
            if result is None:
                continue
            effective_weight = weight * result.confidence
            weighted_sum    += effective_weight * result.score
            total_weight    += effective_weight

        base_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

        # ── Step 2: Evidence amplification ───────────────────────
        # Count weighted modules with score > 0.5 (meaningful signal).
        # Check >=5 FIRST — otherwise the >=3 branch always wins and the
        # >=5 branch becomes unreachable dead code.
        high_modules = [
            r for r in active_scores.values()
            if r.score > 0.5 and r.module_name in self.MODULE_WEIGHTS
        ]
        if len(high_modules) >= 5:
            base_score = min(base_score * 1.20, 1.0)
        elif len(high_modules) >= 3:
            base_score = min(base_score * 1.12, 1.0)

        # ── Step 3: Critical single-module override ───────────────
        # A single very strong signal is itself evidence of fraud.
        max_single = max(
            (r.score for r in active_scores.values()
             if r.module_name in self.MODULE_WEIGHTS),
            default=0.0,
        )
        if max_single >= 0.85:
            base_score = max(base_score, 0.65)   # → minimum HIGH
        elif max_single >= 0.70:
            base_score = max(base_score, 0.42)   # → minimum MEDIUM

        # ── Step 4: Supplementary module boosting ─────────────────
        # metadata and pdf_structure carry zero weight (they don't
        # participate in the weighted average) but are strong structural
        # signals when they fire, so we add an additive boost.
        meta_result = active_scores.get("metadata")
        pdf_result  = active_scores.get("pdf_structure")

        if meta_result and meta_result.score > 0.5:
            base_score = min(base_score + 0.08, 1.0)
        if pdf_result and pdf_result.score > 0.5:
            base_score = min(base_score + 0.10, 1.0)

        # ── Step 5: Strong-evidence counter ───────────────────────
        #
        # Count Tier A signals that fired above their specific thresholds.
        # These thresholds are intentionally lower than the scoring-engine
        # tampered_threshold because we're checking for meaningful presence,
        # not full confidence:
        #
        #   ela_regions >= 5   — five separate anomalous regions; never genuine
        #   checkerboard > 0.8 — definitive GAN pattern; cannot appear in photos
        #   layout_cv > 1.0    — extreme structural inconsistency
        #   copymove > 0.4     — clone detection; low FP on real documents
        #
        # The counter drives two effects:
        #   A. Score DAMPENING  — zero strong signals → ×0.70 (suppress FP)
        #   B. Score AMPLIFYING — 2+ strong signals   → ×1.30 (boost TP)
        #      3+ strong signals → ×1.50 (strong separation for obvious fakes)
        #
        # Effect B is the key new change: it lets manipulated documents
        # with multiple hard indicators separate dramatically from genuine
        # documents that only trigger Tier C (noise, edge, text_forensics).

        # Retrieve the raw signals the modules already computed
        ela_result       = active_scores.get("ela")
        gan_result       = active_scores.get("gan")
        layout_result    = active_scores.get("layout")
        copymove_result  = active_scores.get("copymove")

        # Module-level values needed for the floor rules below
        ela_region_count      = getattr(ela_result,     "_region_count",      0)   if ela_result     else 0
        gan_checkerboard      = getattr(gan_result,     "_checkerboard_score", 0.0) if gan_result     else 0.0
        layout_cv_value       = getattr(layout_result,  "_cv",                0.0) if layout_result  else 0.0
        copymove_score_value  = copymove_result.score if copymove_result and not copymove_result.skipped else 0.0

        strong_signals = 0

        if ela_region_count >= 5:
            strong_signals += 1
        if gan_checkerboard > 0.80:
            strong_signals += 1
        if layout_cv_value > 1.0:
            strong_signals += 1
        if copymove_score_value > 0.40:
            strong_signals += 1

        logger.debug(
            "Strong-signal counter: ela_regions=%d cb=%.3f layout_cv=%.3f "
            "copymove=%.3f  →  strong_signals=%d",
            ela_region_count, gan_checkerboard, layout_cv_value,
            copymove_score_value, strong_signals,
        )

        # Effect A — dampen when there is NO hard evidence (suppress FP)
        if strong_signals == 0:
            base_score *= 0.70

        # Effect B — amplify when multiple hard signals agree (boost TP)
        elif strong_signals >= 3:
            base_score = min(base_score * 1.50, 1.0)
        elif strong_signals >= 2:
            base_score = min(base_score * 1.30, 1.0)

        # ── Step 5b: Hard score floors for individual strong signals ──
        #
        # Applied AFTER the multiplier so they can only raise, never lower.
        # These match the "Most Important Change" recommendation:
        #
        #   ela_regions >= 5     → floor 0.75  (definite editing)
        #   checkerboard >= 0.80 → floor 0.85  (definitive GAN artefact)
        #   layout_cv >= 1.0     → floor 0.75  (extreme structural anomaly)
        #
        # These three lines alone move an obvious fake from LOW (0.29) to
        # HIGH (0.65–0.80) while genuine documents (which lack all three)
        # are unaffected.
        if ela_region_count >= 5:
            base_score = max(base_score, 0.75)
            logger.debug("ELA floor applied (regions=%d): base_score=%.3f", ela_region_count, base_score)

        if gan_checkerboard >= 0.80:
            base_score = max(base_score, 0.85)
            logger.debug("GAN floor applied (cb=%.3f): base_score=%.3f", gan_checkerboard, base_score)

        if layout_cv_value >= 1.0:
            base_score = max(base_score, 0.75)
            logger.debug("Layout floor applied (cv=%.3f): base_score=%.3f", layout_cv_value, base_score)

        # ── Step 6: Convert to 0-100 scale ────────────────────────
        fraud_score = base_score * 100.0

        # ── Step 7: Boolean verdict flags ─────────────────────────
        edited       = self._flag_edited(active_scores)
        ai_generated = self._flag_ai_generated(active_scores)
        ai_assisted  = self._flag_ai_assisted(active_scores, ai_generated)
        tampered     = self._flag_tampered(active_scores)

        # ── Step 8: Flag-score consistency enforcement ────────────
        # The weighted score can underestimate fraud when a supplementary
        # module (weight=0) drives a flag.  Enforce floors so fraud_score
        # is always semantically consistent with the flags.
        # e.g. tampered=True must never produce risk=GENUINE or risk=LOW.
        flag_states = {
            "tampered":     tampered,
            "edited":       edited,
            "ai_generated": ai_generated,
            "ai_assisted":  ai_assisted,
        }
        for flag_name, flag_value in flag_states.items():
            if flag_value:
                floor = self.FLAG_SCORE_FLOORS[flag_name] * 100.0
                if fraud_score < floor:
                    logger.debug(
                        "Flag %s=True overrides score %.1f → %.1f",
                        flag_name, fraud_score, floor,
                    )
                    fraud_score = floor

        # ── Step 9: Tier-A gate for HIGH / CRITICAL ───────────────
        #
        # HIGH (61-80) and CRITICAL (81-100) risk levels require at least
        # one Tier A module to have fired above threshold.  If no Tier A
        # signal exists, cap the risk at MEDIUM (score capped at 60).
        #
        # This prevents a cluster of weak signals (noise + edge +
        # text_forensics) from producing a HIGH or CRITICAL verdict on a
        # genuine document — a common false-positive pattern observed in
        # real-world BGV document forensics.
        if strong_signals == 0 and fraud_score > 60.0:
            logger.debug(
                "No Tier A signal fired — capping HIGH/CRITICAL score %.1f → 60.0",
                fraud_score,
            )
            fraud_score = 60.0

        # ── Step 10: Risk level ───────────────────────────────────
        risk_level = RiskLevel.from_score(fraud_score)

        # ── Step 11: Genuine flag ─────────────────────────────────
        # genuine = True ONLY when every other flag is False AND the
        # score is in the GENUINE band.  Any positive flag disqualifies.
        genuine = self._flag_genuine(
            fraud_score, active_scores,
            any_flag_set=(edited or ai_generated or ai_assisted or tampered),
        )

        # ── Step 12: Confidence ───────────────────────────────────
        confidences = [
            r.confidence for r in active_scores.values()
            if r.module_name in self.MODULE_WEIGHTS
        ]
        raw_confidence = float(sum(confidences) / len(confidences)) if confidences else 0.5

        # Penalise confidence when flags required a score floor uplift —
        # it means the weighted modules disagreed with the structural
        # signals, which is genuine analytical uncertainty.
        any_flag = edited or ai_generated or ai_assisted or tampered
        if any_flag and (fraud_score / 100.0) > (base_score + 0.05):
            uplift_ratio = (fraud_score / 100.0) - base_score   # 0..1
            penalty = min(uplift_ratio * 0.6, 0.25)             # cap at −25 pp
            overall_confidence = max(raw_confidence - penalty, 0.30)
            logger.debug(
                "Confidence penalised by %.3f (uplift=%.3f): %.3f → %.3f",
                penalty, uplift_ratio, raw_confidence, overall_confidence,
            )
        else:
            overall_confidence = raw_confidence

        # ── Step 13: Collect findings ──────────────────────────────
        findings = self._collect_findings(active_scores)

        # ── Step 14: Module score summary ─────────────────────────
        module_score_map = {
            name: result.score
            for name, result in scores.items()
        }

        # ── Step 15: Collect bounding boxes ───────────────────────
        all_bboxes = []
        for result in scores.values():
            for bbox in result.bounding_boxes:
                all_bboxes.append(bbox.as_dict)

        # ── Step 16: Recommendation ────────────────────────────────
        recommendation = self._generate_recommendation(
            fraud_score, risk_level,
            edited, ai_generated, ai_assisted, tampered,
            findings,
        )

        # ── Step 17: Metadata extract ──────────────────────────────
        metadata_dict: dict = {}
        if ctx.metadata:
            meta = ctx.metadata
            metadata_dict = {
                "creator":           meta.creator,
                "producer":          meta.producer,
                "author":            meta.author,
                "software":          meta.software,
                "creation_date":     meta.creation_date.isoformat() if meta.creation_date else None,
                "modification_date": meta.modification_date.isoformat() if meta.modification_date else None,
                "camera_make":       meta.camera_make,
                "camera_model":      meta.camera_model,
            }

        processing_ms = int(
            (datetime.utcnow() - processing_start).total_seconds() * 1000
        )

        verdict = FraudVerdict(
            document_id=ctx.document_id,
            job_id=ctx.job_id,
            fraud_score=round(fraud_score, 2),
            risk_level=risk_level,
            edited=edited,
            ai_generated=ai_generated,
            ai_assisted=ai_assisted,
            tampered=tampered,
            genuine=genuine,
            confidence=round(overall_confidence, 4),
            findings=findings,
            heatmap_path=heatmap_path,
            module_scores=module_score_map,
            bounding_boxes=all_bboxes,
            recommendation=recommendation,
            metadata=metadata_dict,
            processing_time_ms=processing_ms,
        )

        logger.info(
            "Verdict: score=%.2f risk=%s edited=%s ai=%s ai_assisted=%s "
            "tampered=%s genuine=%s confidence=%.3f tier_a_signals=%d [%dms]",
            fraud_score, risk_level.value,
            edited, ai_generated, ai_assisted, tampered, genuine,
            overall_confidence, strong_signals, processing_ms,
        )

        return verdict

    # ─────────────────────────────────────────────
    # Boolean flag logic
    # ─────────────────────────────────────────────

    def _flag_edited(self, scores: dict[str, ModuleScore]) -> bool:
        """
        Edited = strong signal from regional-modification modules.

        Strong modules (ela, copymove, layout) — one is sufficient.
        Each has its own threshold tuned to its signal distribution:
          ela      > 0.40  (pixel compression artefacts; fires cleanly)
          copymove > 0.40  (clone detection; low FP rate on genuine docs)
          layout   > 0.40  (structural shift; needs a slightly higher bar)

        Weak modules (noise, edge, text_forensics) — all three must fire,
        and each has a RAISED threshold to suppress false positives on
        genuine scanned/forwarded documents:
          noise         > 0.60  (genuine scans routinely reach 0.35-0.55)
          edge          > 0.60  (JPEG/WhatsApp compression adds edge noise)
          text_forensics > 0.70 (baseline wobble + kerning CV fire at 0.20-
                                 0.40 on real docs; 0.70 means text was
                                 actually replaced/edited, not just scanned)

        NOTE on text_forensics:  if the module is scoring 0.62+ on genuine
        documents, the issue is upstream in the module itself — baseline
        shift, kerning CV, and character spacing sub-signals are too
        sensitive and need recalibration so that normal scans land in the
        0.20-0.40 range.  The 0.70 threshold here is a scoring-engine
        guard-rail, not a substitute for fixing the module.
        """
        def _score(module: str) -> float:
            r = scores.get(module)
            if r is None or r.skipped:
                return 0.0
            return r.score

        # ── Strong signals (individual thresholds) ────────────────
        strong_edit = 0

        if _score("ela") > 0.40:
            strong_edit += 1

        if _score("copymove") > 0.40:
            strong_edit += 1

        if _score("layout") > 0.40:
            strong_edit += 1

        if strong_edit >= 1:
            return True

        # ── Weak signals (raised thresholds; all three must fire) ──
        weak_edit = 0

        if _score("noise") > 0.60:
            weak_edit += 1

        if _score("edge") > 0.60:
            weak_edit += 1

        if _score("text_forensics") > 0.70:
            weak_edit += 1

        return weak_edit >= 3

    def _flag_ai_generated(self, scores: dict[str, ModuleScore]) -> bool:
        """
        AI generated = GAN fires AND at least one of ai_detection /
        frequency fires above threshold.

        FIX #3: GAN is now required.  Previously, ai_detection + frequency
        was sufficient, which caused false positives because ai_detection
        fires readily on genuine documents.  GAN score was the strongest
        separator in real-world sample data.
        """
        gan_result = scores.get("gan")
        if gan_result is None or gan_result.skipped:
            return False
        if gan_result.score <= settings.ai_generated_threshold:
            return False

        # GAN fired — check for corroboration from ai_detection or frequency
        for module in ("ai_detection", "frequency"):
            result = scores.get(module)
            if result and not result.skipped:
                if result.score > settings.ai_generated_threshold:
                    return True

        return False

    def _flag_ai_assisted(
        self, scores: dict[str, ModuleScore], ai_generated: bool
    ) -> bool:
        """
        AI assisted = elevated signal in AI modules but below full-
        generation threshold.

        Unchanged logic; relies on ai_generated being resolved first so
        the two flags are mutually exclusive.
        """
        if ai_generated:
            return False
        ai_scores = [
            scores[m].score
            for m in self.AI_MODULES
            if m in scores and not scores[m].skipped
        ]
        if not ai_scores:
            return False
        above_thresh = sum(s > settings.ai_assisted_threshold for s in ai_scores)
        return above_thresh >= 2

    def _flag_tampered(self, scores: dict[str, ModuleScore]) -> bool:
        """
        Tampered = structural modification detected.

        FIX #2: Metadata alone no longer triggers tampered=True.
        Rationale: metadata is routinely stripped by WhatsApp, scanner
        apps, Adobe export, and mobile screenshots — all legitimate
        sources.  Allowing metadata alone to set tampered=True would
        produce pervasive false positives on genuine documents with
        a score floor of 45 applied.

        Rules (evaluated in priority order):
          1. pdf_structure > threshold           → tampered
          2. ela > threshold                     → tampered
          3. metadata > threshold
             AND pdf_structure > threshold       → tampered
        """
        thresh = settings.tampered_threshold

        pdf_result  = scores.get("pdf_structure")
        ela_result  = scores.get("ela")
        meta_result = scores.get("metadata")

        pdf_fired  = (
            pdf_result is not None
            and not pdf_result.skipped
            and pdf_result.score > thresh
        )
        ela_fired  = (
            ela_result is not None
            and not ela_result.skipped
            and ela_result.score > thresh
        )
        meta_fired = (
            meta_result is not None
            and not meta_result.skipped
            and meta_result.score > thresh
        )

        # Rule 1 — pdf_structure alone is sufficient
        if pdf_fired:
            return True

        # Rule 2 — ELA alone is sufficient (direct pixel-level evidence)
        if ela_fired:
            return True

        # Rule 3 — metadata only counts when corroborated by pdf_structure
        if meta_fired and pdf_fired:
            return True

        return False

    def _flag_genuine(
        self,
        fraud_score: float,
        scores: dict[str, ModuleScore],
        any_flag_set: bool,
    ) -> bool:
        """
        Genuine = score in GENUINE band AND no positive flags AND
        no single weighted module is meaningfully elevated.

        BUG FIX (carried forward): previously this could return True even
        when tampered=True because it only checked fraud_score, not the
        flag state.
        """
        if any_flag_set:
            return False
        if fraud_score > 20:
            return False
        weighted_modules = {
            name for name, w in self.MODULE_WEIGHTS.items() if w > 0.0
        }
        max_score = max(
            (r.score for name, r in scores.items()
             if name in weighted_modules and not r.skipped),
            default=0.0,
        )
        return max_score < 0.45

    # ─────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────

    def _collect_findings(self, scores: dict[str, ModuleScore]) -> list[str]:
        """Collect all findings from modules, deduplicated."""
        all_findings: list[str] = []
        for result in scores.values():
            for finding in result.findings:
                entry = f"[{result.module_name.upper()}] {finding}"
                if entry not in all_findings:
                    all_findings.append(entry)
        return all_findings

    def _generate_recommendation(
        self,
        score: float,
        risk: RiskLevel,
        edited: bool,
        ai_generated: bool,
        ai_assisted: bool,
        tampered: bool,
        findings: list[str],
    ) -> str:
        """Generate a human-readable recommendation based on the final verdict."""
        if risk == RiskLevel.GENUINE:
            return (
                "Document appears authentic. No significant manipulation indicators detected. "
                "Standard acceptance procedures apply."
            )
        elif risk == RiskLevel.LOW:
            finding_count = len(findings)
            if finding_count == 0:
                return (
                    "No significant anomalies detected. Document appears consistent with "
                    "a legitimate source."
                )
            return (
                f"{finding_count} minor anomal{'y' if finding_count == 1 else 'ies'} detected "
                f"(score {score:.0f}/100). These may reflect normal image processing artefacts. "
                "A secondary review of flagged regions is recommended before acceptance."
            )
        elif risk == RiskLevel.MEDIUM:
            parts = [f"Multiple forensic signals detected (score {score:.0f}/100)."]
            if edited:
                parts.append("Evidence of regional editing found.")
            if tampered:
                parts.append("Structural tampering detected.")
            if ai_assisted:
                parts.append("Possible AI-assisted content detected.")
            if ai_generated:
                parts.append("AI generation artifacts present.")
            parts.append(
                "Manual verification of document origin and comparison with "
                "the original source is strongly recommended before acceptance."
            )
            return " ".join(parts)
        elif risk == RiskLevel.HIGH:
            parts = [f"Significant manipulation indicators detected (score {score:.0f}/100)."]
            if edited:
                parts.append("Document shows signs of regional editing.")
            if tampered:
                parts.append("Structural tampering detected.")
            if ai_generated:
                parts.append("Document is likely AI-generated.")
            elif ai_assisted:
                parts.append("AI-assisted content is likely present.")
            parts.append(
                "Reject document and request the original. Escalate to the fraud team if needed."
            )
            return " ".join(parts)
        else:  # CRITICAL
            parts = [f"CRITICAL: High-confidence manipulation detected (score {score:.0f}/100)."]
            if ai_generated:
                parts.append("Document is AI-generated or AI-assisted.")
            if edited:
                parts.append("Extensive editing detected across multiple regions.")
            if tampered:
                parts.append("Document structure shows clear tampering.")
            parts.append(
                "REJECT immediately. Do not process. Escalate to the security/fraud team "
                "for investigation and preserve the original file as evidence."
            )
            return " ".join(parts)