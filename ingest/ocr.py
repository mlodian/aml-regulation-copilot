"""OCR path for scanned issuances.

Some regulators publish signed scans with no text layer (SEC MC 16, s. 2018) or with
a poor one (most IC circulars). Pages are rendered at 300 dpi and read with Apple's
Vision framework through `ocrmac`, which runs locally at no cost.

Every page gets a mean recognition confidence. A page below MIN_PAGE_CONFIDENCE is
not indexed: it goes to data/review/<doc>.json for a person to check, because a
misread digit in a threshold or deadline is worse than a missing page.

Results are cached per document and keyed on the PDF's SHA-256, so rebuilding the
index is fast and gives the same text every time.
"""
from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

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


def gate(pages: list[dict], min_confidence: float = MIN_PAGE_CONFIDENCE) -> tuple[list[dict], list[dict]]:
    """Split pages into (indexable, for review). Blank pages are neither."""
    keep, review = [], []
    for p in pages:
        if not p["lines"]:
            continue
        (keep if p["confidence"] >= min_confidence else review).append(p)
    return keep, review


def write_review(doc_id: str, review: list[dict]) -> Path | None:
    path = REVIEW / f"{doc_id}.json"
    if not review:
        path.unlink(missing_ok=True)
        return None
    REVIEW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([{"page": p["page"], "confidence": p["confidence"],
                                 "text": "\n".join(l["text"] for l in p["lines"])} for p in review], indent=2))
    return path
