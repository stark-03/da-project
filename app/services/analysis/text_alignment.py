"""Text alignment and document structure (SRS slides 4, 5, 8, 10).

Uses the word boxes from OCR on the deskewed image. On a printed document every text line is
parallel and every word on a line sits on the same baseline. Two measurable deviations:

* **Line angle deviation** — a line tilted relative to the document's dominant line angle.
Line angles use Tesseract's own line grouping (robust to tilt). Baseline offsets use geometric
rows (words grouped by vertical centre), because Tesseract often splits a line containing a
pasted word into separate blocks — which would hide exactly the word we want to measure.

* **Off-baseline word** — a word whose top AND bottom edges are both shifted the same way relative
  to lines fitted through the other words on its line (a common artefact when a word or number is
  pasted over the original). Requiring both edges avoids flagging descenders (g, y, p) or words
  without ascenders, which move only one edge.
"""

from __future__ import annotations

import numpy as np

from ..ocr_service import OcrResult, OcrWord, group_lines
from . import thresholds as T
from .common import Box, Category, Finding, Kind, Severity, round_evidence


def fit_edge(words: list[OcrWord], edge: str = "bottom") -> tuple[float, float]:
    """Least-squares line through word edges: edge_y = slope * center_x + intercept."""
    xs = np.array([w.center_x for w in words], dtype=np.float64)
    ys = np.array([getattr(w, edge) for w in words], dtype=np.float64)
    slope, intercept = np.polyfit(xs, ys, 1)
    return float(slope), float(intercept)


def edge_offset(word: OcrWord, others: list[OcrWord], edge: str) -> float:
    slope, intercept = fit_edge(others, edge)
    return getattr(word, edge) - (slope * word.center_x + intercept)


def shifted_word_offset(word: OcrWord, others: list[OcrWord], tolerance_px: float) -> float | None:
    """Return the shift if both top and bottom edges moved the same way beyond tolerance."""
    top = edge_offset(word, others, "top")
    bottom = edge_offset(word, others, "bottom")
    if np.sign(top) == np.sign(bottom) and min(abs(top), abs(bottom)) > tolerance_px:
        return float(top + bottom) / 2
    return None


def line_box(words: list[OcrWord], label: str) -> Box:
    x0 = min(w.left for w in words)
    y0 = min(w.top for w in words)
    x1 = max(w.left + w.width for w in words)
    y1 = max(w.bottom for w in words)
    return Box(x0, y0, x1 - x0, y1 - y0, label)


def geometric_rows(words: list[OcrWord], median_height: float) -> list[list[OcrWord]]:
    """Group words into rows by vertical centre (independent of Tesseract's block structure)."""
    rows: list[list[OcrWord]] = []
    tolerance = T.ALIGN_ROW_MERGE_RATIO * median_height
    for word in sorted(words, key=lambda w: w.center_y):
        if rows and abs(word.center_y - float(np.median([w.center_y for w in rows[-1]]))) <= tolerance:
            rows[-1].append(word)
        else:
            rows.append([word])
    return [sorted(row, key=lambda w: w.left) for row in rows]


def analyze_text_alignment(ocr: OcrResult) -> list[Finding]:
    reliable = ocr.reliable_words
    lines = [
        sorted(words, key=lambda w: w.left)
        for words in group_lines(reliable).values()
        if len(words) >= T.ALIGN_MIN_WORDS_PER_LINE
    ]
    if len(lines) < T.ALIGN_MIN_LINES:
        return [
            Finding(
                category=Category.TEXT_ALIGNMENT,
                code="alignment_insufficient_text",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Not enough text lines to check alignment",
                description="Alignment checks need several lines of reliably read text.",
                evidence={
                    "usable_lines": len(lines),
                    "minimum_lines": T.ALIGN_MIN_LINES,
                    "minimum_words_per_line": T.ALIGN_MIN_WORDS_PER_LINE,
                },
            )
        ]

    median_height = float(np.median([w.height for w in reliable]))
    fits = [fit_edge(words) for words in lines]
    angles = np.degrees(np.arctan([slope for slope, _ in fits]))
    dominant = float(np.median(angles))

    misaligned_lines: list[tuple[list[OcrWord], float]] = []
    off_baseline: list[tuple[OcrWord, float]] = []
    for words, angle in zip(lines, angles):
        deviation = float(angle - dominant)
        if abs(deviation) > T.ALIGN_LINE_ANGLE_TOLERANCE_DEG:
            misaligned_lines.append((words, deviation))

    # Words on tilted lines are excluded: their offsets are explained by the tilt finding.
    tilted = {id(w) for words, _ in misaligned_lines for w in words}
    tolerance_px = T.ALIGN_BASELINE_OFFSET_RATIO * median_height
    candidates = [
        w
        for w in ocr.words
        if w.confidence >= T.ALIGN_CANDIDATE_MIN_CONFIDENCE and id(w) not in tilted
    ]
    for row in geometric_rows(candidates, median_height):
        if len(row) < T.ALIGN_MIN_WORDS_PER_LINE:
            continue
        for word in row:
            # Leave-one-out: fit the row's reliable words WITHOUT this word, then measure it.
            others = [w for w in row if w is not word and w.confidence >= T.OCR_WORD_MIN_CONFIDENCE]
            if len(others) < 2:
                continue
            offset = shifted_word_offset(word, others, tolerance_px)
            if offset is not None:
                off_baseline.append((word, offset))

    findings: list[Finding] = []
    if misaligned_lines:
        severity = Severity.MEDIUM if len(misaligned_lines) >= T.ALIGN_MEDIUM_COUNT else Severity.LOW
        findings.append(
            Finding(
                category=Category.TEXT_ALIGNMENT,
                code="line_angle_deviation",
                kind=Kind.INDICATOR,
                severity=severity,
                title="Text line(s) not parallel to the rest of the document",
                description=(
                    "These lines are tilted relative to the other lines. Printed documents have parallel "
                    "lines; a tilted line can indicate text that was inserted or re-typed."
                ),
                evidence={
                    "dominant_line_angle_deg": round_evidence(dominant),
                    "tolerance_deg": T.ALIGN_LINE_ANGLE_TOLERANCE_DEG,
                    "deviations_deg": [round_evidence(d) for _, d in misaligned_lines],
                    "lines_checked": len(lines),
                },
                limitation="Curved or folded paper and strong lens distortion can also bend text lines.",
                regions=[line_box(words, "Tilted text line") for words, _ in misaligned_lines],
            )
        )
    if off_baseline:
        severity = Severity.MEDIUM if len(off_baseline) >= T.ALIGN_MEDIUM_COUNT else Severity.LOW
        findings.append(
            Finding(
                category=Category.TEXT_ALIGNMENT,
                code="word_off_baseline",
                kind=Kind.INDICATOR,
                severity=severity,
                title="Word(s) sitting off the text baseline",
                description=(
                    "These words are shifted up or down relative to the other words on the same line, "
                    "which can happen when a word or number is pasted over the original."
                ),
                evidence={
                    "offsets_px": [round_evidence(o, 1) for _, o in off_baseline],
                    "median_word_height_px": round_evidence(median_height, 1),
                    "threshold_ratio": T.ALIGN_BASELINE_OFFSET_RATIO,
                },
                limitation=(
                    "Superscripts, mixed font sizes in a designed layout, and OCR box errors on "
                    "letters with descenders can also trigger this."
                ),
                regions=[
                    Box(w.left, w.top, w.width, w.height, "Word off baseline") for w, _ in off_baseline
                ],
            )
        )
    if not findings:
        findings.append(
            Finding(
                category=Category.TEXT_ALIGNMENT,
                code="alignment_consistent",
                kind=Kind.INFO,
                severity=Severity.NONE,
                title="Text lines are parallel and words share their baselines",
                description="No alignment inconsistencies were found in the reliably read text.",
                evidence={
                    "lines_checked": len(lines),
                    "dominant_line_angle_deg": round_evidence(dominant),
                    "max_line_deviation_deg": round_evidence(float(np.max(np.abs(angles - dominant)))),
                },
                limitation="Only text that OCR read reliably is checked; font identity is not compared.",
            )
        )
    return findings
