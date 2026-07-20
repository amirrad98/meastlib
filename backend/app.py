"""Local administration API for uploading and processing meastlib items."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from backend.metadata import analyze_pdf


ROOT = Path("/app")
DATA_DIR = ROOT / "data"
ITEMS_DIR = DATA_DIR / "items"
UPLOADS_DIR = DATA_DIR / "admin" / "uploads"
JOBS_FILE = DATA_DIR / "admin" / "jobs.json"
PIPELINE_DIR = ROOT / "pipeline"
SOLR_URL = os.environ.get("SOLR_URL", "http://solr:8983/solr/meastlib")
CANTALOUPE_URL = os.environ.get("CANTALOUPE_URL", "http://cantaloupe:8182/")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
ITEM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
ACTIVE_STATUSES = {"queued", "running", "canceling"}

app = FastAPI(title="meastlib administration API", version="0.1.0")
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="meastlib-job")
state_lock = threading.RLock()
processes: dict[str, subprocess.Popen[str]] = {}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            python_stage("OCR", "ocr.py", item, "--engine", "tesseract", "--langs", ocr_languages)
        )
    if action in {"manifest", "all"}:
        stages.append(python_stage("IIIF manifest", "manifest.py", item))
    if action in {"index", "all"}:
        stages.append(python_stage("Solr index", "index.py", item, "--solr", SOLR_URL))
    return stages


def solr_document_count(item_id: str) -> int | None:
    try:
        response = requests.get(
            f"{SOLR_URL}/select",
            params={"q": f'item_id:"{item_id}"', "rows": 0, "wt": "json"},
            timeout=2,
        )
        response.raise_for_status()
        return int(response.json()["response"]["numFound"])
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None


def item_summary(path: Path) -> dict[str, Any]:
    metadata_path = path / "metadata.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        metadata = {"id": path.name, "title": path.name}
    access_pages = len(list((path / "access").glob("page-*.jpg")))
    ocr_pages = len(list((path / "ocr").glob("page-*.alto.xml")))
    return {
        **metadata,
        "access_pages": access_pages,
        "ocr_pages": ocr_pages,
        "has_manifest": (path / "iiif" / "manifest.json").exists(),
        "indexed_pages": solr_document_count(path.name),
    }


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
        "metadata": {"ok": True, "provider": "local", "detail": "PDF metadata + opening-page OCR"},
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
    items = [item_summary(path) for path in ITEMS_DIR.iterdir() if path.is_dir()]
    return sorted(items, key=lambda item: item.get("ingested", ""), reverse=True)


@app.get("/api/items/{item_id}")
def read_item(item_id: str) -> dict[str, Any]:
    path = ITEMS_DIR / item_id
    if not path.is_dir():
        raise HTTPException(status_code=404, detail="Item not found")
    return item_summary(path)


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
