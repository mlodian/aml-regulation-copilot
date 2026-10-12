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


def load_manifest() -> list[dict]:
    return yaml.safe_load(MANIFEST.read_text())["documents"]


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
    resp = requests.get(doc["url"], headers={"User-Agent": USER_AGENT}, timeout=120)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise RuntimeError(f"{doc['id']}: response is not a PDF ({resp.headers.get('content-type')})")
    target.write_bytes(resp.content)
    return target


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    provenance = {}
    for doc in load_manifest():
        print(f"- {doc['id']}")
        path = fetch(doc)
        if path is None:
            continue
        provenance[doc["id"]] = {
            "title": doc["title"],
            "source": doc.get("url") or doc["manual"],
            "retrieved": dt.date.today().isoformat(),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
    (RAW / "provenance.json").write_text(json.dumps(provenance, indent=2))
    print(f"{len(provenance)} documents ready in {RAW.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
