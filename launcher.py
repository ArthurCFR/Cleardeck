"""
Cleardeck Windows launcher.

Sets up the user data directories (model cache + logs), starts the FastAPI
backend with uvicorn, waits until the port is reachable, and opens the
default browser. Designed to be packaged as a windowless exe via PyInstaller
(`--noconsole`), so all output goes to a log file.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path


APP_NAME = "Cleardeck"
HOST = "127.0.0.1"
PORT = 8001
URL = f"http://{HOST}:{PORT}"


def _user_data_dir() -> Path:
    """Return %LOCALAPPDATA%\\Cleardeck on Windows, ~/.cleardeck elsewhere."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _setup_directories() -> tuple[Path, Path]:
    """Create model + log directories. Returns (models_dir, logs_dir)."""
    root = _user_data_dir()
    models_dir = root / "models"
    logs_dir = root / "logs"
    models_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    return models_dir, logs_dir


def _setup_logging(logs_dir: Path) -> None:
    """Route stdout / stderr / logging to a rotating log file."""
    log_file = logs_dir / "cleardeck.log"
    handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(handler)

    # When running --noconsole, stdout/stderr point to NUL — redirect to the
    # log. Must expose enough of the file API for libraries (e.g. uvicorn,
    # transformers) that probe isatty(), encoding, etc.
    class _StreamToLogger:
        encoding = "utf-8"
        errors = "replace"
        mode = "w"
        closed = False

        def __init__(self, level: int) -> None:
            self.level = level
            self._buffer = ""

        def write(self, message: str) -> int:
            self._buffer += message
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    logging.log(self.level, line.rstrip())
            return len(message)

        def writelines(self, lines) -> None:
            for line in lines:
                self.write(line)

        def flush(self) -> None:
            if self._buffer.strip():
                logging.log(self.level, self._buffer.rstrip())
            self._buffer = ""

        def isatty(self) -> bool:
            return False

        def fileno(self) -> int:
            raise OSError("Stream has no underlying file descriptor")

        def readable(self) -> bool:
            return False

        def writable(self) -> bool:
            return True

        def seekable(self) -> bool:
            return False

        def close(self) -> None:
            self.flush()

    sys.stdout = _StreamToLogger(logging.INFO)
    sys.stderr = _StreamToLogger(logging.ERROR)


def _wait_for_port(host: str, port: int, timeout: float = 180.0) -> bool:
    """Block until the TCP port accepts connections, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _open_browser_when_ready() -> None:
    """Run in a thread: wait for the server, then open the browser."""
    if _wait_for_port(HOST, PORT, timeout=180.0):
        logging.info("Server reachable, opening browser at %s", URL)
        try:
            webbrowser.open(URL)
        except Exception as e:
            logging.error("Failed to open browser: %s", e)
    else:
        logging.error("Server did not start within timeout, browser not opened")


def main() -> int:
    models_dir, logs_dir = _setup_directories()

    # IMPORTANT: must be set before transformers / huggingface_hub are imported.
    os.environ.setdefault("HF_HOME", str(models_dir))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(models_dir))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    # Keep user projects OUTSIDE the install directory so they survive
    # uninstall/upgrade (Inno Setup deletes {app} on uninstall).
    os.environ.setdefault("CLEARDECK_DATA_DIR", str(_user_data_dir()))

    _setup_logging(logs_dir)
    logging.info("%s launcher starting", APP_NAME)
    logging.info("User data dir: %s", _user_data_dir())

    # Defer heavy imports so HF_HOME above is honoured. In a PyInstaller
    # bundle these can take 30-90 seconds the first time (transformers walks
    # its module tree on disk), so we start the browser thread AFTER imports
    # are done — otherwise the wait_for_port timeout would fire while imports
    # are still running and the browser would never open.
    import uvicorn
    from backend.main import app

    logging.info("Imports complete, starting server")
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    try:
        # log_config=None: skip uvicorn's stdout-aware ColourizedFormatter
        # (it crashes on our _StreamToLogger). Uvicorn's loggers still flow
        # to the root logger and end up in cleardeck.log.
        uvicorn.run(app, host=HOST, port=PORT, log_level="info", log_config=None)
    except KeyboardInterrupt:
        logging.info("Shutdown requested by user")
    except Exception as e:
        logging.exception("Fatal error in uvicorn: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
