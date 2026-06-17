"""De-anonymization (reverse) endpoint."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from ..engine.deanonymizer import deanonymize, deanonymize_filename

router = APIRouter(prefix="/api", tags=["deanonymize"])

_file_store: dict[str, tuple[bytes, str, str]] = {}


@router.post("/deanonymize")
async def deanonymize_endpoint(
    file: UploadFile = File(...),
    mapping_file: UploadFile = File(...),
):
    """Reverse anonymization using a mapping file."""
    file_bytes = await file.read()
    mapping_bytes = await mapping_file.read()

    filename = file.filename or "restored_file"

    # Determine file type
    if filename.lower().endswith(".docx"):
        file_type = "docx"
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif filename.lower().endswith(".pptx"):
        file_type = "pptx"
        content_type = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    else:
        raise HTTPException(400, "Format non supporté. Utilisez .docx ou .pptx")

    try:
        mapping = json.loads(mapping_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "Fichier de mapping JSON invalide")

    result_bytes = deanonymize(file_bytes, file_type, mapping)

    # Store for download. Restore placeholders in the title too (the body is
    # already de-anonymised above) and prefix with "restaure_".
    result_id = str(uuid.uuid4())
    restored_name = f"restaure_{deanonymize_filename(filename, mapping)}"

    _file_store[result_id] = (result_bytes, restored_name, content_type)

    return {"file_id": result_id, "filename": restored_name}


@router.get("/download-restored/{file_id}")
async def download_restored(file_id: str):
    """Download a restored file."""
    if file_id not in _file_store:
        raise HTTPException(404, "Fichier non trouvé ou expiré")

    data, filename, content_type = _file_store[file_id]
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
