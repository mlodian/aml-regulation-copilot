"""Render the README charts from eval/reports/*.csv / *.json."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "eval" / "reports"
OUT = ROOT / "docs" / "charts"

SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"
CHOSEN, BASELINE = "#2a78d6", "#b9b8b2"
LABELS = {"bm25": "BM25 only", "vector": "Vectors only", "hybrid": "Hybrid (RRF)",
          "hybrid_rerank": "Hybrid + rerank"}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=10)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def retrieval_chart() -> Path:
    df = pd.read_csv(REPORTS / "retrieval.csv")
    df = df[df.chunking == "structured"].set_index("retrieval").loc[list(LABELS)]
    metrics = [("section_recall@1", "Right provision ranked first"),
               ("section_recall@3", "Right provision in top 3"),
               ("mrr", "Mean reciprocal rank")]
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.2), sharey=True, facecolor=SURFACE)
    names = [LABELS[m] for m in df.index]
    colors = [CHOSEN if m == "hybrid_rerank" else BASELINE for m in df.index]
    for ax, (col, title) in zip(axes, metrics):
        vals = df[col].values
        ax.barh(names, vals, color=colors, height=0.55)
        for y, v in enumerate(vals):
            ax.text(v + 0.01, y, f"{v:.2f}", va="center", fontsize=10, color=INK)
        ax.set_xlim(0, 1.12)
        ax.set_title(title, loc="left", fontsize=11, color=INK, pad=8)
        _style(ax)
    axes[0].invert_yaxis()
    fig.suptitle("Retrieval on 50 answerable questions (structure-aware chunks)",
                 x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "retrieval_ablation.png"
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


def answers_chart() -> Path | None:
    path_json = REPORTS / "answers_summary.json"
    if not path_json.exists():
        return None
    s = json.loads(path_json.read_text())
    rows = [("Facts correct", s["fact_accuracy"]),
            ("Cites a gold provision", s["cited_gold_provision"]),
            ("Citations pass verifier", s["citation_valid"]),
            ("Refuses unanswerable", s["correct_refusal_rate"]),
            ("Answers answerable (no false refusal)", 1 - s["false_refusal_rate"])]
    fig, ax = plt.subplots(figsize=(9, 3.4), facecolor=SURFACE)
    names, vals = zip(*rows)
    ax.barh(names, vals, color=CHOSEN, height=0.55)
    for y, v in enumerate(vals):
        ax.text(v + 0.01, y, f"{v:.0%}", va="center", fontsize=10, color=INK)
    ax.set_xlim(0, 1.1)
    ax.invert_yaxis()
    _style(ax)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    fig.suptitle(f"End-to-end answers: {s['answered_questions']} answerable + "
                 f"{s['unanswerable_questions']} out-of-corpus questions",
                 x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout()
    path = OUT / "answer_quality.png"
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


# Phase 2: dev and held-out side by side (categorical slots 1 and 2 of the validated palette)
SPLITS = (("heldout", "Held-out", "#2a78d6"), ("dev", "Dev", "#eb6834"))


def _paired_bars(ax, names, values: dict, fmt, notes: dict | None = None) -> None:
    """Two bars per row, held-out first, a 2px surface gap between them, values labelled
    (notes[split][row], e.g. "7/8", replaces the label where the count matters)."""
    h = 0.36
    for k, (split, label, color) in enumerate(SPLITS):
        ys = [i + (k - 0.5) * (h + 0.04) for i in range(len(names))]
        vals = values[split]
        ax.barh(ys, vals, height=h, color=color, label=label, edgecolor=SURFACE, linewidth=1)
        for row, (y, v) in enumerate(zip(ys, vals)):
            text = (notes or {}).get(split, {}).get(row) or fmt(v)
            ax.text(v + 0.01, y, text, va="center", fontsize=9, color=INK,
                    bbox=dict(boxstyle="square,pad=0.1", facecolor=SURFACE, edgecolor="none"))
    ax.set_yticks(range(len(names)), names)
    ax.invert_yaxis()


def phase2_retrieval_chart() -> Path:
    frames = {s: pd.read_csv(REPORTS / f"retrieval_{s}.csv") for s, _, _ in SPLITS}
    rows = {s: df[df.chunking == "structured"].set_index("retrieval").loc[list(LABELS)] for s, df in frames.items()}
    metrics = [("section_recall@3", "Right provision in top 3"), ("section_recall@5", "Right provision in top 5"),
               ("mrr", "Mean reciprocal rank (top 5)")]
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), sharey=True, facecolor=SURFACE)
    for ax, (col, title) in zip(axes, metrics):
        _paired_bars(ax, [LABELS[m] for m in LABELS], {s: rows[s][col].values for s in rows}, lambda v: f"{v:.2f}")
        ax.set_xlim(0, 1.15)
        ax.set_title(title, loc="left", fontsize=11, color=INK, pad=8)
        _style(ax)
    n = {s: len([q for q in json.loads((REPORTS / f"retrieval_per_question_{s}.json").read_text())
                 if q["strategy"] == "structured" and q["mode"] == "hybrid_rerank"]) for s in rows}
    fig.legend(*axes[0].get_legend_handles_labels(), frameon=False, fontsize=9.5, loc="upper right", ncol=2)
    fig.suptitle(f"Phase 2 retrieval, 18 documents: {n['heldout']} held-out and {n['dev']} dev questions",
                 x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "phase2_retrieval.png"
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


def phase2_answers_chart() -> Path | None:
    summaries = {s: REPORTS / f"answers_summary_{s}.json" for s, _, _ in SPLITS}
    if not all(p.exists() for p in summaries.values()):
        return None
    sm = {s: json.loads(p.read_text()) for s, p in summaries.items()}
    rows = [("fact_accuracy", "Facts correct"), ("citation_valid", "Every citation verified"),
            ("cited_gold_provision", "Cites a gold provision"), ("cited_general_rule", "Cites the general rule"),
            ("correct_refusal_rate", "Refuses unanswerable"), ("transitional_flagged", "Flags the transitional RRG")]
    fig, ax = plt.subplots(figsize=(9.5, 4.2), facecolor=SURFACE)
    # small samples carry their counts: unanswerable questions, answers citing the transitional RRG
    notes = {s: {4: f"{round(sm[s]['correct_refusal_rate'] * sm[s]['unanswerable_questions'])}/{sm[s]['unanswerable_questions']}",
                 5: f"{round(sm[s]['transitional_flagged'] * sm[s]['transitional_cited'])}/{sm[s]['transitional_cited']}"}
             for s in sm}
    _paired_bars(ax, [label for _, label in rows], {s: [sm[s][k] for k, _ in rows] for s in sm},
                 lambda v: f"{v:.0%}", notes)
    ax.plot([0.95, 0.95], [-0.62, 1.5], color=MUTED, linewidth=1, linestyle=(0, (3, 3)), zorder=1)  # facts, citations
    ax.text(0.945, -0.62, "Phase 2 target 95%", ha="right", va="center", fontsize=8.5, color=MUTED)
    ax.set_xlim(0, 1.12)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    _style(ax)
    fig.legend(*ax.get_legend_handles_labels(), frameon=False, fontsize=9.5, loc="upper right", ncol=2,
               bbox_to_anchor=(0.99, 0.93))
    h, d = sm["heldout"], sm["dev"]
    fig.suptitle(f"Phase 2 answers: held-out {h['answered_questions']} + {h['unanswerable_questions']} unanswerable, "
                 f"dev {d['answered_questions']} + {d['unanswerable_questions']}",
                 x=0.01, ha="left", fontsize=12.5, color=INK, fontweight="bold")
    fig.tight_layout()
    path = OUT / "phase2_answers.png"
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return path


if __name__ == "__main__":
    print(retrieval_chart())
    print(answers_chart())
    print(phase2_retrieval_chart())
    print(phase2_answers_chart())
