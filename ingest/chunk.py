"""Structure-aware chunking.

Legal text has an explicit hierarchy (Rule > Section > subsection). Chunking on
that hierarchy, instead of every N tokens, keeps each provision intact and gives
every chunk a citable address such as `2018 IRR, Rule 22, Sec. 2`. Each chunk is
also prefixed with its heading path so the embedding knows where it sits.

A fixed-size chunker is kept alongside for the chunking ablation in eval/.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from ingest.parse import Line, join_lines, read_lines

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

MAX_WORDS = 380      # a section longer than this is split on paragraph boundaries
OVERLAP_WORDS = 40   # carried into the next piece of a split section
FIXED_WORDS = 300    # fixed-size baseline


@dataclass
class Level:
    name: str            # label used in the citation ("Rule", "Sec.", "Part")
    pattern: re.Pattern  # group 1 = number, group 2 (optional) = title
    title_only: bool = False  # only a heading when group 2 reads like a title
    sentence_body: bool = False  # a non-title group 2 opens the body instead of being dropped
    sequential: bool = False  # letters must run a, b, c ... so roman "i." sub-items are not headings


# Per-document heading grammar. Order = hierarchy depth.
PROFILES: dict[str, dict] = {
    "irr2018": {
        "pages": (4, None),  # pages 1-3 are the table of contents
        "min_font": 11.5,    # body is 12pt; footnotes (superseded wording) are 10pt
        "levels": [
            Level("Rule", re.compile(r"^RULE (\d+[A-Z]?)(?:\s*[–-]\s*(.+))?$")),
            Level("Sec.", re.compile(r"^Section (\d+[A-Z]?)\.\s+(.{3,})$")),
            Level("", re.compile(r"^(\d+\.\d+(?:\.\d+)?)\.?\s+([A-Z].{2,90})$"), title_only=True),
        ],
    },
    "rrg2021": {
        "pages": (2, 17),    # Part 1 (policy); Parts 2-4 are portal and file-format manuals
        "min_font": 10.5,
        "levels": [
            Level("Part", re.compile(r"^([IVX]{1,4})\.\s+([A-Z].{2,80})$")),
            Level("", re.compile(r"^([A-H])\.\s+(.+)$"), sentence_body=True),
            # lettered items, e.g. each definition in Part II and each STR determination
            # period in Part IV-D, so no item is split across chunks
            Level("", re.compile(r"^([a-u])\.(?:\s+(.+))?$"), sentence_body=True, sequential=True),
        ],
    },
    "fatf": {
        "pages": (1, None),
        "min_font": 0.0,
        "levels": [Level("Rec.", re.compile(r"^(\d{1,2})\.\s+([A-Z][A-Za-z ,'()\-–]{3,80})\*?$"))],
    },
}

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with", "from"}


def looks_like_title(text: str) -> bool:
    """'Filing of CTRs and STRs.' is a heading; 'STRs shall be promptly filed ...' is not."""
    words = re.findall(r"[A-Za-z][\w/'-]*", text)
    if not words or len(words) > 12:
        return False
    return all(w[0].isupper() or w.lower() in SMALL_WORDS for w in words)


def clean_title(title: str) -> str:
    title = re.sub(r"(?<=[.)A-Za-z])\d{1,3}$", "", title.strip())  # footnote marker
    title = title.rstrip(" .")
    if title.isupper():
        title = " ".join(w.lower() if i and w.lower() in SMALL_WORDS else w.capitalize()
                         for i, w in enumerate(title.split()))
    return title


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_short: str
    section_id: str    # e.g. "irr2018:rule22:sec2" — what the golden set references
    citation: str      # e.g. "2018 IRR, Rule 22, Sec. 2"
    heading: str       # e.g. "Rule 22 – Transaction Reporting > Sec. 2 Suspicious Transaction Reports"
    page_start: int
    page_end: int
    text: str          # body text only

    @property
    def embed_text(self) -> str:
        return f"{self.citation} | {self.heading}\n{self.text}"


def _slug(level: Level, number: str) -> str:
    name = re.sub(r"[^a-z]", "", level.name.lower()) or "s"
    return f"{name}{number.lower()}"


def _split_words(text: str, max_words: int, overlap: int) -> list[str]:
    """Split on paragraph boundaries, falling back to word windows."""
    paras = [p for p in text.split("\n") if p.strip()]
    pieces: list[str] = []
    current: list[str] = []
    for para in paras:
        words = para.split()
        if len(words) > max_words:  # one huge paragraph: window it
            if current:
                pieces.append(" ".join(current))
                current = []
            step = max_words - overlap
            pieces += [" ".join(words[i:i + max_words]) for i in range(0, len(words), step)]
            continue
        if len(current) + len(words) > max_words and current:
            pieces.append(" ".join(current))
            current = current[-overlap:]
        current += words
        current.append("\n")
    if current and any(w != "\n" for w in current):
        pieces.append(" ".join(current))
    return [re.sub(r" ?\n ?", "\n", p).strip() for p in pieces if p.strip()]


def structured_chunks(doc: dict) -> list[Chunk]:
    profile = PROFILES[doc["id"]]
    first, last = profile["pages"]
    lines = read_lines(RAW / f"{doc['id']}.pdf", first, last, profile["min_font"])
    levels: list[Level] = profile["levels"]

    path: list[tuple[Level, str, str] | None] = [None] * len(levels)
    sections: list[tuple[list, list[Line]]] = []
    body: list[Line] = []

    def flush() -> None:
        if body:
            sections.append(([p for p in path if p], list(body)))
            body.clear()

    for i, line in enumerate(lines):
        for depth, level in enumerate(levels):
            m = level.pattern.match(line.text)
            if not m or (level.title_only and not looks_like_title(m.group(2))):
                continue
            if level.sequential:
                prev = path[depth][1] if path[depth] else None
                expected = "a" if prev is None else chr(ord(prev) + 1)
                if m.group(1) not in (expected, "a"):
                    continue
            flush()
            number = m.group(1)
            title = (m.group(2) or "").strip() if (m.lastindex or 0) >= 2 else ""
            if not title and i + 1 < len(lines):  # "RULE 6" with the title on the next line
                title = lines[i + 1].text if lines[i + 1].text.isupper() else ""
            if level.sentence_body and not looks_like_title(title.rstrip(".")):
                body_lead, title = title, ""  # "A. CPs shall report ..." is text, not a title
            else:
                body_lead = ""
            path[depth] = (level, number, clean_title(title))
            for deeper in range(depth + 1, len(levels)):
                path[deeper] = None
            rest = body_lead or line.text[m.end():].strip()
            if rest:  # AMLA puts the body on the heading line
                body.append(Line(line.page, rest))
            break
        else:
            body.append(line)
    flush()

    chunks: list[Chunk] = []
    seen: dict[str, int] = {}
    for headings, sec_lines in sections:
        if not headings:
            continue  # preamble before the first heading
        section_id = doc["id"] + ":" + ":".join(_slug(lv, n) for lv, n, _ in headings)
        if section_id in seen and seen[section_id] != id(headings[-1]):
            section_id += "b"  # the source numbers two provisions the same (IRR Rule 22 has two Sec. 7)
        seen.setdefault(section_id, id(headings[-1]))
        citation = ", ".join([doc["short"]] + [f"{lv.name} {n}".strip() for lv, n, _ in headings])
        heading = " > ".join(f"{lv.name} {n} {t}".strip() for lv, n, t in headings)
        text = join_lines([l.text for l in sec_lines])
        pages = [l.page for l in sec_lines]
        for k, piece in enumerate(_split_words(text, MAX_WORDS, OVERLAP_WORDS)):
            if len(piece.split()) < 8:
                continue
            chunks.append(Chunk(f"{section_id}#{k}", doc["id"], doc["short"], section_id, citation,
                                heading, min(pages), max(pages), piece))
    return chunks


def fixed_chunks(doc: dict) -> list[Chunk]:
    """Baseline: fixed word windows that ignore structure (for the ablation)."""
    profile = PROFILES[doc["id"]]
    first, last = profile["pages"]
    lines = read_lines(RAW / f"{doc['id']}.pdf", first, last, profile["min_font"])
    words: list[tuple[str, int]] = [(w, l.page) for l in lines for w in l.text.split()]
    step = FIXED_WORDS - OVERLAP_WORDS
    out = []
    for k, i in enumerate(range(0, len(words), step)):
        window = words[i:i + FIXED_WORDS]
        out.append(Chunk(f"{doc['id']}:fixed{k}", doc["id"], doc["short"], f"{doc['id']}:fixed{k}",
                         f"{doc['short']}, p. {window[0][1]}", "", window[0][1], window[-1][1],
                         " ".join(w for w, _ in window)))
    return out


def build(strategy: str = "structured") -> list[Chunk]:
    docs = yaml.safe_load((ROOT / "data" / "manifest.yaml").read_text())["documents"]
    fn = structured_chunks if strategy == "structured" else fixed_chunks
    chunks: list[Chunk] = []
    for doc in docs:
        if (RAW / f"{doc['id']}.pdf").exists() and doc["id"] in PROFILES:
            chunks += fn(doc)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    out = PROCESSED / f"chunks_{strategy}.jsonl"
    with out.open("w") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c)) + "\n")
    return chunks


def load(strategy: str = "structured") -> list[Chunk]:
    path = PROCESSED / f"chunks_{strategy}.jsonl"
    return [Chunk(**json.loads(l)) for l in path.read_text().splitlines()]


if __name__ == "__main__":
    for strategy in ("structured", "fixed"):
        cs = build(strategy)
        print(f"{strategy}: {len(cs)} chunks, {len({c.section_id for c in cs})} sections")
