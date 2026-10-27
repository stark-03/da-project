# CLAUDE.md — AI Rental Scam Detector

> Persistent instructions for Claude Code sessions working on this repository.
> Source of truth for requirements: `SRS.pptx` (13 slides) in the project root.
> Detailed requirement-by-requirement status lives in `docs/requirements_traceability.md`.
> User-facing setup lives in `README.md`. Technical details live in `docs/technical.md`.

---

## 1. Project overview

| Item | Value |
|------|-------|
| Project | **AI Rental Scam Detector** (academic project, Dept. of CSE; student: Preeti Hosurkar, guide: Prof. Irrana Tonni — SRS slide 1) |
| Problem | Property owners renting to tenants receive identity/rental documents that may be forged or altered. They need a quick, explainable first-pass check before trusting a document. |
| Target user | **Owner** (property owner) — the only actor in the use-case diagram (slide 6). |
| Objective | Owner uploads an identity/rental document image, previews it, starts verification, and sees extracted text, document-quality findings and a Genuine / Suspicious assessment on a simple dashboard. Records and findings are stored in a database (slide 8). |

### Expected behaviour (end-to-end)
Upload → Validate → Preview → *Start Verification* → Preprocess → OCR → Analyze → Classify →
Persist → Dashboard (preview with highlighted areas, extracted text, findings, outcome, reasons, limitations).

### Scope and limitations (must stay visible in UI and docs)
- The system performs **automated visual and text-structure screening**. It does **not** prove that
  a document is authentic and does **not** check any government database.
- **No trained ML model or labelled dataset exists.** The classifier is a documented,
  versioned **rule-based** engine over measured image/OCR features. Never present its score as a
  probability or claim an accuracy figure. See §2.3 for the ML roadmap.
- Outcome labels: `genuine` (displayed as *"Genuine — no suspicious indicators found"*),
  `suspicious`, and `inconclusive` (manual review needed). `inconclusive` is an implementation
  decision added for safety: unreadable / low-quality / partially analysed documents must never be
  forced into a binary label.

---

## 2. Requirements traceability

Full table with slide refs, implementation, tests and status: **`docs/requirements_traceability.md`**.
Keep it updated whenever a requirement's status changes.

### 2.1 Explicitly stated in the SRS (summary)
- **Slide 2 Software:** Windows 10/11; HTML5/CSS3/JS; Python; OpenCV; Tesseract OCR; MySQL, SQLite; Chrome/Firefox.
- **Slide 3 Hardware:** i5, 8 GB RAM, 10 GB disk, HD display, mobile camera for capture, internet.
- **Slide 4 Tools:** Python, Flask, HTML/CSS/JS, Tesseract, OpenCV (alignment, blur, photo checks), Pandas/NumPy, AI/ML model (genuine/suspicious), MySQL/SQLite (owner, document, verification, findings), VS Code.
- **Slide 5 Methodology:** capture (Aadhaar, PAN, Voter ID, Driving Licence, etc.) → pre-processing (resize, noise removal, enhancement, format conversion) → OCR → AI analysis (text, photo, font, alignment, structure, quality; unusual patterns, blur regions, manipulation) → comparison & detection (compare sections; inconsistencies in font, alignment, quality) → result (Genuine/No suspicious modification vs Suspicious; **highlight suspicious areas with reason**) → output to user.
- **Slide 6 Use cases (Owner):** Upload Document, Preview Document, Start Verification, View Result; Start Verification «include» Extract Text (OCR), Analyze Document, AI/ML Verification.
- **Slide 7 ERD:** OWNER(owner_id, name, email, phone, password) 1—M DOCUMENT(document_id, file_path, document_type, uploaded_at) 1—1 ANALYSIS_RESULT(result_id, result_label, confidence_score, highlighted_area, analysis_time).
- **Slide 8 Proposed system:** Owner → Web UI (upload & preview) → Flask → OCR & image analysis → AI/ML verification → Result → Database.
- **Slides 9–12:** user, functional, non-functional (accuracy/consistency, performance, usability, security, privacy, maintainability, scalability) and external interface requirements.

### 2.2 Technical implementation decisions (not in SRS — documented choices)
| Decision | Reason |
|----------|--------|
| Owner registration/login (Flask-Login, hashed passwords) | ERD has OWNER with `password`; needed so owners only see their own documents. |
| Added `inconclusive` outcome | Safety: avoid forced binary labels on unreadable/low-quality input. |
| ERD `confidence_score` implemented as `indicator_score` | It is a rule-weight sum, not a calibrated confidence. Renamed to avoid a misleading claim. |
| Extra `findings` table (ANALYSIS_RESULT 1—M FINDING) | Slide 4 says DB stores "findings data"; the ERD's single `highlighted_area` cannot hold structured evidence. |
| Extra document metadata (sha256, size, dims, status, original name) | Upload metadata + processing status. |
| SQLite default, MySQL via `DATABASE_URL` (PyMySQL) | SRS lists both. Schema created by `flask --app run init-db` (SQLAlchemy `create_all`), no Alembic yet. |
| Uploads stored in `instance/uploads/` (not `static/`) and served only through an owner-checked route | Privacy NFR. |
| Retention: `RETENTION_DAYS` + `flask --app run purge-expired` | Privacy NFR — limit how long ID images and OCR text are kept. |
| Synchronous verification inside the request | Simple; adequate for single-user academic deployment. Revisit if processing > ~30 s. |
| `opencv-python-headless` | No GUI needed; avoids Qt dependencies on Windows/servers. |

### 2.3 Proposed enhancements (NOT implemented — need approval/prioritisation)
- Train a real ML classifier once a **labelled, authorised dataset** of genuine and altered documents exists. Use `flask --app run export-features` to build the feature table; evaluate with a held-out set before replacing/augmenting the rule engine. Record model version, data, metrics in docs.
- Template comparison per document type ("Original Pattern" vs "Uploaded Document" on slide 5) — needs reference templates for each document type.
- Copy-move detection, font-identity analysis, MRZ/QR/checksum validation (e.g. Aadhaar Verhoeff, PAN format).
- Login rate limiting, account lockout, password reset, Alembic migrations, async job queue.

---

## 3. Technology stack (do not substitute without documenting why)

- **Frontend:** HTML5, CSS3, vanilla JavaScript (no React/Vue/Node build step). Jinja2 templates rendered by Flask.
- **Backend:** Python 3.10+ (developed/tested on 3.12), Flask 3.x, Flask-SQLAlchemy, Flask-Login, Flask-WTF (CSRF + forms).
- **Image processing:** OpenCV (`opencv-python-headless`), NumPy. **Pandas** for the feature table used by the classifier and feature export.
- **OCR:** Tesseract OCR binary + `pytesseract`. Binary path configurable via `TESSERACT_CMD` (Windows).
- **Database:** SQLite (default/dev), MySQL 8 (production, `mysql+pymysql://...`).
- **AI/ML:** `app/services/classifier.py` — `DocumentClassifier` interface; current implementation `RuleBasedClassifier` (versioned).
- **Dev environment:** VS Code, Windows 10/11 and Linux. No Docker, no cloud services, no paid APIs.

---

## 4. Architecture

```
run.py                         Flask entrypoint (app factory)
app/
  __init__.py                  create_app(): config, extensions, blueprints, error handlers, security headers, CLI
  config.py                    Env-driven config classes (development / testing / production)
  extensions.py                db, login_manager, csrf
  models.py                    Owner, Document, AnalysisResult, Finding (+ enums)
  forms.py                     WTForms: register, login, upload, simple POST (CSRF-only) form
  cli.py                       init-db, purge-expired, export-features
  routes/
    auth.py                    /auth/register, /auth/login, /auth/logout
    main.py                    / (dashboard), /health
    documents.py               /documents/upload, /documents/<id>, /<id>/image, /<id>/verify, /<id>/delete
  services/
    document_validation.py     extension, magic-byte MIME sniffing, decode, dimension & pixel limits
    storage.py                 safe filenames, save/load/delete inside UPLOAD_FOLDER only
    image_preprocessing.py     EXIF orientation, resize, document crop (perspective), deskew, denoise; keeps a 3x3 transform back to original coords
    ocr_service.py             Tesseract word-level OCR with confidences; typed errors
    analysis/
      common.py                Finding dataclass, severity/kind enums, tiling + robust statistics helpers
      thresholds.py            ALL tunable numbers, named and commented
      quality.py               global blur, brightness, contrast, resolution, OCR readability
      text_alignment.py        line-angle deviation & off-baseline words from OCR boxes
      blur_regions.py          localized sharpness inconsistencies
      photograph.py            face/photo detection, photo blur & sharpness/noise consistency
      alteration.py            noise-level inconsistency + JPEG error level analysis (ELA)
    classifier.py              feature table (pandas) + RuleBasedClassifier -> label, score, reasons
    verification_service.py    orchestrates the pipeline, persists results, handles partial failures
    retention.py               purge expired uploads / OCR text
  templates/                   base, auth/*, dashboard, upload, document, errors/error
  static/css, static/js        style.css, upload.js (client preview), document.js (highlight overlay)
tests/
  unit/                        pure-function tests (validation, preprocessing, analysis, classifier, OCR parsing)
  integration/                 Flask client + DB workflows, real-Tesseract test (skipped if binary missing)
instance/                      runtime: app.db, uploads/ (git-ignored)
docs/                          requirements_traceability.md, technical.md
```

**Data flow:** browser form (multipart POST + CSRF) → `documents.upload` → `document_validation`
→ `storage.save` → `Document(status=uploaded)` → detail page (preview via owner-checked image route)
→ POST verify → `verification_service.verify_document()` → preprocess → OCR → analyses →
`classifier` → `AnalysisResult` + `Finding` rows → detail page renders result.

**Coordinates:** every analysis returns boxes in its own image space; `image_preprocessing`
exposes the 3x3 transform so `verification_service` maps boxes back to original-image pixels.
Highlighted areas are stored in original-image coordinates and drawn client-side as a CSS overlay.

**Error handling:** services raise typed exceptions (`DocumentValidationError`,
`OcrUnavailableError`, `OcrError`, `AnalysisError`). OCR or analysis failure ⇒ document status
`failed`, no result label shown as success. Error pages never show stack traces or document content.

---

## 5. Coding standards

- PEP 8, type hints on public functions, docstrings on public services/analysis functions.
- Small cohesive functions; analysis modules are **pure** (numpy arrays / dataclasses in, findings out) so they are unit-testable without Flask.
- **No magic numbers**: thresholds go in `analysis/thresholds.py` (or `config.py` for operational limits) with a comment saying what they mean and why.
- Centralised config via environment variables (`.env`, loaded by python-dotenv). No credentials in code.
- Never log document contents, OCR text, file bytes or personal data. Log IDs, sizes, timings, error types.
- Uploaded files: validate server-side, store with random names, never under `static/`, never trust client filename/MIME.
- DB access only through SQLAlchemy ORM (parameterised). No string-built SQL.
- Jinja autoescaping stays on. No `|safe` on user/OCR-derived content. No inline `<script>` (CSP forbids it).
- **No fake results**: no hardcoded labels, no mocked analyses in production code, no invented accuracy metrics. Rule-based findings must be labelled as rule-based.
- Findings must separate **observed evidence** (measured numbers in `evidence`) from **interpretation** (`description`) and state `limitation`.

---

## 6. Testing requirements

- Framework: **pytest**. Synthetic images are generated in `tests/helpers.py` — never commit real identity documents.
- Unit tests: upload validation (good/bad ext, spoofed MIME, corrupt, tiny, oversized, bombs), preprocessing (deskew, transforms), each analysis module (clear vs blurred vs tampered synthetic images), OCR parsing + error mapping (mocked `pytesseract`), classifier decision rules.
- Integration tests: auth, owner isolation (other owner gets 404), upload → verify → result persisted, OCR-unavailable ⇒ `failed`, delete removes file, purge, health endpoint, CSRF enforced in non-test config.
- Real OCR test (`tests/integration/test_real_ocr.py`) is **skipped automatically** if the Tesseract binary is not installed — report skips honestly.
- Fix code, not tests. Never weaken an assertion just to go green.

---

## 7. Development workflow (for Claude Code)

1. Inspect before modifying; read the relevant module and its tests first.
2. Implement incrementally; keep each change scoped to one module/requirement.
3. Run `python -m pytest` after changes; diagnose failures from actual output.
4. Update `docs/requirements_traceability.md` when a requirement's status changes, and `docs/technical.md` / this file when architecture changes.
5. Do not claim a feature works unless a test or a manual run demonstrated it; state what was not verified (e.g. MySQL, Windows) explicitly.
6. Ask the user only when a decision materially blocks safe/correct implementation; otherwise pick a conservative, reversible option and record it in §2.2.

---

## 8. Project commands

Run from the project root with the project's Python environment active
(the user's conda env: `conda activate preeti-env`).

```bash
pip install -r requirements.txt          # runtime deps
pip install -r requirements-dev.txt      # + pytest
cp .env.example .env                     # Windows: copy .env.example .env  — then edit SECRET_KEY etc.
flask --app run init-db                  # create tables (SQLite: instance/app.db)
flask --app run run --debug              # dev server at http://127.0.0.1:5000  (or: python run.py)
python -m pytest                         # all tests
python -m pytest tests/unit -q           # unit tests only
flask --app run purge-expired            # delete uploads/OCR text older than RETENTION_DAYS
flask --app run export-features out.csv  # export classifier feature table (for future ML work)
```

Tesseract must be installed separately (Windows: UB Mannheim installer; set `TESSERACT_CMD`
in `.env` if it is not on PATH). See README.

---

## 9. Security & privacy checklist (implemented unless marked)

- [x] Server-side validation: extension allow-list, magic-byte sniffing, full decode, min/max dimensions, pixel-count cap, `MAX_CONTENT_LENGTH`.
- [x] Random server filenames; path confinement to `UPLOAD_FOLDER`; no public static URL for uploads.
- [x] Owner-scoped access (other owners get 404); login required for every document route.
- [x] CSRF on all state-changing forms (Flask-WTF). Logout is POST.
- [x] Session cookies HttpOnly + SameSite=Lax; `Secure` in production config.
- [x] `SECRET_KEY` from env; production refuses to start without one.
- [x] Security headers (CSP without inline scripts, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, no-store on document images).
- [x] Passwords hashed (Werkzeug scrypt/pbkdf2).
- [x] Generic error pages; no document content/PII in logs.
- [x] Retention purge + owner-initiated delete (file + OCR text + result).
- [ ] Login rate limiting / lockout — **outstanding**.
- [ ] Encryption at rest of uploads — **outstanding** (rely on OS disk encryption for now).
- [ ] Malware scanning of uploads — out of scope (images are fully decoded; non-images rejected).
