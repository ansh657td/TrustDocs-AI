"""
Document Preprocessor

Responsibilities:
1. Validate uploaded file (magic bytes, size, format)
2. Detect document type (PDF, scan, mobile capture, screenshot, computer-generated)
3. Extract image representation(s) for forensic modules
4. Extract basic image properties
5. Compute file hash

Theory:
  Document type classification uses a combination of:
  - MIME type / magic bytes
  - EXIF metadata (camera make/model, GPS = mobile capture)
  - DPI analysis (72/96 dpi = screen, 300+ = scan/print)
  - Noise texture analysis (scanner CCD noise vs camera CMOS vs digital)
  - Compression artifacts (JPEG mobile vs PDF-embedded)

Complexity: O(W*H) for image loading, O(n) for PDF page rasterization
False positive risk: Low for PDF detection; moderate for scan vs mobile
"""

from __future__ import annotations

import io
import logging
import mimetypes
import struct
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ExifTags, UnidentifiedImageError

from app.core.config import settings
from app.domain.entities.document import (
    DocumentType,
    FileHash,
    ForensicContext,
    ImageProperties,
)


from pdf2image import convert_from_path
import platform

logger = logging.getLogger("docfraud.preprocessor")

# Magic bytes for format detection
MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",   # Followed by WEBP
    b"II*\x00": "image/tiff",
    b"MM\x00*": "image/tiff",
    b"%PDF": "application/pdf",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}

MAX_FILE_BYTES = settings.max_upload_mb * 1024 * 1024

ALLOWED_MIMES = {
    "image/jpeg", "image/png", "image/webp",
    "image/tiff", "image/gif", "application/pdf",
}

# DPI thresholds
SCREEN_DPI_MAX = 120.0
MOBILE_DPI_MIN = 72.0
MOBILE_DPI_MAX = 480.0
PRINT_DPI_MIN = 200.0


class PreprocessorError(Exception):
    pass


class DocumentPreprocessor:
    """
    Converts a raw uploaded file into a ForensicContext ready for the pipeline.
    """

    def __init__(self):
        self.logger = logging.getLogger("docfraud.preprocessor")

    def prepare(
        self,
        file_path: Path,
        job_id: str,
        document_id: str,
        original_filename: str,
        requested_by: Optional[str] = None,
    ) -> ForensicContext:
        """
        Full preprocessing pipeline.

        Args:
            file_path: Path to uploaded file on disk
            job_id: Analysis job UUID
            document_id: Document record UUID
            original_filename: User-provided filename
            requested_by: IP address or user identifier

        Returns:
            ForensicContext ready for forensic pipeline

        Raises:
            PreprocessorError: If file is invalid, corrupt, or unsupported
        """
        self.logger.info("Preprocessing %s for job %s", file_path, job_id)

        # 1. Size check
        file_size = file_path.stat().st_size
        if file_size == 0:
            raise PreprocessorError("File is empty.")
        if file_size > MAX_FILE_BYTES:
            raise PreprocessorError(
                f"File size {file_size} exceeds limit {MAX_FILE_BYTES}."
            )

        # 2. Hash
        file_hash = FileHash.from_path(file_path)
        self.logger.info("File hash: %s", file_hash.value)

        # 3. MIME detection from magic bytes
        mime_type = self._detect_mime(file_path)
        if mime_type not in ALLOWED_MIMES:
            raise PreprocessorError(f"Unsupported file type: {mime_type}")

        # 4. Load image representation
        page_images, img_props = self._load_images(file_path, mime_type)

        # 5. Detect document type
        doc_type = self._classify_document_type(
            file_path, mime_type, img_props, page_images
        )

        ctx = ForensicContext(
            job_id=job_id,
            document_id=document_id,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            mime_type=mime_type,
            original_filename=original_filename,
            document_type=doc_type,
            image_properties=img_props,
            page_images=page_images,
        )

        self.logger.info(
            "Preprocessed: type=%s size=%dx%d dpi=%s doc_type=%s",
            mime_type,
            img_props.width if img_props else 0,
            img_props.height if img_props else 0,
            img_props.dpi if img_props else None,
            doc_type.value,
        )

        return ctx

    # ─────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────

    def _detect_mime(self, path: Path) -> str:
        """Detect MIME from magic bytes, not file extension."""
        with open(path, "rb") as f:
            header = f.read(16)

        for magic, mime in MAGIC_BYTES.items():
            if header[: len(magic)] == magic:
                # Special case: RIFF + WEBP
                if magic == b"RIFF" and header[8:12] == b"WEBP":
                    return "image/webp"
                elif magic == b"RIFF":
                    continue  # Not WEBP
                return mime

        # Fallback to extension
        guessed, _ = mimetypes.guess_type(str(path))
        return guessed or "application/octet-stream"

    def _load_images(
        self, path: Path, mime: str
    ) -> tuple[list[np.ndarray], Optional[ImageProperties]]:
        """
        Load document as numpy array(s).

        For PDFs: rasterize each page at 150 DPI using pdf2image.
        For images: load directly with PIL.

        Returns:
            (list of numpy arrays in RGB, ImageProperties)
        """
        if mime == "application/pdf":
            return self._load_pdf(path)
        else:
            return self._load_image(path)

    def _load_image(
        self, path: Path
    ) -> tuple[list[np.ndarray], ImageProperties]:
        """Load image file into numpy array."""
        try:
            with Image.open(path) as img:
                # Preserve original mode for analysis
                original_mode = img.mode
                fmt = img.format or "unknown"

                # Get DPI
                dpi = None
                if hasattr(img, "info") and "dpi" in img.info:
                    raw_dpi = img.info["dpi"]
                    if isinstance(raw_dpi, tuple):
                        dpi = float(raw_dpi[0])
                    else:
                        dpi = float(raw_dpi)

                # Convert to RGB for analysis
                if img.mode in ("RGBA", "P"):
                    has_alpha = True
                    rgb = img.convert("RGB")
                elif img.mode == "L":
                    has_alpha = False
                    rgb = img.convert("RGB")
                elif img.mode == "CMYK":
                    has_alpha = False
                    rgb = img.convert("RGB")
                else:
                    has_alpha = "A" in img.mode
                    rgb = img.convert("RGB")

                w, h = img.size

                props = ImageProperties(
                    width=w,
                    height=h,
                    channels=3,
                    color_mode=original_mode,
                    bit_depth=8,
                    dpi=dpi,
                    format=fmt.lower(),
                    has_alpha=has_alpha,
                )

                arr = np.array(rgb, dtype=np.uint8)
                return [arr], props

        except UnidentifiedImageError as e:
            raise PreprocessorError(f"Cannot identify image: {e}")
        except Exception as e:
            raise PreprocessorError(f"Image load failed: {e}")

    def _load_pdf(
        self, path: Path
    ) -> tuple[list[np.ndarray], Optional[ImageProperties]]:
        """Rasterize PDF pages using pdf2image."""
        try:
            from pdf2image import convert_from_path
            from pdf2image.exceptions import PDFInfoNotInstalledError

            pages = convert_from_path(
                str(path),
                dpi=150,
                fmt="RGB",
                thread_count=2,
                use_pdftocairo=False,
                poppler_path=(
                    r"C:\poppler\Library\bin"
                    if platform.system() == "Windows"
                    else None
                )
            )

            if not pages:
                raise PreprocessorError("PDF has no renderable pages.")

            arrays = [np.array(p, dtype=np.uint8) for p in pages]
            first = pages[0]
            w, h = first.size

            props = ImageProperties(
                width=w,
                height=h,
                channels=3,
                color_mode="RGB",
                bit_depth=8,
                dpi=150.0,
                format="pdf",
                has_alpha=False,
            )

            return arrays, props

        except ImportError:
            # pdf2image not available — try PIL
            self.logger.warning(
                "pdf2image not installed; attempting PIL fallback for PDF"
            )
            return self._load_pdf_pil_fallback(path)

        except Exception as e:
            raise PreprocessorError(f"PDF rasterization failed: {e}")

    def _load_pdf_pil_fallback(
        self, path: Path
    ) -> tuple[list[np.ndarray], Optional[ImageProperties]]:
        """PIL-based PDF loading (limited, for fallback only)."""
        try:
            with Image.open(path) as img:
                arr = np.array(img.convert("RGB"), dtype=np.uint8)
                h, w = arr.shape[:2]
                props = ImageProperties(
                    width=w, height=h, channels=3, color_mode="RGB",
                    bit_depth=8, dpi=72.0, format="pdf", has_alpha=False,
                )
                return [arr], props
        except Exception as e:
            raise PreprocessorError(f"PDF PIL fallback failed: {e}")

    def _classify_document_type(
        self,
        path: Path,
        mime: str,
        props: Optional[ImageProperties],
        images: list[np.ndarray],
    ) -> DocumentType:
        """
        Classify document type using multiple signals.

        Decision logic:
        1. PDF MIME → PDF
        2. EXIF camera make/model → MOBILE_CAPTURE
        3. DPI < 120 with JPEG → SCREENSHOT or COMPUTER_GENERATED
        4. DPI > 200 → SCAN
        5. Otherwise → IMAGE
        """
        if mime == "application/pdf":
            return DocumentType.PDF

        # Try EXIF analysis
        exif_type = self._classify_from_exif(path)
        if exif_type:
            return exif_type

        if props:
            # DPI-based classification
            dpi = props.dpi or 72.0

            if dpi >= PRINT_DPI_MIN:
                # High-DPI images suggest scanned documents
                if props.format in ("tiff", "tif"):
                    return DocumentType.SCAN
                return DocumentType.SCAN

            if dpi <= SCREEN_DPI_MAX:
                # Low DPI with PNG strongly suggests screenshot
                if props.format == "png":
                    return DocumentType.SCREENSHOT
                return DocumentType.COMPUTER_GENERATED

            # Noise texture analysis for mobile vs computer
            if images:
                noise_score = self._estimate_noise_texture(images[0])
                if noise_score > 0.15:
                    return DocumentType.MOBILE_CAPTURE

        return DocumentType.IMAGE

    def _classify_from_exif(self, path: Path) -> Optional[DocumentType]:
        """Use EXIF data to detect mobile camera captures."""
        try:
            with Image.open(path) as img:
                exif_data = img._getexif()
                if not exif_data:
                    return None

                tags = {
                    ExifTags.TAGS.get(k, k): v
                    for k, v in exif_data.items()
                }

                # Camera make/model = mobile or DSLR capture
                if tags.get("Make") or tags.get("Model"):
                    return DocumentType.MOBILE_CAPTURE

        except Exception:
            pass
        return None

    def _estimate_noise_texture(self, image: np.ndarray) -> float:
        """
        Estimate sensor noise level via Laplacian variance.

        Higher = more natural camera noise (mobile/scan)
        Lower = synthetic/computer-generated
        """
        if len(image.shape) == 3:
            gray = np.mean(image, axis=2).astype(np.float32)
        else:
            gray = image.astype(np.float32)

        # Laplacian of Gaussian approximation
        # Using manual kernel for zero-dependency fallback
        kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)

        h, w = gray.shape
        if h < 3 or w < 3:
            return 0.0

        # Manual 2D convolution (edge-aware)
        from scipy.ndimage import convolve
        lap = convolve(gray, kernel)
        return float(np.std(lap) / 255.0)
