"""Private, local metadata suggestions for uploaded PDF books."""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import fitz


DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PERSIAN_CHARS = set("پچژگکی")
URDU_CHARS = set("ٹڈڑںھۓے")
GENERIC_TITLES = {"untitled", "document", "scan", "scanned document", "microsoft word"}
CREATOR_PATTERNS = [
    re.compile(r"(?:تأليف|تالیف|مؤلف|المؤلف|مولف|بقلم)\s*[:：\-–]?\s*(.+)", re.I),
    re.compile(r"(?:نویسنده|نگارنده|گردآورنده)\s*[:：\-–]?\s*(.+)", re.I),
    re.compile(r"(?:author|written by|edited by)\s*[:：\-–]?\s*(.+)", re.I),
]
DATE_CONTEXT = re.compile(r"چاپ|طبع|نشر|انتشار|سنة|عام|published|publication|copyright", re.I)
YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \t\r\n|–—-_:؛،,")


def useful_title(value: str, filename: str) -> bool:
    candidate = clean(value)
    if len(candidate) < 3 or len(candidate) > 240:
        return False
    lowered = candidate.lower()
    return lowered not in GENERIC_TITLES and lowered != Path(filename).stem.lower()


def local_ocr(page: fitz.Page, output_dir: Path, index: int) -> str:
    longest = max(page.rect.width, page.rect.height)
    zoom = min(2.5, 1700 / longest) if longest else 2
    image = output_dir / f"page-{index + 1}.png"
    page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(image)
    result = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", "ara+fas+eng", "--psm", "6"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def extract_opening_pages(document: fitz.Document) -> tuple[list[str], list[dict[str, Any]], list[int]]:
    page_texts: list[str] = []
    display_lines: list[dict[str, Any]] = []
    ocr_pages: list[int] = []
    with tempfile.TemporaryDirectory(prefix="meastlib-metadata-") as directory:
        output_dir = Path(directory)
        for index in range(min(6, document.page_count)):
            page = document[index]
            text = page.get_text("text") or ""
            try:
                page_dict = page.get_text("dict")
            except (ValueError, RuntimeError):
                page_dict = {"blocks": []}
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    line_text = clean("".join(span.get("text", "") for span in spans))
                    if line_text:
                        display_lines.append({
                            "text": line_text,
                            "size": max((float(span.get("size", 0)) for span in spans), default=0),
                            "page": index + 1,
                        })
            if len(clean(text)) < 100 and index < 4:
                ocr_text = local_ocr(page, output_dir, index)
                if clean(ocr_text):
                    text = f"{text}\n{ocr_text}"
                    ocr_pages.append(index + 1)
            page_texts.append(text)
    return page_texts, display_lines, ocr_pages


def detect_language(text: str) -> tuple[str, float, str]:
    if sum(char in URDU_CHARS for char in text) >= 2:
        return "urd", 0.82, "Urdu-specific characters in the opening pages"
    if sum(char in PERSIAN_CHARS for char in text) >= 2:
        return "fas", 0.78, "Persian-specific characters in the opening pages"
    arabic_count = sum("\u0600" <= char <= "\u06ff" for char in text)
    if arabic_count >= 10:
        return "ara", 0.7, "Arabic-script text in the opening pages"
    return "ara", 0.25, "No strong language signal; kept the library default"


def find_title(metadata: dict[str, Any], filename: str, lines: list[dict[str, Any]], texts: list[str]) -> tuple[str, float, dict[str, Any]]:
    embedded = clean(str(metadata.get("title") or ""))
    if useful_title(embedded, filename):
        return embedded, 0.95, {"field": "title", "source": "Embedded PDF metadata", "text": embedded}

    candidates = [
        line for line in lines
        if line["page"] <= 3 and useful_title(line["text"], filename)
        and not YEAR_RE.fullmatch(line["text"].translate(DIGIT_TRANSLATION))
    ]
    if candidates:
        candidates.sort(key=lambda line: (line["size"], -line["page"], len(line["text"])), reverse=True)
        best = candidates[0]
        return best["text"], 0.72, {
            "field": "title", "source": "Largest opening-page text", "text": best["text"], "page": best["page"]
        }

    for page, text in enumerate(texts[:3], start=1):
        for raw_line in text.splitlines():
            candidate = clean(raw_line)
            if useful_title(candidate, filename) and len(candidate) >= 5:
                return candidate, 0.42, {
                    "field": "title", "source": "Opening-page OCR", "text": candidate, "page": page
                }
    return "", 0.0, {"field": "title", "source": "Not found", "text": ""}


def find_creator(metadata: dict[str, Any], texts: list[str]) -> tuple[str, float, dict[str, Any]]:
    embedded = clean(str(metadata.get("author") or ""))
    if embedded:
        return embedded, 0.95, {"field": "creator", "source": "Embedded PDF metadata", "text": embedded}
    for page, text in enumerate(texts[:4], start=1):
        lines = [clean(line) for line in text.splitlines() if clean(line)]
        for index, line in enumerate(lines):
            for pattern in CREATOR_PATTERNS:
                match = pattern.search(line)
                if match:
                    creator = clean(match.group(1))
                    if not creator and index + 1 < len(lines):
                        creator = lines[index + 1]
                    if 2 < len(creator) <= 160:
                        return creator, 0.68, {
                            "field": "creator", "source": "Authorship line", "text": line, "page": page
                        }
    return "", 0.0, {"field": "creator", "source": "Not found", "text": ""}


def find_date(texts: list[str]) -> tuple[str, float, dict[str, Any]]:
    fallback: tuple[str, int, str] | None = None
    for page, text in enumerate(texts[:6], start=1):
        for raw_line in text.splitlines():
            line = clean(raw_line).translate(DIGIT_TRANSLATION)
            years = YEAR_RE.findall(line)
            if not years:
                continue
            if DATE_CONTEXT.search(line):
                return years[0], 0.7, {"field": "date_published", "source": "Publication line", "text": line, "page": page}
            if fallback is None:
                fallback = (years[0], page, line)
    if fallback:
        return fallback[0], 0.38, {
            "field": "date_published", "source": "Opening-page year", "text": fallback[2], "page": fallback[1]
        }
    return "", 0.0, {"field": "date_published", "source": "Not found", "text": ""}


def suggested_item_id(title: str, date_published: str, pdf_path: Path) -> str:
    ascii_words = re.findall(r"[a-z0-9]+", title.lower())
    if ascii_words:
        base = "-".join(ascii_words[:8])[:60].strip("-")
    else:
        base = "book"
    hasher = hashlib.sha256()
    with pdf_path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    digest = hasher.hexdigest()[:8]
    suffix = f"-{date_published}" if date_published else ""
    return f"{base}{suffix}-{digest}"[:80]


def analyze_pdf(pdf_path: Path, filename: str) -> dict[str, Any]:
    document = fitz.open(pdf_path)
    try:
        metadata = document.metadata or {}
        texts, lines, ocr_pages = extract_opening_pages(document)
        combined = "\n".join(texts)
        title, title_confidence, title_evidence = find_title(metadata, filename, lines, texts)
        creator, creator_confidence, creator_evidence = find_creator(metadata, texts)
        date_published, date_confidence, date_evidence = find_date(texts)
        language, language_confidence, language_reason = detect_language(combined)
        lowered = combined.lower()
        if re.search(r"روزنامه|صحيفة|جريدة|newspaper", lowered):
            item_type, type_confidence = "newspaper", 0.72
        elif document.page_count <= 4:
            item_type, type_confidence = "document", 0.48
        else:
            item_type, type_confidence = "book", 0.7
        evidence = [title_evidence, creator_evidence, date_evidence, {
            "field": "language", "source": "Script analysis", "text": language_reason
        }]
        warnings = ["Suggestions should be reviewed against the title and publication pages."]
        if ocr_pages:
            warnings.append(f"Local OCR was used on page(s): {', '.join(map(str, ocr_pages))}.")
        return {
            "provider": "local",
            "title": title,
            "title_original_script": title if any("\u0600" <= char <= "\u06ff" for char in title) else "",
            "creator": creator,
            "date_published": date_published,
            "language": language,
            "item_type": item_type,
            "suggested_id": suggested_item_id(title, date_published, pdf_path),
            "pages_total": document.page_count,
            "pages_analyzed": min(6, document.page_count),
            "ocr_pages": ocr_pages,
            "confidence": {
                "title": title_confidence,
                "creator": creator_confidence,
                "date_published": date_confidence,
                "language": language_confidence,
                "item_type": type_confidence,
            },
            "evidence": evidence,
            "warnings": warnings,
        }
    finally:
        document.close()
