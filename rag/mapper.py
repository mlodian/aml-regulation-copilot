"""Control-to-regulation mapping.

Given a description of an internal control or test case, find the provisions it
should satisfy and judge, provision by provision, whether the control covers
the requirement, covers it partly, or leaves a gap. Retrieval and the final
coverage table are deterministic; the LLM only judges each pairing and must
quote the requirement it is judging, which is then verified against the source.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ingest.chunk import Chunk
from rag import llm
from rag.cite_check import quote_supported
from rag.retrieve import retrieve

STATUSES = ("covered", "partial", "gap", "not_applicable")

SYSTEM = """You are an AML compliance assurance reviewer in the Philippines.
You compare an internal control against regulatory provisions and return JSON only."""

PROMPT = """CONTROL UNDER REVIEW
{control}

PROVISIONS (numbered)
{provisions}

For EACH numbered provision, decide how the control relates to it:
- "covered": the control fully addresses what the provision requires
- "partial": the control addresses some but not all of it
- "gap": the provision applies to this control's scope but the control does not address it
- "not_applicable": the provision is unrelated to this control's scope

Return JSON of this exact shape:
{{"assessments": [
  {{"n": 1, "status": "covered|partial|gap|not_applicable",
    "requirement_quote": "<exact words copied from provision n stating the requirement>",
    "reason": "<one sentence>",
    "recommendation": "<one sentence for partial/gap, else empty>"}}
]}}"""


@dataclass
class Assessment:
    provision: Chunk
    status: str
    requirement_quote: str
    reason: str
    recommendation: str
    quote_verified: bool


@dataclass
class MappingResult:
    control: str
    assessments: list[Assessment] = field(default_factory=list)

    def by_status(self, status: str) -> list[Assessment]:
        return [a for a in self.assessments if a.status == status]


def map_control(control: str, k: int = 8, as_of: str | None = None) -> MappingResult:
    """Map a control to the requirements in force on `as_of` (YYYY-MM-DD, default today)."""
    from rag.answer import format_context, source_text

    chunks = retrieve(control, k=k, as_of=as_of)
    provisions = format_context(chunks, as_of)
    data = llm.complete_json(PROMPT.format(control=control, provisions=provisions), system=SYSTEM)

    result = MappingResult(control)
    for item in data.get("assessments", []):
        n = item.get("n")
        if not isinstance(n, int) or not 1 <= n <= len(chunks):
            continue
        status = item.get("status") if item.get("status") in STATUSES else "gap"
        quote = item.get("requirement_quote", "")
        provision, verified = chunks[n - 1], bool(quote) and quote_supported(quote, [source_text(chunks[n - 1])])
        if quote and not verified:
            # the model sometimes labels a genuine quote with the wrong excerpt number;
            # re-point it to the supplied excerpt that actually contains the wording
            match = next((c for c in chunks if quote_supported(quote, [source_text(c)])), None)
            if match is not None:
                provision, verified = match, True
        result.assessments.append(Assessment(
            provision=provision, status=status, requirement_quote=quote,
            reason=item.get("reason", ""), recommendation=item.get("recommendation", ""),
            quote_verified=verified,
        ))
    order = {s: i for i, s in enumerate(("gap", "partial", "covered", "not_applicable"))}
    result.assessments.sort(key=lambda a: order[a.status])
    return result
