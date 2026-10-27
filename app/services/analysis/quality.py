"""Global image-quality and OCR-readability checks.

Quality problems are reported as ``Kind.QUALITY``: they can make a result inconclusive but are
never counted as evidence of tampering — a blurry photo of a genuine card is still genuine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..ocr_service import OcrResult
from . import thresholds as T
from .common import Category, Finding, Kind, Severity, laplacian_variance, round_evidence


@dataclass
class QualityAssessment:
    metrics: dict
    findings: list[Finding] = field(default_factory=list)
    sufficient: bool = True


def assess_image_quality(gray: np.ndarray) -> QualityAssessment:
    """Measure global sharpness, exposure and contrast of the normalised grayscale image."""
    sharpness = laplacian_variance(gray)
    brightness = float(gray.mean())
    contrast = float(gray.std())
    height, width = gray.shape[:2]
    metrics = {
        "sharpness_laplacian_var": round_evidence(sharpness),
        "brightness_mean": round_evidence(brightness),
        "contrast_std": round_evidence(contrast),
        "analysis_width_px": int(width),
        "analysis_height_px": int(height),
    }
    findings: list[Finding] = []

    if sharpness < T.GLOBAL_BLUR_LAPLACIAN_MIN:
        findings.append(
            Finding(
                category=Category.IMAGE_QUALITY,
                code="image_blurry",
                kind=Kind.QUALITY,
                severity=Severity.MEDIUM,
                title="Image is blurry overall",
                description=(
                    "The whole image is out of focus or motion-blurred. Text extraction and "
                    "fine-detail checks are unreliable, so no authenticity decision is made."
                ),
                evidence={
                    "laplacian_variance": round_evidence(sharpness),
                    "minimum_expected": T.GLOBAL_BLUR_LAPLACIAN_MIN,
                },
                limitation="Global blur is a capture problem, not evidence of tampering. Retake the photo in focus.",
            )
        )

    if brightness < T.BRIGHTNESS_MIN or brightness > T.BRIGHTNESS_MAX:
        too_dark = brightness < T.BRIGHTNESS_MIN
        findings.append(
            Finding(
                category=Category.IMAGE_QUALITY,
                code="image_underexposed" if too_dark else "image_overexposed",
                kind=Kind.QUALITY,
                severity=Severity.MEDIUM,
                title="Image is too dark" if too_dark else "Image is washed out",
                description="Poor exposure hides text and detail needed for analysis.",
                evidence={
                    "mean_brightness": round_evidence(brightness),
                    "expected_range": [T.BRIGHTNESS_MIN, T.BRIGHTNESS_MAX],
                },
                limitation="Exposure is a capture problem, not evidence of tampering.",
            )
        )

    if contrast < T.CONTRAST_STD_MIN:
        findings.append(
            Finding(
                category=Category.IMAGE_QUALITY,
                code="image_low_contrast",
                kind=Kind.QUALITY,
                severity=Severity.MEDIUM,
                title="Image has very low contrast",
                description="Text and background are hard to separate, reducing analysis reliability.",
                evidence={
                    "gray_level_std": round_evidence(contrast),
                    "minimum_expected": T.CONTRAST_STD_MIN,
                },
                limitation="Low contrast is a capture problem, not evidence of tampering.",
            )
        )

    sufficient = not findings
    if sufficient:
        findings.append(
            Finding(
                category=Category.IMAGE_QUALITY,
                code="image_quality_ok",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Image quality is adequate",
                description="Focus, exposure and contrast are within the ranges needed for analysis.",
                evidence={
                    **metrics,
                    "blur_min": T.GLOBAL_BLUR_LAPLACIAN_MIN,
                    "brightness_range": [T.BRIGHTNESS_MIN, T.BRIGHTNESS_MAX],
                    "contrast_min": T.CONTRAST_STD_MIN,
                },
            )
        )
    return QualityAssessment(metrics=metrics, findings=findings, sufficient=sufficient)


def assess_ocr_readability(ocr: OcrResult) -> tuple[list[Finding], bool]:
    """Return readability findings and whether the text is readable enough to analyse."""
    reliable = len(ocr.reliable_words)
    evidence = {
        "words_detected": ocr.word_count,
        "reliable_words": reliable,
        "reliable_word_min_confidence": T.OCR_WORD_MIN_CONFIDENCE,
        "mean_confidence": round_evidence(ocr.mean_confidence) if ocr.mean_confidence is not None else None,
    }

    if reliable < T.OCR_MIN_RELIABLE_WORDS:
        return [
            Finding(
                category=Category.OCR,
                code="ocr_unreadable",
                kind=Kind.QUALITY,
                severity=Severity.MEDIUM,
                title="Little or no readable text",
                description=(
                    "OCR could not read enough text with reasonable confidence. Text-based checks "
                    "cannot be performed, so the document cannot be assessed reliably."
                ),
                evidence={**evidence, "minimum_reliable_words": T.OCR_MIN_RELIABLE_WORDS},
                limitation=(
                    "May be caused by blur, glare, an unsupported language/script, or a document "
                    "with little printed text — not by itself evidence of tampering."
                ),
            )
        ], False

    findings: list[Finding] = []
    if ocr.mean_confidence is not None and ocr.mean_confidence < T.OCR_MEAN_CONFIDENCE_MIN:
        findings.append(
            Finding(
                category=Category.OCR,
                code="ocr_low_confidence",
                kind=Kind.QUALITY,
                severity=Severity.LOW,
                title="Low average OCR confidence",
                description="Parts of the text were read with low confidence; extracted text may contain errors.",
                evidence={**evidence, "minimum_expected_mean": T.OCR_MEAN_CONFIDENCE_MIN},
                limitation="Logos, stamps, holograms and non-English script commonly lower OCR confidence.",
            )
        )
    else:
        findings.append(
            Finding(
                category=Category.OCR,
                code="ocr_ok",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Text extracted",
                description="OCR read the document text with acceptable confidence.",
                evidence=evidence,
                limitation="OCR extracts text only; it does not verify that the text is true.",
            )
        )
    return findings, True
