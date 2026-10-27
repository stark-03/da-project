"""AI Rental Scam Detector — Flask application factory."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

# Load .env before config classes read os.environ.
load_dotenv()

from flask import Flask, render_template  # noqa: E402
from flask_wtf.csrf import CSRFError  # noqa: E402

from .config import INSTANCE_DIR, get_config  # noqa: E402
from .extensions import csrf, db, login_manager  # noqa: E402

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(config_name: str | None = None, overrides: dict | None = None) -> Flask:
    app = Flask(__name__, instance_path=str(INSTANCE_DIR), instance_relative_config=False)
    app.config.from_object(get_config(config_name))
    if overrides:
        app.config.update(overrides)

    if not app.config.get("SECRET_KEY") or app.config["SECRET_KEY"] == "change-me":
        raise RuntimeError("SECRET_KEY must be set (see .env.example) before starting the app.")

    _configure_logging(app)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    from .models import Owner

    @login_manager.user_loader
    def load_owner(owner_id: str):
        return db.session.get(Owner, int(owner_id))

    from .routes import auth, documents, main

    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(documents.bp)

    _register_error_handlers(app)
    _register_security_headers(app)

    from .cli import register_cli

    register_cli(app)

    with app.app_context():
        # Idempotent: creates missing tables only. `flask --app run init-db` does the same.
        db.create_all()

    return app


def _configure_logging(app: Flask) -> None:
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app.logger.setLevel(level)


def _register_error_handlers(app: Flask) -> None:
    messages = {
        400: ("Bad request", "The request could not be processed."),
        403: ("Forbidden", "You do not have access to this page."),
        404: ("Not found", "The page or document you requested does not exist."),
        405: ("Method not allowed", "This action is not allowed here."),
        413: ("File too large", f"The upload exceeds the {app.config['MAX_UPLOAD_MB']} MB limit."),
        500: ("Server error", "Something went wrong on our side. Please try again."),
    }

    def render_error(code: int):
        title, message = messages[code]
        return render_template("errors/error.html", code=code, title=title, message=message), code

    for code in messages:
        app.register_error_handler(code, lambda _e, code=code: render_error(code))

    @app.errorhandler(CSRFError)
    def csrf_error(_error):
        return (
            render_template(
                "errors/error.html",
                code=400,
                title="Session expired",
                message="Your form session expired. Please go back, reload the page and try again.",
            ),
            400,
        )


def _register_security_headers(app: Flask) -> None:
    @app.after_request
    def set_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
