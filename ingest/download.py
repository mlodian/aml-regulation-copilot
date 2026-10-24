"""Download the corpus listed in data/manifest.yaml and record provenance.

Each file is saved to data/raw/<id>.pdf and its URL, retrieval date and
SHA-256 are written to data/raw/provenance.json, so any answer can be traced
back to the exact bytes it was grounded on.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "manifest.yaml"
RAW = ROOT / "data" / "raw"
USER_AGENT = "Mozilla/5.0 (aml-regulation-copilot corpus builder)"

ISSUERS = {"AMLC", "BSP", "SEC", "IC", "FATF"}
STATUSES = {"current", "transitional", "superseded", "amendment"}
DATE_FIELDS = ("issued", "effective_from", "effective_to", "transitional_from")


def validate(docs: list[dict]) -> list[str]:
    """Schema problems in the manifest; an empty list means it is usable."""
    errors: list[str] = []
    ids = [d.get("id") for d in docs]
    known = set(ids)
    for d in docs:
        did = d.get("id", "?")
        for field in ("id", "title", "short", "issuer", "status"):
            if not d.get(field):
                errors.append(f"{did}: missing {field}")
        if ("url" in d) == ("manual" in d):
            errors.append(f"{did}: needs exactly one of url / manual")
        if d.get("issuer") not in ISSUERS:
            errors.append(f"{did}: unknown issuer {d.get('issuer')!r}")
        if d.get("status") not in STATUSES:
            errors.append(f"{did}: unknown status {d.get('status')!r}")
        for field in DATE_FIELDS:
            if field in d and not isinstance(d[field], dt.date):
                errors.append(f"{did}: {field} must be a YYYY-MM-DD date")
        if d.get("status") != "current" and d.get("status") != "amendment" and not d.get("superseded_by"):
            errors.append(f"{did}: a {d.get('status')} document needs superseded_by")
        if d.get("status") == "transitional" and "transitional_from" not in d:
            errors.append(f"{did}: a transitional document needs transitional_from")
        for ref in [d.get("superseded_by"), *d.get("supersedes", []), *d.get("amends", [])]:
            if ref and ref not in known:
                errors.append(f"{did}: refers to unknown document {ref!r}")
    if len(ids) != len(known):
        errors.append("duplicate document ids")
    return errors


def load_manifest() -> list[dict]:
    docs = yaml.safe_load(MANIFEST.read_text())["documents"]
    errors = validate(docs)
    if errors:
        raise ValueError("manifest problems:\n  " + "\n  ".join(errors))
    return docs


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(doc: dict) -> Path | None:
    target = RAW / f"{doc['id']}.pdf"
    if target.exists():
        return target
    if "manual" in doc:
        src = ROOT / doc["manual"]
        if src.exists():
            shutil.copyfile(src, target)
            return target
        level = "skip (optional)" if doc.get("optional") else "MISSING"
        print(f"  {level}: place {doc['id']} at {doc['manual']}")
        return None
    resp = requests.get(doc["url"], headers={"User-Agent": USER_AGENT}, timeout=900)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise RuntimeError(f"{doc['id']}: response is not a PDF ({resp.headers.get('content-type')})")
    target.write_bytes(resp.content)
    return target


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    prov_path = RAW / "provenance.json"
    previous = json.loads(prov_path.read_text()) if prov_path.exists() else {}
    provenance = {}
    for doc in load_manifest():
        print(f"- {doc['id']}")
        path = fetch(doc)
        if path is None:
            continue
        digest = sha256(path)
        old = previous.get(doc["id"], {})
        provenance[doc["id"]] = {
            "title": doc["title"],
            "issuer": doc["issuer"],
            "source": doc.get("url") or doc["manual"],
            # keep the first retrieval date while the bytes are unchanged
            "retrieved": old["retrieved"] if old.get("sha256") == digest else dt.date.today().isoformat(),
            "sha256": digest,
            "bytes": path.stat().st_size,
        }
    prov_path.write_text(json.dumps(provenance, indent=2))
    print(f"{len(provenance)} documents ready in {RAW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
