"""Evaluation harness.

    python -m eval.run_eval retrieval [--split dev|heldout]          # no LLM: retrieval ablation table
    python -m eval.run_eval answers [--split dev|heldout] [--limit N] # end-to-end answers through the LLM backend

Every question is asked as of its `as_of` date (default: the golden file's), so retrieval
only sees the provisions in force then. The held-out split is run once per release.

Retrieval metrics
  section_recall@k  a gold or `also` provision (a sector restatement of the same rule) is
                    among the top-k chunks (structured chunks only; fixed windows have
                    no provision address)
  general_recall@k  the same, counting only `gold`: did the general rule make the cut, or
                    only a sector restatement of it?
  evidence_recall@k the top-k chunk texts together contain every required fact; this is
                    comparable across chunking strategies
  mrr               reciprocal rank of the first gold or `also` provision within the top 5
                    (0 when none is in the top 5)
  context_words@5   words handed to the LLM; evidence recall rises with chunk size, so
                    compare strategies at similar context budgets
  ms_p50, ms_p95    retrieval latency per query, warm

Answer metrics
  fact_accuracy     answer states every required fact (answerable questions)
  citation_valid    every [n] refers to a supplied block and every quote is found in the block it cites
  cited_gold        the answer cites at least one gold provision
  refusal_correct   answer refuses on unanswerable questions / answers the answerable ones
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = {"dev": ROOT / "eval" / "golden.yaml", "heldout": ROOT / "eval" / "golden_heldout.yaml"}
REPORTS = ROOT / "eval" / "reports"
KS = (1, 3, 5)


def load_golden(split: str = "dev") -> list[dict]:
    """Questions of a split, each with its `as_of` date filled in."""
    data = yaml.safe_load(GOLDEN[split].read_text())
    default = str(data["as_of"])
    return [{**q, "as_of": str(q.get("as_of", default))} for q in data["questions"]]


def is_gold(section_id: str, gold: list[str]) -> bool:
    """A gold label may name a provision or any ancestor of it (e.g. a whole Part)."""
    return any(section_id == g or section_id.startswith(g + ":") for g in gold)


CITATION_MARK = re.compile(r"\[\d+(?:\s*[,–-]\s*\d+)*\]")


def facts_present(text: str, patterns: list[str]) -> bool:
    """Every pattern matches. Citation markers are removed first: "[3]" must not count as
    the number three."""
    text = CITATION_MARK.sub(" ", text)
    return all(re.search(p, text, re.I) for p in patterns)


def eval_retrieval(split: str = "dev") -> pd.DataFrame:
    from rag.retrieve import MODES, retrieve

    questions = [q for q in load_golden(split) if q["kind"] != "unanswerable"]
    for strategy in ("fixed", "structured"):  # load models and both indexes before timing
        for mode in MODES:
            retrieve(questions[0]["question"], k=1, mode=mode, strategy=strategy, as_of=questions[0]["as_of"])
    rows, per_q = [], []
    for strategy in ("fixed", "structured"):
        for mode in MODES:
            hits = {k: [] for k in KS}
            general = {k: [] for k in KS}
            evid = {k: [] for k in KS}
            rr, words, ms = [], [], []
            for q in questions:
                t0 = time.perf_counter()
                chunks = retrieve(q["question"], k=max(KS), mode=mode, strategy=strategy, as_of=q["as_of"])
                ms.append(1000 * (time.perf_counter() - t0))
                sections = [c.section_id for c in chunks]
                accepted = q["gold"] + q.get("also", [])
                first = next((i for i, s in enumerate(sections) if is_gold(s, accepted)), None)
                first_general = next((i for i, s in enumerate(sections) if is_gold(s, q["gold"])), None)
                rr.append(0.0 if first is None else 1.0 / (first + 1))
                words.append(sum(len(c.text.split()) for c in chunks[:max(KS)]))
                for k in KS:
                    hits[k].append(first is not None and first < k)
                    general[k].append(first_general is not None and first_general < k)
                    evid[k].append(facts_present(" ".join(c.text for c in chunks[:k]), q["must_contain"]))
                per_q.append({"strategy": strategy, "mode": mode, "id": q["id"], "kind": q["kind"],
                              "first_gold_rank": None if first is None else first + 1,
                              "first_general_rank": None if first_general is None else first_general + 1,
                              "top3": sections[:3]})
            row = {"chunking": strategy, "retrieval": mode}
            for k in KS:
                row[f"evidence_recall@{k}"] = sum(evid[k]) / len(questions)
            if strategy == "structured":
                for k in KS:
                    row[f"section_recall@{k}"] = sum(hits[k]) / len(questions)
                for k in (3, 5):
                    row[f"general_recall@{k}"] = sum(general[k]) / len(questions)
                row["mrr"] = sum(rr) / len(questions)
            row[f"context_words@{max(KS)}"] = sum(words) / len(words)
            row["ms_p50"] = float(pd.Series(ms).quantile(0.5))
            row["ms_p95"] = float(pd.Series(ms).quantile(0.95))
            rows.append(row)
            print(f"  {strategy:10s} {mode:14s} done")
    REPORTS.mkdir(parents=True, exist_ok=True)
    suffix = f"_{split}"  # the pilot's reports keep their original names
    (REPORTS / f"retrieval_per_question{suffix}.json").write_text(json.dumps(per_q, indent=1))
    df = pd.DataFrame(rows)
    df.to_csv(REPORTS / f"retrieval{suffix}.csv", index=False)
    return df


def eval_answers(limit: int | None = None, mode: str = "hybrid_rerank", split: str = "dev") -> pd.DataFrame:
    from rag.answer import answer
    from rag.llm import UsageLimitError

    out_path = REPORTS / f"answers_{split}.jsonl"
    REPORTS.mkdir(parents=True, exist_ok=True)
    done = {}
    if out_path.exists():  # resumable: a usage limit parks the run, rerun continues
        for line in out_path.read_text().splitlines():
            rec = json.loads(line)
            done[rec["id"]] = rec

    questions = load_golden(split)[:limit] if limit else load_golden(split)
    with out_path.open("a") as f:
        for q in questions:
            if q["id"] in done:
                continue
            try:
                res = answer(q["question"], mode=mode, as_of=q["as_of"])
            except UsageLimitError as e:
                print(f"Usage limit reached at {q['id']}; rerun later to resume. ({e})")
                break
            cited_sections = {res.sources[n - 1].section_id for n in res.report.cited
                              if 1 <= n <= len(res.sources)}
            rec = {
                "id": q["id"], "kind": q["kind"], "as_of": q["as_of"], "question": q["question"], "answer": res.text,
                "refused": res.report.refused,
                "citation_valid": res.report.ok,
                "invalid_citations": res.report.invalid_citations,
                "unsupported_quotes": res.report.unsupported_quotes,
                "uncited_sentences": res.report.uncited_sentences,
                "cited_sections": sorted(cited_sections),
                "fact_ok": (not res.report.refused and facts_present(res.text, q["must_contain"]))
                if q["kind"] != "unanswerable" else None,
                "cited_gold": any(is_gold(s, q["gold"] + q.get("also", [])) for s in cited_sections)
                if q["gold"] else None,
                "cited_general": any(is_gold(s, q["gold"]) for s in cited_sections) if q["gold"] else None,
                "seconds": res.seconds,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[q["id"]] = rec
            print(f"  {q['id']}: refused={rec['refused']} fact_ok={rec['fact_ok']} "
                  f"cite_ok={rec['citation_valid']} ({rec['seconds']:.0f}s)")

    recs = [done[q["id"]] for q in questions if q["id"] in done]
    summary = summarise(recs, questions)
    (REPORTS / f"answers_summary_{split}.json").write_text(json.dumps(summary, indent=2))
    return pd.DataFrame([{k: v for k, v in summary.items() if not isinstance(v, dict)}])


def summarise(recs: list[dict], questions: list[dict]) -> dict:
    """Answer metrics, plus the effective-date ones:

    superseded_cited     share of answers citing a provision not in force on the question's date.
                         Retrieval filters on the date first, so this is 0 by construction; it
                         is reported as a guard against that filter breaking.
    stale_fact_rate      for two-date pairs: share of answers whose opening line (the direct
                         answer) states the other date's fact without saying it changed
                         ("previously", "amended", "transitional", ...). The body may legitimately
                         mention the other version as history or as a sector rule, so only the
                         direct answer is tested.
    transitional_flagged of answers citing a transitional provision (the 2021 RRG today), the
                         share that say so ("transitional", "repealed", "being replaced", ...)
    pair_accuracy        complete two-date pairs with both dates answered correctly
    """
    from types import SimpleNamespace

    from ingest.versions import status

    chunks = {}
    for line in (ROOT / "data" / "processed" / "chunks_structured.jsonl").open():
        c = json.loads(line)
        chunks.setdefault(c["section_id"], SimpleNamespace(**c))
    ans = [r for r in recs if r["kind"] != "unanswerable"]
    una = [r for r in recs if r["kind"] == "unanswerable"]
    cited_status = {r["id"]: [status(chunks[s], r["as_of"]) for s in r["cited_sections"] if s in chunks] for r in recs}
    transitional = [r for r in recs if "transitional" in cited_status[r["id"]]]
    pairs = collections.defaultdict(list)
    by_id = {r["id"]: r for r in recs}
    qmap = {q["id"]: q for q in questions}
    for q in questions:
        if q.get("pair") and q["id"] in by_id:
            pairs[q["pair"]].append(by_id[q["id"]])
    pairs = {k: v for k, v in pairs.items() if len(v) == 2}
    stale = []
    for a, b in pairs.values():
        for this, other in ((a, b), (b, a)):
            opening = this["answer"].strip().splitlines()[0] if this["answer"].strip() else ""
            states_other = facts_present(opening, qmap[other["id"]]["must_contain"])
            stale.append(states_other and not CHANGE_WORDS.search(opening))
    for r in ans:  # rescore facts with the current patterns (fixes apply without a rerun)
        r["fact_ok"] = not r["refused"] and facts_present(r["answer"], qmap[r["id"]]["must_contain"])
    kinds = collections.defaultdict(list)
    for r in ans:
        kinds[r["kind"]].append(r["fact_ok"])
    return {
        "answered_questions": len(ans),
        "unanswerable_questions": len(una),
        "fact_accuracy": _mean(r["fact_ok"] for r in ans),
        "cited_gold_provision": _mean(r["cited_gold"] for r in ans),
        "cited_general_rule": _mean(r["cited_general"] for r in ans if "cited_general" in r),
        "citation_valid": _mean(r["citation_valid"] for r in ans if not r["refused"]),
        "false_refusal_rate": _mean(r["refused"] for r in ans),
        "correct_refusal_rate": _mean(r["refused"] for r in una),
        "median_seconds": float(pd.Series([r["seconds"] for r in recs]).median()) if recs else None,
        "superseded_cited": _mean("superseded" in cited_status[r["id"]] for r in recs),
        "stale_fact_rate": _mean(stale),
        "transitional_cited": len(transitional),
        "transitional_flagged": _mean(bool(STATUS_WORDS.search(r["answer"])) for r in transitional),
        "pairs": len(pairs),
        "pair_accuracy": _mean(all(r["fact_ok"] for r in v) for v in pairs.values()),
        "fact_accuracy_by_kind": {k: round(sum(map(bool, v)) / len(v), 3) for k, v in sorted(kinds.items())},
    }


STATUS_WORDS = re.compile(r"transitional|repealed|superseded|being replaced|no longer", re.I)
CHANGE_WORDS = re.compile(r"transitional|repealed|superseded|amended|previously|formerly|no longer|"
                          r"was changed|has changed|replaced|earlier|old rule|prior rule", re.I)


def _mean(values) -> float | None:
    vals = [bool(v) for v in values]
    return sum(vals) / len(vals) if vals else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["retrieval", "answers"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--split", choices=list(GOLDEN), default="dev")
    args = ap.parse_args()
    pd.set_option("display.width", 220, "display.float_format", "{:.3f}".format)
    df = eval_retrieval(args.split) if args.what == "retrieval" else eval_answers(args.limit, split=args.split)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
