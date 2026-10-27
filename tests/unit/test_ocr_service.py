import numpy as np
import pytest
import pytesseract

from app.services.ocr_service import OcrError, OcrService, OcrUnavailableError, parse_tesseract_data

SAMPLE = {
    "text": ["", "Name:", "Rahul", "", "DOB:", "12-05-1998", "  "],
    "conf": ["-1", "95.5", "91", "-1", "88", "40", "-1"],
    "left": [0, 10, 90, 0, 10, 80, 0],
    "top": [0, 10, 10, 0, 50, 50, 0],
    "width": [0, 60, 70, 0, 50, 120, 0],
    "height": [0, 20, 20, 0, 20, 20, 0],
    "block_num": [1, 1, 1, 1, 1, 1, 1],
    "par_num": [1, 1, 1, 1, 1, 1, 1],
    "line_num": [0, 1, 1, 0, 2, 2, 0],
}


def test_parse_tesseract_data_builds_words_and_text():
    result = parse_tesseract_data(SAMPLE)
    assert [w.text for w in result.words] == ["Name:", "Rahul", "DOB:", "12-05-1998"]
    assert result.text == "Name: Rahul\nDOB: 12-05-1998"
    assert result.mean_confidence == pytest.approx((95.5 + 91 + 88 + 40) / 4)
    assert [w.text for w in result.reliable_words] == ["Name:", "Rahul", "DOB:"]


def test_parse_empty_output():
    result = parse_tesseract_data({"text": [], "conf": []})
    assert result.words == [] and result.text == "" and result.mean_confidence is None


def test_missing_binary_maps_to_unavailable(monkeypatch):
    def boom(*_a, **_k):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", boom)
    with pytest.raises(OcrUnavailableError):
        OcrService().extract(np.zeros((10, 10), np.uint8))


def test_tesseract_error_maps_to_ocr_error(monkeypatch):
    def boom(*_a, **_k):
        raise pytesseract.TesseractError(1, "Failed loading language 'xyz'")

    monkeypatch.setattr(pytesseract, "image_to_data", boom)
    with pytest.raises(OcrError, match="language 'xyz'"):
        OcrService(lang="xyz").extract(np.zeros((10, 10), np.uint8))


def test_timeout_maps_to_ocr_error(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setattr(pytesseract, "image_to_data", boom)
    with pytest.raises(OcrError, match="timed out"):
        OcrService().extract(np.zeros((10, 10), np.uint8))
