"""Evaluation harness.

    python -m eval.run_eval retrieval          # no LLM: retrieval ablation table
    python -m eval.run_eval answers [--limit N] # end-to-end answers through the LLM backend

Retrieval metrics
  section_recall@k  a gold provision is among the top-k chunks (structured chunks only;
                    fixed windows have no provision address)
  evidence_recall@k the top-k chunk texts together contain every required fact; this is
                    comparable across chunking strategies
  mrr               reciprocal rank of the first gold provision
  context_words@5   words handed to the LLM; evidence recall rises with chunk size, so
                    compare strategies at similar context budgets

Answer metrics
  fact_accuracy     answer states every required fact (answerable questions)
  citation_valid    every [n] refers to a supplied block and every quote is found in the block it cites
  cited_gold        the answer cites at least one gold provision
  refusal_correct   answer refuses on unanswerable questions / answers the answerable ones
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval" / "golden.yaml"
REPORTS = ROOT / "eval" / "reports"
KS = (1, 3, 5)


def load_golden() -> list[dict]:
    return yaml.safe_load(GOLDEN.read_text())["questions"]


def is_gold(section_id: str, gold: list[str]) -> bool:
    """A gold label may name a provision or any ancestor of it (e.g. a whole Part)."""
    return any(section_id == g or section_id.startswith(g + ":") for g in gold)


def facts_present(text: str, patterns: list[str]) -> bool:
    return all(re.search(p, text, re.I) for p in patterns)


def eval_retrieval() -> pd.DataFrame:
    from rag.retrieve import MODES, retrieve

    questions = [q for q in load_golden() if q["kind"] != "unanswerable"]
    rows, per_q = [], []
    for strategy in ("fixed", "structured"):
        for mode in MODES:
            t0 = time.perf_counter()
            hits = {k: [] for k in KS}
            evid = {k: [] for k in KS}
            rr, words = [], []
            for q in questions:
                chunks = retrieve(q["question"], k=max(KS), mode=mode, strategy=strategy)
                sections = [c.section_id for c in chunks]
                first = next((i for i, s in enumerate(sections) if is_gold(s, q["gold"])), None)
                rr.append(0.0 if first is None else 1.0 / (first + 1))
                words.append(sum(len(c.text.split()) for c in chunks[:max(KS)]))
                for k in KS:
                    hits[k].append(first is not None and first < k)
                    evid[k].append(facts_present(" ".join(c.text for c in chunks[:k]), q["must_contain"]))
                per_q.append({"strategy": strategy, "mode": mode, "id": q["id"],
                              "first_gold_rank": None if first is None else first + 1,
                              "top3": sections[:3]})
            row = {"chunking": strategy, "retrieval": mode}
            for k in KS:
                row[f"evidence_recall@{k}"] = sum(evid[k]) / len(questions)
            if strategy == "structured":
                for k in KS:
                    row[f"section_recall@{k}"] = sum(hits[k]) / len(questions)
                row["mrr"] = sum(rr) / len(questions)
            row[f"context_words@{max(KS)}"] = sum(words) / len(words)
            row["ms_per_query"] = 1000 * (time.perf_counter() - t0) / len(questions)
            rows.append(row)
            print(f"  {strategy:10s} {mode:14s} done")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "retrieval_per_question.json").write_text(json.dumps(per_q, indent=1))
    df = pd.DataFrame(rows)
    df.to_csv(REPORTS / "retrieval.csv", index=False)
    return df


def eval_answers(limit: int | None = None, mode: str = "hybrid_rerank") -> pd.DataFrame:
    from rag.answer import answer
    from rag.llm import UsageLimitError

    out_path = REPORTS / "answers.jsonl"
    REPORTS.mkdir(parents=True, exist_ok=True)
    done = {}
    if out_path.exists():  # resumable: a usage limit parks the run, rerun continues
        for line in out_path.read_text().splitlines():
            rec = json.loads(line)
            done[rec["id"]] = rec

    questions = load_golden()[:limit] if limit else load_golden()
    with out_path.open("a") as f:
        for q in questions:
            if q["id"] in done:
                continue
            try:
                res = answer(q["question"], mode=mode)
            except UsageLimitError as e:
                print(f"Usage limit reached at {q['id']}; rerun later to resume. ({e})")
                break
            cited_sections = {res.sources[n - 1].section_id for n in res.report.cited
                              if 1 <= n <= len(res.sources)}
            rec = {
                "id": q["id"], "kind": q["kind"], "question": q["question"], "answer": res.text,
                "refused": res.report.refused,
                "citation_valid": res.report.ok,
                "invalid_citations": res.report.invalid_citations,
                "unsupported_quotes": res.report.unsupported_quotes,
                "uncited_sentences": res.report.uncited_sentences,
                "cited_sections": sorted(cited_sections),
                "fact_ok": (not res.report.refused and facts_present(res.text, q["must_contain"]))
                if q["kind"] != "unanswerable" else None,
                "cited_gold": any(is_gold(s, q["gold"]) for s in cited_sections) if q["gold"] else None,
                "seconds": res.seconds,
            }
            f.write(json.dumps(rec) + "\n")
            f.flush()
            done[q["id"]] = rec
            print(f"  {q['id']}: refused={rec['refused']} fact_ok={rec['fact_ok']} "
                  f"cite_ok={rec['citation_valid']} ({rec['seconds']:.0f}s)")

    recs = [done[q["id"]] for q in questions if q["id"] in done]
    ans = [r for r in recs if r["kind"] != "unanswerable"]
    una = [r for r in recs if r["kind"] == "unanswerable"]
    summary = {
        "answered_questions": len(ans),
        "unanswerable_questions": len(una),
        "fact_accuracy": _mean(r["fact_ok"] for r in ans),
        "cited_gold_provision": _mean(r["cited_gold"] for r in ans),
        "citation_valid": _mean(r["citation_valid"] for r in ans if not r["refused"]),
        "false_refusal_rate": _mean(r["refused"] for r in ans),
        "correct_refusal_rate": _mean(r["refused"] for r in una),
        "median_seconds": float(pd.Series([r["seconds"] for r in recs]).median()) if recs else None,
    }
    (REPORTS / "answers_summary.json").write_text(json.dumps(summary, indent=2))
    return pd.DataFrame([summary])


def _mean(values) -> float | None:
    vals = [bool(v) for v in values]
    return sum(vals) / len(vals) if vals else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["retrieval", "answers"])
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    pd.set_option("display.width", 200, "display.float_format", "{:.3f}".format)
    df = eval_retrieval() if args.what == "retrieval" else eval_answers(args.limit)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
