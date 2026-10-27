"""Synthetic test images. No real identity documents are used anywhere in the test suite."""

from __future__ import annotations

import cv2
import numpy as np

FONT = cv2.FONT_HERSHEY_SIMPLEX

SAMPLE_LINES = [
    "GOVERNMENT OF SAMPLELAND",
    "IDENTITY CARD SPECIMEN",
    "Name: Rahul Sharma",
    "Date of Birth: 12-05-1998",
    "Address: 21 Station Road Pune",
    "Card Number: 1234 5678 9012",
    "Issued On: 01-01-2020",
    "This specimen is synthetic test data",
    "Valid for testing purposes only",
    "Signature of issuing authority",
]


def synthetic_document(
    width: int = 1400,
    height: int = 900,
    lines: list[str] | None = None,
    noise_sigma: float = 0.0,
    seed: int = 0,
    with_photo_box: bool = False,
) -> np.ndarray:
    """A clean, printed-looking document: black text on a light background (BGR)."""
    rng = np.random.default_rng(seed)
    image = np.full((height, width, 3), 245, dtype=np.uint8)
    cv2.rectangle(image, (20, 20), (width - 21, height - 21), (60, 60, 60), 3)
    y = 90
    text_x = 420 if with_photo_box else 70
    for line in lines or SAMPLE_LINES:
        cv2.putText(image, line, (text_x, y), FONT, 1.1, (20, 20, 20), 2, cv2.LINE_AA)
        y += 75
    if with_photo_box:
        cv2.rectangle(image, (60, 120), (360, 500), (90, 90, 90), 2)
    if noise_sigma > 0:
        noisy = image.astype(np.float64) + rng.normal(0, noise_sigma, image.shape)
        image = np.clip(noisy, 0, 255).astype(np.uint8)
    return image


def blur_patch(image: np.ndarray, x: int, y: int, w: int, h: int, sigma: float = 4.0) -> np.ndarray:
    out = image.copy()
    out[y : y + h, x : x + w] = cv2.GaussianBlur(out[y : y + h, x : x + w], (0, 0), sigma)
    return out


def paste_clean_patch(noisy: np.ndarray, clean: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Simulate a splice: copy a noise-free region into a noisy capture."""
    out = noisy.copy()
    out[y : y + h, x : x + w] = clean[y : y + h, x : x + w]
    return out


def rotate(image: np.ndarray, angle: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE)


def encode(image: np.ndarray, ext: str = ".png", quality: int = 95) -> bytes:
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
    ok, buffer = cv2.imencode(ext, image, params)
    assert ok
    return buffer.tobytes()
