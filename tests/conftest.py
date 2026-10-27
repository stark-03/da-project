"""Shared fixtures. All images are synthetic (tests/helpers.py)."""

from __future__ import annotations

import io
import shutil

import pytest

from app import create_app
from app.extensions import db
from app.models import Owner
from app.services.ocr_service import OcrResult, OcrWord

from .helpers import encode, synthetic_document


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


@pytest.fixture
def app(tmp_path):
    app = create_app(
        "testing",
        {
            "UPLOAD_FOLDER": str(tmp_path / "uploads"),
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        },
    )
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def make_owner(email="owner@example.com", password="correct-horse", name="Test Owner") -> Owner:
    owner = Owner(name=name, email=email)
    owner.set_password(password)
    db.session.add(owner)
    db.session.commit()
    return owner


@pytest.fixture
def owner(app):
    return make_owner()


@pytest.fixture
def logged_in(client, owner):
    response = client.post(
        "/auth/login", data={"email": owner.email, "password": "correct-horse"}, follow_redirects=False
    )
    assert response.status_code == 302
    return client


@pytest.fixture
def document_png() -> bytes:
    return encode(synthetic_document(noise_sigma=4, seed=3))


def upload(client, data: bytes, filename="card.png", document_type="aadhaar"):
    return client.post(
        "/documents/upload",
        data={"document": (io.BytesIO(data), filename), "document_type": document_type},
        content_type="multipart/form-data",
    )


def fake_ocr_result(lines: list[list[str]] | None = None, confidence: float = 92.0) -> OcrResult:
    """A readable OCR result laid out as straight, evenly spaced lines."""
    from app.services.ocr_service import words_to_text

    lines = lines or [["Name:", "Rahul", "Sharma"], ["Date", "of", "Birth"], ["Card", "Number", "1234"], ["Issued", "On", "2020"]]
    words = []
    for line_index, line in enumerate(lines):
        x = 50
        for text in line:
            width = 20 * len(text)
            words.append(OcrWord(text, confidence, x, 100 + 60 * line_index, width, 28, (1, 1, line_index + 1)))
            x += width + 25
    return OcrResult(text=words_to_text(words), words=words, mean_confidence=confidence, engine="fake")


class FakeOcrService:
    """Test double injected in place of Tesseract for deterministic integration tests."""

    def __init__(self, result: OcrResult | None = None, error: Exception | None = None):
        self.result = result or fake_ocr_result()
        self.error = error

    def extract(self, _gray):
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def fake_ocr(monkeypatch):
    """Patch OcrService.from_config to return a controllable fake."""
    from app.services import verification_service

    holder = {"service": FakeOcrService()}
    monkeypatch.setattr(
        verification_service.OcrService, "from_config", classmethod(lambda cls, config: holder["service"])
    )
    return holder
