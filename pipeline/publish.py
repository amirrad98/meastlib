#!/usr/bin/env python3
"""Atomically export reviewed public-domain derivatives to a public data tree."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

try:
    from pipeline.migrate_metadata import upgrade
except ImportError:  # direct script execution from pipeline/
    from migrate_metadata import upgrade


PUBLIC_DIRECTORIES = ("access", "ocr", "derivatives", "iiif")


def publishable(metadata: dict) -> bool:
    value = upgrade(metadata)
    return bool(value["public"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/items"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--portal-base", required=True)
    parser.add_argument("--solr", default="")
    args = parser.parse_args()
    source = args.items.resolve()
    output = args.output.resolve()
    if output == source or source in output.parents:
        raise SystemExit("Public output must be separate from the private item tree")
    staging = output.with_name(f".{output.name}-staging-{uuid.uuid4().hex[:8]}")
    backup = output.with_name(f".{output.name}-previous")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    published = []
    try:
        for item in sorted(path for path in source.iterdir() if path.is_dir() and not path.name.startswith(".")):
            metadata = json.loads((item / "metadata.json").read_text(encoding="utf-8"))
            if not publishable(metadata):
                continue
            destination = staging / item.name
            destination.mkdir()
            migrated = upgrade(metadata)
            (destination / "metadata.json").write_text(json.dumps(migrated, ensure_ascii=False, indent=2), encoding="utf-8")
            provenance = item / "metadata-provenance.json"
            if provenance.exists():
                shutil.copy2(provenance, destination / provenance.name)
            for directory in PUBLIC_DIRECTORIES:
                if (item / directory).exists():
                    shutil.copytree(item / directory, destination / directory, dirs_exist_ok=True)
            subprocess.run([
                sys.executable, str(Path(__file__).with_name("manifest.py")), str(destination),
                "--portal-base", args.portal_base,
            ], check=True)
            if args.solr:
                subprocess.run([
                    sys.executable, str(Path(__file__).with_name("index.py")), str(destination), "--solr", args.solr,
                ], check=True)
            published.append(item.name)
        report = {"portal_base": args.portal_base, "published": published, "count": len(published)}
        (staging / "publication.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(backup, ignore_errors=True)
        if output.exists():
            output.replace(backup)
        staging.replace(output)
        shutil.rmtree(backup, ignore_errors=True)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not output.exists():
            backup.replace(output)
        raise


if __name__ == "__main__":
    main()
