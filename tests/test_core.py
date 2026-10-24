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


def test_label_drops_repeated_provision_number():
    from ingest.chunk import Chunk
    c = Chunk("x#0", "irr2018", "2018 IRR", "x", "2018 IRR, Rule 22, Sec. 2",
              "Rule 22 Transaction Reporting > Sec. 2 Timing of Reporting", 84, 84, "text")
    assert c.label == "2018 IRR, Rule 22, Sec. 2 · Timing of Reporting"
    d = Chunk("y#0", "rrg2021", "2021 RRG", "y", "2021 RRG, Part IV, D, e",
              "Part IV STRs > D Quality > e", 11, 11, "text")
    assert d.label == "2021 RRG, Part IV, D, e"


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


def test_citation_abbreviations_do_not_split_sentences():
    ctx = ["Covered persons shall establish the suspicion within sixty (60) calendar days."]
    ans = ("- The current rule is GoTRACS, Ch. I, Sec. 5, 5.4(viii): \"within sixty (60) calendar days\" [1].")
    assert check(ans, ctx).ok


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


# --- Phase 2: manifest, OCR, coverage, versioning ------------------------------

def _doc(**kw):
    import datetime as dt
    base = {"id": "d1", "title": "t", "short": "D1", "issuer": "AMLC", "status": "current",
            "url": "https://example.org/d1.pdf", "issued": dt.date(2021, 1, 1)}
    return {**base, **kw}


def test_manifest_schema_catches_problems():
    from ingest.download import validate
    assert validate([_doc()]) == []
    assert any("unknown issuer" in e for e in validate([_doc(issuer="CBP")]))
    assert any("needs superseded_by" in e for e in validate([_doc(status="transitional")]))
    assert any("transitional_from" in e for e in validate([_doc(status="transitional", superseded_by="d1")]))
    assert any("unknown document" in e for e in validate([_doc(amends=["nope"])]))
    assert any("YYYY-MM-DD" in e for e in validate([_doc(issued="Jan 2021")]))
    assert any("exactly one of url / manual" in e for e in validate([_doc(manual="x.pdf")]))


def test_project_manifest_is_valid():
    from ingest.download import load_manifest
    assert len(load_manifest()) >= 20  # raises on any schema problem


def test_ocr_gate_routes_low_confidence_pages_to_review():
    from ingest.ocr import gate
    pages = [{"page": 1, "confidence": 0.97, "lines": [{"text": "a"}]},
             {"page": 2, "confidence": 0.41, "lines": [{"text": "b"}]},
             {"page": 3, "confidence": 0.0, "lines": []}]
    keep, review = gate(pages, min_confidence=0.8)
    assert [p["page"] for p in keep] == [1]
    assert [p["page"] for p in review] == [2]  # blank page 3 is neither


def test_ocr_gate_holds_pages_whose_numbers_disagree():
    from ingest.ocr import gate, number_disagreements
    assert number_disagreements("within sixty (60) days, thirty-one (31) days, "
                                "five hundred thousand pesos (PHP500,000.00)") == []
    assert number_disagreements("within sixty (80) calendar days") == ["sixty (80)"]
    misread = {"page": 1, "confidence": 0.99, "lines": [{"text": "file within five (S) working days"}]}
    keep, review = gate([misread])
    assert not keep and review[0]["reason"].startswith("numbers disagree")


def test_ocr_normalisation_of_list_markers_and_headings():
    from ingest.parse import normalize_ocr
    assert normalize_ocr("(її)") == "(ii)"
    assert normalize_ocr("(i¡i)") == "(iii)"
    assert normalize_ocr("(Z)") == "(2)"
    assert normalize_ocr("Section I. Declaration of Policy") == "Section 1. Declaration of Policy"
    assert normalize_ocr("Section S.A.2. Continuing Due Diligence") == "Section 5.A.2. Continuing Due Diligence"
    assert normalize_ocr("TITLE I|I") == "TITLE III"


def test_running_headers_are_dropped():
    from ingest.parse import Line, drop_running_headers
    header = "Guidelines on Transaction Reporting and Compliance Submissions (GoTRACS)"
    lines = [Line(p, t) for p in range(1, 6) for t in (header, f"body text on page {p}")]
    assert [l.text for l in drop_running_headers(lines)] == [f"body text on page {p}" for p in range(1, 6)]


def test_repeated_text_mid_page_is_not_a_running_header():
    from ingest.parse import Line, drop_running_headers
    note = "Fine is on a per account basis."
    lines = [Line(p, t) for p in range(1, 6)
             for t in ("first line", "second line", note, "fourth line", "fifth line")]
    assert note in [l.text for l in drop_running_headers(lines)]


def test_peso_amounts_from_old_ocr_layers_are_repaired():
    from ingest.parse import fix_amounts
    assert fix_amounts("a fine of Php500,OOO.OO") == "a fine of Php500,000.00"
    assert fix_amounts("Php may be Sold") == "Php may be Sold"


def test_split_title_on_dash_or_title_like_sentence():
    from ingest.chunk import split_title
    assert split_title("Scope. – These Guidelines shall apply") == ("Scope", "These Guidelines shall apply")
    assert split_title("General Policy on Customer Due Diligence – These") == \
        ("General Policy on Customer Due Diligence", "These")
    assert split_title("Risk Management. All ICREs shall develop") == ("Risk Management", "All ICREs shall develop")
    assert split_title("Anti-Money Laundering Council") == ("Anti-Money Laundering Council", "")


def test_coverage_flags_a_grammar_that_misses_headings(monkeypatch):
    from ingest import coverage
    from ingest.parse import Line
    lines = [Line(1, "word " * 50)]
    monkeypatch.setitem(coverage.PROFILES, "d1", {"levels": ["x"], "preamble": False})
    monkeypatch.setattr(coverage, "parse_sections", lambda doc, trace: [([], lines), ([("lv", "1", "")], lines[:0] + [Line(1, "w")])])
    row = coverage.measure({"id": "d1"})
    assert row.preamble_words == 50 and row.flagged  # almost all text sits before any heading


def test_missed_heading_flags_a_grammar_that_lost_a_level(monkeypatch):
    from ingest import coverage
    from ingest.parse import Line
    lines = [Line(1, t) for t in ("RULE 1", "Section 1. Title", "body", "Section 2. Scope", "body", "2.1. numbered")]
    profile = {"levels": ["x"], "not_headings": [coverage.re.compile(r"^\d+\.\d+\.")]}
    monkeypatch.setitem(coverage.PROFILES, "d1", profile)

    def parse(doc, trace):  # a grammar that only knows RULE: both Sections are missed
        trace.update(lines=lines, heads={0})
        return [([("lv", "1", "")], lines[1:])]
    monkeypatch.setattr(coverage, "parse_sections", parse)
    row = coverage.measure({"id": "d1"})
    assert row.missed_headings == ["Section 1. Title", "Section 2. Scope"] and row.flagged  # "2.1." is declared


def test_one_changed_word_is_a_new_version():
    from ingest.versions import words
    old = "6.1. MVTS providers shall make the information available within five (5) working days " * 20
    new = old.replace("within five (5) working days", "within three working days")
    assert words(old) != words(new)  # rapidfuzz ratio of these two is above 99
    assert words("“Rule 22.”  STRs") == words("rule 22 STRs")  # quote marks, case and spacing do not count


def test_list_labels_follow_in_order():
    from ingest.chunk import _follows
    assert _follows(None, "a") and _follows("h", "i") and _follows("z", "aa") and _follows("aa", "bb")
    assert _follows("2", "3") and _follows("7", "1")  # a list may restart
    assert not _follows("h", "ii") and not _follows(None, "c") and not _follows("2", "4")


def test_short_list_items_join_their_parent_instead_of_vanishing():
    from ingest.chunk import Level, fold_short_sections
    from ingest.parse import Line
    sec, par, item = Level("Sec.", None), Level("", None, attach=True), Level("", None, attach=True)
    parent = [(sec, "3", ""), (par, "b", "")]
    sections = [(parent, [Line(1, "Persons supervised or regulated by the IC, such as:")]),
                (parent + [(item, "1", "")], [Line(1, "Insurance companies;")]),
                (parent + [(item, "2", "")], [Line(1, "Pre-need companies;")])]
    folded = fold_short_sections(sections)
    assert len(folded) == 1
    assert [l.text for l in folded[0][1]][1:] == ["(1) Insurance companies;", "(2) Pre-need companies;"]


def test_cohen_kappa():
    from eval.review.agreement import cohen_kappa
    assert cohen_kappa(["accept", "accept", "reject", "accept"], ["accept", "reject", "reject", "accept"]) == 0.5
    assert cohen_kappa(["accept", "reject"], ["accept", "reject"]) == 1.0


def _chunk(**kw):
    from ingest.chunk import Chunk
    base = dict(chunk_id="x#0", doc_id="d", doc_short="D", section_id="d:s1", citation="D, s1",
                heading="", page_start=1, page_end=1, text="t", issuer="AMLC")
    return Chunk(**{**base, **kw})


def test_in_force_window_and_status():
    from ingest.versions import in_force, status
    old = _chunk(effective_from="2018-11-20", effective_to="2020-01-29")
    rrg = _chunk(effective_from="2021-06-22", transitional_from="2024-12-11", superseded_by="gotracs2024")
    assert in_force(old, "2019-06-01") and not in_force(old, "2020-01-29")  # effective_to is exclusive
    assert not in_force(rrg, "2021-01-01")
    assert status(rrg, "2022-01-01") == "current"
    assert status(rrg, "2026-01-01") == "transitional"
    assert status(old, "2026-01-01") == "superseded"


def test_ari_targets_parse_amended_rule_and_section(tmp_path, monkeypatch):
    from ingest import versions
    monkeypatch.setattr(versions, "RAW", tmp_path)
    text = ("Section 9. Section 2.2 of Rule 22 of the 2018 Implementing Rules is hereby amended to read. "
            "Section 1. Paragraph (z) Section 1 of Rule II of the 2018 IRR is hereby amended. "
            "Section 7. Rule 10 of the 2018 IRR is hereby amended to read as follows. "
            "Section 18. Section 5.2 on Manual Monitoring of Rule 22 is hereby renumbered to be Section 5.3.")
    import pymupdf
    pdf = pymupdf.open()
    pdf.new_page().insert_textbox(pymupdf.Rect(36, 36, 560, 800), text, fontsize=8)
    pdf.save(tmp_path / "ari.pdf")
    targets = versions.ari_targets("ari")
    assert ("22", "2") in targets and ("2", "1") in targets and ("10", None) in targets
    assert ("22", "5") not in targets  # renumbering is not an amendment


def test_transitional_provision_brings_its_replacement(monkeypatch):
    from rag import retrieve as r
    rrg = _chunk(chunk_id="rrg#0", doc_id="rrg2021", effective_from="2021-06-22",
                 transitional_from="2024-12-11", superseded_by="gotracs2024")
    other = [_chunk(chunk_id=f"o{i}#0", doc_id="irr2018") for i in range(3)]
    new = _chunk(chunk_id="g#0", doc_id="gotracs2024", effective_from="2024-12-11")
    top = [rrg, *other]
    out = r.with_replacements(top, top + [new], "q", "2026-01-01", "structured")
    assert out == [rrg, new, *other[:2]]  # replacement sits next to it; list length unchanged
    assert r.with_replacements(top, top + [new], "q", "2022-01-01", "structured") == top  # not yet repealed
