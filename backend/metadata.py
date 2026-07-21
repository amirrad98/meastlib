"""Local bibliographic extraction and optional public-catalog enrichment."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import fitz
import requests


DIGIT_TRANSLATION = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
PERSIAN_CHARS = set("پچژگکی")
URDU_CHARS = set("ٹڈڑںھۓے")
GENERIC_TITLES = {"untitled", "document", "scan", "scanned document", "microsoft word"}
GARBAGE_CREATORS = {"it", "it2", "scanner", "admin", "administrator", "unknown", "user"}
HEX_PLACEHOLDER_RE = re.compile(r"^<?[0-9a-f]{24,}>?$", re.I)
BIDI_CONTROL_RE = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
YEAR_RE = re.compile(r"(?<!\d)0?(1[0-9]{3}|20[0-9]{2})(?!\d)")
DATE_CONTEXT = re.compile(r"چاپ|طبع|نشر|انتشار|سنة|عام|published|publication|copyright", re.I)
ISBN_RE = re.compile(
    r"(?:ISBN|شابک)[^0-9۰-۹٠-٩\n]{0,28}([0-9۰-۹٠-٩][0-9۰-۹٠-٩\-\s]{7,22}[0-9Xx۰-۹٠-٩])",
    re.I,
)
CREATOR_PATTERNS = [
    re.compile(r"^(?:تأليف|تالیف|مؤلف|المؤلف|مولف|بقلم|نوشته(?:‌ی|\s+ی)?)\s*[:：\-–]?\s*(.+)", re.I),
    re.compile(r"^(?:نویسنده|نگارنده|گردآورنده)\s*[:：\-–]?\s*(.+)", re.I),
    re.compile(r"^(?:author|written by)\s*[:：\-–]?\s*(.+)", re.I),
]
CONTRIBUTOR_PATTERNS = [
    ("editor", re.compile(r"^(?:ویرایش\s+(?:از|توسط)|به\s+کوشش)\s*[:：\-–]?\s*(.+)", re.I)),
    ("translator", re.compile(r"^(?:ترجمه\s+(?:از|توسط)|مترجم\s*[:：])\s*(.+)", re.I)),
]
TITLE_LABELS = re.compile(r"(?:عنوان(?:\s*و\s*پدید[اآ]ور)?|نام\s*کتاب|title)\s*[:：]\s*(.+)", re.I)
PUBLISHER_LINE = re.compile(
    r"(?:مشخصات\s*نشر|نشر|انتشار|published)\s*[:：]?\s*(?:(?P<place>[^:\n،]{2,60})\s*[:：])?\s*(?P<publisher>[^\n،؛]{2,100})",
    re.I,
)
VOLUME_WORDS = {
    "اول": 1, "یکم": 1, "دوم": 2, "سوم": 3, "چهارم": 4, "پنجم": 5,
    "ششم": 6, "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10,
    "الأول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5,
}
PUBLISHER_AUTHORITIES = {
    "کتابسرا": "کتاب‌سرا",
}
PERSIAN_MONTHS = {
    "فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4,
    "مرداد": 5, "شهریور": 6, "مهر": 7, "آبان": 8,
    "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12,
}
PERSIAN_MONTH_LABELS = {value: key for key, value in PERSIAN_MONTHS.items()}
NEWSPAPER_TITLE_AUTHORITIES = {
    "kayhan": "کیهان",
    "keyhan": "کیهان",
    "ettelaat": "اطلاعات",
}
NEWSPAPER_FILENAME_RE = re.compile(
    r"^(?P<year>[0-9۰-۹٠-٩]{4})[-_](?P<month>[^-_]+)[-_](?P<day>[0-9۰-۹٠-٩]{1,2})"
    r"__+(?P<publication>.+?)_?\((?P<issue>[0-9۰-۹٠-٩]+)\)"
    r"(?:__+(?P<accession>[0-9۰-۹٠-٩]+))?$",
    re.I,
)


def clean(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value or "")
    normalized = BIDI_CONTROL_RE.sub("", normalized)
    normalized = normalized.replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")
    return re.sub(r"\s+", " ", normalized).strip()


def clean_edge(value: str) -> str:
    return clean(value).strip(" \t\r\n|–—-_:؛،،,/.")


def normalize_publisher(value: str) -> str:
    """Apply conservative authority control to repair common OCR spacing/noise."""
    candidate = clean_edge(value)
    if ":" in candidate or "：" in candidate:
        candidate = clean_edge(re.split(r"[:：]", candidate)[-1])
    if contains_arabic_script(candidate):
        candidate = clean_edge(re.sub(r"\s+[A-Za-z]{1,5}$", "", candidate))
    compact = re.sub(r"[^\w]+", "", candidate.replace("‌", ""), flags=re.UNICODE).casefold()
    for authority_key, authority_value in PUBLISHER_AUTHORITIES.items():
        if SequenceMatcher(None, compact, authority_key).ratio() >= 0.85:
            return authority_value
    return candidate


def ascii_digits(value: str) -> str:
    return value.translate(DIGIT_TRANSLATION)


def contains_arabic_script(value: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in value)


def looks_like_garbage(value: str, filename: str = "", field: str = "title") -> bool:
    candidate = clean_edge(value)
    lowered = candidate.casefold()
    if not candidate or len(candidate) > 300 or HEX_PLACEHOLDER_RE.fullmatch(candidate):
        return True
    if field == "title":
        return (
            len(candidate) < 3
            or lowered in GENERIC_TITLES
            or lowered == Path(filename).stem.casefold()
            or (candidate.startswith("<") and candidate.endswith(">"))
        )
    if field == "creator":
        return len(candidate) < 3 or lowered in GARBAGE_CREATORS or lowered.isdigit()
    return False


def useful_title(value: str, filename: str) -> bool:
    return not looks_like_garbage(value, filename, "title")


def filename_title(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"^\s*\d{4,}[\s_-]+", "", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    return clean_edge(re.sub(r"\s+", " ", stem))


def parse_newspaper_filename(filename: str) -> dict[str, Any] | None:
    """Parse the issue naming convention used by historical newspaper scans."""
    match = NEWSPAPER_FILENAME_RE.match(Path(filename).stem)
    if not match:
        return None
    year = int(ascii_digits(match.group("year")))
    day = int(ascii_digits(match.group("day")))
    raw_month = clean_edge(match.group("month").replace("_", " "))
    month = PERSIAN_MONTHS.get(raw_month)
    if not month or not 1 <= day <= 31:
        return None
    raw_publication = clean_edge(match.group("publication").replace("_", " "))
    authority_key = re.sub(r"[^a-z0-9]+", "", raw_publication.casefold())
    publication = NEWSPAPER_TITLE_AUTHORITIES.get(authority_key, raw_publication)
    issue_number = ascii_digits(match.group("issue"))
    accession_number = ascii_digits(match.group("accession") or "")
    date_value = f"{year:04d}-{month:02d}-{day:02d}"
    date_display = f"{day} {PERSIAN_MONTH_LABELS[month]} {year}"
    slug = re.sub(r"[^a-z0-9]+", "-", authority_key).strip("-") or "newspaper"
    return {
        "publication_title": publication,
        "alternative_title": raw_publication if raw_publication != publication else "",
        "issue_number": issue_number,
        "accession_number": accession_number,
        "date_published": date_value,
        "date_display": date_display,
        "date_calendar": "solar-hijri",
        "collection_id": f"newspaper-{slug}",
        "suggested_id": f"{slug}-{date_value}-{issue_number}"[:80],
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_ocr(page: fitz.Page, output_dir: Path, index: int, languages: str = "ara+fas+eng") -> str:
    longest = max(page.rect.width, page.rect.height)
    zoom = min(300 / 72, 3200 / longest) if longest else 2
    image = output_dir / f"page-{index + 1}.png"
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    pixmap.save(image)
    result = subprocess.run(
        ["tesseract", str(image), "stdout", "-l", languages, "--psm", "6"],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode == 0:
        return result.stdout
    if "+eng" in languages:
        return local_ocr(page, output_dir, index, languages.replace("+eng", ""))
    return ""


def metadata_page_indexes(page_count: int) -> list[int]:
    opening = list(range(min(12, page_count)))
    closing = list(range(max(0, page_count - 5), page_count))
    return list(dict.fromkeys(opening + closing))


def extract_metadata_pages(
    document: fitz.Document,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[int]]:
    pages: list[dict[str, Any]] = []
    display_lines: list[dict[str, Any]] = []
    ocr_pages: list[int] = []
    indexes = metadata_page_indexes(document.page_count)
    with tempfile.TemporaryDirectory(prefix="meastlib-metadata-") as directory:
        output_dir = Path(directory)
        for index in indexes:
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
            if len(clean(text)) < 100:
                ocr_text = local_ocr(page, output_dir, index)
                if clean(ocr_text):
                    text = f"{text}\n{ocr_text}"
                    ocr_pages.append(index + 1)
            pages.append({"page": index + 1, "text": text})
    return pages, display_lines, ocr_pages


def extract_opening_pages(document: fitz.Document) -> tuple[list[str], list[dict[str, Any]], list[int]]:
    """Backward-compatible helper used by older callers and tests."""
    pages, lines, ocr_pages = extract_metadata_pages(document)
    opening = [entry["text"] for entry in pages if entry["page"] <= 6]
    return opening, lines, [page for page in ocr_pages if page <= 6]


def detect_language(text: str) -> tuple[str, float, str]:
    if sum(char in URDU_CHARS for char in text) >= 2:
        return "urd", 0.82, "Urdu-specific characters in sampled pages"
    if sum(char in PERSIAN_CHARS for char in text) >= 2:
        return "fas", 0.82, "Persian-specific characters in sampled pages"
    arabic_count = sum("\u0600" <= char <= "\u06ff" for char in text)
    if arabic_count >= 10:
        return "ara", 0.72, "Arabic-script text in sampled pages"
    latin_count = sum(char.isascii() and char.isalpha() for char in text)
    if latin_count >= 30:
        return "eng", 0.65, "Latin-script text in sampled pages"
    return "ara", 0.2, "No strong language signal; retained the library default"


def page_lines(pages: Iterable[dict[str, Any]]) -> Iterable[tuple[int, str]]:
    for page in pages:
        for raw_line in page.get("text", "").splitlines():
            line = clean_edge(raw_line)
            if line:
                yield int(page["page"]), line


def normalize_labeled_value(value: str) -> str:
    return clean_edge(re.split(r"\s[/|]\s|\s{2,}", value, maxsplit=1)[0])


def find_title(
    metadata: dict[str, Any], filename: str, lines: list[dict[str, Any]], pages: list[dict[str, Any]]
) -> tuple[str, float, dict[str, Any]]:
    embedded = clean_edge(str(metadata.get("title") or ""))
    if useful_title(embedded, filename):
        return embedded, 0.92, {"field": "title", "source": "Embedded PDF metadata", "text": embedded}

    for page, line in page_lines(pages):
        match = TITLE_LABELS.search(line)
        if match:
            candidate = normalize_labeled_value(match.group(1))
            candidate = re.sub(r"^(?:سرشناسه|عنوان)\s*[:：]?", "", candidate).strip()
            if useful_title(candidate, filename):
                return candidate, 0.84, {
                    "field": "title", "source": "Labeled bibliographic line", "text": line, "page": page
                }

    filename_candidate = filename_title(filename)
    has_accession_prefix = bool(re.match(r"^\s*\d{4,}[\s_-]+", Path(filename).stem))
    if has_accession_prefix and useful_title(filename_candidate, filename) and len(filename_candidate) <= 80:
        return filename_candidate, 0.68, {
            "field": "title", "source": "Accession filename", "text": filename_candidate
        }

    candidates = [
        line for line in lines
        if line["page"] <= 4 and useful_title(line["text"], filename)
        and not YEAR_RE.fullmatch(ascii_digits(line["text"]))
        and not re.match(r"^(?:یادداشت\s+مترجم|فهرست|پیشگفتار|مقدمه)\s*[:：]", line["text"], re.I)
    ]
    if candidates:
        candidates.sort(key=lambda line: (line["size"], -line["page"], len(line["text"])), reverse=True)
        best = candidates[0]
        return best["text"], 0.72, {
            "field": "title", "source": "Largest opening-page text", "text": best["text"], "page": best["page"]
        }

    fallback = filename_title(filename)
    return fallback, 0.45 if fallback else 0.0, {
        "field": "title", "source": "Filename fallback" if fallback else "Not found", "text": fallback
    }


def find_creator(
    metadata: dict[str, Any], pages: list[dict[str, Any]], filename: str = ""
) -> tuple[str, float, dict[str, Any]]:
    embedded = clean_edge(str(metadata.get("author") or ""))
    embedded_title = clean_edge(str(metadata.get("title") or ""))
    if (
        not looks_like_garbage(embedded, field="creator")
        and useful_title(embedded_title, filename)
    ):
        return embedded, 0.92, {"field": "creator", "source": "Embedded PDF metadata", "text": embedded}
    for page, line in page_lines(pages):
        if page > 8:
            continue
        for pattern in CREATOR_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            creator = normalize_labeled_value(match.group(1))
            creator = re.split(r"(?:ویرایش|ترجمه|edited|translated)", creator, maxsplit=1, flags=re.I)[0]
            creator = clean_edge(creator)
            if not looks_like_garbage(creator, field="creator") and len(creator) <= 180:
                return creator, 0.78, {
                    "field": "creator", "source": "Authorship line", "text": line, "page": page
                }
    return "", 0.0, {"field": "creator", "source": "Not found", "text": ""}


def find_contributors(pages: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    values: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for page, line in page_lines(pages):
        if page > 8:
            continue
        for role, pattern in CONTRIBUTOR_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            name = normalize_labeled_value(match.group(1))
            name = clean_edge(name)
            key = (role, re.sub(r"[\s‌]+", "", name).casefold())
            if 2 < len(name) <= 180 and key not in seen:
                seen.add(key)
                values.append({"name": name, "role": role})
                evidence.append({
                    "field": "contributors", "source": f"{role.title()} line", "text": line, "page": page
                })
    return values, evidence


def find_date(pages: list[dict[str, Any]]) -> tuple[str, str, float, dict[str, Any]]:
    for page, raw_line in page_lines(pages):
        if page > 6:
            continue
        line = ascii_digits(raw_line)
        years = YEAR_RE.findall(line)
        if not years:
            continue
        if DATE_CONTEXT.search(line):
            year = years[-1]
            calendar = "solar-hijri" if 1200 <= int(year) <= 1499 else "gregorian"
            return year, calendar, 0.78, {
                "field": "date_published", "source": "Publication line", "text": raw_line, "page": page
            }
    return "", "", 0.0, {"field": "date_published", "source": "Not found", "text": ""}


def find_publisher(pages: list[dict[str, Any]]) -> tuple[str, str, dict[str, Any] | None]:
    for page, line in page_lines(pages):
        if page > 6:
            continue
        match = PUBLISHER_LINE.search(ascii_digits(line))
        if not match:
            continue
        publisher = clean_edge(match.group("publisher"))
        publisher = YEAR_RE.split(publisher, maxsplit=1)[0].strip(" ،؛:.-")
        publisher = normalize_publisher(publisher)
        place = clean_edge(match.group("place") or "")
        if 2 <= len(publisher) <= 100:
            return publisher, place, {
                "field": "publisher", "source": "Publication statement", "text": line, "page": page
            }
    return "", "", None


def isbn_checksum_valid(value: str) -> bool:
    digits = re.sub(r"[^0-9X]", "", ascii_digits(value).upper())
    if len(digits) == 10:
        total = sum((10 - i) * (10 if char == "X" else int(char)) for i, char in enumerate(digits))
        return total % 11 == 0
    if len(digits) == 13:
        total = sum(int(char) * (1 if i % 2 == 0 else 3) for i, char in enumerate(digits[:-1]))
        return (10 - total % 10) % 10 == int(digits[-1])
    return False


def normalize_isbn(value: str) -> str:
    return re.sub(r"[^0-9X]", "", ascii_digits(value).upper())


def find_identifiers(pages: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    values: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page, line in page_lines(pages):
        for match in ISBN_RE.finditer(line):
            isbn = normalize_isbn(match.group(1))
            if isbn in seen or len(isbn) not in {10, 13}:
                continue
            seen.add(isbn)
            scope = "set" if re.search(r"دوره|set", line, re.I) else "volume"
            raw_isbn = isbn
            if len(isbn) == 13 and isbn.startswith("978") and not isbn_checksum_valid(isbn):
                isbn10 = isbn[3:]
                if isbn_checksum_valid(isbn10):
                    isbn = isbn10
            values.append({
                "scheme": "ISBN", "value": isbn, "scope": scope,
                "valid_checksum": isbn_checksum_valid(isbn),
                **({"raw_value": raw_isbn} if raw_isbn != isbn else {}),
            })
            evidence.append({"field": "identifiers", "source": "ISBN line", "text": line, "page": page})
    return values, evidence


def find_volume(filename: str, pages: list[dict[str, Any]]) -> tuple[int | None, str, dict[str, Any] | None]:
    candidates: list[tuple[str, int, str]] = [(filename_title(filename), 0, "Filename")]
    candidates.extend(
        (line, page, "Scanned page")
        for page, line in page_lines(pages)
        if re.match(r"^(?:جلد|مجلد|volume|vol\.?)(?:\s|:)", ascii_digits(line), re.I)
    )
    for line, page, source in candidates:
        match = re.search(r"(?:جلد|مجلد|volume|vol\.?)[\s:._-]*(\d{1,2}|[آ-ی]+)", ascii_digits(line), re.I)
        if not match:
            trailing = re.search(r"(?:^|\s)([1-9])$", ascii_digits(line)) if source == "Filename" else None
            if not trailing:
                continue
            token = trailing.group(1)
        else:
            token = match.group(1)
        number = int(token) if token.isdigit() else VOLUME_WORDS.get(token)
        if number:
            return number, f"جلد {token}" if contains_arabic_script(line) else f"Volume {number}", {
                "field": "volume_number", "source": source, "text": line, **({"page": page} if page else {})
            }
    return None, "", None


def find_edition(pages: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    for page, line in page_lines(pages):
        if page > 6:
            continue
        match = re.search(
            r"(?:^|\s)(?:نوبت\s*)?چاپ\s*(?:[:：]?\s*)([آ-ی]+|\d{1,2})(?:\s|،|,|$)",
            ascii_digits(line), re.I,
        )
        if match:
            token = match.group(1)
            if not token.isdigit() and token not in VOLUME_WORDS:
                continue
            value = f"چاپ {token}"
            return value, {"field": "edition", "source": "Edition statement", "text": line, "page": page}
    return "", None


def find_subjects(pages: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    values: list[str] = []
    evidence: list[dict[str, Any]] = []
    for page, line in page_lines(pages):
        match = re.search(r"(?:موضوع|subject)\s*[:：]\s*(.+)", line, re.I)
        if not match:
            continue
        subject = clean_edge(match.group(1))
        if 2 < len(subject) <= 180 and subject not in values:
            values.append(subject)
            evidence.append({"field": "subjects", "source": "Subject line", "text": line, "page": page})
    return values, evidence


def find_temporal_coverage(pages: list[dict[str, Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    values: list[str] = []
    evidence: list[dict[str, Any]] = []
    for page, raw_line in page_lines(pages):
        line = ascii_digits(raw_line)
        if not re.search(r"مندرجات|پوشش|coverage", line, re.I):
            continue
        years = YEAR_RE.findall(line)
        if len(years) >= 2:
            value = f"{years[0]}/{years[-1]}"
            if value not in values:
                values.append(value)
                evidence.append({
                    "field": "temporal_coverage", "source": "Coverage line", "text": raw_line, "page": page
                })
    return values, evidence


def suggested_item_id(
    title: str,
    published: str,
    pdf_path: Path,
    language: str = "ara",
    item_type: str = "book",
    volume_number: int | None = None,
) -> str:
    digest = sha256(pdf_path)[:10]
    ascii_words = re.findall(r"[a-z0-9]+", title.casefold())
    if ascii_words:
        base = "-".join(ascii_words[:7])[:48].strip("-")
        suffix = f"-{published}" if published else ""
        return f"{base}{suffix}-{digest}"[:80]
    volume = f"-v{volume_number:02d}" if volume_number else ""
    return f"{language}-{item_type}{volume}-{digest}"[:80]


def _confidence_summary(confidence: dict[str, float]) -> list[str]:
    return [field for field, value in confidence.items() if value < 0.55]


def analyze_pdf(pdf_path: Path, filename: str | None = None) -> dict[str, Any]:
    filename = filename or pdf_path.name
    document = fitz.open(pdf_path)
    try:
        embedded = document.metadata or {}
        pages, lines, ocr_pages = extract_metadata_pages(document)
        newspaper = parse_newspaper_filename(filename)
        combined = f"{filename_title(filename)}\n" + "\n".join(page["text"] for page in pages)
        title, title_confidence, title_evidence = find_title(embedded, filename, lines, pages)
        creator, creator_confidence, creator_evidence = find_creator(embedded, pages, filename)
        contributors, contributor_evidence = find_contributors(pages)
        published, calendar, date_confidence, date_evidence = find_date(pages)
        language, language_confidence, language_reason = detect_language(combined)
        publisher, place, publisher_evidence = find_publisher(pages)
        identifiers, identifier_evidence = find_identifiers(pages)
        volume_number, volume_label, volume_evidence = find_volume(filename, pages)
        edition, edition_evidence = find_edition(pages)
        subjects, subject_evidence = find_subjects(pages)
        coverage, coverage_evidence = find_temporal_coverage(pages)
        classification_text = clean(f"{filename_title(filename)}\n{title}").casefold()
        if newspaper:
            item_type, type_confidence = "newspaper", 0.98
            title = f"{newspaper['publication_title']} — {newspaper['date_display']}"
            title_confidence = 0.98
            published = newspaper["date_published"]
            calendar = newspaper["date_calendar"]
            date_confidence = 0.99
            volume_number = None
            volume_label = ""
            title_evidence = {
                "field": "title", "source": "Newspaper issue filename", "text": Path(filename).stem
            }
            date_evidence = {
                "field": "date_published", "source": "Newspaper issue filename",
                "text": newspaper["date_display"],
            }
        elif re.search(r"روزنامه|صحیفه|جریده|newspaper", classification_text):
            item_type, type_confidence = "newspaper", 0.76
        elif document.page_count <= 4:
            item_type, type_confidence = "document", 0.55
        else:
            item_type, type_confidence = "book", 0.86

        confidence = {
            "title": title_confidence,
            "creator": creator_confidence,
            "date_published": date_confidence,
            "language": language_confidence,
            "item_type": type_confidence,
        }
        evidence = [title_evidence, creator_evidence, date_evidence, {
            "field": "language", "source": "Script analysis", "text": language_reason
        }]
        for optional in (publisher_evidence, volume_evidence, edition_evidence):
            if optional:
                evidence.append(optional)
        evidence.extend(contributor_evidence + identifier_evidence + subject_evidence + coverage_evidence)
        warnings = []
        low_fields = _confidence_summary(confidence)
        if low_fields:
            warnings.append(f"Low-confidence or missing fields: {', '.join(low_fields)}.")
        if ocr_pages:
            warnings.append(f"Local OCR was used on page(s): {', '.join(map(str, ocr_pages))}.")
        if looks_like_garbage(str(embedded.get("title") or ""), filename, "title") and embedded.get("title"):
            warnings.append("Corrupt or meaningless embedded title metadata was ignored.")
        if looks_like_garbage(str(embedded.get("author") or ""), field="creator") and embedded.get("author"):
            warnings.append("Corrupt or meaningless embedded creator metadata was ignored.")
        elif embedded.get("author") and not useful_title(str(embedded.get("title") or ""), filename):
            warnings.append("Embedded creator metadata was ignored because the PDF title metadata was not trustworthy.")

        file_hash = sha256(pdf_path)
        suggested_id = newspaper["suggested_id"] if newspaper else suggested_item_id(
            title, published, pdf_path, language=language, item_type=item_type, volume_number=volume_number
        )
        alternative_titles = []
        if newspaper and newspaper["alternative_title"]:
            alternative_titles.append(newspaper["alternative_title"])
        newspaper_identifiers = []
        if newspaper:
            newspaper_identifiers.append({
                "scheme": "issue-number", "value": newspaper["issue_number"], "scope": "issue"
            })
            if newspaper["accession_number"]:
                newspaper_identifiers.append({
                    "scheme": "source-accession", "value": newspaper["accession_number"], "scope": "issue"
                })
        metadata_record = {
            "schema_version": 3,
            "id": suggested_id,
            "title": title,
            "title_original_script": title if contains_arabic_script(title) else "",
            "alternative_titles": alternative_titles,
            "creator": creator,
            "creators": ([{"name": creator, "role": "author"}] if creator else []),
            "contributors": contributors,
            "publisher": publisher,
            "place_published": place,
            "date_published": published,
            "date_display": newspaper["date_display"] if newspaper else published,
            "date_calendar": calendar,
            "edition": edition,
            "series_title": newspaper["publication_title"] if newspaper else "",
            "collection_id": newspaper["collection_id"] if newspaper else "",
            "volume_number": volume_number,
            "volume_label": volume_label,
            "issue_number": newspaper["issue_number"] if newspaper else "",
            "identifiers": newspaper_identifiers + identifiers,
            "subjects": subjects,
            "temporal_coverage": coverage,
            "language": language,
            "script": "Arab" if language in {"ara", "fas", "ota", "urd"} else "Latn",
            "type": item_type,
            "pages": document.page_count,
            "source": "",
            "source_file": {
                "name": filename,
                "mime_type": "application/pdf",
                "bytes": pdf_path.stat().st_size,
                "sha256": file_hash,
            },
            "rights": "unknown",
            "rights_basis": "",
            "rights_reviewed_at": "",
            "rights_reviewed_by": "",
            "public": False,
            "cover_page": 1,
            "ingested": "",
            "notes": "",
            "processing_status": "analyzed",
            "metadata_warnings": warnings,
        }
        return {
            "provider": "local",
            **{key: metadata_record[key] for key in (
                "title", "title_original_script", "creator", "date_published", "language"
            )},
            "item_type": item_type,
            "suggested_id": suggested_id,
            "pages_total": document.page_count,
            "pages_analyzed": len(pages),
            "ocr_pages": ocr_pages,
            "confidence": confidence,
            "evidence": evidence,
            "warnings": warnings,
            "metadata": metadata_record,
        }
    finally:
        document.close()


def _catalog_cache_file(cache_dir: Path, provider: str, isbn: str) -> Path:
    return cache_dir / f"{provider}-{isbn}.json"


def lookup_open_library(isbn: str, cache_dir: Path) -> dict[str, Any] | None:
    contact = os.environ.get("MEASTLIB_CATALOG_EMAIL", "")
    agent = "meastlib/0.2"
    if contact:
        agent += f" ({contact})"
    cache_file = _catalog_cache_file(cache_dir, "openlibrary", isbn)
    payload: dict[str, Any] | None = None
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
    if payload is None:
        try:
            response = requests.get(
                "https://openlibrary.org/search.json",
                params={
                    "isbn": isbn,
                    "fields": "key,title,author_name,publish_date,publisher,isbn,subject,language",
                    "limit": 1,
                },
                headers={"User-Agent": agent},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(cache_file)
            time.sleep(1.0)
        except (requests.RequestException, ValueError):
            return None
    docs = payload.get("docs", []) if isinstance(payload, dict) else []
    return docs[0] if docs else None


def lookup_google_books(isbn: str, cache_dir: Path) -> dict[str, Any] | None:
    api_key = os.environ.get("GOOGLE_BOOKS_API_KEY", "")
    if not api_key:
        return None
    cache_file = _catalog_cache_file(cache_dir, "googlebooks", isbn)
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
    else:
        try:
            response = requests.get(
                "https://www.googleapis.com/books/v1/volumes",
                params={"q": f"isbn:{isbn}", "maxResults": 1, "key": api_key},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(cache_file)
        except (requests.RequestException, ValueError):
            return None
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return items[0].get("volumeInfo", {}) if items else None


def enrich_metadata(
    record: dict[str, Any], cache_dir: Path
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Fill missing fields from public catalogs without overriding local evidence."""
    enriched = json.loads(json.dumps(record, ensure_ascii=False))
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []
    isbns = [
        item.get("value", "") for item in enriched.get("identifiers", [])
        if item.get("scheme") == "ISBN" and item.get("value") and item.get("valid_checksum", True)
    ]
    if not isbns:
        return enriched, evidence, warnings
    isbn = isbns[0]
    result = lookup_open_library(isbn, cache_dir)
    provider = "Open Library"
    if result is None:
        result = lookup_google_books(isbn, cache_dir)
        provider = "Google Books"
    if result is None:
        warnings.append(f"No public-catalog match found for ISBN {isbn}.")
        return enriched, evidence, warnings

    mapping: dict[str, Any]
    if provider == "Open Library":
        mapping = {
            "title": result.get("title", ""),
            "creator": (result.get("author_name") or [""])[0],
            "publisher": (result.get("publisher") or [""])[0],
            "subjects": result.get("subject") or [],
        }
    else:
        mapping = {
            "title": result.get("title", ""),
            "creator": (result.get("authors") or [""])[0],
            "publisher": result.get("publisher", ""),
            "subjects": result.get("categories") or [],
        }
    for field, value in mapping.items():
        if not value:
            continue
        if field == "subjects":
            existing = list(enriched.get("subjects") or [])
            for subject in value:
                if subject not in existing:
                    existing.append(subject)
            enriched["subjects"] = existing
        elif not enriched.get(field):
            enriched[field] = value
            if field == "creator" and value:
                enriched["creators"] = [{"name": value, "role": "author"}]
            if field == "title" and contains_arabic_script(value):
                enriched["title_original_script"] = value
        elif clean(str(enriched.get(field))) != clean(str(value)):
            warnings.append(f"Catalog {field} conflicts with local evidence; retained the local value.")
            continue
        evidence.append({"field": field, "source": provider, "identifier": isbn, "text": value})
    return enriched, evidence, warnings


def metadata_provenance(analysis: dict[str, Any], catalog_evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated": date.today().isoformat(),
        "provider": analysis.get("provider", "local"),
        "confidence": analysis.get("confidence", {}),
        "evidence": list(analysis.get("evidence", [])) + catalog_evidence,
        "warnings": analysis.get("warnings", []),
        "sampled_pages": analysis.get("pages_analyzed", 0),
        "ocr_pages": analysis.get("ocr_pages", []),
    }
