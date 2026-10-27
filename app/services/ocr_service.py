"""Text extraction with Tesseract OCR (SRS slide 5 step 3, use case "Extract Text (OCR)").

OCR only extracts text and word positions; it does not establish authenticity. Word boxes and
confidences feed the readability and text-alignment checks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pytesseract
from pytesseract import Output

from .analysis import thresholds as T

logger = logging.getLogger(__name__)

# --oem 3: default LSTM engine; --psm 3: automatic page segmentation (no orientation detection).
TESSERACT_CONFIG = "--oem 3 --psm 3"


class OcrError(Exception):
    """OCR ran but failed. Message is safe to show to the user."""


class OcrUnavailableError(OcrError):
    """The Tesseract binary is not installed or not configured."""


@dataclass
class OcrWord:
    text: str
    confidence: float  # 0-100
    left: int
    top: int
    width: int
    height: int
    line_key: tuple[int, int, int]  # (block, paragraph, line) from Tesseract layout analysis

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


@dataclass
class OcrResult:
    text: str
    words: list[OcrWord] = field(default_factory=list)
    mean_confidence: float | None = None
    engine: str = "tesseract"

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def reliable_words(self) -> list[OcrWord]:
        return [w for w in self.words if w.confidence >= T.OCR_WORD_MIN_CONFIDENCE]


class OcrService:
    def __init__(self, tesseract_cmd: str | None = None, lang: str = "eng", timeout: int = 60):
        self.tesseract_cmd = tesseract_cmd
        self.lang = lang
        self.timeout = timeout

    @classmethod
    def from_config(cls, config) -> "OcrService":
        return cls(config.get("TESSERACT_CMD"), config["OCR_LANG"], config["OCR_TIMEOUT_SECONDS"])

    def _configure(self) -> None:
        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd

    def engine_version(self) -> str:
        """Return the Tesseract version, or raise OcrUnavailableError."""
        self._configure()
        try:
            return str(pytesseract.get_tesseract_version())
        except (pytesseract.TesseractNotFoundError, OSError) as exc:
            raise OcrUnavailableError(
                "Tesseract OCR is not installed or TESSERACT_CMD is not set correctly."
            ) from exc

    def extract(self, gray: np.ndarray) -> OcrResult:
        """Run OCR on a preprocessed grayscale image."""
        self._configure()
        try:
            data = pytesseract.image_to_data(
                gray,
                lang=self.lang,
                config=TESSERACT_CONFIG,
                output_type=Output.DICT,
                timeout=self.timeout,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError(
                "Tesseract OCR is not installed or TESSERACT_CMD is not set correctly."
            ) from exc
        except pytesseract.TesseractError as exc:
            logger.warning("Tesseract failed (status=%s)", getattr(exc, "status", "?"))
            raise OcrError(
                f"Text extraction failed. Check that the OCR language '{self.lang}' is installed."
            ) from exc
        except RuntimeError as exc:  # pytesseract raises RuntimeError on timeout
            raise OcrError("Text extraction timed out.") from exc

        version = self._safe_version()
        return parse_tesseract_data(data, engine=f"tesseract {version}" if version else "tesseract")

    def _safe_version(self) -> str | None:
        try:
            return str(pytesseract.get_tesseract_version())
        except Exception:  # version is informational only
            return None


def parse_tesseract_data(data: dict, engine: str = "tesseract") -> OcrResult:
    """Convert pytesseract's ``image_to_data`` dict into words + line-structured text."""
    words: list[OcrWord] = []
    for i, raw_text in enumerate(data.get("text", [])):
        text = (raw_text or "").strip()
        try:
            confidence = float(data["conf"][i])
        except (KeyError, ValueError, TypeError):
            continue
        if not text or confidence < 0:  # conf -1 marks non-word layout entries
            continue
        words.append(
            OcrWord(
                text=text,
                confidence=confidence,
                left=int(data["left"][i]),
                top=int(data["top"][i]),
                width=int(data["width"][i]),
                height=int(data["height"][i]),
                line_key=(int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i])),
            )
        )

    mean_conf = float(np.mean([w.confidence for w in words])) if words else None
    return OcrResult(text=words_to_text(words), words=words, mean_confidence=mean_conf, engine=engine)


def group_lines(words: list[OcrWord]) -> dict[tuple[int, int, int], list[OcrWord]]:
    lines: dict[tuple[int, int, int], list[OcrWord]] = {}
    for word in words:
        lines.setdefault(word.line_key, []).append(word)
    return lines


def words_to_text(words: list[OcrWord]) -> str:
    """Rebuild readable text: one output line per Tesseract line, blank line between blocks."""
    out: list[str] = []
    previous_block = None
    for key, line_words in group_lines(words).items():
        if previous_block is not None and key[0] != previous_block:
            out.append("")
        out.append(" ".join(w.text for w in sorted(line_words, key=lambda w: w.left)))
        previous_block = key[0]
    return "\n".join(out)
