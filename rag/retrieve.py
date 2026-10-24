"""Retrieval modes compared in the ablation: bm25, vector, hybrid, hybrid+rerank."""
from __future__ import annotations

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


def rerank(query: str, chunks: list[Chunk]) -> list[Chunk]:
    if not chunks:
        return chunks
    scores = reranker().predict([(query, c.embed_text) for c in chunks], show_progress_bar=False)
    return [c for _, c in sorted(zip(scores, chunks), key=lambda sc: -sc[0])]


def retrieve(query: str, k: int = 6, mode: str = "hybrid_rerank", strategy: str = "structured",
             as_of: str | None = None) -> list[Chunk]:
    """Top-k chunks for `query` among provisions in force on `as_of` (YYYY-MM-DD, default today)."""
    idx = get_index(strategy)
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
            ranked = rerank(query, [idx.chunks[i] for i in ids])
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
