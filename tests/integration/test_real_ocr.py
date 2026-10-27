"""End-to-end with the real Tesseract binary. Skipped automatically if it is not installed."""

import pytest

from app.extensions import db
from app.models import Document
from app.services.ocr_service import OcrService
from tests.conftest import tesseract_available, upload
from tests.helpers import encode, synthetic_document

pytestmark = pytest.mark.skipif(not tesseract_available(), reason="Tesseract OCR binary not installed")


def test_tesseract_reads_synthetic_document():
    from app.services.image_preprocessing import load_image, preprocess

    prepared = preprocess(load_image(encode(synthetic_document(noise_sigma=3))))
    result = OcrService().extract(prepared.ocr_gray)
    assert "Rahul Sharma" in result.text
    assert "SAMPLELAND" in result.text
    assert result.mean_confidence > 70


def test_full_workflow_with_real_ocr(logged_in):
    upload(logged_in, encode(synthetic_document(noise_sigma=4, seed=2), ".jpg", 92), filename="card.jpg")
    response = logged_in.post("/documents/1/verify", follow_redirects=True)
    document = db.session.get(Document, 1)
    assert document.status == "completed"
    assert document.result.result_label == "genuine"
    assert "Rahul Sharma" in document.result.ocr_text
    assert document.result.ocr_engine.startswith("tesseract")
    assert b"Rahul Sharma" in response.data
