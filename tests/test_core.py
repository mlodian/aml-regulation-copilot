"""Unit tests for the deterministic parts: chunking, fusion, citation checks, refusal."""
from __future__ import annotations

import re

import pytest

from ingest.chunk import PROFILES, _split_words, clean_title, looks_like_title
from ingest.parse import join_lines
from rag.cite_check import REFUSAL, check, cited_numbers, quote_supported
from rag.fusion import rrf


# --- chunking -------------------------------------------------------------

def test_subsection_heading_vs_numbered_sentence():
    assert looks_like_title("Filing of CTRs and STRs.")
    assert looks_like_title("Timing of CVP")
    assert not looks_like_title("STRs shall be promptly filed within the next working day")


def test_clean_title_strips_footnote_marker_and_case():
    assert clean_title("Safe Harbor Provision.62") == "Safe Harbor Provision"
    assert clean_title("DEFINITION OF TERMS") == "Definition of Terms"


def test_irr_heading_patterns():
    rule, sec, sub = PROFILES["irr2018"]["levels"]
    assert rule.pattern.match("RULE 22 – TRANSACTION REPORTING").group(1) == "22"
    assert rule.pattern.match("RULE 6").group(1) == "6"
    assert sec.pattern.match("Section 2. Timing of Reporting.").group(1) == "2"
    # cross-references in running text must not open a new section
    assert not sec.pattern.match("Section 3 paragraphs b, c, e, g, h and i of Republic Act No. 3019")
    assert sub.pattern.match("5.3. Manual Monitoring.").group(1) == "5.3"


def test_split_respects_limit_and_keeps_all_words():
    text = "\n".join(" ".join(f"w{p}_{i}" for i in range(50)) for p in range(20))
    pieces = _split_words(text, max_words=120, overlap=10)
    assert all(len(p.split()) <= 120 + 10 for p in pieces)
    joined = " ".join(pieces)
    assert all(f"w{p}_49" in joined for p in range(20))


def test_join_lines_repairs_hyphenation_and_enumeration():
    out = join_lines(["The covered per-", "son shall file", "(a)", "a report; and", "(b) keep records."])
    assert "covered person shall file" in out
    assert re.search(r"^\(a\) a report; and$", out, re.M)


# --- fusion ---------------------------------------------------------------

def test_rrf_rewards_agreement():
    fused = [doc for doc, _ in rrf([["a", "b", "c"], ["b", "c", "a"]])]
    assert fused[0] == "b"


def test_rrf_includes_items_from_either_list():
    fused = dict(rrf([["a"], ["z"]]))
    assert set(fused) == {"a", "z"}


# --- citation checking ----------------------------------------------------

CONTEXTS = [
    "2.1. CTRs shall be filed within five (5) working days, unless the AMLC prescribes a different period.",
    "2.2. STRs shall be promptly filed within the next working day from occurrence thereof.",
]


def test_valid_answer_passes():
    ans = 'CTRs are due within five working days [1]. STRs must be "promptly filed within the next working day" [2].'
    report = check(ans, CONTEXTS)
    assert report.ok and report.cited == [1, 2]


def test_out_of_range_citation_flagged():
    report = check("CTRs are due within five working days of the transaction [3].", CONTEXTS)
    assert report.invalid_citations == [3]
    assert not report.ok


def test_fabricated_quote_flagged():
    ans = 'STRs must be "filed within thirty calendar days of the transaction date" [2].'
    report = check(ans, CONTEXTS)
    assert report.unsupported_quotes
    assert not report.ok


def test_quote_checked_against_cited_block_only():
    # the quote exists in [2] but the answer cites [1]
    ans = 'STRs must be "promptly filed within the next working day" according to the rules [1].'
    assert check(ans, CONTEXTS).unsupported_quotes


def test_short_quoted_term_does_not_shift_quote_pairing():
    # "Occurrence" is too short to verify; the text between it and the next quote
    # must not be mistaken for a quotation.
    ans = '"Occurrence" means the day STRs are "promptly filed within the next working day" [2].'
    assert check(ans, CONTEXTS).ok


def test_uncited_claim_flagged():
    ans = "CTRs are due within five working days [1]. Penalties can reach five hundred thousand pesos per violation."
    report = check(ans, CONTEXTS)
    assert len(report.uncited_sentences) == 1


def test_refusal_detected():
    report = check(f"{REFUSAL}\nThe excerpts do not cover Singapore rules.", CONTEXTS)
    assert report.refused and report.ok


@pytest.mark.parametrize("text,expected", [("[1]", [1]), ("[1, 3]", [1, 3]), ("[2][4]", [2, 4]), ("none", [])])
def test_cited_numbers(text, expected):
    assert cited_numbers(text) == expected


def test_ellipsis_quote_checks_each_part():
    assert quote_supported("CTRs shall be filed ... unless the AMLC prescribes", CONTEXTS)
    assert not quote_supported("CTRs shall be filed … within thirty calendar days of the end of month", CONTEXTS)


def test_quote_style_and_dash_spacing_ignored():
    assert quote_supported("no 'tipping – off' of customers", ["that no “tipping-off” of customers will happen"])


def test_quote_supported_tolerates_whitespace():
    assert quote_supported("within  five (5)\nworking days", CONTEXTS)
