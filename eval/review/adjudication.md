# Golden-set review: agreement and adjudication

Sample: 40 questions (`sample.csv`), drawn by `make_sample.py` before any evaluation run.
Annotator A drafted the questions (`annotator_a.csv`). Annotator B reviewed them
independently: an automated second review, without access to A's labels. It still
needs a person to confirm it.

| | A | B |
|---|---|---|
| rejected | 2 | 16 |
| percent agreement | 65.0% | |
| Cohen's kappa | 0.15 | |

The low kappa reflects A being too lenient, not B being noisy. B's rejects were checked
against the source text and all were upheld. 14 were disagreements; A's two rejects
(a06, s07) were also rejected by B.

## What the rejects had in common

Most were required facts that a wrong answer could still pass:

- **Unanchored numbers.** "20" matches "2024", "two" matches "network", "ten" matches
  "extension".
- **Facts already in the question.** "real estate" in "Are real estate brokers covered
  persons?", or "before" in "Must banks assess risks before launching?".

Both are now checked by `eval/validate_golden.py` across all 200 questions, not just
the sample. That check found 100 cases: 82 unanchored numbers and 18 echoed facts,
including four in the pilot questions. Anchoring is applied mechanically to every
question (`eval/build/review_fixes.anchor_numbers`). Echoed facts were fixed one by
one, rewording the question where the fact could not be separated from it.

The remaining rejects corrected the gold labels:

- **q16:** the BO Guidelines section labelled was the definition of legal owners; it
  is now the ownership prong, and the GoTRACS beneficial-owner definition is added.
- **q23, q28:** a whole-Part label was narrowed to the provision.
- **q28:** now also requires the current GoTRACS list, which adds graft and corrupt
  practices.

All fixes are in `eval/build/review_fixes.py`.

## Effect on the pilot result

Rescoring the pilot's saved answers (`eval/reports/answers.jsonl`) with the corrected
patterns leaves fact accuracy at 49 of 50 except for q28. q28 now requires the GoTRACS
list, which was not in the pilot corpus. The loose patterns did not inflate the pilot
score; they only could not have caught a wrong answer.

## Limits

Only 40 of 200 questions were reviewed. The two systematic flaws are now checked
automatically for all of them, but other kinds of error in the unreviewed 160 (an
ambiguous question, a missing alternative provision) would not be.
