#!/usr/bin/env python3
"""Idempotently migrate meastlib item metadata to schema v3."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def upgrade(metadata: dict) -> dict:
    value = dict(metadata)
    value["schema_version"] = 3
    value.setdefault("rights_basis", "")
    value.setdefault("rights_reviewed_at", "")
    value.setdefault("rights_reviewed_by", "")
    value.setdefault("date_display", value.get("date_published", ""))
    value.setdefault("cover_page", 1)
    value["public"] = bool(
        value.get("rights") == "public-domain"
        and value.get("rights_basis")
        and value.get("rights_reviewed_at")
    )
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("items", type=Path, nargs="?", default=Path("data/items"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    changed = 0
    for path in sorted(args.items.glob("*/metadata.json")):
        original = json.loads(path.read_text(encoding="utf-8"))
        migrated = upgrade(original)
        if migrated == original:
            continue
        changed += 1
        print(f"{'Would migrate' if args.dry_run else 'Migrating'} {path.parent.name}")
        if not args.dry_run:
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
    print(f"{changed} item(s) {'need' if args.dry_run else 'received'} metadata v3 updates")


if __name__ == "__main__":
    main()
