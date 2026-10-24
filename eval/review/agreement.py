"""Inter-annotator agreement on the golden-set review sample.

    python -m eval.review.agreement

Compares the drafting annotator's labels (annotator_a.csv) with the second annotator's
(the your_label column of sample.csv): percent agreement and Cohen's kappa on
accept / reject, and the questions where they disagree, for adjudication.
"""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cohen_kappa(a: list[str], b: list[str]) -> float:
    labels = sorted(set(a) | set(b))
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def main() -> None:
    a = {r["id"]: r for r in csv.DictReader((HERE / "annotator_a.csv").open())}
    b = {r["id"]: r for r in csv.DictReader((HERE / "sample.csv").open())}
    ids = [i for i in b if b[i]["your_label"].strip()]
    if not ids:
        print("sample.csv has no your_label values yet")
        return
    la = [a[i]["label"].strip().lower() for i in ids]
    lb = [b[i]["your_label"].strip().lower() for i in ids]
    agree = sum(x == y for x, y in zip(la, lb))
    print(f"labelled by both: {len(ids)} of {len(b)}")
    print(f"percent agreement: {agree / len(ids):.1%}   Cohen's kappa: {cohen_kappa(la, lb):.2f}")
    print(f"rejected: annotator A {la.count('reject')}, annotator B {lb.count('reject')}")
    for i, x, y in zip(ids, la, lb):
        if x != y:
            print(f"  {i}: A={x} B={y}  | A: {a[i]['edit'] or a[i]['notes']} | B: {b[i]['your_edit'] or b[i]['notes']}")


if __name__ == "__main__":
    main()
