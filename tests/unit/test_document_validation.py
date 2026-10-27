import io

import numpy as np
import pytest
from PIL import Image

from app.services.document_validation import (
    DocumentValidationError,
    UploadLimits,
    make_display_name,
    sniff_format,
    validate_image_upload,
)
from tests.helpers import encode, synthetic_document

LIMITS = UploadLimits(
    allowed_extensions=frozenset({"jpg", "jpeg", "png"}),
    max_bytes=2 * 1024 * 1024,
    min_side_px=300,
    max_side_px=12000,
    max_pixels=50_000_000,
)


def test_valid_png_accepted():
    data = encode(synthetic_document())
    result = validate_image_upload("card.png", data, LIMITS)
    assert result.mime_type == "image/png"
    assert (result.width, result.height) == (1400, 900)
    assert len(result.sha256) == 64


def test_valid_jpeg_accepted_with_uppercase_extension():
    data = encode(synthetic_document(), ".jpg", 90)
    result = validate_image_upload("PHOTO.JPG", data, LIMITS)
    assert result.image_format == "JPEG"


@pytest.mark.parametrize("name", ["card.gif", "card.pdf", "card", "card.png.exe", "card.svg"])
def test_unsupported_extension_rejected(name):
    with pytest.raises(DocumentValidationError, match="Unsupported file type"):
        validate_image_upload(name, encode(synthetic_document()), LIMITS)


def test_empty_file_rejected():
    with pytest.raises(DocumentValidationError, match="empty"):
        validate_image_upload("card.png", b"", LIMITS)


def test_oversized_file_rejected():
    with pytest.raises(DocumentValidationError, match="too large"):
        validate_image_upload("card.png", b"\x89PNG\r\n\x1a\n" + b"0" * (LIMITS.max_bytes + 1), LIMITS)


def test_non_image_content_with_image_extension_rejected():
    with pytest.raises(DocumentValidationError, match="not a valid image"):
        validate_image_upload("card.jpg", b"<html><script>alert(1)</script></html>", LIMITS)


def test_extension_content_mismatch_rejected():
    png = encode(synthetic_document())
    with pytest.raises(DocumentValidationError, match="does not match"):
        validate_image_upload("card.jpg", png, LIMITS)


def test_truncated_image_rejected():
    data = encode(synthetic_document(), ".jpg", 90)
    with pytest.raises(DocumentValidationError, match="could not be read"):
        validate_image_upload("card.jpg", data[: len(data) // 3], LIMITS)


def test_corrupted_png_rejected():
    data = bytearray(encode(synthetic_document()))
    data[100:400] = b"\x00" * 300
    with pytest.raises(DocumentValidationError):
        validate_image_upload("card.png", bytes(data), LIMITS)


def test_too_small_image_rejected():
    small = encode(np.full((200, 250, 3), 200, np.uint8))
    with pytest.raises(DocumentValidationError, match="too small"):
        validate_image_upload("card.png", small, LIMITS)


def test_pixel_bomb_rejected_before_decoding():
    limits = UploadLimits(LIMITS.allowed_extensions, LIMITS.max_bytes, 300, 12000, max_pixels=1_000_000)
    buffer = io.BytesIO()
    Image.new("L", (2000, 2000), 255).save(buffer, "PNG")  # compresses to a few KB
    with pytest.raises(DocumentValidationError, match="resolution is too large"):
        validate_image_upload("bomb.png", buffer.getvalue(), limits)


def test_sniff_format():
    assert sniff_format(b"\xff\xd8\xff\xe0rest") == "JPEG"
    assert sniff_format(b"\x89PNG\r\n\x1a\nrest") == "PNG"
    assert sniff_format(b"GIF89a") is None


@pytest.mark.parametrize(
    "raw, expected",
    [("../../etc/passwd.png", "etc_passwd.png"), ("..\\..\\win.png", "win.png"), ("", "document.png")],
)
def test_display_name_is_sanitised(raw, expected):
    name = make_display_name(raw, "png")
    assert "/" not in name and "\\" not in name and ".." not in name
    assert name == expected
