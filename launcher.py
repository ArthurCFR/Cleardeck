"""
Cleardeck Windows launcher.

Sets up the user data directories (model cache + logs), starts the FastAPI
backend with uvicorn in a background thread, waits until the port is
reachable, then opens the app inside a native desktop window (pywebview /
Edge WebView2). Falls back to the default browser if the window can't be
created. Designed to be packaged as a windowless exe via PyInstaller
(`--noconsole`), so all output goes to a log file.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
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


def _open_url(url: str) -> bool:
    """Open URL in the default browser. Tries multiple strategies and logs
    which one succeeded, because the obvious choices (webbrowser.open,
    os.startfile) silently fail in PyInstaller --noconsole bundles on
    Windows 11 when the default browser is a UWP app like Edge."""
    if sys.platform == "win32":
        # Strategy 1: cmd /c start — the canonical Windows way, works for
        # both classic Win32 browsers and UWP/Store apps (Edge), and the
        # CREATE_NO_WINDOW flag keeps the cmd console hidden.
        try:
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                ["cmd", "/c", "start", "", url],
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
            logging.info("Browser launch attempted via cmd start")
            return True
        except Exception as e:
            logging.warning("cmd start failed: %s", e)

        # Strategy 2: rundll32 url.dll — bypasses shell associations.
        try:
            subprocess.Popen(
                ["rundll32.exe", "url.dll,FileProtocolHandler", url],
                creationflags=0x08000000,
                close_fds=True,
            )
            logging.info("Browser launch attempted via rundll32")
            return True
        except Exception as e:
            logging.warning("rundll32 failed: %s", e)

        # Strategy 3: direct ShellExecuteW (Win32 API).
        try:
            import ctypes
            rc = ctypes.windll.shell32.ShellExecuteW(None, "open", url, None, None, 1)
            if rc > 32:
                logging.info("Browser launch attempted via ShellExecuteW")
                return True
            logging.warning("ShellExecuteW returned %s", rc)
        except Exception as e:
            logging.warning("ShellExecuteW failed: %s", e)

        # Strategy 4: os.startfile (works for classic browsers).
        try:
            os.startfile(url)
            logging.info("Browser launch attempted via os.startfile")
            return True
        except OSError as e:
            logging.warning("os.startfile failed: %s", e)

    # Non-Windows or all Windows strategies failed: try webbrowser.
    try:
        if webbrowser.open(url):
            logging.info("Browser launch attempted via webbrowser.open")
            return True
        logging.warning("webbrowser.open returned False")
    except Exception as e:
        logging.warning("webbrowser.open raised: %s", e)

    return False


class _JsApi:
    """Bridge exposed to the frontend as ``window.pywebview.api``.

    The Edge WebView2 control has no built-in download UI, so the browser's
    ``<a download>`` trick silently no-ops inside the native window — clicking
    a download button did nothing. The frontend instead calls ``save_file``,
    which fetches the file from the local server and writes it to a location
    the user picks via a native "Save As" dialog.
    """

    def save_file(self, params: dict) -> dict:
        import urllib.request
        import webview

        params = params or {}
        url_path = params.get("url") or ""
        suggested = params.get("filename") or ""
        if not url_path:
            return {"ok": False, "error": "missing url"}

        full_url = f"{URL}{url_path}" if url_path.startswith("/") else url_path
        try:
            with urllib.request.urlopen(full_url) as resp:
                data = resp.read()
                if not suggested:
                    cd = resp.headers.get("Content-Disposition", "") or ""
                    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
                    if m:
                        suggested = m.group(1)

            window = webview.windows[0]
            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=suggested or "cleardeck_download",
            )
            if not result:
                return {"ok": False, "cancelled": True}

            # create_file_dialog returns a str on some backends, a tuple on others.
            path = result if isinstance(result, str) else result[0]
            with open(path, "wb") as f:
                f.write(data)
            logging.info("Saved download to %s", path)
            return {"ok": True, "path": str(path)}
        except Exception as e:  # pragma: no cover — surfaced to the user via JS
            logging.exception("save_file failed: %s", e)
            return {"ok": False, "error": str(e)}


def _run_server() -> None:
    """Run uvicorn in a background thread (daemon, dies with the process)."""
    import uvicorn
    from backend.main import app

    try:
        # log_config=None: skip uvicorn's stdout-aware ColourizedFormatter
        # (it crashes on our _StreamToLogger). Uvicorn's loggers still flow
        # to the root logger and end up in cleardeck.log.
        uvicorn.run(app, host=HOST, port=PORT, log_level="info", log_config=None)
    except Exception as e:  # pragma: no cover — surfaced in the log file
        logging.exception("Fatal error in uvicorn: %s", e)


def _open_in_browser_and_block() -> int:
    """Fallback path: open the system browser and keep the process (and thus
    the daemon server thread) alive until the user kills it."""
    logging.info("Falling back to the system browser at %s", URL)
    if not _open_url(URL):
        logging.error(
            "Could not open the browser automatically. "
            "Open %s manually in your browser.", URL,
        )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logging.info("Shutdown requested by user")
    return 0


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

    # Server runs in a daemon thread; the main thread is reserved for the
    # native window. pywebview MUST run on the main thread on Windows/macOS.
    threading.Thread(target=_run_server, daemon=True).start()

    if not _wait_for_port(HOST, PORT, timeout=180.0):
        logging.error("Server did not start within timeout")
        return 1

    logging.info("Server reachable, opening application window")
    try:
        import webview

        webview.create_window(
            APP_NAME,
            URL,
            width=1280,
            height=860,
            min_size=(960, 640),
            js_api=_JsApi(),
        )
        # Blocking call — returns when the user closes the window, after
        # which main() returns and the daemon server thread is torn down.
        webview.start()
        logging.info("Application window closed, shutting down")
        return 0
    except Exception as e:
        logging.exception("Could not open native window (%s)", e)
        return _open_in_browser_and_block()


if __name__ == "__main__":
    sys.exit(main())
