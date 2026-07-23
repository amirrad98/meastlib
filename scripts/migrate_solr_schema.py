#!/usr/bin/env python3
"""Add meastlib catalog facet/sort fields to an existing Solr core and optionally reindex."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import requests


FIELDS = [
    {"name": "title_sort", "type": "string", "indexed": True, "stored": True},
    {"name": "creator_facet", "type": "string", "indexed": True, "stored": True},
    {"name": "publisher_facet", "type": "string", "indexed": True, "stored": True},
    {"name": "date_sort", "type": "string", "indexed": True, "stored": True},
    {"name": "date_year", "type": "pint", "indexed": True, "stored": True},
    {"name": "subjects_facet", "type": "string", "indexed": True, "stored": True, "multiValued": True},
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solr", default="http://localhost:8983/solr/meastlib")
    parser.add_argument("--items", type=Path, default=Path("data/items"))
    parser.add_argument("--reindex", action="store_true")
    args = parser.parse_args()
    known = requests.get(f"{args.solr}/schema/fields", params={"wt": "json"}, timeout=30)
    known.raise_for_status()
    names = {field["name"] for field in known.json().get("fields", [])}
    for field in FIELDS:
        if field["name"] in names:
            continue
        response = requests.post(f"{args.solr}/schema", json={"add-field": field}, timeout=30)
        if response.status_code == 400 and "schema is not editable" in response.text:
            raise SystemExit(
                "This core uses an immutable schema.xml. Recreate the Solr data volume to adopt the new "
                "configset, or continue without the optional creator/subject facets and title sort."
            )
        response.raise_for_status()
        print(f"Added {field['name']}")
    if args.reindex:
        indexer = Path(__file__).resolve().parent.parent / "pipeline/index.py"
        for item in sorted(path for path in args.items.iterdir() if (path / "metadata.json").exists()):
            subprocess.run([sys.executable, str(indexer), str(item), "--solr", args.solr], check=True)


if __name__ == "__main__":
    main()
