"""Chunking coverage check.

A heading grammar that silently misses a document's headings still produces
chunks, just bad ones: whole Titles glued into one section, or text before the
first recognised heading dropped. This check measures, per document, how much
of the body text sits under a recognised heading and flags documents below
MIN_COVERAGE so a broken grammar cannot pass unnoticed.

Text before the first heading is a cover letter for circulars whose profile sets
`preamble` (it is indexed as `<doc>:main`); anywhere else it is dropped text.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from ingest.chunk import PROFILES, parse_sections

MIN_COVERAGE = 0.90


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

    @property
    def coverage(self) -> float:
        return self.headed_words / self.words if self.words else 0.0

    @property
    def flagged(self) -> bool:
        if not PROFILES[self.doc_id]["levels"]:
            return False  # a short letter with no internal headings
        if self.preamble_indexed:  # judge the guidelines, not the cover letter
            body = self.words - self.preamble_words
            return body > 0 and self.headed_words / body < MIN_COVERAGE
        return self.coverage < MIN_COVERAGE


def measure(doc: dict) -> Coverage:
    sections = parse_sections(doc)
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
    )


def report(docs: list[dict]) -> list[Coverage]:
    rows = [measure(d) for d in docs]
    print(f"{'document':22s} {'words':>7s} {'headed':>7s} {'preamble':>9s} {'sections':>8s}  status")
    for r in rows:
        pre = f"{r.preamble_words}{'*' if r.preamble_indexed else '!'}" if r.preamble_words else "0"
        status = "FLAG: check the heading grammar" if r.flagged else "ok"
        print(f"{r.doc_id:22s} {r.words:7d} {r.coverage:7.1%} {pre:>9s} {r.sections:8d}  {status}")
        if r.flagged and r.orphan_sample:
            print(f"{'':22s} unheaded text starts: {r.orphan_sample!r}")
    print("  preamble: * indexed as a cover letter, ! dropped (text before the first heading)")
    return rows


def as_json(rows: list[Coverage]) -> list[dict]:
    return [{**asdict(r), "coverage": round(r.coverage, 4), "flagged": r.flagged} for r in rows]
