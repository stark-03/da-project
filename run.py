"""Application entry point.

Usage:
    flask --app run run --debug      # development server
    python run.py                    # same, using APP_ENV from .env
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False))
