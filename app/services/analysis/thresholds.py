"""Every tunable number used by preprocessing, analysis and the rule-based classifier.

These are engineering heuristics chosen from common practice and checked against synthetic
test images (see tests/). They have NOT been calibrated on a labelled dataset of real genuine
and forged documents — no such dataset is available. Change them here only, bump
``RULE_ENGINE_VERSION`` when decision behaviour changes, and record why in the docs.
"""

# --- Preprocessing --------------------------------------------------------------------------
# All analyses run on a copy whose long side is scaled into this range so pixel-based
# thresholds mean the same thing regardless of camera resolution.
ANALYSIS_LONG_SIDE_MIN_PX = 1000
ANALYSIS_LONG_SIDE_MAX_PX = 1600

# Deskew search range and step (degrees). Phone captures are rarely tilted more than this.
DESKEW_MAX_ANGLE_DEG = 10.0
DESKEW_STEP_DEG = 0.5
# Skew below this is left uncorrected (rotation itself resamples and slightly blurs text).
DESKEW_MIN_CORRECTION_DEG = 0.5
# Long side of the thumbnail used for the projection-profile skew search (speed).
DESKEW_SEARCH_LONG_SIDE_PX = 800

# Perspective crop: a detected 4-corner contour must cover this fraction of the frame.
DOCUMENT_QUAD_MIN_AREA_RATIO = 0.25
# ...and less than this (otherwise the document already fills the frame).
DOCUMENT_QUAD_MAX_AREA_RATIO = 0.95

# --- Global image quality -------------------------------------------------------------------
# Laplacian variance on the normalised grayscale image. ~100 is the widely used
# "blurry" cut-off for this measure; below it OCR and fine-detail checks become unreliable.
GLOBAL_BLUR_LAPLACIAN_MIN = 100.0
BRIGHTNESS_MIN = 50.0  # mean gray level (0-255); darker = under-exposed
BRIGHTNESS_MAX = 235.0  # brighter = washed out / over-exposed
CONTRAST_STD_MIN = 25.0  # std of gray levels; lower = flat, low-contrast capture

# --- OCR readability --------------------------------------------------------------------------
OCR_WORD_MIN_CONFIDENCE = 60.0  # per-word conf (0-100) for a word to count as "reliable"
OCR_MIN_RELIABLE_WORDS = 5  # fewer reliable words => document text effectively unreadable
OCR_MEAN_CONFIDENCE_MIN = 55.0  # mean conf over all words below this => poor readability

# --- Tiling for local consistency checks ----------------------------------------------------
TILES_ON_LONG_SIDE = 16
MIN_TILE_PX = 32
# Tile counts as "has content" (text/graphics) when its gray std exceeds this.
CONTENT_TILE_STD_MIN = 12.0
# Minimum number of comparable tiles before local statistics are meaningful.
MIN_TILES_FOR_STATISTICS = 12

# --- Blurred / unclear regions --------------------------------------------------------------
# Gradient magnitude (gray levels per pixel) above which a pixel counts as an edge pixel.
# 20 keeps moderately blurred text (Gaussian sigma ~3) measurable while ignoring sensor noise.
EDGE_GRADIENT_MIN = 20.0
# A tile needs at least this many edge pixels for its sharpness to be measurable.
MIN_EDGE_PIXELS = 40
# Robust z-score (on log Laplacian variance) below which a content tile is "much blurrier"
# than the rest of the document.
BLUR_REGION_Z_THRESHOLD = -3.5
# Tile must also be at least this many times blurrier than the document's median tile.
# On synthetic tests clean documents never drop below ~0.85x of the median; Gaussian blur
# of sigma 1.5 px gives ~2.4x. Gradual focus fall-off is rejected by the z-score (it widens MAD).
BLUR_REGION_MEDIAN_RATIO = 2.0
# Floor for MAD of log-variance so uniform synthetic images do not produce huge z-scores.
BLUR_REGION_MIN_MAD = 0.15
BLUR_REGION_MEDIUM_TILE_COUNT = 2  # >= this many flagged tiles => medium severity

# --- Noise inconsistency (alteration) -------------------------------------------------------
# Pixels with Sobel gradient magnitude below this percentile are treated as "flat" and used
# to estimate sensor/compression noise (edges would dominate otherwise).
NOISE_FLAT_PERCENTILE = 50
# Pixels within this many px of an edge are also excluded: JPEG ringing around text would
# otherwise look like noise.
NOISE_EDGE_EXCLUSION_PX = 3
NOISE_MIN_FLAT_PIXELS = 200
NOISE_Z_THRESHOLD = 4.0
NOISE_MIN_MAD = 0.1  # floor on MAD of log-noise
# Absolute ratio guard: an outlier tile must differ from the median noise by this factor.
NOISE_MIN_RATIO = 2.0
# ...and by at least this many gray levels (differences below ~1 level are quantisation noise).
NOISE_MIN_ABS_DIFF = 1.0
NOISE_MEDIUM_TILE_COUNT = 2

# --- Error level analysis (JPEG only) -------------------------------------------------------
# Deliberately conservative: on text-heavy images ELA varies a lot with content (synthetic tests
# show genuine tiles up to ~5x the median), so only extreme outliers are reported.
ELA_JPEG_QUALITY = 90
ELA_Z_THRESHOLD = 4.0
ELA_MIN_MAD = 0.1  # floor on MAD of log error level
ELA_MIN_RATIO = 6.0
ELA_MEDIUM_TILE_COUNT = 2

# --- Text alignment -------------------------------------------------------------------------
ALIGN_MIN_WORDS_PER_LINE = 3
ALIGN_MIN_LINES = 3
# A text line whose baseline angle differs from the document's dominant angle by more than
# this is flagged. Printed documents have all lines parallel to within a fraction of a degree.
ALIGN_LINE_ANGLE_TOLERANCE_DEG = 1.5
# A word whose bottom edge sits this many median word-heights off its line's fitted baseline.
ALIGN_BASELINE_OFFSET_RATIO = 0.35
# Words are grouped into geometric rows when their vertical centres are within this many
# median word-heights (Tesseract sometimes splits an edited line into separate blocks).
ALIGN_ROW_MERGE_RATIO = 0.6
# Words below OCR_WORD_MIN_CONFIDENCE are still *tested* for baseline offset if above this
# (pasted text is often read with lower confidence, but its box position is still valid);
# the reference baseline is fitted on reliable words only.
ALIGN_CANDIDATE_MIN_CONFIDENCE = 30.0
ALIGN_MEDIUM_COUNT = 2  # >= this many misaligned lines/words => medium severity

# --- Photograph -----------------------------------------------------------------------------
FACE_MIN_SIZE_RATIO = 0.06  # min face side as fraction of the image's short side
# Detected face box is expanded by this factor to approximate the printed photo area.
PHOTO_BOX_EXPANSION = 1.6
PHOTO_BLUR_LAPLACIAN_MIN = 60.0
# Photo sharpness relative to the document's median content-tile sharpness.
PHOTO_SHARPNESS_RATIO_LOW = 0.15
PHOTO_SHARPNESS_RATIO_HIGH = 6.0
PHOTO_NOISE_RATIO_LOW = 0.4
PHOTO_NOISE_RATIO_HIGH = 2.5

# --- Rule-based classifier ------------------------------------------------------------------
RULE_ENGINE_NAME = "rule-based"
RULE_ENGINE_VERSION = "1.0.0"
SEVERITY_WEIGHTS = {"none": 0.0, "low": 1.0, "medium": 2.0, "high": 3.0}
# indicator_score >= SUSPICIOUS => "suspicious"; >= REVIEW => "inconclusive" (manual review).
SCORE_SUSPICIOUS = 4.0
SCORE_REVIEW = 2.0
