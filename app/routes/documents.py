"""Document upload, preview, verification and result pages (SRS use cases, slide 6)."""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import ActionForm, UploadForm
from ..models import Document, DocumentStatus, DocumentType
from ..services.analysis.common import Category
from ..services.document_validation import (
    DocumentValidationError,
    UploadLimits,
    validate_image_upload,
)
from ..services.retention import purge_document_content
from ..services.storage import DocumentStorage, StorageError
from ..services.verification_service import VerificationError, verify_document

bp = Blueprint("documents", __name__, url_prefix="/documents")
logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3}
KIND_ORDER = {"indicator": 0, "quality": 1, "info": 2}


def _storage() -> DocumentStorage:
    return DocumentStorage(current_app.config["UPLOAD_FOLDER"])


def _owned_document_or_404(document_id: int) -> Document:
    """Return the document only if it belongs to the current owner (404 otherwise, so other
    owners cannot even learn that the ID exists)."""
    document = db.session.get(Document, document_id)
    if document is None or document.owner_id != current_user.id:
        abort(404)
    return document


@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    form = UploadForm()
    if form.validate_on_submit():
        file = form.document.data
        data = file.read()
        try:
            validated = validate_image_upload(
                file.filename or "", data, UploadLimits.from_config(current_app.config)
            )
        except DocumentValidationError as exc:
            form.document.errors.append(str(exc))
            return render_template("upload.html", form=form), 400

        try:
            stored_name = _storage().save(data, validated.extension)
        except OSError:
            logger.exception("Could not store upload")
            form.document.errors.append("The file could not be saved. Please try again.")
            return render_template("upload.html", form=form), 500

        document = Document(
            owner_id=current_user.id,
            file_path=stored_name,
            document_type=DocumentType(form.document_type.data).value,
            original_filename=validated.display_name,
            mime_type=validated.mime_type,
            file_size=validated.size_bytes,
            width=validated.width,
            height=validated.height,
            sha256=validated.sha256,
            status=DocumentStatus.UPLOADED.value,
        )
        db.session.add(document)
        db.session.commit()
        logger.info("Document %s uploaded (%d bytes)", document.id, validated.size_bytes)
        flash("Document uploaded. Check the preview, then start verification.", "success")
        return redirect(url_for("documents.detail", document_id=document.id))

    status = 400 if form.is_submitted() else 200
    return render_template("upload.html", form=form), status


@bp.route("/<int:document_id>")
@login_required
def detail(document_id: int):
    document = _owned_document_or_404(document_id)
    result = document.result
    grouped: dict[str, list] = {}
    if result is not None:
        ordered = sorted(
            result.findings,
            key=lambda f: (KIND_ORDER.get(f.kind, 9), SEVERITY_ORDER.get(f.severity, 9), f.id),
        )
        for category in Category:
            items = [f for f in ordered if f.category == category.value]
            if items:
                grouped[category.label] = items
    return render_template(
        "document.html",
        document=document,
        result=result,
        grouped_findings=grouped,
        action_form=ActionForm(),
    )


@bp.route("/<int:document_id>/image")
@login_required
def image(document_id: int):
    document = _owned_document_or_404(document_id)
    if not document.file_path:
        abort(404)
    try:
        path = _storage().path_for(document.file_path)
    except StorageError:
        abort(404)
    response = send_file(path, mimetype=document.mime_type, max_age=0, conditional=False)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Content-Disposition"] = "inline"
    return response


@bp.route("/<int:document_id>/verify", methods=["POST"])
@login_required
def verify(document_id: int):
    document = _owned_document_or_404(document_id)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    if document.status == DocumentStatus.PROCESSING.value:
        flash("Verification is already running for this document.", "info")
        return redirect(url_for("documents.detail", document_id=document.id))
    try:
        verify_document(document)
        flash("Verification complete.", "success")
    except VerificationError as exc:
        flash(f"Verification failed: {exc}", "error")
    return redirect(url_for("documents.detail", document_id=document.id))


@bp.route("/<int:document_id>/delete", methods=["POST"])
@login_required
def delete(document_id: int):
    document = _owned_document_or_404(document_id)
    form = ActionForm()
    if not form.validate_on_submit():
        abort(400)
    purge_document_content(document, _storage())
    db.session.delete(document)
    db.session.commit()
    logger.info("Document %s deleted by owner", document_id)
    flash("The document, its image and its verification record were deleted.", "success")
    return redirect(url_for("main.dashboard"))
