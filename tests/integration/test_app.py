import io

import pytest

from app import create_app
from app.extensions import db
from tests.conftest import make_owner
from tests.helpers import encode, synthetic_document


def test_health_reports_database_and_ocr(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.get_json()
    assert body["database"] == "ok"
    assert body["status"] in {"ok", "degraded"}
    assert "available" in body["ocr"]


def test_security_headers_present(client):
    response = client.get("/auth/login")
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_about_page_explains_labels(client):
    page = client.get("/about").data
    assert b"not</strong> proof" in page and b"no accuracy figure exists" in page


def test_404_page_is_generic(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404 and b"Traceback" not in response.data


def test_production_requires_secret_key(monkeypatch, tmp_path):
    from app import config

    monkeypatch.setattr(config.ProductionConfig, "SECRET_KEY", None)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production", {"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'p.db'}"})


def test_production_cookies_are_secure():
    from app.config import ProductionConfig

    assert ProductionConfig.SESSION_COOKIE_SECURE is True
    assert ProductionConfig.SESSION_COOKIE_HTTPONLY is True
    assert ProductionConfig.DEBUG is False


def test_csrf_enforced_when_enabled(tmp_path):
    app = create_app(
        "testing",
        {
            "WTF_CSRF_ENABLED": True,
            "UPLOAD_FOLDER": str(tmp_path / "u"),
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'c.db'}",
        },
    )
    with app.app_context():
        db.create_all()
        make_owner()
        client = app.test_client()
        response = client.post("/auth/login", data={"email": "owner@example.com", "password": "correct-horse"})
        assert response.status_code == 400  # missing CSRF token
        response = client.post(
            "/documents/upload",
            data={"document": (io.BytesIO(encode(synthetic_document())), "a.png")},
            content_type="multipart/form-data",
        )
        assert response.status_code in (302, 400)  # unauthenticated redirect or CSRF rejection


def test_cli_init_db_and_export(app, tmp_path):
    runner = app.test_cli_runner()
    assert "Database ready" in runner.invoke(args=["init-db"]).output
    out = tmp_path / "features.csv"
    result = runner.invoke(args=["export-features", str(out)])
    assert "Wrote 0 row(s)" in result.output and out.exists()
    assert "Purged content of 0" in runner.invoke(args=["purge-expired"]).output
