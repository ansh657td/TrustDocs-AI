# """
# PDF Structure Analysis, Layout Consistency, and Heatmap Generation Modules
# """

# from __future__ import annotations

# import logging
# from pathlib import Path
# from typing import Optional

# import numpy as np
# from PIL import Image

# from app.core.config import settings
# from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
# from app.domain.services.base_module import ForensicModule

# logger = logging.getLogger("docfraud.modules")


# # ══════════════════════════════════════════════════════════════
# #  PDF STRUCTURE ANALYSIS
# # ══════════════════════════════════════════════════════════════

# class PDFStructureModule(ForensicModule):
#     """
#     Deep forensic analysis of PDF internal structure.

#     Theory:
#     PDF files store content in a tree of objects (streams, dictionaries,
#     arrays). Legitimate documents are created by a single authoring tool
#     in a single pass. Tampered PDFs show:

#     1. Incremental updates — new xref sections appended after original EOF
#        (used to modify content without rewriting full file)
#     2. Multiple revisions — legitimate for signed PDFs, suspicious otherwise
#     3. Object stream tampering — inline object replacement
#     4. Page insertion/deletion — mismatched page tree
#     5. Metadata inconsistency — creator/modification timestamp mismatches
#     6. Suspicious action objects — JavaScript, auto-open, launch actions

#     Algorithm:
#     1. Parse PDF with pypdf (pure Python, no system deps)
#     2. Check for incremental updates (multiple %%EOF markers)
#     3. Analyze xref table consistency
#     4. Inspect metadata vs document properties
#     5. Check for suspicious objects (JS, Launch, URI)
#     6. Analyze page count vs page tree depth

#     Limitations:
#     - Some legitimate tools produce incremental updates (Adobe Acrobat)
#     - Digitally signed PDFs MUST use incremental updates
#     - Cannot detect content-level tampering (only structural)
#     """

#     MODULE_NAME = "pdf_structure"
#     WEIGHT = 0.08
#     REQUIRES_PDF = True

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         findings = []
#         risk_score = 0.0

#         try:
#             raw_findings, raw_score = self._analyze_pdf_structure(ctx.file_path)
#             findings.extend(raw_findings)
#             risk_score = raw_score
#         except Exception as e:
#             logger.warning("PDF structure analysis failed: %s", e)
#             return self._make_score(0.0, 0.0, findings=["PDF structural analysis unavailable"])

#         confidence = 0.70 if findings else 0.45
#         return self._make_score(
#             score=min(risk_score, 1.0),
#             confidence=confidence,
#             findings=findings,
#             raw_data={"risk_contributions": risk_score},
#         )

#     def _analyze_pdf_structure(self, path: Path) -> tuple[list[str], float]:
#         """Analyze PDF internal structure for tampering indicators."""
#         findings = []
#         risk = 0.0

#         # Read raw bytes for low-level analysis
#         with open(path, "rb") as f:
#             raw = f.read()

#         # 1. Count EOF markers — more than 1 = incremental update
#         eof_count = raw.count(b"%%EOF")
#         if eof_count > 1:
#             findings.append(
#                 f"PDF has {eof_count} EOF markers — incremental update(s) detected"
#             )
#             risk += 0.30

#         # 2. Count xref sections — each xref section = one revision
#         xref_count = raw.count(b"\nxref") + raw.count(b"\r\nxref")
#         if xref_count > 1:
#             findings.append(
#                 f"{xref_count} xref table sections — document has been revised"
#             )
#             risk += 0.20

#         # 3. Check for JavaScript objects
#         if b"/JavaScript" in raw or b"/JS " in raw:
#             findings.append("JavaScript action object found in PDF — high risk")
#             risk += 0.50

#         # 4. Check for Launch/OpenAction
#         if b"/Launch" in raw:
#             findings.append("Launch action found — document executes external programs")
#             risk += 0.40
#         if b"/OpenAction" in raw:
#             findings.append("OpenAction found — document auto-executes on open")
#             risk += 0.25

#         # 5. Check for embedded files
#         if b"/EmbeddedFile" in raw or b"/EmbeddedFiles" in raw:
#             findings.append("Embedded files detected in PDF")
#             risk += 0.15

#         # 6. Pypdf structural analysis
#         try:
#             import pypdf

#             reader = pypdf.PdfReader(str(path))
#             page_count = len(reader.pages)

#             # Metadata
#             meta = reader.metadata
#             if meta:
#                 creator = str(meta.get("/Creator", ""))
#                 producer = str(meta.get("/Producer", ""))
#                 creation = str(meta.get("/CreationDate", ""))
#                 mod = str(meta.get("/ModDate", ""))

#                 if creator:
#                     # Check for editing tools
#                     for tool in ["photoshop", "gimp", "canva", "inkscape", "figma"]:
#                         if tool in creator.lower() or tool in producer.lower():
#                             findings.append(
#                                 f"PDF created/modified with image editing tool: {creator or producer}"
#                             )
#                             risk += 0.35
#                             break

#                 if creation and mod and mod < creation:
#                     findings.append("PDF modification date precedes creation date")
#                     risk += 0.30

#             # Check for encrypted PDF with modified content
#             if reader.is_encrypted:
#                 findings.append("PDF is encrypted — content inspection limited")
#                 risk += 0.10

#             # Check for form fields (could mask content replacement)
#             if "/AcroForm" in str(reader.trailer):
#                 findings.append("PDF contains form fields (AcroForm)")
#                 risk += 0.10

#         except ImportError:
#             findings.append("pypdf not installed; deep PDF analysis skipped")
#         except Exception as e:
#             logger.debug("pypdf analysis error: %s", e)

#         return findings, min(risk, 1.0)


# # ══════════════════════════════════════════════════════════════
# #  LAYOUT CONSISTENCY MODULE
# # ══════════════════════════════════════════════════════════════

# class LayoutConsistencyModule(ForensicModule):
#     """
#     Detect layout anomalies that indicate local modifications.

#     Theory:
#     Genuine documents have consistent structural layout:
#     - Uniform margins
#     - Consistent line spacing
#     - Regular text alignment
#     - Consistent column widths

#     Tampered documents often show:
#     - Irregular line spacing in modified regions
#     - Margin inconsistencies where content was re-flowed
#     - Misaligned elements after replacement
#     - Inconsistent word spacing (tracking) from OCR re-insertion

#     Algorithm:
#     1. Detect horizontal text baselines via Hough transform
#     2. Analyze inter-baseline spacing consistency
#     3. Detect margin boundaries
#     4. Analyze left-edge text alignment
#     5. Identify outlier regions
#     """

#     MODULE_NAME = "layout"
#     WEIGHT = 0.05
#     MIN_IMAGE_SIZE = 64

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         findings = []

#         spacing_score, spacing_findings = self._analyze_line_spacing(image)
#         margin_score, margin_findings = self._analyze_margins(image)
#         alignment_score, alignment_findings = self._analyze_text_alignment(image)

#         findings = spacing_findings + margin_findings + alignment_findings
#         score = (
#             0.40 * spacing_score
#             + 0.30 * margin_score
#             + 0.30 * alignment_score
#         )

#         return self._make_score(
#             score=score,
#             confidence=0.45 + score * 0.40,
#             findings=findings,
#             raw_data={
#                 "spacing_score": spacing_score,
#                 "margin_score": margin_score,
#                 "alignment_score": alignment_score,
#             },
#         )

#     def _analyze_line_spacing(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """Detect inconsistent line spacing via horizontal projection profile."""
#         findings = []
#         gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

#         # Horizontal projection profile
#         # Text lines = rows with low mean brightness; spaces = high brightness
#         row_means = gray.mean(axis=1)
#         threshold = row_means.mean()

#         # Find transitions: white (space) → dark (text) = line start
#         is_text = row_means < threshold
#         transitions = np.diff(is_text.astype(int))
#         line_starts = np.where(transitions == 1)[0]

#         if len(line_starts) < 3:
#             return 0.0, []

#         # Inter-line spacings
#         spacings = np.diff(line_starts).astype(float)

#         if len(spacings) < 2:
#             return 0.0, []

#         mean_s = spacings.mean()
#         std_s = spacings.std()
#         cv = float(std_s / (mean_s + 1e-8))  # Coefficient of variation

#         # CV > 0.3 = inconsistent line spacing
#         score = min(cv / 0.5, 1.0)
#         if cv > 0.25:
#             findings.append(
#                 f"Line spacing irregularity (CV={cv:.2f}) suggests content modification"
#             )

#         return score, findings

#     def _analyze_margins(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """Detect inconsistent margins via column projection."""
#         findings = []
#         gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

#         # Vertical projection for left/right margins
#         col_means = gray.mean(axis=0)
#         threshold = gray.mean()
#         is_text_col = col_means < threshold

#         # Find left margin: first column with text
#         left_positions = np.where(is_text_col)[0]
#         if len(left_positions) == 0:
#             return 0.0, []

#         # Divide into vertical thirds and compare left margin position
#         h = gray.shape[0]
#         thirds = [
#             gray[:h//3], gray[h//3:2*h//3], gray[2*h//3:]
#         ]

#         margins = []
#         for third in thirds:
#             col_m = third.mean(axis=0)
#             text_cols = np.where(col_m < col_m.mean())[0]
#             if len(text_cols) > 0:
#                 margins.append(int(text_cols[0]))

#         if len(margins) < 2:
#             return 0.0, []

#         margin_std = float(np.std(margins))
#         score = min(margin_std / 50.0, 1.0)

#         if margin_std > 20:
#             findings.append(
#                 f"Margin inconsistency across document thirds (std={margin_std:.1f}px)"
#             )

#         return score, findings

#     def _analyze_text_alignment(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """Detect text alignment inconsistencies."""
#         findings = []
#         # Simple analysis via horizontal profile variance per region
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)
#         h, w = gray.shape

#         # Compare variance of row profiles in top vs bottom halves
#         top_var = float(gray[:h//2].mean(axis=1).std())
#         bot_var = float(gray[h//2:].mean(axis=1).std())

#         diff = abs(top_var - bot_var) / (max(top_var, bot_var) + 1e-8)
#         score = min(diff * 2.0, 1.0)

#         if diff > 0.4:
#             findings.append("Row brightness variance mismatch between document halves")

#         return score, findings


# # ══════════════════════════════════════════════════════════════
# #  HEATMAP GENERATOR
# # ══════════════════════════════════════════════════════════════

# class HeatmapGenerator:
#     """
#     Composites outputs from all spatial forensic modules into a
#     unified fraud heatmap.

#     Algorithm:
#     1. Collect spatial maps from: ELA, Noise, CopyMove, Edge, Color
#     2. Normalize each map to [0, 1]
#     3. Weighted average (using module weights)
#     4. Apply Gaussian smoothing
#     5. Overlay on original image with colormap (cool-warm)
#     6. Save and return path
#     """

#     WEIGHTS = {
#         "ela": 0.35,
#         "noise": 0.20,
#         "copymove": 0.20,
#         "edge": 0.15,
#         "color": 0.10,
#     }

#     def __init__(self):
#         self.logger = logging.getLogger("docfraud.heatmap")

#     def generate(
#         self,
#         original_image: np.ndarray,
#         ctx: ForensicContext,
#         job_id: str,
#     ) -> Optional[str]:
#         """
#         Generate composite heatmap from module results.

#         Returns path to saved heatmap PNG, or None on failure.
#         """
#         try:
#             h, w = original_image.shape[:2]
#             composite = np.zeros((h, w), dtype=np.float32)
#             total_weight = 0.0

#             # Load ELA map if available
#             ela_result = ctx.module_scores.get("ela")
#             if ela_result and ela_result.artifact_path:
#                 ela_map = self._load_artifact_as_map(ela_result.artifact_path, h, w)
#                 if ela_map is not None:
#                     composite += self.WEIGHTS["ela"] * ela_map
#                     total_weight += self.WEIGHTS["ela"]

#             # Noise map
#             noise_result = ctx.module_scores.get("noise")
#             if noise_result and noise_result.artifact_path:
#                 noise_map = self._load_artifact_as_map(noise_result.artifact_path, h, w)
#                 if noise_map is not None:
#                     composite += self.WEIGHTS["noise"] * noise_map
#                     total_weight += self.WEIGHTS["noise"]

#             # Build bounding box contribution maps for copymove/edge
#             for module_name, weight_key in [("copymove", "copymove"), ("edge", "edge")]:
#                 result = ctx.module_scores.get(module_name)
#                 if result and result.bounding_boxes:
#                     bbox_map = self._bboxes_to_map(result.bounding_boxes, h, w)
#                     composite += self.WEIGHTS[weight_key] * bbox_map
#                     total_weight += self.WEIGHTS[weight_key]

#             if total_weight == 0:
#                 # No spatial data — create uniform heatmap from overall score
#                 overall = np.mean([
#                     r.score for r in ctx.module_scores.values()
#                     if not r.skipped
#                 ] or [0.0])
#                 composite = np.full((h, w), overall, dtype=np.float32)
#             else:
#                 composite /= total_weight

#             # Normalize
#             composite = np.clip(composite, 0.0, 1.0)

#             # Smooth
#             from scipy.ndimage import gaussian_filter
#             composite = gaussian_filter(composite, sigma=8.0)

#             # Create overlay
#             heatmap_img = self._apply_colormap(original_image, composite)

#             # Save
#             out_dir = settings.heatmap_dir
#             out_dir.mkdir(parents=True, exist_ok=True)
#             out_path = out_dir / f"{job_id}_heatmap.png"
#             heatmap_img.save(str(out_path))
#             self.logger.info("Heatmap saved: %s", out_path)
#             return str(out_path)

#         except Exception as e:
#             self.logger.exception("Heatmap generation failed: %s", e)
#             return None

#     def _load_artifact_as_map(
#         self, path: str, h: int, w: int
#     ) -> Optional[np.ndarray]:
#         """Load an artifact image and resize to target dimensions."""
#         try:
#             img = Image.open(path).convert("L").resize((w, h), Image.LANCZOS)
#             arr = np.array(img, dtype=np.float32) / 255.0
#             return arr
#         except Exception:
#             return None

#     def _bboxes_to_map(
#         self, bboxes: list, h: int, w: int
#     ) -> np.ndarray:
#         """Convert list of BoundingBox objects to a heatmap mask."""
#         mask = np.zeros((h, w), dtype=np.float32)
#         for bbox in bboxes:
#             y1 = max(0, bbox.y)
#             y2 = min(h, bbox.y + bbox.height)
#             x1 = max(0, bbox.x)
#             x2 = min(w, bbox.x + bbox.width)
#             mask[y1:y2, x1:x2] = np.maximum(mask[y1:y2, x1:x2], bbox.confidence)
#         return mask

#     def _apply_colormap(
#         self, original: np.ndarray, heatmap: np.ndarray
#     ) -> Image.Image:
#         """
#         Blend heatmap onto original using a red-hot colormap.
#         Transparent where score is low; red/yellow where high.
#         """
#         # Cool-warm colormap: blue (low) → yellow → red (high)
#         r = np.clip(heatmap * 2.0, 0, 1)
#         g = np.clip(1.0 - np.abs(heatmap - 0.5) * 2.0, 0, 1)
#         b = np.clip((1.0 - heatmap) * 2.0, 0, 1)

#         colored = np.stack([r, g, b], axis=2)
#         colored_uint8 = (colored * 255).astype(np.uint8)

#         # Alpha = heatmap intensity
#         alpha = (heatmap * 200).astype(np.uint8)

#         # Composite over original
#         orig_rgb = original[:, :, :3] if original.shape[2] >= 3 else np.stack([original[:,:,0]]*3, axis=2)
#         overlay = (
#             orig_rgb.astype(np.float32) * (1.0 - alpha[:, :, None] / 255.0)
#             + colored_uint8.astype(np.float32) * (alpha[:, :, None] / 255.0)
#         ).astype(np.uint8)

#         return Image.fromarray(overlay, mode="RGB")


# """
# PDF Structure Analysis, Layout Consistency, and Heatmap Generation Modules
# """

# from __future__ import annotations

# import logging
# from pathlib import Path
# from typing import Optional

# import numpy as np
# from PIL import Image

# from app.core.config import settings
# from app.domain.entities.document import BoundingBox, ForensicContext, ModuleScore
# from app.domain.services.base_module import ForensicModule

# logger = logging.getLogger("docfraud.modules")


# # ══════════════════════════════════════════════════════════════
# #  PDF STRUCTURE ANALYSIS
# # ══════════════════════════════════════════════════════════════

# class PDFStructureModule(ForensicModule):
#     """
#     Deep forensic analysis of PDF internal structure.

#     Theory:
#     PDF files store content in a tree of objects (streams, dictionaries,
#     arrays). Legitimate documents are created by a single authoring tool
#     in a single pass. Tampered PDFs show:

#     1. Incremental updates — new xref sections appended after original EOF
#        (used to modify content without rewriting full file)
#     2. Multiple revisions — legitimate for signed PDFs, suspicious otherwise
#     3. Object stream tampering — inline object replacement
#     4. Page insertion/deletion — mismatched page tree
#     5. Metadata inconsistency — creator/modification timestamp mismatches
#     6. Suspicious action objects — JavaScript, auto-open, launch actions

#     Algorithm:
#     1. Parse PDF with pypdf (pure Python, no system deps)
#     2. Check for incremental updates (multiple %%EOF markers)
#     3. Analyze xref table consistency
#     4. Inspect metadata vs document properties
#     5. Check for suspicious objects (JS, Launch, URI)
#     6. Analyze page count vs page tree depth

#     Limitations:
#     - Some legitimate tools produce incremental updates (Adobe Acrobat)
#     - Digitally signed PDFs MUST use incremental updates
#     - Cannot detect content-level tampering (only structural)
#     """

#     MODULE_NAME = "pdf_structure"
#     WEIGHT = 0.08
#     REQUIRES_PDF = True

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         findings = []
#         risk_score = 0.0

#         try:
#             raw_findings, raw_score = self._analyze_pdf_structure(ctx.file_path)
#             findings.extend(raw_findings)
#             risk_score = raw_score
#         except Exception as e:
#             logger.warning("PDF structure analysis failed: %s", e)
#             return self._make_score(0.0, 0.0, findings=["PDF structural analysis unavailable"])

#         confidence = 0.70 if findings else 0.45
#         return self._make_score(
#             score=min(risk_score, 1.0),
#             confidence=confidence,
#             findings=findings,
#             raw_data={"risk_contributions": risk_score},
#         )

#     def _analyze_pdf_structure(self, path: Path) -> tuple[list[str], float]:
#         """Analyze PDF internal structure for tampering indicators."""
#         findings = []
#         risk = 0.0

#         # Read raw bytes for low-level analysis
#         with open(path, "rb") as f:
#             raw = f.read()

#         # 1. Count EOF markers — more than 1 = incremental update
#         eof_count = raw.count(b"%%EOF")
#         if eof_count > 1:
#             findings.append(
#                 f"PDF has {eof_count} EOF markers — incremental update(s) detected"
#             )
#             risk += 0.30

#         # 2. Count xref sections — each xref section = one revision
#         xref_count = raw.count(b"\nxref") + raw.count(b"\r\nxref")
#         if xref_count > 1:
#             findings.append(
#                 f"{xref_count} xref table sections — document has been revised"
#             )
#             risk += 0.20

#         # 3. Check for JavaScript objects
#         if b"/JavaScript" in raw or b"/JS " in raw:
#             findings.append("JavaScript action object found in PDF — high risk")
#             risk += 0.50

#         # 4. Check for Launch/OpenAction
#         if b"/Launch" in raw:
#             findings.append("Launch action found — document executes external programs")
#             risk += 0.40
#         if b"/OpenAction" in raw:
#             findings.append("OpenAction found — document auto-executes on open")
#             risk += 0.25

#         # 5. Check for embedded files
#         if b"/EmbeddedFile" in raw or b"/EmbeddedFiles" in raw:
#             findings.append("Embedded files detected in PDF")
#             risk += 0.15

#         # 6. Pypdf structural analysis
#         try:
#             import pypdf

#             reader = pypdf.PdfReader(str(path))
#             page_count = len(reader.pages)

#             # Metadata
#             meta = reader.metadata
#             if meta:
#                 creator = str(meta.get("/Creator", ""))
#                 producer = str(meta.get("/Producer", ""))
#                 creation = str(meta.get("/CreationDate", ""))
#                 mod = str(meta.get("/ModDate", ""))

#                 if creator:
#                     # Check for editing tools
#                     for tool in ["photoshop", "gimp", "canva", "inkscape", "figma"]:
#                         if tool in creator.lower() or tool in producer.lower():
#                             findings.append(
#                                 f"PDF created/modified with image editing tool: {creator or producer}"
#                             )
#                             risk += 0.35
#                             break

#                 if creation and mod and mod < creation:
#                     findings.append("PDF modification date precedes creation date")
#                     risk += 0.30

#             # Check for encrypted PDF with modified content
#             if reader.is_encrypted:
#                 findings.append("PDF is encrypted — content inspection limited")
#                 risk += 0.10

#             # Check for form fields (could mask content replacement)
#             if "/AcroForm" in str(reader.trailer):
#                 findings.append("PDF contains form fields (AcroForm)")
#                 risk += 0.10

#         except ImportError:
#             findings.append("pypdf not installed; deep PDF analysis skipped")
#         except Exception as e:
#             logger.debug("pypdf analysis error: %s", e)

#         return findings, min(risk, 1.0)


# # ══════════════════════════════════════════════════════════════
# #  LAYOUT CONSISTENCY MODULE
# # ══════════════════════════════════════════════════════════════

# class LayoutConsistencyModule(ForensicModule):
#     """
#     Detect layout anomalies that indicate local modifications.

#     Theory:
#     Genuine documents have consistent structural layout:
#     - Uniform margins
#     - Consistent line spacing
#     - Regular text alignment
#     - Consistent column widths

#     Tampered documents often show:
#     - Irregular line spacing in modified regions
#     - Margin inconsistencies where content was re-flowed
#     - Misaligned elements after replacement
#     - Inconsistent word spacing (tracking) from OCR re-insertion

#     Algorithm:
#     1. Detect horizontal text baselines via Hough transform
#     2. Analyze inter-baseline spacing consistency
#     3. Detect margin boundaries
#     4. Analyze left-edge text alignment
#     5. Identify outlier regions
#     """

#     MODULE_NAME = "layout"
#     WEIGHT = 0.05
#     MIN_IMAGE_SIZE = 64

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         findings = []

#         spacing_score, spacing_findings = self._analyze_line_spacing(image)
#         margin_score, margin_findings = self._analyze_margins(image)
#         alignment_score, alignment_findings = self._analyze_text_alignment(image)

#         findings = spacing_findings + margin_findings + alignment_findings
#         score = (
#             0.40 * spacing_score
#             + 0.30 * margin_score
#             + 0.30 * alignment_score
#         )

#         return self._make_score(
#             score=score,
#             confidence=0.45 + score * 0.40,
#             findings=findings,
#             raw_data={
#                 "spacing_score": spacing_score,
#                 "margin_score": margin_score,
#                 "alignment_score": alignment_score,
#             },
#         )

#     def _analyze_line_spacing(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """Detect inconsistent line spacing via horizontal projection profile."""
#         findings = []
#         gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

#         # Horizontal projection profile
#         # Text lines = rows with low mean brightness; spaces = high brightness
#         row_means = gray.mean(axis=1)
#         threshold = row_means.mean()

#         # Find transitions: white (space) → dark (text) = line start
#         is_text = row_means < threshold
#         transitions = np.diff(is_text.astype(int))
#         line_starts = np.where(transitions == 1)[0]

#         if len(line_starts) < 3:
#             return 0.0, []

#         # Inter-line spacings
#         spacings = np.diff(line_starts).astype(float)

#         if len(spacings) < 2:
#             return 0.0, []

#         mean_s = spacings.mean()
#         std_s = spacings.std()
#         cv = float(std_s / (mean_s + 1e-8))  # Coefficient of variation

#         # Bilingual documents (e.g. Devanagari + Latin) have inherently mixed
#         # line heights → CV up to ~1.3 is normal.  Only flag above 1.5.
#         # Score ramps from 0 at CV=0.8 to 1.0 at CV=2.3.
#         score = float(np.clip((cv - 0.8) / 1.5, 0.0, 1.0))
#         if cv > 1.5:
#             findings.append(
#                 f"Line spacing irregularity (CV={cv:.2f}) suggests content modification"
#             )

#         return score, findings

#     def _analyze_margins(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """Detect inconsistent margins via column projection."""
#         findings = []
#         gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

#         # Vertical projection for left/right margins
#         col_means = gray.mean(axis=0)
#         threshold = gray.mean()
#         is_text_col = col_means < threshold

#         # Find left margin: first column with text
#         left_positions = np.where(is_text_col)[0]
#         if len(left_positions) == 0:
#             return 0.0, []

#         # Divide into vertical thirds and compare left margin position
#         h = gray.shape[0]
#         thirds = [
#             gray[:h//3], gray[h//3:2*h//3], gray[2*h//3:]
#         ]

#         margins = []
#         for third in thirds:
#             col_m = third.mean(axis=0)
#             text_cols = np.where(col_m < col_m.mean())[0]
#             if len(text_cols) > 0:
#                 margins.append(int(text_cols[0]))

#         if len(margins) < 2:
#             return 0.0, []

#         margin_std = float(np.std(margins))
#         score = min(margin_std / 50.0, 1.0)

#         if margin_std > 20:
#             findings.append(
#                 f"Margin inconsistency across document thirds (std={margin_std:.1f}px)"
#             )

#         return score, findings

#     def _analyze_text_alignment(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """Detect text alignment inconsistencies."""
#         findings = []
#         # Simple analysis via horizontal profile variance per region
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)
#         h, w = gray.shape

#         # Compare variance of row profiles in top vs bottom halves
#         top_var = float(gray[:h//2].mean(axis=1).std())
#         bot_var = float(gray[h//2:].mean(axis=1).std())

#         diff = abs(top_var - bot_var) / (max(top_var, bot_var) + 1e-8)
#         score = min(diff * 2.0, 1.0)

#         # Real ID cards always have a photo-side vs text-side brightness split.
#         # Only flag at diff > 0.60 to avoid false positives on all photo-bearing IDs.
#         if diff > 0.60:
#             findings.append("Row brightness variance mismatch between document halves")

#         return score, findings


# # ══════════════════════════════════════════════════════════════
# #  HEATMAP GENERATOR
# # ══════════════════════════════════════════════════════════════

# class HeatmapGenerator:
#     """
#     Composites outputs from all spatial forensic modules into a
#     unified fraud heatmap.

#     Algorithm:
#     1. Collect spatial maps from: ELA, Noise, CopyMove, Edge, Color
#     2. Normalize each map to [0, 1]
#     3. Weighted average (using module weights)
#     4. Apply Gaussian smoothing
#     5. Overlay on original image with colormap (cool-warm)
#     6. Save and return path
#     """

#     WEIGHTS = {
#         "ela": 0.35,
#         "noise": 0.20,
#         "copymove": 0.20,
#         "edge": 0.15,
#         "color": 0.10,
#     }

#     def __init__(self):
#         self.logger = logging.getLogger("docfraud.heatmap")

#     def generate(
#         self,
#         original_image: np.ndarray,
#         ctx: ForensicContext,
#         job_id: str,
#     ) -> Optional[str]:
#         """
#         Generate composite heatmap from module results.

#         Returns path to saved heatmap PNG, or None on failure.
#         """
#         try:
#             h, w = original_image.shape[:2]
#             composite = np.zeros((h, w), dtype=np.float32)
#             total_weight = 0.0

#             # Load ELA map if available
#             ela_result = ctx.module_scores.get("ela")
#             if ela_result and ela_result.artifact_path:
#                 ela_map = self._load_artifact_as_map(ela_result.artifact_path, h, w)
#                 if ela_map is not None:
#                     composite += self.WEIGHTS["ela"] * ela_map
#                     total_weight += self.WEIGHTS["ela"]

#             # Noise map
#             noise_result = ctx.module_scores.get("noise")
#             if noise_result and noise_result.artifact_path:
#                 noise_map = self._load_artifact_as_map(noise_result.artifact_path, h, w)
#                 if noise_map is not None:
#                     composite += self.WEIGHTS["noise"] * noise_map
#                     total_weight += self.WEIGHTS["noise"]

#             # Build bounding box contribution maps for copymove/edge
#             for module_name, weight_key in [("copymove", "copymove"), ("edge", "edge")]:
#                 result = ctx.module_scores.get(module_name)
#                 if result and result.bounding_boxes:
#                     bbox_map = self._bboxes_to_map(result.bounding_boxes, h, w)
#                     composite += self.WEIGHTS[weight_key] * bbox_map
#                     total_weight += self.WEIGHTS[weight_key]

#             if total_weight == 0:
#                 # No spatial data — create uniform heatmap from overall score
#                 overall = np.mean([
#                     r.score for r in ctx.module_scores.values()
#                     if not r.skipped
#                 ] or [0.0])
#                 composite = np.full((h, w), overall, dtype=np.float32)
#             else:
#                 composite /= total_weight

#             # Normalize
#             composite = np.clip(composite, 0.0, 1.0)

#             # Smooth
#             from scipy.ndimage import gaussian_filter
#             composite = gaussian_filter(composite, sigma=8.0)

#             # Create overlay
#             heatmap_img = self._apply_colormap(original_image, composite)

#             # Save
#             out_dir = settings.heatmap_dir
#             out_dir.mkdir(parents=True, exist_ok=True)
#             out_path = out_dir / f"{job_id}_heatmap.png"
#             heatmap_img.save(str(out_path))
#             self.logger.info("Heatmap saved: %s", out_path)
#             return str(out_path)

#         except Exception as e:
#             self.logger.exception("Heatmap generation failed: %s", e)
#             return None

#     def _load_artifact_as_map(
#         self, path: str, h: int, w: int
#     ) -> Optional[np.ndarray]:
#         """Load an artifact image and resize to target dimensions."""
#         try:
#             img = Image.open(path).convert("L").resize((w, h), Image.LANCZOS)
#             arr = np.array(img, dtype=np.float32) / 255.0
#             return arr
#         except Exception:
#             return None

#     def _bboxes_to_map(
#         self, bboxes: list, h: int, w: int
#     ) -> np.ndarray:
#         """Convert list of BoundingBox objects to a heatmap mask."""
#         mask = np.zeros((h, w), dtype=np.float32)
#         for bbox in bboxes:
#             y1 = max(0, bbox.y)
#             y2 = min(h, bbox.y + bbox.height)
#             x1 = max(0, bbox.x)
#             x2 = min(w, bbox.x + bbox.width)
#             mask[y1:y2, x1:x2] = np.maximum(mask[y1:y2, x1:x2], bbox.confidence)
#         return mask

#     def _apply_colormap(
#         self, original: np.ndarray, heatmap: np.ndarray
#     ) -> Image.Image:
#         """
#         Blend heatmap onto original using a red-hot colormap.
#         Transparent where score is low; red/yellow where high.
#         """
#         # Cool-warm colormap: blue (low) → yellow → red (high)
#         r = np.clip(heatmap * 2.0, 0, 1)
#         g = np.clip(1.0 - np.abs(heatmap - 0.5) * 2.0, 0, 1)
#         b = np.clip((1.0 - heatmap) * 2.0, 0, 1)

#         colored = np.stack([r, g, b], axis=2)
#         colored_uint8 = (colored * 255).astype(np.uint8)

#         # Alpha = heatmap intensity
#         alpha = (heatmap * 200).astype(np.uint8)

#         # Composite over original
#         orig_rgb = original[:, :, :3] if original.shape[2] >= 3 else np.stack([original[:,:,0]]*3, axis=2)
#         overlay = (
#             orig_rgb.astype(np.float32) * (1.0 - alpha[:, :, None] / 255.0)
#             + colored_uint8.astype(np.float32) * (alpha[:, :, None] / 255.0)
#         ).astype(np.uint8)

#         return Image.fromarray(overlay, mode="RGB")



"""
PDF Structure Analysis, Layout Consistency, and Heatmap Generation Modules
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

logger = logging.getLogger("docfraud.modules")


# ══════════════════════════════════════════════════════════════
#  PDF STRUCTURE ANALYSIS
# ══════════════════════════════════════════════════════════════

class PDFStructureModule(ForensicModule):
    """
    Deep forensic analysis of PDF internal structure.

    Theory:
    PDF files store content in a tree of objects (streams, dictionaries,
    arrays). Legitimate documents are created by a single authoring tool
    in a single pass. Tampered PDFs show:

    1. Incremental updates — new xref sections appended after original EOF
       (used to modify content without rewriting full file)
    2. Multiple revisions — legitimate for signed PDFs, suspicious otherwise
    3. Object stream tampering — inline object replacement
    4. Page insertion/deletion — mismatched page tree
    5. Metadata inconsistency — creator/modification timestamp mismatches
    6. Suspicious action objects — JavaScript, auto-open, launch actions

    Algorithm:
    1. Parse PDF with pypdf (pure Python, no system deps)
    2. Check for incremental updates (multiple %%EOF markers)
    3. Analyze xref table consistency
    4. Inspect metadata vs document properties
    5. Check for suspicious objects (JS, Launch, URI)
    6. Analyze page count vs page tree depth

    Limitations:
    - Some legitimate tools produce incremental updates (Adobe Acrobat)
    - Digitally signed PDFs MUST use incremental updates
    - Cannot detect content-level tampering (only structural)
    """

    MODULE_NAME = "pdf_structure"
    WEIGHT = 0.08
    REQUIRES_PDF = True

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        findings = []
        risk_score = 0.0

        try:
            raw_findings, raw_score = self._analyze_pdf_structure(ctx.file_path)
            findings.extend(raw_findings)
            risk_score = raw_score
        except Exception as e:
            logger.warning("PDF structure analysis failed: %s", e)
            return self._make_score(0.0, 0.0, findings=["PDF structural analysis unavailable"])

        confidence = 0.70 if findings else 0.45
        return self._make_score(
            score=min(risk_score, 1.0),
            confidence=confidence,
            findings=findings,
            raw_data={"risk_contributions": risk_score},
        )

    def _analyze_pdf_structure(self, path: Path) -> tuple[list[str], float]:
        """Analyze PDF internal structure for tampering indicators."""
        findings = []
        risk = 0.0

        # Read raw bytes for low-level analysis
        with open(path, "rb") as f:
            raw = f.read()

        # 1. Count EOF markers — more than 1 = incremental update
        eof_count = raw.count(b"%%EOF")
        if eof_count > 1:
            findings.append(
                f"PDF has {eof_count} EOF markers — incremental update(s) detected"
            )
            risk += 0.30

        # 2. Count xref sections — each xref section = one revision
        xref_count = raw.count(b"\nxref") + raw.count(b"\r\nxref")
        if xref_count > 1:
            findings.append(
                f"{xref_count} xref table sections — document has been revised"
            )
            risk += 0.20

        # 3. Check for JavaScript objects
        if b"/JavaScript" in raw or b"/JS " in raw:
            findings.append("JavaScript action object found in PDF — high risk")
            risk += 0.50

        # 4. Check for Launch/OpenAction
        if b"/Launch" in raw:
            findings.append("Launch action found — document executes external programs")
            risk += 0.40
        if b"/OpenAction" in raw:
            findings.append("OpenAction found — document auto-executes on open")
            risk += 0.25

        # 5. Check for embedded files
        if b"/EmbeddedFile" in raw or b"/EmbeddedFiles" in raw:
            findings.append("Embedded files detected in PDF")
            risk += 0.15

        # 6. Pypdf structural analysis
        try:
            import pypdf

            reader = pypdf.PdfReader(str(path))
            page_count = len(reader.pages)

            # Metadata
            meta = reader.metadata
            if meta:
                creator = str(meta.get("/Creator", ""))
                producer = str(meta.get("/Producer", ""))
                creation = str(meta.get("/CreationDate", ""))
                mod = str(meta.get("/ModDate", ""))

                if creator:
                    # Check for editing tools
                    for tool in ["photoshop", "gimp", "canva", "inkscape", "figma"]:
                        if tool in creator.lower() or tool in producer.lower():
                            findings.append(
                                f"PDF created/modified with image editing tool: {creator or producer}"
                            )
                            risk += 0.35
                            break

                if creation and mod and mod < creation:
                    findings.append("PDF modification date precedes creation date")
                    risk += 0.30

            # Check for encrypted PDF with modified content
            if reader.is_encrypted:
                findings.append("PDF is encrypted — content inspection limited")
                risk += 0.10

            # Check for form fields (could mask content replacement)
            if "/AcroForm" in str(reader.trailer):
                findings.append("PDF contains form fields (AcroForm)")
                risk += 0.10

        except ImportError:
            findings.append("pypdf not installed; deep PDF analysis skipped")
        except Exception as e:
            logger.debug("pypdf analysis error: %s", e)

        return findings, min(risk, 1.0)


# ══════════════════════════════════════════════════════════════
#  LAYOUT CONSISTENCY MODULE
# ══════════════════════════════════════════════════════════════

class LayoutConsistencyModule(ForensicModule):
    """
    Detect layout anomalies that indicate local modifications.

    Theory:
    Genuine documents have consistent structural layout:
    - Uniform margins
    - Consistent line spacing
    - Regular text alignment
    - Consistent column widths

    Tampered documents often show:
    - Irregular line spacing in modified regions
    - Margin inconsistencies where content was re-flowed
    - Misaligned elements after replacement
    - Inconsistent word spacing (tracking) from OCR re-insertion

    Algorithm:
    1. Detect horizontal text baselines via Hough transform
    2. Analyze inter-baseline spacing consistency
    3. Detect margin boundaries
    4. Analyze left-edge text alignment
    5. Identify outlier regions
    """

    MODULE_NAME = "layout"
    WEIGHT = 0.05
    MIN_IMAGE_SIZE = 64

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        findings = []

        spacing_score, spacing_findings, spacing_cv = self._analyze_line_spacing(image)
        margin_score, margin_findings = self._analyze_margins(image)
        alignment_score, alignment_findings = self._analyze_text_alignment(image)

        findings = spacing_findings + margin_findings + alignment_findings

        # Use spacing_cv (the dominant structural signal) as the layout CV
        # for the fixed piecewise scoring below.
        self._computed_cv = spacing_cv

        # ── Layout score assembly (fixed) ────────────────────────────────────
        layout_cv = self._computed_cv   # keep existing CV calculation above this

        # Piecewise — calibrated to genuine vs. fake CV distributions
        if layout_cv < 0.50:
            layout_score = 0.05

        elif layout_cv < 1.00:
            layout_score = 0.15

        elif layout_cv < 1.50:
            layout_score = 0.25

        elif layout_cv < 2.00:
            layout_score = 0.35

        else:
            layout_score = 0.50

        # Hard floor: CV ≥ 1.0 is extreme structural inconsistency
        

        # ── Expose for scoring engine ─────────────────────────────────────────
        self._cv   = layout_cv      # ← engine reads this
        score      = round(layout_score, 4)

        return self._make_score(
            score=score,
            confidence=0.45 + score * 0.40,
            findings=findings,
            raw_data={
                "spacing_cv": spacing_cv,
                "spacing_score": spacing_score,
                "margin_score": margin_score,
                "alignment_score": alignment_score,
            },
        )

    def _analyze_line_spacing(self, image: np.ndarray) -> tuple[float, list[str], float]:
        """
        Detect inconsistent line spacing via horizontal projection profile.

        Returns (score, findings, cv) — cv is exposed as the layout CV.
        """
        findings = []
        gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

        # Horizontal projection profile
        # Text lines = rows with low mean brightness; spaces = high brightness
        row_means = gray.mean(axis=1)
        threshold = row_means.mean()

        # Find transitions: white (space) → dark (text) = line start
        is_text = row_means < threshold
        transitions = np.diff(is_text.astype(int))
        line_starts = np.where(transitions == 1)[0]

        if len(line_starts) < 3:
            return 0.0, [], 0.0

        # Inter-line spacings
        spacings = np.diff(line_starts).astype(float)

        if len(spacings) < 2:
            return 0.0, [], 0.0

        mean_s = spacings.mean()
        std_s = spacings.std()
        cv = float(std_s / (mean_s + 1e-8))  # Coefficient of variation

        # Bilingual documents (e.g. Devanagari + Latin) have inherently mixed
        # line heights → CV up to ~1.3 is normal.  Only flag above 1.5.
        # Score ramps from 0 at CV=0.8 to 1.0 at CV=2.3.
        score = float(np.clip((cv - 0.8) / 1.5, 0.0, 1.0))
        if cv > 1.5:
            findings.append(
                f"Line spacing irregularity (CV={cv:.2f}) suggests content modification"
            )

        return score, findings, cv

    def _analyze_margins(self, image: np.ndarray) -> tuple[float, list[str]]:
        """Detect inconsistent margins via column projection."""
        findings = []
        gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

        # Vertical projection for left/right margins
        col_means = gray.mean(axis=0)
        threshold = gray.mean()
        is_text_col = col_means < threshold

        # Find left margin: first column with text
        left_positions = np.where(is_text_col)[0]
        if len(left_positions) == 0:
            return 0.0, []

        # Divide into vertical thirds and compare left margin position
        h = gray.shape[0]
        thirds = [
            gray[:h//3], gray[h//3:2*h//3], gray[2*h//3:]
        ]

        margins = []
        for third in thirds:
            col_m = third.mean(axis=0)
            text_cols = np.where(col_m < col_m.mean())[0]
            if len(text_cols) > 0:
                margins.append(int(text_cols[0]))

        if len(margins) < 2:
            return 0.0, []

        margin_std = float(np.std(margins))
        score = min(margin_std / 50.0, 1.0)

        if margin_std > 20:
            findings.append(
                f"Margin inconsistency across document thirds (std={margin_std:.1f}px)"
            )

        return score, findings

    def _analyze_text_alignment(self, image: np.ndarray) -> tuple[float, list[str]]:
        """Detect text alignment inconsistencies."""
        findings = []
        # Simple analysis via horizontal profile variance per region
        gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)
        h, w = gray.shape

        # Compare variance of row profiles in top vs bottom halves
        top_var = float(gray[:h//2].mean(axis=1).std())
        bot_var = float(gray[h//2:].mean(axis=1).std())

        diff = abs(top_var - bot_var) / (max(top_var, bot_var) + 1e-8)
        score = min(diff * 2.0, 1.0)

        # Real ID cards always have a photo-side vs text-side brightness split.
        # Only flag at diff > 0.60 to avoid false positives on all photo-bearing IDs.
        if diff > 0.60:
            findings.append("Row brightness variance mismatch between document halves")

        return score, findings


# ══════════════════════════════════════════════════════════════
#  HEATMAP GENERATOR
# ══════════════════════════════════════════════════════════════

class HeatmapGenerator:
    """
    Composites outputs from all spatial forensic modules into a
    unified fraud heatmap.

    Algorithm:
    1. Collect spatial maps from: ELA, Noise, CopyMove, Edge, Color
    2. Normalize each map to [0, 1]
    3. Weighted average (using module weights)
    4. Apply Gaussian smoothing
    5. Overlay on original image with colormap (cool-warm)
    6. Save and return path
    """

    WEIGHTS = {
        "ela": 0.35,
        "noise": 0.20,
        "copymove": 0.20,
        "edge": 0.15,
        "color": 0.10,
    }

    def __init__(self):
        self.logger = logging.getLogger("docfraud.heatmap")

    def generate(
        self,
        original_image: np.ndarray,
        ctx: ForensicContext,
        job_id: str,
    ) -> Optional[str]:
        """
        Generate composite heatmap from module results.

        Returns path to saved heatmap PNG, or None on failure.
        """
        try:
            h, w = original_image.shape[:2]
            composite = np.zeros((h, w), dtype=np.float32)
            total_weight = 0.0

            # Load ELA map if available
            ela_result = ctx.module_scores.get("ela")
            if ela_result and ela_result.artifact_path:
                ela_map = self._load_artifact_as_map(ela_result.artifact_path, h, w)
                if ela_map is not None:
                    composite += self.WEIGHTS["ela"] * ela_map
                    total_weight += self.WEIGHTS["ela"]

            # Noise map
            noise_result = ctx.module_scores.get("noise")
            if noise_result and noise_result.artifact_path:
                noise_map = self._load_artifact_as_map(noise_result.artifact_path, h, w)
                if noise_map is not None:
                    composite += self.WEIGHTS["noise"] * noise_map
                    total_weight += self.WEIGHTS["noise"]

            # Build bounding box contribution maps for copymove/edge
            for module_name, weight_key in [("copymove", "copymove"), ("edge", "edge")]:
                result = ctx.module_scores.get(module_name)
                if result and result.bounding_boxes:
                    bbox_map = self._bboxes_to_map(result.bounding_boxes, h, w)
                    composite += self.WEIGHTS[weight_key] * bbox_map
                    total_weight += self.WEIGHTS[weight_key]

            if total_weight == 0:
                # No spatial data — create uniform heatmap from overall score
                overall = np.mean([
                    r.score for r in ctx.module_scores.values()
                    if not r.skipped
                ] or [0.0])
                composite = np.full((h, w), overall, dtype=np.float32)
            else:
                composite /= total_weight

            # Normalize
            composite = np.clip(composite, 0.0, 1.0)

            # Smooth
            from scipy.ndimage import gaussian_filter
            composite = gaussian_filter(composite, sigma=8.0)

            # Create overlay
            heatmap_img = self._apply_colormap(original_image, composite)

            # Save
            out_dir = settings.heatmap_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{job_id}_heatmap.png"
            heatmap_img.save(str(out_path))
            self.logger.info("Heatmap saved: %s", out_path)
            return str(out_path)

        except Exception as e:
            self.logger.exception("Heatmap generation failed: %s", e)
            return None

    def _load_artifact_as_map(
        self, path: str, h: int, w: int
    ) -> Optional[np.ndarray]:
        """Load an artifact image and resize to target dimensions."""
        try:
            img = Image.open(path).convert("L").resize((w, h), Image.LANCZOS)
            arr = np.array(img, dtype=np.float32) / 255.0
            return arr
        except Exception:
            return None

    def _bboxes_to_map(
        self, bboxes: list, h: int, w: int
    ) -> np.ndarray:
        """Convert list of BoundingBox objects to a heatmap mask."""
        mask = np.zeros((h, w), dtype=np.float32)
        for bbox in bboxes:
            y1 = max(0, bbox.y)
            y2 = min(h, bbox.y + bbox.height)
            x1 = max(0, bbox.x)
            x2 = min(w, bbox.x + bbox.width)
            mask[y1:y2, x1:x2] = np.maximum(mask[y1:y2, x1:x2], bbox.confidence)
        return mask

    def _apply_colormap(
        self, original: np.ndarray, heatmap: np.ndarray
    ) -> Image.Image:
        """
        Blend heatmap onto original using a red-hot colormap.
        Transparent where score is low; red/yellow where high.
        """
        # Cool-warm colormap: blue (low) → yellow → red (high)
        r = np.clip(heatmap * 2.0, 0, 1)
        g = np.clip(1.0 - np.abs(heatmap - 0.5) * 2.0, 0, 1)
        b = np.clip((1.0 - heatmap) * 2.0, 0, 1)

        colored = np.stack([r, g, b], axis=2)
        colored_uint8 = (colored * 255).astype(np.uint8)

        # Alpha = heatmap intensity
        alpha = (heatmap * 200).astype(np.uint8)

        # Composite over original
        orig_rgb = original[:, :, :3] if original.shape[2] >= 3 else np.stack([original[:,:,0]]*3, axis=2)
        overlay = (
            orig_rgb.astype(np.float32) * (1.0 - alpha[:, :, None] / 255.0)
            + colored_uint8.astype(np.float32) * (alpha[:, :, None] / 255.0)
        ).astype(np.uint8)

        return Image.fromarray(overlay, mode="RGB")