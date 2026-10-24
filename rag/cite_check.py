"""Deterministic citation verification.

The answer prompt asks the model to cite sources as [1], [2] ... (the numbered
context blocks) and to put any verbatim wording in double quotes. This module
checks, without an LLM, that:

* every cited number refers to a context block that was actually supplied;
* every quoted span appears (fuzzily) in at least one cited block;
* every sentence that makes a claim carries at least one citation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
QUOTE_RE = re.compile(r"\"([^\"]*)\"|“([^”]*)”")  # pair quotes first, filter by length after
MIN_QUOTE_CHARS = 12
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\-•*])")
# citation abbreviations ("GoTRACS, Ch. I, Sec. 5", "ARI No. 1, s. 2020") do not end a sentence
ABBREVIATION_END = re.compile(r"(?:\b(?:Ch|Sec|Secs|No|Nos|Art|Par|Rec|Pt|s|e\.g|i\.e|vs|cf)\.)$")


def sentences(text: str) -> list[str]:
    out: list[str] = []
    for piece in SENTENCE_RE.split(text.strip()):
        if out and ABBREVIATION_END.search(out[-1]):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out
QUOTE_MATCH_THRESHOLD = 90
REFUSAL = "NOT_IN_SOURCES"


@dataclass
class CitationReport:
    cited: list[int] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)
    unsupported_quotes: list[str] = field(default_factory=list)
    uncited_sentences: list[str] = field(default_factory=list)
    refused: bool = False

    @property
    def ok(self) -> bool:
        return not (self.invalid_citations or self.unsupported_quotes or self.uncited_sentences)


def cited_numbers(text: str) -> list[int]:
    nums: list[int] = []
    for group in CITE_RE.findall(text):
        nums += [int(n) for n in group.split(",")]
    return nums


def quotes(text: str) -> list[str]:
    """Quoted spans long enough to be verbatim wording (short ones are usually terms)."""
    found = [a or b for a, b in QUOTE_RE.findall(text)]
    return [q for q in found if len(q.strip()) >= MIN_QUOTE_CHARS]


def _normalise(s: str) -> str:
    s = re.sub(r"[\"'“”‘’]", "", s)           # quote style differs between model and source
    s = re.sub(r"\s*[–—-]\s*", "-", s)          # "tipping – off" vs "tipping-off"
    return re.sub(r"\s+", " ", s).strip(" .;,").lower()


def quote_supported(quote: str, sources: list[str]) -> bool:
    """Every part of the quote (split on ellipses) must appear in one of the sources."""
    parts = [p for p in re.split(r"\.{3}|…", quote) if len(p.strip()) >= 4]
    normed = [_normalise(s) for s in sources]
    for part in parts or [quote]:
        q = _normalise(part)
        if not any(q in s or fuzz.partial_ratio(q, s) >= QUOTE_MATCH_THRESHOLD for s in normed):
            return False
    return True


def check(answer: str, contexts: list[str]) -> CitationReport:
    """`contexts[i]` is the text of block [i+1] that was given to the model."""
    report = CitationReport()
    if answer.strip().startswith(REFUSAL):
        report.refused = True
        return report

    report.cited = sorted(set(cited_numbers(answer)))
    report.invalid_citations = [n for n in report.cited if not 1 <= n <= len(contexts)]

    for sentence in sentences(answer):
        s = sentence.strip()
        if not s or s.endswith(":") or len(s.split()) < 6:
            continue  # headings, list intros and fragments carry no claim
        nums = [n for n in cited_numbers(s) if 1 <= n <= len(contexts)]
        if not nums:
            report.uncited_sentences.append(s)
            continue
        for quote in quotes(s):
            if not quote_supported(quote, [contexts[n - 1] for n in nums]):
                report.unsupported_quotes.append(quote)
    return report
