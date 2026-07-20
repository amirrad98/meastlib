#!/usr/bin/env python3
"""Index an item's OCR into Solr with solr-ocrhighlighting.

One Solr document per page. The ocr_text field stores a pointer to the ALTO
file on disk (ExternalUtf8ContentFilter), so Solr can return word coordinates
for highlighting without bloating the index.

Note: the ALTO path stored must be readable by the Solr *container* — the
data/ dir is mounted at /data in docker-compose.yml.

Usage:
    python pipeline/index.py data/items/my-book [--solr http://localhost:8983/solr/meastlib]
"""
import argparse
import json
from pathlib import Path

import requests


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("item", type=Path)
    ap.add_argument("--solr", default="http://localhost:8983/solr/meastlib")
    args = ap.parse_args()

    meta = json.loads((args.item / "metadata.json").read_text(encoding="utf-8"))
    if not meta.get("public", False):
        print(f"NOTE: {meta['id']} is not marked public (rights: {meta.get('rights')}). "
              "Indexing anyway for local use — do not expose this Solr publicly.")

    item_id = meta["id"]
    docs = []
    for alto in sorted((args.item / "ocr").glob("page-*.alto.xml")):
        page = alto.name.replace(".alto.xml", "")
        container_path = f"/data/items/{item_id}/ocr/{alto.name}"
        docs.append({
            "id": f"{item_id}/{page}",
            "item_id": item_id,
            "page": page,
            "title": meta.get("title", ""),
            "creator": meta.get("creator", ""),
            "date_published": meta.get("date_published", ""),
            "language": meta.get("language", ""),
            "type": meta.get("type", ""),
            "public": meta.get("public", False),
            "ocr_text": container_path,
        })

    if not docs:
        raise SystemExit(f"No ALTO files in {args.item}/ocr — run ocr.py first.")

    r = requests.post(f"{args.solr}/update?commit=true", json=docs, timeout=120)
    if not r.ok:
        raise SystemExit(f"Solr indexing failed ({r.status_code}): {r.text}")
    print(f"Indexed {len(docs)} pages of {item_id} into {args.solr}")
    print(f'Try: {args.solr}/select?q=ocr_text:YOUR_QUERY&hl=on&hl.ocr.fl=ocr_text')


if __name__ == "__main__":
    main()
