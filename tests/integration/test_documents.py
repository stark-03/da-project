import os
from datetime import timedelta

import pytest

from app.extensions import db
from app.models import AnalysisResult, Document, Finding, utcnow
from app.services.ocr_service import OcrUnavailableError
from app.services.retention import purge_expired
from tests.conftest import FakeOcrService, fake_ocr_result, make_owner, upload
from tests.helpers import blur_patch, encode, paste_clean_patch, synthetic_document


def stored_path(app, document):
    return os.path.join(app.config["UPLOAD_FOLDER"], document.file_path)


# --- upload & preview ------------------------------------------------------------------------
def test_upload_valid_image(app, logged_in, document_png):
    response = upload(logged_in, document_png)
    assert response.status_code == 302
    document = Document.query.one()
    assert document.status == "uploaded" and document.document_type == "aadhaar"
    assert document.original_filename == "card.png"
    assert document.file_path != "card.png"  # random server name
    assert os.path.isfile(stored_path(app, document))
    assert "static" not in app.config["UPLOAD_FOLDER"]


def test_detail_page_shows_preview_and_verify_button(logged_in, document_png):
    upload(logged_in, document_png)
    page = logged_in.get("/documents/1")
    assert page.status_code == 200
    assert b"/documents/1/image" in page.data and b"Start verification" in page.data


def test_image_route_serves_private_file_with_no_store(logged_in, document_png):
    upload(logged_in, document_png)
    response = logged_in.get("/documents/1/image")
    assert response.status_code == 200
    assert response.data == document_png
    assert response.mimetype == "image/png"
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.parametrize(
    "data, filename, message",
    [
        (b"%PDF-1.4 fake", "doc.pdf", b"Unsupported file type"),
        (b"<script>alert(1)</script>", "doc.png", b"not a valid image"),
        (b"", "doc.png", b"empty"),
    ],
)
def test_invalid_uploads_rejected(logged_in, data, filename, message):
    response = upload(logged_in, data, filename=filename)
    assert response.status_code == 400
    assert message in response.data
    assert Document.query.count() == 0


def test_upload_over_size_limit_returns_413(app, logged_in):
    app.config["MAX_CONTENT_LENGTH"] = 1024
    response = upload(logged_in, encode(synthetic_document()))
    assert response.status_code == 413
    assert Document.query.count() == 0


def test_invalid_document_type_rejected(logged_in, document_png):
    response = upload(logged_in, document_png, document_type="passport-of-mars")
    assert response.status_code == 400


# --- owner isolation ------------------------------------------------------------------------
def test_other_owner_gets_404_for_document_and_image(client, logged_in, document_png):
    upload(logged_in, document_png)
    logged_in.post("/auth/logout")
    make_owner(email="intruder@example.com")
    client.post("/auth/login", data={"email": "intruder@example.com", "password": "correct-horse"})
    for url in ["/documents/1", "/documents/1/image"]:
        assert client.get(url).status_code == 404
    assert client.post("/documents/1/verify").status_code == 404
    assert client.post("/documents/1/delete").status_code == 404
    assert Document.query.count() == 1


# --- verification -----------------------------------------------------------------------------
def test_verify_persists_result_findings_and_ocr(app, logged_in, document_png, fake_ocr):
    upload(logged_in, document_png)
    response = logged_in.post("/documents/1/verify", follow_redirects=True)
    assert response.status_code == 200
    document = db.session.get(Document, 1)
    assert document.status == "completed"
    result = document.result
    assert result.result_label in {"genuine", "suspicious", "inconclusive"}
    assert result.engine_name == "rule-based"
    assert result.ocr_text.startswith("Name: Rahul Sharma")
    assert Finding.query.filter_by(result_id=result.id).count() >= 4
    assert {"image_quality", "ocr", "text_alignment", "blur_regions", "alteration", "photograph"} <= {
        f.category for f in result.findings
    }
    assert b"Why this result" in response.data
    assert b"not a probability" in response.data


def test_clean_document_is_genuine_and_tampered_is_flagged(app, logged_in, fake_ocr):
    clean = synthetic_document(noise_sigma=4, seed=2)
    tampered = blur_patch(paste_clean_patch(clean, synthetic_document(), 300, 380, 450, 170), 300, 600, 450, 150, 3)
    upload(logged_in, encode(clean), filename="clean.png")
    upload(logged_in, encode(tampered), filename="tampered.png")
    logged_in.post("/documents/1/verify")
    logged_in.post("/documents/2/verify")
    clean_result = db.session.get(Document, 1).result
    tampered_result = db.session.get(Document, 2).result
    assert clean_result.result_label == "genuine"
    assert tampered_result.result_label == "suspicious"
    assert tampered_result.highlighted_area, "suspicious areas must be highlighted"
    for area in tampered_result.highlighted_area:
        assert 0 <= area["x"] <= 1400 and 0 <= area["y"] <= 900


def test_blurry_capture_is_inconclusive_not_suspicious(logged_in, fake_ocr):
    import cv2

    upload(logged_in, encode(cv2.GaussianBlur(synthetic_document(), (0, 0), 3)))
    logged_in.post("/documents/1/verify")
    assert db.session.get(Document, 1).result.result_label == "inconclusive"


def test_unreadable_document_is_inconclusive(logged_in, fake_ocr, document_png):
    from app.services.ocr_service import OcrResult

    fake_ocr["service"] = FakeOcrService(OcrResult(text="", words=[]))
    upload(logged_in, document_png)
    logged_in.post("/documents/1/verify")
    result = db.session.get(Document, 1).result
    assert result.result_label == "inconclusive"
    assert "ocr_unreadable" in {f.code for f in result.findings}


def test_ocr_unavailable_marks_failed_without_result(logged_in, fake_ocr, document_png):
    fake_ocr["service"] = FakeOcrService(error=OcrUnavailableError("Tesseract OCR is not installed."))
    upload(logged_in, document_png)
    response = logged_in.post("/documents/1/verify", follow_redirects=True)
    document = db.session.get(Document, 1)
    assert document.status == "failed"
    assert document.result is None
    assert AnalysisResult.query.count() == 0
    assert b"Verification failed" in response.data


def test_failed_rerun_removes_stale_result(logged_in, fake_ocr, document_png):
    upload(logged_in, document_png)
    logged_in.post("/documents/1/verify")
    assert AnalysisResult.query.count() == 1
    fake_ocr["service"] = FakeOcrService(error=OcrUnavailableError("missing"))
    logged_in.post("/documents/1/verify")
    assert AnalysisResult.query.count() == 0
    assert db.session.get(Document, 1).status == "failed"


def test_reverification_replaces_result(logged_in, fake_ocr, document_png):
    upload(logged_in, document_png)
    logged_in.post("/documents/1/verify")
    logged_in.post("/documents/1/verify")
    assert AnalysisResult.query.count() == 1


def test_missing_file_fails_gracefully(app, logged_in, fake_ocr, document_png):
    upload(logged_in, document_png)
    os.remove(stored_path(app, db.session.get(Document, 1)))
    logged_in.post("/documents/1/verify")
    assert db.session.get(Document, 1).status == "failed"


def test_verify_requires_post(logged_in, document_png):
    upload(logged_in, document_png)
    assert logged_in.get("/documents/1/verify").status_code == 405


# --- deletion & retention -----------------------------------------------------------------
def test_delete_removes_file_result_and_record(app, logged_in, fake_ocr, document_png):
    upload(logged_in, document_png)
    logged_in.post("/documents/1/verify")
    path = stored_path(app, db.session.get(Document, 1))
    response = logged_in.post("/documents/1/delete")
    assert response.status_code == 302
    assert not os.path.exists(path)
    assert Document.query.count() == 0 and AnalysisResult.query.count() == 0 and Finding.query.count() == 0


def test_purge_expired_removes_image_and_text_keeps_verdict(app, logged_in, fake_ocr, document_png):
    upload(logged_in, document_png)
    logged_in.post("/documents/1/verify")
    document = db.session.get(Document, 1)
    path = stored_path(app, document)
    document.uploaded_at = utcnow() - timedelta(days=45)
    db.session.commit()

    assert purge_expired(app.config["UPLOAD_FOLDER"], retention_days=30) == 1
    document = db.session.get(Document, 1)
    assert document.file_path is None and document.file_deleted_at is not None
    assert not os.path.exists(path)
    assert document.result.ocr_text is None
    assert document.result.result_label in {"genuine", "suspicious", "inconclusive"}
    assert logged_in.get("/documents/1/image").status_code == 404
    assert b"retention policy" in logged_in.get("/documents/1").data


def test_purge_keeps_recent_documents(app, logged_in, document_png):
    upload(logged_in, document_png)
    assert purge_expired(app.config["UPLOAD_FOLDER"], retention_days=30) == 0


# --- output escaping ----------------------------------------------------------------------
def test_ocr_text_is_html_escaped(logged_in, fake_ocr, document_png):
    fake_ocr["service"] = FakeOcrService(
        fake_ocr_result([["<script>alert(1)</script>", "Rahul", "Sharma"], ["a", "b", "c"], ["d", "e", "f"]])
    )
    upload(logged_in, document_png)
    page = logged_in.post("/documents/1/verify", follow_redirects=True).data
    assert b"<script>alert(1)</script>" not in page
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in page
