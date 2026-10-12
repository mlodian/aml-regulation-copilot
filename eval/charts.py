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


if __name__ == "__main__":
    print(retrieval_chart())
    print(answers_chart())
