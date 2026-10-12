"""Build and query the index: dense vectors in DuckDB, BM25 in memory.

The corpus is a few hundred chunks, so exact cosine search inside DuckDB
(`array_cosine_similarity`) is fast and avoids an approximate index.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import duckdb
from rank_bm25 import BM25Okapi

from ingest.chunk import Chunk, load

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "data" / "index"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "  # bge convention
STOPWORDS = set("""a an and are as at be by for from has have if in is it its of on or shall that the
their this to under which with within any all such other these those be been being""".split())


@lru_cache(maxsize=1)
def embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBED_MODEL)


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)*", text.lower()) if t not in STOPWORDS]


def db_path(strategy: str) -> Path:
    return INDEX_DIR / f"{strategy}.duckdb"


def build(strategy: str = "structured") -> int:
    chunks = load(strategy)
    vectors = embedder().encode([c.embed_text for c in chunks], normalize_embeddings=True,
                                batch_size=32, show_progress_bar=False)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path = db_path(strategy)
    path.unlink(missing_ok=True)
    con = duckdb.connect(str(path))
    con.execute(f"""CREATE TABLE chunks (chunk_id VARCHAR PRIMARY KEY, doc_id VARCHAR, doc_short VARCHAR,
        section_id VARCHAR, citation VARCHAR, heading VARCHAR, page_start INT, page_end INT,
        text VARCHAR, embedding FLOAT[{EMBED_DIM}])""")
    con.executemany("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [[*asdict(c).values(), v.tolist()] for c, v in zip(chunks, vectors)])
    con.close()
    return len(chunks)


class Index:
    """Read-side handle: vector search, BM25 search and chunk lookup."""

    def __init__(self, strategy: str = "structured"):
        self.strategy = strategy
        self.con = duckdb.connect(str(db_path(strategy)), read_only=True)
        rows = self.con.execute("SELECT chunk_id, doc_id, doc_short, section_id, citation, heading, "
                                "page_start, page_end, text FROM chunks ORDER BY chunk_id").fetchall()
        self.chunks = {r[0]: Chunk(*r) for r in rows}
        self._ids = list(self.chunks)
        self._bm25 = BM25Okapi([tokenize(self.chunks[i].embed_text) for i in self._ids])

    def vector_search(self, query: str, k: int = 20) -> list[str]:
        q = embedder().encode(QUERY_PREFIX + query, normalize_embeddings=True).tolist()
        rows = self.con.execute(
            f"SELECT chunk_id FROM chunks ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{EMBED_DIM}]) DESC LIMIT ?",
            [q, k]).fetchall()
        return [r[0] for r in rows]

    def bm25_search(self, query: str, k: int = 20) -> list[str]:
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: -scores[i])[:k]
        return [self._ids[i] for i in order if scores[i] > 0]


if __name__ == "__main__":
    for strategy in ("structured", "fixed"):
        print(f"{strategy}: indexed {build(strategy)} chunks")
