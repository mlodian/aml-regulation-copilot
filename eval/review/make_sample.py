"""Draw the second-annotator review sample from the golden set.

    python -m eval.review.make_sample

Writes eval/review/sample.csv: 40 questions (34 drafted in Phase 2, 6 pilot questions whose
gold was relabelled for Phase 2), stratified by kind, seeded. For each, the reviewer sees
the question, the date it is asked about, the provisions expected to answer it, the
passage where the required fact appears, and the facts the answer must state, and fills:

  your_label   accept | reject   (reject: the question, the expected provisions or the
                                  required facts are wrong, ambiguous or incomplete)
  your_edit    what should change, when rejecting
  notes        anything else

The drafting annotator's own labels are kept apart in annotator_a.csv so the two are
independent; eval/review/agreement.py compares them.
"""
from __future__ import annotations

import collections
import csv
import json
import random
import re
from pathlib import Path
from types import SimpleNamespace

from eval.run_eval import is_gold, load_golden
from ingest.versions import in_force

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "review" / "sample.csv"
SEED, PHASE2, PILOT = 20261024, 34, 6


def readable(pattern: str) -> str:
    """'five|\\b5\\b' -> 'five or 5'."""
    return " or ".join(re.sub(r"\\[bs]|[\\^$]", "", p).replace("?", "").strip() for p in pattern.split("|"))


def label_citation(label: str, citation: dict) -> str:
    """A label naming a whole Part or Section reads as that unit: '2021 RRG, Part IV (all of it)'."""
    if label in citation:
        return citation[label]
    child = next((c for s, c in citation.items() if is_gold(s, [label])), None)
    if child is None:
        return label
    depth = len(label.split(":")) - 1
    doc, _, rest = child.partition(", ")
    levels = re.findall(r"\([^)]*\)|[^,(]+", rest)  # "Sec. 2(g)(1)" -> "Sec. 2", "(g)", "(1)"
    kept = "".join(l if l.startswith("(") else ", " + l.strip() for l in levels[:depth] if l.strip())
    return doc + kept + " (all of it)"


def evidence(q: dict, chunks: list) -> tuple[str, str]:
    live = [c for c in chunks if is_gold(c.section_id, q["gold"]) and in_force(c, q["as_of"])]
    for c in live:
        text = re.sub(r"\s+", " ", c.text)
        m = re.search(q["must_contain"][0], text, re.I) if q["must_contain"] else None
        if m:
            start, end = max(0, m.start() - 220), min(len(text), m.end() + 160)
            return c.citation, ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")
    return (live[0].citation if live else ""), ""


def main() -> None:
    chunks = [SimpleNamespace(**json.loads(l)) for l in (ROOT / "data" / "processed" / "chunks_structured.jsonl").open()]
    citation = {}
    for c in chunks:
        citation.setdefault(c.section_id, c.citation)
    questions = [{**q, "split": s} for s in ("dev", "heldout") for q in load_golden(s)]
    rng = random.Random(SEED)
    by_kind = collections.defaultdict(list)
    for q in questions:
        if q["source"] == "phase2":
            by_kind[q["kind"]].append(q)
    phase2 = sum(len(v) for v in by_kind.values())
    sample = []
    for kind, qs in sorted(by_kind.items()):
        rng.shuffle(qs)
        sample += qs[:max(1, round(PHASE2 * len(qs) / phase2))]
    sample = sample[:PHASE2]
    relabelled = [q for q in questions if q["source"] == "pilot" and any(g.startswith("gotracs") for g in q["gold"])]
    sample += rng.sample(relabelled, PILOT)
    rng.shuffle(sample)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["n", "id", "split", "kind", "asked_as_of", "question", "expected_provisions",
                    "evidence_from", "evidence_passage", "required_facts", "your_label", "your_edit", "notes"])
        for n, q in enumerate(sample, 1):
            if q["kind"] == "unanswerable":
                expected, src, passage, facts = "none: the copilot should refuse", "", "", ""
            else:
                labels = q["gold"] + q.get("also", [])
                expected = "; ".join(label_citation(g, citation) for g in labels)
                src, passage = evidence(q, chunks)
                facts = "; ".join(readable(p) for p in q["must_contain"])
            w.writerow([n, q["id"], q["split"], q["kind"], q["as_of"], q["question"], expected, src, passage, facts, "", "", ""])
    print(f"{len(sample)} questions -> {OUT.relative_to(ROOT)}  kinds {dict(collections.Counter(q['kind'] for q in sample))}")


if __name__ == "__main__":
    main()
