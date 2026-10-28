"""Chunking coverage check.

A heading grammar that silently misses a document's headings still produces
chunks, just bad ones: whole Titles glued into one section, or text before the
first recognised heading dropped. Three checks, per document:

1. Missed headings (the main check). Every line shaped like a heading in any of
   the corpus's layouts ("Section 5. Title", "CHAPTER II", "5.4 Title", "921 Title",
   a bold run-in title) must either be consumed by the document's grammar or match
   one of the profile's `not_headings`, each of which says why (numbered paragraphs,
   headings quoted from an amended issuance). Lines before the first heading count
   too, except a transmitting circular's own headings (`cover_headings`). Any other
   such line flags the document, with the lines listed. There is no tolerance: every
   exception is written down, so one unexplained line is one thing to look at.
2. Lead-in text. Text before the first recognised heading is a cover letter for
   circulars whose profile sets `preamble` (it is indexed as `<doc>:main`); anywhere
   else it is dropped text, and over 10% of a document (MIN_COVERAGE 0.90) means the
   grammar missed the opening headings. This catches a grammar that fails from the
   start; it cannot see headings missed later on, which is what check 1 is for.
3. No sections: a grammar that finds no heading at all.

What they catch (eval/heading_sweep.py: remove each level of each grammar in turn,
46 broken grammars, every one changing the sections): check 1 flags 23, check 2 a
further 4 (all losing the top level), check 3 a further 2; 29 in all, and none of
the intact documents. Intact documents score 0.973 to 1.000 on coverage and the 4
broken ones 0.00 to 0.76, so any floor in between separates them; 0.90 sits in
that gap. The other 17 are not flagged. 16 lose a lower level (lettered, numbered
or roman items, the TFPSA IRR's sub-rules, IC CL 2024-16's Stages): those items
merge into the passage above, so citations get coarser but no text is lost. One
loses the 2021 RRG's Parts, written "IV. Title": its coverage falls from 0.992
to 0.970, still above the floor, as the text before its first lettered heading is
dropped. Patterns for these forms would also match the lists in the body text:
one for "IV. Title" flags real lists in four intact documents.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ingest.chunk import PROFILES, parse_sections
from ingest.parse import RUNIN

MIN_COVERAGE = 0.90

HEADING_LIKE = [
    re.compile(r"^(CHAPTER|TITLE|RULE|PART|ARTICLE)\s+([IVXL]+|\d+)\b"),
    re.compile(r"^(?:Section|SECTION|Sec\.|SEC\.)\s+\d+(?:\.[\dA-Z]+)*\.\s+[A-Z]"),  # not "Section 3 of the AMLA"
    re.compile(r"^\d{1,2}(?:\.\d{1,2}){1,2}\.?(?:\s+[A-Z].*)?$"),
    re.compile(r"^\d{3}\s+[A-Z][a-z]+(?:\s+[A-Za-z,&-]+){0,8}$"),
    re.compile("^" + re.escape(RUNIN)),
]


@dataclass
class Coverage:
    doc_id: str
    words: int
    headed_words: int       # under a recognised heading
    preamble_words: int     # before the first heading
    preamble_indexed: bool  # True: a cover letter kept as <doc>:main; False: dropped
    sections: int
    largest_section_words: int
    orphan_sample: str
    headings: int = 0
    missed_headings: list[str] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.headed_words / self.words if self.words else 0.0

    @property
    def flagged(self) -> bool:
        if not PROFILES[self.doc_id]["levels"]:
            return False  # a short letter with no internal headings
        if self.missed_headings or not self.sections:
            return True
        if self.preamble_indexed:  # judge the guidelines, not the cover letter
            body = self.words - self.preamble_words
            return body > 0 and self.headed_words / body < MIN_COVERAGE
        return self.coverage < MIN_COVERAGE


def missed_headings(doc: dict, trace: dict) -> list[str]:
    """Heading-shaped lines the grammar neither consumed nor explains. Lines before the
    first heading count too (a grammar that loses its top level pushes them there),
    except the profile's `cover_headings`: headings of a transmitting circular."""
    heads, lines = trace.get("heads", set()), trace.get("lines", [])
    if not heads:
        return []
    profile = PROFILES[doc["id"]]
    skip, cover = profile.get("not_headings", []), profile.get("cover_headings", [])
    return [l.text for i, l in enumerate(lines)
            if i not in heads and any(p.match(l.text) for p in HEADING_LIKE)
            and not any(p.match(l.text) for p in skip)
            and not (i < min(heads) and any(p.match(l.text) for p in cover))]


def measure(doc: dict) -> Coverage:
    trace: dict = {}
    sections = parse_sections(doc, trace)
    sizes = [(bool(h), sum(len(l.text.split()) for l in lines), lines) for h, lines in sections]
    preamble = [lines for headed, _, lines in sizes if not headed]
    return Coverage(
        doc_id=doc["id"],
        words=sum(n for _, n, _ in sizes),
        headed_words=sum(n for headed, n, _ in sizes if headed),
        preamble_words=sum(n for headed, n, _ in sizes if not headed),
        preamble_indexed=bool(PROFILES[doc["id"]].get("preamble")),
        sections=sum(1 for headed, _, _ in sizes if headed),
        largest_section_words=max((n for headed, n, _ in sizes if headed), default=0),
        orphan_sample=" ".join(l.text for l in preamble[0])[:160] if preamble else "",
        headings=len(trace.get("heads", ())),
        missed_headings=missed_headings(doc, trace),
    )


def report(docs: list[dict]) -> list[Coverage]:
    rows = [measure(d) for d in docs]
    print(f"{'document':22s} {'words':>7s} {'headed':>7s} {'preamble':>9s} {'sections':>8s}  status")
    for r in rows:
        pre = f"{r.preamble_words}{'*' if r.preamble_indexed else '!'}" if r.preamble_words else "0"
        status = "FLAG: check the heading grammar" if r.flagged else "ok"
        print(f"{r.doc_id:22s} {r.words:7d} {r.coverage:7.1%} {pre:>9s} {r.sections:8d}  {status}")
        for text in r.missed_headings[:5]:
            print(f"{'':22s} missed heading: {text[:70]!r}")
        if r.flagged and not r.missed_headings and r.orphan_sample:
            print(f"{'':22s} unheaded text starts: {r.orphan_sample!r}")
    print("  preamble: * indexed as a cover letter, ! dropped (text before the first heading)")
    return rows


def as_json(rows: list[Coverage]) -> list[dict]:
    return [{**asdict(r), "coverage": round(r.coverage, 4), "flagged": r.flagged} for r in rows]
