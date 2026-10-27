from app.services.analysis import thresholds as T
from app.services.analysis.common import Category, Finding, Kind, Severity
from app.services.classifier import FEATURE_COLUMNS, RuleBasedClassifier, build_feature_frame

METRICS = {"sharpness_laplacian_var": 900.0, "brightness_mean": 200.0, "contrast_std": 60.0}


def indicator(severity, category=Category.ALTERATION, code="noise_inconsistency"):
    return Finding(category, code, Kind.INDICATOR, severity, "Test indicator", "desc")


def classify(findings, quality_ok=True, readable=True):
    features = build_feature_frame(findings, METRICS, quality_ok, readable, 90.0, 40)
    return RuleBasedClassifier().classify(features, findings)


def test_no_indicators_is_genuine_with_caveat():
    decision = classify([])
    assert decision.label == "genuine"
    assert decision.indicator_score == 0
    assert any("not proof" in r for r in decision.reasons)


def test_minor_indicator_stays_genuine_but_is_reported():
    decision = classify([indicator(Severity.LOW)])
    assert decision.label == "genuine"
    assert any("Minor indicator" in r for r in decision.reasons)


def test_review_threshold_gives_inconclusive():
    decision = classify([indicator(Severity.MEDIUM)])
    assert decision.indicator_score == T.SCORE_REVIEW
    assert decision.label == "inconclusive"


def test_suspicious_threshold():
    decision = classify([indicator(Severity.MEDIUM), indicator(Severity.MEDIUM, Category.BLUR_REGIONS, "localized_blur")])
    assert decision.label == "suspicious"
    assert decision.indicator_score == 4.0


def test_poor_quality_is_inconclusive_even_with_indicators():
    findings = [
        Finding(Category.IMAGE_QUALITY, "image_blurry", Kind.QUALITY, Severity.MEDIUM, "Image is blurry overall", "d"),
        indicator(Severity.HIGH),
        indicator(Severity.HIGH),
    ]
    decision = classify(findings, quality_ok=False)
    assert decision.label == "inconclusive"
    assert any("unreliable" in r for r in decision.reasons)


def test_unreadable_text_is_inconclusive():
    assert classify([], readable=False).label == "inconclusive"


def test_quality_and_info_findings_do_not_add_to_score():
    findings = [
        Finding(Category.OCR, "ocr_low_confidence", Kind.QUALITY, Severity.LOW, "t", "d"),
        Finding(Category.PHOTOGRAPH, "photo_not_found", Kind.INFO, Severity.NONE, "t", "d"),
    ]
    assert classify(findings).indicator_score == 0


def test_feature_frame_has_fixed_columns():
    frame = build_feature_frame([indicator(Severity.LOW)], METRICS, True, True, None, 0)
    assert list(frame.columns) == FEATURE_COLUMNS
    assert frame.loc[0, "alteration_indicator_count"] == 1
    assert frame.loc[0, "ocr_mean_confidence"] == 0.0


def test_engine_is_labelled_rule_based():
    decision = classify([])
    assert decision.engine_name == "rule-based"
    assert decision.engine_version == T.RULE_ENGINE_VERSION
