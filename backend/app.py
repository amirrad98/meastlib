"""Local administration API for uploading and processing meastlib items."""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.metadata import analyze_pdf


ROOT = Path("/app")
DATA_DIR = ROOT / "data"
ITEMS_DIR = DATA_DIR / "items"
UPLOADS_DIR = DATA_DIR / "admin" / "uploads"
JOBS_FILE = DATA_DIR / "admin" / "jobs.json"
FIXITY_FILE = DATA_DIR / "admin" / "fixity.json"
BATCHES_DIR = DATA_DIR / "admin" / "batches"
INBOX_DIR = Path(os.environ.get("INBOX_DIR", "/inbox"))
PIPELINE_DIR = ROOT / "pipeline"
SOLR_URL = os.environ.get("SOLR_URL", "http://solr:8983/solr/meastlib")
CANTALOUPE_URL = os.environ.get("CANTALOUPE_URL", "http://cantaloupe:8182/")
OCR_WORKERS = max(1, int(os.environ.get("OCR_WORKERS", "2")))
SEARCH_VISIBILITY = os.environ.get("MEASTLIB_SEARCH_VISIBILITY", "all")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
ITEM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
BATCH_ID_RE = re.compile(r"^[a-f0-9]{32}$")
ACTIVE_STATUSES = {"queued", "running", "canceling"}
REMOVABLE_BATCH_STATUSES = {"partial", "failed", "canceled"}

app = FastAPI(title="meastlib administration API", version="0.1.0")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meastlib-job")
state_lock = threading.RLock()
processes: dict[str, subprocess.Popen[str]] = {}


class BatchRequest(BaseModel):
    files: list[str] = Field(min_length=1, max_length=10000)
    process_mode: str = "full"


class MetadataPatch(BaseModel):
    title: str | None = None
    title_original_script: str | None = None
    creator: str | None = None
    publisher: str | None = None
    place_published: str | None = None
    date_published: str | None = None
    date_calendar: str | None = None
    edition: str | None = None
    series_title: str | None = None
    collection_id: str | None = None
    volume_number: int | None = None
    volume_label: str | None = None
    issue_number: str | None = None
    language: str | None = None
    item_type: str | None = None
    subjects: list[str] | None = None
    rights: str | None = None
    rights_basis: str | None = None
    rights_reviewed_by: str | None = None
    cover_page: int | None = Field(default=None, ge=1)
    notes: str | None = None


class WordCorrection(BaseModel):
    word_id: str
    original: str
    content: str = Field(max_length=500)


class CorrectionRequest(BaseModel):
    corrections: list[WordCorrection] = Field(max_length=1000)
    reviewer: str = "local administrator"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_highlight_snippet(value: Any) -> str:
    escaped = html.escape(str(value))
    return escaped.replace("&lt;em&gt;", "<em>").replace("&lt;/em&gt;", "</em>")


def upgraded_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return the metadata v3 view without rewriting the preservation record."""
    value = dict(metadata)
    value["schema_version"] = 3
    value.setdefault("rights_basis", "")
    value.setdefault("rights_reviewed_at", "")
    value.setdefault("rights_reviewed_by", "")
    value.setdefault("date_display", value.get("date_published", ""))
    value.setdefault("cover_page", 1)
    value.setdefault("issue_number", "")
    value["public"] = bool(
        value.get("rights") == "public-domain"
        and value.get("rights_basis")
        and value.get("rights_reviewed_at")
    )
    return value


def load_item_metadata(path: Path) -> dict[str, Any]:
    try:
        return upgraded_metadata(json.loads((path / "metadata.json").read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return upgraded_metadata({"id": path.name, "title": path.name, "rights": "unknown"})


def item_is_visible(metadata: dict[str, Any]) -> bool:
    return SEARCH_VISIBILITY != "public" or bool(metadata.get("public"))


def public_item_path(item_id: str) -> Path:
    if not ITEM_ID_RE.fullmatch(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    path = ITEMS_DIR / item_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")
    metadata = load_item_metadata(path)
    if not item_is_visible(metadata):
        raise HTTPException(status_code=404, detail="Item not found")
    return path


def cover_url(metadata: dict[str, Any], width: int = 360) -> str:
    page = max(1, int(metadata.get("cover_page") or 1))
    item_id = metadata.get("id", "")
    filename = f"page-{page:04d}.jpg"
    return f"/iiif/3/{item_id}%2Faccess%2F{filename}/full/{width},/0/default.jpg"


def catalog_card(path: Path, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    value = metadata or load_item_metadata(path)
    return {
        "id": value.get("id", path.name),
        "title": value.get("title") or path.name,
        "title_original_script": value.get("title_original_script", ""),
        "creator": value.get("creator", ""),
        "date": value.get("date_display") or value.get("date_published", ""),
        "date_calendar": value.get("date_calendar", ""),
        "language": value.get("language", ""),
        "type": value.get("type", ""),
        "subjects": value.get("subjects", []),
        "series_title": value.get("series_title", ""),
        "collection_id": value.get("collection_id", ""),
        "volume_number": value.get("volume_number"),
        "volume_label": value.get("volume_label", ""),
        "issue_number": value.get("issue_number", ""),
        "pages": value.get("pages", 0),
        "rights": value.get("rights", "unknown"),
        "public": bool(value.get("public")),
        "ocr_confidence": value.get("ocr_confidence"),
        "ingested": value.get("ingested", ""),
        "thumbnail": cover_url(value),
    }


def solr_facet(values: list[Any]) -> list[dict[str, Any]]:
    return [
        {"value": str(values[index]), "count": int(values[index + 1])}
        for index in range(0, len(values) - 1, 2)
        if values[index] not in (None, "") and int(values[index + 1]) > 0
    ]


def escaped_filter(field: str, value: str) -> str:
    clean = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'{field}:"{clean}"'


def solr_field_names() -> set[str]:
    try:
        response = requests.get(f"{SOLR_URL}/schema/fields", params={"wt": "json"}, timeout=5)
        response.raise_for_status()
        return {str(field.get("name")) for field in response.json().get("fields", [])}
    except (requests.RequestException, ValueError):
        return set()


def safe_ocr_highlighting(value: dict[str, Any]) -> dict[str, Any]:
    result = {"numTotal": int(value.get("numTotal", 0)), "snippets": []}
    for snippet in value.get("snippets", [])[:3]:
        result["snippets"].append({
            "text": safe_highlight_snippet(snippet.get("text", "")),
            "pages": snippet.get("pages", []),
            "regions": [
                {**region, "text": safe_highlight_snippet(region.get("text", ""))}
                for region in snippet.get("regions", [])
            ],
            "highlights": [
                [{**highlight, "text": html.escape(str(highlight.get("text", "")))} for highlight in group]
                for group in snippet.get("highlights", [])
            ],
        })
    return result


def correction_page(item_id: str, page: str) -> tuple[Path, Path, Path]:
    if not re.fullmatch(r"page-\d{4}", page):
        raise HTTPException(status_code=400, detail="Invalid page identifier")
    item = ITEMS_DIR / item_id
    if not item.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")
    source = item / "ocr" / f"{page}.alto.xml"
    if not source.exists():
        raise HTTPException(status_code=404, detail="ALTO page not found")
    return source, item / "ocr" / "corrected" / source.name, item / "ocr" / "corrections" / f"{page}.json"


def alto_words(path: Path) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    words = []
    for word in root.findall(".//{*}String"):
        words.append({
            "id": word.get("ID", ""), "content": word.get("CONTENT", ""),
            "confidence": float(word.get("WC", "0") or 0),
            "bbox": [int(float(word.get(name, "0") or 0)) for name in ("HPOS", "VPOS", "WIDTH", "HEIGHT")],
        })
    return words


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def safe_inbox_file(relative_path: str) -> Path:
    inbox = INBOX_DIR.resolve()
    candidate = (inbox / relative_path).resolve()
    if candidate != inbox and inbox not in candidate.parents:
        raise HTTPException(status_code=400, detail=f"Inbox path escapes mounted directory: {relative_path}")
    if not candidate.is_file() or candidate.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail=f"Inbox PDF not found: {relative_path}")
    return candidate


def known_source_checksums() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ITEMS_DIR.exists():
        return values
    for metadata_path in ITEMS_DIR.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            checksum = metadata.get("source_file", {}).get("sha256")
            if checksum:
                values[str(checksum)] = metadata_path.parent.name
        except (OSError, json.JSONDecodeError):
            continue
    return values


def load_batch(batch_id: str) -> dict[str, Any]:
    path = BATCHES_DIR / f"{batch_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Batch not found")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Batch state is unreadable: {exc}") from exc


def save_batch(batch: dict[str, Any]) -> None:
    atomic_json(BATCHES_DIR / f"{batch['id']}.json", batch)


def remove_batch_history(batch_id: str) -> dict[str, str]:
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise HTTPException(status_code=404, detail="Batch not found")
    with state_lock:
        batch = load_batch(batch_id)
        if batch.get("status") not in REMOVABLE_BATCH_STATUSES or active_batch_job(batch_id):
            raise HTTPException(
                status_code=409,
                detail="Only failed, partial, or canceled batches that are no longer running can be removed",
            )
        (BATCHES_DIR / f"{batch_id}.json").unlink()
        shutil.rmtree(BATCHES_DIR / "work" / batch_id, ignore_errors=True)
        jobs[:] = [job for job in jobs if job.get("item_id") != f"batch:{batch_id}"]
        save_jobs()
    return {"removed": batch_id}


def load_jobs() -> list[dict[str, Any]]:
    if not JOBS_FILE.exists():
        return []
    try:
        jobs = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    changed = False
    for job in jobs:
        if job.get("status") in ACTIVE_STATUSES:
            job["status"] = "interrupted"
            job["finished_at"] = now()
            job["error"] = "The administration service restarted while this job was active."
            changed = True
    if changed:
        save_jobs(jobs)
    return jobs


def save_jobs(value: list[dict[str, Any]] | None = None) -> None:
    JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = jobs if value is None else value
    temporary = JOBS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(JOBS_FILE)


jobs: list[dict[str, Any]] = []
jobs = load_jobs()


def get_job(job_id: str) -> dict[str, Any]:
    with state_lock:
        for job in jobs:
            if job["id"] == job_id:
                return job
    raise HTTPException(status_code=404, detail="Job not found")


def update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    with state_lock:
        job = get_job(job_id)
        job.update(updates)
        save_jobs()
        return dict(job)


def append_log(job_id: str, line: str) -> None:
    clean = line.rstrip()
    if not clean:
        return
    with state_lock:
        job = get_job(job_id)
        job.setdefault("logs", []).append(clean)
        job["logs"] = job["logs"][-1200:]
        save_jobs()


def make_job(item_id: str, kind: str, stages: list[dict[str, Any]], cleanup: str = "") -> dict[str, Any]:
    job = {
        "id": uuid.uuid4().hex,
        "item_id": item_id,
        "kind": kind,
        "status": "queued",
        "stage": "Waiting",
        "created_at": now(),
        "started_at": None,
        "finished_at": None,
        "error": "",
        "logs": [],
        "stages": stages,
        "cleanup": cleanup,
    }
    with state_lock:
        jobs.insert(0, job)
        del jobs[200:]
        save_jobs()
    executor.submit(run_job, job["id"])
    return dict(job)


def run_job(job_id: str) -> None:
    job = get_job(job_id)
    if job["status"] == "canceled":
        return
    update_job(job_id, status="running", started_at=now())
    try:
        for stage in job["stages"]:
            if get_job(job_id)["status"] in {"canceled", "canceling"}:
                update_job(job_id, status="canceled", stage="Canceled", finished_at=now())
                return
            label = stage["label"]
            command = [str(value) for value in stage["command"]]
            update_job(job_id, stage=label)
            append_log(job_id, f"\n[{label}]")
            append_log(job_id, "$ " + " ".join(command))
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
            with state_lock:
                processes[job_id] = process
            assert process.stdout is not None
            for line in process.stdout:
                append_log(job_id, line)
            return_code = process.wait()
            with state_lock:
                processes.pop(job_id, None)
            if get_job(job_id)["status"] in {"canceled", "canceling"}:
                update_job(job_id, status="canceled", stage="Canceled", finished_at=now())
                return
            if return_code:
                raise RuntimeError(f"{label} exited with status {return_code}")
        update_job(job_id, status="succeeded", stage="Complete", finished_at=now())
    except Exception as exc:  # job failures are returned to the administration UI
        append_log(job_id, f"ERROR: {exc}")
        update_job(job_id, status="failed", stage="Failed", error=str(exc), finished_at=now())
    finally:
        with state_lock:
            processes.pop(job_id, None)
        cleanup = job.get("cleanup")
        if cleanup:
            shutil.rmtree(cleanup, ignore_errors=True)


def python_stage(label: str, script: str, *args: str) -> dict[str, Any]:
    return {
        "label": label,
        "command": [sys.executable, str(PIPELINE_DIR / script), *args],
    }


def processing_stages(item_id: str, action: str, ocr_languages: str) -> list[dict[str, Any]]:
    item = str(ITEMS_DIR / item_id)
    stages: list[dict[str, Any]] = []
    if action in {"ocr", "all"}:
        stages.append(
            python_stage(
                "OCR", "ocr.py", item, "--engine", "tesseract", "--langs", ocr_languages,
                "--workers", str(OCR_WORKERS),
            )
        )
    if action in {"manifest", "all"}:
        stages.append(python_stage("IIIF manifest", "manifest.py", item))
    if action in {"index", "all"}:
        stages.append(python_stage("Solr index", "index.py", item, "--solr", SOLR_URL))
    return stages


def batch_stages(batch_id: str) -> list[dict[str, Any]]:
    return [python_stage(
        "Batch processing",
        "batch.py",
        "--state", str(BATCHES_DIR / f"{batch_id}.json"),
        "--inbox", str(INBOX_DIR),
        "--data", str(DATA_DIR),
        "--solr", SOLR_URL,
        "--workers", str(OCR_WORKERS),
    )]


def active_batch_job(batch_id: str) -> dict[str, Any] | None:
    item_id = f"batch:{batch_id}"
    with state_lock:
        return next(
            (job for job in jobs if job.get("item_id") == item_id and job.get("status") in ACTIVE_STATUSES),
            None,
        )


def other_active_batch_job(batch_id: str = "") -> dict[str, Any] | None:
    current_item_id = f"batch:{batch_id}" if batch_id else ""
    with state_lock:
        return next(
            (
                job for job in jobs
                if str(job.get("item_id", "")).startswith("batch:")
                and job.get("item_id") != current_item_id
                and job.get("status") in ACTIVE_STATUSES
            ),
            None,
        )


def queue_batch(batch_id: str) -> dict[str, Any]:
    active = active_batch_job(batch_id)
    if active:
        return dict(active)
    batch = load_batch(batch_id)
    batch.update({"status": "queued", "finished_at": None, "updated_at": now()})
    save_batch(batch)
    return make_job(f"batch:{batch_id}", "batch", batch_stages(batch_id))


def solr_document_count(item_id: str) -> int | None:
    try:
        response = requests.get(
            f"{SOLR_URL}/select",
            params={
                "q": f'item_id:"{item_id}"',
                "fq": "doc_type:page",
                "rows": 0,
                "wt": "json",
            },
            timeout=2,
        )
        response.raise_for_status()
        return int(response.json()["response"]["numFound"])
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None


def item_summary(path: Path) -> dict[str, Any]:
    metadata = load_item_metadata(path)
    access_pages = len(list((path / "access").glob("page-*.jpg")))
    ocr_pages = len(list((path / "ocr").glob("page-*.alto.xml")))
    searchable_pdf = path / "derivatives" / "searchable.pdf"
    provenance_path = path / "ocr" / "provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        provenance = {}
    return {
        **metadata,
        "access_pages": access_pages,
        "ocr_pages": ocr_pages,
        "ocr_confidence": metadata.get("ocr_confidence"),
        "ocr_failed_pages": provenance.get("pages_failed", []),
        "has_manifest": (path / "iiif" / "manifest.json").exists(),
        "searchable_pdf": (
            f"/data/items/{path.name}/derivatives/searchable.pdf" if searchable_pdf.exists() else ""
        ),
        "indexed_pages": solr_document_count(path.name),
    }


def item_quality(path: Path) -> dict[str, Any]:
    summary = item_summary(path)
    try:
        provenance = json.loads((path / "ocr/provenance.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        provenance = {}
    low_pages = []
    for page_id, record in provenance.get("pages", {}).items():
        confidence = record.get("mean_confidence")
        if record.get("status") == "ok" and not record.get("blank") and confidence is not None and confidence < 0.70:
            low_pages.append({"page": page_id, "confidence": confidence, "words": record.get("words", 0)})
    issues = []
    if summary.get("metadata_warnings"):
        issues.append("metadata")
    if summary.get("ocr_confidence") is not None and summary["ocr_confidence"] < 0.75:
        issues.append("low-item-confidence")
    if low_pages:
        issues.append("low-page-confidence")
    if summary.get("ocr_failed_pages"):
        issues.append("failed-pages")
    if summary.get("access_pages") != summary.get("ocr_pages"):
        issues.append("page-count-mismatch")
    if summary.get("indexed_pages") is not None and summary.get("indexed_pages") != summary.get("ocr_pages"):
        issues.append("index-mismatch")
    if summary.get("rights") == "unknown" or not summary.get("rights_reviewed_at"):
        issues.append("rights-review")
    return {"item": catalog_card(path, summary), "issues": issues, "low_pages": low_pages[:100], "summary": summary}


def service_check(url: str) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=3)
        return {"ok": response.ok, "status": response.status_code}
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/tools")
def tools() -> dict[str, Any]:
    try:
        version = subprocess.run(
            ["tesseract", "--version"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.splitlines()[0]
        languages = subprocess.run(
            ["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5, check=True
        ).stdout.splitlines()[1:]
        tesseract = {"ok": True, "version": version, "languages": languages}
    except (OSError, subprocess.SubprocessError) as exc:
        tesseract = {"ok": False, "error": str(exc), "languages": []}
    return {
        "tesseract": tesseract,
        "solr": service_check(f"{SOLR_URL}/admin/ping?wt=json"),
        "iiif": service_check(CANTALOUPE_URL),
        "storage": {"ok": os.access(DATA_DIR, os.W_OK), "path": str(DATA_DIR)},
        "inbox": {
            "ok": INBOX_DIR.is_dir() and os.access(INBOX_DIR, os.R_OK),
            "path": str(INBOX_DIR),
            "read_only": True,
        },
        "metadata": {"ok": True, "provider": "local", "detail": "PDF metadata + sampled-page OCR"},
    }


@app.get("/api/inbox")
def scan_inbox(recursive: bool = True) -> dict[str, Any]:
    if not INBOX_DIR.is_dir():
        return {"ok": False, "path": str(INBOX_DIR), "files": [], "error": "Inbox mount is unavailable"}
    paths = INBOX_DIR.rglob("*") if recursive else INBOX_DIR.glob("*")
    known = known_source_checksums()
    files: list[dict[str, Any]] = []
    for path in sorted(candidate for candidate in paths if candidate.is_file() and candidate.suffix.lower() == ".pdf"):
        try:
            checksum = sha256_file(path)
            stat = path.stat()
        except OSError:
            continue
        files.append({
            "relative_path": path.relative_to(INBOX_DIR).as_posix(),
            "bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "sha256": checksum,
            "status": "duplicate" if checksum in known else "ready",
            "duplicate_of": known.get(checksum, ""),
        })
    return {
        "ok": True,
        "path": str(INBOX_DIR),
        "files": files,
        "total_bytes": sum(item["bytes"] for item in files),
    }


@app.get("/api/batches")
def list_batches() -> list[dict[str, Any]]:
    if not BATCHES_DIR.exists():
        return []
    values = []
    for path in BATCHES_DIR.glob("*.json"):
        try:
            values.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(values, key=lambda batch: batch.get("created_at", ""), reverse=True)


@app.post("/api/batches")
def create_batch(request: BatchRequest) -> dict[str, Any]:
    if request.process_mode not in {"full", "viewer"}:
        raise HTTPException(status_code=400, detail="Invalid process mode")
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for relative in request.files:
        normalized = Path(relative).as_posix().lstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        source = safe_inbox_file(normalized)
        stat = source.stat()
        files.append({
            "relative_path": normalized,
            "bytes": stat.st_size,
            "sha256": sha256_file(source),
            "status": "queued",
            "stage": "Waiting",
            "item_id": "",
            "duplicate_of": "",
            "pages_done": 0,
            "pages_total": 0,
            "current_page": "",
            "page_detail": "",
            "error": "",
            "updated_at": now(),
        })
    batch_id = uuid.uuid4().hex
    batch = {
        "id": batch_id,
        "status": "queued",
        "process_mode": request.process_mode,
        "created_at": now(),
        "updated_at": now(),
        "started_at": None,
        "finished_at": None,
        "files": files,
    }
    with state_lock:
        if other_active_batch_job():
            raise HTTPException(status_code=409, detail="Another folder batch is already active")
        save_batch(batch)
        job = queue_batch(batch_id)
    return {**batch, "job_id": job["id"]}


@app.get("/api/batches/{batch_id}")
def read_batch(batch_id: str) -> dict[str, Any]:
    return load_batch(batch_id)


@app.post("/api/batches/{batch_id}/resume")
def resume_batch(batch_id: str) -> dict[str, Any]:
    batch = load_batch(batch_id)
    if batch.get("status") == "succeeded":
        return batch
    if other_active_batch_job(batch_id):
        raise HTTPException(status_code=409, detail="Another folder batch is already active")
    job = queue_batch(batch_id)
    return {**load_batch(batch_id), "job_id": job["id"]}


@app.post("/api/batches/{batch_id}/cancel")
def cancel_batch(batch_id: str) -> dict[str, Any]:
    batch = load_batch(batch_id)
    job = active_batch_job(batch_id)
    if job:
        cancel_job(job["id"])
    batch.update({"status": "canceled", "finished_at": now(), "updated_at": now()})
    save_batch(batch)
    return batch


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str) -> dict[str, str]:
    """Dismiss terminal failed batch history without touching inbox files or library items."""
    return remove_batch_history(batch_id)


@app.get("/api/catalog/items")
def catalog_items(
    q: str = "",
    start: int = 0,
    rows: int = 24,
    sort: str = "recent",
    language: str = "",
    item_type: str = "",
    collection: str = "",
    creator: str = "",
    subject: str = "",
    date_from: str = "",
    date_to: str = "",
) -> dict[str, Any]:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    values = []
    query = q.strip().casefold()
    for path in ITEMS_DIR.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        metadata = load_item_metadata(path)
        if not item_is_visible(metadata):
            continue
        haystack = " ".join(str(value) for value in [
            metadata.get("title", ""), metadata.get("title_original_script", ""),
            metadata.get("creator", ""), metadata.get("publisher", ""),
            metadata.get("series_title", ""), metadata.get("issue_number", ""),
            *metadata.get("alternative_titles", []), *metadata.get("subjects", []),
        ]).casefold()
        if query and query not in haystack:
            continue
        values.append((path, metadata))

    facet_source = [metadata for _, metadata in values]
    if language:
        values = [entry for entry in values if entry[1].get("language") == language]
    if item_type:
        values = [entry for entry in values if entry[1].get("type") == item_type]
    if collection:
        values = [entry for entry in values if entry[1].get("collection_id") == collection]
    if creator:
        values = [entry for entry in values if entry[1].get("creator") == creator]
    if subject:
        values = [entry for entry in values if subject in entry[1].get("subjects", [])]
    if date_from:
        values = [entry for entry in values if str(entry[1].get("date_published", "")) >= date_from]
    if date_to:
        values = [entry for entry in values if str(entry[1].get("date_published", "")) <= date_to]

    if sort == "title":
        values.sort(key=lambda entry: str(entry[1].get("title", "")).casefold())
    elif sort == "date":
        values.sort(key=lambda entry: str(entry[1].get("date_published", "")), reverse=True)
    else:
        values.sort(key=lambda entry: str(entry[1].get("ingested", "")), reverse=True)

    def facet(field: str, many: bool = False) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for metadata in facet_source:
            raw = metadata.get(field, []) if many else [metadata.get(field, "")]
            for value in raw or []:
                if value:
                    counts[str(value)] = counts.get(str(value), 0) + 1
        return [{"value": key, "count": count} for key, count in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]

    start = max(0, start)
    rows = max(1, min(rows, 100))
    collection_labels = {
        str(metadata.get("collection_id")): str(metadata.get("series_title") or metadata.get("title") or metadata.get("collection_id"))
        for metadata in facet_source if metadata.get("collection_id")
    }
    collection_facets = facet("collection_id")
    for entry in collection_facets:
        entry["label"] = collection_labels.get(entry["value"], entry["value"])
    return {
        "total": len(values),
        "start": start,
        "rows": rows,
        "items": [catalog_card(path, metadata) for path, metadata in values[start:start + rows]],
        "facets": {
            "language": facet("language"), "type": facet("type"),
            "collection": collection_facets, "creator": facet("creator"),
            "subject": facet("subjects", many=True),
        },
    }


@app.get("/api/catalog/items/{item_id}")
def catalog_item(item_id: str) -> dict[str, Any]:
    path = public_item_path(item_id)
    metadata = load_item_metadata(path)
    related = []
    collection_id = metadata.get("collection_id")
    if collection_id:
        for candidate in ITEMS_DIR.iterdir():
            if candidate.is_dir() and not candidate.name.startswith("."):
                candidate_metadata = load_item_metadata(candidate)
                if candidate_metadata.get("collection_id") == collection_id and item_is_visible(candidate_metadata):
                    related.append(catalog_card(candidate, candidate_metadata))
        if metadata.get("type") == "newspaper":
            related.sort(key=lambda item: str(item.get("date", "")), reverse=True)
        else:
            related.sort(key=lambda item: (item.get("volume_number") is None, item.get("volume_number") or 0))
    derivatives = {
        "manifest": f"/data/items/{item_id}/iiif/manifest.json" if (path / "iiif/manifest.json").exists() else "",
        "searchable_pdf": f"/data/items/{item_id}/derivatives/searchable.pdf" if (path / "derivatives/searchable.pdf").exists() else "",
        "alto_template": f"/api/catalog/items/{item_id}/ocr/{{page}}?format=alto",
        "text_template": f"/api/catalog/items/{item_id}/ocr/{{page}}?format=text",
    }
    return {**metadata, "thumbnail": cover_url(metadata, 600), "related_items": related, "derivatives": derivatives}


@app.get("/api/catalog/items/{item_id}/ocr/{page}")
def catalog_ocr_derivative(item_id: str, page: str, format: str = "text") -> FileResponse:
    item = public_item_path(item_id)
    if not re.fullmatch(r"page-\d{4,8}", page):
        raise HTTPException(status_code=404, detail="OCR page not found")
    if format == "text":
        suffix, media_type = ".txt", "text/plain; charset=utf-8"
    elif format == "alto":
        suffix, media_type = ".alto.xml", "application/xml"
    else:
        raise HTTPException(status_code=400, detail="Format must be text or alto")
    corrected = item / "ocr" / "corrected" / f"{page}{suffix}"
    original = item / "ocr" / f"{page}{suffix}"
    path = corrected if corrected.is_file() else original
    if not path.is_file():
        raise HTTPException(status_code=404, detail="OCR derivative not found")
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/catalog/collections/{collection_id}")
def catalog_collection(collection_id: str) -> dict[str, Any]:
    items = []
    for path in ITEMS_DIR.iterdir() if ITEMS_DIR.exists() else []:
        if path.is_dir() and not path.name.startswith("."):
            metadata = load_item_metadata(path)
            if metadata.get("collection_id") == collection_id and item_is_visible(metadata):
                items.append(catalog_card(path, metadata))
    if not items:
        raise HTTPException(status_code=404, detail="Collection not found")
    if items[0].get("type") == "newspaper":
        items.sort(key=lambda item: str(item.get("date", "")), reverse=True)
    else:
        items.sort(key=lambda item: (item.get("volume_number") is None, item.get("volume_number") or 0))
    return {"id": collection_id, "title": items[0].get("series_title") or items[0]["title"], "items": items}


@app.get("/api/search")
def search(
    q: str,
    rows: int = 10,
    start: int = 0,
    scope: str = "all",
    sort: str = "relevance",
    language: str = "",
    item_type: str = "",
    collection: str = "",
    creator: str = "",
    subject: str = "",
    date_from: int | None = None,
    date_to: int | None = None,
) -> dict[str, Any]:
    query = q.strip()
    if not query:
        return {"total": 0, "hits": []}
    if len(query) > 500:
        raise HTTPException(status_code=400, detail="Search query is too long")
    rows = max(1, min(rows, 50))
    start = max(0, start)
    available_fields = solr_field_names()
    params: list[tuple[str, Any]] = [
        ("q", query),
        ("defType", "edismax"),
        ("q.op", "AND"),
        (
            "qf",
            "title^8 title_original_script^8 alternative_titles^6 creators^6 "
            "contributors^4 series_title^6 publisher^3 place_published^2 "
            "date_published^2 edition^2 identifiers^7 subjects^3 temporal_coverage^3 ocr_text",
        ),
        ("hl", "on"),
        ("hl.ocr.fl", "ocr_text"),
        ("hl.snippets", 3),
        ("group", "true"),
        ("group.field", "item_id"),
        ("group.ngroups", "true"),
        ("group.limit", 4),
        ("group.sort", "score desc"),
        ("facet", "true"),
        ("facet.limit", 50),
        ("facet.mincount", 1),
        ("facet.field", "language"),
        ("facet.field", "type"),
        ("facet.field", "collection_id"),
        ("rows", rows),
        ("start", start),
        ("wt", "json"),
    ]
    if "creator_facet" in available_fields:
        params.append(("facet.field", "creator_facet"))
    if "subjects_facet" in available_fields:
        params.append(("facet.field", "subjects_facet"))
    filters = []
    if scope == "catalog":
        filters.append("doc_type:item")
    elif scope == "fulltext":
        filters.append("doc_type:page")
    elif scope != "all":
        raise HTTPException(status_code=400, detail="Invalid search scope")
    for field, value in (
        ("language", language), ("type", item_type), ("collection_id", collection),
        (("creator_facet" if "creator_facet" in available_fields else "creator"), creator),
        (("subjects_facet" if "subjects_facet" in available_fields else "subjects"), subject),
    ):
        if value:
            filters.append(escaped_filter(field, value))
    if date_from is not None:
        filters.append(f"{('date_year' if 'date_year' in available_fields else 'date_published')}:[{date_from} TO *]")
    if date_to is not None:
        filters.append(f"{('date_year' if 'date_year' in available_fields else 'date_published')}:[* TO {date_to}]")
    for value in filters:
        params.append(("fq", value))
    if sort == "date":
        params.append(("sort", f"{('date_sort' if 'date_sort' in available_fields else 'date_published')} desc"))
    elif sort == "title":
        params.append(("sort", f"{('title_sort' if 'title_sort' in available_fields else 'id')} asc"))
    elif sort != "relevance":
        raise HTTPException(status_code=400, detail="Invalid search sort")
    if SEARCH_VISIBILITY == "public":
        params.append(("fq", "public:true"))
    try:
        response = requests.get(f"{SOLR_URL}/select", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Search service unavailable: {exc}") from exc
    highlighting = payload.get("ocrHighlighting", {})
    grouped = payload.get("grouped", {}).get("item_id", {})
    hits = []
    for group in grouped.get("groups", []):
        documents = group.get("doclist", {}).get("docs", [])
        if not documents:
            continue
        catalog = next((document for document in documents if document.get("doc_type") == "item"), None)
        representative = catalog or documents[0]
        creators = representative.get("creators") or []
        if isinstance(creators, str):
            creators = [creators]
        page_hits = []
        for document in documents:
            if document.get("doc_type") != "page":
                continue
            ocr = highlighting.get(document.get("id"), {}).get("ocr_text", {})
            page_hits.append({
                "id": document.get("id"), "page": document.get("page", "page-0001"),
                **safe_ocr_highlighting(ocr),
            })
        item_id = representative.get("item_id") or group.get("groupValue")
        hits.append({
            "item_id": item_id,
            "title": representative.get("title_display") or representative.get("title") or item_id,
            "creator": representative.get("creator_display") or representative.get("creator") or (creators[0] if creators else ""),
            "date": representative.get("date_display") or representative.get("date_published", ""),
            "language": representative.get("language", ""), "type": representative.get("type", ""),
            "series_title": representative.get("series_display") or representative.get("series_title", ""),
            "collection_id": representative.get("collection_id", ""),
            "volume_number": representative.get("volume_display") or representative.get("volume_number"),
            "catalog_match": catalog is not None,
            "page_hit_count": max(0, int(group.get("doclist", {}).get("numFound", 0)) - (1 if catalog else 0)),
            "page_hits": page_hits,
            "thumbnail": cover_url({"id": item_id, "cover_page": 1}),
        })
    fields = payload.get("facet_counts", {}).get("facet_fields", {})
    return {
        "total": int(grouped.get("ngroups") or 0), "total_documents": int(grouped.get("matches") or 0),
        "start": start, "rows": rows, "hits": hits,
        "facets": {
            "language": solr_facet(fields.get("language", [])),
            "type": solr_facet(fields.get("type", [])),
            "collection": solr_facet(fields.get("collection_id", [])),
            "creator": solr_facet(fields.get("creator_facet", [])),
            "subject": solr_facet(fields.get("subjects_facet", [])),
        },
    }


@app.get("/api/catalog/items/{item_id}/search")
def search_within_item(item_id: str, q: str, page: str = "") -> dict[str, Any]:
    public_item_path(item_id)
    if not q.strip():
        return {"total": 0, "pages": [], "current": None}
    params: list[tuple[str, Any]] = [
        ("q", q.strip()), ("defType", "edismax"), ("qf", "ocr_text"),
        ("fq", escaped_filter("item_id", item_id)), ("fq", "doc_type:page"),
        ("sort", "page asc"), ("rows", 2000), ("fl", "id,item_id,page"),
        ("hl", "on"), ("hl.ocr.fl", "ocr_text"), ("hl.snippets", 3), ("wt", "json"),
    ]
    if SEARCH_VISIBILITY == "public":
        params.append(("fq", "public:true"))
    try:
        response = requests.get(f"{SOLR_URL}/select", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Search service unavailable: {exc}") from exc
    documents = payload.get("response", {}).get("docs", [])
    pages = [document.get("page") for document in documents if document.get("page")]
    current_page = page if page in pages else (pages[0] if pages else "")
    current_id = f"{item_id}/{current_page}" if current_page else ""
    ocr = payload.get("ocrHighlighting", {}).get(current_id, {}).get("ocr_text", {})
    return {"total": len(pages), "pages": pages, "current": ({"page": current_page, **safe_ocr_highlighting(ocr)} if current_page else None)}


@app.get("/api/iiif/{item_id}/search")
def iiif_content_search(item_id: str, q: str) -> dict[str, Any]:
    public_item_path(item_id)
    params: list[tuple[str, Any]] = [
        ("q", q.strip()), ("defType", "edismax"), ("qf", "ocr_text"),
        ("fq", escaped_filter("item_id", item_id)), ("fq", "doc_type:page"),
        ("sort", "page asc"), ("rows", 100), ("hl", "on"),
        ("hl.ocr.fl", "ocr_text"), ("hl.snippets", 10), ("wt", "json"),
    ]
    if SEARCH_VISIBILITY == "public":
        params.append(("fq", "public:true"))
    try:
        response = requests.get(f"{SOLR_URL}/select", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Search service unavailable: {exc}") from exc
    items = []
    highlighting = payload.get("ocrHighlighting", {})
    for document in payload.get("response", {}).get("docs", []):
        page_id_value = document.get("page", "page-0001")
        ocr = highlighting.get(document.get("id"), {}).get("ocr_text", {})
        for snippet_index, snippet in enumerate(ocr.get("snippets", [])):
            for group_index, group in enumerate(snippet.get("highlights", [])):
                for word_index, word in enumerate(group):
                    region_index = int(word.get("parentRegionIdx", 0) or 0)
                    regions = snippet.get("regions", [])
                    region = regions[region_index] if 0 <= region_index < len(regions) else {}
                    x = int(region.get("ulx", 0)) + int(word.get("ulx", 0))
                    y = int(region.get("uly", 0)) + int(word.get("uly", 0))
                    width = max(1, int(word.get("lrx", 0)) - int(word.get("ulx", 0)))
                    height = max(1, int(word.get("lry", 0)) - int(word.get("uly", 0)))
                    items.append({
                        "id": f"/api/iiif/{item_id}/search/annotation/{page_id_value}-{snippet_index}-{group_index}-{word_index}",
                        "type": "Annotation", "motivation": "supplementing",
                        "body": {"type": "TextualBody", "value": str(word.get("text", "")), "format": "text/plain"},
                        "target": f"/iiif/{item_id}/canvas/{page_id_value}#xywh={x},{y},{width},{height}",
                    })
    return {
        "@context": "http://iiif.io/api/search/2/context.json",
        "id": f"/api/iiif/{item_id}/search?q={q}", "type": "AnnotationPage",
        "partOf": {"id": f"/data/items/{item_id}/iiif/manifest.json", "type": "Manifest"},
        "items": items,
    }


@app.post("/api/metadata/analyze")
async def analyze_metadata(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "book.pdf").name
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files can be analyzed")
    analysis_dir = UPLOADS_DIR / f"analysis-{uuid.uuid4().hex}"
    analysis_dir.mkdir(parents=True, exist_ok=False)
    pdf_path = analysis_dir / filename
    size = 0
    try:
        with pdf_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 2 GB analysis limit")
                output.write(chunk)
        try:
            return await asyncio.to_thread(analyze_pdf, pdf_path, filename)
        except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            raise HTTPException(status_code=422, detail=f"Could not analyze this PDF: {exc}") from exc
    finally:
        await file.close()
        shutil.rmtree(analysis_dir, ignore_errors=True)


@app.get("/api/items")
def list_items() -> list[dict[str, Any]]:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    items = [
        item_summary(path) for path in ITEMS_DIR.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    return sorted(items, key=lambda item: item.get("ingested", ""), reverse=True)


@app.get("/api/items/{item_id}")
def read_item(item_id: str) -> dict[str, Any]:
    path = ITEMS_DIR / item_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")
    return item_summary(path)


@app.get("/api/admin/quality")
def quality_queue() -> list[dict[str, Any]]:
    if not ITEMS_DIR.exists():
        return []
    values = [item_quality(path) for path in ITEMS_DIR.iterdir() if path.is_dir() and not path.name.startswith(".")]
    return sorted((value for value in values if value["issues"]), key=lambda value: (-len(value["issues"]), value["item"]["title"]))


@app.get("/api/admin/fixity")
def fixity_status() -> dict[str, Any]:
    try:
        return json.loads(FIXITY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": None, "items": [], "message": "No fixity audit has been run yet."}


@app.post("/api/admin/fixity/run")
def run_fixity_audit() -> dict[str, Any]:
    if any(value["item_id"] == "library:fixity" and value["status"] in ACTIVE_STATUSES for value in jobs):
        raise HTTPException(status_code=409, detail="A fixity audit is already running")
    return make_job("library:fixity", "fixity", [python_stage(
        "Fixity audit", "fixity.py", str(ITEMS_DIR), "--json", str(FIXITY_FILE),
    )])


@app.patch("/api/admin/items/{item_id}")
def update_item_metadata(item_id: str, patch: MetadataPatch) -> dict[str, Any]:
    if not ITEM_ID_RE.fullmatch(item_id):
        raise HTTPException(status_code=404, detail="Item not found")
    path = ITEMS_DIR / item_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")
    metadata_path = path / "metadata.json"
    metadata = load_item_metadata(path)
    updates = patch.model_dump(exclude_unset=True)
    if "item_type" in updates:
        updates["type"] = updates.pop("item_type")
    if updates.get("rights") and updates["rights"] not in {"unknown", "public-domain", "in-copyright"}:
        raise HTTPException(status_code=400, detail="Invalid rights value")
    metadata.update(updates)
    if metadata.get("rights") == "public-domain" and metadata.get("rights_basis"):
        metadata["rights_reviewed_at"] = metadata.get("rights_reviewed_at") or now()
        metadata["rights_reviewed_by"] = metadata.get("rights_reviewed_by") or "local administrator"
    elif metadata.get("rights") != "public-domain":
        metadata["rights_reviewed_at"] = metadata.get("rights_reviewed_at") or now()
        metadata["public"] = False
    metadata = upgraded_metadata(metadata)
    atomic_json(metadata_path, metadata)
    job = None
    if not any(value["item_id"] == item_id and value["status"] in ACTIVE_STATUSES for value in jobs):
        job = make_job(item_id, "metadata", processing_stages(item_id, "manifest", "ara+fas") + processing_stages(item_id, "index", "ara+fas"))
    return {"item": item_summary(path), "job": job}


@app.get("/api/admin/items/{item_id}/ocr/{page}/words")
def read_ocr_words(item_id: str, page: str) -> dict[str, Any]:
    source, corrected, ledger_path = correction_page(item_id, page)
    words = alto_words(source)
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        ledger = {"versions": [], "current": {}}
    current = ledger.get("current", {})
    for word in words:
        if word["id"] in current:
            word["corrected"] = current[word["id"]]["content"]
    return {
        "item_id": item_id, "page": page, "words": words,
        "versions": ledger.get("versions", []), "corrected_alto": corrected.exists(),
        "image": f"/iiif/3/{item_id}%2Faccess%2F{page}.jpg/full/1000,/0/default.jpg",
    }


@app.patch("/api/admin/items/{item_id}/ocr/{page}/corrections")
def correct_ocr_words(item_id: str, page: str, request: CorrectionRequest) -> dict[str, Any]:
    source, corrected, ledger_path = correction_page(item_id, page)
    tree = ET.parse(source)
    root = tree.getroot()
    elements = {word.get("ID", ""): word for word in root.findall(".//{*}String")}
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        ledger = {"schema_version": 1, "item_id": item_id, "page": page, "versions": [], "current": {}}
    changes = []
    for correction in request.corrections:
        word = elements.get(correction.word_id)
        if word is None:
            raise HTTPException(status_code=409, detail=f"OCR word no longer exists: {correction.word_id}")
        original = word.get("CONTENT", "")
        if correction.original != original:
            raise HTTPException(status_code=409, detail=f"OCR source changed for {correction.word_id}; reload the page")
        content = correction.content.strip()
        if not content or content == original:
            ledger.get("current", {}).pop(correction.word_id, None)
            continue
        record = {
            "content": content, "original": original,
            "bbox": [int(float(word.get(name, "0") or 0)) for name in ("HPOS", "VPOS", "WIDTH", "HEIGHT")],
        }
        ledger.setdefault("current", {})[correction.word_id] = record
        changes.append({"word_id": correction.word_id, **record})
    version = {"id": uuid.uuid4().hex, "created_at": now(), "reviewer": request.reviewer, "changes": changes}
    ledger.setdefault("versions", []).append(version)
    ledger["updated_at"] = version["created_at"]
    corrected.parent.mkdir(parents=True, exist_ok=True)
    for word_id, value in ledger.get("current", {}).items():
        if word_id in elements:
            elements[word_id].set("CONTENT", value["content"])
    temporary_alto = corrected.with_suffix(corrected.suffix + ".tmp")
    tree.write(temporary_alto, encoding="utf-8", xml_declaration=True)
    temporary_alto.replace(corrected)
    corrected_text = corrected.with_suffix("").with_suffix(".txt")
    lines = []
    for line in root.findall(".//{*}TextLine"):
        content = " ".join(word.get("CONTENT", "") for word in line.findall("./{*}String") if word.get("CONTENT"))
        if content:
            lines.append(content)
    corrected_text.write_text("\n".join(lines) + "\n", encoding="utf-8")
    atomic_json(ledger_path, ledger)
    provenance_path = ITEMS_DIR / item_id / "ocr/provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        provenance["human_reviewed"] = True
        provenance["correction_pages"] = len(list((ITEMS_DIR / item_id / "ocr/corrections").glob("page-*.json")))
        atomic_json(provenance_path, provenance)
    except (OSError, json.JSONDecodeError):
        pass
    job = None
    if not any(value["item_id"] == item_id and value["status"] in ACTIVE_STATUSES for value in jobs):
        job = make_job(item_id, "correction-derivatives", [
            python_stage("Corrected searchable PDF", "corrected_pdf.py", str(ITEMS_DIR / item_id)),
            *processing_stages(item_id, "manifest", "ara+fas"),
            *processing_stages(item_id, "index", "ara+fas"),
        ])
    return {
        "version": version, "current": ledger["current"], "job": job,
        "searchable_pdf_regeneration_queued": job is not None,
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict[str, Any]]:
    with state_lock:
        return [dict(job) for job in jobs]


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str) -> dict[str, Any]:
    return dict(get_job(job_id))


@app.delete("/api/jobs")
def clear_finished_jobs() -> dict[str, int]:
    with state_lock:
        before = len(jobs)
        jobs[:] = [job for job in jobs if job["status"] in ACTIVE_STATUSES]
        save_jobs()
        return {"removed": before - len(jobs)}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job["status"] not in ACTIVE_STATUSES:
        return dict(job)
    if job["status"] == "running":
        update_job(job_id, status="canceling")
    else:
        update_job(job_id, status="canceled", stage="Canceled", finished_at=now())
    with state_lock:
        process = processes.get(job_id)
    if process and process.poll() is None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            process.terminate()
    return dict(get_job(job_id))


@app.post("/api/items/{item_id}/actions/{action}")
def run_item_action(item_id: str, action: str, ocr_languages: str = "ara+fas") -> dict[str, Any]:
    if action not in {"ocr", "manifest", "index", "all"}:
        raise HTTPException(status_code=400, detail="Unknown action")
    if not (ITEMS_DIR / item_id).is_dir():
        raise HTTPException(status_code=404, detail="Item not found")
    if any(job["item_id"] == item_id and job["status"] in ACTIVE_STATUSES for job in jobs):
        raise HTTPException(status_code=409, detail="This item already has an active job")
    return make_job(item_id, action, processing_stages(item_id, action, ocr_languages))


@app.post("/api/items")
async def upload_item(
    file: UploadFile = File(...),
    item_id: str = Form(...),
    title: str = Form(""),
    creator: str = Form(""),
    date_published: str = Form(""),
    language: str = Form("ara"),
    item_type: str = Form("book"),
    series_title: str = Form(""),
    collection_id: str = Form(""),
    issue_number: str = Form(""),
    source_note: str = Form(""),
    rights: str = Form("unknown"),
    process_mode: str = Form("full"),
    ocr_languages: str = Form("ara+fas"),
) -> dict[str, Any]:
    item_id = item_id.strip().lower()
    if not ITEM_ID_RE.fullmatch(item_id):
        raise HTTPException(
            status_code=400,
            detail="Item ID must use lowercase letters, numbers, dots, hyphens, or underscores.",
        )
    if item_type not in {"book", "newspaper", "document"}:
        raise HTTPException(status_code=400, detail="Invalid item type")
    if rights not in {"public-domain", "unknown", "in-copyright"}:
        raise HTTPException(status_code=400, detail="Invalid rights value")
    if process_mode not in {"full", "viewer"}:
        raise HTTPException(status_code=400, detail="Invalid processing mode")
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF uploads are currently supported")
    with state_lock:
        reserved = any(
            job["item_id"] == item_id and job["status"] in ACTIVE_STATUSES for job in jobs
        )
    if (ITEMS_DIR / item_id).exists() or reserved:
        raise HTTPException(status_code=409, detail="That item ID already exists or is being uploaded")

    upload_dir = UPLOADS_DIR / uuid.uuid4().hex
    upload_dir.mkdir(parents=True, exist_ok=False)
    upload_path = upload_dir / Path(file.filename or "book.pdf").name
    size = 0
    try:
        with upload_path.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 2 GB upload limit")
                output.write(chunk)
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    finally:
        await file.close()

    ingest = python_stage(
        "Ingest PDF",
        "ingest.py",
        str(upload_path),
        "--id",
        item_id,
        "--title",
        title,
        "--creator",
        creator,
        "--date",
        date_published,
        "--lang",
        language,
        "--type",
        item_type,
        "--series-title",
        series_title,
        "--collection-id",
        collection_id,
        "--issue-number",
        issue_number,
        "--source-note",
        source_note,
        "--rights",
        rights,
    )
    stages = [ingest]
    if process_mode == "full":
        stages.extend(processing_stages(item_id, "all", ocr_languages))
    else:
        stages.extend(processing_stages(item_id, "manifest", ocr_languages))
    return make_job(item_id, f"upload-{process_mode}", stages, cleanup=str(upload_dir))


@app.on_event("startup")
def resume_interrupted_batches() -> None:
    if not BATCHES_DIR.exists():
        return
    for path in BATCHES_DIR.glob("*.json"):
        try:
            batch = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if batch.get("status") in {"queued", "running"}:
            queue_batch(batch["id"])
