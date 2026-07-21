#!/usr/bin/env python3
"""Transactionally ingest a PDF or image folder into the meastlib layout."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import uuid
from datetime import date
from pathlib import Path
from typing import Any


DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "items"
IMAGE_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".jp2"}
ACCESS_MAX_DIM = 2400
ACCESS_QUALITY = 88


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def ingest_pdf(src: Path, item: Path) -> int:
    import fitz

    document = fitz.open(src)
    access = item / "access"
    access.mkdir(parents=True, exist_ok=True)
    try:
        for index, page in enumerate(document, start=1):
            zoom = min(300 / 72, ACCESS_MAX_DIM / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            output = access / f"page-{index:04d}.jpg"
            temporary = output.with_suffix(".tmp.jpg")
            pixmap.save(temporary, jpg_quality=ACCESS_QUALITY)
            temporary.replace(output)
        return document.page_count
    finally:
        document.close()


def ingest_images(src: Path, item: Path) -> int:
    from PIL import Image

    access = item / "access"
    access.mkdir(parents=True, exist_ok=True)
    files = sorted(path for path in src.iterdir() if path.suffix.lower() in IMAGE_EXTS)
    if not files:
        raise ValueError(f"No images found in {src}")
    for index, source in enumerate(files, start=1):
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((ACCESS_MAX_DIM, ACCESS_MAX_DIM))
            output = access / f"page-{index:04d}.jpg"
            temporary = output.with_suffix(".tmp.jpg")
            image.save(temporary, quality=ACCESS_QUALITY)
            temporary.replace(output)
    return len(files)


def default_metadata(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": 3,
        "id": args.id,
        "title": args.title,
        "title_original_script": "",
        "alternative_titles": [],
        "creator": args.creator,
        "creators": ([{"name": args.creator, "role": "author"}] if args.creator else []),
        "contributors": [],
        "publisher": "",
        "place_published": "",
        "date_published": args.pub_date,
        "date_display": args.pub_date,
        "date_calendar": "",
        "edition": "",
        "series_title": "",
        "collection_id": "",
        "volume_number": None,
        "volume_label": "",
        "issue_number": args.issue_number,
        "identifiers": [],
        "subjects": [],
        "temporal_coverage": [],
        "language": args.lang,
        "script": "Arab",
        "type": args.type,
        "source": args.source_note,
        "rights": args.rights,
        "rights_basis": "",
        "rights_reviewed_at": "",
        "rights_reviewed_by": "",
        "public": False,
        "cover_page": 1,
        "notes": "",
        "processing_status": "ingesting",
        "metadata_warnings": [],
    }


def apply_newspaper_fields(metadata: dict[str, Any], args: argparse.Namespace) -> None:
    if args.series_title:
        metadata["series_title"] = args.series_title
    if args.collection_id:
        metadata["collection_id"] = args.collection_id
    if args.issue_number:
        metadata["issue_number"] = args.issue_number


def load_metadata(args: argparse.Namespace) -> dict[str, Any]:
    if not args.metadata_file:
        metadata = default_metadata(args)
        apply_newspaper_fields(metadata, args)
        return metadata
    try:
        metadata = json.loads(args.metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read metadata file: {exc}") from exc
    metadata["id"] = args.id
    metadata["schema_version"] = 3
    metadata.setdefault("rights", "unknown")
    metadata.setdefault("rights_basis", "")
    metadata.setdefault("rights_reviewed_at", "")
    metadata.setdefault("rights_reviewed_by", "")
    metadata.setdefault("date_display", metadata.get("date_published", ""))
    metadata.setdefault("cover_page", 1)
    metadata.setdefault("issue_number", "")
    apply_newspaper_fields(metadata, args)
    metadata["public"] = bool(
        metadata.get("rights") == "public-domain"
        and metadata.get("rights_basis")
        and metadata.get("rights_reviewed_at")
    )
    return metadata


def ingest(args: argparse.Namespace) -> Path:
    destination = DATA_DIR / args.id
    if destination.exists():
        raise FileExistsError(
            f"Item {args.id} already exists - originals are immutable. Use a new id for a new version."
        )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for orphan in DATA_DIR.glob(f".staging-{args.id}-*"):
        shutil.rmtree(orphan, ignore_errors=True)
    staging = DATA_DIR / f".staging-{args.id}-{uuid.uuid4().hex[:8]}"
    originals = staging / "originals"
    originals.mkdir(parents=True)
    source = args.source.resolve()
    try:
        if source.is_file():
            if source.suffix.lower() != ".pdf":
                raise ValueError("Single-file ingest supports PDFs; pass a folder for page images.")
            original = originals / source.name
            shutil.copy2(source, original)
            checksums = {source.name: sha256(original)}
            pages = ingest_pdf(original, staging)
        elif source.is_dir():
            checksums: dict[str, str] = {}
            for image in sorted(path for path in source.iterdir() if path.suffix.lower() in IMAGE_EXTS):
                original = originals / image.name
                shutil.copy2(image, original)
                checksums[image.name] = sha256(original)
            pages = ingest_images(source, staging)
        else:
            raise FileNotFoundError(f"Source does not exist: {source}")

        if pages <= 0:
            raise ValueError(f"Source produced no readable pages: {source}")

        (originals / "checksums.sha256").write_text(
            "".join(f"{digest}  {name}\n" for name, digest in checksums.items()), encoding="utf-8"
        )
        metadata = load_metadata(args)
        metadata.update({
            "id": args.id,
            "pages": pages,
            "ingested": date.today().isoformat(),
            "processing_status": "ingested",
        })
        source_file = metadata.setdefault("source_file", {})
        if source.is_file():
            source_file.update({
                "name": source.name,
                "mime_type": "application/pdf",
                "bytes": source.stat().st_size,
                "sha256": checksums[source.name],
            })
        atomic_json(staging / "metadata.json", metadata)
        staging.replace(destination)
        return destination
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--id", required=True, help="Permanent lowercase URL-safe item identifier")
    parser.add_argument("--metadata-file", type=Path, help="Rich metadata v2 JSON produced by analysis")
    parser.add_argument("--title", default="")
    parser.add_argument("--creator", default="")
    parser.add_argument("--date", dest="pub_date", default="")
    parser.add_argument("--lang", default="ara")
    parser.add_argument("--type", default="book", choices=["book", "newspaper", "document"])
    parser.add_argument("--series-title", default="", help="Publication or series title")
    parser.add_argument("--collection-id", default="", help="Stable identifier grouping related issues or volumes")
    parser.add_argument("--issue-number", default="", help="Printed newspaper issue number")
    parser.add_argument("--source-note", default="")
    parser.add_argument("--rights", default="unknown", choices=["public-domain", "unknown", "in-copyright"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        item = ingest(args)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
    pages = json.loads((item / "metadata.json").read_text(encoding="utf-8")).get("pages", 0)
    print(f"Ingested {args.id}: {pages} pages -> {item}", flush=True)
    print(f"Next: python pipeline/ocr.py {item}", flush=True)


if __name__ == "__main__":
    main()
