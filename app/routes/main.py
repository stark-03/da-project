"""Dashboard and health check."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template
from flask_login import current_user, login_required
from sqlalchemy import text

from ..extensions import db
from ..models import Document
from ..services.ocr_service import OcrService, OcrUnavailableError

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def dashboard():
    documents = (
        current_user.documents.order_by(Document.uploaded_at.desc(), Document.id.desc()).all()
    )
    counts = {"total": len(documents), "genuine": 0, "suspicious": 0, "inconclusive": 0, "pending": 0, "failed": 0}
    for document in documents:
        if document.result is not None:
            counts[document.result.result_label] = counts.get(document.result.result_label, 0) + 1
        elif document.status == "failed":
            counts["failed"] += 1
        else:
            counts["pending"] += 1
    return render_template("dashboard.html", documents=documents, counts=counts)


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/health")
def health():
    """Liveness/readiness: database reachable and OCR engine availability. No sensitive data."""
    status = {"status": "ok", "database": "ok", "ocr": {"available": False}}
    http_status = 200
    try:
        db.session.execute(text("SELECT 1"))
    except Exception:
        current_app.logger.exception("Health check: database unavailable")
        status["database"] = "unavailable"
        status["status"] = "error"
        http_status = 503
    try:
        version = OcrService.from_config(current_app.config).engine_version()
        status["ocr"] = {"available": True, "version": version}
    except OcrUnavailableError:
        if status["status"] == "ok":
            status["status"] = "degraded"
    return jsonify(status), http_status
