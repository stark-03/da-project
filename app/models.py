"""Database models.

Mirrors the ERD on SRS slide 7:

    OWNER 1 ── M DOCUMENT 1 ── 1 ANALYSIS_RESULT

plus a FINDING table (ANALYSIS_RESULT 1 ── M FINDING) for the structured findings that
slide 4 says must be stored. Deviations from the ERD are documented in CLAUDE.md §2.2.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DocumentType(str, enum.Enum):
    """Document types named on SRS slide 5 ("Aadhaar, PAN, Voter ID, Driving Licence, etc.")."""

    AADHAAR = "aadhaar"
    PAN = "pan"
    VOTER_ID = "voter_id"
    DRIVING_LICENCE = "driving_licence"
    RENTAL_AGREEMENT = "rental_agreement"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            "aadhaar": "Aadhaar card",
            "pan": "PAN card",
            "voter_id": "Voter ID",
            "driving_licence": "Driving licence",
            "rental_agreement": "Rental agreement",
            "other": "Other identity / rental document",
        }[self.value]


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ResultLabel(str, enum.Enum):
    """Verification outcome.

    ``genuine`` means *no suspicious indicators were found by the implemented checks* — it is
    not proof of authenticity. ``inconclusive`` is used when quality or evidence is insufficient.
    """

    GENUINE = "genuine"
    SUSPICIOUS = "suspicious"
    INCONCLUSIVE = "inconclusive"

    @property
    def display(self) -> str:
        return {
            "genuine": "Genuine — no suspicious indicators found",
            "suspicious": "Suspicious — possible alteration indicators found",
            "inconclusive": "Inconclusive — manual review needed",
        }[self.value]


class Owner(UserMixin, db.Model):
    __tablename__ = "owners"

    id = db.Column("owner_id", db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(20), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    documents = db.relationship(
        "Document", back_populates="owner", cascade="all, delete-orphan", lazy="dynamic"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column("document_id", db.Integer, primary_key=True)
    owner_id = db.Column(
        db.Integer, db.ForeignKey("owners.owner_id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Random server-side filename relative to UPLOAD_FOLDER (ERD: file_path). NULL once purged.
    file_path = db.Column(db.String(255), nullable=True, unique=True)
    document_type = db.Column(db.String(32), nullable=False, default=DocumentType.OTHER.value)
    original_filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(32), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    width = db.Column(db.Integer, nullable=False)
    height = db.Column(db.Integer, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    status = db.Column(db.String(16), nullable=False, default=DocumentStatus.UPLOADED.value)
    error_message = db.Column(db.String(500), nullable=True)
    uploaded_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    file_deleted_at = db.Column(db.DateTime, nullable=True)

    owner = db.relationship("Owner", back_populates="documents")
    result = db.relationship(
        "AnalysisResult", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def type_label(self) -> str:
        try:
            return DocumentType(self.document_type).label
        except ValueError:
            return self.document_type

    @property
    def has_file(self) -> bool:
        return self.file_path is not None


class AnalysisResult(db.Model):
    __tablename__ = "analysis_results"

    id = db.Column("result_id", db.Integer, primary_key=True)
    document_id = db.Column(
        db.Integer,
        db.ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    result_label = db.Column(db.String(16), nullable=False)
    # ERD "confidence_score": implemented as a rule-weight sum, NOT a probability.
    indicator_score = db.Column(db.Float, nullable=False, default=0.0)
    # ERD "highlighted_area": list of {x, y, w, h, label, severity} in original-image pixels.
    highlighted_area = db.Column(db.JSON, nullable=False, default=list)
    analysis_time = db.Column(db.DateTime, nullable=False, default=utcnow)
    processing_ms = db.Column(db.Integer, nullable=True)

    engine_name = db.Column(db.String(64), nullable=False)
    engine_version = db.Column(db.String(32), nullable=False)
    reasons = db.Column(db.JSON, nullable=False, default=list)
    limitations = db.Column(db.JSON, nullable=False, default=list)
    quality_metrics = db.Column(db.JSON, nullable=False, default=dict)
    features = db.Column(db.JSON, nullable=False, default=dict)

    # Extracted text is personal data: cleared by the retention purge.
    ocr_text = db.Column(db.Text, nullable=True)
    ocr_mean_confidence = db.Column(db.Float, nullable=True)
    ocr_word_count = db.Column(db.Integer, nullable=True)
    ocr_engine = db.Column(db.String(64), nullable=True)

    document = db.relationship("Document", back_populates="result")
    findings = db.relationship(
        "Finding",
        back_populates="result",
        cascade="all, delete-orphan",
        order_by="Finding.id",
    )

    @property
    def label_enum(self) -> ResultLabel:
        return ResultLabel(self.result_label)


class Finding(db.Model):
    __tablename__ = "findings"

    id = db.Column("finding_id", db.Integer, primary_key=True)
    result_id = db.Column(
        db.Integer,
        db.ForeignKey("analysis_results.result_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category = db.Column(db.String(32), nullable=False)
    code = db.Column(db.String(64), nullable=False)
    kind = db.Column(db.String(16), nullable=False)
    severity = db.Column(db.String(16), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    evidence = db.Column(db.JSON, nullable=False, default=dict)
    limitation = db.Column(db.Text, nullable=True)
    regions = db.Column(db.JSON, nullable=False, default=list)

    result = db.relationship("AnalysisResult", back_populates="findings")
