import io

import cv2
import numpy as np
import pytest
from PIL import Image

from app.services.analysis.common import AnalysisError, Box
from app.services.image_preprocessing import (
    estimate_skew_angle,
    load_image,
    map_box_to_original,
    preprocess,
    scale_factor_for,
)
from tests.helpers import encode, rotate, synthetic_document


def test_original_is_not_modified():
    original = synthetic_document(noise_sigma=3)
    snapshot = original.copy()
    preprocess(original)
    assert np.array_equal(original, snapshot)


@pytest.mark.parametrize("angle", [-4.0, -2.0, 3.0, 6.0])
def test_skew_is_estimated(angle):
    image = cv2.cvtColor(rotate(synthetic_document(), angle), cv2.COLOR_BGR2GRAY)
    assert abs(estimate_skew_angle(image) - (-angle)) <= 0.5


def test_scale_factor_normalises_long_side():
    assert scale_factor_for(4000, 3000) == pytest.approx(1600 / 4000)
    assert scale_factor_for(600, 400) == pytest.approx(1000 / 600)
    assert scale_factor_for(1400, 900) == 1.0


def test_box_maps_back_to_original_coordinates():
    original = cv2.resize(synthetic_document(), None, fx=2.5, fy=2.5)  # 3500 x 2250 -> scaled down
    prepared = preprocess(original)
    box = Box(100, 100, 50, 40)
    space = prepared.to_normalized
    mapped = map_box_to_original(box, space, prepared.original_size)
    # Round trip: map the mapped box forward again and compare with the input box.
    corners = np.array([[mapped.x, mapped.y], [mapped.x + mapped.w, mapped.y + mapped.h]], dtype=np.float64)
    forward = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), space).reshape(-1, 2)
    assert forward[0] == pytest.approx([100, 100], abs=2)
    assert forward[1] == pytest.approx([150, 140], abs=2)


def test_exif_orientation_is_applied():
    image = Image.fromarray(np.full((400, 800, 3), 200, np.uint8))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise on display
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", exif=exif.tobytes())
    decoded = load_image(buffer.getvalue())
    assert decoded.shape[:2] == (800, 400)


def test_transparent_png_flattened_on_white():
    rgba = np.zeros((400, 400, 4), np.uint8)  # fully transparent
    buffer = io.BytesIO()
    Image.fromarray(rgba).save(buffer, "PNG")
    decoded = load_image(buffer.getvalue())
    assert decoded.mean() == pytest.approx(255)


def test_invalid_bytes_raise_analysis_error():
    with pytest.raises(AnalysisError):
        load_image(b"not an image")


def test_ocr_image_is_grayscale_and_document_outline_detected():
    background = np.full((1200, 1800, 3), (40, 90, 40), np.uint8)  # document photographed on a table
    background[150:1050, 200:1600] = synthetic_document()
    prepared = preprocess(cv2.imdecode(np.frombuffer(encode(background), np.uint8), 1))
    assert prepared.ocr_gray.ndim == 2
    assert prepared.document_cropped is True
