# Golden-set review

`sample.csv` holds 40 questions from the golden set (34 drafted for Phase 2, 6 pilot
questions relabelled for Phase 2), drawn by `make_sample.py`. Please fill in
`your_label` for every row, without looking at `annotator_a.csv`:

- **accept**: a compliance analyst would ask this question this way, the expected
  provisions answer it on the `asked_as_of` date, and the required facts are what a
  correct answer must state, no more and no less.
- **reject**: the question is ambiguous, an expected provision is wrong or missing, or
  a required fact is wrong, too strict (a correct answer could fail it) or too loose (a
  wrong answer could pass it). Say what should change in `your_edit`.

For unanswerable rows, accept if the library really cannot answer the question.

Then run `python -m eval.review.agreement` for percent agreement and Cohen's kappa;
the disagreements are adjudicated and fixed in `eval/build/` before the evaluation runs.
