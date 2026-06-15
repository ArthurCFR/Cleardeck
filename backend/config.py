"""Runtime configuration helpers.

In packaged (PyInstaller) mode, user-writable data must live OUTSIDE the
install directory so it survives uninstall and upgrade. The launcher
exports CLEARDECK_DATA_DIR for that purpose. In dev mode (running uvicorn
directly), we fall back to data/ at the repo root.
"""

from __future__ import annotations

import os
from pathlib import Path


def _user_data_root() -> Path:
    """Resolve the directory used for persistent user data."""
    env_dir = os.environ.get("CLEARDECK_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    # Dev fallback: <repo>/data/ — backend/ is two parents up from this file.
    return Path(__file__).resolve().parent.parent / "data"


def get_projects_dir() -> Path:
    """Return (and create) the directory where project JSON files live."""
    path = _user_data_root() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path
