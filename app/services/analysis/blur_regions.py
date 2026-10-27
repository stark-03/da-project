"""Blurred, unclear or inconsistent regions (SRS slides 8 & 10: "Check blurred, unclear or
inconsistent regions").

Idea: on a genuine single-capture document all printed content shares roughly the same edge
sharpness. A tile is flagged when it is a strong statistical outlier (robust z-score) AND at
least ``BLUR_REGION_MEDIAN_RATIO`` times blurrier than the document median. A region that is much blurrier than its surroundings can come from smudging,
re-printing, or pasting in lower-resolution content.

Sharpness measure per tile: ``sum(|Laplacian|) / sum(|gradient|)`` over edge pixels. Both terms
scale with contrast and with the amount of text in the tile, so their ratio mostly reflects
*edge width* (blur), not how much ink the tile contains.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import thresholds as T
from .common import (
    Category,
    Finding,
    Kind,
    Severity,
    Tile,
    bounding_box,
    iter_tiles,
    merge_adjacent_tiles,
    robust_z_scores,
    round_evidence,
    tile_size_for,
)

@dataclass
class SharpnessMap:
    tile_size: int
    tiles: list[Tile] = field(default_factory=list)
    sharpness: dict[tuple[int, int], float] = field(default_factory=dict)

    @property
    def median(self) -> float | None:
        return float(np.median(list(self.sharpness.values()))) if self.sharpness else None


@dataclass
class BlurRegionAnalysis:
    findings: list[Finding]
    sharpness_map: SharpnessMap


def gradient_images(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    gray_f = gray.astype(np.float64)
    gx = cv2.Sobel(gray_f, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray_f, cv2.CV_64F, 0, 1, ksize=3)
    # Sobel ksize=3 has gain 4 relative to a unit-step gradient; normalise to gray-level units.
    gradient = np.hypot(gx, gy) / 4.0
    laplacian = np.abs(cv2.Laplacian(gray_f, cv2.CV_64F, ksize=3))
    return gradient, laplacian


def edge_sharpness(gradient: np.ndarray, laplacian: np.ndarray) -> float | None:
    mask = gradient >= T.EDGE_GRADIENT_MIN
    if int(mask.sum()) < T.MIN_EDGE_PIXELS:
        return None
    return float(laplacian[mask].sum() / gradient[mask].sum())


def compute_sharpness_map(gray: np.ndarray) -> SharpnessMap:
    size = tile_size_for(gray.shape, T.TILES_ON_LONG_SIDE, T.MIN_TILE_PX)
    gradient, laplacian = gradient_images(gray)
    result = SharpnessMap(tile_size=size)
    for tile in iter_tiles(gray.shape[0], gray.shape[1], size):
        window = (slice(tile.y, tile.y + tile.h), slice(tile.x, tile.x + tile.w))
        value = edge_sharpness(gradient[window], laplacian[window])
        if value is not None:
            result.tiles.append(tile)
            result.sharpness[(tile.row, tile.col)] = value
    return result


def region_sharpness(gray: np.ndarray) -> float | None:
    gradient, laplacian = gradient_images(gray)
    return edge_sharpness(gradient, laplacian)


def analyze_blur_regions(gray: np.ndarray, globally_blurry: bool) -> BlurRegionAnalysis:
    sharpness_map = compute_sharpness_map(gray)

    if globally_blurry:
        return BlurRegionAnalysis(
            [
                Finding(
                    category=Category.BLUR_REGIONS,
                    code="blur_regions_skipped",
                    kind=Kind.INFO,
                    severity=Severity.NONE,
                    title="Local blur check skipped",
                    description="The whole image is blurry, so locally blurred regions cannot be distinguished.",
                    limitation="Retake the photo in focus to enable this check.",
                )
            ],
            sharpness_map,
        )

    tiles = sharpness_map.tiles
    if len(tiles) < T.MIN_TILES_FOR_STATISTICS:
        return BlurRegionAnalysis(
            [
                Finding(
                    category=Category.BLUR_REGIONS,
                    code="blur_regions_insufficient_content",
                    kind=Kind.INFO,
                    severity=Severity.NONE,
                    title="Not enough printed content to compare regions",
                    description="Too few regions contain text or graphics for a reliable local comparison.",
                    evidence={"content_tiles": len(tiles), "minimum": T.MIN_TILES_FOR_STATISTICS},
                )
            ],
            sharpness_map,
        )

    keys = [(t.row, t.col) for t in tiles]
    values = np.array([sharpness_map.sharpness[k] for k in keys])
    z_scores = robust_z_scores(np.log(values), T.BLUR_REGION_MIN_MAD)

    median = float(np.median(values))
    flagged: list[Tile] = []
    flagged_details: list[dict] = []
    for tile, value, z in zip(tiles, values, z_scores):
        if z > T.BLUR_REGION_Z_THRESHOLD or median < T.BLUR_REGION_MEDIAN_RATIO * value:
            continue
        flagged.append(tile)
        flagged_details.append(
            {
                "tile": [tile.x, tile.y, tile.w, tile.h],
                "sharpness": round_evidence(value, 3),
                "robust_z": round_evidence(z),
                "times_blurrier_than_median": round_evidence(median / value),
            }
        )

    if not flagged:
        return BlurRegionAnalysis(
            [
                Finding(
                    category=Category.BLUR_REGIONS,
                    code="blur_regions_consistent",
                    kind=Kind.INFO,
                    severity=Severity.NONE,
                    title="Sharpness is consistent across the document",
                    description="No region was found to be much blurrier than the surrounding printed content.",
                    evidence={
                        "content_tiles_compared": len(tiles),
                        "median_edge_sharpness": round_evidence(median, 3),
                    },
                    limitation="Very careful edits that match the original sharpness are not detected by this check.",
                )
            ],
            sharpness_map,
        )

    findings: list[Finding] = []
    for group in merge_adjacent_tiles(flagged):
        severity = Severity.MEDIUM if len(group) >= T.BLUR_REGION_MEDIUM_TILE_COUNT else Severity.LOW
        group_xy = {(t.x, t.y) for t in group}
        findings.append(
            Finding(
                category=Category.BLUR_REGIONS,
                code="localized_blur",
                kind=Kind.INDICATOR,
                severity=severity,
                title="Region much blurrier than its surroundings",
                description=(
                    "Printed content in this area is markedly less sharp than neighbouring content "
                    "captured in the same photo. This can indicate smudging, re-printed or pasted-in content."
                ),
                evidence={
                    "tiles": [d for d in flagged_details if (d["tile"][0], d["tile"][1]) in group_xy],
                    "tile_count": len(group),
                    "document_median_sharpness": round_evidence(median, 3),
                    "z_threshold": T.BLUR_REGION_Z_THRESHOLD,
                },
                limitation=(
                    "Also caused by uneven focus, glare, a fold or a stamp/hologram. Inspect the "
                    "highlighted area on the physical document."
                ),
                regions=[bounding_box(group, "Unusually blurred region")],
            )
        )
    return BlurRegionAnalysis(findings, sharpness_map)
