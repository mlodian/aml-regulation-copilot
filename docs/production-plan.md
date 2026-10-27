# Production plan

Author: Lodian Mier · Status: Phase 1 complete; Phase 2 built and evaluated, exit criteria not yet met

This document describes how the pilot grows from two public documents into a copilot that serves a compliance team over a full regulatory library and internal policy and control documents. The pilot was built so that each later phase changes components behind stable interfaces (`ingest`, `index`, `rag.retrieve`, `rag.llm`) rather than the pipeline's shape.

## Where the pilot stands

| Area | Pilot (Phase 1) | Why it is enough for now |
|---|---|---|
| Corpus | 2018 AMLA IRR (Jan 2021 amendment), 2021 AMLC reporting guidelines Part 1 | Public, verifiable, covers the questions analysts ask most |
| Size | 364 chunks | Exact search in DuckDB is milliseconds at this size |
| Retrieval | BM25 + bge-small vectors, RRF, local cross-encoder rerank | Measured: R@3 0.98, MRR 0.93 |
| LLM | Claude through the `claude` CLI, one function in `rag/llm.py` | Zero marginal cost per evaluation run |
| Verification | Deterministic citation and quote checks on every answer | 98% of answers pass; failures are surfaced, not hidden |
| Evaluation | 60-question golden set, resumable runs, per-question reports | Regression baseline for every change |
| Interface | CLI and Streamlit demo | Enough to collect analyst feedback |

## Phase 2: regulatory library

**Result.**

| | |
|---|---|
| Documents | 18, from AMLC, BSP, SEC and the Insurance Commission |
| Chunks | 1,580, 4.3 times the pilot |
| Golden set | 200 questions, 60 held out |

Met on the held-out split:
- retrieval latency: p95 0.41 s against the under-1-s target;
- the right provision in the top 5 for 96% of questions;
- both dates right on all four two-date pairs, with no stale or superseded rule given as current;
- the transitional 2021 RRG flagged in every answer that cites it.

Not met: fact accuracy is 88% and verified citations 92%, both below the 95% target. Three things cause most of it:
- **Lists:** a list split across chunks is retrieved only in part.
- **Answer hygiene:** comments about the excerpts and uncited summary sentences.
- **One out-of-library trap** that the model answered.

The fixes, in order:
1. retrieve a list's sibling items together;
2. a post-generation pass for comments about the excerpts and uncited summaries;
3. an answerability check.

Then the held-out split is run again, once. Full results are in the README.

**Scope as built.**
- **AMLC:** the 2018 IRR (both editions), the TFPSA IRR, the 2021 reporting guidelines (transitional), GoTRACS 2024, and guidelines on DNFBPs, sanctions, beneficial ownership and sanctions screening, plus the administrative sanctions rules.
- **BSP:** MORB Part IX, the 2025 consolidated edition.
- **SEC:** MC 16, s. 2018 and MC 4, s. 2021.
- **Insurance Commission:** five circular letters.
- **Not included:** the FATF Recommendations stay optional.

**Work.**
- **Effective-date versioning.** Store each provision with `effective_from`/`effective_to` and the amending issuance, so a question can be answered as of a date and superseded text is never served as current. In the pilot this is handled by dropping footnotes; at library scale it has to be modelled explicitly.
- **Per-issuer heading grammars.** Each issuer formats provisions differently. The chunker already takes a per-document profile (`ingest/chunk.py: PROFILES`). Phase 2 adds profiles and a check that flags documents where too much text falls outside any recognised heading.
- **OCR path** for scanned issuances (RA 11521 is the first example), with a confidence threshold below which a page is routed for manual review rather than indexed.
- **Golden set to 200+ questions**, written by two annotators with agreement measured, and split into a development set and a held-out set that is only run at release.
- **Change detection.** Re-run the manifest on a schedule, and when a document's SHA-256 changes, re-index it and run the evaluation automatically.

**Exit criteria.** Fact accuracy and verified-citation rate stay at or above 95% on the held-out split with a corpus roughly ten times larger, and retrieval latency stays under one second before generation.

**What changed from the plan.**
- **Versioning became the centre of Phase 2.** GoTRACS (December 2024) repealed the 2021 RRG, which the pilot was built on, but kept it in force during the transition.
- **Several first-guess thresholds were replaced once tested against data:**
  - the OCR confidence gate became a floor for unreadable pages, and a check that numbers written twice agree took its place;
  - a coverage percentage became a missed-heading check;
  - a text-similarity cut-off became word-for-word comparison of IRR editions.

## Phase 3: internal documents

**Scope.** AML/CTF policy manuals, the money laundering and terrorism financing prevention programme (MTPP), the control inventory, and automated test-case definitions from the compliance testing programme.

**Work.**
- **Control-to-regulation mapping at inventory scale.** Run `rag.mapper` over every control and test case and produce a coverage matrix: which requirements are covered, partly covered, or have no control at all. Every cell links to the requirement quote and the control text, and every mapping goes to a reviewer before it counts.
- **Access control.** Internal documents carry their source system's permissions. Retrieval filters on the user's entitlements *before* ranking, so a restricted chunk can never reach the prompt.
- **Data handling.** No customer data is indexed. Documents are scanned for personal data on ingestion and blocked if any is found. Prompts and answers are logged without free-text customer identifiers.
- **Formats.** DOCX, HTML and spreadsheet ingestion alongside PDF, keeping the same citable addressing (document, section, version).

**Exit criteria.** Mapper output agrees with compliance reviewers on a sample of at least 100 control-requirement pairs at an agreed threshold. No access-control violations in a red-team test.

## Phase 4: production hardening

| Concern | Pilot | Production |
|---|---|---|
| LLM backend | `claude` CLI (`rag/llm.py`) | API backend with enterprise data controls (no training on inputs, regional processing where required), same `complete()` interface |
| Vector store | DuckDB exact search | Postgres + pgvector or a managed store once the corpus passes ~100k chunks; BM25 moves to the database's full-text search |
| Reranker | Local MiniLM cross-encoder | Same model served behind an internal endpoint, or a larger reranker if the held-out evaluation justifies the latency |
| Evaluation | Run by hand | Gate in CI: a pull request that lowers held-out fact accuracy or the verified-citation rate fails |
| Observability | Per-run JSONL reports | Every request logs query, retrieved provision IDs, verifier result, latency and user feedback; dashboards track refusal rate, verifier failures and drift |
| Interface | Streamlit | Internal web app with SSO; answers that fail the verifier are shown with a warning, never silently |
| Governance | — | Model risk documentation, periodic re-validation, and a named owner for the corpus and golden set |

## Risks and controls

| Risk | Control |
|---|---|
| Superseded text served as current law | Effective-date versioning: retrieval filters on the question's date before ranking; transitional rules always shown with their replacement and flagged in the answer. Held-out: 0 superseded citations, 0 stale answers |
| Wrong effective date on a document | Each date's basis recorded in the manifest. Most issuances do not print their publication date, so approval dates stand in and can be early by a few weeks; only consolidated editions exist for the BSP manual |
| Fluent but unsupported answer | Deterministic citation and quote verification on every answer; refusal instruction; verifier failures logged and shown |
| Retrieval misses the governing provision | Hybrid retrieval and reranking; per-question retrieval reports; misses added to the golden set |
| Golden set overfitting | Held-out split drawn only from questions never used while building, run once per release; grading checked automatically for facts that echo the question or match inside other words; a sampled second review (automated so far, to be confirmed by a person); new questions from real analyst queries |
| Confidential documents reaching the wrong user | Entitlement filtering before ranking; no customer data in the corpus |
| Over-reliance by users | Positioned as research support with sources always shown; mapping results require reviewer sign-off |

## Success measures

- Analyst time to answer a regulatory question, before and after, on a sample of real queries.
- Share of the control inventory with a reviewed regulatory mapping, and the number of genuine gaps found.
- Held-out fact accuracy and verified-citation rate per release, plus refusal rate on out-of-corpus questions.
