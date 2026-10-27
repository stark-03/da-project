"""Retention of uploaded identity documents (Privacy NFR, SRS slide 11).

After ``RETENTION_DAYS`` the image file is deleted and extracted text is cleared. The verdict,
findings and non-personal metadata are kept so the owner retains a record of the check.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from ..extensions import db
from ..models import Document, utcnow
from .storage import DocumentStorage

logger = logging.getLogger(__name__)


def purge_document_content(document: Document, storage: DocumentStorage) -> None:
    """Delete the stored image and clear extracted text for one document (not committed)."""
    storage.delete(document.file_path)
    document.file_path = None
    document.file_deleted_at = utcnow()
    if document.result is not None:
        document.result.ocr_text = None


def purge_expired(upload_folder: str, retention_days: int) -> int:
    """Purge content of documents uploaded more than ``retention_days`` ago. Returns count."""
    cutoff = utcnow() - timedelta(days=retention_days)
    storage = DocumentStorage(upload_folder)
    expired = (
        Document.query.filter(Document.uploaded_at < cutoff, Document.file_path.isnot(None)).all()
    )
    for document in expired:
        purge_document_content(document, storage)
    db.session.commit()
    logger.info("Retention purge removed content of %d document(s)", len(expired))
    return len(expired)
