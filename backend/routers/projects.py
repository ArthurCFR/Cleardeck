"""CRUD endpoints for project profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File

from ..config import get_projects_dir
from ..models.schemas import ProjectCreate, ProjectEntitiesUpdate, SeedEntitiesRequest
from ..services.project_setup import build_project_data, seed_entities
from ..engine.image_handler import compute_phash

router = APIRouter(prefix="/api/projects", tags=["projects"])

PROJECTS_DIR = get_projects_dir()


def _ensure_dir():
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


@router.get("")
async def list_projects():
    """List all saved projects."""
    _ensure_dir()
    projects = []
    for f in sorted(PROJECTS_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        entity_count = sum(len(v) for v in data.get("entities", {}).values())
        projects.append({
            "id": data["id"],
            "name": data["name"],
            "client": data["client"],
            "created_at": data.get("created_at", ""),
            "entity_count": entity_count,
            "logo_count": len(data.get("logo_hashes", [])),
            "logo_thumbnail": data.get("logo_thumbnail", ""),
        })
    return projects


@router.get("/{project_id}")
async def get_project(project_id: str):
    """Get a single project by ID."""
    _ensure_dir()
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        raise HTTPException(404, "Projet non trouvé")
    return json.loads(path.read_text(encoding="utf-8"))


@router.post("")
async def create_project(req: ProjectCreate):
    """Create a new project (without entities — call generate separately)."""
    _ensure_dir()
    data = build_project_data(req.name, req.client, {
        "entreprises": [],
        "personnes": [],
        "lieux": [],
        "autres": [],
    })
    path = PROJECTS_DIR / f"{data['id']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


@router.post("/seed-entities")
async def seed_entities_endpoint(req: SeedEntitiesRequest):
    """Pre-seed entity lists from manual user inputs (no external API call)."""
    entities = seed_entities(
        client_name=req.client,
        subsidiaries=req.subsidiaries,
        contacts=req.contacts,
    )
    return {"entities": entities}


@router.put("/{project_id}/entities")
async def update_entities(project_id: str, req: ProjectEntitiesUpdate):
    """Update the entity list for a project."""
    _ensure_dir()
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        raise HTTPException(404, "Projet non trouvé")

    data = json.loads(path.read_text(encoding="utf-8"))
    data["entities"] = req.entities
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


@router.post("/save")
async def save_project_with_entities(req: dict):
    """Save a complete project (with entities) in one call."""
    _ensure_dir()

    name = req.get("name", "")
    client = req.get("client", "")
    entities = req.get("entities", {})

    if not name or not client:
        raise HTTPException(400, "Nom du projet et nom du client requis")

    logo_hashes = req.get("logo_hashes", [])
    data = build_project_data(name, client, entities, logo_hashes)
    # Preserve extra fields
    for key in ["subsidiaries", "contacts", "notes", "logo_thumbnail"]:
        if key in req:
            data[key] = req[key]

    path = PROJECTS_DIR / f"{data['id']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


@router.post("/{project_id}/logos")
async def upload_logos(project_id: str, logos: List[UploadFile] = File(...)):
    """Upload logo images and compute their perceptual hashes.

    Accepts PNG/JPG files only (SVG not supported in V1).
    Returns the list of computed hashes.
    """
    _ensure_dir()
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        raise HTTPException(404, "Projet non trouve")

    data = json.loads(path.read_text(encoding="utf-8"))
    existing_hashes = data.get("logo_hashes", [])

    new_hashes = []
    for logo in logos:
        filename = logo.filename or ""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in ("png", "jpg", "jpeg"):
            raise HTTPException(400, f"Format non supporte : .{ext}. Utilisez PNG ou JPG.")

        logo_bytes = await logo.read()
        h = compute_phash(logo_bytes)
        if h not in existing_hashes:
            new_hashes.append(h)

    data["logo_hashes"] = existing_hashes + new_hashes
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"logo_hashes": data["logo_hashes"], "added": len(new_hashes)}


@router.post("/upload-logos")
async def upload_logos_standalone(logos: List[UploadFile] = File(...)):
    """Compute perceptual hashes for logo files without requiring a saved project.

    Used during project creation before the project is saved.
    Returns the list of computed hashes.
    """
    hashes = []
    for logo in logos:
        filename = logo.filename or ""
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext not in ("png", "jpg", "jpeg"):
            raise HTTPException(400, f"Format non supporte : .{ext}. Utilisez PNG ou JPG.")

        logo_bytes = await logo.read()
        h = compute_phash(logo_bytes)
        hashes.append(h)

    return {"logo_hashes": hashes}


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """Delete a project."""
    _ensure_dir()
    path = PROJECTS_DIR / f"{project_id}.json"
    if not path.exists():
        raise HTTPException(404, "Projet non trouvé")
    path.unlink()
    return {"status": "deleted"}
