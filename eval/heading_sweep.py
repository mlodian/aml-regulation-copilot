"""What the chunking checks catch: remove each level of each heading grammar in turn.

    python -m eval.heading_sweep

For every indexed document with a grammar, and for each level of that grammar, the
document is parsed with that one level removed and measured with ingest.coverage.
A removal counts as a break when it changes the parsed sections. Writes
eval/reports/heading_sweep.json and prints which check flags each break (each break is
credited to the first check that flags it: missed headings, then coverage, then no sections).
"""
from __future__ import annotations

import json
from pathlib import Path

import ingest.chunk as chunk_mod
from ingest.chunk import PROFILES, indexable_docs, parse_sections
from ingest.coverage import MIN_COVERAGE, measure

ROOT = Path(__file__).resolve().parents[1]


def body_coverage(m) -> float | None:
    body = m.words - (m.preamble_words if m.preamble_indexed else 0)
    return round(m.headed_words / body, 4) if body else None


def sections(doc: dict) -> list:
    return [h for h, _ in parse_sections(doc)]


def main() -> None:
    intact, broken = [], []
    for doc in indexable_docs():
        saved = PROFILES[doc["id"]]
        levels = saved["levels"]
        if not levels:
            continue
        base, m = sections(doc), measure(doc)
        intact.append({"doc_id": doc["id"], "coverage": body_coverage(m), "flagged": m.flagged})
        for drop in range(len(levels)):
            chunk_mod.PROFILES[doc["id"]] = dict(saved, levels=[lv for i, lv in enumerate(levels) if i != drop])
            try:
                m, after = measure(doc), sections(doc)
            finally:
                chunk_mod.PROFILES[doc["id"]] = saved
            cov = body_coverage(m)
            broken.append({
                "doc_id": doc["id"], "level_removed": drop, "levels": len(levels), "changed": after != base,
                "sections": [len(base), len(after)], "coverage": cov,
                "missed_headings": len(m.missed_headings),
                "by_missed_headings": bool(m.missed_headings),
                "by_coverage": cov is not None and cov < MIN_COVERAGE and not m.missed_headings,
                "by_no_sections": not m.sections and not m.missed_headings and not (cov is not None and cov < MIN_COVERAGE),
                "flagged": m.flagged,
            })
    breaks = [b for b in broken if b["changed"]]
    summary = {
        "grammars_tested": len(intact),
        "removals": len(broken),
        "breaks": len(breaks),
        "flagged_by_missed_headings": sum(b["by_missed_headings"] for b in breaks),
        "flagged_by_coverage": sum(b["by_coverage"] for b in breaks),
        "flagged_by_no_sections": sum(b["by_no_sections"] for b in breaks),
        "flagged": sum(b["flagged"] for b in breaks),
        "intact_coverage_range": [min(i["coverage"] for i in intact if i["coverage"] is not None),
                                  max(i["coverage"] for i in intact if i["coverage"] is not None)],
        "intact_flagged": sum(i["flagged"] for i in intact),
        "coverage_of_breaks_flagged_by_coverage": sorted(b["coverage"] for b in breaks if b["by_coverage"]),
        "min_coverage": MIN_COVERAGE,
    }
    out = ROOT / "eval" / "reports" / "heading_sweep.json"
    out.write_text(json.dumps({"summary": summary, "intact": intact, "broken": broken}, indent=1))
    print(json.dumps(summary, indent=1))
    for b in breaks:
        if not b["flagged"]:
            print(f"not flagged: {b['doc_id']} without level {b['level_removed']} "
                  f"(sections {b['sections'][0]} -> {b['sections'][1]}, coverage {b['coverage']})")


if __name__ == "__main__":
    main()
