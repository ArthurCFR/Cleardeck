"""CRUD endpoints for client profiles.

A client is intentionally simple: a name + a flat list of sensitive terms
(people, companies, project code names, …). Those terms are injected into the
"manual identification" list on the anonymize page in one click.
"""

from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, HTTPException

from ..config import get_projects_dir

router = APIRouter(prefix="/api/projects", tags=["clients"])

PROJECTS_DIR = get_projects_dir()


def _ensure_dir():
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    for chars, repl in (("àâäã", "a"), ("éèêë", "e"), ("îï", "i"),
                        ("ôö", "o"), ("ùûü", "u"), ("ç", "c")):
        text = re.sub(f"[{chars}]", repl, text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "client"


def _load(path) -> dict:
    """Read a client file, tolerating the legacy project format."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if "terms" not in data:
        # Legacy "project" files stored entities by category — flatten them.
        terms: list[str] = []
        for vals in (data.get("entities") or {}).values():
            terms.extend(vals)
        data["terms"] = terms
    if not data.get("name"):
        data["name"] = data.get("client") or data.get("id", "")
    return data


def _dedupe(terms) -> list[str]:
    seen, out = set(), []
    for t in terms:
        if not isinstance(t, str):
            continue
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


@router.get("")
async def list_clients():
    """List all saved clients."""
    _ensure_dir()
    clients = []
    for f in sorted(PROJECTS_DIR.glob("*.json")):
        data = _load(f)
        clients.append({
            "id": data["id"],
            "name": data["name"],
            "term_count": len(data.get("terms", [])),
        })
    return clients


@router.get("/{client_id}")
async def get_client(client_id: str):
    """Get a single client by ID."""
    _ensure_dir()
    path = PROJECTS_DIR / f"{client_id}.json"
    if not path.exists():
        raise HTTPException(404, "Client non trouvé")
    data = _load(path)
    return {"id": data["id"], "name": data["name"], "terms": data.get("terms", [])}


@router.post("/save")
async def save_client(req: dict):
    """Create or update a client (name + flat list of terms)."""
    _ensure_dir()
    name = (req.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nom du client requis")

    terms = _dedupe(req.get("terms") or [])
    client_id = req.get("id") or _slugify(name)
    data = {
        "id": client_id,
        "name": name,
        "terms": terms,
        "created_at": datetime.now().isoformat(),
    }
    (PROJECTS_DIR / f"{client_id}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


@router.delete("/{client_id}")
async def delete_client(client_id: str):
    """Delete a client."""
    _ensure_dir()
    path = PROJECTS_DIR / f"{client_id}.json"
    if not path.exists():
        raise HTTPException(404, "Client non trouvé")
    path.unlink()
    return {"status": "deleted"}
