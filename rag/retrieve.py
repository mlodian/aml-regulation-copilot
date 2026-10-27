"""Retrieval modes compared in the ablation: bm25, vector, hybrid, hybrid+rerank."""
from __future__ import annotations

import re
from functools import lru_cache

from index.store import Index, today
from ingest.chunk import Chunk
from ingest.versions import status
from rag.fusion import rrf

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CANDIDATES = 30  # pool handed to RRF / the reranker
MODES = ("bm25", "vector", "hybrid", "hybrid_rerank")


@lru_cache(maxsize=2)
def get_index(strategy: str = "structured") -> Index:
    return Index(strategy)


@lru_cache(maxsize=1)
def reranker():
    from sentence_transformers import CrossEncoder
    return CrossEncoder(RERANK_MODEL)


# A question that names a document or a regulator ("under the 2018 IRR", "for a bank",
# "the Insurance Commission's rules") is about that source: it gets extra candidates from
# those documents and a fixed bonus in the reranker's score (SCOPE_BONUS, set on dev).
_I = re.I
SCOPES = [  # (pattern, documents); acronyms match case-sensitively so "Sec. 2" is not the SEC
    (re.compile(r"\b2018 IRR\b|\bIRR of the AMLA\b"), ("irr2018", "irr2018_orig")),
    (re.compile(r"\bGoTRACS\b"), ("gotracs2024",)),
    (re.compile(r"\bRRG\b|registration and reporting guidelines", _I), ("rrg2021",)),
    (re.compile(r"\bTFPSA\b|terrorism financing prevention and suppression act", _I), ("tf_irr",)),
    (re.compile(r"\bsanctions guidelines\b", _I), ("sanctions2021",)),
    (re.compile(r"\bBO [Gg]uidelines\b|beneficial ownership guidelines", _I), ("bo2018",)),
    (re.compile(r"\bscreening guidance\b", _I), ("screening2023",)),
    (re.compile(r"administrative sanctions rules", _I), ("admin_sanctions2017",)),
    (re.compile(r"\bDNFBPs?\b|[Dd]esignated non-financial"), ("dnfbp2021",)),
    (re.compile(r"\bBSP\b|Bangko Sentral|\bMORB\b|\b[Bb]anks?\b(?! (inquiry|deposits?|accounts?|secrecy))"),
     ("bsp_morb_p9",)),
    (re.compile(r"\bSEC\b|Securities and Exchange Commission|\bsecurities (broker|dealer|firm)", 0), ("sec_mc16_2018", "sec_mc4_2021")),
    (re.compile(r"Insurance Commission|\binsurers?\b|insurance compan", _I), ("ic_cl2018_48", "ic_cl2019_65", "ic_cl2020_113",
                                                                          "ic_cl2022_27", "ic_cl2024_16")),
]
SCOPE_BONUS = 2.0  # dev (121 questions): recall@3 0.851 -> 0.884, MRR 0.769 -> 0.804; flat from 2 to 5
SCOPE_CANDIDATES = 10


def scope(query: str) -> tuple[str, ...]:
    """Documents the question names, directly or through their regulator."""
    return tuple(d for pattern, docs in SCOPES if pattern.search(query) for d in docs)


def rerank(query: str, chunks: list[Chunk], favour: tuple[str, ...] = (), bonus: float = 0.0) -> list[Chunk]:
    if not chunks:
        return chunks
    scores = reranker().predict([(query, c.embed_text) for c in chunks], show_progress_bar=False)
    scores = [s + (bonus if c.doc_id in favour else 0.0) for s, c in zip(scores, chunks)]
    return [c for _, c in sorted(zip(scores, chunks), key=lambda sc: -sc[0])]


def retrieve(query: str, k: int = 6, mode: str = "hybrid_rerank", strategy: str = "structured",
             as_of: str | None = None, bonus: float | None = None) -> list[Chunk]:
    """Top-k chunks for `query` among provisions in force on `as_of` (YYYY-MM-DD, default today)."""
    idx = get_index(strategy)
    bonus = SCOPE_BONUS if bonus is None else bonus
    if mode == "bm25":
        ids = idx.bm25_search(query, k, as_of)
    elif mode == "vector":
        ids = idx.vector_search(query, k, as_of)
    elif mode in ("hybrid", "hybrid_rerank"):
        fused = rrf([idx.bm25_search(query, CANDIDATES, as_of), idx.vector_search(query, CANDIDATES, as_of)])
        ids = [doc_id for doc_id, _ in fused][:CANDIDATES]
        if mode == "hybrid":
            ids = ids[:k]
        else:
            named = scope(query) if bonus else ()
            if named:  # candidates from the documents the question names
                extra = rrf([idx.bm25_search(query, SCOPE_CANDIDATES, as_of, named),
                             idx.vector_search(query, SCOPE_CANDIDATES, as_of, named)])
                ids += [i for i, _ in extra if i not in ids][:SCOPE_CANDIDATES]
            ranked = rerank(query, [idx.chunks[i] for i in ids], named, bonus)
            return with_replacements(ranked[:k], ranked, query, as_of or today(), strategy)
    else:
        raise ValueError(f"unknown mode {mode!r}; choose from {MODES}")
    return [idx.chunks[i] for i in ids]


def with_replacements(top: list[Chunk], pool: list[Chunk], query: str, as_of: str,
                      strategy: str) -> list[Chunk]:
    """Never show a transitional provision without the issuance replacing it.

    When a repealed-but-still-in-force provision (the 2021 RRG under GoTRACS) makes
    the cut and nothing from its replacement does, the replacement's best-ranked
    candidate is placed right after it, displacing the lowest-ranked chunk.
    """
    out = list(top)
    for c in top:
        if status(c, as_of) != "transitional" or not c.superseded_by:
            continue
        repl_doc = c.superseded_by.split(":")[0]
        if any(x.doc_id == repl_doc for x in out):
            continue
        best = next((x for x in pool if x.doc_id == repl_doc), None)
        if best is None:  # not in the candidate pool: search the replacing document alone
            idx = get_index(strategy)
            ids = [i for i in idx.vector_search(query, CANDIDATES, as_of) if idx.chunks[i].doc_id == repl_doc]
            best = rerank(query, [idx.chunks[i] for i in ids])[0] if ids else None
        if best is not None:
            out.insert(out.index(c) + 1, best)
            out = out[:len(top)]
    return out
