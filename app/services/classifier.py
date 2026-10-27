"""Document classification (SRS slide 4: "AI/ML Model – classifies the document as genuine or
suspicious"; slide 6: "AI/ML Verification").

Status: **no trained ML model exists** — no labelled dataset of genuine and altered documents
is available, and training on invented data would produce meaningless accuracy claims.

What is implemented instead:

* ``build_feature_frame`` — a fixed, numeric feature vector (pandas DataFrame) derived from the
  analysis findings. This is the input contract for a future trained model and is exported by
  ``flask --app run export-features`` so a dataset can be assembled.
* ``DocumentClassifier`` — the interface any classifier implements.
* ``RuleBasedClassifier`` — a transparent, versioned decision rule over the findings. Its
  ``indicator_score`` is a sum of severity weights, NOT a probability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import pandas as pd

from .analysis import thresholds as T
from .analysis.common import Category, Finding, Kind, Severity

FEATURE_COLUMNS = [
    "quality_sufficient",
    "ocr_readable",
    "ocr_mean_confidence",
    "ocr_word_count",
    "sharpness_laplacian_var",
    "brightness_mean",
    "contrast_std",
    "photo_detected",
    *[f"{c.value}_indicator_count" for c in Category],
    *[f"{c.value}_indicator_weight" for c in Category],
    "indicator_count",
    "indicator_score",
]


@dataclass
class Decision:
    label: str  # "genuine" | "suspicious" | "inconclusive"
    indicator_score: float
    reasons: list[str] = field(default_factory=list)
    engine_name: str = T.RULE_ENGINE_NAME
    engine_version: str = T.RULE_ENGINE_VERSION


class DocumentClassifier(Protocol):
    name: str
    version: str

    def classify(self, features: pd.DataFrame, findings: list[Finding]) -> Decision: ...


def severity_weight(severity: Severity) -> float:
    return T.SEVERITY_WEIGHTS[severity.value]


def build_feature_frame(
    findings: list[Finding],
    quality_metrics: dict,
    quality_sufficient: bool,
    ocr_readable: bool,
    ocr_mean_confidence: float | None,
    ocr_word_count: int,
) -> pd.DataFrame:
    """One-row DataFrame of numeric features in a fixed column order."""
    indicators = [f for f in findings if f.kind == Kind.INDICATOR]
    row: dict[str, float] = {
        "quality_sufficient": float(quality_sufficient),
        "ocr_readable": float(ocr_readable),
        "ocr_mean_confidence": float(ocr_mean_confidence) if ocr_mean_confidence is not None else 0.0,
        "ocr_word_count": float(ocr_word_count),
        "sharpness_laplacian_var": float(quality_metrics.get("sharpness_laplacian_var", 0.0)),
        "brightness_mean": float(quality_metrics.get("brightness_mean", 0.0)),
        "contrast_std": float(quality_metrics.get("contrast_std", 0.0)),
        "photo_detected": float(
            any(f.category == Category.PHOTOGRAPH and f.code != "photo_not_found" for f in findings)
        ),
    }
    for category in Category:
        in_category = [f for f in indicators if f.category == category]
        row[f"{category.value}_indicator_count"] = float(len(in_category))
        row[f"{category.value}_indicator_weight"] = float(sum(severity_weight(f.severity) for f in in_category))
    row["indicator_count"] = float(len(indicators))
    row["indicator_score"] = float(sum(severity_weight(f.severity) for f in indicators))
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


class RuleBasedClassifier:
    """Transparent decision rule.

    1. If image quality or OCR readability is insufficient → ``inconclusive``
       (poor captures are neither trusted nor accused).
    2. Otherwise sum severity weights of *indicator* findings (quality/info findings excluded):
       score ≥ ``SCORE_SUSPICIOUS`` → ``suspicious``;
       score ≥ ``SCORE_REVIEW``     → ``inconclusive`` (manual review);
       else                          → ``genuine`` (= no suspicious indicators found).
    """

    name = T.RULE_ENGINE_NAME
    version = T.RULE_ENGINE_VERSION

    def classify(self, features: pd.DataFrame, findings: list[Finding]) -> Decision:
        row = features.iloc[0]
        score = float(row["indicator_score"])
        indicators = [f for f in findings if f.kind == Kind.INDICATOR]
        indicator_titles = [f"{f.title} ({f.severity.value})" for f in indicators]

        if not bool(row["quality_sufficient"]) or not bool(row["ocr_readable"]):
            reasons = [
                f.title for f in findings if f.kind == Kind.QUALITY and f.severity != Severity.NONE
            ] or ["Image quality is insufficient for a reliable assessment."]
            reasons = ["The capture quality is too poor for a reliable decision: " + "; ".join(reasons) + "."]
            if indicators:
                reasons.append(
                    "Possible indicators were also measured but are unreliable on a poor capture: "
                    + "; ".join(indicator_titles)
                    + "."
                )
            reasons.append("Retake a clear, well-lit, in-focus photo of the whole document, or verify manually.")
            return self._decision("inconclusive", score, reasons)

        if score >= T.SCORE_SUSPICIOUS:
            return self._decision(
                "suspicious",
                score,
                [
                    f"Indicator score {score:g} reached the 'suspicious' threshold of {T.SCORE_SUSPICIOUS:g}.",
                    "Indicators found: " + "; ".join(indicator_titles) + ".",
                    "Inspect the highlighted areas on the original document before relying on it.",
                ],
            )

        if score >= T.SCORE_REVIEW:
            return self._decision(
                "inconclusive",
                score,
                [
                    f"Indicator score {score:g} is between the review threshold ({T.SCORE_REVIEW:g}) "
                    f"and the suspicious threshold ({T.SCORE_SUSPICIOUS:g}).",
                    "Indicators found: " + "; ".join(indicator_titles) + ".",
                    "Manual review of the highlighted areas is recommended.",
                ],
            )

        reasons = ["The implemented checks found no significant indicators of alteration."]
        if indicators:
            reasons.append(
                "Minor indicator(s) below the review threshold: " + "; ".join(indicator_titles) + "."
            )
        reasons.append(
            "This is not proof of authenticity: the document was not checked against any issuing "
            "authority, and skilled forgeries can pass visual checks."
        )
        return self._decision("genuine", score, reasons)

    def _decision(self, label: str, score: float, reasons: list[str]) -> Decision:
        return Decision(label, score, reasons, self.name, self.version)
