"""Grounded question answering with verifiable citations."""
from __future__ import annotations

import time
from dataclasses import dataclass

from ingest.chunk import Chunk
from rag import llm
from rag.cite_check import REFUSAL, CitationReport, check
from rag.retrieve import retrieve

SYSTEM = f"""You are an AML/CTF regulatory research assistant for the Philippines.
You answer ONLY from the numbered source excerpts supplied in the user message.

Rules:
1. Every sentence that states a rule, number, deadline or obligation must end with
   the number(s) of the excerpt(s) that support it, e.g. [2] or [1, 3].
2. When you quote wording, copy it exactly inside double quotes and cite it.
3. Prefer the 2018 IRR for the rule itself and the 2021 RRG for reporting procedure.
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


def format_context(chunks: list[Chunk]) -> str:
    blocks = [f"[{i}] {c.citation} — {c.heading.split(' > ')[-1]}\n{c.text}"
              for i, c in enumerate(chunks, start=1)]
    return "\n\n".join(blocks)


def answer(question: str, k: int = 6, mode: str = "hybrid_rerank") -> Answer:
    t0 = time.perf_counter()
    chunks = retrieve(question, k=k, mode=mode)
    prompt = f"SOURCE EXCERPTS\n\n{format_context(chunks)}\n\nQUESTION\n{question}"
    text = llm.complete(prompt, system=SYSTEM).strip()
    report = check(text, [c.text for c in chunks])
    return Answer(question, text, chunks, report, time.perf_counter() - t0)
