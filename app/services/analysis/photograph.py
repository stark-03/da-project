"""Photograph quality and consistency (SRS slides 4, 8, 10: "photograph quality and possible
alterations").

The holder's photo is located with OpenCV's bundled Haar frontal-face detector, then compared
with the rest of the document:

* photo blur (quality),
* photo sharpness vs the document's printed content (a photo swapped in from another source
  often has very different sharpness),
* photo noise level vs the document's noise level.

Not every document has a photo (e.g. rental agreements), so "no face found" is informational.
"""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np

from . import thresholds as T
from .alteration import NoiseMap, noise_residual_and_flat_mask
from .blur_regions import SharpnessMap, region_sharpness
from .common import Box, Category, Finding, Kind, Severity, laplacian_variance, round_evidence

HAAR_SCALE_FACTOR = 1.1
HAAR_MIN_NEIGHBORS = 6


@lru_cache(maxsize=1)
def _face_detector() -> cv2.CascadeClassifier:
    path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(path)
    if detector.empty():
        raise RuntimeError("OpenCV face detector model could not be loaded")
    return detector


def detect_faces(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    min_side = int(min(gray.shape[:2]) * T.FACE_MIN_SIZE_RATIO)
    faces = _face_detector().detectMultiScale(
        gray,
        scaleFactor=HAAR_SCALE_FACTOR,
        minNeighbors=HAAR_MIN_NEIGHBORS,
        minSize=(min_side, min_side),
    )
    return [tuple(int(v) for v in face) for face in faces]


def photo_box_from_face(face: tuple[int, int, int, int], shape: tuple[int, ...]) -> Box:
    """Expand a face box to approximate the printed passport-style photo around it."""
    x, y, w, h = face
    cx, cy = x + w / 2, y + h / 2
    half_w = w * T.PHOTO_BOX_EXPANSION / 2
    half_h = h * T.PHOTO_BOX_EXPANSION / 2
    x0, y0 = max(0, int(cx - half_w)), max(0, int(cy - half_h))
    x1, y1 = min(shape[1], int(cx + half_w)), min(shape[0], int(cy + half_h))
    return Box(x0, y0, x1 - x0, y1 - y0, "Photograph")


def region_noise_sigma(gray_region: np.ndarray) -> float | None:
    if gray_region.size == 0:
        return None
    residual, flat = noise_residual_and_flat_mask(gray_region)
    if int(flat.sum()) < T.NOISE_MIN_FLAT_PIXELS:
        return None
    return float(residual[flat].std())


def assess_photo_region(
    gray: np.ndarray,
    box: Box,
    document_sharpness: float | None,
    document_noise: float | None,
) -> list[Finding]:
    """Compare one photo region with document-wide sharpness and noise statistics."""
    region = gray[int(box.y) : int(box.y + box.h), int(box.x) : int(box.x + box.w)]
    blur_var = laplacian_variance(region)
    sharpness = region_sharpness(region)
    noise = region_noise_sigma(region)

    evidence = {
        "photo_box_px": [int(box.x), int(box.y), int(box.w), int(box.h)],
        "photo_laplacian_variance": round_evidence(blur_var),
        "photo_edge_sharpness": round_evidence(sharpness, 3) if sharpness is not None else None,
        "document_edge_sharpness": round_evidence(document_sharpness, 3) if document_sharpness else None,
        "photo_noise_sigma": round_evidence(noise, 3) if noise is not None else None,
        "document_noise_sigma": round_evidence(document_noise, 3) if document_noise else None,
    }
    findings: list[Finding] = []

    if blur_var < T.PHOTO_BLUR_LAPLACIAN_MIN:
        findings.append(
            Finding(
                category=Category.PHOTOGRAPH,
                code="photo_blurry",
                kind=Kind.QUALITY,
                severity=Severity.LOW,
                title="Photograph is blurry",
                description="The holder's photo is not sharp enough to inspect facial detail.",
                evidence={**evidence, "minimum_expected": T.PHOTO_BLUR_LAPLACIAN_MIN},
                limitation="Printed ID photos are often soft; this alone does not indicate tampering.",
                regions=[Box(box.x, box.y, box.w, box.h, "Blurry photograph")],
            )
        )

    if sharpness is not None and document_sharpness:
        ratio = sharpness / document_sharpness
        evidence["sharpness_ratio"] = round_evidence(ratio)
        if ratio < T.PHOTO_SHARPNESS_RATIO_LOW or ratio > T.PHOTO_SHARPNESS_RATIO_HIGH:
            findings.append(
                Finding(
                    category=Category.PHOTOGRAPH,
                    code="photo_sharpness_mismatch",
                    kind=Kind.INDICATOR,
                    severity=Severity.LOW,
                    title="Photograph sharpness differs strongly from the document",
                    description=(
                        "The photo is much sharper or much softer than the printed text around it. "
                        "A photo replaced with one from another source can show this difference."
                    ),
                    evidence={
                        **evidence,
                        "expected_ratio_range": [T.PHOTO_SHARPNESS_RATIO_LOW, T.PHOTO_SHARPNESS_RATIO_HIGH],
                    },
                    limitation="Photo printing methods (dithering, lamination) differ from text printing on genuine cards too.",
                    regions=[Box(box.x, box.y, box.w, box.h, "Photo sharpness mismatch")],
                )
            )

    if noise is not None and document_noise:
        ratio = (noise + 0.1) / (document_noise + 0.1)
        evidence["noise_ratio"] = round_evidence(ratio)
        if ratio < T.PHOTO_NOISE_RATIO_LOW or ratio > T.PHOTO_NOISE_RATIO_HIGH:
            findings.append(
                Finding(
                    category=Category.PHOTOGRAPH,
                    code="photo_noise_mismatch",
                    kind=Kind.INDICATOR,
                    severity=Severity.LOW,
                    title="Photograph noise differs from the document",
                    description=(
                        "The image noise inside the photo differs from the rest of the capture, "
                        "which can happen when a photo is digitally inserted."
                    ),
                    evidence={**evidence, "expected_ratio_range": [T.PHOTO_NOISE_RATIO_LOW, T.PHOTO_NOISE_RATIO_HIGH]},
                    limitation="Skin tones and photo backgrounds are smoother than paper texture on many genuine cards.",
                    regions=[Box(box.x, box.y, box.w, box.h, "Photo noise mismatch")],
                )
            )

    if not findings:
        findings.append(
            Finding(
                category=Category.PHOTOGRAPH,
                code="photo_consistent",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Photograph quality is consistent with the document",
                description="The photo is reasonably sharp and its sharpness and noise match the rest of the capture.",
                evidence=evidence,
                limitation="Face identity is not verified — this check cannot tell whose photo it is.",
                regions=[Box(box.x, box.y, box.w, box.h, "Photograph")],
            )
        )
    return findings


def analyze_photograph(
    gray: np.ndarray, sharpness_map: SharpnessMap, noise_map: NoiseMap
) -> list[Finding]:
    faces = detect_faces(gray)
    if not faces:
        return [
            Finding(
                category=Category.PHOTOGRAPH,
                code="photo_not_found",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="No photograph detected",
                description=(
                    "No face photo was found, so photo checks were not performed. This is expected "
                    "for documents without a photo, such as rental agreements."
                ),
                limitation="Very small, rotated, partially covered or low-contrast photos may be missed.",
            )
        ]

    largest = max(faces, key=lambda f: f[2] * f[3])
    box = photo_box_from_face(largest, gray.shape)
    findings = assess_photo_region(gray, box, sharpness_map.median, noise_map.median)
    if len(faces) > 1:
        findings.append(
            Finding(
                category=Category.PHOTOGRAPH,
                code="multiple_faces",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="More than one face detected",
                description="Only the largest photo was analysed. Some cards carry a second small 'ghost' photo.",
                evidence={"faces_detected": len(faces)},
            )
        )
    return findings
