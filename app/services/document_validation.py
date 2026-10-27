"""Server-side validation of uploaded document images.

Never trust the client: the extension, the browser-supplied MIME type and the file name are
all checked against the actual bytes, and the image is fully decoded before it is accepted.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

EXTENSION_TO_FORMAT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}
FORMAT_TO_MIME = {"JPEG": "image/jpeg", "PNG": "image/png"}
MAX_DISPLAY_NAME_LENGTH = 200


class DocumentValidationError(ValueError):
    """Upload rejected. The message is safe to show to the user."""


@dataclass(frozen=True)
class UploadLimits:
    allowed_extensions: frozenset[str]
    max_bytes: int
    min_side_px: int
    max_side_px: int
    max_pixels: int

    @classmethod
    def from_config(cls, config) -> "UploadLimits":
        return cls(
            allowed_extensions=frozenset(config["ALLOWED_EXTENSIONS"]),
            max_bytes=int(config["MAX_CONTENT_LENGTH"]),
            min_side_px=int(config["MIN_IMAGE_SIDE_PX"]),
            max_side_px=int(config["MAX_IMAGE_SIDE_PX"]),
            max_pixels=int(config["MAX_IMAGE_PIXELS"]),
        )


@dataclass(frozen=True)
class ValidatedImage:
    extension: str
    image_format: str
    mime_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str
    display_name: str


def file_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].strip().lower()


def sniff_format(data: bytes) -> str | None:
    """Identify the image format from its magic bytes (not from the name or client MIME)."""
    if data.startswith(JPEG_MAGIC):
        return "JPEG"
    if data.startswith(PNG_MAGIC):
        return "PNG"
    return None


def make_display_name(filename: str, extension: str) -> str:
    safe = secure_filename(filename or "")
    if not safe:
        safe = f"document.{extension}"
    if len(safe) > MAX_DISPLAY_NAME_LENGTH:
        safe = safe[: MAX_DISPLAY_NAME_LENGTH - len(extension) - 1] + "." + extension
    return safe


def validate_image_upload(filename: str, data: bytes, limits: UploadLimits) -> ValidatedImage:
    """Validate an uploaded image and return its verified metadata.

    Raises:
        DocumentValidationError: with a user-safe message when the upload is rejected.
    """
    if not filename:
        raise DocumentValidationError("Please choose a document image to upload.")

    extension = file_extension(filename)
    allowed = ", ".join(sorted(e.upper() for e in limits.allowed_extensions))
    if extension not in limits.allowed_extensions:
        raise DocumentValidationError(f"Unsupported file type. Allowed types: {allowed}.")

    if not data:
        raise DocumentValidationError("The uploaded file is empty.")
    if len(data) > limits.max_bytes:
        max_mb = limits.max_bytes / (1024 * 1024)
        raise DocumentValidationError(f"The file is too large. Maximum size is {max_mb:.0f} MB.")

    sniffed = sniff_format(data)
    if sniffed is None:
        raise DocumentValidationError(
            f"The file content is not a valid image. Allowed types: {allowed}."
        )
    if sniffed != EXTENSION_TO_FORMAT[extension]:
        raise DocumentValidationError(
            "The file extension does not match the file content. Please upload the original image."
        )

    width, height = _decode_and_measure(data, sniffed, limits)

    return ValidatedImage(
        extension=extension,
        image_format=sniffed,
        mime_type=FORMAT_TO_MIME[sniffed],
        width=width,
        height=height,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        display_name=make_display_name(filename, extension),
    )


def _decode_and_measure(data: bytes, expected_format: str, limits: UploadLimits) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            # Header-only read: check size BEFORE decoding pixels (decompression-bomb guard).
            width, height = probe.size
            if probe.format != expected_format:
                raise DocumentValidationError("The file content does not match a supported image.")
            if width * height > limits.max_pixels:
                raise DocumentValidationError("The image resolution is too large to process.")
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()  # full decode: catches truncated / corrupt data verify() can miss
    except DocumentValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError):
        raise DocumentValidationError(
            "The image could not be read. It may be corrupted or incomplete."
        ) from None

    if min(width, height) < limits.min_side_px:
        raise DocumentValidationError(
            f"The image is too small ({width}×{height} px). Each side must be at least "
            f"{limits.min_side_px} px for the text and photo to be analysed."
        )
    if max(width, height) > limits.max_side_px:
        raise DocumentValidationError("The image dimensions are too large to process.")
    return width, height
