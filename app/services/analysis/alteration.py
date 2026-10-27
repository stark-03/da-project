"""Possible-alteration indicators (SRS slides 5, 8, 10: "possible alterations",
"digital manipulations").

Two established, explainable image-forensics measurements:

1. **Noise-level inconsistency.** A single camera capture has a fairly uniform noise level.
   Content pasted from another source (or digitally drawn) usually has a different noise level.
   Noise is estimated per tile on *flat* pixels only (low gradient), so text edges do not
   dominate the estimate.
2. **Error level analysis (ELA), JPEG only.** The image is re-saved at a known JPEG quality and
   the difference measured. Regions with a different compression history (e.g. pasted after the
   original was saved) often show a different error level.

Both produce *indicators*, not proof: glare, shadows, stamps, holograms and printing processes
can produce similar statistics.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from . import thresholds as T
from .blur_regions import gradient_images
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

LOG_EPSILON = 0.1  # added before log() so zero-noise tiles stay finite


@dataclass
class NoiseMap:
    tile_size: int
    tiles: list[Tile]
    sigma: dict[tuple[int, int], float]

    @property
    def median(self) -> float | None:
        return float(np.median(list(self.sigma.values()))) if self.sigma else None


def noise_residual_and_flat_mask(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median-filter residual (≈ noise) and a mask of flat pixels away from edges."""
    residual = gray.astype(np.float64) - cv2.medianBlur(gray, 3).astype(np.float64)
    gradient, _ = gradient_images(gray)
    kernel_size = 2 * T.NOISE_EDGE_EXCLUSION_PX + 1
    near_edge = cv2.dilate(
        (gradient >= T.EDGE_GRADIENT_MIN).astype(np.uint8), np.ones((kernel_size, kernel_size), np.uint8)
    ).astype(bool)
    flat = (gradient <= np.percentile(gradient, T.NOISE_FLAT_PERCENTILE)) & ~near_edge
    return residual, flat


def estimate_noise_map(gray: np.ndarray) -> NoiseMap:
    """Per-tile noise sigma measured on flat pixels (away from text edges)."""
    residual, flat = noise_residual_and_flat_mask(gray)

    size = tile_size_for(gray.shape, T.TILES_ON_LONG_SIDE, T.MIN_TILE_PX)
    tiles: list[Tile] = []
    sigma: dict[tuple[int, int], float] = {}
    for tile in iter_tiles(gray.shape[0], gray.shape[1], size):
        window = (slice(tile.y, tile.y + tile.h), slice(tile.x, tile.x + tile.w))
        mask = flat[window]
        if int(mask.sum()) < T.NOISE_MIN_FLAT_PIXELS:
            continue
        tiles.append(tile)
        sigma[(tile.row, tile.col)] = float(residual[window][mask].std())
    return NoiseMap(size, tiles, sigma)


def _outlier_tiles(
    tiles: list[Tile],
    values: dict[tuple[int, int], float],
    z_threshold: float,
    min_mad: float,
    min_ratio: float,
    high_only: bool,
    min_abs_diff: float = 0.0,
) -> tuple[list[Tile], list[dict], float]:
    keys = [(t.row, t.col) for t in tiles]
    raw = np.array([values[k] for k in keys])
    z_scores = robust_z_scores(np.log(raw + LOG_EPSILON), min_mad)
    median = float(np.median(raw))
    flagged, details = [], []
    for tile, value, z in zip(tiles, raw, z_scores):
        if high_only and z < z_threshold:
            continue
        if not high_only and abs(z) < z_threshold:
            continue
        ratio = (value + LOG_EPSILON) / (median + LOG_EPSILON)
        if max(ratio, 1 / ratio) < min_ratio or abs(value - median) < min_abs_diff:
            continue
        flagged.append(tile)
        details.append(
            {
                "tile": [tile.x, tile.y, tile.w, tile.h],
                "value": round_evidence(value, 3),
                "robust_z": round_evidence(z),
                "ratio_to_median": round_evidence(ratio),
            }
        )
    return flagged, details, median


def analyze_noise_consistency(gray: np.ndarray, noise_map: NoiseMap | None = None) -> list[Finding]:
    noise_map = noise_map or estimate_noise_map(gray)
    if len(noise_map.tiles) < T.MIN_TILES_FOR_STATISTICS:
        return [
            Finding(
                category=Category.ALTERATION,
                code="noise_check_insufficient_area",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Noise consistency check not possible",
                description="Too few flat background areas to estimate image noise reliably.",
                evidence={"usable_tiles": len(noise_map.tiles), "minimum": T.MIN_TILES_FOR_STATISTICS},
            )
        ]

    flagged, details, median = _outlier_tiles(
        noise_map.tiles,
        noise_map.sigma,
        T.NOISE_Z_THRESHOLD,
        T.NOISE_MIN_MAD,
        T.NOISE_MIN_RATIO,
        high_only=False,
        min_abs_diff=T.NOISE_MIN_ABS_DIFF,
    )
    if not flagged:
        return [
            Finding(
                category=Category.ALTERATION,
                code="noise_consistent",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Image noise is consistent",
                description="No region has a noise level that stands out from the rest of the image.",
                evidence={"tiles_compared": len(noise_map.tiles), "median_noise_sigma": round_evidence(median, 3)},
                limitation="Edits re-captured by photographing a printout can have uniform noise and are not detected.",
            )
        ]

    findings = []
    for group in merge_adjacent_tiles(flagged):
        xy = {(t.x, t.y) for t in group}
        severity = Severity.MEDIUM if len(group) >= T.NOISE_MEDIUM_TILE_COUNT else Severity.LOW
        findings.append(
            Finding(
                category=Category.ALTERATION,
                code="noise_inconsistency",
                kind=Kind.INDICATOR,
                severity=severity,
                title="Region with inconsistent image noise",
                description=(
                    "The noise level in this area differs strongly from the rest of the capture. "
                    "Content pasted from another image, or digitally drawn, often shows this pattern."
                ),
                evidence={
                    "tiles": [d for d in details if (d["tile"][0], d["tile"][1]) in xy],
                    "tile_count": len(group),
                    "median_noise_sigma": round_evidence(median, 3),
                    "z_threshold": T.NOISE_Z_THRESHOLD,
                },
                limitation=(
                    "Glare, deep shadow, holograms, laminate reflections and solid printed areas "
                    "can also change measured noise."
                ),
                regions=[bounding_box(group, "Inconsistent noise level")],
            )
        )
    return findings


def error_level_map(original_bgr: np.ndarray, quality: int = T.ELA_JPEG_QUALITY) -> np.ndarray:
    """Mean absolute difference (per pixel, averaged over channels) after JPEG re-compression."""
    ok, buffer = cv2.imencode(".jpg", original_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG re-encoding failed")
    recompressed = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    diff = cv2.absdiff(original_bgr, recompressed).astype(np.float32)
    return diff.mean(axis=2)


def analyze_error_levels(
    original_bgr: np.ndarray,
    is_jpeg: bool,
    to_normalized: np.ndarray,
    normalized_shape: tuple[int, int],
    normalized_gray: np.ndarray,
) -> list[Finding]:
    """ELA on the original pixels, warped into normalised space so tiles match other checks."""
    if not is_jpeg:
        return [
            Finding(
                category=Category.ALTERATION,
                code="ela_not_applicable",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Compression analysis not applicable",
                description="Error level analysis only applies to JPEG photos; this file is PNG.",
                limitation="PNG files carry no JPEG compression history to compare.",
            )
        ]

    ela = error_level_map(original_bgr)
    height, width = normalized_shape
    ela_norm = cv2.warpPerspective(ela, to_normalized, (width, height), flags=cv2.INTER_AREA)

    size = tile_size_for(normalized_gray.shape, T.TILES_ON_LONG_SIDE, T.MIN_TILE_PX)
    tiles: list[Tile] = []
    values: dict[tuple[int, int], float] = {}
    for tile in iter_tiles(height, width, size):
        window = (slice(tile.y, tile.y + tile.h), slice(tile.x, tile.x + tile.w))
        # Only content tiles: blank paper has near-zero error everywhere and would dominate.
        if float(normalized_gray[window].std()) < T.CONTENT_TILE_STD_MIN:
            continue
        tiles.append(tile)
        values[(tile.row, tile.col)] = float(ela_norm[window].mean())

    if len(tiles) < T.MIN_TILES_FOR_STATISTICS:
        return [
            Finding(
                category=Category.ALTERATION,
                code="ela_insufficient_content",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Compression analysis not possible",
                description="Too few printed regions to compare compression error levels.",
                evidence={"content_tiles": len(tiles), "minimum": T.MIN_TILES_FOR_STATISTICS},
            )
        ]

    flagged, details, median = _outlier_tiles(
        tiles, values, T.ELA_Z_THRESHOLD, T.ELA_MIN_MAD, T.ELA_MIN_RATIO, high_only=True
    )
    if not flagged:
        return [
            Finding(
                category=Category.ALTERATION,
                code="ela_consistent",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Compression error levels are consistent",
                description="No printed region shows a markedly different JPEG error level.",
                evidence={"tiles_compared": len(tiles), "median_error_level": round_evidence(median, 3)},
                limitation="Images re-saved several times lose most compression differences.",
            )
        ]

    findings = []
    for group in merge_adjacent_tiles(flagged):
        xy = {(t.x, t.y) for t in group}
        severity = Severity.MEDIUM if len(group) >= T.ELA_MEDIUM_TILE_COUNT else Severity.LOW
        findings.append(
            Finding(
                category=Category.ALTERATION,
                code="ela_inconsistency",
                kind=Kind.INDICATOR,
                severity=severity,
                title="Region with unusual compression error level",
                description=(
                    "After re-compression this area changes much more than comparable printed areas, "
                    "suggesting a different editing/compression history."
                ),
                evidence={
                    "tiles": [d for d in details if (d["tile"][0], d["tile"][1]) in xy],
                    "tile_count": len(group),
                    "median_error_level": round_evidence(median, 3),
                    "jpeg_quality": T.ELA_JPEG_QUALITY,
                },
                limitation="High-contrast fine detail (small text, patterns, holograms) also raises error levels.",
                regions=[bounding_box(group, "Unusual compression error level")],
            )
        )
    return findings
