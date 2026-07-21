#!/usr/bin/env python3
"""Resumable per-page OCR with ALTO, text, confidence, and searchable PDF output."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from lxml import etree
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter, Transformation


CONFIDENCE_RETRY_THRESHOLD = 0.70
MIN_WORDS_FOR_CONFIDENCE = 5
BLANK_INK_RATIO = 0.0015


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def tesseract_version() -> str:
    result = subprocess.run(
        ["tesseract", "--version"], capture_output=True, text=True, timeout=10, check=True
    )
    return result.stdout.splitlines()[0]


def available_languages() -> set[str]:
    result = subprocess.run(
        ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10, check=True
    )
    return {line.strip() for line in result.stdout.splitlines()[1:] if line.strip()}


def validate_languages(requested: str) -> None:
    available = available_languages()
    missing = [language for language in requested.split("+") if language not in available]
    if missing:
        raise RuntimeError(
            f"Missing Tesseract language pack(s): {', '.join(missing)}. Available: {', '.join(sorted(available))}"
        )


def original_pdf(item: Path) -> Path | None:
    pdfs = sorted((item / "originals").glob("*.pdf"))
    return pdfs[0] if len(pdfs) == 1 else None


def source_checksum(item: Path, source_pdf: Path | None) -> str:
    metadata_path = item / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        value = metadata.get("source_file", {}).get("sha256")
        if value:
            return str(value)
    except (OSError, json.JSONDecodeError):
        pass
    if source_pdf:
        return file_sha256(source_pdf)
    digest = hashlib.sha256()
    for image in sorted((item / "access").glob("page-*.jpg")):
        digest.update(file_sha256(image).encode())
    return digest.hexdigest()


def page_signature(source_hash: str, page_number: int, languages: str, dpi: int, version: str) -> str:
    value = f"{source_hash}:{page_number}:{languages}:{dpi}:{version}:psm3+retry6:text-only-pdf:v2"
    return hashlib.sha256(value.encode()).hexdigest()


def render_page(source_pdf: Path | None, access_image: Path, page_number: int, output: Path, dpi: int) -> None:
    if source_pdf:
        document = fitz.open(source_pdf)
        try:
            page = document[page_number - 1]
            max_dimension = 4000
            scale = min(dpi / 72, max_dimension / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False
            )
            pixmap.save(output)
        finally:
            document.close()
        return
    with Image.open(access_image) as image:
        ImageOps.grayscale(image).save(output)


def image_ink_ratio(path: Path) -> float:
    with Image.open(path) as image:
        gray = ImageOps.grayscale(image)
        histogram = gray.histogram()
        dark = sum(histogram[:220])
        return dark / max(image.width * image.height, 1)


def alto_stats(path: Path) -> tuple[float | None, int]:
    tree = etree.parse(str(path))
    confidences: list[float] = []
    words = 0
    for element in tree.iter("{*}String"):
        words += 1
        value = element.get("WC")
        if value is not None:
            try:
                confidences.append(float(value))
            except ValueError:
                pass
    return (sum(confidences) / len(confidences) if confidences else None), words


def run_tesseract(image: Path, base: Path, languages: str, dpi: int, psm: int) -> dict[str, Any]:
    started = time.monotonic()
    result = subprocess.run(
        [
            "tesseract", str(image), str(base), "-l", languages,
            "--dpi", str(dpi), "--psm", str(psm), "-c", "textonly_pdf=1",
            "alto", "txt", "pdf",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"Tesseract exited with {result.returncode}")
    xml = base.with_suffix(".xml")
    text = base.with_suffix(".txt")
    pdf = base.with_suffix(".pdf")
    if not xml.exists() or not text.exists() or not pdf.exists():
        raise RuntimeError("Tesseract did not create every requested OCR output")
    confidence, words = alto_stats(xml)
    return {
        "base": base,
        "alto": xml,
        "text": text,
        "pdf": pdf,
        "confidence": confidence,
        "words": words,
        "psm": psm,
        "seconds": round(time.monotonic() - started, 3),
        "stderr": result.stderr.strip(),
    }


def output_paths(item: Path, page_stem: str) -> dict[str, Path]:
    ocr = item / "ocr"
    return {
        "alto": ocr / f"{page_stem}.alto.xml",
        "text": ocr / f"{page_stem}.txt",
        "pdf": ocr / "layers" / f"{page_stem}.text.pdf",
    }


def valid_existing_outputs(paths: dict[str, Path], record: dict[str, Any], signature: str) -> bool:
    return (
        record.get("signature") == signature
        and all(path.exists() and path.stat().st_size > 0 for path in paths.values())
    )


def process_page(
    item: Path,
    source_pdf: Path | None,
    access_image: Path,
    page_number: int,
    languages: str,
    dpi: int,
    signature: str,
) -> dict[str, Any]:
    page_stem = f"page-{page_number:04d}"
    final = output_paths(item, page_stem)
    for path in final.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    work_root = item / "ocr" / ".working"
    work_root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{page_stem}-", dir=work_root))
    rendered = work / f"{page_stem}.png"
    try:
        render_page(source_pdf, access_image, page_number, rendered, dpi)
        ink_ratio = image_ink_ratio(rendered)
        primary = run_tesseract(rendered, work / "primary", languages, dpi, 3)
        attempts = [{key: value for key, value in primary.items() if key not in {"base", "alto", "text", "pdf"}}]
        chosen = primary
        confidence = primary["confidence"]
        if (
            ink_ratio >= BLANK_INK_RATIO
            and primary["words"] >= MIN_WORDS_FOR_CONFIDENCE
            and (confidence is None or confidence < CONFIDENCE_RETRY_THRESHOLD)
        ):
            retry = run_tesseract(rendered, work / "retry", languages, dpi, 6)
            attempts.append({key: value for key, value in retry.items() if key not in {"base", "alto", "text", "pdf"}})
            if (retry["confidence"] or 0) > (primary["confidence"] or 0):
                chosen = retry
        for key, target in final.items():
            temporary = target.with_suffix(target.suffix + ".tmp")
            shutil.copy2(chosen[key], temporary)
            temporary.replace(target)
        return {
            "page": page_stem,
            "signature": signature,
            "status": "ok",
            "blank": ink_ratio < BLANK_INK_RATIO and chosen["words"] < MIN_WORDS_FOR_CONFIDENCE,
            "ink_ratio": round(ink_ratio, 6),
            "mean_confidence": (
                round(chosen["confidence"], 4) if chosen["confidence"] is not None else None
            ),
            "words": chosen["words"],
            "selected_psm": chosen["psm"],
            "attempts": attempts,
            "outputs": {
                key: {"file": path.relative_to(item).as_posix(), "sha256": file_sha256(path)}
                for key, path in final.items()
            },
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def merge_searchable_pdf(item: Path, source_pdf: Path, page_count: int) -> dict[str, Any]:
    source = PdfReader(str(source_pdf))
    if len(source.pages) != page_count:
        raise RuntimeError("Source PDF page count changed during OCR")
    writer = PdfWriter(clone_from=str(source_pdf))
    text_pages = 0
    for index, source_page in enumerate(writer.pages, start=1):
        layer_path = output_paths(item, f"page-{index:04d}")["pdf"]
        if layer_path.exists():
            layer = PdfReader(str(layer_path)).pages[0]
            source_width = float(source_page.mediabox.width)
            source_height = float(source_page.mediabox.height)
            layer_width = float(layer.mediabox.width)
            layer_height = float(layer.mediabox.height)
            if abs(source_width - layer_width) > 1 or abs(source_height - layer_height) > 1:
                transformation = Transformation().scale(
                    sx=source_width / max(layer_width, 1),
                    sy=source_height / max(layer_height, 1),
                )
                source_page.merge_transformed_page(layer, transformation, over=False, expand=False)
            else:
                source_page.merge_page(layer, over=False, expand=False)
            text_pages += 1
    derivatives = item / "derivatives"
    derivatives.mkdir(exist_ok=True)
    destination = derivatives / "searchable.pdf"
    temporary = derivatives / ".searchable.tmp.pdf"
    with temporary.open("wb") as output:
        writer.write(output)
    verified = PdfReader(str(temporary))
    if len(verified.pages) != page_count:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("Searchable PDF page-count verification failed")
    pages_with_extractable_text = sum(bool((page.extract_text() or "").strip()) for page in verified.pages)
    temporary.replace(destination)
    result = {
        "file": destination.relative_to(item).as_posix(),
        "sha256": file_sha256(destination),
        "bytes": destination.stat().st_size,
        "pages": page_count,
        "text_layer_pages": text_pages,
        "extractable_text_pages": pages_with_extractable_text,
        "visual_source": source_pdf.relative_to(item).as_posix(),
    }
    atomic_json(derivatives / "provenance.json", {
        "generated": datetime.now(timezone.utc).isoformat(),
        "method": "Tesseract text-only PDF layers merged beneath immutable original pages",
        **result,
    })
    return result


def update_item_metadata(item: Path, provenance: dict[str, Any], derivative: dict[str, Any] | None) -> None:
    metadata_path = item / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    pages = list(provenance.get("pages", {}).values())
    successful = [page for page in pages if page.get("status") == "ok"]
    confidences = [
        page["mean_confidence"] for page in successful
        if page.get("mean_confidence") is not None and not page.get("blank")
    ]
    metadata["ocr_confidence"] = round(sum(confidences) / len(confidences), 4) if confidences else None
    metadata["ocr_pages"] = len(successful)
    metadata["processing_status"] = "ocr_complete" if len(successful) == provenance["pages_total"] else "partial"
    metadata["searchable_pdf"] = derivative["file"] if derivative else ""
    atomic_json(metadata_path, metadata)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item", type=Path)
    parser.add_argument("--engine", default="tesseract", choices=["tesseract"])
    parser.add_argument("--langs", default="ara+fas")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--dpi", type=int, default=300)
    args = parser.parse_args()

    item = args.item.resolve()
    access = item / "access"
    pages = sorted(access.glob("page-*.jpg"))
    if not pages:
        sys.exit(f"No access images in {item}; run ingest.py first.")
    try:
        validate_languages(args.langs)
        version = tesseract_version()
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        sys.exit(str(exc))

    source_pdf = original_pdf(item)
    source_hash = source_checksum(item, source_pdf)
    provenance_path = item / "ocr" / "provenance.json"
    if provenance_path.exists():
        try:
            old = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}
    else:
        old = {}
    records: dict[str, Any] = dict(old.get("pages", {}))
    provenance: dict[str, Any] = {
        "schema_version": 2,
        "engine": "tesseract",
        "engine_version": version,
        "model": args.langs,
        "model_version": "system-traineddata",
        "date": datetime.now(timezone.utc).isoformat(),
        "language": args.langs,
        "script": "Arab",
        "dpi": args.dpi,
        "workers": max(1, args.workers),
        "source_sha256": source_hash,
        "pages_total": len(pages),
        "pages": records,
        "human_reviewed": False,
    }
    (item / "ocr").mkdir(exist_ok=True)
    working_root = item / "ocr" / ".working"
    if working_root.exists():
        for orphan in working_root.iterdir():
            if orphan.is_dir():
                shutil.rmtree(orphan, ignore_errors=True)

    pending: list[tuple[int, Path, str]] = []
    skipped = 0
    for index, access_page in enumerate(pages, start=1):
        stem = f"page-{index:04d}"
        signature = page_signature(source_hash, index, args.langs, args.dpi, version)
        if valid_existing_outputs(output_paths(item, stem), records.get(stem, {}), signature):
            skipped += 1
            print(f"PROGRESS {skipped}/{len(pages)} {stem} skipped", flush=True)
            continue
        pending.append((index, access_page, signature))

    failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers), thread_name_prefix="ocr-page") as executor:
        futures = {
            executor.submit(
                process_page, item, source_pdf, access_page, index, args.langs, args.dpi, signature
            ): index
            for index, access_page, signature in pending
        }
        completed = skipped
        for future in as_completed(futures):
            index = futures[future]
            stem = f"page-{index:04d}"
            try:
                record = future.result()
                records[stem] = record
                confidence = record.get("mean_confidence")
                label = "blank" if record.get("blank") else (
                    f"confidence={confidence:.3f}" if confidence is not None else "no-confidence"
                )
            except Exception as exc:
                failures.append(stem)
                records[stem] = {
                    "page": stem,
                    "status": "failed",
                    "signature": next(signature for page, _, signature in pending if page == index),
                    "error": str(exc),
                }
                label = f"FAILED {exc}"
            completed += 1
            provenance["date"] = datetime.now(timezone.utc).isoformat()
            atomic_json(provenance_path, provenance)
            print(f"PROGRESS {completed}/{len(pages)} {stem} {label}", flush=True)

    for stem, record in records.items():
        if record.get("status") != "ok":
            output_paths(item, stem)["pdf"].unlink(missing_ok=True)

    derivative = None
    if source_pdf:
        try:
            derivative = merge_searchable_pdf(item, source_pdf, len(pages))
            print(f"Searchable PDF: {item / derivative['file']}", flush=True)
        except Exception as exc:
            failures.append("searchable-pdf")
            provenance["derivative_error"] = str(exc)
            print(f"Searchable PDF FAILED: {exc}", file=sys.stderr, flush=True)
    provenance["pages_ok"] = sum(record.get("status") == "ok" for record in records.values())
    provenance["pages_failed"] = sorted(set(failures))
    provenance["date"] = datetime.now(timezone.utc).isoformat()
    atomic_json(provenance_path, provenance)
    update_item_metadata(item, provenance, derivative)
    print(
        f"OCR done: {provenance['pages_ok']} ok, {len(provenance['pages_failed'])} failed.",
        flush=True,
    )
    if provenance["pages_ok"] == 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
