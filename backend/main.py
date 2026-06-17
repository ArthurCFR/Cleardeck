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

# Download progress (0-100), polled by the install modal. CamemBERT-NER weighs
# ~441 Mo on disk; the actual bytes land in the HF cache "blobs/" dir while
# downloading, so we poll that directory's size against this known total. It is
# an estimate (capped at 99% until the model is fully loaded), good enough to
# drive a progress bar without hooking into huggingface_hub's internals.
_MODEL_TOTAL_BYTES = 441_000_000
_MODEL_REPO_DIR = "models--Jean-Baptiste--camembert-ner"
_model_progress = 0.0


def _model_blobs_dir() -> Path:
    """Locate the HF cache 'blobs' dir for CamemBERT-NER (download target)."""
    base = (
        os.environ.get("HF_HOME")
        or os.environ.get("TRANSFORMERS_CACHE")
        or str(Path.home() / ".cache" / "huggingface")
    )
    return Path(base) / "hub" / _MODEL_REPO_DIR / "blobs"


def _dir_size(path: Path) -> int:
    """Total size in bytes of all files under path (0 if absent)."""
    total = 0
    try:
        for entry in path.iterdir():
            try:
                total += entry.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def _poll_progress(stop: threading.Event) -> None:
    """While downloading, reflect the blobs/ size as a 0-99% progress value."""
    global _model_progress
    while not stop.is_set():
        size = _dir_size(_model_blobs_dir())
        _model_progress = min(99.0, size / _MODEL_TOTAL_BYTES * 100)
        stop.wait(0.4)

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
    global _model_error, _model_installing, _model_progress
    stop = threading.Event()
    threading.Thread(target=_poll_progress, args=(stop,), daemon=True).start()
    try:
        from .engine.ai_detector import get_pipeline
        get_pipeline()
        _model_progress = 100.0
        _model_ready.set()
    except Exception as e:  # pragma: no cover — surfaced via /api/health
        _model_error = str(e)
    finally:
        stop.set()
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
        "progress": round(100.0 if _model_ready.is_set() else _model_progress),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
