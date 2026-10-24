"""Effective-date versioning of provisions.

Every chunk gets the window in which its text was in force:

    effective_from <= date < effective_to      (effective_to empty = still in force)

plus `transitional_from` when a newer issuance has repealed it but keeps it in force
during a transition (the 2021 RRG under GoTRACS), and `superseded_by` naming what
replaced it. Retrieval filters on these dates before ranking (index/store.py), so
superseded wording never reaches the prompt for a question about today, and a
question "as of" an earlier date gets the wording in force then.

Sources of the dates, in order:
1. The manifest gives each document its window and status.
2. The 2018 IRR exists in two editions. Each provision of the 2018 issue is compared
   with the January 2021 consolidation: identical text (including renumbered
   provisions) is indexed once; changed text is kept as a superseded version,
   closed on the date of the amendment issuance (ARI 2020 or ARI 2021) that cites it.
   "Identical" means the same words in the same order once case, punctuation and
   quote marks are ignored. A similarity ratio is not enough: one changed word in a
   long section ("five (5) working days" -> "three working days") still scores
   above 99, and calling that identical would serve the new deadline for dates
   before the amendment. A false "changed" only keeps one redundant old version.
3. Amending circulars that replace whole sections (IC CL 2019-65 for CL 2018-48,
   SEC MC 4 for MC 16) close the sections they name.
4. OVERRIDES: conflicts no issuance resolves explicitly, each with its reason.
"""
from __future__ import annotations

import datetime as dt
import re
from collections import OrderedDict, defaultdict
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

def words(text: str) -> str:
    """Comparison key: lower-case words and numbers only."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


# Provision-level conflicts that no issuance resolves explicitly.
OVERRIDES = [
    {
        "section_id": "tf_irr:rule17:s17.b",
        "effective_to": "2020-01-29",
        "superseded_by": "irr2018:rule22:sec2",
        "note": "The TFPSA IRR (2012) gives five working days to report a suspicious transaction. "
                "ARI No. 1, s. 2020 amended Rule 22, Sec. 2.2 of the 2018 IRR to require filing "
                "within the next working day; the later rule governs.",
    },
]


def iso(value) -> str | None:
    return value.isoformat() if isinstance(value, (dt.date, dt.datetime)) else value


def apply(chunks: list, docs: list[dict], structured: bool = True) -> list:
    """Stamp every chunk with its in-force window; returns the chunks to index."""
    by_id = {d["id"]: d for d in docs}
    for c in chunks:
        d = by_id[c.doc_id]
        c.issuer = d["issuer"]
        c.effective_from = iso(d.get("effective_from"))
        c.effective_to = iso(d.get("effective_to"))
        c.transitional_from = iso(d.get("transitional_from"))
        c.superseded_by = d.get("superseded_by") if d.get("status") == "transitional" else None
    if not structured:  # fixed windows have no provision addresses: document-level dates only
        for c in chunks:
            if c.doc_id == "irr2018_orig":
                c.effective_to = iso(by_id["irr2018"]["issued"])
        return chunks
    chunks = _irr_editions(chunks, by_id)
    _section_amendments(chunks, by_id, "ic_cl2019_65", "ic_cl2018_48",
                        re.compile(r"^Section (\d+) of CL No\. 2018-48"), lambda n: rf":sec{n}(?::|$)")
    _section_amendments(chunks, by_id, "sec_mc4_2021", "sec_mc16_2018",
                        re.compile(r"^Section (\d+\.\d+)\. of the 2018 AML/CFT Guidelines is amended"),
                        lambda n: rf":sec{re.escape(n)}(?::|$)")
    by_section = defaultdict(list)
    for c in chunks:
        by_section[c.section_id].append(c)
    for o in OVERRIDES:
        for c in by_section.get(o["section_id"], []):
            c.effective_to = o["effective_to"]
            c.superseded_by = o["superseded_by"]
    return chunks


# --- 2018 IRR: first issue vs January 2021 consolidation -------------------------

# "Section 2.2 of Rule 22", "Section 1, Rule 6", "Section 5.2 on Manual Monitoring of Rule 22",
# or a whole rule: "Rule 10 of the 2018 IRR is hereby amended". The connector before "Rule"
# is required, so an issuance's own heading ("Section 7. Rule 10 of ...") is not misread.
ARI_TARGET = re.compile(
    r"(?:Paragraph \(?\w+\)?,?\s*(?:of\s+)?)?(?:Section|Sec\.) (\d+)[\d.]*(?:\s*\([a-z]\))?"
    r"(?:,\s*|\s+of\s+|\s+on\s+[^.]{1,60}?\s+of\s+)Rule\s+([IVX]+|\d+)"
    r"|\bRule (\d+) of the 2018 IRR is hereby amended")
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}


def ari_targets(doc_id: str) -> set[tuple[str, str | None]]:
    """(rule, top-level section) pairs an amendment issuance says it amends or inserts."""
    text = re.sub(r"\s+", " ", " ".join(p.get_text() for p in pymupdf.open(RAW / f"{doc_id}.pdf")))
    targets: set[tuple[str, str | None]] = set()
    for m in ARI_TARGET.finditer(text):
        end = text.find(". ", m.end())
        clause = text[m.end(): end if end != -1 else m.end() + 160]  # this clause only
        if "renumbered" in clause and "amended" not in clause:
            continue  # renumbering moves text without changing it
        if m.group(3):
            targets.add((m.group(3), None))
        else:
            rule = m.group(2)
            targets.add((str(ROMAN.get(rule, rule)), m.group(1)))
    return targets


def _amended_on(section_id: str, dated_targets: list[tuple[str, set]]) -> str | None:
    parts = section_id.split(":")
    rule = parts[0].removeprefix("rule")
    sec = parts[1].removeprefix("sec") if len(parts) > 1 else None
    for date, targets in dated_targets:  # earliest first
        if (rule, None) in targets or (rule, sec) in targets:
            return date
    return None


def _irr_editions(chunks: list, by_id: dict) -> list:
    orig = [c for c in chunks if c.doc_id == "irr2018_orig"]
    if not orig:
        return chunks
    cons_date = iso(by_id["irr2018"]["issued"])
    dated_targets = sorted((iso(by_id[a]["issued"]), ari_targets(a))
                           for a in ("ari2020_irr", "ari2021_irr") if (RAW / f"{a}.pdf").exists())

    def sections(doc_id: str) -> OrderedDict:
        out: OrderedDict = OrderedDict()
        for c in chunks:
            if c.doc_id == doc_id:
                out.setdefault(c.section_id.split(":", 1)[1], []).append(c)
        return out

    def text(cs: list) -> str:
        return words(" ".join(c.text for c in cs))

    old, new = sections("irr2018_orig"), sections("irr2018")
    new_text = {k: text(v) for k, v in new.items()}
    drop: set[int] = set()
    matched_new: set[str] = set()
    for sid, cs in old.items():
        t = text(cs)
        if sid in new and t == new_text[sid]:
            drop.update(id(c) for c in cs)
            matched_new.add(sid)
            continue
        rule = sid.split(":")[0]
        same = next((k for k in new if k.split(":")[0] == rule and t == new_text[k]), None)
        if same:  # renumbered, text unchanged
            drop.update(id(c) for c in cs)
            matched_new.add(same)
            continue
        changed_on = _amended_on(sid, dated_targets) or cons_date
        successor = sid if sid in new else None
        for c in cs:
            c.effective_to = changed_on
            c.superseded_by = f"irr2018:{successor}" if successor else "irr2018"
        if successor:
            for c in new[successor]:
                c.effective_from = changed_on
            matched_new.add(successor)
    for sid, cs in new.items():  # provisions added by the amendments
        if sid not in matched_new and sid not in old:
            for c in cs:
                c.effective_from = _amended_on(sid, dated_targets) or cons_date
    return [c for c in chunks if id(c) not in drop]


# --- circulars that replace whole sections -----------------------------------------

def _section_amendments(chunks: list, by_id: dict, amending: str, amended: str,
                        target: re.Pattern, section_pattern) -> None:
    if amending not in by_id or amended not in by_id:
        return
    date = iso(by_id[amending]["issued"])
    for c in chunks:
        if c.doc_id != amending or not c.chunk_id.endswith("#0"):
            continue
        m = target.match(c.text)
        if not m:
            continue
        pat = re.compile(section_pattern(m.group(1)))
        for old in chunks:
            if old.doc_id == amended and pat.search(old.section_id) and old.effective_to is None:
                old.effective_to = date
                old.superseded_by = c.section_id


def in_force(chunk, as_of: str) -> bool:
    """True when the chunk's text applied on `as_of` (YYYY-MM-DD)."""
    return ((chunk.effective_from or "0000") <= as_of
            and (chunk.effective_to is None or as_of < chunk.effective_to))


def status(chunk, as_of: str) -> str:
    if chunk.effective_to and chunk.effective_to <= as_of:
        return "superseded"
    if chunk.transitional_from and chunk.transitional_from <= as_of:
        return "transitional"
    return "current"
