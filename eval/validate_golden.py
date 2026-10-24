"""Check a golden question file against the built corpus.

    python -m eval.validate_golden [file ...]      # default: eval/golden.yaml and eval/golden_heldout.yaml

For every question:
- ids are unique; both questions of a `pair` exist, ask the same thing, on different dates;
- every gold / also label matches at least one section;
- at least one gold section is in force on the question's `as_of`;
- every `must_contain` pattern is found in the text of the gold sections in force then,
  so a question can only pass when the evidence for that date says what it requires.
`also` labels (sector restatements) get the same checks but only warn.
Exits non-zero on any error.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

from eval.run_eval import is_gold
from ingest.versions import in_force

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = [ROOT / "eval" / "golden.yaml", ROOT / "eval" / "golden_heldout.yaml"]


def load(paths: list[Path]) -> tuple[str, list[dict]]:
    as_of, questions = None, []
    for p in paths:
        data = yaml.safe_load(p.read_text())
        as_of = str(data.get("as_of", as_of)) if data.get("as_of") else as_of
        questions += data["questions"]
    return as_of, questions


def validate(questions: list[dict], default_as_of: str) -> tuple[list[str], list[str]]:
    chunks = [SimpleNamespace(**json.loads(l)) for l in (ROOT / "data" / "processed" / "chunks_structured.jsonl").open()]
    errors, warnings = [], []
    ids = collections.Counter(q["id"] for q in questions)
    errors += [f"{i}: duplicate id" for i, n in ids.items() if n > 1]
    pairs = collections.defaultdict(list)
    for q in questions:
        if q.get("pair"):
            pairs[q["pair"]].append(q)
    for name, qs in pairs.items():
        if len(qs) != 2 or qs[0]["question"] != qs[1]["question"] or \
                str(qs[0].get("as_of", default_as_of)) == str(qs[1].get("as_of", default_as_of)):
            errors.append(f"pair {name}: needs two questions with the same text on different dates")
    for q in questions:
        as_of = str(q.get("as_of", default_as_of))
        if q["kind"] == "unanswerable":
            if q.get("gold") or q.get("must_contain"):
                errors.append(f"{q['id']}: unanswerable questions have no gold or facts")
            continue
        for tier, labels, report in (("gold", q["gold"], errors), ("also", q.get("also", []), warnings)):
            for label in labels:
                matched = [c for c in chunks if is_gold(c.section_id, [label])]
                live = [c for c in matched if in_force(c, as_of)]
                if not matched:
                    report.append(f"{q['id']}: {tier} {label} matches no section")
                elif not live:
                    report.append(f"{q['id']}: {tier} {label} is not in force on {as_of}")
                elif tier == "also":
                    text = " ".join(c.text for c in live)
                    missing = [p for p in q["must_contain"] if not re.search(p, text, re.I)]
                    if missing:
                        warnings.append(f"{q['id']}: also {label} lacks {missing}")
        live_gold = [c for c in chunks if is_gold(c.section_id, q["gold"]) and in_force(c, as_of)]
        text = " ".join(c.heading + " " + c.text for c in live_gold)
        for p in q["must_contain"]:
            if not re.search(p, text, re.I):
                errors.append(f"{q['id']}: '{p}' not in its gold text in force on {as_of}")
    return errors, warnings


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] or [p for p in DEFAULT if p.exists()]
    as_of, questions = load(paths)
    errors, warnings = validate(questions, as_of)
    for w in warnings:
        print("warn ", w)
    for e in errors:
        print("ERROR", e)
    print(f"{len(questions)} questions, {len(errors)} errors, {len(warnings)} warnings (as_of {as_of})")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
