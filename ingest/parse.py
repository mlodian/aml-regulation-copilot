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


def read_lines(pdf: Path, first_page: int = 1, last_page: int | None = None,
               min_font: float = 0.0) -> list[Line]:
    """Extract non-empty lines (1-indexed, inclusive page range) without headers/footers.

    Spans smaller than `min_font` are dropped. In the IRR that removes footnotes,
    which quote the superseded original wording of amended provisions and would
    otherwise be retrieved as if they were current law.
    """
    doc = pymupdf.open(pdf)
    last_page = last_page or len(doc)
    lines: list[Line] = []
    for idx in range(first_page - 1, last_page):
        for block in doc[idx].get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                raw = "".join(s["text"] for s in line["spans"] if s["size"] >= min_font)
                text = re.sub(r"\s+", " ", raw).strip()
                if text and not any(p.match(text) for p in PAGE_FURNITURE):
                    lines.append(Line(idx + 1, text))
    return lines


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
