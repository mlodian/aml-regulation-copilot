"""Command-line interface.

    python copilot.py ask "When must an STR be filed?"
    python copilot.py map "Daily batch screens new customers against UN sanctions lists"
    python copilot.py search "covered transaction threshold" --mode bm25
"""
from __future__ import annotations

import argparse
import textwrap

STATUS_LABEL = {"gap": "GAP", "partial": "PARTIAL", "covered": "COVERED", "not_applicable": "n/a"}


def cmd_ask(args) -> None:
    from rag.answer import answer
    res = answer(args.question, k=args.k)
    print("\n" + res.text + "\n")
    print("Sources")
    for i, c in enumerate(res.sources, start=1):
        mark = "*" if i in res.report.cited else " "
        print(f" {mark}[{i}] {c.citation} — {c.heading.split(' > ')[-1]} (p. {c.page_start})")
    status = "verified" if res.report.ok else "CHECK"
    print(f"\nCitations {status}", end="")
    if not res.report.ok:
        print(f": invalid={res.report.invalid_citations} "
              f"unsupported_quotes={len(res.report.unsupported_quotes)} "
              f"uncited_sentences={len(res.report.uncited_sentences)}", end="")
    print(f"  ·  {res.seconds:.1f}s")


def cmd_map(args) -> None:
    from rag.mapper import map_control
    res = map_control(args.control, k=args.k)
    for a in res.assessments:
        if a.status == "not_applicable" and not args.all:
            continue
        flag = "" if a.quote_verified else "  (quote not verified)"
        print(f"\n{STATUS_LABEL[a.status]:8s} {a.provision.citation} — "
              f"{a.provision.heading.split(' > ')[-1]}{flag}")
        print(textwrap.fill(f"Requirement: \"{a.requirement_quote}\"", 100, initial_indent="  ",
                            subsequent_indent="  "))
        print(textwrap.fill(f"Why: {a.reason}", 100, initial_indent="  ", subsequent_indent="  "))
        if a.recommendation:
            print(textwrap.fill(f"Fix: {a.recommendation}", 100, initial_indent="  ",
                                subsequent_indent="  "))


def cmd_search(args) -> None:
    from rag.retrieve import retrieve
    for i, c in enumerate(retrieve(args.query, k=args.k, mode=args.mode), start=1):
        print(f"[{i}] {c.citation} — {c.heading.split(' > ')[-1]}")
        print(textwrap.indent(textwrap.shorten(c.text, 240), "    "))


def main() -> None:
    ap = argparse.ArgumentParser(description="AML Regulation Copilot")
    sub = ap.add_subparsers(required=True)

    p = sub.add_parser("ask", help="answer a question with citations")
    p.add_argument("question")
    p.add_argument("-k", type=int, default=6)
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("map", help="map a control to the provisions it should satisfy")
    p.add_argument("control")
    p.add_argument("-k", type=int, default=8)
    p.add_argument("--all", action="store_true", help="also show unrelated provisions")
    p.set_defaults(fn=cmd_map)

    p = sub.add_parser("search", help="retrieval only, no LLM")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=5)
    p.add_argument("--mode", default="hybrid_rerank",
                   choices=["bm25", "vector", "hybrid", "hybrid_rerank"])
    p.set_defaults(fn=cmd_search)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
