"""Analysis modules on synthetic clean vs manipulated documents."""

import cv2
import numpy as np

from app.services.analysis.alteration import (
    analyze_error_levels,
    analyze_noise_consistency,
    estimate_noise_map,
)
from app.services.analysis.blur_regions import analyze_blur_regions
from app.services.analysis.common import Box, Kind, robust_z_scores
from app.services.analysis.photograph import analyze_photograph, assess_photo_region
from app.services.analysis.quality import assess_image_quality, assess_ocr_readability
from app.services.analysis.text_alignment import analyze_text_alignment
from app.services.image_preprocessing import preprocess
from app.services.ocr_service import OcrResult, OcrWord
from tests.helpers import blur_patch, encode, paste_clean_patch, synthetic_document


def gray_of(image):
    return preprocess(image).normalized_gray


def codes(findings):
    return {f.code for f in findings}


def indicator_codes(findings):
    return {f.code for f in findings if f.kind == Kind.INDICATOR}


# --- quality -------------------------------------------------------------------------------
def test_clear_image_has_sufficient_quality():
    quality = assess_image_quality(gray_of(synthetic_document(noise_sigma=3)))
    assert quality.sufficient
    assert codes(quality.findings) == {"image_quality_ok"}


def test_blurred_image_flagged_as_quality_not_indicator():
    blurred = cv2.GaussianBlur(synthetic_document(), (0, 0), 3)
    quality = assess_image_quality(gray_of(blurred))
    assert not quality.sufficient
    assert "image_blurry" in codes(quality.findings)
    assert all(f.kind == Kind.QUALITY for f in quality.findings)


def test_dark_and_flat_images_flagged():
    dark = assess_image_quality(np.full((900, 1400), 20, np.uint8))
    assert {"image_underexposed", "image_low_contrast"} <= codes(dark.findings)


def test_empty_ocr_is_unreadable():
    findings, readable = assess_ocr_readability(OcrResult(text="", words=[]))
    assert not readable and codes(findings) == {"ocr_unreadable"}


# --- blur regions --------------------------------------------------------------------------
def test_clean_document_has_no_blur_regions():
    analysis = analyze_blur_regions(gray_of(synthetic_document(noise_sigma=4)), globally_blurry=False)
    assert indicator_codes(analysis.findings) == set()


def test_locally_blurred_region_detected_and_located():
    image = blur_patch(synthetic_document(noise_sigma=4), 300, 230, 400, 160, sigma=2.5)
    prepared = preprocess(image)
    analysis = analyze_blur_regions(prepared.normalized_gray, globally_blurry=False)
    flagged = [f for f in analysis.findings if f.code == "localized_blur"]
    assert flagged
    box = flagged[0].regions[0]
    # Region must overlap the blurred patch (normalised coords ~ original minus small crop offset).
    assert box.x < 700 and box.x + box.w > 300 and box.y < 390 and box.y + box.h > 230


def test_blur_region_check_skipped_when_globally_blurry():
    analysis = analyze_blur_regions(gray_of(synthetic_document()), globally_blurry=True)
    assert codes(analysis.findings) == {"blur_regions_skipped"}


# --- alteration ------------------------------------------------------------------------------
def test_noise_consistent_on_single_capture():
    findings = analyze_noise_consistency(gray_of(synthetic_document(noise_sigma=5, seed=1)))
    assert indicator_codes(findings) == set()


def test_noise_free_document_is_not_flagged():
    findings = analyze_noise_consistency(gray_of(synthetic_document()))
    assert indicator_codes(findings) == set()


def test_pasted_clean_region_detected():
    spliced = paste_clean_patch(synthetic_document(noise_sigma=5, seed=1), synthetic_document(), 300, 230, 400, 200)
    findings = analyze_noise_consistency(gray_of(spliced))
    assert "noise_inconsistency" in indicator_codes(findings)


def test_ela_not_applicable_for_png():
    prepared = preprocess(synthetic_document())
    findings = analyze_error_levels(
        prepared.original, False, prepared.to_normalized, prepared.normalized_gray.shape, prepared.normalized_gray
    )
    assert codes(findings) == {"ela_not_applicable"}


def test_ela_consistent_on_single_jpeg():
    jpeg = cv2.imdecode(np.frombuffer(encode(synthetic_document(noise_sigma=3), ".jpg", 85), np.uint8), 1)
    prepared = preprocess(jpeg)
    findings = analyze_error_levels(
        prepared.original, True, prepared.to_normalized, prepared.normalized_gray.shape, prepared.normalized_gray
    )
    assert indicator_codes(findings) == set()


def test_noise_map_has_tiles():
    assert len(estimate_noise_map(gray_of(synthetic_document(noise_sigma=3))).tiles) > 50


# --- photograph ------------------------------------------------------------------------------
def test_no_photo_is_informational():
    gray = gray_of(synthetic_document())
    blur = analyze_blur_regions(gray, False)
    findings = analyze_photograph(gray, blur.sharpness_map, estimate_noise_map(gray))
    assert codes(findings) == {"photo_not_found"}
    assert findings[0].kind == Kind.INFO


def test_blurry_photo_region_flagged_as_quality():
    gray = cv2.cvtColor(synthetic_document(noise_sigma=3), cv2.COLOR_BGR2GRAY)
    gray[150:450, 80:330] = cv2.GaussianBlur(gray[150:450, 80:330], (0, 0), 6)
    findings = assess_photo_region(gray, Box(80, 150, 250, 300), document_sharpness=2.6, document_noise=2.0)
    assert "photo_blurry" in codes(findings)
    assert next(f for f in findings if f.code == "photo_blurry").kind == Kind.QUALITY


def test_photo_noise_mismatch_detected():
    rng = np.random.default_rng(0)
    gray = np.full((600, 600), 200, np.uint8)
    cv2.putText(gray, "PHOTO", (60, 300), cv2.FONT_HERSHEY_SIMPLEX, 3, 30, 6)
    noisy = np.clip(gray + rng.normal(0, 12, gray.shape), 0, 255).astype(np.uint8)
    findings = assess_photo_region(noisy, Box(0, 0, 600, 600), document_sharpness=None, document_noise=1.0)
    assert "photo_noise_mismatch" in codes(findings)


# --- text alignment --------------------------------------------------------------------------
def make_words(rows, shift=None, tilt_row=None, tilt_deg=0.0):
    """rows: list of word counts. shift=(row, index, px) moves one word vertically."""
    words = []
    for r, count in enumerate(rows):
        x = 40
        for i in range(count):
            y = 100 + r * 60
            if tilt_row == r:
                y += int(round(np.tan(np.radians(tilt_deg)) * (x - 40)))
            if shift and shift[0] == r and shift[1] == i:
                y += shift[2]
            words.append(OcrWord(f"w{r}{i}", 95.0, x, y, 80, 28, (1, 1, r + 1)))
            x += 110
    return OcrResult(text="", words=words, mean_confidence=95.0)


def test_straight_lines_are_consistent():
    findings = analyze_text_alignment(make_words([5, 5, 5, 5]))
    assert codes(findings) == {"alignment_consistent"}


def test_shifted_word_detected():
    findings = analyze_text_alignment(make_words([5, 5, 5, 5], shift=(1, 2, 14)))
    flagged = [f for f in findings if f.code == "word_off_baseline"]
    assert flagged and flagged[0].evidence["offsets_px"] == [14.0]


def test_descender_does_not_trigger_shift():
    # Only the bottom edge moves (e.g. 'g' descender): must NOT be flagged.
    result = make_words([5, 5, 5, 5])
    result.words[7].height += 10
    assert codes(analyze_text_alignment(result)) == {"alignment_consistent"}


def test_tilted_line_detected():
    findings = analyze_text_alignment(make_words([5, 5, 5, 5], tilt_row=2, tilt_deg=4.0))
    tilted = [f for f in findings if f.code == "line_angle_deviation"]
    assert tilted and abs(tilted[0].evidence["deviations_deg"][0]) > 3


def test_too_little_text_is_informational():
    findings = analyze_text_alignment(make_words([2, 2]))
    assert codes(findings) == {"alignment_insufficient_text"}


# --- helpers -----------------------------------------------------------------------------------
def test_robust_z_scores_with_constant_data():
    z = robust_z_scores(np.array([1.0, 1.0, 1.0, 1.0]), min_mad=0.1)
    assert np.all(z == 0)
