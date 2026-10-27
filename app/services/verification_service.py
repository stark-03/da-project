"""Verification pipeline orchestration (SRS slide 6: Start Verification «include» Extract Text,
Analyze Document, AI/ML Verification).

load → preprocess → OCR → analyses → classify → persist. Any failure marks the document
``failed`` with a user-safe message; a failed run never produces a result label.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from flask import current_app

from ..extensions import db
from ..models import AnalysisResult, Document, DocumentStatus, Finding, utcnow
from .analysis.alteration import analyze_error_levels, analyze_noise_consistency, estimate_noise_map
from .analysis.blur_regions import analyze_blur_regions
from .analysis.common import AnalysisError, Category, Finding as FindingData, Kind
from .analysis.photograph import analyze_photograph
from .analysis.quality import assess_image_quality, assess_ocr_readability
from .analysis.text_alignment import analyze_text_alignment
from .classifier import DocumentClassifier, RuleBasedClassifier, build_feature_frame
from .image_preprocessing import PreprocessedImage, load_image, map_box_to_original, preprocess
from .ocr_service import OcrError, OcrResult, OcrService
from .storage import DocumentStorage, StorageError

logger = logging.getLogger(__name__)

# Categories whose boxes are in OCR (deskewed) space; all others are in normalised space.
OCR_SPACE_CATEGORIES = {Category.TEXT_ALIGNMENT}

STANDING_LIMITATIONS = [
    "Automated visual screening only — the document was not checked against any government or issuer database.",
    "The decision is made by a transparent rule-based engine, not a trained ML model; no accuracy figure has been established.",
    "The indicator score is a sum of rule weights, not a probability of fraud.",
    "Skilled forgeries, and documents altered before printing, may show no visual indicators.",
]


class VerificationError(Exception):
    """Verification could not be completed. Message is safe to show to the user."""


@dataclass
class PipelineOutput:
    findings: list[FindingData]
    ocr: OcrResult
    quality_metrics: dict
    features: dict
    label: str
    score: float
    reasons: list[str]
    limitations: list[str]
    highlighted: list[dict]
    engine_name: str
    engine_version: str


def run_pipeline(
    image_bytes: bytes,
    is_jpeg: bool,
    ocr_service: OcrService,
    classifier: DocumentClassifier | None = None,
) -> PipelineOutput:
    """Run every analysis stage on raw image bytes. Pure apart from calling Tesseract."""
    classifier = classifier or RuleBasedClassifier()
    original = load_image(image_bytes)
    prepared = preprocess(original)

    quality = assess_image_quality(prepared.normalized_gray)
    ocr = ocr_service.extract(prepared.ocr_gray)  # raises OcrError / OcrUnavailableError
    ocr_findings, ocr_readable = assess_ocr_readability(ocr)

    blur = analyze_blur_regions(prepared.normalized_gray, globally_blurry=not quality.sufficient)
    noise_map = estimate_noise_map(prepared.normalized_gray)

    findings: list[FindingData] = [*quality.findings, *ocr_findings]
    if ocr_readable:
        findings += analyze_text_alignment(ocr)
    findings += blur.findings
    findings += analyze_photograph(prepared.normalized_gray, blur.sharpness_map, noise_map)
    findings += analyze_noise_consistency(prepared.normalized_gray, noise_map)
    findings += analyze_error_levels(
        prepared.original,
        is_jpeg,
        prepared.to_normalized,
        prepared.normalized_gray.shape,
        prepared.normalized_gray,
    )

    _map_regions_to_original(findings, prepared)

    features = build_feature_frame(
        findings,
        quality.metrics,
        quality.sufficient,
        ocr_readable,
        ocr.mean_confidence,
        ocr.word_count,
    )
    decision = classifier.classify(features, findings)

    limitations = list(STANDING_LIMITATIONS)
    if not ocr_readable:
        limitations.append("Text alignment was not checked because too little text could be read.")
    if not is_jpeg:
        limitations.append("Compression (ELA) analysis does not apply to PNG files.")
    if prepared.steps:
        limitations.append("Preprocessing applied: " + "; ".join(prepared.steps) + ".")

    quality_metrics = {
        **quality.metrics,
        "deskew_angle_deg": round(prepared.deskew_angle_deg, 2),
        "document_outline_detected": prepared.document_cropped,
        "analysis_scale": round(prepared.scale, 4),
    }

    return PipelineOutput(
        findings=findings,
        ocr=ocr,
        quality_metrics=quality_metrics,
        features={k: float(v) for k, v in features.iloc[0].to_dict().items()},
        label=decision.label,
        score=decision.indicator_score,
        reasons=decision.reasons,
        limitations=limitations,
        highlighted=_highlighted_areas(findings),
        engine_name=decision.engine_name,
        engine_version=decision.engine_version,
    )


def _map_regions_to_original(findings: list[FindingData], prepared: PreprocessedImage) -> None:
    size = prepared.original_size
    for finding in findings:
        space = prepared.to_ocr if finding.category in OCR_SPACE_CATEGORIES else prepared.to_normalized
        finding.regions = [map_box_to_original(box, space, size) for box in finding.regions]


def _highlighted_areas(findings: list[FindingData]) -> list[dict]:
    """ERD ``highlighted_area``: indicator regions (the 'suspicious areas with reason')."""
    areas = []
    for finding in findings:
        if finding.kind != Kind.INDICATOR:
            continue
        for box in finding.regions:
            areas.append(
                {
                    "x": box.x,
                    "y": box.y,
                    "w": box.w,
                    "h": box.h,
                    "label": box.label or finding.title,
                    "severity": finding.severity.value,
                    "code": finding.code,
                }
            )
    return areas


def verify_document(document: Document) -> AnalysisResult:
    """Run verification for a stored document and persist the result.

    Raises:
        VerificationError: verification failed; the document is marked ``failed``.
    """
    config = current_app.config
    storage = DocumentStorage(config["UPLOAD_FOLDER"])
    started = time.perf_counter()

    document.status = DocumentStatus.PROCESSING.value
    document.error_message = None
    db.session.commit()

    try:
        if not document.file_path:
            raise VerificationError("The document image has been deleted and cannot be verified.")
        image_bytes = storage.read(document.file_path)
        output = run_pipeline(
            image_bytes,
            is_jpeg=document.mime_type == "image/jpeg",
            ocr_service=OcrService.from_config(config),
        )
    except (VerificationError, OcrError, AnalysisError, StorageError) as exc:
        _mark_failed(document, str(exc))
        logger.warning("Verification failed for document %s: %s", document.id, type(exc).__name__)
        raise VerificationError(str(exc)) from exc
    except Exception as exc:  # unexpected bug: log trace, show generic message
        logger.exception("Unexpected verification error for document %s", document.id)
        _mark_failed(document, "An unexpected error occurred during analysis.")
        raise VerificationError("An unexpected error occurred during analysis.") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result = _persist(document, output, elapsed_ms)
    logger.info(
        "Verified document %s: label=%s score=%.1f findings=%d in %d ms",
        document.id,
        result.result_label,
        result.indicator_score,
        len(output.findings),
        elapsed_ms,
    )
    return result


def _mark_failed(document: Document, message: str) -> None:
    db.session.rollback()
    if document.result is not None:
        db.session.delete(document.result)  # never leave a stale result next to a failed run
    document.status = DocumentStatus.FAILED.value
    document.error_message = message[:500]
    db.session.commit()


def _persist(document: Document, output: PipelineOutput, elapsed_ms: int) -> AnalysisResult:
    if document.result is not None:  # re-verification replaces the previous result (ERD 1:1)
        db.session.delete(document.result)
        db.session.flush()

    result = AnalysisResult(
        document_id=document.id,
        result_label=output.label,
        indicator_score=output.score,
        highlighted_area=output.highlighted,
        analysis_time=utcnow(),
        processing_ms=elapsed_ms,
        engine_name=output.engine_name,
        engine_version=output.engine_version,
        reasons=output.reasons,
        limitations=output.limitations,
        quality_metrics=output.quality_metrics,
        features=output.features,
        ocr_text=output.ocr.text,
        ocr_mean_confidence=output.ocr.mean_confidence,
        ocr_word_count=output.ocr.word_count,
        ocr_engine=output.ocr.engine,
    )
    for finding in output.findings:
        data = finding.to_dict()
        result.findings.append(
            Finding(
                category=data["category"],
                code=data["code"],
                kind=data["kind"],
                severity=data["severity"],
                title=data["title"],
                description=data["description"],
                evidence=data["evidence"],
                limitation=data["limitation"],
                regions=data["regions"],
            )
        )
    db.session.add(result)
    document.status = DocumentStatus.COMPLETED.value
    document.error_message = None
    db.session.commit()
    return result

