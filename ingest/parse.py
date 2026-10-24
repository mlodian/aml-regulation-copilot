"""PDF -> clean lines with page numbers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

PAGE_FURNITURE = [
    re.compile(r"^Page \d+ of \d+$"),   # "Page 11 of 106"
    re.compile(r"^\d{1,3}$"),           # bare page numbers
    re.compile(r"^-{2,}\s*\d*$"),       # TOC leaders
]


@dataclass
class Line:
    page: int
    text: str


RUNIN = "§ "  # prefix for a line that opens with a bold run-in subsection title


def read_lines(pdf: Path, first_page: int = 1, last_page: int | None = None,
               min_font: float = 0.0, ocr: bool = False, bold_runin: bool = False) -> list[Line]:
    """Extract non-empty lines (1-indexed, inclusive page range) without headers/footers.

    Spans smaller than `min_font` are dropped. In the IRR that removes footnotes,
    which quote the superseded original wording of amended provisions and would
    otherwise be retrieved as if they were current law.

    With `ocr=True` the text comes from ingest.ocr instead; pages below its confidence
    threshold are left out and listed in data/review/<doc>.json.

    With `bold_runin=True`, a line that starts with an indented bold phrase ending in a
    full stop ("Risk assessment. Consistent with ...", the BSP manual's unnumbered
    subsections) is prefixed with RUNIN so a heading grammar can split on it.
    """
    if ocr:
        return _ocr_lines(pdf, first_page, last_page)
    doc = pymupdf.open(pdf)
    last_page = last_page or len(doc)
    lines: list[Line] = []
    for idx in range(first_page - 1, last_page):
        page_lines: list[tuple[float, str]] = []
        for block in doc[idx].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["size"] >= min_font]
                text = fix_amounts(re.sub(r"\s+", " ", "".join(s["text"] for s in spans)).strip())
                if text and bold_runin and spans and spans[0]["flags"] & 16 and spans[0]["bbox"][0] > 100 \
                        and re.search(r"\w\.(\s|$)", spans[0]["text"]):
                    text = RUNIN + text
                if text:
                    page_lines.append((line["bbox"][1], text))
        for k, (top, text) in enumerate(page_lines):
            # a section number set in the margin ("901") is its own line on the same
            # baseline as its title; join them before bare numbers are dropped as page numbers
            if re.fullmatch(r"\d{3}(?:\.\d+)*", text) and k + 1 < len(page_lines) \
                    and abs(page_lines[k + 1][0] - top) < 2:
                page_lines[k + 1] = (page_lines[k + 1][0], f"{text} {page_lines[k + 1][1]}")
                continue
            if not any(p.match(text) for p in PAGE_FURNITURE):
                lines.append(Line(idx + 1, text))
    return drop_running_headers(lines)


# Peso amounts in old embedded OCR layers: "Php500,OOO.OO" -> "Php500,000.00"
AMOUNT = re.compile(r"(?<=PHP)[\dOSl,.]*\d[\dOSl,.]*|(?<=Php)[\dOSl,.]*\d[\dOSl,.]*")


def fix_amounts(text: str) -> str:
    return AMOUNT.sub(lambda m: m.group(0).translate(str.maketrans("OSl", "051")), text)


EDGE_LINES = 2  # a running header or footer is among the first or last two lines of its page


def drop_running_headers(lines: list[Line], min_share: float = 0.3) -> list[Line]:
    """Remove running headers/footers: a line of 15+ characters repeated on many pages,
    always at the top or bottom of the page.

    "Guidelines on Transaction Reporting and Compliance Submissions (GoTRACS)" sits at
    the top of every GoTRACS page and would otherwise land mid-sentence in the text.
    The page-edge test keeps repeated body text, such as the table note "Fine is on a
    per account basis." that appears mid-page in the administrative sanctions rules.
    """
    by_page: dict[int, list[str]] = {}
    for l in lines:
        by_page.setdefault(l.page, []).append(l.text)
    if len(by_page) < 4:
        return lines
    seen: dict[str, set[int]] = {}
    off_edge: set[str] = set()
    for texts in by_page.values():
        for i, t in enumerate(texts):
            if len(t) < 15:
                continue
            seen.setdefault(t, set())
            if EDGE_LINES <= i < len(texts) - EDGE_LINES:
                off_edge.add(t)
    for l in lines:
        if l.text in seen:
            seen[l.text].add(l.page)
    repeated = {t for t, ps in seen.items() if len(ps) >= max(3, min_share * len(by_page)) and t not in off_edge}
    return [l for l in lines if l.text not in repeated]


# Vision reads roman-numeral markers such as "(ii)" as Cyrillic or Spanish look-alikes
# ("(її)", "(i¡i)") and "(2)" as "(Z)"; the documents are English, so map them back.
HOMOGLYPHS = str.maketrans({"і": "i", "ї": "i", "¡": "i", "І": "I", "Ї": "I", "ӏ": "l", "О": "O", "о": "o"})
MARKER = re.compile(r"^\(?[\w¡]{1,5}[.)]$")


def normalize_ocr(text: str) -> str:
    text = text.translate(HOMOGLYPHS)
    # heading numbers misread as letters: "Section I." (1), "Section S.A.2" (5.A.2), "TITLE I|I" (III)
    text = re.sub(r"^(Section )I(?=\.\s)", r"\g<1>1", text)
    text = re.sub(r"^(Section )S(?=\.[A-Z0-9])", r"\g<1>5", text)
    text = re.sub(r"^(TITLE|CHAPTER|RULE) ([IVX|]+)$", lambda m: f"{m.group(1)} {m.group(2).replace('|', 'I')}", text)
    if MARKER.match(text):  # a lone list marker
        text = re.sub(r"(?<=\()Z(?=\))", "2", text)
        text = re.sub(r"(?<=\()IV(?=\))|(?<=\()V(?=\))", lambda m: m.group(0).lower(), text)
    return text


def _ocr_lines(pdf: Path, first_page: int, last_page: int | None) -> list[Line]:
    from ingest import ocr

    pages = [p for p in ocr.ocr_pages(pdf)
             if p["page"] >= first_page and (last_page is None or p["page"] <= last_page)]
    keep, review = ocr.gate(pages)
    ocr.write_review(pdf.stem, review)
    lines: list[Line] = []
    for p in keep:
        for l in p["lines"]:
            text = normalize_ocr(re.sub(r"\s+", " ", l["text"]).strip())
            if text and not any(f.match(text) for f in PAGE_FURNITURE):
                lines.append(Line(p["page"], text))
    return drop_running_headers(lines)


def join_lines(lines: list[str]) -> str:
    """Re-flow PDF lines into paragraphs, repairing hyphenated line breaks."""
    out = ""
    for line in lines:
        if not out:
            out = line
        elif out.endswith("-") and not out.endswith(" -") and line[:1].islower():
            out = out[:-1] + line
        elif re.match(r"^(\(\w{1,4}\)|[a-z]{1,2}\.|\d+\.\d*\.?|•)\s*$", out.splitlines()[-1]):
            out += " " + line  # "(a)" or "2.1." sat alone on its line
        elif re.match(r"^(\(\w{1,4}\)|[a-z]\.)(\s|$)", line):
            out += "\n" + line  # new enumerated item
        else:
            out += " " + line
    return out
