"""Fixes from the second review of the golden set (eval/review/sample.csv), applied by assemble.py.

The review rejected 16 of 40 sampled questions; the first annotator had rejected 2
(kappa 0.15). Nearly every reject was a required fact a wrong answer could pass, so
the same two checks were added to eval/validate_golden.py and run over all 200
questions, not just the sample:

- a number or number word must match as a whole word ("20" matched "2024",
  "two" matched "network", "ten" matched "extension"): anchor_numbers() below
  fixes this mechanically for every question;
- a required fact must not already appear in the question ("real estate" in "Are
  real estate brokers covered persons?"): fixed one by one in FIXES, rewording the
  question where the fact cannot be separated from it.

FIXES also carries the reviewer's other corrections (wrong or missing gold, facts that
were too strict). Each entry replaces the named fields of that question.
"""
from __future__ import annotations

import re

NUMBER_WORDS = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                "fifteen", "twenty", "thirty", "forty", "fifty", "sixty", "ninety", "hundred", "thousand", "million"}


def _alternatives(pattern: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in pattern:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "|" and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def anchor_numbers(pattern: str) -> str:
    """'20|twenty' -> '(?<![\\d,.])20(?![\\d,])|\\btwenty\\b': digits may not touch other digits
    (so 'P50,000.00' still matches 50,000 but '2024' does not match 20)."""
    def one(a: str) -> str:
        if re.fullmatch(r"[\d,.]+", a):
            return rf"(?<![\d,.]){a}(?!\d|,\d)"
        return rf"\b{a}\b" if a.lower() in NUMBER_WORDS else a
    return "|".join(one(a) for a in _alternatives(pattern))


DAYS = r"\)? (calendar |working )?days"
FIXES: dict[str, dict] = {
    # --- reviewer rejects ----------------------------------------------------------
    "q16": {"gold": ["irr2018:rule2:sec1", "gotracs2024:chi:sec2:sd", "gotracs2024:chi:sec2:se", "sanctions2021:s4.1",
                     "bo2018:sec4:sb"]},                     # bo2018:sec2:sd defines legal owners, not BO
    "q23": {"gold": ["rrg2021:partiv:sd:se", "gotracs2024:chi:sec5:s5.4:sc:s3:sviii"]},
    "q28": {"gold": ["rrg2021:partiv:se", "gotracs2024:chii:part1:sec4:s4.8"],
            "must_contain": ["kidnapping", "drug", "terroris", "graft|corrupt"]},   # the current GoTRACS list
    "n011": {"must_contain": [r"\bfour\b|\b4\b", r"after 7|7 o.clock|7:00|7 ?pm|\bseven\b",
                              r"one \(1\) hour|\bone hour|\b1 hour|within an hour"]},
    "n018": {"must_contain": [r"\b20\b|\btwenty\b", r"\btiers?\b|series of (corporate )?ownership"]},
    "a06": {"must_contain": [r"not (be )?(allowed|entertained|permitted|granted)|no (motion|extension)|cannot|prohibited"]},
    "e06": {"question": "How long after publication does SEC Memorandum Circular No. 4, s. 2021 take effect?",
            "must_contain": [r"(fifteen|\b15\b)" + DAYS]},
    "a04": {"must_contain": [r"(\bten\b|\b10\b)" + DAYS]},
    "t06": {"must_contain": ["food", "rent|mortgage", "utilit|tax|insurance premium"]},
    "s07": {"must_contain": [r"(fifteen|\b15\b)" + DAYS]},
    "m11": {"question": "When must banks assess the ML/TF risks of a new product?",
            "must_contain": [r"prior to (the )?launch|before (the |their |its )?launch|before launching|development process"]},
    "n025": {"must_contain": [r"\byes\b|designated non-financial|DNFBP|Rule 4"]},
    "v06a": {"must_contain": [r"(five|\b5\b)\)? working days"]},
    "x07": {"must_contain": [r"(five|\b5\b)\)? working days"]},  # the gold includes the BSP rule
    "m03": {"must_contain": [r"as long as the account (exists|is open|remains)|life of the account",
                             r"(five|\b5\b)\)? years"]},
    "d03": {"must_contain": [r"(two|\b2\b)\)? years|every two|biennial"]},
    # --- facts already in the question (found by the new check on all 200) -------
    "q31": {"must_contain": [r"as an? (suspicious transaction|STR)\b|report(ed)? .{0,20}as (an? )?(STR|ST\b|suspicious)"]},
    "q32": {"must_contain": [r"\byes\b|whether completed or attempted|including attempts|attempts thereof|likewise file"]},
    "q35": {"must_contain": [r"\byes\b|no (administrative|criminal|civil)|proceedings shall lie|safe harbo"]},
    "q48": {"must_contain": [r"ultimate responsibility|remains? with the (relying )?(covered person|institution)|relying covered person"]},
    "v05a": {"must_contain": [r"secure the consent|\byes\b"]},
    "v05b": {"must_contain": [r"comply with (the )?(obligations|UNSC|United Nations)|\bno\b"]},
    "n026": {"must_contain": [r"\byes\b|service providers|designated non-financial|DNFBP"]},
    "n028": {"must_contain": [r"\byes\b|in case of any changes|are updated|be updated"]},
    "t07": {"must_contain": [r"no (administrative|criminal|civil)|shall lie|not (be )?liable"]},
    "s06": {"must_contain": [r"\byes\b|prior authori[sz]ation|may be credited|permit"]},
    "e05": {"must_contain": [r"\byes\b|online reporting system|Rule 4"]},
    "i03": {"must_contain": ["identif", "likelihood|impact", "mitigat|strateg|priorit"]},
    "m12": {"must_contain": [r"\bno\b|shall not be construed|not .{0,30}discriminat"]},
    "n023": {"question": "In what order must KYC documents and the STR they support be uploaded?",
             "must_contain": [r"prior to the upload|before (uploading|the upload|filing|submitting)"]},
    "c02": {"question": "What name-matching method should sanctions screening use?",
            "must_contain": ["fuzzy"]},
    # --- after the dev run (eval/reports/answers_dev.jsonl): facts too strict for correct answers
    "q44": {"must_contain": ["senior management", r"STR|suspicious transaction report"]},
    "m08": {"must_contain": [r"amount|50,000", "condition|subject to"]},
    # both dates say "next working day"; what changed is that GoTRACS counts from the end of the
    # 60-day determination period
    "v02a": {"must_contain": [r"from (the )?(occurrence|establishment of suspicion|date of establishment)"]},
    "v02b": {"must_contain": [r"after the (said )?60|end of the (60-day )?determination period|after the determination period"]},
}


def apply(q: dict) -> dict:
    q = {**q, **FIXES.get(q["id"], {})}
    q["must_contain"] = [anchor_numbers(p) for p in q.get("must_contain", [])]
    return q
