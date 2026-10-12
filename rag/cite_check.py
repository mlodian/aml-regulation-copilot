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
QUOTE_RE = re.compile(r"[\"“]([^\"”]{12,})[\"”]")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\-•*])")
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


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_supported(quote: str, sources: list[str]) -> bool:
    q = _normalise(quote)
    return any(q in _normalise(s) or fuzz.partial_ratio(q, _normalise(s)) >= QUOTE_MATCH_THRESHOLD
               for s in sources)


def check(answer: str, contexts: list[str]) -> CitationReport:
    """`contexts[i]` is the text of block [i+1] that was given to the model."""
    report = CitationReport()
    if answer.strip().startswith(REFUSAL):
        report.refused = True
        return report

    report.cited = sorted(set(cited_numbers(answer)))
    report.invalid_citations = [n for n in report.cited if not 1 <= n <= len(contexts)]

    for sentence in SENTENCE_RE.split(answer.strip()):
        s = sentence.strip()
        if not s or s.endswith(":") or len(s.split()) < 6:
            continue  # headings, list intros and fragments carry no claim
        nums = [n for n in cited_numbers(s) if 1 <= n <= len(contexts)]
        if not nums:
            report.uncited_sentences.append(s)
            continue
        for quote in QUOTE_RE.findall(s):
            if not quote_supported(quote, [contexts[n - 1] for n in nums]):
                report.unsupported_quotes.append(quote)
    return report
