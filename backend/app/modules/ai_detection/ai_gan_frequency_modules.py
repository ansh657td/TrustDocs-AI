# """
# AI Artifact Detection, GAN Detection, and Frequency Analysis Modules

# ═══════════════════════════════════════════════════════════════
# FORENSIC THEORY — AI DETECTION
# ═══════════════════════════════════════════════════════════════
# Generative models (Stable Diffusion, Flux, DALL-E, Midjourney) produce
# images that differ from camera-captured images in key ways:

# 1. FREQUENCY DOMAIN: AI images show characteristic spectral artifacts.
#    GANs produce a "grid pattern" in the FFT (GAN fingerprint).
#    Diffusion models create smoother but unnaturally clean noise floors.

# 2. NOISE PATTERNS: AI images lack natural sensor noise. Their noise
#    follows i.i.d. distributions rather than spatially correlated PRNU.

# 3. TEXTURE STATISTICS: Deep neural networks produce characteristic
#    texture distributions. Co-occurrence statistics (GLCM) differ.

# 4. SEMANTIC INCONSISTENCIES: Fingers, teeth, text, reflections — areas
#    where current models still fail.

# 5. GRADIENT STATISTICS: Natural images follow specific heavy-tailed
#    gradient distributions. AI images have lighter tails.

# ═══════════════════════════════════════════════════════════════
# FORENSIC THEORY — FREQUENCY ANALYSIS
# ═══════════════════════════════════════════════════════════════
# DCT (Discrete Cosine Transform) and FFT analysis expose:
# - Double JPEG compression grid artifacts (8×8 block traces)
# - AI generation grid artifacts
# - Splicing boundaries in frequency domain
# - Periodic tamper patterns invisible in spatial domain
# """

# from __future__ import annotations

# import logging
# from typing import Optional
# from pathlib import Path

# import numpy as np
# from PIL import Image

# from app.core.config import settings
# from app.domain.entities.document import ForensicContext, ModuleScore
# from app.domain.services.base_module import ForensicModule

# logger = logging.getLogger("docfraud.module.ai")


# # ══════════════════════════════════════════════════════════════
# #  AI ARTIFACT DETECTION
# # ══════════════════════════════════════════════════════════════

# class AIArtifactDetectionModule(ForensicModule):
#     """
#     Detect AI-generated image artifacts using texture, gradient, and spectral analysis.

#     Note: This module uses statistical/handcrafted features only.
#     For maximum accuracy, a trained CNN classifier (e.g. CNNDetection, GragnanielloGAN)
#     should be integrated via torch inference. The statistical approach here
#     achieves ~70-80% accuracy vs 90%+ for trained models.

#     Integration point: Replace _cnn_score() with a loaded PyTorch model.
#     """

#     MODULE_NAME = "ai_detection"
#     WEIGHT = 0.15
#     MIN_IMAGE_SIZE = 64
#     THRESHOLD = 0.50

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         findings = []

#         # 1. Gradient statistics
#         grad_score, grad_findings = self._gradient_statistics(image)
#         findings.extend(grad_findings)

#         # 2. Texture analysis (GLCM)
#         texture_score, texture_findings = self._texture_analysis(image)
#         findings.extend(texture_findings)

#         # 3. Noise pattern analysis
#         noise_score, noise_findings = self._noise_pattern_analysis(image)
#         findings.extend(noise_findings)

#         # 4. CNN score (placeholder — returns 0 without a model file)
#         cnn_score = self._cnn_score(image)

#         # Weighted combination
#         # 4. CNN score (-1.0 = no model available, omit from combination)
#         cnn_score = self._cnn_score(image)

#         # Weighted combination
#         if cnn_score >= 0.0:
#             score = (
#                 0.15 * grad_score
#                 + 0.15 * texture_score
#                 + 0.20 * noise_score
#                 + 0.50 * cnn_score
#             )
#         else:
#             # No CNN model — redistribute weights across statistical features
#             score = (
#                 0.35 * grad_score
#                 + 0.35 * texture_score
#                 + 0.30 * noise_score
#             )

#         ai_generated = score > self.THRESHOLD
#         if ai_generated:
#             findings.append(
#                 f"AI-generation probability: {score*100:.1f}% — likely AI-generated or AI-assisted"
#             )

#         confidence = 0.55 + abs(score - 0.5) * 0.8

#         return self._make_score(
#             score=score,
#             confidence=min(confidence, 0.90),
#             findings=findings,
#             raw_data={
#                 "gradient_score": grad_score,
#                 "texture_score": texture_score,
#                 "noise_score": noise_score,
#                 "cnn_score": cnn_score if cnn_score >= 0.0 else None,
#                 "cnn_model_available": cnn_score >= 0.0,
#             },
#         )

#     def _gradient_statistics(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Analyze gradient magnitude distribution.

#         AI images have lighter-tailed gradient distributions than natural images.
#         We measure kurtosis and tail weight of gradient histogram.
#         """
#         findings = []
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

#         # Compute gradients
#         gy, gx = np.gradient(gray)
#         mag = np.sqrt(gx**2 + gy**2).ravel()

#         if len(mag) == 0:
#             return 0.0, []

#         # Normalized gradient magnitude
#         mag_norm = mag / (mag.max() + 1e-8)

#         # Kurtosis — natural images: high (heavy tail); AI: lower (lighter tail)
#         mean_m = mag_norm.mean()
#         std_m = mag_norm.std() + 1e-8
#         kurtosis = float(np.mean(((mag_norm - mean_m) / std_m) ** 4))

#         # Natural image kurtosis typically 10-50; AI images 3-10
#         if kurtosis < 5.0:
#             score = 0.7 - kurtosis / 15.0  # Low kurtosis → AI signal
#             findings.append(f"Low gradient kurtosis ({kurtosis:.2f}) — AI generation signature")
#         elif kurtosis > 60.0:
#             score = 0.15
#         else:
#             score = max(0.0, (8.0 - kurtosis) / 8.0) * 0.5

#         return max(0.0, min(score, 1.0)), findings

#     def _texture_analysis(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Analyze texture via Local Binary Patterns and GLCM statistics.
#         AI images show unnaturally regular or smooth texture patterns.
#         """
#         findings = []
#         try:
#             from skimage.feature import graycomatrix, graycoprops

#             gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

#             # Downsample for speed
#             if gray.shape[0] > 512:
#                 from skimage.transform import resize
#                 gray = (resize(gray, (512, 512)) * 255).astype(np.uint8)

#             # GLCM at multiple distances and angles
#             glcm = graycomatrix(
#                 gray, distances=[1, 3], angles=[0, np.pi/4, np.pi/2],
#                 levels=64, symmetric=True, normed=True
#             )

#             contrast = float(graycoprops(glcm, 'contrast').mean())
#             energy = float(graycoprops(glcm, 'energy').mean())
#             homogeneity = float(graycoprops(glcm, 'homogeneity').mean())

#             # AI images tend toward: high energy, high homogeneity, low contrast
#             # These thresholds are empirically derived
#             ai_signal = (
#                 0.35 * min(energy / 0.05, 1.0)         # unnaturally high energy
#                 + 0.35 * min(homogeneity / 0.9, 1.0)   # unnaturally smooth
#                 + 0.30 * max(0, (0.3 - contrast) / 0.3) # very low contrast
#             )

#             if energy > 0.04:
#                 findings.append(f"Unnaturally high texture energy ({energy:.4f}) — AI texture signature")
#             if homogeneity > 0.85:
#                 findings.append(f"Excessive texture homogeneity ({homogeneity:.3f})")

#             return float(min(ai_signal, 1.0)), findings

#         except ImportError:
#             return 0.0, []
#         except Exception as e:
#             logger.debug("Texture analysis failed: %s", e)
#             return 0.0, []

#     def _noise_pattern_analysis(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Check if noise follows i.i.d. distribution (AI) vs spatially
#         correlated sensor noise (camera).
#         """
#         findings = []
#         try:
#             from skimage.restoration import denoise_wavelet, estimate_sigma

#             gray = np.mean(image, axis=2).astype(np.float64) / 255.0 if len(image.shape) == 3 else image.astype(np.float64) / 255.0

#             sigma = estimate_sigma(gray, average_sigmas=True)

#             if sigma < 0.002:
#                 findings.append(f"Near-zero noise level (σ={sigma:.5f}) — consistent with AI synthesis")
#                 return 0.75, findings

#             denoised = denoise_wavelet(gray, sigma=sigma, wavelet_levels=4)
#             residual = gray - denoised

#             # Test for spatial correlation: if i.i.d., autocorrelation ≈ delta
#             h, w = residual.shape
#             center_h, center_w = h // 2, w // 2
#             sample = residual[
#                 max(0, center_h-64):center_h+64,
#                 max(0, center_w-64):center_w+64
#             ]

#             if sample.size < 100:
#                 return 0.0, []

#             # Autocorrelation at lag-1
#             flat = sample.ravel()
#             ac = float(np.corrcoef(flat[:-1], flat[1:])[0, 1])

#             # Camera noise: |ac| ~ 0.0-0.1; AI: |ac| can be very small too
#             # But AI often shows periodic noise in autocorrelation
#             # We check variance of autocorrelation across directions

#             hor_ac = float(np.corrcoef(sample[0, :-1], sample[0, 1:])[0, 1]) if sample.shape[1] > 1 else 0.0
#             vert_ac = float(np.corrcoef(sample[:-1, 0], sample[1:, 0])[0, 1]) if sample.shape[0] > 1 else 0.0

#             # i.i.d. noise: both small. Periodic: one large
#             ac_diff = abs(hor_ac - vert_ac)
#             score = min(ac_diff * 3.0, 1.0) * 0.4 + (0.6 if sigma < 0.005 else 0.0)

#             if ac_diff > 0.2:
#                 findings.append(f"Directional noise autocorrelation asymmetry ({ac_diff:.3f}) — possible synthetic origin")

#             return float(min(score, 1.0)), findings

#         except Exception as e:
#             logger.debug("Noise pattern analysis failed: %s", e)
#             return 0.0, []

#     def _cnn_score(self, image: np.ndarray) -> float:
#         """
#         Placeholder for trained CNN-based AI detector.

#         To activate:
#         1. Download a pretrained model (e.g. CNNDetection by Wang et al.)
#         2. Save as 'models/ai_detector.pt'
#         3. Implement inference below

#         Returns 0.0 when no model is available.
#         """
#         model_path = Path("models/ai_detector.pt")
#         if not model_path.exists():
#             return -1.0

#         try:
#             import torch
#             import torchvision.transforms as T

#             model = torch.load(str(model_path), map_location="cpu")
#             model.eval()

#             transform = T.Compose([
#                 T.ToPILImage(),
#                 T.Resize((224, 224)),
#                 T.ToTensor(),
#                 T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
#             ])

#             tensor = transform(image).unsqueeze(0)
#             with torch.no_grad():
#                 logits = model(tensor)
#                 prob = torch.sigmoid(logits).item()
#             return float(prob)

#         except Exception as e:
#             logger.debug("CNN inference failed: %s", e)
#             return 0.0


# # ══════════════════════════════════════════════════════════════
# #  GAN DETECTION MODULE
# # ══════════════════════════════════════════════════════════════

# class GANDetectionModule(ForensicModule):
#     """
#     Detect GAN fingerprints and synthetic texture artifacts.

#     GAN-specific signatures:
#     1. Spectral peaks at specific frequencies (up-conv artifacts)
#     2. Characteristic checkerboard patterns in FFT
#     3. Spectral azimuthal anisotropy
#     4. Specific spatial frequency band energy ratios
#     """

#     MODULE_NAME = "gan"
#     WEIGHT = 0.07
#     MIN_IMAGE_SIZE = 64

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

#         spectral_score, spectral_findings = self._spectral_analysis(gray)
#         checkerboard_score = self._detect_checkerboard(gray)
#         azimuthal_score = self._azimuthal_anisotropy(gray)

#         findings = spectral_findings
#         if checkerboard_score > 0.65:
#             findings.append(f"Checkerboard artifact in frequency domain (score={checkerboard_score:.2f}) — GAN up-convolution")
#         if azimuthal_score > 0.55:
#             findings.append(f"Azimuthal spectral anisotropy ({azimuthal_score:.2f}) — synthetic generation pattern")

#         score = (
#             0.50 * spectral_score
#             + 0.30 * checkerboard_score
#             + 0.20 * azimuthal_score
#         )

#         confidence = 0.40 + score * 0.45

#         return self._make_score(
#             score=score,
#             confidence=confidence,
#             findings=findings,
#             raw_data={
#                 "spectral_score": spectral_score,
#                 "checkerboard_score": checkerboard_score,
#                 "azimuthal_score": azimuthal_score,
#             },
#         )

#     def _spectral_analysis(self, gray: np.ndarray) -> tuple[float, list[str]]:
#         """Compute 2D FFT and look for GAN spectral fingerprints."""
#         findings = []
#         fft = np.fft.fft2(gray)
#         fft_shift = np.fft.fftshift(fft)
#         magnitude = np.log1p(np.abs(fft_shift))

#         h, w = magnitude.shape
#         cy, cx = h // 2, w // 2

#         # Look for periodic peaks outside DC
#         # Remove DC component
#         mag_no_dc = magnitude.copy()
#         mag_no_dc[cy-5:cy+5, cx-5:cx+5] = 0

#         # Spectral mean excluding DC
#         spectral_mean = float(mag_no_dc.mean())
#         spectral_std = float(mag_no_dc.std())

#         # Find peaks significantly above mean
#         peak_mask = mag_no_dc > spectral_mean + 4.0 * spectral_std
#         peak_count = int(peak_mask.sum())

#         # Many spectral peaks = GAN grid artifact
#         peak_ratio = peak_count / max(h * w, 1)
#         score = min(peak_ratio * 500.0, 1.0)

#         if peak_count > 20:
#             findings.append(f"Spectral peaks in FFT ({peak_count}) suggest GAN fingerprint")

#         return score, findings

#     def _detect_checkerboard(self, gray: np.ndarray) -> float:
#         """
#         Detect checkerboard pattern in FFT — artifact from transposed convolution in GANs.

#         True GAN checkerboard: sharp isolated spikes at exact Nyquist grid positions
#         (h//2, w//2 and harmonics) that stand out *above the local high-frequency floor*.

#         Documents naturally have high corner energy due to text/line structure, so we
#         compare Nyquist-corner energy against the surrounding high-frequency neighbourhood
#         rather than against DC.  A genuine checkerboard artifact shows corner energy
#         significantly above its local neighbourhood; natural documents do not.
#         """
#         try:
#             fft = np.fft.fft2(gray)
#             magnitude = np.abs(fft)
#             h, w = magnitude.shape

#             # Corner 4×4 windows (Nyquist region in unshifted FFT)
#             corners = [
#                 magnitude[:4, :4],
#                 magnitude[:4, -4:],
#                 magnitude[-4:, :4],
#                 magnitude[-4:, -4:],
#             ]
#             corner_energy = float(np.mean([c.mean() for c in corners]))

#             # Local high-frequency neighbourhood (next ring out, 4-16 px from corners)
#             neighbourhood = [
#                 magnitude[4:16, 4:16],
#                 magnitude[4:16, -16:-4],
#                 magnitude[-16:-4, 4:16],
#                 magnitude[-16:-4, -16:-4],
#             ]
#             neigh_energy = float(np.mean([n.mean() for n in neighbourhood])) + 1e-8

#             # Ratio > 1 means Nyquist spike is above local floor → GAN checkerboard
#             # Typical documents: ratio ~0.8-1.2.  GAN artifacts: ratio >2.5
#             ratio = corner_energy / neigh_energy
#             score = float(np.clip((ratio - 1.2) / 2.0, 0.0, 1.0))
#             return score

#         except Exception:
#             return 0.0

#     def _azimuthal_anisotropy(self, gray: np.ndarray) -> float:
#         """
#         Measure azimuthal anisotropy of power spectrum.
#         Natural images: isotropic. Many GANs: anisotropic.

#         Documents always have strong H/V anisotropy from text baselines and borders,
#         so we compare the *diagonal* sectors (45°, 135°, 225°, 315°) against the
#         *axis-aligned* sectors (0°, 90°, 180°, 270°) rather than overall CV.
#         A GAN checkerboard creates equal spikes in ALL directions, not just H/V —
#         so the diagonal/axis ratio approaches 1.0 for GANs and <<1.0 for documents.
#         """
#         try:
#             fft = np.fft.fft2(gray)
#             fft_shift = np.fft.fftshift(fft)
#             power = np.abs(fft_shift) ** 2

#             h, w = power.shape
#             cy, cx = h // 2, w // 2

#             angles = np.arctan2(
#                 *np.mgrid[-cy:h - cy, -cx:w - cx]
#             )

#             sector_width = np.pi / 8  # 22.5° half-width per sector

#             def sector_mean(center_angle: float) -> float:
#                 lo = center_angle - sector_width
#                 hi = center_angle + sector_width
#                 mask = (angles >= lo) & (angles < hi)
#                 return float(power[mask].mean()) if mask.sum() > 0 else 0.0

#             # Axis-aligned sectors (documents always strong here)
#             axis = np.mean([
#                 sector_mean(0.0),
#                 sector_mean(np.pi / 2),
#                 sector_mean(-np.pi / 2),
#                 sector_mean(np.pi),
#             ]) + 1e-8

#             # Diagonal sectors (GANs show energy here too; documents don't)
#             diag = np.mean([
#                 sector_mean(np.pi / 4),
#                 sector_mean(3 * np.pi / 4),
#                 sector_mean(-np.pi / 4),
#                 sector_mean(-3 * np.pi / 4),
#             ])

#             # ratio→1 means isotropic (GAN); ratio<<1 means axis-dominant (document)
#             ratio = diag / axis
#             score = float(np.clip((ratio - 0.4) / 0.5, 0.0, 1.0))
#             return score

#         except Exception:
#             return 0.0


# # ══════════════════════════════════════════════════════════════
# #  FREQUENCY ANALYSIS MODULE
# # ══════════════════════════════════════════════════════════════

# class FrequencyAnalysisModule(ForensicModule):
#     """
#     FFT + DCT based manipulation trace detection.

#     Detects:
#     - Double JPEG compression (8×8 block grid in DCT)
#     - AI model signatures in frequency domain
#     - Localized frequency anomalies (spliced regions)
#     """

#     MODULE_NAME = "frequency"
#     WEIGHT = 0.05
#     MIN_IMAGE_SIZE = 64

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

#         double_jpeg_score, double_findings = self._detect_double_jpeg(gray)
#         fft_score, fft_findings = self._fft_manipulation_traces(gray)

#         findings = double_findings + fft_findings
#         score = 0.60 * double_jpeg_score + 0.40 * fft_score

#         return self._make_score(
#             score=score,
#             confidence=0.50 + score * 0.35,
#             findings=findings,
#             raw_data={
#                 "double_jpeg_score": double_jpeg_score,
#                 "fft_score": fft_score,
#             },
#         )

#     def _detect_double_jpeg(self, gray: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Detect double JPEG compression via DCT coefficient histogram.

#         First compression → quantizes DCT coefficients to multiples of Q
#         Second compression → creates characteristic "ghost" histogram peaks
#         Single-compressed: smooth histogram
#         Double-compressed: periodic spikes (Benford's law deviation)
#         """
#         findings = []
#         try:
#             from scipy.fft import dct

#             h, w = gray.shape
#             block_dcts = []

#             # Process 8×8 blocks
#             for y in range(0, h - 8, 8):
#                 for x in range(0, w - 8, 8):
#                     block = gray[y:y+8, x:x+8]
#                     d = dct(dct(block.T, norm='ortho').T, norm='ortho')
#                     block_dcts.append(d.ravel())

#             if not block_dcts:
#                 return 0.0, []

#             all_coeffs = np.array(block_dcts).ravel()

#             # Histogram of AC coefficients (exclude DC)
#             ac_coeffs = all_coeffs[all_coeffs != all_coeffs[0]]  # crude DC removal
#             hist, bins = np.histogram(ac_coeffs, bins=200, range=(-50, 50))

#             # Double JPEG: periodic dips at multiples of quantization step
#             # Detect by looking for alternating high/low pattern
#             if len(hist) < 20:
#                 return 0.0, []

#             # Measure periodicity via autocorrelation of histogram
#             hist_norm = hist / (hist.max() + 1e-8)
#             autocorr = np.correlate(hist_norm, hist_norm, mode='full')
#             autocorr = autocorr[len(autocorr)//2:]
#             # Normalized peaks at lag 1-10 indicate periodic structure
#             if autocorr[0] > 0:
#                 peak_ratio = float(autocorr[2:8].max() / autocorr[0])
#             else:
#                 peak_ratio = 0.0

#             score = min(peak_ratio * 3.0, 1.0)
#             if score > 0.4:
#                 findings.append(
#                     f"DCT coefficient periodicity ({peak_ratio:.3f}) — double JPEG compression detected"
#                 )

#             return score, findings

#         except Exception as e:
#             logger.debug("Double JPEG detection failed: %s", e)
#             return 0.0, []

#     def _fft_manipulation_traces(self, gray: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Detect manipulation traces in FFT via spectral whiteness test.
#         Manipulated regions often have non-stationary spectral content.
#         """
#         findings = []
#         fft = np.fft.fft2(gray)
#         magnitude = np.abs(np.fft.fftshift(fft))
#         log_mag = np.log1p(magnitude)

#         # Expected: 1/f spectral decay. Deviations indicate manipulation.
#         h, w = magnitude.shape
#         cy, cx = h // 2, w // 2

#         # Radial average
#         y_idx, x_idx = np.mgrid[-cy:h-cy, -cx:w-cx]
#         r = np.sqrt(x_idx**2 + y_idx**2).astype(int)
#         r_max = min(cy, cx)

#         if r_max < 10:
#             return 0.0, []

#         radial = np.zeros(r_max)
#         counts = np.zeros(r_max)
#         for ri in range(r_max):
#             mask = r == ri
#             if mask.sum() > 0:
#                 radial[ri] = float(magnitude[mask].mean())
#                 counts[ri] = mask.sum()

#         # Fit 1/f to radial profile; residuals = deviation from natural
#         freqs = np.arange(1, r_max)
#         if len(freqs) == 0:
#             return 0.0, []

#         expected = radial[1] / (freqs + 1e-8)  # 1/f model
#         actual = radial[1:r_max]
#         residuals = np.abs(actual - expected) / (expected + 1e-8)
#         mean_residual = float(residuals.mean())

#         score = min(mean_residual / 2.0, 1.0)
#         if score > 0.4:
#             findings.append(f"FFT spectral 1/f deviation ({mean_residual:.3f}) — manipulation traces")

#         return score, findings



# """
# AI Artifact Detection, GAN Detection, and Frequency Analysis Modules

# ═══════════════════════════════════════════════════════════════
# FORENSIC THEORY — AI DETECTION
# ═══════════════════════════════════════════════════════════════
# Generative models (Stable Diffusion, Flux, DALL-E, Midjourney) produce
# images that differ from camera-captured images in key ways:

# 1. FREQUENCY DOMAIN: AI images show characteristic spectral artifacts.
#    GANs produce a "grid pattern" in the FFT (GAN fingerprint).
#    Diffusion models create smoother but unnaturally clean noise floors.

# 2. NOISE PATTERNS: AI images lack natural sensor noise. Their noise
#    follows i.i.d. distributions rather than spatially correlated PRNU.

# 3. TEXTURE STATISTICS: Deep neural networks produce characteristic
#    texture distributions. Co-occurrence statistics (GLCM) differ.

# 4. SEMANTIC INCONSISTENCIES: Fingers, teeth, text, reflections — areas
#    where current models still fail.

# 5. GRADIENT STATISTICS: Natural images follow specific heavy-tailed
#    gradient distributions. AI images have lighter tails.

# ═══════════════════════════════════════════════════════════════
# FORENSIC THEORY — FREQUENCY ANALYSIS
# ═══════════════════════════════════════════════════════════════
# DCT (Discrete Cosine Transform) and FFT analysis expose:
# - Double JPEG compression grid artifacts (8×8 block traces)
# - AI generation grid artifacts
# - Splicing boundaries in frequency domain
# - Periodic tamper patterns invisible in spatial domain
# """

# from __future__ import annotations

# import logging
# from typing import Optional
# from pathlib import Path

# import numpy as np
# from PIL import Image

# from app.core.config import settings
# from app.domain.entities.document import ForensicContext, ModuleScore
# from app.domain.services.base_module import ForensicModule

# logger = logging.getLogger("docfraud.module.ai")


# # ══════════════════════════════════════════════════════════════
# #  AI ARTIFACT DETECTION
# # ══════════════════════════════════════════════════════════════

# class AIArtifactDetectionModule(ForensicModule):
#     """
#     Detect AI-generated image artifacts using texture, gradient, and spectral analysis.

#     Note: This module uses statistical/handcrafted features only.
#     For maximum accuracy, a trained CNN classifier (e.g. CNNDetection, GragnanielloGAN)
#     should be integrated via torch inference. The statistical approach here
#     achieves ~70-80% accuracy vs 90%+ for trained models.

#     Integration point: Replace _cnn_score() with a loaded PyTorch model.
#     """

#     MODULE_NAME = "ai_detection"
#     WEIGHT = 0.15
#     MIN_IMAGE_SIZE = 64
#     THRESHOLD = 0.50

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         findings = []

#         # 1. Gradient statistics
#         grad_score, grad_findings = self._gradient_statistics(image)
#         findings.extend(grad_findings)

#         # 2. Texture analysis (GLCM)
#         texture_score, texture_findings = self._texture_analysis(image)
#         findings.extend(texture_findings)

#         # 3. Noise pattern analysis
#         noise_score, noise_findings = self._noise_pattern_analysis(image)
#         findings.extend(noise_findings)

#         # 4. CNN score (placeholder — returns 0 without a model file)
#         cnn_score = self._cnn_score(image)

#         # Weighted combination
#         # 4. CNN score (-1.0 = no model available, omit from combination)
#         cnn_score = self._cnn_score(image)

#         # Weighted combination
#         if cnn_score >= 0.0:
#             score = (
#                 0.15 * grad_score
#                 + 0.15 * texture_score
#                 + 0.20 * noise_score
#                 + 0.50 * cnn_score
#             )
#         else:
#             # No CNN model — redistribute weights across statistical features
#             score = (
#                 0.35 * grad_score
#                 + 0.35 * texture_score
#                 + 0.30 * noise_score
#             )

#         ai_generated = score > self.THRESHOLD
#         if ai_generated:
#             findings.append(
#                 f"AI-generation probability: {score*100:.1f}% — likely AI-generated or AI-assisted"
#             )

#         confidence = 0.55 + abs(score - 0.5) * 0.8

#         return self._make_score(
#             score=score,
#             confidence=min(confidence, 0.90),
#             findings=findings,
#             raw_data={
#                 "gradient_score": grad_score,
#                 "texture_score": texture_score,
#                 "noise_score": noise_score,
#                 "cnn_score": cnn_score if cnn_score >= 0.0 else None,
#                 "cnn_model_available": cnn_score >= 0.0,
#             },
#         )

#     def _gradient_statistics(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Analyze gradient magnitude distribution.

#         AI images have lighter-tailed gradient distributions than natural images.
#         We measure kurtosis and tail weight of gradient histogram.
#         """
#         findings = []
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

#         # Compute gradients
#         gy, gx = np.gradient(gray)
#         mag = np.sqrt(gx**2 + gy**2).ravel()

#         if len(mag) == 0:
#             return 0.0, []

#         # Normalized gradient magnitude
#         mag_norm = mag / (mag.max() + 1e-8)

#         # Kurtosis — natural images: high (heavy tail); AI: lower (lighter tail)
#         mean_m = mag_norm.mean()
#         std_m = mag_norm.std() + 1e-8
#         kurtosis = float(np.mean(((mag_norm - mean_m) / std_m) ** 4))

#         # Natural image kurtosis typically 10-50; AI images 3-10
#         if kurtosis < 5.0:
#             score = 0.7 - kurtosis / 15.0  # Low kurtosis → AI signal
#             findings.append(f"Low gradient kurtosis ({kurtosis:.2f}) — AI generation signature")
#         elif kurtosis > 60.0:
#             score = 0.15
#         else:
#             score = max(0.0, (8.0 - kurtosis) / 8.0) * 0.5

#         return max(0.0, min(score, 1.0)), findings

#     def _texture_analysis(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Analyze texture via Local Binary Patterns and GLCM statistics.
#         AI images show unnaturally regular or smooth texture patterns.
#         """
#         findings = []
#         try:
#             from skimage.feature import graycomatrix, graycoprops

#             gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

#             # Downsample for speed
#             if gray.shape[0] > 512:
#                 from skimage.transform import resize
#                 gray = (resize(gray, (512, 512)) * 255).astype(np.uint8)

#             # GLCM at multiple distances and angles
#             glcm = graycomatrix(
#                 gray, distances=[1, 3], angles=[0, np.pi/4, np.pi/2],
#                 levels=64, symmetric=True, normed=True
#             )

#             contrast = float(graycoprops(glcm, 'contrast').mean())
#             energy = float(graycoprops(glcm, 'energy').mean())
#             homogeneity = float(graycoprops(glcm, 'homogeneity').mean())

#             # AI images tend toward: high energy, high homogeneity, low contrast
#             # These thresholds are empirically derived
#             ai_signal = (
#                 0.35 * min(energy / 0.05, 1.0)         # unnaturally high energy
#                 + 0.35 * min(homogeneity / 0.9, 1.0)   # unnaturally smooth
#                 + 0.30 * max(0, (0.3 - contrast) / 0.3) # very low contrast
#             )

#             if energy > 0.04:
#                 findings.append(f"Unnaturally high texture energy ({energy:.4f}) — AI texture signature")
#             if homogeneity > 0.85:
#                 findings.append(f"Excessive texture homogeneity ({homogeneity:.3f})")

#             return float(min(ai_signal, 1.0)), findings

#         except ImportError:
#             return 0.0, []
#         except Exception as e:
#             logger.debug("Texture analysis failed: %s", e)
#             return 0.0, []

#     def _noise_pattern_analysis(self, image: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Check if noise follows i.i.d. distribution (AI) vs spatially
#         correlated sensor noise (camera).
#         """
#         findings = []
#         try:
#             from skimage.restoration import denoise_wavelet, estimate_sigma

#             gray = np.mean(image, axis=2).astype(np.float64) / 255.0 if len(image.shape) == 3 else image.astype(np.float64) / 255.0

#             sigma = estimate_sigma(gray, average_sigmas=True)

#             if sigma < 0.002:
#                 findings.append(f"Near-zero noise level (σ={sigma:.5f}) — consistent with AI synthesis")
#                 return 0.75, findings

#             denoised = denoise_wavelet(gray, sigma=sigma, wavelet_levels=4)
#             residual = gray - denoised

#             # Test for spatial correlation: if i.i.d., autocorrelation ≈ delta
#             h, w = residual.shape
#             center_h, center_w = h // 2, w // 2
#             sample = residual[
#                 max(0, center_h-64):center_h+64,
#                 max(0, center_w-64):center_w+64
#             ]

#             if sample.size < 100:
#                 return 0.0, []

#             # Autocorrelation at lag-1
#             flat = sample.ravel()
#             ac = float(np.corrcoef(flat[:-1], flat[1:])[0, 1])

#             # Camera noise: |ac| ~ 0.0-0.1; AI: |ac| can be very small too
#             # But AI often shows periodic noise in autocorrelation
#             # We check variance of autocorrelation across directions

#             hor_ac = float(np.corrcoef(sample[0, :-1], sample[0, 1:])[0, 1]) if sample.shape[1] > 1 else 0.0
#             vert_ac = float(np.corrcoef(sample[:-1, 0], sample[1:, 0])[0, 1]) if sample.shape[0] > 1 else 0.0

#             # i.i.d. noise: both small. Periodic: one large
#             ac_diff = abs(hor_ac - vert_ac)
#             score = min(ac_diff * 3.0, 1.0) * 0.4 + (0.6 if sigma < 0.005 else 0.0)

#             if ac_diff > 0.2:
#                 findings.append(f"Directional noise autocorrelation asymmetry ({ac_diff:.3f}) — possible synthetic origin")

#             return float(min(score, 1.0)), findings

#         except Exception as e:
#             logger.debug("Noise pattern analysis failed: %s", e)
#             return 0.0, []

#     def _cnn_score(self, image: np.ndarray) -> float:
#         """
#         Placeholder for trained CNN-based AI detector.

#         To activate:
#         1. Download a pretrained model (e.g. CNNDetection by Wang et al.)
#         2. Save as 'models/ai_detector.pt'
#         3. Implement inference below

#         Returns 0.0 when no model is available.
#         """
#         model_path = Path("models/ai_detector.pt")
#         if not model_path.exists():
#             return -1.0

#         try:
#             import torch
#             import torchvision.transforms as T

#             model = torch.load(str(model_path), map_location="cpu")
#             model.eval()

#             transform = T.Compose([
#                 T.ToPILImage(),
#                 T.Resize((224, 224)),
#                 T.ToTensor(),
#                 T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
#             ])

#             tensor = transform(image).unsqueeze(0)
#             with torch.no_grad():
#                 logits = model(tensor)
#                 prob = torch.sigmoid(logits).item()
#             return float(prob)

#         except Exception as e:
#             logger.debug("CNN inference failed: %s", e)
#             return 0.0


# # ══════════════════════════════════════════════════════════════
# #  GAN DETECTION MODULE
# # ══════════════════════════════════════════════════════════════

# class GANDetectionModule(ForensicModule):
#     """
#     Detect GAN fingerprints and synthetic texture artifacts.

#     GAN-specific signatures:
#     1. Spectral peaks at specific frequencies (up-conv artifacts)
#     2. Characteristic checkerboard patterns in FFT
#     3. Spectral azimuthal anisotropy
#     4. Specific spatial frequency band energy ratios
#     """

#     MODULE_NAME = "gan"
#     WEIGHT = 0.07
#     MIN_IMAGE_SIZE = 64

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

#         spectral_score, spectral_findings = self._spectral_analysis(gray)
#         checkerboard_score = self._detect_checkerboard(gray)
#         azimuthal_score = self._azimuthal_anisotropy(gray)

#         findings = spectral_findings
#         # Checkerboard alone is not enough — real photographed documents with
#         # sharp text edges produce Nyquist-corner ratios > 1.2 naturally.
#         # Only flag AND fully credit checkerboard when spectral score also
#         # supports a GAN signature so both signals must agree.
#         # When spectral is low, checkerboard contribution is discounted to
#         # 10% of its raw value to prevent false-positive inflation.
#         checkerboard_confirmed = checkerboard_score > 0.65 and spectral_score > 0.30
#         if checkerboard_confirmed:
#             findings.append(
#                 f"Checkerboard artifact in frequency domain (score={checkerboard_score:.2f})"
#                 " — GAN up-convolution"
#             )
#         if azimuthal_score > 0.55:
#             findings.append(
#                 f"Azimuthal spectral anisotropy ({azimuthal_score:.2f})"
#                 " — synthetic generation pattern"
#             )

#         # Discount checkerboard when not spectrally confirmed (real doc FP guard)
#         checkerboard_contribution = checkerboard_score if checkerboard_confirmed else checkerboard_score * 0.10

#         score = (
#             0.50 * spectral_score
#             + 0.30 * checkerboard_contribution
#             + 0.20 * azimuthal_score
#         )

#         confidence = 0.40 + score * 0.45

#         return self._make_score(
#             score=score,
#             confidence=confidence,
#             findings=findings,
#             raw_data={
#                 "spectral_score": spectral_score,
#                 "checkerboard_score": checkerboard_score,
#                 "azimuthal_score": azimuthal_score,
#             },
#         )

#     def _spectral_analysis(self, gray: np.ndarray) -> tuple[float, list[str]]:
#         """Compute 2D FFT and look for GAN spectral fingerprints."""
#         findings = []
#         fft = np.fft.fft2(gray)
#         fft_shift = np.fft.fftshift(fft)
#         magnitude = np.log1p(np.abs(fft_shift))

#         h, w = magnitude.shape
#         cy, cx = h // 2, w // 2

#         # Look for periodic peaks outside DC
#         # Remove DC component
#         mag_no_dc = magnitude.copy()
#         mag_no_dc[cy-5:cy+5, cx-5:cx+5] = 0

#         # Spectral mean excluding DC
#         spectral_mean = float(mag_no_dc.mean())
#         spectral_std = float(mag_no_dc.std())

#         # Find peaks significantly above mean
#         peak_mask = mag_no_dc > spectral_mean + 4.0 * spectral_std
#         peak_count = int(peak_mask.sum())

#         # Many spectral peaks = GAN grid artifact
#         peak_ratio = peak_count / max(h * w, 1)
#         score = min(peak_ratio * 500.0, 1.0)

#         # Real documents with security holograms can show 100-400 spectral peaks.
#         # Genuine GAN fingerprints show 1000+ peaks.  Only flag above 500.
#         if peak_count > 500:
#             findings.append(f"Spectral peaks in FFT ({peak_count}) suggest GAN fingerprint")

#         return score, findings

#     def _detect_checkerboard(self, gray: np.ndarray) -> float:
#         """
#         Detect checkerboard pattern in FFT — artifact from transposed convolution in GANs.

#         True GAN checkerboard: sharp isolated spikes at exact Nyquist grid positions
#         (h//2, w//2 and harmonics) that stand out *above the local high-frequency floor*.

#         Documents naturally have high corner energy due to text/line structure, so we
#         compare Nyquist-corner energy against the surrounding high-frequency neighbourhood
#         rather than against DC.  A genuine checkerboard artifact shows corner energy
#         significantly above its local neighbourhood; natural documents do not.
#         """
#         try:
#             fft = np.fft.fft2(gray)
#             magnitude = np.abs(fft)
#             h, w = magnitude.shape

#             # Corner 4×4 windows (Nyquist region in unshifted FFT)
#             corners = [
#                 magnitude[:4, :4],
#                 magnitude[:4, -4:],
#                 magnitude[-4:, :4],
#                 magnitude[-4:, -4:],
#             ]
#             corner_energy = float(np.mean([c.mean() for c in corners]))

#             # Local high-frequency neighbourhood (next ring out, 4-16 px from corners)
#             neighbourhood = [
#                 magnitude[4:16, 4:16],
#                 magnitude[4:16, -16:-4],
#                 magnitude[-16:-4, 4:16],
#                 magnitude[-16:-4, -16:-4],
#             ]
#             neigh_energy = float(np.mean([n.mean() for n in neighbourhood])) + 1e-8

#             # Ratio > 1 means Nyquist spike is above local floor → GAN checkerboard
#             # Typical documents: ratio ~0.8-1.2.  GAN artifacts: ratio >2.5
#             ratio = corner_energy / neigh_energy
#             score = float(np.clip((ratio - 1.2) / 2.0, 0.0, 1.0))
#             return score

#         except Exception:
#             return 0.0

#     def _azimuthal_anisotropy(self, gray: np.ndarray) -> float:
#         """
#         Measure azimuthal anisotropy of power spectrum.
#         Natural images: isotropic. Many GANs: anisotropic.

#         Documents always have strong H/V anisotropy from text baselines and borders,
#         so we compare the *diagonal* sectors (45°, 135°, 225°, 315°) against the
#         *axis-aligned* sectors (0°, 90°, 180°, 270°) rather than overall CV.
#         A GAN checkerboard creates equal spikes in ALL directions, not just H/V —
#         so the diagonal/axis ratio approaches 1.0 for GANs and <<1.0 for documents.
#         """
#         try:
#             fft = np.fft.fft2(gray)
#             fft_shift = np.fft.fftshift(fft)
#             power = np.abs(fft_shift) ** 2

#             h, w = power.shape
#             cy, cx = h // 2, w // 2

#             angles = np.arctan2(
#                 *np.mgrid[-cy:h - cy, -cx:w - cx]
#             )

#             sector_width = np.pi / 8  # 22.5° half-width per sector

#             def sector_mean(center_angle: float) -> float:
#                 lo = center_angle - sector_width
#                 hi = center_angle + sector_width
#                 mask = (angles >= lo) & (angles < hi)
#                 return float(power[mask].mean()) if mask.sum() > 0 else 0.0

#             # Axis-aligned sectors (documents always strong here)
#             axis = np.mean([
#                 sector_mean(0.0),
#                 sector_mean(np.pi / 2),
#                 sector_mean(-np.pi / 2),
#                 sector_mean(np.pi),
#             ]) + 1e-8

#             # Diagonal sectors (GANs show energy here too; documents don't)
#             diag = np.mean([
#                 sector_mean(np.pi / 4),
#                 sector_mean(3 * np.pi / 4),
#                 sector_mean(-np.pi / 4),
#                 sector_mean(-3 * np.pi / 4),
#             ])

#             # ratio→1 means isotropic (GAN); ratio<<1 means axis-dominant (document)
#             ratio = diag / axis
#             score = float(np.clip((ratio - 0.4) / 0.5, 0.0, 1.0))
#             return score

#         except Exception:
#             return 0.0


# # ══════════════════════════════════════════════════════════════
# #  FREQUENCY ANALYSIS MODULE
# # ══════════════════════════════════════════════════════════════

# class FrequencyAnalysisModule(ForensicModule):
#     """
#     FFT + DCT based manipulation trace detection.

#     Detects:
#     - Double JPEG compression (8×8 block grid in DCT)
#     - AI model signatures in frequency domain
#     - Localized frequency anomalies (spliced regions)
#     """

#     MODULE_NAME = "frequency"
#     WEIGHT = 0.05
#     MIN_IMAGE_SIZE = 64

#     def _analyze(self, ctx: ForensicContext) -> ModuleScore:
#         if not ctx.page_images:
#             return self._make_score(0.0, 0.0)

#         image = ctx.page_images[0]
#         gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

#         double_jpeg_score, double_findings = self._detect_double_jpeg(gray)
#         fft_score, fft_findings = self._fft_manipulation_traces(gray)

#         findings = double_findings + fft_findings
#         score = 0.60 * double_jpeg_score + 0.40 * fft_score

#         return self._make_score(
#             score=score,
#             confidence=0.50 + score * 0.35,
#             findings=findings,
#             raw_data={
#                 "double_jpeg_score": double_jpeg_score,
#                 "fft_score": fft_score,
#             },
#         )

#     def _detect_double_jpeg(self, gray: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Detect double JPEG compression via DCT coefficient histogram.

#         First compression → quantizes DCT coefficients to multiples of Q
#         Second compression → creates characteristic "ghost" histogram peaks
#         Single-compressed: smooth histogram
#         Double-compressed: periodic spikes (Benford's law deviation)
#         """
#         findings = []
#         try:
#             from scipy.fft import dct

#             h, w = gray.shape
#             block_dcts = []

#             # Process 8×8 blocks
#             for y in range(0, h - 8, 8):
#                 for x in range(0, w - 8, 8):
#                     block = gray[y:y+8, x:x+8]
#                     d = dct(dct(block.T, norm='ortho').T, norm='ortho')
#                     block_dcts.append(d.ravel())

#             if not block_dcts:
#                 return 0.0, []

#             all_coeffs = np.array(block_dcts).ravel()

#             # Histogram of AC coefficients (exclude DC)
#             ac_coeffs = all_coeffs[all_coeffs != all_coeffs[0]]  # crude DC removal
#             hist, bins = np.histogram(ac_coeffs, bins=200, range=(-50, 50))

#             # Double JPEG: periodic dips at multiples of quantization step
#             # Detect by looking for alternating high/low pattern
#             if len(hist) < 20:
#                 return 0.0, []

#             # Measure periodicity via autocorrelation of histogram
#             hist_norm = hist / (hist.max() + 1e-8)
#             autocorr = np.correlate(hist_norm, hist_norm, mode='full')
#             autocorr = autocorr[len(autocorr)//2:]
#             # Normalized peaks at lag 1-10 indicate periodic structure
#             if autocorr[0] > 0:
#                 peak_ratio = float(autocorr[2:8].max() / autocorr[0])
#             else:
#                 peak_ratio = 0.0

#             score = min(peak_ratio * 3.0, 1.0)
#             if score > 0.4:
#                 findings.append(
#                     f"DCT coefficient periodicity ({peak_ratio:.3f}) — double JPEG compression detected"
#                 )

#             return score, findings

#         except Exception as e:
#             logger.debug("Double JPEG detection failed: %s", e)
#             return 0.0, []

#     def _fft_manipulation_traces(self, gray: np.ndarray) -> tuple[float, list[str]]:
#         """
#         Detect manipulation traces in FFT via spectral whiteness test.
#         Manipulated regions often have non-stationary spectral content.
#         """
#         findings = []
#         fft = np.fft.fft2(gray)
#         magnitude = np.abs(np.fft.fftshift(fft))
#         log_mag = np.log1p(magnitude)

#         # Expected: 1/f spectral decay. Deviations indicate manipulation.
#         h, w = magnitude.shape
#         cy, cx = h // 2, w // 2

#         # Radial average
#         y_idx, x_idx = np.mgrid[-cy:h-cy, -cx:w-cx]
#         r = np.sqrt(x_idx**2 + y_idx**2).astype(int)
#         r_max = min(cy, cx)

#         if r_max < 10:
#             return 0.0, []

#         radial = np.zeros(r_max)
#         counts = np.zeros(r_max)
#         for ri in range(r_max):
#             mask = r == ri
#             if mask.sum() > 0:
#                 radial[ri] = float(magnitude[mask].mean())
#                 counts[ri] = mask.sum()

#         # Fit 1/f to radial profile; residuals = deviation from natural
#         freqs = np.arange(1, r_max)
#         if len(freqs) == 0:
#             return 0.0, []

#         expected = radial[1] / (freqs + 1e-8)  # 1/f model
#         actual = radial[1:r_max]
#         residuals = np.abs(actual - expected) / (expected + 1e-8)
#         mean_residual = float(residuals.mean())

#         score = min(mean_residual / 2.0, 1.0)
#         if score > 0.4:
#             findings.append(f"FFT spectral 1/f deviation ({mean_residual:.3f}) — manipulation traces")

#         return score, findings

"""
AI Artifact Detection, GAN Detection, and Frequency Analysis Modules

═══════════════════════════════════════════════════════════════
FORENSIC THEORY — AI DETECTION
═══════════════════════════════════════════════════════════════
Generative models (Stable Diffusion, Flux, DALL-E, Midjourney) produce
images that differ from camera-captured images in key ways:

1. FREQUENCY DOMAIN: AI images show characteristic spectral artifacts.
   GANs produce a "grid pattern" in the FFT (GAN fingerprint).
   Diffusion models create smoother but unnaturally clean noise floors.

2. NOISE PATTERNS: AI images lack natural sensor noise. Their noise
   follows i.i.d. distributions rather than spatially correlated PRNU.

3. TEXTURE STATISTICS: Deep neural networks produce characteristic
   texture distributions. Co-occurrence statistics (GLCM) differ.

4. SEMANTIC INCONSISTENCIES: Fingers, teeth, text, reflections — areas
   where current models still fail.

5. GRADIENT STATISTICS: Natural images follow specific heavy-tailed
   gradient distributions. AI images have lighter tails.

═══════════════════════════════════════════════════════════════
FORENSIC THEORY — FREQUENCY ANALYSIS
═══════════════════════════════════════════════════════════════
DCT (Discrete Cosine Transform) and FFT analysis expose:
- Double JPEG compression grid artifacts (8×8 block traces)
- AI generation grid artifacts
- Splicing boundaries in frequency domain
- Periodic tamper patterns invisible in spatial domain
"""

from __future__ import annotations

import logging
from typing import Optional
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import settings
from app.domain.entities.document import ForensicContext, ModuleScore
from app.domain.services.base_module import ForensicModule

logger = logging.getLogger("docfraud.module.ai")


# ══════════════════════════════════════════════════════════════
#  AI ARTIFACT DETECTION
# ══════════════════════════════════════════════════════════════

class AIArtifactDetectionModule(ForensicModule):
    """
    Detect AI-generated image artifacts using texture, gradient, and spectral analysis.

    Note: This module uses statistical/handcrafted features only.
    For maximum accuracy, a trained CNN classifier (e.g. CNNDetection, GragnanielloGAN)
    should be integrated via torch inference. The statistical approach here
    achieves ~70-80% accuracy vs 90%+ for trained models.

    Integration point: Replace _cnn_score() with a loaded PyTorch model.
    """

    MODULE_NAME = "ai_detection"
    WEIGHT = 0.15
    MIN_IMAGE_SIZE = 64
    THRESHOLD = 0.50

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        findings = []

        # 1. Gradient statistics
        grad_score, grad_findings = self._gradient_statistics(image)
        findings.extend(grad_findings)

        # 2. Texture analysis (GLCM)
        texture_score, texture_findings = self._texture_analysis(image)
        findings.extend(texture_findings)

        # 3. Noise pattern analysis
        noise_score, noise_findings = self._noise_pattern_analysis(image)
        findings.extend(noise_findings)

        # 4. CNN score (placeholder — returns 0 without a model file)
        cnn_score = self._cnn_score(image)

        # Weighted combination
        # 4. CNN score (-1.0 = no model available, omit from combination)
        cnn_score = self._cnn_score(image)

        # Weighted combination
        if cnn_score >= 0.0:
            score = (
                0.15 * grad_score
                + 0.15 * texture_score
                + 0.20 * noise_score
                + 0.50 * cnn_score
            )
        else:
            # No CNN model — redistribute weights across statistical features
            score = (
                0.35 * grad_score
                + 0.35 * texture_score
                + 0.30 * noise_score
            )

        ai_generated = score > self.THRESHOLD
        if ai_generated:
            findings.append(
                f"AI-generation probability: {score*100:.1f}% — likely AI-generated or AI-assisted"
            )

        confidence = 0.55 + abs(score - 0.5) * 0.8

        return self._make_score(
            score=score,
            confidence=min(confidence, 0.90),
            findings=findings,
            raw_data={
                "gradient_score": grad_score,
                "texture_score": texture_score,
                "noise_score": noise_score,
                "cnn_score": cnn_score if cnn_score >= 0.0 else None,
                "cnn_model_available": cnn_score >= 0.0,
            },
        )

    def _gradient_statistics(self, image: np.ndarray) -> tuple[float, list[str]]:
        """
        Analyze gradient magnitude distribution.

        AI images have lighter-tailed gradient distributions than natural images.
        We measure kurtosis and tail weight of gradient histogram.
        """
        findings = []
        gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

        # Compute gradients
        gy, gx = np.gradient(gray)
        mag = np.sqrt(gx**2 + gy**2).ravel()

        if len(mag) == 0:
            return 0.0, []

        # Normalized gradient magnitude
        mag_norm = mag / (mag.max() + 1e-8)

        # Kurtosis — natural images: high (heavy tail); AI: lower (lighter tail)
        mean_m = mag_norm.mean()
        std_m = mag_norm.std() + 1e-8
        kurtosis = float(np.mean(((mag_norm - mean_m) / std_m) ** 4))

        # Natural image kurtosis typically 10-50; AI images 3-10
        if kurtosis < 5.0:
            score = 0.7 - kurtosis / 15.0  # Low kurtosis → AI signal
            findings.append(f"Low gradient kurtosis ({kurtosis:.2f}) — AI generation signature")
        elif kurtosis > 60.0:
            score = 0.15
        else:
            score = max(0.0, (8.0 - kurtosis) / 8.0) * 0.5

        return max(0.0, min(score, 1.0)), findings

    def _texture_analysis(self, image: np.ndarray) -> tuple[float, list[str]]:
        """
        Analyze texture via Local Binary Patterns and GLCM statistics.
        AI images show unnaturally regular or smooth texture patterns.
        """
        findings = []
        try:
            from skimage.feature import graycomatrix, graycoprops

            gray = np.mean(image, axis=2).astype(np.uint8) if len(image.shape) == 3 else image.astype(np.uint8)

            # Downsample for speed
            if gray.shape[0] > 512:
                from skimage.transform import resize
                gray = (resize(gray, (512, 512)) * 255).astype(np.uint8)

            # GLCM at multiple distances and angles
            glcm = graycomatrix(
                gray, distances=[1, 3], angles=[0, np.pi/4, np.pi/2],
                levels=64, symmetric=True, normed=True
            )

            contrast = float(graycoprops(glcm, 'contrast').mean())
            energy = float(graycoprops(glcm, 'energy').mean())
            homogeneity = float(graycoprops(glcm, 'homogeneity').mean())

            # AI images tend toward: high energy, high homogeneity, low contrast
            # These thresholds are empirically derived
            ai_signal = (
                0.35 * min(energy / 0.05, 1.0)         # unnaturally high energy
                + 0.35 * min(homogeneity / 0.9, 1.0)   # unnaturally smooth
                + 0.30 * max(0, (0.3 - contrast) / 0.3) # very low contrast
            )

            if energy > 0.04:
                findings.append(f"Unnaturally high texture energy ({energy:.4f}) — AI texture signature")
            if homogeneity > 0.85:
                findings.append(f"Excessive texture homogeneity ({homogeneity:.3f})")

            return float(min(ai_signal, 1.0)), findings

        except ImportError:
            return 0.0, []
        except Exception as e:
            logger.debug("Texture analysis failed: %s", e)
            return 0.0, []

    def _noise_pattern_analysis(self, image: np.ndarray) -> tuple[float, list[str]]:
        """
        Check if noise follows i.i.d. distribution (AI) vs spatially
        correlated sensor noise (camera).
        """
        findings = []
        try:
            from skimage.restoration import denoise_wavelet, estimate_sigma

            gray = np.mean(image, axis=2).astype(np.float64) / 255.0 if len(image.shape) == 3 else image.astype(np.float64) / 255.0

            sigma = estimate_sigma(gray, average_sigmas=True)

            if sigma < 0.002:
                findings.append(f"Near-zero noise level (σ={sigma:.5f}) — consistent with AI synthesis")
                return 0.75, findings

            denoised = denoise_wavelet(gray, sigma=sigma, wavelet_levels=4)
            residual = gray - denoised

            # Test for spatial correlation: if i.i.d., autocorrelation ≈ delta
            h, w = residual.shape
            center_h, center_w = h // 2, w // 2
            sample = residual[
                max(0, center_h-64):center_h+64,
                max(0, center_w-64):center_w+64
            ]

            if sample.size < 100:
                return 0.0, []

            # Autocorrelation at lag-1
            flat = sample.ravel()
            ac = float(np.corrcoef(flat[:-1], flat[1:])[0, 1])

            # Camera noise: |ac| ~ 0.0-0.1; AI: |ac| can be very small too
            # But AI often shows periodic noise in autocorrelation
            # We check variance of autocorrelation across directions

            hor_ac = float(np.corrcoef(sample[0, :-1], sample[0, 1:])[0, 1]) if sample.shape[1] > 1 else 0.0
            vert_ac = float(np.corrcoef(sample[:-1, 0], sample[1:, 0])[0, 1]) if sample.shape[0] > 1 else 0.0

            # i.i.d. noise: both small. Periodic: one large
            ac_diff = abs(hor_ac - vert_ac)
            score = min(ac_diff * 3.0, 1.0) * 0.4 + (0.6 if sigma < 0.005 else 0.0)

            if ac_diff > 0.2:
                findings.append(f"Directional noise autocorrelation asymmetry ({ac_diff:.3f}) — possible synthetic origin")

            return float(min(score, 1.0)), findings

        except Exception as e:
            logger.debug("Noise pattern analysis failed: %s", e)
            return 0.0, []

    def _cnn_score(self, image: np.ndarray) -> float:
        """
        Placeholder for trained CNN-based AI detector.

        To activate:
        1. Download a pretrained model (e.g. CNNDetection by Wang et al.)
        2. Save as 'models/ai_detector.pt'
        3. Implement inference below

        Returns 0.0 when no model is available.
        """
        model_path = Path("models/ai_detector.pt")
        if not model_path.exists():
            return -1.0

        try:
            import torch
            import torchvision.transforms as T

            model = torch.load(str(model_path), map_location="cpu")
            model.eval()

            transform = T.Compose([
                T.ToPILImage(),
                T.Resize((224, 224)),
                T.ToTensor(),
                T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])

            tensor = transform(image).unsqueeze(0)
            with torch.no_grad():
                logits = model(tensor)
                prob = torch.sigmoid(logits).item()
            return float(prob)

        except Exception as e:
            logger.debug("CNN inference failed: %s", e)
            return 0.0


# ══════════════════════════════════════════════════════════════
#  GAN DETECTION MODULE
# ══════════════════════════════════════════════════════════════

class GANDetectionModule(ForensicModule):
    """
    Detect GAN fingerprints and synthetic texture artifacts.

    GAN-specific signatures:
    1. Spectral peaks at specific frequencies (up-conv artifacts)
    2. Characteristic checkerboard patterns in FFT
    3. Spectral azimuthal anisotropy
    4. Specific spatial frequency band energy ratios
    """

    MODULE_NAME = "gan"
    WEIGHT = 0.07
    MIN_IMAGE_SIZE = 64

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

        spectral_score, spectral_findings = self._spectral_analysis(gray)
        checkerboard_score = self._detect_checkerboard(gray)
        azimuthal_score = self._azimuthal_anisotropy(gray)

        findings = spectral_findings
        # Checkerboard alone is not enough — real photographed documents with
        # sharp text edges produce Nyquist-corner ratios > 1.2 naturally.
        # Only flag AND fully credit checkerboard when spectral score also
        # supports a GAN signature so both signals must agree.
        # When spectral is low, checkerboard contribution is discounted to
        # 10% of its raw value to prevent false-positive inflation.
        checkerboard_confirmed = checkerboard_score > 0.65 and spectral_score > 0.30
        if checkerboard_confirmed:
            findings.append(
                f"Checkerboard artifact in frequency domain (score={checkerboard_score:.2f})"
                " — GAN up-convolution"
            )
        if azimuthal_score > 0.55:
            findings.append(
                f"Azimuthal spectral anisotropy ({azimuthal_score:.2f})"
                " — synthetic generation pattern"
            )

        # Discount checkerboard when not spectrally confirmed (real doc FP guard)
        checkerboard_contribution = checkerboard_score if checkerboard_confirmed else checkerboard_score * 0.10

        # Store sub-signal scores on self so the fixed assembly block can read them
        self._checkerboard_score = float(checkerboard_contribution)
        self._fft_peak_score = float(spectral_score)

        # ── GAN score assembly (fixed) ────────────────────────────────────────
        checkerboard_score_clamped = max(0.0, min(self._checkerboard_score, 1.0))
        fft_peak_score_clamped     = max(0.0, min(self._fft_peak_score,     1.0))

        # Option A (recommended) — dominant signal wins
        gan_score = max(checkerboard_score_clamped, fft_peak_score_clamped)

        # Hard floor: checkerboard ≥ 0.80 cannot appear in genuine photos
        if checkerboard_score_clamped >= 0.80:
            gan_score = max(gan_score, 0.85)

        gan_score = round(min(gan_score, 1.0), 4)

        # ── Expose for scoring engine ─────────────────────────────────────────
        self._checkerboard_score = checkerboard_score_clamped   # ← engine reads this
        self.score               = gan_score

        confidence = 0.40 + gan_score * 0.45

        return self._make_score(
            score=gan_score,
            confidence=confidence,
            findings=findings,
            raw_data={
                "spectral_score": spectral_score,
                "checkerboard_score": checkerboard_score,
                "azimuthal_score": azimuthal_score,
            },
        )

    def _spectral_analysis(self, gray: np.ndarray) -> tuple[float, list[str]]:
        """Compute 2D FFT and look for GAN spectral fingerprints."""
        findings = []
        fft = np.fft.fft2(gray)
        fft_shift = np.fft.fftshift(fft)
        magnitude = np.log1p(np.abs(fft_shift))

        h, w = magnitude.shape
        cy, cx = h // 2, w // 2

        # Look for periodic peaks outside DC
        # Remove DC component
        mag_no_dc = magnitude.copy()
        mag_no_dc[cy-5:cy+5, cx-5:cx+5] = 0

        # Spectral mean excluding DC
        spectral_mean = float(mag_no_dc.mean())
        spectral_std = float(mag_no_dc.std())

        # Find peaks significantly above mean
        peak_mask = mag_no_dc > spectral_mean + 4.0 * spectral_std
        peak_count = int(peak_mask.sum())

        # Many spectral peaks = GAN grid artifact
        peak_ratio = peak_count / max(h * w, 1)
        score = min(peak_ratio * 500.0, 1.0)

        # Real documents with security holograms can show 100-400 spectral peaks.
        # Genuine GAN fingerprints show 1000+ peaks.  Only flag above 500.
        if peak_count > 500:
            findings.append(f"Spectral peaks in FFT ({peak_count}) suggest GAN fingerprint")

        return score, findings

    def _detect_checkerboard(self, gray: np.ndarray) -> float:
        """
        Detect checkerboard pattern in FFT — artifact from transposed convolution in GANs.

        True GAN checkerboard: sharp isolated spikes at exact Nyquist grid positions
        (h//2, w//2 and harmonics) that stand out *above the local high-frequency floor*.

        Documents naturally have high corner energy due to text/line structure, so we
        compare Nyquist-corner energy against the surrounding high-frequency neighbourhood
        rather than against DC.  A genuine checkerboard artifact shows corner energy
        significantly above its local neighbourhood; natural documents do not.
        """
        try:
            fft = np.fft.fft2(gray)
            magnitude = np.abs(fft)
            h, w = magnitude.shape

            # Corner 4×4 windows (Nyquist region in unshifted FFT)
            corners = [
                magnitude[:4, :4],
                magnitude[:4, -4:],
                magnitude[-4:, :4],
                magnitude[-4:, -4:],
            ]
            corner_energy = float(np.mean([c.mean() for c in corners]))

            # Local high-frequency neighbourhood (next ring out, 4-16 px from corners)
            neighbourhood = [
                magnitude[4:16, 4:16],
                magnitude[4:16, -16:-4],
                magnitude[-16:-4, 4:16],
                magnitude[-16:-4, -16:-4],
            ]
            neigh_energy = float(np.mean([n.mean() for n in neighbourhood])) + 1e-8

            # Ratio > 1 means Nyquist spike is above local floor → GAN checkerboard
            # Typical documents: ratio ~0.8-1.2.  GAN artifacts: ratio >2.5
            ratio = corner_energy / neigh_energy
            score = float(np.clip((ratio - 1.2) / 2.0, 0.0, 1.0))
            return score

        except Exception:
            return 0.0

    def _azimuthal_anisotropy(self, gray: np.ndarray) -> float:
        """
        Measure azimuthal anisotropy of power spectrum.
        Natural images: isotropic. Many GANs: anisotropic.

        Documents always have strong H/V anisotropy from text baselines and borders,
        so we compare the *diagonal* sectors (45°, 135°, 225°, 315°) against the
        *axis-aligned* sectors (0°, 90°, 180°, 270°) rather than overall CV.
        A GAN checkerboard creates equal spikes in ALL directions, not just H/V —
        so the diagonal/axis ratio approaches 1.0 for GANs and <<1.0 for documents.
        """
        try:
            fft = np.fft.fft2(gray)
            fft_shift = np.fft.fftshift(fft)
            power = np.abs(fft_shift) ** 2

            h, w = power.shape
            cy, cx = h // 2, w // 2

            angles = np.arctan2(
                *np.mgrid[-cy:h - cy, -cx:w - cx]
            )

            sector_width = np.pi / 8  # 22.5° half-width per sector

            def sector_mean(center_angle: float) -> float:
                lo = center_angle - sector_width
                hi = center_angle + sector_width
                mask = (angles >= lo) & (angles < hi)
                return float(power[mask].mean()) if mask.sum() > 0 else 0.0

            # Axis-aligned sectors (documents always strong here)
            axis = np.mean([
                sector_mean(0.0),
                sector_mean(np.pi / 2),
                sector_mean(-np.pi / 2),
                sector_mean(np.pi),
            ]) + 1e-8

            # Diagonal sectors (GANs show energy here too; documents don't)
            diag = np.mean([
                sector_mean(np.pi / 4),
                sector_mean(3 * np.pi / 4),
                sector_mean(-np.pi / 4),
                sector_mean(-3 * np.pi / 4),
            ])

            # ratio→1 means isotropic (GAN); ratio<<1 means axis-dominant (document)
            ratio = diag / axis
            score = float(np.clip((ratio - 0.4) / 0.5, 0.0, 1.0))
            return score

        except Exception:
            return 0.0


# ══════════════════════════════════════════════════════════════
#  FREQUENCY ANALYSIS MODULE
# ══════════════════════════════════════════════════════════════

class FrequencyAnalysisModule(ForensicModule):
    """
    FFT + DCT based manipulation trace detection.

    Detects:
    - Double JPEG compression (8×8 block grid in DCT)
    - AI model signatures in frequency domain
    - Localized frequency anomalies (spliced regions)
    """

    MODULE_NAME = "frequency"
    WEIGHT = 0.05
    MIN_IMAGE_SIZE = 64

    def _analyze(self, ctx: ForensicContext) -> ModuleScore:
        if not ctx.page_images:
            return self._make_score(0.0, 0.0)

        image = ctx.page_images[0]
        gray = np.mean(image, axis=2).astype(np.float32) if len(image.shape) == 3 else image.astype(np.float32)

        double_jpeg_score, double_findings = self._detect_double_jpeg(gray)
        fft_score, fft_findings = self._fft_manipulation_traces(gray)

        findings = double_findings + fft_findings
        score = 0.60 * double_jpeg_score + 0.40 * fft_score

        return self._make_score(
            score=score,
            confidence=0.50 + score * 0.35,
            findings=findings,
            raw_data={
                "double_jpeg_score": double_jpeg_score,
                "fft_score": fft_score,
            },
        )

    def _detect_double_jpeg(self, gray: np.ndarray) -> tuple[float, list[str]]:
        """
        Detect double JPEG compression via DCT coefficient histogram.

        First compression → quantizes DCT coefficients to multiples of Q
        Second compression → creates characteristic "ghost" histogram peaks
        Single-compressed: smooth histogram
        Double-compressed: periodic spikes (Benford's law deviation)
        """
        findings = []
        try:
            from scipy.fft import dct

            h, w = gray.shape
            block_dcts = []

            # Process 8×8 blocks
            for y in range(0, h - 8, 8):
                for x in range(0, w - 8, 8):
                    block = gray[y:y+8, x:x+8]
                    d = dct(dct(block.T, norm='ortho').T, norm='ortho')
                    block_dcts.append(d.ravel())

            if not block_dcts:
                return 0.0, []

            all_coeffs = np.array(block_dcts).ravel()

            # Histogram of AC coefficients (exclude DC)
            ac_coeffs = all_coeffs[all_coeffs != all_coeffs[0]]  # crude DC removal
            hist, bins = np.histogram(ac_coeffs, bins=200, range=(-50, 50))

            # Double JPEG: periodic dips at multiples of quantization step
            # Detect by looking for alternating high/low pattern
            if len(hist) < 20:
                return 0.0, []

            # Measure periodicity via autocorrelation of histogram
            hist_norm = hist / (hist.max() + 1e-8)
            autocorr = np.correlate(hist_norm, hist_norm, mode='full')
            autocorr = autocorr[len(autocorr)//2:]
            # Normalized peaks at lag 1-10 indicate periodic structure
            if autocorr[0] > 0:
                peak_ratio = float(autocorr[2:8].max() / autocorr[0])
            else:
                peak_ratio = 0.0

            score = min(peak_ratio * 3.0, 1.0)
            if score > 0.4:
                findings.append(
                    f"DCT coefficient periodicity ({peak_ratio:.3f}) — double JPEG compression detected"
                )

            return score, findings

        except Exception as e:
            logger.debug("Double JPEG detection failed: %s", e)
            return 0.0, []

    def _fft_manipulation_traces(self, gray: np.ndarray) -> tuple[float, list[str]]:
        """
        Detect manipulation traces in FFT via spectral whiteness test.
        Manipulated regions often have non-stationary spectral content.
        """
        findings = []
        fft = np.fft.fft2(gray)
        magnitude = np.abs(np.fft.fftshift(fft))
        log_mag = np.log1p(magnitude)

        # Expected: 1/f spectral decay. Deviations indicate manipulation.
        h, w = magnitude.shape
        cy, cx = h // 2, w // 2

        # Radial average
        y_idx, x_idx = np.mgrid[-cy:h-cy, -cx:w-cx]
        r = np.sqrt(x_idx**2 + y_idx**2).astype(int)
        r_max = min(cy, cx)

        if r_max < 10:
            return 0.0, []

        radial = np.zeros(r_max)
        counts = np.zeros(r_max)
        for ri in range(r_max):
            mask = r == ri
            if mask.sum() > 0:
                radial[ri] = float(magnitude[mask].mean())
                counts[ri] = mask.sum()

        # Fit 1/f to radial profile; residuals = deviation from natural
        freqs = np.arange(1, r_max)
        if len(freqs) == 0:
            return 0.0, []

        expected = radial[1] / (freqs + 1e-8)  # 1/f model
        actual = radial[1:r_max]
        residuals = np.abs(actual - expected) / (expected + 1e-8)
        mean_residual = float(residuals.mean())

        score = min(mean_residual / 2.0, 1.0)
        if score > 0.4:
            findings.append(f"FFT spectral 1/f deviation ({mean_residual:.3f}) — manipulation traces")

        return score, findings