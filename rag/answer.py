"""Grounded question answering with verifiable citations."""
from __future__ import annotations

import time
from dataclasses import dataclass
from functools import lru_cache

from index.store import today
from ingest.chunk import Chunk
from ingest.download import load_manifest
from ingest.versions import status
from rag import llm
from rag.cite_check import REFUSAL, CitationReport, check
from rag.retrieve import retrieve

SYSTEM = f"""You are an AML/CTF regulatory research assistant for the Philippines.
You answer ONLY from the numbered source excerpts supplied in the user message.

Rules:
1. Every sentence that states a rule, number, deadline or obligation must end with
   the number(s) of the excerpt(s) that support it, e.g. [2] or [1, 3]. This includes
   the opening one-line answer (e.g. "Yes, attempts must be reported [5].").
2. When you quote wording, copy it exactly inside double quotes and cite it.
3. Each excerpt's header names its issuer and its status on the question's date.
   Prefer CURRENT excerpts. If your answer relies on an excerpt marked TRANSITIONAL,
   say so in one sentence and name the issuance replacing it (shown in its header).
   Take the general rule from the AMLC issuances, and add the BSP, SEC or IC rules
   when the question concerns entities that regulator supervises.
4. If the excerpts do not contain the answer, reply with exactly {REFUSAL} on the first
   line, then one sentence saying what is missing. Do not use outside knowledge, and
   do not guess numbers that are not in the excerpts.
5. Be concise: a direct answer first, then supporting detail as short bullets if needed.
6. This is research support, not legal advice; do not add disclaimers unless asked."""


@dataclass
class Answer:
    question: str
    text: str
    sources: list[Chunk]
    report: CitationReport
    seconds: float


@lru_cache(maxsize=1)
def doc_shorts() -> dict[str, str]:
    return {d["id"]: d["short"] for d in load_manifest()}


def status_note(c: Chunk, as_of: str) -> str:
    """'AMLC · CURRENT since 2024-12-11' or 'AMLC · TRANSITIONAL: being replaced by GoTRACS'."""
    state = status(c, as_of)
    if state == "transitional":
        repl = doc_shorts().get((c.superseded_by or "").split(":")[0], c.superseded_by)
        return f"{c.issuer} · TRANSITIONAL: repealed by {repl}, in force until it is fully implemented"
    since = f" since {c.effective_from}" if c.effective_from else ""
    return f"{c.issuer} · {state.upper()}{since}"


def format_context(chunks: list[Chunk], as_of: str | None = None) -> str:
    as_of = as_of or today()
    blocks = [f"[{i}] {c.citation}{' — ' + c.heading.split(' > ')[-1] if c.heading else ''} "
              f"({status_note(c, as_of)})\n{c.text}" for i, c in enumerate(chunks, start=1)]
    return "\n\n".join(blocks)


def answer(question: str, k: int = 6, mode: str = "hybrid_rerank", as_of: str | None = None) -> Answer:
    """Answer `question` from the provisions in force on `as_of` (YYYY-MM-DD, default today)."""
    t0 = time.perf_counter()
    chunks = retrieve(question, k=k, mode=mode, as_of=as_of)
    when = f" (as of {as_of})" if as_of else ""
    prompt = f"SOURCE EXCERPTS\n\n{format_context(chunks, as_of)}\n\nQUESTION{when}\n{question}"
    text = llm.complete(prompt, system=SYSTEM).strip()
    report = check(text, [c.text for c in chunks])
    return Answer(question, text, chunks, report, time.perf_counter() - t0)
