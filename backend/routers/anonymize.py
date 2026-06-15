"""Upload, preview, and anonymize endpoints — V2 (CamemBERT-NER)."""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..config import get_projects_dir
from ..engine.anonymizer import preview, anonymize
from ..engine.image_handler import preview_images, apply_image_anonymization

router = APIRouter(prefix="/api", tags=["anonymize"])

# Temporary storage for processed files (in-memory for simplicity)
_file_store: dict[str, tuple[bytes, str, str]] = {}  # id -> (bytes, filename, content_type)

# Batch jobs registry (in-memory). Old jobs are evicted after BATCH_JOB_TTL.
_batch_jobs: dict[str, dict] = {}
_batch_jobs_lock = threading.Lock()
BATCH_MAX_FILES = 50
BATCH_JOB_TTL = 60 * 60  # 1 hour

PROJECTS_DIR = get_projects_dir()


def _get_file_type(filename: str) -> str:
    if filename.lower().endswith(".docx"):
        return "docx"
    elif filename.lower().endswith(".pptx"):
        return "pptx"
    else:
        raise HTTPException(400, "Format non supporté. Utilisez .docx ou .pptx")


def _load_project_entities(project_id: str | None) -> dict[str, list[str]] | None:
    if not project_id:
        return None
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        raise HTTPException(404, f"Projet '{project_id}' non trouvé")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("entities")


def _load_project_logo_hashes(project_id: str | None) -> list[str]:
    if not project_id:
        return []
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("logo_hashes", [])


@router.post("/preview")
async def preview_endpoint(
    file: UploadFile = File(...),
    project_id: str = Form(default=""),
    manual_entities: str = Form(default=""),
):
    """Preview entities that will be anonymized."""
    file_bytes = await file.read()
    file_type = _get_file_type(file.filename)

    # Load entities
    entities = None
    if project_id:
        entities = _load_project_entities(project_id)
    elif manual_entities:
        try:
            entities = json.loads(manual_entities)
        except json.JSONDecodeError:
            raise HTTPException(400, "Format JSON invalide pour les entités manuelles")

    result = preview(file_bytes, file_type, entities)
    return result


@router.post("/preview-images")
async def preview_images_endpoint(
    file: UploadFile = File(...),
    project_id: str = Form(default=""),
):
    """Preview images in a document and match against project logos."""
    file_bytes = await file.read()
    file_type = _get_file_type(file.filename)
    logo_hashes = _load_project_logo_hashes(project_id) if project_id else []
    result = preview_images(file_bytes, file_type, logo_hashes)
    return result


@router.post("/anonymize")
async def anonymize_endpoint(
    file: UploadFile = File(...),
    project_id: str = Form(default=""),
    manual_entities: str = Form(default=""),
    confirmed_ai: str = Form(default="[]"),
    image_remove_indices: str = Form(default="[]"),
):
    """Anonymize a file and return download IDs.

    V2: confirmed_ai replaces confirmed_fuzzy + confirmed_spacy.
    """
    file_bytes = await file.read()
    filename = file.filename
    file_type = _get_file_type(filename)

    # Load entities
    entities = None
    if project_id:
        entities = _load_project_entities(project_id)
    elif manual_entities:
        try:
            entities = json.loads(manual_entities)
        except json.JSONDecodeError:
            raise HTTPException(400, "Format JSON invalide")

    try:
        ai_ents = json.loads(confirmed_ai) if confirmed_ai else []
    except json.JSONDecodeError:
        ai_ents = []

    try:
        remove_indices = json.loads(image_remove_indices) if image_remove_indices else []
    except json.JSONDecodeError:
        remove_indices = []

    # Step 1: Apply image anonymization first (on original bytes)
    logo_hashes = _load_project_logo_hashes(project_id) if project_id else []
    if logo_hashes or remove_indices:
        file_bytes = apply_image_anonymization(
            file_bytes, file_type, logo_hashes, remove_indices
        )

    # Step 2: Apply text anonymization
    result_bytes, mapping, anon_name = anonymize(
        file_bytes=file_bytes,
        file_type=file_type,
        filename=filename,
        project_id=project_id or None,
        project_entities=entities,
        confirmed_ai=ai_ents,
    )

    # Store results for download
    anon_id = str(uuid.uuid4())
    mapping_id = str(uuid.uuid4())

    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if file_type == "docx"
        else "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    )

    anon_filename = f"anonymise_{anon_name}"
    _file_store[anon_id] = (result_bytes, anon_filename, content_type)
    _file_store[mapping_id] = (
        json.dumps(mapping, ensure_ascii=False, indent=2).encode("utf-8"),
        f"mapping_{filename.rsplit('.', 1)[0]}.json",
        "application/json",
    )

    return {
        "anon_file_id": anon_id,
        "mapping_file_id": mapping_id,
        "mapping": mapping,
    }


@router.get("/download/{file_id}")
async def download_file(file_id: str):
    """Download a processed file."""
    if file_id not in _file_store:
        raise HTTPException(404, "Fichier non trouvé ou expiré")

    data, filename, content_type = _file_store[file_id]
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================================
# Batch anonymization (up to BATCH_MAX_FILES at once, auto-confirm all
# detections, ZIP output with one mapping file per document).
# ============================================================================


def _evict_old_jobs() -> None:
    """Remove jobs older than BATCH_JOB_TTL to bound memory usage."""
    now = time.time()
    with _batch_jobs_lock:
        for jid in list(_batch_jobs.keys()):
            if now - _batch_jobs[jid].get("created_at", now) > BATCH_JOB_TTL:
                _batch_jobs.pop(jid, None)


def _run_batch_job(
    job_id: str,
    files: list[tuple[str, bytes]],
    project_id: str | None,
    project_entities: dict[str, list[str]] | None,
    logo_hashes: list[str],
) -> None:
    """Worker: anonymize each file and pack everything into an in-memory ZIP."""
    job = _batch_jobs[job_id]
    zip_buffer = io.BytesIO()

    try:
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, file_bytes in files:
                job["current_file"] = filename
                try:
                    file_type = _get_file_type(filename)
                except HTTPException:
                    job["skipped"].append(filename)
                    job["done"] += 1
                    continue

                try:
                    if logo_hashes:
                        file_bytes = apply_image_anonymization(
                            file_bytes, file_type, logo_hashes, []
                        )

                    # auto_confirm_all=True: detection + anonymisation in a
                    # single pass — avoids the double NER work that made the
                    # batch 2x slower than running each doc individually.
                    result_bytes, mapping, anon_name = anonymize(
                        file_bytes=file_bytes,
                        file_type=file_type,
                        filename=filename,
                        project_id=project_id,
                        project_entities=project_entities,
                        auto_confirm_all=True,
                    )

                    stem = filename.rsplit(".", 1)[0]
                    zf.writestr(f"anonymise_{anon_name}", result_bytes)
                    zf.writestr(
                        f"mapping_{stem}.json",
                        json.dumps(mapping, ensure_ascii=False, indent=2),
                    )
                except Exception as e:
                    job["errors"].append({"file": filename, "error": str(e)})

                job["done"] += 1

        job["zip_bytes"] = zip_buffer.getvalue()
        job["status"] = "completed"
        job["current_file"] = ""
    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)


@router.post("/anonymize-batch")
async def anonymize_batch_endpoint(
    files: List[UploadFile] = File(...),
    project_id: str = Form(default=""),
    manual_entities: str = Form(default=""),
):
    """Start a batch anonymization job. Returns a job_id for polling.

    All detected entities (regardless of confidence) are auto-confirmed —
    suitable for bulk processing. For nuanced triage use /anonymize per file.
    """
    _evict_old_jobs()

    if not files:
        raise HTTPException(400, "Aucun fichier fourni")
    if len(files) > BATCH_MAX_FILES:
        raise HTTPException(400, f"Maximum {BATCH_MAX_FILES} fichiers par lot")

    file_data: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        file_data.append((f.filename or "unknown", content))

    entities: dict[str, list[str]] | None = None
    if project_id:
        entities = _load_project_entities(project_id)
    elif manual_entities:
        try:
            entities = json.loads(manual_entities)
        except json.JSONDecodeError:
            raise HTTPException(400, "Format JSON invalide pour les entités manuelles")

    logo_hashes = _load_project_logo_hashes(project_id) if project_id else []

    job_id = str(uuid.uuid4())
    with _batch_jobs_lock:
        _batch_jobs[job_id] = {
            "status": "running",
            "done": 0,
            "total": len(file_data),
            "current_file": "",
            "zip_bytes": None,
            "error": None,
            "errors": [],     # per-file errors (didn't kill the run)
            "skipped": [],    # unsupported file types
            "created_at": time.time(),
        }

    threading.Thread(
        target=_run_batch_job,
        args=(job_id, file_data, project_id or None, entities, logo_hashes),
        daemon=True,
    ).start()

    return {"job_id": job_id, "total": len(file_data)}


@router.get("/batch-status/{job_id}")
async def batch_status(job_id: str):
    """Poll the progression of a batch job."""
    if job_id not in _batch_jobs:
        raise HTTPException(404, "Job non trouvé ou expiré")
    job = _batch_jobs[job_id]
    return {
        "status": job["status"],
        "done": job["done"],
        "total": job["total"],
        "current_file": job["current_file"],
        "error": job["error"],
        "file_errors": job["errors"],
        "skipped": job["skipped"],
    }


@router.get("/batch-download/{job_id}")
async def batch_download(job_id: str):
    """Download the completed batch as a ZIP archive."""
    if job_id not in _batch_jobs:
        raise HTTPException(404, "Job non trouvé ou expiré")
    job = _batch_jobs[job_id]
    if job["status"] != "completed":
        raise HTTPException(400, f"Job pas terminé (statut: {job['status']})")
    if not job["zip_bytes"]:
        raise HTTPException(500, "Archive ZIP indisponible")

    filename = f"cleardeck_batch_{job_id[:8]}.zip"
    return Response(
        content=job["zip_bytes"],
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
