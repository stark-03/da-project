"""Flask CLI commands: ``flask --app run <command>``."""

from __future__ import annotations

import click
import pandas as pd
from flask import Flask, current_app

from .extensions import db
from .models import AnalysisResult, Document
from .services.classifier import FEATURE_COLUMNS
from .services.retention import purge_expired


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        """Create database tables (safe to run repeatedly)."""
        db.create_all()
        click.echo(f"Database ready: {current_app.config['SQLALCHEMY_DATABASE_URI'].split('@')[-1]}")

    @app.cli.command("purge-expired")
    @click.option("--days", type=int, default=None, help="Override RETENTION_DAYS.")
    def purge(days: int | None) -> None:
        """Delete images and extracted text older than the retention period."""
        retention = days if days is not None else current_app.config["RETENTION_DAYS"]
        count = purge_expired(current_app.config["UPLOAD_FOLDER"], retention)
        click.echo(f"Purged content of {count} document(s) older than {retention} day(s).")

    @app.cli.command("export-features")
    @click.argument("output", type=click.Path(dir_okay=False, writable=True))
    def export_features(output: str) -> None:
        """Export the classifier feature table (no personal data) to CSV.

        Add a ground-truth 'label' column by hand to build a dataset for training/evaluating
        a future ML model.
        """
        rows = []
        query = db.session.query(AnalysisResult, Document).join(Document)
        for result, document in query.all():
            row = {"document_id": document.id, "document_type": document.document_type}
            row.update({col: result.features.get(col) for col in FEATURE_COLUMNS})
            row["rule_label"] = result.result_label
            row["engine_version"] = result.engine_version
            rows.append(row)
        frame = pd.DataFrame(rows, columns=["document_id", "document_type", *FEATURE_COLUMNS, "rule_label", "engine_version"])
        frame.to_csv(output, index=False)
        click.echo(f"Wrote {len(frame)} row(s) to {output}")
