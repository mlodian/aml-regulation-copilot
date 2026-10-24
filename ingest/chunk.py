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

from ingest.parse import RUNIN, Line, join_lines, read_lines

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
    split: bool = False      # "Scope. – These Guidelines apply ..." -> title "Scope", body "These Guidelines ..."
    title_next: bool = False  # the title is the next line ("RULE 1" / "Title"), in any case
    child_of_prev: bool = False  # "5.4" is only a heading inside Section 5
    roman: bool = False      # numbers run i, ii, iii ... (checked like `sequential`)


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
        # numbered paragraphs ("2.2. STRs shall be filed ...") stay inside their Section;
        # Rules are numbered across the whole IRR, so citations do not need the Chapter
        "not_headings": [re.compile(r"^\d+\.\d+(?:\.\d+)*\.?(?:\s|$)"), re.compile(r"^CHAPTER [IVX]+$")],
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
    # --- Phase 2 -------------------------------------------------------------
    "tf_irr": {
        "pages": (1, None),
        "min_font": 0.0,
        "levels": [
            Level("Rule", re.compile(r"^RULE (\d+)$"), title_next=True),
            Level("", re.compile(r"^Rule\.?\s?(\d+\.[a-z])(?!\.\d)\.?\s+(.+)$"), split=True, child_of_prev=True),
            Level("", re.compile(r"^Rule\.?\s?(\d+\.[a-z]\.\d+)\.?\s+(.+)$"), split=True, child_of_prev=True),
        ],
    },
    "gotracs2024": {
        "pages": (3, 50),    # pages 1-2 are the table of contents; 51-200 are file-format annexes
        "min_font": 9.5,
        "levels": [
            Level("Ch.", re.compile(r"^CHAPTER ([IVX]+)$")),
            Level("Part", re.compile(r"^PART (\d+)\s*[–-]\s*(.+)$")),
            Level("Sec.", re.compile(r"^Section (\d+)\.\s+(.+)$"), split=True),
            Level("", re.compile(r"^(\d+\.\d+)\.?(?:\s+(.+))?$"), sentence_body=True, child_of_prev=True),
            # each STR determination period in 5.4(c)(3) is its own chunk, as in the 2021 RRG
            Level("", re.compile(r"^(i|ii|iii|iv|v|vi|vii|viii|ix|x)\.(?:\s+(.+))?$"), sentence_body=True, roman=True),
        ],
    },
    "dnfbp2021": {
        "pages": (1, None),
        "min_font": 11.0,    # body 12pt, footnotes 10pt
        "levels": [
            Level("Title", re.compile(r"^TITLE ([IVX]+)$")),
            Level("Sec.", re.compile(r"^Section (\d+)\.\s+(.+)$"), split=True),
            Level("", re.compile(r"^([a-z]{1,2})\.(?:\s+(.+))?$"), sentence_body=True, sequential=True),
        ],
        "not_headings": [re.compile(r"^\d+\.\d+(?:\.\d+)*\.?(?:\s|$)")],  # numbered paragraphs of Section 59
    },
    "sanctions2021": {
        "pages": (4, None),  # pages 1-3 are the cover and contents
        "min_font": 10.5,    # body 11-12pt, footnotes 10pt
        "levels": [  # question-and-answer numbering: "1.5 What is the AMLC's mandate ...?"
            Level("", re.compile(r"^(\d{1,2}\.\d{1,2})\.?\s+(.+)$")),
            Level("", re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{1,2})\.?\s+(.+)$"), child_of_prev=True),
        ],
        "not_headings": [re.compile(r"^SEC\. 11\. Authority to Freeze")],  # quoted from the TFPSA
    },
    "bo2018": {
        "pages": (1, None),
        "min_font": 12.0,    # body 13pt, footnotes 11pt
        "levels": [
            Level("Sec.", re.compile(r"^Section (\d+)\.\s+(.+)$"), split=True),
            Level("", re.compile(r"^([a-z])\.(?:\s+(.+))?$"), sentence_body=True, sequential=True),
        ],
    },
    "screening2023": {
        "pages": (1, None),
        "min_font": 10.5,
        "levels": [
            Level("Sec.", re.compile(r"^(\d)\.\s+([A-Z][A-Za-z &,'-]{2,60})$"), title_only=True),
            Level("", re.compile(r"^(\d\.\d)\s+(.+)$"), child_of_prev=True),
            Level("", re.compile(r"^(\d\.\d\.\d)\s*(.*)$"), sentence_body=True, child_of_prev=True),
        ],
    },
    "admin_sanctions2017": {
        "pages": (1, None),
        "min_font": 11.0,
        "levels": [
            Level("Rule", re.compile(r"^RULE ([IVX]+)$")),
            Level("Sec.", re.compile(r"^Section (\d+)\.\s+(.+)$"), split=True),
        ],
    },
    "sec_mc16_2018": {   # OCR; pages 1-2 are the circular that transmits the guidelines
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [
            Level("Ch.", re.compile(r"^CHAPTER (\d+)$")),
            Level("Sec.", re.compile(r"^Section (\d+\.[A-Z0-9]+(?:\.\d+)?)\.\s+(.+)$"), split=True),
        ],
        "not_headings": [re.compile(r"^\d+\.\d+(?:\.\d+)*\.?(?:\s|$)")],  # numbered lists inside a section ("1.2.1 Securities Brokers ...")
    },
    "sec_mc4_2021": {
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [Level("Sec.", re.compile(r"^SECTION (\d+)\.\s+(.+)$"), sentence_body=True)],
        "not_headings": [re.compile(r"^\d+\.\d+(?:\.\d+)*\.?(?:\s|$)")],  # quoted items of the MC 16 sections it amends
    },
    "ic_cl2018_48": {    # OCR
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [
            Level("Title", re.compile(r"^TITLE ([IVX]+)$")),
            Level("Sec.", re.compile(r"^Section (\d+)\.\s+(.+)$"), split=True),
            Level("", re.compile(r"^([A-Z])\.\s+(.+)$"), sentence_body=True, sequential=True),
            Level("", re.compile(r"^([a-z])\.(?:\s+(.+))?$"), sentence_body=True, sequential=True),
        ],
    },
    "ic_cl2019_65": {    # OCR; each SEC. replaces a section of CL 2018-48
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [
            Level("Sec.", re.compile(r"^(?:SECTION|SEC\.)\s+(\d+)\.\s+(.+)$"), sentence_body=True),
            Level("", re.compile(r"^([A-Z])\.\s+(.+)$"), sentence_body=True, sequential=True),
        ],
        "not_headings": [re.compile(r"^Section \d+\. ")],  # the new text of the CL 2018-48 sections it replaces
    },
    "ic_cl2024_16": {    # OCR
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [
            Level("Title", re.compile(r"^TITLE ([IVX]+)$")),
            Level("Stage", re.compile(r"^STAGE (\d+):\s*(.+)$")),
            Level("", re.compile(r"^([a-z])\.\s+(.+)$"), sentence_body=True, sequential=True),
        ],
    },
    "ic_cl2022_27": {    # OCR
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [Level("", re.compile(r"^([A-Z])\.\s+([A-Z][A-Z ,&/()-]{3,80})$"), sequential=True)],
    },
    "ic_cl2020_113": {   # OCR; a three-page letter with no internal headings
        "pages": (1, None),
        "min_font": 0.0,
        "preamble": True,
        "levels": [],
    },
    "bsp_morb_p9": {
        "pages": (2, None),  # page 1 is the table of contents
        "min_font": 8.0,     # body 9pt, footnotes and running footer 7pt
        "bold_runin": True,
        "levels": [
            Level("Sec.", re.compile(r"^(9\d\d) (.+)$")),
            # unnamed subsections: "Risk assessment. Consistent with risk-based approach, ..."
            Level("", re.compile(r"^§ ([^.]{3,120})\.(?:\s+(.*))?$"), sentence_body=True),
        ],
    },
    "fatf": {
        "pages": (1, None),
        "min_font": 0.0,
        "levels": [Level("Rec.", re.compile(r"^(\d{1,2})\.\s+([A-Z][A-Za-z ,'()\-–]{3,80})\*?$"))],
    },
}
PROFILES["irr2018_orig"] = PROFILES["irr2018"]  # same layout as the consolidated edition

ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii"]

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "in", "of", "on", "or", "the", "to", "with", "from"}

ACRONYMS = {"AML", "AMLA", "AMLC", "BSP", "CDD", "CFT", "CTF", "CTR", "CTRS", "IC", "ICRE", "ICRES", "IRA", "IRR",
             "KYC", "ML", "MTPP", "PEP", "PEPS", "PF", "SEC", "STR", "STRS", "TF", "TFS", "UN", "UNSC"}

TITLE_DASH = re.compile(r"\.?\s+[–—-]+\.?\s+|\.\s*[–—]\s*")  # "Scope. – ", "Scope – ", "Scope.–"


def split_title(text: str) -> tuple[str, str]:
    """Split 'Scope. – These Guidelines apply ...' into ('Scope', 'These Guidelines apply ...').

    Falls back to the first full stop when what precedes it reads like a title
    ('Risk Management. All ICREs shall ...'); otherwise the whole text is the title.
    """
    m = TITLE_DASH.search(text)
    if m and m.start() > 0:
        return text[:m.start()], text[m.end():]
    m = re.search(r"\.\s+(?=[A-Z])", text)
    if m and looks_like_title(text[:m.start()]):
        return text[:m.start()], text[m.end():]
    return text, ""


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
        def word(i: int, w: str) -> str:
            if w.strip("(),") in ACRONYMS or "/" in w:
                return w
            return w.lower() if i and w.lower() in SMALL_WORDS else w.capitalize()
        title = " ".join(word(i, w) for i, w in enumerate(title.split()))
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
    # versioning (ingest/versions.py): in force from effective_from until effective_to
    issuer: str = ""
    effective_from: str | None = None
    effective_to: str | None = None
    transitional_from: str | None = None  # repealed but kept in force during a transition
    superseded_by: str | None = None

    @property
    def title(self) -> str:
        """Name of the innermost provision without its number, e.g. 'Timing of Reporting'."""
        last = self.heading.split(" > ")[-1]
        return re.sub(r"^(?:(?:Rule|Sec\.|Part|Rec\.|Title|Ch\.|Stage)\s+)?[0-9A-Za-z.]+\s*", "", last, count=1)

    @property
    def label(self) -> str:
        """Display label: citation plus the provision's name when it has one."""
        return f"{self.citation} · {self.title}" if self.title else self.citation

    @property
    def embed_text(self) -> str:
        return f"{self.citation} | {self.heading}\n{self.text}"


def _slug(level: Level, number: str) -> str:
    name = re.sub(r"[^a-z]", "", level.name.lower()) or "s"
    return f"{name}{re.sub(r'[^a-z0-9.]', '', number.lower())[:40]}"


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


def parse_sections(doc: dict, trace: dict | None = None) -> list[tuple[list, list[Line]]]:
    """Walk the document's lines with its heading grammar.

    Returns (heading path, body lines) per section; the path is empty for text
    before the first heading. A `trace` dict, if given, receives the lines read
    and the indices of those consumed as headings (for ingest/coverage.py).
    """
    profile = PROFILES[doc["id"]]
    first, last = profile["pages"]
    lines = read_lines(RAW / f"{doc['id']}.pdf", first, last, profile["min_font"], ocr=doc.get("ocr", False),
                       bold_runin=profile.get("bold_runin", False))
    levels: list[Level] = profile["levels"]
    heads: set[int] = set()
    if trace is not None:
        trace.update(lines=lines, heads=heads)

    path: list[tuple[Level, str, str] | None] = [None] * len(levels)
    sections: list[tuple[list, list[Line]]] = []
    body: list[Line] = []
    skip: set[int] = set()  # title lines already consumed by the heading above them

    def flush() -> None:
        if body:
            sections.append(([p for p in path if p], list(body)))
            body.clear()

    for i, line in enumerate(lines):
        if i in skip:
            continue
        for depth, level in enumerate(levels):
            m = level.pattern.match(line.text)
            if not m or (level.title_only and not looks_like_title(m.group(2))):
                continue
            if level.sequential:
                prev = path[depth][1] if path[depth] else None
                expected = "a" if prev is None else chr(ord(prev.lower()) + 1)
                if m.group(1).lower() not in (expected, "a"):
                    continue
            if level.roman:
                prev = path[depth][1] if path[depth] else None
                expected = "i" if prev is None else ROMAN[ROMAN.index(prev) + 1]
                if m.group(1) not in (expected, "i"):
                    continue
            if level.child_of_prev:
                parent = next((p for p in reversed(path[:depth]) if p), None)
                if not parent or not m.group(1).startswith(parent[1] + "."):
                    continue
            flush()
            heads.add(i)
            number = m.group(1)
            title = (m.group(2) or "").strip() if (m.lastindex or 0) >= 2 else ""
            if not title and i + 1 < len(lines):  # "RULE 6" with the title on the next line
                nxt = lines[i + 1].text
                if level.title_next or nxt.isupper():
                    title = nxt
                    skip.add(i + 1)
            body_lead = ""
            if level.split and title:
                title, body_lead = split_title(title)
            elif level.sentence_body and not looks_like_title(title.rstrip(".")):
                body_lead, title = title, ""  # "A. CPs shall report ..." is text, not a title
            path[depth] = (level, number, clean_title(title))
            for deeper in range(depth + 1, len(levels)):
                path[deeper] = None
            rest = body_lead or line.text[m.end():].strip()
            if rest:  # AMLA puts the body on the heading line
                body.append(Line(line.page, rest))
            break
        else:
            body.append(Line(line.page, line.text.removeprefix(RUNIN)))
    flush()
    return sections


def structured_chunks(doc: dict) -> list[Chunk]:
    profile = PROFILES[doc["id"]]
    chunks: list[Chunk] = []
    seen: dict[str, int] = {}
    for headings, sec_lines in parse_sections(doc):
        if not headings and not profile.get("preamble"):
            continue  # preamble before the first heading
        section_id = doc["id"] + ":" + (":".join(_slug(lv, n) for lv, n, _ in headings) or "main")
        key = id(headings[-1]) if headings else 0
        base, suffix = section_id, "b"
        while section_id in seen and seen[section_id] != key:
            # the source numbers two provisions the same (IRR Rule 22 has two Sec. 7)
            section_id, suffix = base + suffix, chr(ord(suffix) + 1)
        seen.setdefault(section_id, key)
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
    lines = read_lines(RAW / f"{doc['id']}.pdf", first, last, profile["min_font"], ocr=doc.get("ocr", False),
                       bold_runin=profile.get("bold_runin", False))
    lines = [Line(l.page, l.text.removeprefix(RUNIN)) for l in lines]
    words: list[tuple[str, int]] = [(w, l.page) for l in lines for w in l.text.split()]
    step = FIXED_WORDS - OVERLAP_WORDS
    out = []
    for k, i in enumerate(range(0, len(words), step)):
        window = words[i:i + FIXED_WORDS]
        out.append(Chunk(f"{doc['id']}:fixed{k}", doc["id"], doc["short"], f"{doc['id']}:fixed{k}",
                         f"{doc['short']}, p. {window[0][1]}", "", window[0][1], window[-1][1],
                         " ".join(w for w, _ in window)))
    return out


def indexable_docs() -> list[dict]:
    """Manifest documents that are downloaded, have a heading grammar and are not index: false."""
    docs = yaml.safe_load((ROOT / "data" / "manifest.yaml").read_text())["documents"]
    return [d for d in docs
            if d.get("index", True) and (RAW / f"{d['id']}.pdf").exists() and d["id"] in PROFILES]


def build(strategy: str = "structured") -> list[Chunk]:
    from ingest import versions

    fn = structured_chunks if strategy == "structured" else fixed_chunks
    docs = yaml.safe_load((ROOT / "data" / "manifest.yaml").read_text())["documents"]
    chunks: list[Chunk] = []
    for doc in indexable_docs():
        chunks += fn(doc)
    chunks = versions.apply(chunks, docs, structured=strategy == "structured")
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
    from ingest import coverage

    for strategy in ("structured", "fixed"):
        cs = build(strategy)
        print(f"{strategy}: {len(cs)} chunks, {len({c.section_id for c in cs})} sections")
    print()
    rows = coverage.report(indexable_docs())
    (PROCESSED / "coverage.json").write_text(json.dumps(coverage.as_json(rows), indent=2))
    review = sorted(p.stem for p in (ROOT / "data" / "review").glob("*.json"))
    print(f"OCR review queue: {', '.join(review) if review else 'empty'}")
