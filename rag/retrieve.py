"""Retrieval modes compared in the ablation: bm25, vector, hybrid, hybrid+rerank."""
from __future__ import annotations

from functools import lru_cache

from index.store import Index
from ingest.chunk import Chunk
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


def retrieve(query: str, k: int = 6, mode: str = "hybrid_rerank", strategy: str = "structured") -> list[Chunk]:
    idx = get_index(strategy)
    if mode == "bm25":
        ids = idx.bm25_search(query, k)
    elif mode == "vector":
        ids = idx.vector_search(query, k)
    elif mode in ("hybrid", "hybrid_rerank"):
        fused = rrf([idx.bm25_search(query, CANDIDATES), idx.vector_search(query, CANDIDATES)])
        ids = [doc_id for doc_id, _ in fused][:CANDIDATES]
        if mode == "hybrid":
            ids = ids[:k]
        else:
            return rerank(query, [idx.chunks[i] for i in ids])[:k]
    else:
        raise ValueError(f"unknown mode {mode!r}; choose from {MODES}")
    return [idx.chunks[i] for i in ids]
