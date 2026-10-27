"""Shared types and helpers for the analysis modules.

Every analysis module is pure: it takes numpy arrays / dataclasses and returns ``Finding``
objects, so it can be unit-tested without Flask or a database.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field
from typing import Iterator

import cv2
import numpy as np

# MAD -> standard-deviation factor for normally distributed data.
MAD_TO_SIGMA = 1.4826


class AnalysisError(Exception):
    """Raised when an analysis step cannot run on the given input."""


class Category(str, enum.Enum):
    IMAGE_QUALITY = "image_quality"
    OCR = "ocr"
    TEXT_ALIGNMENT = "text_alignment"
    BLUR_REGIONS = "blur_regions"
    PHOTOGRAPH = "photograph"
    ALTERATION = "alteration"

    @property
    def label(self) -> str:
        return {
            "image_quality": "Image quality",
            "ocr": "Text extraction (OCR)",
            "text_alignment": "Text alignment & structure",
            "blur_regions": "Blurred / unclear regions",
            "photograph": "Photograph",
            "alteration": "Possible alterations",
        }[self.value]


class Kind(str, enum.Enum):
    """What a finding means for the decision.

    * ``indicator`` — measured evidence that *may* indicate alteration; counts towards the score.
    * ``quality``   — capture/readability problem; can make the result inconclusive but is
      never treated as evidence of fraud by itself.
    * ``info``      — context only (e.g. a check that was not applicable).
    """

    INDICATOR = "indicator"
    QUALITY = "quality"
    INFO = "info"


class Severity(str, enum.Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class Box:
    """Axis-aligned rectangle in the pixel space of the image it was measured on."""

    x: float
    y: float
    w: float
    h: float
    label: str = ""

    def corners(self) -> np.ndarray:
        return np.array(
            [
                [self.x, self.y],
                [self.x + self.w, self.y],
                [self.x + self.w, self.y + self.h],
                [self.x, self.y + self.h],
            ],
            dtype=np.float64,
        )


@dataclass
class Finding:
    """One analysis observation.

    ``evidence`` holds measured values (observations); ``description`` the interpretation;
    ``limitation`` what the measurement cannot tell us.
    """

    category: Category
    code: str
    kind: Kind
    severity: Severity
    title: str
    description: str
    evidence: dict = field(default_factory=dict)
    limitation: str | None = None
    regions: list[Box] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["category"] = self.category.value
        data["kind"] = self.kind.value
        data["severity"] = self.severity.value
        return data


@dataclass
class Tile:
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int

    def box(self, label: str = "") -> Box:
        return Box(self.x, self.y, self.w, self.h, label)


def iter_tiles(height: int, width: int, tile_size: int) -> Iterator[Tile]:
    """Yield non-overlapping tiles covering the image (edge tiles may be smaller)."""
    for row, y in enumerate(range(0, height, tile_size)):
        for col, x in enumerate(range(0, width, tile_size)):
            yield Tile(row, col, x, y, min(tile_size, width - x), min(tile_size, height - y))


def tile_size_for(shape: tuple[int, ...], tiles_on_long_side: int, min_tile: int) -> int:
    long_side = max(shape[0], shape[1])
    return max(min_tile, long_side // tiles_on_long_side)


def robust_z_scores(values: np.ndarray, min_mad: float) -> np.ndarray:
    """Median/MAD z-scores. ``min_mad`` stops near-constant data from exploding the scores."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return values
    median = np.median(values)
    mad = max(float(np.median(np.abs(values - median))), min_mad)
    return (values - median) / (MAD_TO_SIGMA * mad)


def laplacian_variance(gray: np.ndarray) -> float:
    """Variance of the Laplacian — a standard focus/sharpness measure (higher = sharper)."""
    if gray.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def ensure_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def merge_adjacent_tiles(tiles: list[Tile]) -> list[list[Tile]]:
    """Group tiles that touch (8-connectivity) so neighbouring outliers form one region."""
    remaining = {(t.row, t.col): t for t in tiles}
    groups: list[list[Tile]] = []
    while remaining:
        _, seed = remaining.popitem()
        stack, group = [seed], [seed]
        while stack:
            current = stack.pop()
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    neighbour = remaining.pop((current.row + dr, current.col + dc), None)
                    if neighbour is not None:
                        stack.append(neighbour)
                        group.append(neighbour)
        groups.append(group)
    return groups


def bounding_box(tiles: list[Tile], label: str = "") -> Box:
    x0 = min(t.x for t in tiles)
    y0 = min(t.y for t in tiles)
    x1 = max(t.x + t.w for t in tiles)
    y1 = max(t.y + t.h for t in tiles)
    return Box(x0, y0, x1 - x0, y1 - y0, label)


def round_evidence(value: float, digits: int = 2) -> float:
    return float(round(float(value), digits))
