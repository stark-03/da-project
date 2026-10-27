"""WTForms definitions (CSRF protection comes from FlaskForm)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileRequired
from wtforms import EmailField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import Email, EqualTo, Length, Optional, Regexp

from .models import DocumentType

PASSWORD_MIN_LENGTH = 8


class RegisterForm(FlaskForm):
    name = StringField("Full name", validators=[Length(min=2, max=120)])
    email = EmailField("Email", validators=[Email(), Length(max=255)])
    phone = StringField(
        "Phone (optional)",
        validators=[Optional(), Regexp(r"^\+?[0-9 \-]{7,20}$", message="Enter a valid phone number.")],
    )
    password = PasswordField("Password", validators=[Length(min=PASSWORD_MIN_LENGTH, max=128)])
    confirm = PasswordField(
        "Confirm password", validators=[EqualTo("password", message="Passwords must match.")]
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[Email(), Length(max=255)])
    password = PasswordField("Password", validators=[Length(min=1, max=128)])
    submit = SubmitField("Sign in")


class UploadForm(FlaskForm):
    document_type = SelectField(
        "Document type",
        choices=[(t.value, t.label) for t in DocumentType],
        default=DocumentType.AADHAAR.value,
    )
    document = FileField("Document image", validators=[FileRequired("Please choose an image.")])
    submit = SubmitField("Upload document")


class ActionForm(FlaskForm):
    """Empty form used only to carry a CSRF token on POST buttons (verify, delete, logout)."""
