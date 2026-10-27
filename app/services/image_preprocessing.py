"""Image preprocessing (SRS slide 5, step 2: resizing, noise removal, enhancement, conversion).

Produces two working images and never modifies the original:

* ``normalized``  — scaled (and perspective-cropped if a document outline is found). Used by
  the forensic checks (blur regions, noise, ELA, photo). It is deliberately NOT denoised:
  denoising would erase the noise patterns those checks measure.
* ``ocr_gray``    — ``normalized`` + deskew + denoise + contrast enhancement, for Tesseract
  and the text-alignment check.

Each working image carries a 3x3 matrix mapping original-image pixels into its own space, so
boxes found by any analysis can be mapped back to the original for highlighting.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps

from .analysis import thresholds as T
from .analysis.common import AnalysisError, Box

# Canny / contour parameters for the document-outline search.
CANNY_LOW = 50
CANNY_HIGH = 150
CONTOUR_CANDIDATES = 5
POLY_APPROX_EPSILON = 0.02  # fraction of contour perimeter
# Non-local-means strength for OCR denoising (OpenCV's recommended range is ~3-10).
DENOISE_STRENGTH = 7
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID = (8, 8)


@dataclass
class PreprocessedImage:
    original: np.ndarray  # BGR, orientation-corrected, never modified
    normalized: np.ndarray  # BGR
    normalized_gray: np.ndarray
    ocr_gray: np.ndarray
    to_normalized: np.ndarray  # 3x3: original -> normalized
    to_ocr: np.ndarray  # 3x3: original -> ocr_gray
    scale: float
    document_cropped: bool
    deskew_angle_deg: float
    steps: list[str] = field(default_factory=list)

    @property
    def original_size(self) -> tuple[int, int]:
        """(width, height) of the orientation-corrected original."""
        return int(self.original.shape[1]), int(self.original.shape[0])


def load_image(data: bytes) -> np.ndarray:
    """Decode image bytes to BGR, applying EXIF orientation (phone photos) and flattening alpha.

    Browsers also honour EXIF orientation when displaying the image, so coordinates computed
    here line up with the on-screen preview.
    """
    try:
        with Image.open(io.BytesIO(data)) as pil:
            pil = ImageOps.exif_transpose(pil)
            if pil.mode in ("RGBA", "LA") or (pil.mode == "P" and "transparency" in pil.info):
                rgba = pil.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                rgb = background
            else:
                rgb = pil.convert("RGB")
            array = np.asarray(rgb, dtype=np.uint8)
    except (OSError, ValueError) as exc:
        raise AnalysisError("The stored image could not be decoded.") from exc
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def scale_factor_for(width: int, height: int) -> float:
    long_side = max(width, height)
    if long_side > T.ANALYSIS_LONG_SIDE_MAX_PX:
        return T.ANALYSIS_LONG_SIDE_MAX_PX / long_side
    if long_side < T.ANALYSIS_LONG_SIDE_MIN_PX:
        return T.ANALYSIS_LONG_SIDE_MIN_PX / long_side
    return 1.0


def scale_matrix(factor: float) -> np.ndarray:
    return np.array([[factor, 0, 0], [0, factor, 0], [0, 0, 1]], dtype=np.float64)


def order_quad(points: np.ndarray) -> np.ndarray:
    """Order 4 points as top-left, top-right, bottom-right, bottom-left."""
    pts = points.reshape(4, 2).astype(np.float32)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(sums)], pts[np.argmin(diffs)], pts[np.argmax(sums)], pts[np.argmax(diffs)]],
        dtype=np.float32,
    )


def find_document_quad(gray: np.ndarray) -> np.ndarray | None:
    """Find the outline of a document photographed on a background, if there is one."""
    image_area = gray.shape[0] * gray.shape[1]
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, CANNY_LOW, CANNY_HIGH)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:CONTOUR_CANDIDATES]:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, POLY_APPROX_EPSILON * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        ratio = cv2.contourArea(approx) / image_area
        if T.DOCUMENT_QUAD_MIN_AREA_RATIO <= ratio <= T.DOCUMENT_QUAD_MAX_AREA_RATIO:
            return order_quad(approx)
    return None


def perspective_matrix(quad: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    tl, tr, br, bl = quad
    width = int(round(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl))))
    height = int(round(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl))))
    target = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32
    )
    return cv2.getPerspectiveTransform(quad, target).astype(np.float64), (width, height)


def estimate_skew_angle(gray: np.ndarray) -> float:
    """Estimate the rotation (degrees, OpenCV sign convention) that makes text lines horizontal.

    Projection-profile method: rotate a binarised thumbnail through candidate angles and keep
    the one whose row-sum profile has the sharpest transitions (text lines aligned to rows).
    """
    factor = min(1.0, T.DESKEW_SEARCH_LONG_SIDE_PX / max(gray.shape))
    small = cv2.resize(gray, None, fx=factor, fy=factor, interpolation=cv2.INTER_AREA)
    _, binary = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    height, width = binary.shape
    center = (width / 2, height / 2)

    best_angle, best_score = 0.0, -1.0
    steps = int(round(T.DESKEW_MAX_ANGLE_DEG / T.DESKEW_STEP_DEG))
    for i in range(-steps, steps + 1):
        angle = i * T.DESKEW_STEP_DEG
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(binary, matrix, (width, height), flags=cv2.INTER_NEAREST)
        profile = rotated.sum(axis=1, dtype=np.float64)
        score = float(np.sum(np.diff(profile) ** 2))
        if score > best_score:
            best_angle, best_score = angle, score
    return best_angle


def rotation_matrix_expanded(shape: tuple[int, int], angle: float) -> tuple[np.ndarray, tuple[int, int]]:
    """3x3 rotation about the centre with the canvas enlarged so no corner is cut off."""
    height, width = shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_w = int(round(height * sin + width * cos))
    new_h = int(round(height * cos + width * sin))
    matrix[0, 2] += new_w / 2 - width / 2
    matrix[1, 2] += new_h / 2 - height / 2
    return np.vstack([matrix, [0, 0, 1]]), (new_w, new_h)


def enhance_for_ocr(gray: np.ndarray) -> np.ndarray:
    denoised = cv2.fastNlMeansDenoising(gray, None, h=DENOISE_STRENGTH)
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_TILE_GRID)
    return clahe.apply(denoised)


def preprocess(original: np.ndarray) -> PreprocessedImage:
    """Run the preprocessing chain on an orientation-corrected BGR image."""
    if original is None or original.ndim != 3 or original.size == 0:
        raise AnalysisError("Image data is empty or not a colour image.")

    height, width = original.shape[:2]
    steps: list[str] = []

    factor = scale_factor_for(width, height)
    to_normalized = scale_matrix(factor)
    if factor != 1.0:
        interpolation = cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC
        normalized = cv2.resize(original, None, fx=factor, fy=factor, interpolation=interpolation)
        steps.append(f"Resized by {factor:.2f}× for consistent analysis")
    else:
        normalized = original.copy()

    cropped = False
    quad = find_document_quad(cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY))
    if quad is not None:
        warp, (warp_w, warp_h) = perspective_matrix(quad)
        normalized = cv2.warpPerspective(normalized, warp, (warp_w, warp_h), flags=cv2.INTER_CUBIC)
        to_normalized = warp @ to_normalized
        cropped = True
        steps.append("Detected document outline and corrected perspective")

    normalized_gray = cv2.cvtColor(normalized, cv2.COLOR_BGR2GRAY)

    angle = estimate_skew_angle(normalized_gray)
    to_ocr = to_normalized.copy()
    ocr_source = normalized_gray
    if abs(angle) >= T.DESKEW_MIN_CORRECTION_DEG:
        rotation, (rot_w, rot_h) = rotation_matrix_expanded(normalized_gray.shape, angle)
        ocr_source = cv2.warpAffine(
            normalized_gray,
            rotation[:2],
            (rot_w, rot_h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )
        to_ocr = rotation @ to_normalized
        steps.append(f"Corrected skew of {angle:+.1f}°")
    else:
        angle = 0.0

    ocr_gray = enhance_for_ocr(ocr_source)
    steps.append("Converted to grayscale, removed noise and enhanced contrast for OCR")

    return PreprocessedImage(
        original=original,
        normalized=normalized,
        normalized_gray=normalized_gray,
        ocr_gray=ocr_gray,
        to_normalized=to_normalized,
        to_ocr=to_ocr,
        scale=factor,
        document_cropped=cropped,
        deskew_angle_deg=float(angle),
        steps=steps,
    )


def map_box_to_original(box: Box, to_space: np.ndarray, original_size: tuple[int, int]) -> Box:
    """Map a box from a working image back to original-image pixels (clipped to the image)."""
    inverse = np.linalg.inv(to_space)
    corners = box.corners().reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(corners, inverse).reshape(-1, 2)
    width, height = original_size
    x0 = float(np.clip(mapped[:, 0].min(), 0, width))
    y0 = float(np.clip(mapped[:, 1].min(), 0, height))
    x1 = float(np.clip(mapped[:, 0].max(), 0, width))
    y1 = float(np.clip(mapped[:, 1].max(), 0, height))
    return Box(round(x0, 1), round(y0, 1), round(x1 - x0, 1), round(y1 - y0, 1), box.label)
