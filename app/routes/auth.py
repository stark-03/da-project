"""Owner registration and login (ERD OWNER entity has email/password)."""

from __future__ import annotations

import logging
from urllib.parse import urlsplit

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..forms import ActionForm, LoginForm, RegisterForm
from ..models import Owner

bp = Blueprint("auth", __name__, url_prefix="/auth")
logger = logging.getLogger(__name__)


def _safe_next(target: str | None) -> str | None:
    """Only allow relative redirects within this site (prevents open redirects)."""
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = RegisterForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if Owner.query.filter_by(email=email).first():
            form.email.errors.append("An account with this email already exists.")
        else:
            owner = Owner(name=form.name.data.strip(), email=email, phone=(form.phone.data or "").strip() or None)
            owner.set_password(form.password.data)
            db.session.add(owner)
            db.session.commit()
            login_user(owner)
            logger.info("Owner %s registered", owner.id)
            flash("Account created. You can now upload a document.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    form = LoginForm()
    if form.validate_on_submit():
        owner = Owner.query.filter_by(email=form.email.data.strip().lower()).first()
        if owner is None or not owner.check_password(form.password.data):
            # Same message for unknown email and wrong password (no account enumeration).
            form.password.errors.append("Invalid email or password.")
        else:
            login_user(owner)
            return redirect(_safe_next(request.args.get("next")) or url_for("main.dashboard"))
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    form = ActionForm()
    if form.validate_on_submit():
        logout_user()
        flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
