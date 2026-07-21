#!/usr/bin/env python3
"""Verify original, OCR, and derivative checksums for one item or a library."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, expected: str, root: Path, failures: list[dict]) -> None:
    if not path.is_file():
        failures.append({"file": path.relative_to(root).as_posix(), "error": "missing"})
        return
    actual = sha256(path)
    if actual != expected:
        failures.append({"file": path.relative_to(root).as_posix(), "error": "checksum", "expected": expected, "actual": actual})


def audit_item(item: Path) -> dict:
    failures: list[dict] = []
    checksums = item / "originals/checksums.sha256"
    if checksums.exists():
        for line in checksums.read_text(encoding="utf-8").splitlines():
            if "  " in line:
                expected, name = line.split("  ", 1)
                verify(item / "originals" / name, expected, item, failures)
    else:
        failures.append({"file": "originals/checksums.sha256", "error": "missing"})

    provenance_path = item / "ocr/provenance.json"
    if provenance_path.exists():
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        for record in provenance.get("pages", {}).values():
            for output in record.get("outputs", {}).values():
                if output.get("file") and output.get("sha256"):
                    verify(item / output["file"], output["sha256"], item, failures)
    derivative_path = item / "derivatives/provenance.json"
    if derivative_path.exists():
        derivative = json.loads(derivative_path.read_text(encoding="utf-8"))
        if derivative.get("file") and derivative.get("sha256"):
            verify(item / derivative["file"], derivative["sha256"], item, failures)
    return {"item_id": item.name, "ok": not failures, "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=Path("data/items"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    items = [args.path] if (args.path / "metadata.json").exists() else sorted(path for path in args.path.iterdir() if path.is_dir() and not path.name.startswith("."))
    report = {"ok": True, "items": [audit_item(item) for item in items]}
    report["ok"] = all(item["ok"] for item in report["items"])
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.json.with_suffix(args.json.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(args.json)
    print(payload)
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
