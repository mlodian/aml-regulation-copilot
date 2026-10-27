"""Assemble the Phase 2 golden set and its dev / held-out split.

    python -m eval.build.assemble

Inputs: the pilot questions as they stood (eval/build/pilot_golden.yaml, a frozen copy),
their relabel (relabel_pilot.py), the Phase 2 questions (new_questions.yaml), and the
fixes from the second review (review_fixes.py).
Outputs: eval/golden.yaml (dev) and eval/golden_heldout.yaml (held-out).

The split, seeded so it is reproducible:
- The pilot questions were used while building the system, so all of them stay in dev.
- About 30% of the whole set is held out, drawn only from the Phase 2 questions,
  stratified by kind and by the issuer of the gold provisions.
- Both questions of a same-question, two-date pair go to the same side.
The held-out file is only run with `--split heldout`, once per release.
"""
from __future__ import annotations

import collections
import random
from pathlib import Path

import yaml

from eval.build import review_fixes
from eval.build.relabel_pilot import ALSO, GOLD_ADD, MUST_CONTAIN
from ingest.download import load_manifest

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
AS_OF = "2026-10-24"
HELDOUT_SHARE = 0.30
SEED = 20261024

HEADER = """# Golden evaluation set ({split}).
#
# gold:          section ids that answer the question; a label also matches every section under it
# also:          sector restatements stating the same fact (BSP, SEC, IC, DNFBP rules): correct
#                evidence, but not the general rule (scored separately)
# must_contain:  facts the answer must state (case-insensitive regex, all required)
# kind:          numeric | factual | list | multi_doc | cross_issuer | versioned | unanswerable
# as_of:         the date the question is asked about (default below); retrieval only sees the
#                provisions in force on that date
# pair:          the two questions of a same-question, two-date pair
# source:        pilot (written for the 2-document pilot, relabelled for Phase 2) | phase2
#
# Questions are paraphrased the way a compliance analyst would ask them. Unanswerable
# questions are in-domain but outside this library; the correct behaviour is to refuse.
# Built by eval/build/assemble.py; checked by `python -m eval.validate_golden`.
{note}
as_of: {as_of}

"""
NOTES = {
    "dev": "# Dev split: all pilot questions plus ~half of the Phase 2 questions. Iterate on these.",
    "held-out": "# Held-out split: Phase 2 questions never used while building. Run once per release:\n"
                "#   python -m eval.run_eval answers --split heldout",
}
FIELDS = ("id", "question", "as_of", "pair", "gold", "also", "must_contain", "kind", "source", "note")


def issuer_of(q: dict, issuers: dict) -> str:
    return issuers.get(q["gold"][0].split(":")[0], "?") if q["gold"] else "none"


def pilot() -> list[dict]:
    qs = yaml.safe_load((HERE / "pilot_golden.yaml").read_text())["questions"]
    for q in qs:
        q["gold"] = q["gold"] + [g for g in GOLD_ADD.get(q["id"], []) if g not in q["gold"]]
        if q["id"] in ALSO:
            q["also"] = ALSO[q["id"]]
        q["must_contain"] = MUST_CONTAIN.get(q["id"], q.get("must_contain", []))
        if q["id"] == "u06":  # answerable since the BSP manual is in the library
            q.update(gold=["bsp_morb_p9:sec923:ssupervisoryenforcementaction"], also=["sec_mc16_2018:ch5:sec5.k.1"],
                     must_contain=["50,000"], kind="numeric",
                     note="relabelled: unanswerable in the pilot, answered by the BSP manual in Phase 2")
        q["source"] = "pilot"
    return qs


def phase2() -> list[dict]:
    qs = yaml.safe_load((HERE / "new_questions.yaml").read_text())["questions"]
    for q in qs:
        if q["id"].startswith("u"):  # the pilot uses u01-u10
            q["id"] = f"u{int(q['id'][1:]) + 10:02d}"
        q["source"] = "phase2"
    return qs


def split(questions: list[dict], issuers: dict) -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    units = collections.OrderedDict()  # a pair is one unit
    for q in questions:
        units.setdefault(q.get("pair") or q["id"], []).append(q)
    strata = collections.defaultdict(list)
    for key, qs in units.items():
        strata[(qs[0]["kind"], issuer_of(qs[0], issuers))].append(key)
    total = len(questions)
    target = round(HELDOUT_SHARE * total)
    candidates = sum(len(v) for v in units.values() if v[0]["source"] == "phase2")
    share = target / candidates
    held: set[str] = set()
    for _, keys in sorted(strata.items()):
        keys = [k for k in keys if units[k][0]["source"] == "phase2"]
        rng.shuffle(keys)
        size = sum(len(units[k]) for k in keys)
        take, n = 0, 0
        for k in keys:
            if n + len(units[k]) / 2 <= share * size:  # round half
                held.add(k)
                n += len(units[k])
    heldout = [q for k, qs in units.items() if k in held for q in qs]
    dev = [q for k, qs in units.items() if k not in held for q in qs]
    return dev, heldout


def dump(path: Path, questions: list[dict], split_name: str) -> None:
    def scalar(v, f=""):
        if isinstance(v, list):
            return "[" + ", ".join("'" + str(x).replace("'", "''") + "'" if f == "must_contain" else str(x)
                                   for x in v) + "]"
        return yaml.safe_dump(v, width=10_000).strip().removesuffix("...").strip()
    lines = [HEADER.format(split=split_name, note=NOTES[split_name], as_of=AS_OF), "questions:"]
    for q in questions:
        first = True
        for f in FIELDS:
            if f not in q or q[f] in (None, []) and f not in ("gold", "must_contain"):
                continue
            v = q[f]
            if f == "as_of":
                v = str(v)
            lines.append(f"  {'- ' if first else '  '}{f}: {scalar(v, f)}")
            first = False
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    issuers = {d["id"]: d["issuer"] for d in load_manifest()}
    questions = [review_fixes.apply(q) for q in pilot() + phase2()]
    dev, heldout = split(questions, issuers)
    dump(EVAL / "golden.yaml", dev, "dev")
    dump(EVAL / "golden_heldout.yaml", heldout, "held-out")
    count = lambda qs, key: dict(sorted(collections.Counter(key(q) for q in qs).items()))
    for name, qs in (("dev", dev), ("held-out", heldout)):
        print(f"{name}: {len(qs)} questions  kinds {count(qs, lambda q: q['kind'])}")
        print(f"{'':10s}issuers {count(qs, lambda q: issuer_of(q, issuers))}")
    print(f"held-out share {len(heldout) / len(questions):.0%} of {len(questions)}")


if __name__ == "__main__":
    main()
