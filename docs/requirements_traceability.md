# Requirements Traceability — AI Rental Scam Detector

Source: `SRS.pptx` (13 slides). Slide 1 is the title slide and slide 13 says "Thank You";
neither contains requirements.
Status values: **Done** (implemented and covered by an automated test or a recorded manual run),
**Partial** (implemented with a documented gap), **Not done** (documented, not implemented),
**N/A** (environmental, not software).

Last updated: 2026-10-15 · Test run: 114 passed (with Tesseract 5.5.3), 112 passed + 2 skipped (without).

## 1. Requirements stated in the SRS

### Slide 2 — Software requirements
| ID | Requirement | Category | Implementation | Verification | Status |
|----|-------------|----------|----------------|--------------|--------|
| SW-1 | OS: Windows 10/11 | Platform | Pure-Python code, no OS-specific APIs, `opencv-python-headless`, `TESSERACT_CMD` for the Windows path, Windows setup in README | Not executed on Windows; tested on Linux | **Partial** — not yet run on Windows |
| SW-2 | Frontend: HTML5, CSS3, JavaScript | Tech | Jinja templates, `static/css/style.css`, `static/js/*.js` (vanilla) | Playwright screenshots at 1280 px and 375 px, no console errors | Done |
| SW-3 | Backend: Python | Tech | Flask app in `app/` | Test suite | Done |
| SW-4 | AI/Image processing: OpenCV | Tech | `image_preprocessing.py`, `analysis/*` | Unit tests | Done |
| SW-5 | OCR: Tesseract OCR | Tech | `ocr_service.py` (pytesseract) | `test_ocr_service.py`, `test_real_ocr.py` | Done |
| SW-6 | Database: MySQL, SQLite | Tech | SQLAlchemy. SQLite by default, MySQL via `DATABASE_URL` + PyMySQL | SQLite: integration tests. MySQL: not run against a live server | **Partial** — MySQL untested |
| SW-7 | Browser: Chrome, Firefox | Platform | Standard HTML/CSS/JS, no browser-specific features | Chrome (headless) verified | Partial — Firefox not run |

### Slide 3 — Hardware requirements
| ID | Requirement | Implementation | Status |
|----|-------------|----------------|--------|
| HW-1 | Intel Core i5 processor | A ~1400×900 image is analysed in about 0.6–0.8 s on the dev machine | N/A |
| HW-2 | 8 GB RAM recommended | Images are capped at 50 MP and analysed at ≤1600 px | N/A |
| HW-3 | 10 GB free storage | Uploads ≤ 8 MB each, purged after `RETENTION_DAYS` | N/A |
| HW-4 | Standard HD monitor | Responsive layout from 360 px up | N/A |
| HW-5 | Mobile camera for capturing clear images | The `accept="image/jpeg,image/png"` file input offers the camera on phones. EXIF orientation is applied. Perspective correction handles angled captures | Done (`test_exif_orientation_is_applied`, `test_ocr_image_is_grayscale_and_document_outline_detected`) |
| HW-6 | Internet for accessing the web-based system | Web app over HTTP(S). OCR and analysis run locally with no external calls | N/A |

### Slide 4 — Tools & technologies
| ID | Requirement | Implementation | Verification | Status |
|----|-------------|----------------|--------------|--------|
| TT-1 | Python for backend logic and AI/ML | `app/` | Tests | Done |
| TT-2 | Flask connects UI and backend | `app/__init__.py`, `routes/` | Integration tests | Done |
| TT-3 | HTML/CSS/JS for upload, preview and result dashboard | `upload.html` + `upload.js`, `document.html` + `document.js`, `dashboard.html` | Manual browser run + tests | Done |
| TT-4 | Tesseract extracts text from the document image | `ocr_service.py` | `test_real_ocr.py` | Done |
| TT-5 | OpenCV for alignment, blur and photograph checks | `text_alignment.py` (uses OCR boxes on the OpenCV-deskewed image), `blur_regions.py`, `photograph.py` | `test_analysis.py` | Done |
| TT-6 | Pandas, NumPy for data handling | NumPy throughout. Pandas for the classifier feature table and `export-features` | `test_classifier.py`, `test_cli_init_db_and_export` | Done |
| TT-7 | AI/ML model classifies the document as genuine or suspicious | `classifier.py`: `DocumentClassifier` interface + `RuleBasedClassifier`. **No trained model** (no dataset) | `test_classifier.py` | **Partial** — rule-based. See §3 |
| TT-8 | MySQL/SQLite stores owner, document, verification and findings data | Tables `owners`, `documents`, `analysis_results`, `findings` | `test_verify_persists_result_findings_and_ocr` | Done (SQLite) |
| TT-9 | Visual Studio Code as development environment | Plain project layout. `.vscode/` git-ignored | — | N/A |

### Slide 5 — Methodology diagram
| ID | Step / requirement | Implementation | Verification | Status |
|----|--------------------|----------------|--------------|--------|
| ME-1 | Owner captures the document with a phone or uploads an existing image | Upload form (camera on mobile) | Upload tests | Done |
| ME-2 | Supported documents: Aadhaar, PAN, Voter ID, Driving Licence, etc. | `DocumentType` enum + "Rental agreement" and "Other". The analysis is generic across types | `test_invalid_document_type_rejected` | Done (no per-type logic — see ME-9) |
| ME-3 | Pre-processing: resizing and noise removal | `scale_factor_for`, `fastNlMeansDenoising` | `test_preprocessing.py` | Done |
| ME-4 | Enhancement of image quality | CLAHE contrast enhancement, deskew, perspective correction | `test_skew_is_estimated` | Done |
| ME-5 | Conversion to a format suitable for analysis | Grayscale working copies, alpha flattened, EXIF-normalised | `test_transparent_png_flattened_on_white` | Done |
| ME-6 | OCR extracts text into an editable, analysable format | Text + word boxes and confidences, stored and displayed | `test_parse_tesseract_data_builds_words_and_text` | Done |
| ME-7 | AI analysis of text, photo, font, alignment, structure and quality | Alignment, blur regions, photo, noise/ELA, quality. **Font identity is not analysed** | `test_analysis.py` | **Partial** — no font analysis |
| ME-8 | Detects unusual patterns, blur regions and digital manipulation | `localized_blur`, `noise_inconsistency`, `ela_inconsistency` | `test_locally_blurred_region_detected_and_located`, `test_pasted_clean_region_detected` | Done (rule-based, synthetic-validated only) |
| ME-9 | Comparison & detection: "Original Pattern" vs "Uploaded Document" | Sections are compared *within* the document (tile statistics, line/baseline consistency). **No reference template comparison** — no templates are available | — | **Partial** |
| ME-10 | Identifies inconsistencies in font, alignment and image quality | Alignment and image quality: done. Font: not done | Tests above | Partial |
| ME-11 | Result: Genuine / No suspicious modification vs Suspicious/Scam document | `genuine` / `suspicious`, plus `inconclusive` (see §2 D-2) | `test_clean_document_is_genuine_and_tampered_is_flagged` | Done |
| ME-12 | Highlights the suspicious areas with reasons | `highlighted_area` boxes drawn over the preview, numbered legend, per-finding descriptions | Integration test + screenshot | Done |
| ME-13 | Output: easy to understand, highlighted areas, helps the owner act | Verdict panel, "Why this result", tips, limitations, About page | Screenshot review | Done |

### Slide 6 — Use case diagram (actor: Owner)
| ID | Use case | Implementation | Verification | Status |
|----|----------|----------------|--------------|--------|
| UC-1 | Upload Document | `POST /documents/upload` | `test_upload_valid_image` | Done |
| UC-2 | Preview Document | Client preview before upload. Server preview through `GET /documents/<id>/image` (owner only) | `test_detail_page_shows_preview_and_verify_button`, `test_image_route_serves_private_file_with_no_store` | Done |
| UC-3 | Start Verification | `POST /documents/<id>/verify` | `test_verify_persists_result_findings_and_ocr` | Done |
| UC-4 | View Result | `GET /documents/<id>` result section | same + screenshot | Done |
| UC-5 | «include» Extract Text (OCR) | `run_pipeline` → `OcrService.extract` | `test_full_workflow_with_real_ocr` | Done |
| UC-6 | «include» Analyze Document | `run_pipeline` → analysis modules | Integration tests | Done |
| UC-7 | «include» AI/ML Verification | `run_pipeline` → `RuleBasedClassifier` | `test_classifier.py` | Partial (rule-based) |

### Slide 7 — Entity relationship diagram
| ID | Entity / attribute | Implementation | Status |
|----|--------------------|----------------|--------|
| ER-1 | OWNER(owner_id PK, name, email, phone, password) | `owners` table. The password is stored as a hash in `password_hash` | Done |
| ER-2 | DOCUMENT(document_id PK, file_path, document_type, uploaded_at) | `documents` table + upload metadata | Done |
| ER-3 | OWNER 1—M DOCUMENT ("uploads") | `documents.owner_id` FK | Done |
| ER-4 | ANALYSIS_RESULT(result_id PK, result_label, confidence_score, highlighted_area, analysis_time) | `analysis_results`. `confidence_score` → `indicator_score` (see D-3). `highlighted_area` is JSON | Done (renamed column) |
| ER-5 | DOCUMENT 1—1 ANALYSIS_RESULT ("has") | Unique FK `analysis_results.document_id`. Re-verification replaces the result | Done (`test_reverification_replaces_result`) |

### Slide 8 — Proposed system
| ID | Requirement | Implementation | Status |
|----|-------------|----------------|--------|
| PS-1 | Owner uploads an identity/rental document and the system verifies it automatically | Upload → one-click verification | Done |
| PS-2 | Checks text alignment, blurred regions, photograph quality and possible alterations | Four analysis modules | Done (rule-based) |
| PS-3 | Result shown on a simple dashboard as genuine or suspicious | Dashboard + detail page | Done |
| PS-4 | Verification records and findings stored in the database | `analysis_results` + `findings` | Done |
| PS-5 | Architecture: Web UI → Flask → OCR & image analysis → AI/ML → Result → DB | Matches `verification_service.run_pipeline` | Done |

### Slide 9 — User requirements (the owner is able to…)
| ID | Requirement | Status |
|----|-------------|--------|
| UR-1 | Access the system through a web interface | Done |
| UR-2 | Upload or select a clear identity document image | Done |
| UR-3 | Preview the uploaded document | Done |
| UR-4 | Start document verification | Done |
| UR-5 | View detected text and document analysis | Done |
| UR-6 | View the final genuine/suspicious result | Done |
| UR-7 | Understand the result through a simple dashboard | Done — includes reasons, highlighted areas, an About page and label definitions |

### Slide 10 — Functional requirements
| ID | Requirement | Implementation | Test | Status |
|----|-------------|----------------|------|--------|
| FR-1 | Accept an identity/rental document image as input | Upload route | `test_upload_valid_image` | Done |
| FR-2 | Validate and preview the uploaded document | `document_validation.py`, preview | `test_document_validation.py`, `test_invalid_uploads_rejected` | Done |
| FR-3 | Extract document text using OCR | `ocr_service.py` | `test_real_ocr.py` | Done |
| FR-4 | Analyse text alignment and document structure | `text_alignment.py` | `test_shifted_word_detected`, `test_tilted_line_detected` | Done |
| FR-5 | Check blurred, unclear or inconsistent regions | `blur_regions.py`, `quality.py` | `test_locally_blurred_region_detected_and_located` | Done |
| FR-6 | Analyse photograph quality and possible alterations | `photograph.py`, `alteration.py` | `test_blurry_photo_region_flagged_as_quality`, `test_photo_noise_mismatch_detected`, `test_pasted_clean_region_detected` | Done. Face detection was only checked on the no-face path (no synthetic face) |
| FR-7 | Apply AI/ML-based document analysis | Rule-based classifier + ML-ready feature table | `test_classifier.py` | **Partial** (§3) |
| FR-8 | Display the verification result and relevant findings | `document.html` | Integration tests + screenshots | Done |

### Slide 11 — Non-functional requirements
| ID | Requirement | Implementation | Status |
|----|-------------|----------------|--------|
| NFR-1 | Accuracy: consistent document-level analysis | Deterministic pipeline: the same image always gives the same result. A versioned engine (`engine_version` is stored). **Accuracy on real documents has not been measured** | Partial |
| NFR-2 | Performance: process a valid document in reasonable time | ~0.6–0.8 s for 1400×900 on the dev machine. OCR timeout is configurable | Done |
| NFR-3 | Usability: simple, user-friendly interface | Two-step flow, client preview, capture tips, responsive layout | Done |
| NFR-4 | Security: protect uploaded document information | Private storage, owner checks, CSRF, CSP, hashed passwords, validation (see `technical.md` §Security) | Done (rate limiting outstanding) |
| NFR-5 | Privacy: avoid unnecessary exposure of identity documents | No public URLs, `no-store`, no PII in logs, retention purge, owner delete | Done |
| NFR-6 | Maintainability: easy updates to verification logic | Independent pure analysis modules, every threshold in `thresholds.py`, versioned engine, `DocumentClassifier` interface | Done |
| NFR-7 | Scalability: support more document types in future | `DocumentType` enum. The analysis does not depend on the type | Done |

### Slide 12 — External interface requirements
| ID | Requirement | Status |
|----|-------------|--------|
| EI-1 | UI: web-based document verification dashboard | Done |
| EI-2 | UI: document upload and image preview | Done |
| EI-3 | UI: verify button and analysis-result display | Done |
| EI-4 | UI: text and document-quality findings | Done |
| EI-5 | Software: Flask backend, Python OCR/image-processing modules and AI/ML model | Done (rule-based model) |
| EI-6 | Hardware: camera or mobile device may be used to capture the image | Done (file input offers the camera, EXIF and perspective handling) |

## 2. Implementation decisions (not in the SRS)
| ID | Decision | Reason |
|----|----------|--------|
| D-1 | Owner registration/login | The ERD has OWNER with a password. Needed to keep each owner's documents private |
| D-2 | Third outcome `inconclusive` | Safety: unreadable or low-quality captures and mixed evidence must not be forced into Genuine/Suspicious |
| D-3 | `confidence_score` implemented as `indicator_score` | The value is a sum of rule weights, not a calibrated confidence. Renamed so it isn't misread as one |
| D-4 | Extra `findings` table | Slide 4 requires storing "findings data" |
| D-5 | Retention purge (`RETENTION_DAYS`, default 30) | Privacy NFR |
| D-6 | Schema creation via `create_all` (`flask --app run init-db`), no Alembic | Simplicity for an academic project. Add Alembic before changing the schema in production |
| D-7 | Synchronous verification | About 1 s per document. A job queue would be unnecessary complexity |

## 3. Ambiguities, gaps and proposed enhancements (need approval)
| ID | Item | Notes |
|----|------|-------|
| A-1 | **AI/ML model**: the SRS names a model but no model, dataset or training procedure exists | A rule engine is used instead and labelled as such. Next step: collect an authorised, labelled dataset of genuine and altered documents, export features (`export-features`), train and evaluate on a held-out set, then add a `ModelClassifier` implementing `DocumentClassifier`. Record the data source, metrics and model version |
| A-2 | "Original Pattern" comparison (slide 5) needs reference templates per document type | Not available. Proposed as an enhancement |
| A-3 | Font analysis (slide 5) | Not implemented. Needs font-feature extraction and per-type references |
| A-4 | No authentication rules in the SRS beyond ERD attributes | Implemented basic owner auth. Password reset, rate limiting and lockout are outstanding |
| A-5 | Retention period not specified | Defaulted to 30 days, configurable |
| A-6 | Windows and MySQL execution not yet verified | Run the README steps on Windows with MySQL and record the results here |
