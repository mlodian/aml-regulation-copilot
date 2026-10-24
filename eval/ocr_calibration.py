"""Calibrate the OCR review gate against ground truth.

Pages that have a clean text layer are rendered as images at decreasing quality
(lower resolution; blur plus noise), read with the same Vision OCR as the scanned
issuances, and compared word by word with their text layer. The report shows how
well each candidate signal predicts a bad page:

- Vision's mean line confidence (the original gate, MIN_PAGE_CONFIDENCE);
- number-pair agreement: a spelled-out number and the digits after it ("sixty (60)")
  must say the same thing (ingest.ocr.number_disagreements).

A page counts as bad when it loses more than 5% of its words. Writes
eval/reports/ocr_calibration.json. macOS only (Vision); about ten minutes.
"""
from __future__ import annotations

import collections
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.ocr import MIN_PAGE_CONFIDENCE, NUMBER_PAIR, number_disagreements  # noqa: E402

RAW = ROOT / "data" / "raw"
OUT = ROOT / "eval" / "reports" / "ocr_calibration.json"
PAGES = ([("gotracs2024", p) for p in (5, 12, 20, 28)] + [("dnfbp2021", p) for p in (4, 15, 30)]
         + [("irr2018", p) for p in (10, 40, 80)] + [("bsp_morb_p9", p) for p in (5, 20)])
BAD_WORD_RECALL = 0.95


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def variants(page: pymupdf.Page):
    sharp = Image.open(io.BytesIO(page.get_pixmap(dpi=300).tobytes("png"))).convert("L")
    yield "300 dpi", sharp
    for dpi in (150, 100, 72, 60):
        low = Image.open(io.BytesIO(page.get_pixmap(dpi=dpi).tobytes("png"))).convert("L")
        yield f"{dpi} dpi", low.resize(sharp.size)
    rng = np.random.default_rng(0)
    for sigma, radius in ((40, 1.5), (70, 2.5), (90, 3.2)):
        pixels = np.asarray(sharp.filter(ImageFilter.GaussianBlur(radius)), dtype=float)
        pixels += rng.normal(0, sigma, pixels.shape)
        yield f"blur {radius} + noise {sigma}", Image.fromarray(np.clip(pixels, 0, 255).astype("uint8"))


def main() -> None:
    from ocrmac import ocrmac

    rows = []
    for doc_id, number in PAGES:
        page = pymupdf.open(RAW / f"{doc_id}.pdf")[number - 1]
        truth = collections.Counter(tokens(page.get_text()))
        for name, image in variants(page):
            result = ocrmac.OCR(image, recognition_level="accurate", language_preference=["en-US"]).recognize()
            text = " ".join(t for t, _, _ in result)
            read = collections.Counter(tokens(text))
            rows.append({"doc": doc_id, "page": number, "variant": name,
                         "confidence": round(sum(c for _, c, _ in result) / len(result), 4) if result else 0.0,
                         "word_recall": round(sum((truth & read).values()) / sum(truth.values()), 4),
                         "number_pairs": len(NUMBER_PAIR.findall(text)),
                         "number_disagreements": len(number_disagreements(text))})
            print(rows[-1], flush=True)

    bad = [r for r in rows if r["word_recall"] < BAD_WORD_RECALL]
    conf = np.array([r["confidence"] for r in rows])
    recall = np.array([r["word_recall"] for r in rows])
    rank = lambda a: np.argsort(np.argsort(a))
    text_layer_pairs = text_layer_disagreements = 0
    for doc_id in ("gotracs2024", "irr2018", "bsp_morb_p9", "dnfbp2021"):
        for page in pymupdf.open(RAW / f"{doc_id}.pdf"):
            text = " ".join(page.get_text().split())
            text_layer_pairs += len(NUMBER_PAIR.findall(text))
            text_layer_disagreements += len(number_disagreements(text))
    summary = {
        "pages": len(PAGES), "readings": len(rows), "bad_definition": f"word recall < {BAD_WORD_RECALL}",
        "bad_readings": len(bad),
        "confidence_spearman_with_word_recall": round(float(np.corrcoef(rank(conf), rank(recall))[0, 1]), 3),
        "confidence_range_clean_300dpi": [min(r["confidence"] for r in rows if r["variant"] == "300 dpi"),
                                          max(r["confidence"] for r in rows if r["variant"] == "300 dpi")],
        "confidence_range_bad": [min(r["confidence"] for r in bad), max(r["confidence"] for r in bad)] if bad else None,
        "bad_caught_by_confidence_gate": sum(r["confidence"] < MIN_PAGE_CONFIDENCE for r in bad),
        "number_disagreements_by_variant": {v: sum(r["number_disagreements"] for r in rows if r["variant"] == v)
                                            for v in dict.fromkeys(r["variant"] for r in rows)},
        "text_layer_number_pairs": text_layer_pairs, "text_layer_number_disagreements": text_layer_disagreements,
    }
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
