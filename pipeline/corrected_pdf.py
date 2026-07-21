#!/usr/bin/env python3
"""Regenerate a searchable PDF from immutable scans and corrected-or-original ALTO."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import fitz
from pypdf import PdfReader


FONT_CANDIDATES = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def alto_for(item: Path, page_number: int) -> tuple[Path, bool]:
    name = f"page-{page_number:04d}.alto.xml"
    corrected = item / "ocr" / "corrected" / name
    return (corrected, True) if corrected.is_file() else (item / "ocr" / name, False)


def add_alto_text(page: fitz.Page, alto: Path, font: Path) -> int:
    root = ET.parse(alto).getroot()
    alto_page = root.find(".//{*}Page")
    if alto_page is None:
        return 0
    source_width = max(float(alto_page.get("WIDTH", "0") or 0), 1)
    source_height = max(float(alto_page.get("HEIGHT", "0") or 0), 1)
    scale_x = page.rect.width / source_width
    scale_y = page.rect.height / source_height
    font_name = "MeastlibOCR"
    page.insert_font(fontname=font_name, fontfile=str(font))
    count = 0
    for word in root.findall(".//{*}String"):
        content = word.get("CONTENT", "").strip()
        if not content:
            continue
        x = float(word.get("HPOS", "0") or 0) * scale_x
        y = float(word.get("VPOS", "0") or 0) * scale_y
        height = max(float(word.get("HEIGHT", "0") or 0) * scale_y, 1)
        page.insert_text(
            fitz.Point(x, y + height * 0.82), content,
            fontname=font_name, fontsize=max(1, height * 0.78),
            render_mode=3, overlay=True,
        )
        count += 1
    return count


def regenerate(item: Path, font: Path | None = None) -> dict:
    originals = sorted((item / "originals").glob("*.pdf"))
    if len(originals) != 1:
        raise RuntimeError("Exactly one immutable original PDF is required")
    font = font or next((candidate for candidate in FONT_CANDIDATES if candidate.is_file()), None)
    if font is None:
        raise RuntimeError("A Unicode font is required to regenerate the corrected text layer")
    source_document = fitz.open(originals[0])
    document = fitz.open()
    corrected_pages = 0
    words = 0
    try:
        for index, source_page in enumerate(source_document, start=1):
            access_image = item / "access" / f"page-{index:04d}.jpg"
            if not access_image.is_file():
                raise RuntimeError(f"Missing access image for page {index}")
            page = document.new_page(width=source_page.rect.width, height=source_page.rect.height)
            page.insert_image(page.rect, filename=str(access_image), keep_proportion=False)
            alto, corrected = alto_for(item, index)
            if not alto.is_file():
                continue
            words += add_alto_text(page, alto, font)
            corrected_pages += int(corrected)
        derivatives = item / "derivatives"
        derivatives.mkdir(exist_ok=True)
        destination = derivatives / "searchable.pdf"
        temporary = derivatives / ".searchable.corrected.tmp.pdf"
        document.save(temporary, garbage=4, deflate=True)
    finally:
        document.close()
        source_document.close()
    if len(PdfReader(str(temporary)).pages) != len(PdfReader(str(originals[0])).pages):
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Corrected searchable PDF page-count verification failed")
    temporary.replace(destination)
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "method": "Corrected-or-original ALTO words embedded invisibly over access-image pages",
        "file": destination.relative_to(item).as_posix(),
        "sha256": sha256(destination),
        "pages": len(PdfReader(str(destination)).pages),
        "corrected_pages": corrected_pages,
        "words": words,
        "visual_source": "access/page-*.jpg",
    }
    (derivatives / "provenance.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", type=Path)
    args = parser.parse_args()
    print(json.dumps(regenerate(args.item.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
