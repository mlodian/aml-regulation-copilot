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
        text VARCHAR, issuer VARCHAR, effective_from VARCHAR, effective_to VARCHAR,
        transitional_from VARCHAR, superseded_by VARCHAR, embedding FLOAT[{EMBED_DIM}])""")
    con.executemany(f"INSERT INTO chunks VALUES ({', '.join(['?'] * 15)})",
                    [[*asdict(c).values(), v.tolist()] for c, v in zip(chunks, vectors)])
    con.close()
    return len(chunks)


class Index:
    """Read-side handle: vector search, BM25 search and chunk lookup."""

    def __init__(self, strategy: str = "structured"):
        self.strategy = strategy
        self.con = duckdb.connect(str(db_path(strategy)), read_only=True)
        rows = self.con.execute("SELECT chunk_id, doc_id, doc_short, section_id, citation, heading, "
                                "page_start, page_end, text, issuer, effective_from, effective_to, "
                                "transitional_from, superseded_by FROM chunks ORDER BY chunk_id").fetchall()
        self.chunks = {r[0]: Chunk(*r) for r in rows}
        self._ids = list(self.chunks)
        self._bm25 = BM25Okapi([tokenize(self.chunks[i].embed_text) for i in self._ids])

    # Filtering happens before ranking: text not in force on `as_of` is never a candidate,
    # so it cannot crowd out the current provision or reach the prompt.
    IN_FORCE = "COALESCE(effective_from, '') <= ? AND (effective_to IS NULL OR effective_to > ?)"

    def vector_search(self, query: str, k: int = 20, as_of: str | None = None,
                      docs: tuple[str, ...] | None = None) -> list[str]:
        """Nearest chunks in force on `as_of`, optionally only from the documents `docs`."""
        q = embedder().encode(QUERY_PREFIX + query, normalize_embeddings=True).tolist()
        as_of = as_of or today()
        only = f" AND doc_id IN ({', '.join('?' * len(docs))})" if docs else ""
        rows = self.con.execute(
            f"SELECT chunk_id FROM chunks WHERE {self.IN_FORCE}{only} "
            f"ORDER BY array_cosine_similarity(embedding, ?::FLOAT[{EMBED_DIM}]) DESC LIMIT ?",
            [as_of, as_of, *(docs or ()), q, k]).fetchall()
        return [r[0] for r in rows]

    def bm25_search(self, query: str, k: int = 20, as_of: str | None = None,
                    docs: tuple[str, ...] | None = None) -> list[str]:
        scores = self._bm25.get_scores(tokenize(query))
        allowed = self.in_force_mask(as_of or today())
        keep = (lambda i: allowed[i] and self.chunks[self._ids[i]].doc_id in docs) if docs else (lambda i: allowed[i])
        order = sorted((i for i in range(len(scores)) if keep(i)), key=lambda i: -scores[i])[:k]
        return [self._ids[i] for i in order if scores[i] > 0]

    @lru_cache(maxsize=16)
    def in_force_mask(self, as_of: str) -> tuple[bool, ...]:
        from ingest.versions import in_force
        return tuple(in_force(self.chunks[i], as_of) for i in self._ids)


def today() -> str:
    import datetime as dt
    return dt.date.today().isoformat()


if __name__ == "__main__":
    for strategy in ("structured", "fixed"):
        print(f"{strategy}: indexed {build(strategy)} chunks")
