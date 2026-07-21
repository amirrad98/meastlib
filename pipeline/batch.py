#!/usr/bin/env python3
"""Process a persisted inbox batch through metadata, ingest, OCR, IIIF, and Solr."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.metadata import (  # noqa: E402
    analyze_pdf,
    clean_edge,
    enrich_metadata,
    metadata_provenance,
    normalize_publisher,
)


PROGRESS_RE = re.compile(r"^PROGRESS\s+(\d+)/(\d+)\s+(page-\d+)\s+(.*)$")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_inbox_path(inbox: Path, relative: str) -> Path:
    inbox = inbox.resolve()
    candidate = (inbox / relative).resolve()
    if candidate != inbox and inbox not in candidate.parents:
        raise ValueError(f"Inbox path escapes mounted directory: {relative}")
    if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
        raise ValueError(f"Inbox PDF not found: {relative}")
    return candidate


def canonical_series(value: str) -> str:
    value = value.translate(str.maketrans("يكى", "یکی"))
    value = re.sub(r"[\s‌\-_]+", "", value.casefold())
    return value


def series_title(title: str, volume_number: int | None) -> str:
    if not volume_number:
        return ""
    cleaned = re.sub(
        r"(?:جلد|مجلد|volume|vol\.?)\s*(?:\d{1,2}|[آ-ی]+)", "", title, flags=re.I
    )
    cleaned = re.sub(r"[\s_-]+[۰-۹٠-٩1-9]$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_،")
    compact = canonical_series(cleaned)
    if re.fullmatch(r"یادداشتهای(?:علم|(?:امیر)?اسداللهعلم)", compact):
        return "یادداشتهای علم"
    return cleaned


def collection_id_for(series: str) -> str:
    if not series:
        return ""
    digest = hashlib.sha256(canonical_series(series).encode()).hexdigest()[:12]
    return f"collection-{digest}"


def existing_checksums(items_dir: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not items_dir.exists():
        return result
    for metadata_file in items_dir.glob("*/metadata.json"):
        try:
            metadata = load_json(metadata_file)
            checksum = metadata.get("source_file", {}).get("sha256")
            if checksum:
                result[str(checksum)] = metadata_file.parent.name
        except (OSError, json.JSONDecodeError):
            continue
    return result


def _metadata_confidence(item: Path) -> dict[str, float]:
    try:
        provenance = load_json(item / "metadata-provenance.json")
        return {
            str(field): float(value)
            for field, value in provenance.get("confidence", {}).items()
        }
    except (OSError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        return {}


def _person_quality(value: str) -> int:
    arabic = len(re.findall(r"[\u0600-\u06ff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    digits = len(re.findall(r"[0-9۰-۹٠-٩]", value))
    return arabic * 2 + len(value) - latin * 3 - digits * 10


def _mixed_script_noise(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2,}", value) and re.search(r"[\u0600-\u06ff]{3,}", value))


def _person_key(value: str) -> str:
    return re.sub(r"[\s‌_-]+", "", value).translate(str.maketrans("يكى", "یکی")).casefold()


def _clean_person_name(value: str) -> str:
    return clean_edge(re.sub(r"[\s،,.;:]*[0-9۰-۹٠-٩]+$", "", value))


def harmonize_collections(items_dir: Path, item_ids: list[str]) -> list[str]:
    """Normalize series authorities and reuse stronger names within a volume set."""
    records: list[tuple[Path, dict[str, Any], dict[str, float], str]] = []
    for item_id in dict.fromkeys(item_ids):
        item = items_dir / item_id
        try:
            metadata = load_json(item / "metadata.json")
        except (OSError, json.JSONDecodeError):
            continue
        original = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        series = series_title(
            metadata.get("series_title") or metadata.get("title", ""),
            metadata.get("volume_number"),
        )
        if series:
            metadata["series_title"] = series
            metadata["collection_id"] = collection_id_for(series)
        records.append((item, metadata, _metadata_confidence(item), original))

    groups: dict[str, list[tuple[Path, dict[str, Any], dict[str, float], str]]] = {}
    for record in records:
        groups.setdefault(record[1].get("collection_id") or record[0].name, []).append(record)

    changed_ids: list[str] = []
    for group in groups.values():
        best_creator_record = max(
            group,
            key=lambda record: (
                record[2].get("creator", 0),
                _person_quality(record[1].get("creator", "")),
            ),
        )
        best_creator = best_creator_record[1].get("creator", "")
        best_date_record = max(group, key=lambda record: record[2].get("date_published", 0))
        best_date_confidence = best_date_record[2].get("date_published", 0)
        best_date = best_date_record[1].get("date_published", "")
        best_calendar = best_date_record[1].get("date_calendar", "")
        best_contributors: dict[str, str] = {}
        for _, metadata, _, _ in group:
            for contributor in metadata.get("contributors") or []:
                role = contributor.get("role", "contributor")
                name = _clean_person_name(contributor.get("name", ""))
                if _person_quality(name) > _person_quality(best_contributors.get(role, "")):
                    best_contributors[role] = name

        for item, metadata, confidence, before in group:
            authority_fields: list[str] = []
            series = metadata.get("series_title", "")
            if series and metadata.get("title") != series:
                metadata["title"] = series
                if metadata.get("language") in {"ara", "fas", "ota", "urd"}:
                    metadata["title_original_script"] = series
                authority_fields.append("title")
            raw_publisher = metadata.get("publisher", "")
            place = clean_edge(metadata.get("place_published", ""))
            if not place and (":" in raw_publisher or "：" in raw_publisher):
                possible_place = clean_edge(re.split(r"[:：]", raw_publisher)[-2])
                if 2 <= len(possible_place) <= 60:
                    place = possible_place
            if place != metadata.get("place_published", ""):
                metadata["place_published"] = place
                authority_fields.append("place_published")
            normalized_publisher = normalize_publisher(raw_publisher)
            if normalized_publisher != raw_publisher:
                metadata["publisher"] = normalized_publisher
                authority_fields.append("publisher")
            current_creator = metadata.get("creator", "")
            if best_creator and (
                not current_creator
                or confidence.get("creator", 0) < 0.55
                or _person_key(current_creator) == _person_key(best_creator)
            ) and current_creator != best_creator:
                metadata["creator"] = best_creator
                metadata["creators"] = [{"name": best_creator, "role": "author"}]
                authority_fields.append("creator")
            if (
                best_date
                and best_date_confidence >= 0.7
                and confidence.get("date_published", 0) < 0.55
                and metadata.get("date_published") != best_date
            ):
                metadata["date_published"] = best_date
                metadata["date_calendar"] = best_calendar
                authority_fields.append("date_published")
            contributors = []
            seen_contributors: set[tuple[str, str]] = set()
            for contributor in metadata.get("contributors") or []:
                role = contributor.get("role", "contributor")
                original_name = contributor.get("name", "")
                name = _clean_person_name(original_name)
                replacement = best_contributors.get(role, "")
                if replacement and _person_key(name) == _person_key(replacement) and name != replacement:
                    name = replacement
                    authority_fields.append("contributors")
                elif _mixed_script_noise(name) and replacement:
                    runs = re.findall(r"[\u0600-\u06ff]{4,}", name)
                    if any(run in replacement for run in runs):
                        name = replacement
                        authority_fields.append("contributors")
                if name != original_name:
                    authority_fields.append("contributors")
                contributor_key = (role, _person_key(name))
                if not name or contributor_key in seen_contributors:
                    authority_fields.append("contributors")
                    continue
                seen_contributors.add(contributor_key)
                contributors.append({**contributor, "name": name})
            metadata["contributors"] = contributors
            if authority_fields:
                fields = ", ".join(dict.fromkeys(authority_fields))
                warning = f"Collection authority normalization applied to: {fields}."
                warnings = metadata.setdefault("metadata_warnings", [])
                if warning not in warnings:
                    warnings.append(warning)
            after = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
            if after != before:
                atomic_json(item / "metadata.json", metadata)
                changed_ids.append(item.name)
    return changed_ids


def set_file_state(state_path: Path, state: dict[str, Any], record: dict[str, Any], **updates: Any) -> None:
    record.update(updates)
    record["updated_at"] = now()
    state["updated_at"] = now()
    atomic_json(state_path, state)


def run_command(
    command: list[str],
    state_path: Path,
    state: dict[str, Any],
    record: dict[str, Any],
    progress: Callable[[re.Match[str]], None] | None = None,
) -> None:
    print("$ " + " ".join(command), flush=True)
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        if line:
            print(line, flush=True)
        if progress and (match := PROGRESS_RE.match(line)):
            progress(match)
            atomic_json(state_path, state)
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"Command exited with status {return_code}: {' '.join(command[:3])}")


def language_pack(language: str) -> str:
    return {
        "fas": "fas",
        "ara": "ara",
        "eng": "eng",
        "urd": "urd",
        "ota": "ota",
    }.get(language, "ara")


def process_record(
    record: dict[str, Any],
    state: dict[str, Any],
    state_path: Path,
    inbox: Path,
    data_dir: Path,
    solr: str,
    workers: int,
) -> None:
    items_dir = data_dir / "items"
    source = safe_inbox_path(inbox, record["relative_path"])
    set_file_state(state_path, state, record, status="fingerprinting", stage="Fingerprint")
    checksum = file_sha256(source)
    record["sha256"] = checksum
    known = existing_checksums(items_dir)
    expected_item_id = record.get("item_id", "")
    if checksum in known and known[checksum] != expected_item_id:
        set_file_state(
            state_path, state, record, status="duplicate", stage="Complete",
            duplicate_of=known[checksum], item_id=known[checksum], error="",
        )
        print(f"DUPLICATE {record['relative_path']} -> {known[checksum]}", flush=True)
        return

    work = data_dir / "admin" / "batches" / "work" / state["id"] / checksum[:12]
    work.mkdir(parents=True, exist_ok=True)
    metadata_file = work / "metadata.json"
    provenance_file = work / "metadata-provenance.json"
    if not metadata_file.exists() or not provenance_file.exists():
        set_file_state(state_path, state, record, status="analyzing", stage="Metadata analysis")
        analysis = analyze_pdf(source, source.name)
        metadata = analysis["metadata"]
        metadata["source"] = record["relative_path"]
        metadata["source_file"]["sha256"] = checksum
        metadata["rights"] = "unknown"
        metadata["public"] = False
        metadata["processing_status"] = "analyzed"
        series = series_title(metadata.get("title", ""), metadata.get("volume_number"))
        if series:
            metadata["series_title"] = series
            metadata["collection_id"] = collection_id_for(series)
            metadata["title"] = series
            if metadata.get("title_original_script"):
                metadata["title_original_script"] = series
        metadata, catalog_evidence, catalog_warnings = enrich_metadata(
            metadata, data_dir / "admin" / "catalog-cache"
        )
        metadata.setdefault("metadata_warnings", []).extend(catalog_warnings)
        provenance = metadata_provenance(analysis, catalog_evidence)
        provenance["warnings"] = list(dict.fromkeys(provenance.get("warnings", []) + catalog_warnings))
        atomic_json(metadata_file, metadata)
        atomic_json(provenance_file, provenance)
    metadata = load_json(metadata_file)
    item_id = metadata["id"]
    record["item_id"] = item_id
    item = items_dir / item_id

    if not item.exists():
        set_file_state(state_path, state, record, status="ingesting", stage="Immutable ingest", item_id=item_id)
        run_command(
            [
                sys.executable, str(ROOT / "pipeline" / "ingest.py"), str(source),
                "--id", item_id, "--metadata-file", str(metadata_file),
            ],
            state_path, state, record,
        )
        (item / "metadata-provenance.json").write_text(
            provenance_file.read_text(encoding="utf-8"), encoding="utf-8"
        )
    else:
        item_metadata = load_json(item / "metadata.json")
        if item_metadata.get("source_file", {}).get("sha256") != checksum:
            raise RuntimeError(f"Permanent item ID collision: {item_id}")

    if state.get("process_mode", "full") == "full":
        set_file_state(state_path, state, record, status="ocr", stage="OCR", pages_done=0)

        def update_progress(match: re.Match[str]) -> None:
            record["pages_done"] = int(match.group(1))
            record["pages_total"] = int(match.group(2))
            record["current_page"] = match.group(3)
            record["page_detail"] = match.group(4)
            record["updated_at"] = now()

        run_command(
            [
                sys.executable, str(ROOT / "pipeline" / "ocr.py"), str(item),
                "--engine", "tesseract", "--langs", language_pack(metadata.get("language", "ara")),
                "--workers", str(max(1, workers)),
            ],
            state_path, state, record, progress=update_progress,
        )

    set_file_state(state_path, state, record, status="manifest", stage="IIIF manifest")
    run_command(
        [sys.executable, str(ROOT / "pipeline" / "manifest.py"), str(item)],
        state_path, state, record,
    )
    final_metadata = load_json(item / "metadata.json")
    if state.get("process_mode", "full") == "full":
        final_metadata["processing_status"] = (
            "ready"
            if final_metadata.get("ocr_pages") == final_metadata.get("pages")
            else "partial"
        )
    else:
        final_metadata["processing_status"] = "metadata_ready"
    atomic_json(item / "metadata.json", final_metadata)

    if state.get("process_mode", "full") == "full":
        set_file_state(state_path, state, record, status="indexing", stage="Solr index")
        run_command(
            [sys.executable, str(ROOT / "pipeline" / "index.py"), str(item), "--solr", solr],
            state_path, state, record,
        )
    set_file_state(
        state_path, state, record,
        status=(
            "partial" if final_metadata["processing_status"] == "partial" else "succeeded"
        ),
        stage="Complete", error="", pages_done=final_metadata.get("ocr_pages", 0),
        pages_total=final_metadata.get("pages", 0),
    )


def process_records(
    state: dict[str, Any],
    state_path: Path,
    inbox: Path,
    data_dir: Path,
    solr: str,
    workers: int,
    processor: Callable[..., None] = process_record,
) -> int:
    failures = 0
    for record in state.get("files", []):
        if record.get("status") in {"succeeded", "duplicate"}:
            continue
        try:
            processor(record, state, state_path, inbox, data_dir, solr, workers)
        except Exception as exc:
            failures += 1
            set_file_state(
                state_path, state, record, status="failed", stage="Failed", error=str(exc)
            )
            print(f"ERROR {record.get('relative_path')}: {exc}", file=sys.stderr, flush=True)
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--inbox", required=True, type=Path)
    parser.add_argument("--data", type=Path, default=ROOT / "data")
    parser.add_argument("--solr", default="http://localhost:8983/solr/meastlib")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()

    state_path = args.state.resolve()
    state = load_json(state_path)
    state.update({"status": "running", "started_at": state.get("started_at") or now(), "updated_at": now()})
    atomic_json(state_path, state)
    failures = process_records(
        state, state_path, args.inbox, args.data, args.solr, args.workers
    )
    completed_records = [
        record for record in state.get("files", [])
        if record.get("status") in {"succeeded", "partial"} and record.get("item_id")
    ]
    harmonize_collections(
        args.data / "items", [record["item_id"] for record in completed_records]
    )
    for record in completed_records:
        item = args.data / "items" / record["item_id"]
        try:
            set_file_state(
                state_path, state, record, status="finalizing", stage="Collection authority"
            )
            run_command(
                [sys.executable, str(ROOT / "pipeline" / "manifest.py"), str(item)],
                state_path, state, record,
            )
            if state.get("process_mode", "full") == "full":
                run_command(
                    [sys.executable, str(ROOT / "pipeline" / "index.py"), str(item), "--solr", args.solr],
                    state_path, state, record,
                )
            metadata = load_json(item / "metadata.json")
            final_status = "partial" if metadata.get("processing_status") == "partial" else "succeeded"
            set_file_state(
                state_path, state, record, status=final_status, stage="Complete", error="",
                pages_done=metadata.get("ocr_pages", 0), pages_total=metadata.get("pages", 0),
            )
        except Exception as exc:
            failures += 1
            set_file_state(
                state_path, state, record, status="failed", stage="Finalization failed", error=str(exc)
            )
            print(
                f"ERROR finalizing {record.get('relative_path')}: {exc}",
                file=sys.stderr,
                flush=True,
            )
    statuses = {record.get("status") for record in state.get("files", [])}
    if failures or "failed" in statuses or "partial" in statuses:
        status = "partial"
    else:
        status = "succeeded"
    state.update({"status": status, "finished_at": now(), "updated_at": now()})
    atomic_json(state_path, state)
    print(f"Batch {state['id']} {status}: {len(state.get('files', []))} file(s)", flush=True)
    if all(record.get("status") == "failed" for record in state.get("files", [])):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
