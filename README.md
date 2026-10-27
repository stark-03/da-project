# AI Rental Scam Detector

A web application that helps a property owner screen a tenant's identity or rental document
before trusting it. The owner uploads a photo or scan, previews it and starts verification. The
system then extracts the text (Tesseract OCR) and analyses the image (OpenCV). The result page shows:

- the document with suspicious areas highlighted,
- the extracted text,
- quality and alteration findings with their measured evidence,
- a **Genuine / Suspicious / Inconclusive** result with the reasons behind it.

Every verification is stored in a database.

> **Important:** this is automated *visual screening*. It does not check any government
> database and cannot prove a document is authentic. The decision engine is **rule-based**:
> no labelled dataset exists to train an ML model, so **no accuracy figure has been established**.
> See [Known limitations](#known-limitations).

Requirements source: `SRS.pptx`. For requirement-by-requirement status see
[`docs/requirements_traceability.md`](docs/requirements_traceability.md). For technical details
see [`docs/technical.md`](docs/technical.md).

---

## Features

| Feature | Details |
|---------|---------|
| Owner accounts | Register and sign in. Each owner sees only their own documents. |
| Upload & preview | JPG/PNG with an instant in-browser preview. Strict server-side validation: real image content, size and dimension limits, corrupt files rejected. Phones can capture directly from the camera. |
| Pre-processing | EXIF orientation, resizing, document outline + perspective correction, deskew, denoise, contrast enhancement. The original is never modified. |
| OCR | Tesseract with per-word confidence and boxes. Extracted text is shown on the result page. |
| Text alignment | Flags lines that are not parallel and words shifted off the baseline. |
| Blurred regions | Flags areas much blurrier than the rest of the document. |
| Photograph | Detects the holder's photo and checks its blur, and whether its sharpness and noise match the document. |
| Possible alterations | Image-noise inconsistency, plus JPEG error level analysis. |
| Decision | Transparent rule engine (v1.0.0): **Genuine** (no significant indicators), **Suspicious**, or **Inconclusive** (poor quality or mixed evidence, so manual review). |
| Dashboard | Summary counts, document list, highlighted areas, reasons, evidence and limitations. |
| Privacy | Uploads are stored privately (never in `static/`). Images and extracted text are deleted after `RETENTION_DAYS`, and owners can delete a document at any time. |

## Architecture

```
Browser (HTML/CSS/vanilla JS)
   │  multipart upload + CSRF token
   ▼
Flask routes (auth, main, documents)
   │
   ├─ document_validation ─ storage (instance/uploads, random names)
   │
   └─ verification_service
        load → preprocess → OCR (Tesseract) → analyses (OpenCV/NumPy)
             → feature table (pandas) → RuleBasedClassifier → persist
                                                               │
                                     SQLite (dev) / MySQL (prod) ◄┘
```

Details: [`docs/technical.md`](docs/technical.md).

---

## Prerequisites

- **Python 3.10+** (developed and tested with 3.12). A conda environment works fine.
- **Tesseract OCR 4 or 5** — a separate program, not a pip package.
- Optional: **MySQL 8** for production. SQLite is used by default with no setup.
- A modern browser (Chrome or Firefox).

### Installing Tesseract

**Windows 10/11**
1. Download the installer from the UB Mannheim build: <https://github.com/UB-Mannheim/tesseract/wiki>.
2. Install it (default path: `C:\Program Files\Tesseract-OCR`).
3. Either add that folder to `PATH`, or set this in `.env`:
   ```
   TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

**Linux:** `sudo apt install tesseract-ocr` (Debian/Ubuntu), or `sudo dnf install tesseract` (Fedora).

**Any OS with conda:** `conda install -c conda-forge tesseract`

Check the install with `tesseract --version`. Extra languages (for example Hindi: `hin`) need their
language packs. Then set `OCR_LANG=eng+hin`.

## Setup

From the project folder, with your environment active (e.g. `conda activate preeti-env`):

```bash
pip install -r requirements.txt          # app dependencies
pip install -r requirements-dev.txt      # + pytest, for running tests

# create your .env
cp .env.example .env                     # Windows (cmd): copy .env.example .env
```

Edit `.env` and set at least `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Create the database (SQLite file at `instance/app.db`):

```bash
flask --app run init-db
```

## Running

```bash
flask --app run run --debug
# or
python run.py
```

Open <http://127.0.0.1:5000>, register an owner account, and upload a document.

Health check: <http://127.0.0.1:5000/health>. It reports database status and whether Tesseract was found.

### Using MySQL instead of SQLite

```sql
CREATE DATABASE rental_scam_detector CHARACTER SET utf8mb4;
CREATE USER 'rsd'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL ON rental_scam_detector.* TO 'rsd'@'localhost';
```

Then, in `.env`:

```
DATABASE_URL=mysql+pymysql://rsd:choose-a-password@localhost:3306/rental_scam_detector?charset=utf8mb4
```

Then run `flask --app run init-db`. *(The MySQL path uses standard SQLAlchemy/PyMySQL but has not been
tested against a live MySQL server in this project yet. SQLite is the tested configuration.)*

### Production notes

- Set `APP_ENV=production` and a strong `SECRET_KEY`. Production refuses to start without one.
- Serve over HTTPS. Production forces `Secure` cookies.
- Run behind a production WSGI server (e.g. `pip install waitress` then `waitress-serve --call app:create_app` on Windows,
  or gunicorn on Linux) rather than `flask run`.
- Schedule `flask --app run purge-expired` daily (Windows Task Scheduler or cron).

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `APP_ENV` | `development` | `development`, `production` or `testing` |
| `SECRET_KEY` | — (required) | Session/CSRF signing key |
| `DATABASE_URL` | SQLite `instance/app.db` | SQLAlchemy URL (MySQL: `mysql+pymysql://…`) |
| `TESSERACT_CMD` | `tesseract` on PATH | Full path to `tesseract.exe` on Windows |
| `OCR_LANG` | `eng` | Tesseract language(s), e.g. `eng+hin` |
| `OCR_TIMEOUT_SECONDS` | `60` | Kill OCR after this many seconds |
| `UPLOAD_FOLDER` | `instance/uploads` | Private storage for uploaded images |
| `MAX_UPLOAD_MB` | `8` | Maximum upload size |
| `RETENTION_DAYS` | `30` | Days before images and extracted text are purged |
| `SESSION_COOKIE_SECURE` | `0` | Set to `1` when served over HTTPS (always on in production) |
| `LOG_LEVEL` | `INFO` | Logging level. Logs never contain document content |

## Other commands

```bash
flask --app run purge-expired             # delete images + extracted text older than RETENTION_DAYS
flask --app run purge-expired --days 7    # custom period
flask --app run export-features out.csv   # numeric feature table (no personal data) for future ML work
```

## Testing

```bash
python -m pytest            # everything
python -m pytest tests/unit # fast unit tests only
```

All test images are synthetic and generated in code (`tests/helpers.py`). No real identity
documents are used. The two tests in `tests/integration/test_real_ocr.py` run the real Tesseract
binary, and are **skipped** automatically if Tesseract is not installed.

Last recorded run (Linux, Python 3.12, Tesseract 5.5.3): **114 passed**. Without Tesseract:
112 passed, 2 skipped.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `RuntimeError: SECRET_KEY must be set` | Create `.env` from `.env.example` and set `SECRET_KEY`. |
| Verification fails with "Tesseract OCR is not installed…" | Install Tesseract, or set `TESSERACT_CMD` to the full path of `tesseract.exe`. Check `/health`. |
| "Check that the OCR language 'xyz' is installed" | Install the language pack, or set `OCR_LANG=eng`. |
| "The file extension does not match the file content" | The file was renamed (e.g. a PNG saved as `.jpg`). Upload the original file. |
| Result is often **Inconclusive** | The photo is blurry, dark or unreadable. Retake it flat, in focus, in even light, with the document filling the frame. |
| `ModuleNotFoundError: cv2` | Run `pip install -r requirements.txt` in the active environment. |
| "Session expired" after a form submit | The CSRF token is older than an hour. Reload the page and resubmit. |
| `cryptography` error with MySQL 8 | It is in `requirements.txt`. Reinstall the requirements. |

## Known limitations

- **No trained ML model.** No labelled dataset of genuine vs altered documents was available, so the
  "AI/ML verification" step is implemented as a documented rule-based engine over measured
  features. The feature table and classifier interface are ready for a trained model (see
  `docs/technical.md` → *ML roadmap*). **Accuracy on real documents has not been measured.**
- Thresholds were checked on **synthetic** documents only. Expect false alarms from glare, folds,
  stamps, holograms and laminate, and expect missed forgeries that were done carefully or before printing.
- Detection limits measured on synthetic tests:
  - a region must be blurred by about Gaussian σ ≥ 1.5 px to be flagged (σ = 1 is not);
  - a word must be shifted by about ≥ 0.35× the word height (≈ 9 px on the test documents);
  - a line must be tilted by more than 1.5°;
  - error level analysis is deliberately conservative and rarely fires on text-heavy images.
- No face identity check, no template comparison per document type, no QR/MRZ/checksum validation,
  and no lookup against the issuing authority.
- Verification runs inside the web request (about 1 s on the test machine for a 1400×900 image).
- Login rate limiting and encryption at rest are not implemented yet.
- Tested on Linux. The code avoids OS-specific APIs and documents Windows setup, but has not been
  executed on Windows in this project.
