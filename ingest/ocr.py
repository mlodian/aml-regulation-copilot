"""OCR path for scanned issuances.

Some regulators publish signed scans with no text layer (SEC MC 16, s. 2018) or with
a poor one (most IC circulars). Pages are rendered at 300 dpi and read with Apple's
Vision framework through `ocrmac`, which runs locally at no cost.

A page is not indexed when either check fails; it goes to data/review/<doc>.json for a
person to check, because a misread digit in a threshold or deadline is worse than a
missing page:

1. Numbers written twice must agree. Philippine regulations spell out their figures,
   "sixty (60) calendar days", "five hundred thousand pesos (PHP500,000.00)", so a
   misread digit shows up as a disagreement between the words and the digits. On
   pages with a clean text layer this never fails (176 pairs, 0 disagreements); on
   the same pages rendered blurred and noisy, OCR disagreements appear.
2. Mean recognition confidence must reach MIN_PAGE_CONFIDENCE. This is a floor for
   pages Vision could not read at all (blank, handwritten, upside down), not a quality
   gate: tested on text-layer pages degraded until a fifth of the words were lost,
   Vision still reported 0.91 to 0.98, and clean pages scored as low as 0.89.

Results are cached per document and keyed on the PDF's SHA-256, so rebuilding the
index is fast and gives the same text every time.
"""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import re

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "processed" / "ocr"
REVIEW = ROOT / "data" / "review"
DPI = 300
MIN_PAGE_CONFIDENCE = 0.80


@dataclass
class OcrLine:
    text: str
    confidence: float
    top: float      # distance from the top of the page, 0..1
    left: float
    height: float   # line height as a share of the page height


def _recognize(page: pymupdf.Page) -> list[OcrLine]:
    from ocrmac import ocrmac  # macOS only; imported lazily so other platforms can still read text PDFs
    from PIL import Image

    image = Image.open(io.BytesIO(page.get_pixmap(dpi=DPI).tobytes("png")))
    results = ocrmac.OCR(image, recognition_level="accurate", language_preference=["en-US"]).recognize()
    # Vision boxes are (x, y, w, h) with the origin at the bottom-left
    return [OcrLine(text, float(conf), 1 - (y + h), x, h) for text, conf, (x, y, w, h) in results]


def _reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    """Top to bottom; boxes whose tops are within half a line height share a row, left to right."""
    lines = sorted(lines, key=lambda l: l.top)
    rows: list[list[OcrLine]] = []
    for line in lines:
        if rows and abs(rows[-1][0].top - line.top) < 0.5 * line.height:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [l for row in rows for l in sorted(row, key=lambda l: l.left)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ocr_pages(pdf: Path) -> list[dict]:
    """Per-page OCR result for the whole document: {page, confidence, lines}. Cached."""
    digest = _sha256(pdf)
    cache = CACHE / f"{pdf.stem}.json"
    if cache.exists():
        cached = json.loads(cache.read_text())
        if cached.get("sha256") == digest:
            return cached["pages"]
    doc = pymupdf.open(pdf)
    pages = []
    for idx in range(len(doc)):
        lines = _reading_order(_recognize(doc[idx]))
        conf = sum(l.confidence for l in lines) / len(lines) if lines else 0.0
        pages.append({"page": idx + 1, "confidence": round(conf, 4),
                      "lines": [{"text": l.text, "confidence": round(l.confidence, 3),
                                 "height": round(l.height, 5)} for l in lines]})
    CACHE.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"sha256": digest, "dpi": DPI, "pages": pages}))
    return pages


_UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
          "fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_VALUE = {w: i for i, w in enumerate(_UNITS)} | {w: 20 + 10 * i for i, w in enumerate(_TENS)}
_NUMBER_WORDS = r"(?:\b(?:%s|hundred|thousand|million|and)\b[ -]*)+" % "|".join(sorted(_VALUE, key=len, reverse=True))
# "sixty (60)", "thirty-one (31)", "five hundred thousand pesos (PHP500,000.00)"
NUMBER_PAIR = re.compile(r"(" + _NUMBER_WORDS + r")(?:pesos\s*)?\(\s*(?:PHP|P|Php)?\s*([^)\s]{1,16})\s*\)", re.I)


def _words_to_int(words: str) -> int:
    total = current = 0
    for w in re.findall(r"[a-z]+", words.lower()):
        if w in _VALUE:
            current += _VALUE[w]
        elif w == "hundred":
            current *= 100
        elif w in ("thousand", "million"):
            total += current * (1000 if w == "thousand" else 1_000_000)
            current = 0
    return total + current


def number_disagreements(text: str) -> list[str]:
    """Spelled-out numbers whose digits in brackets say something else, e.g. 'sixty (80)'."""
    bad = []
    for m in NUMBER_PAIR.finditer(text):
        spelled = _words_to_int(m.group(1))
        if spelled == 0 and "zero" not in m.group(1).lower():
            continue  # only "and"
        digits = re.sub(r"[,]|\.00$", "", m.group(2))
        if not (digits.isdigit() and int(digits) == spelled):
            bad.append(m.group(0).strip())
    return bad


def gate(pages: list[dict], min_confidence: float = MIN_PAGE_CONFIDENCE) -> tuple[list[dict], list[dict]]:
    """Split pages into (indexable, for review); a page for review gets a `reason`. Blank pages are neither."""
    keep, review = [], []
    for p in pages:
        if not p["lines"]:
            continue
        mismatched = number_disagreements(" ".join(l["text"] for l in p["lines"]))
        if mismatched:
            review.append({**p, "reason": "numbers disagree: " + "; ".join(mismatched)})
        elif p["confidence"] < min_confidence:
            review.append({**p, "reason": f"confidence {p['confidence']:.2f} below {min_confidence:.2f}"})
        else:
            keep.append(p)
    return keep, review


def write_review(doc_id: str, review: list[dict]) -> Path | None:
    path = REVIEW / f"{doc_id}.json"
    if not review:
        path.unlink(missing_ok=True)
        return None
    REVIEW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"page": p["page"], "confidence": p["confidence"], "reason": p.get("reason", ""),
                                 "text": "\n".join(l["text"] for l in p["lines"])} for p in review], indent=2))
    return path
