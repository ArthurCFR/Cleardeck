"""
ClearDeck V2 — FastAPI application entry point.

Uses CamemBERT-NER for AI-powered entity detection.
Serves both the API and the static frontend.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routers import projects, anonymize, deanonymize

_model_ready = threading.Event()
_model_error: str | None = None

# Load .env file
_root = Path(__file__).resolve().parent.parent
load_dotenv(_root / ".env")

app = FastAPI(
    title="ClearDeck V2",
    description="Anonymisation locale de documents professionnels — moteur GLiNER",
    version="2.0.0",
)

# Register API routers
app.include_router(projects.router)
app.include_router(anonymize.router)
app.include_router(deanonymize.router)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.get("/")
async def serve_index():
    """Serve the main SPA page."""
    return FileResponse(FRONTEND_DIR / "index.html")


# Mount static files (CSS, JS) — must be after the root route
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


def _load_model_async() -> None:
    """Download / load CamemBERT-NER in the background so the server can
    accept requests immediately. Status is exposed via /api/health."""
    global _model_error
    try:
        from .engine.ai_detector import get_pipeline
        get_pipeline()
        _model_ready.set()
    except Exception as e:  # pragma: no cover — surfaced via /api/health
        _model_error = str(e)


@app.on_event("startup")
async def startup() -> None:
    threading.Thread(target=_load_model_async, daemon=True).start()


@app.get("/api/health")
async def health() -> dict:
    """Report whether the NER model is ready (used by the frontend on load)."""
    return {
        "model_ready": _model_ready.is_set(),
        "model_error": _model_error,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
