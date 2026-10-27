"""Environment-driven configuration.

All operational limits live here; image-analysis thresholds live in
``app/services/analysis/thresholds.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INSTANCE_DIR = BASE_DIR / "instance"

BYTES_PER_MB = 1024 * 1024


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


class Config:
    """Base configuration shared by all environments."""

    SECRET_KEY = os.environ.get("SECRET_KEY") or None
    DEBUG = False
    TESTING = False

    SQLALCHEMY_DATABASE_URI = (
        os.environ.get("DATABASE_URL", "").strip() or f"sqlite:///{INSTANCE_DIR / 'app.db'}"
    )
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Uploaded identity documents live outside /static and are served only via an
    # owner-checked route.
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "").strip() or str(INSTANCE_DIR / "uploads")
    MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 8)
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * BYTES_PER_MB
    ALLOWED_EXTENSIONS = frozenset({"jpg", "jpeg", "png"})
    # Smallest side below which text/photo analysis is meaningless.
    MIN_IMAGE_SIDE_PX = 300
    # Largest side accepted (a 108 MP phone photo is ~12000 px).
    MAX_IMAGE_SIDE_PX = 12000
    # Decompression-bomb guard (pixels). 50 MP is above any phone camera default.
    MAX_IMAGE_PIXELS = 50_000_000

    TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "").strip() or None
    OCR_LANG = os.environ.get("OCR_LANG", "eng").strip() or "eng"
    OCR_TIMEOUT_SECONDS = _env_int("OCR_TIMEOUT_SECONDS", 60)

    RETENTION_DAYS = _env_int("RETENTION_DAYS", 30)

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()


class DevelopmentConfig(Config):
    DEBUG = True
    # A fixed dev key keeps sessions across restarts; never used in production.
    SECRET_KEY = Config.SECRET_KEY or "dev-only-insecure-key"


class TestingConfig(Config):
    TESTING = True
    SECRET_KEY = "testing-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True


CONFIG_BY_NAME = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}


def get_config(name: str | None = None) -> type[Config]:
    """Return the config class for ``name`` (defaults to the APP_ENV variable)."""
    env_name = (name or os.environ.get("APP_ENV") or "development").strip().lower()
    if env_name not in CONFIG_BY_NAME:
        raise ValueError(f"Unknown APP_ENV '{env_name}'. Use one of {sorted(CONFIG_BY_NAME)}.")
    return CONFIG_BY_NAME[env_name]
