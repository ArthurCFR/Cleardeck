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
_model_installing = False
_install_lock = threading.Lock()

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


def _load_model() -> None:
    """Download / load CamemBERT-NER. On first ever launch this downloads
    ~400 Mo; afterwards it just loads the cached model into memory. Triggered
    by POST /api/install-model; progress is exposed via /api/health."""
    global _model_error, _model_installing
    try:
        from .engine.ai_detector import get_pipeline
        get_pipeline()
        _model_ready.set()
    except Exception as e:  # pragma: no cover — surfaced via /api/health
        _model_error = str(e)
    finally:
        _model_installing = False


def _start_install() -> str:
    """Idempotently kick off model loading in the background.

    Returns "ready" if already loaded, otherwise "installing". Safe to call
    repeatedly (e.g. health polling races) — the lock guarantees a single
    loader thread.
    """
    global _model_installing, _model_error
    if _model_ready.is_set():
        return "ready"
    with _install_lock:
        if _model_installing:
            return "installing"
        _model_installing = True
        _model_error = None  # clear any previous failure so a retry is clean
        threading.Thread(target=_load_model, daemon=True).start()
    return "installing"


@app.post("/api/install-model")
async def install_model() -> dict:
    """Start loading the NER model on demand (driven by the install modal)."""
    return {"status": _start_install()}


@app.get("/api/health")
async def health() -> dict:
    """Report model status (used by the frontend install modal on load)."""
    return {
        "model_ready": _model_ready.is_set(),
        "model_error": _model_error,
        "installing": _model_installing,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
