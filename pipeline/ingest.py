#!/usr/bin/env python3
"""Ingest a PDF or a folder of page images into the meastlib item layout.

- Copies originals verbatim (immutable) and records SHA-256 checksums.
- Renders/exports web-access JPEGs, one per page.
- Writes metadata.json skeleton.

Usage:
    python pipeline/ingest.py book.pdf --id my-book --title "..." --lang ara --type book
    python pipeline/ingest.py scans_folder/ --id my-newspaper-1923-05-01 --type newspaper
"""
import argparse
import hashlib
import json
import shutil
import sys
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "items"
IMAGE_EXTS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".jp2"}
ACCESS_MAX_DIM = 2400  # px, long edge of access JPEGs
ACCESS_QUALITY = 88


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ingest_pdf(src: Path, item: Path) -> int:
    import fitz  # pymupdf

    doc = fitz.open(src)
    access = item / "access"
    access.mkdir(parents=True, exist_ok=True)
    for i, page in enumerate(doc, start=1):
        # ~300 DPI equivalent render, capped
        zoom = min(300 / 72, ACCESS_MAX_DIM / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        pix.save(access / f"page-{i:04d}.jpg", jpg_quality=ACCESS_QUALITY)
    n = doc.page_count
    doc.close()
    return n


def ingest_images(src: Path, item: Path) -> int:
    from PIL import Image

    access = item / "access"
    access.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    if not files:
        sys.exit(f"No images found in {src}")
    for i, f in enumerate(files, start=1):
        with Image.open(f) as im:
            im = im.convert("RGB")
            im.thumbnail((ACCESS_MAX_DIM, ACCESS_MAX_DIM))
            im.save(access / f"page-{i:04d}.jpg", quality=ACCESS_QUALITY)
    return len(files)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("--id", required=True, help="item identifier (url-safe, permanent)")
    ap.add_argument("--title", default="")
    ap.add_argument("--creator", default="")
    ap.add_argument("--date", dest="pub_date", default="")
    ap.add_argument("--lang", default="ara", help="ISO 639-3: ara, fas, ota, ...")
    ap.add_argument("--type", default="book", choices=["book", "newspaper", "document"])
    ap.add_argument("--source-note", default="", help="where this file came from")
    ap.add_argument("--rights", default="unknown", choices=["public-domain", "unknown", "in-copyright"])
    args = ap.parse_args()

    item = DATA_DIR / args.id
    if item.exists():
        sys.exit(f"Item {args.id} already exists — originals are immutable. Use a new id for a new version.")

    originals = item / "originals"
    originals.mkdir(parents=True)

    src = args.source.resolve()
    if src.is_file():
        dest = originals / src.name
        shutil.copy2(src, dest)
        checksums = {src.name: sha256(dest)}
        pages = ingest_pdf(dest, item) if src.suffix.lower() == ".pdf" else None
        if pages is None:
            sys.exit("Single-file ingest supports PDFs; for images pass the folder.")
    else:
        checksums = {}
        for f in sorted(p for p in src.iterdir() if p.suffix.lower() in IMAGE_EXTS):
            dest = originals / f.name
            shutil.copy2(f, dest)
            checksums[f.name] = sha256(dest)
        pages = ingest_images(src, item)

    (originals / "checksums.sha256").write_text(
        "".join(f"{v}  {k}\n" for k, v in checksums.items()), encoding="utf-8"
    )

    meta = {
        "id": args.id,
        "title": args.title,
        "title_original_script": "",
        "creator": args.creator,
        "date_published": args.pub_date,
        "language": args.lang,
        "script": "Arab",
        "type": args.type,
        "source": args.source_note,
        "rights": args.rights,
        "public": args.rights == "public-domain",
        "pages": pages,
        "ingested": date.today().isoformat(),
        "notes": "",
    }
    (item / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ingested {args.id}: {pages} pages -> {item}")
    print("Next: python pipeline/ocr.py", item)


if __name__ == "__main__":
    main()
