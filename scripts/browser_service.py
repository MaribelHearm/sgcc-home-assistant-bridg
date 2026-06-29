#!/usr/bin/env python3
"""Small HTTP manager for on-demand official Google Chrome sidecar.

The app container attaches to Chrome through CDP. This process owns the Chrome
lifecycle so the heavy browser is only running during a fetch/login check.
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from urllib.request import urlopen

HOST = os.getenv("SGCC_BROWSER_SERVICE_HOST", "0.0.0.0")
PORT = int(os.getenv("SGCC_BROWSER_SERVICE_PORT", "39222"))
CDP_HOST = os.getenv("SGCC_BROWSER_CDP_HOST", "0.0.0.0")
CDP_PORT = int(os.getenv("SGCC_BROWSER_CDP_PORT", "9222"))
PROFILE_DIR = os.getenv("SGCC_BROWSER_PROFILE", "/data/chrome-profile")
HOME_URL = os.getenv("SGCC_BROWSER_HOME_URL", "https://95598.cn/osgweb/login")
CHROME_BIN = os.getenv("SGCC_CHROME_BIN") or shutil.which("google-chrome") or shutil.which("google-chrome-stable") or "/usr/bin/google-chrome"
DISPLAY = os.getenv("DISPLAY", ":99")
LANG = os.getenv("BROWSER_LANGUAGE", "zh-CN")
WINDOW_SIZE = os.getenv("BROWSER_WINDOW_SIZE", "1280,900")
START_TIMEOUT = float(os.getenv("SGCC_BROWSER_START_TIMEOUT", "60"))

_state_lock = threading.RLock()
_proc: subprocess.Popen | None = None
_last_started_at: float | None = None
_last_stopped_at: float | None = None
_last_error: str = ""


def _cdp_probe_host() -> str:
    # Chrome listens on 0.0.0.0 for the peer app container, but local probes must
    # use loopback inside the sidecar container.
    if CDP_HOST in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return CDP_HOST


def _is_running() -> bool:
    return _proc is not None and _proc.poll() is None


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _ready() -> bool:
    if not _is_running():
        return False
    try:
        with socket.create_connection((_cdp_probe_host(), CDP_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _wait_ready(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ready():
            return True
        if _proc is not None and _proc.poll() is not None:
            return False
        time.sleep(0.5)
    return False


def _clear_profile_locks() -> None:
    os.makedirs(PROFILE_DIR, exist_ok=True)
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            os.unlink(os.path.join(PROFILE_DIR, name))
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"warn: remove profile lock {name} failed: {exc}", flush=True)


def _start_chrome() -> dict:
    global _proc, _last_started_at, _last_error
    with _state_lock:
        if _ready():
            return _status_payload()
        if _proc is not None and _proc.poll() is None:
            # A previous Chrome process exists but CDP is not reachable. Do not
            # start a second Chrome on the same profile/port.
            _proc.terminate()
            try:
                _proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _proc.kill()
                _proc.wait(timeout=10)
            _proc = None
        if _proc is not None and _proc.poll() is not None:
            _proc = None
        _clear_profile_locks()
        env = os.environ.copy()
        env["DISPLAY"] = DISPLAY
        env.setdefault("LANG", "C.UTF-8")
        env.setdefault("LC_ALL", "C.UTF-8")
        args = [
            CHROME_BIN,
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-address={CDP_HOST}",
            f"--remote-debugging-port={CDP_PORT}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-sandbox",
            f"--lang={LANG}",
            f"--window-size={WINDOW_SIZE}",
            HOME_URL,
        ]
        print("starting chrome: " + " ".join(args), flush=True)
        try:
            _proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            _last_started_at = time.time()
            _last_error = ""
        except Exception as exc:
            _proc = None
            _last_error = str(exc)
            raise
        if not _wait_ready(START_TIMEOUT):
            code = _proc.poll() if _proc is not None else None
            _last_error = f"chrome CDP did not become ready, exit_code={code}"
            raise RuntimeError(_last_error)
        return _status_payload()


def _stop_chrome() -> dict:
    global _proc, _last_stopped_at
    with _state_lock:
        proc = _proc
        if proc is not None and proc.poll() is None:
            print(f"stopping chrome pid={proc.pid}", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        _proc = None
        _last_stopped_at = time.time()
        return _status_payload()


def _status_payload() -> dict:
    proc = _proc
    running = proc is not None and proc.poll() is None
    return {
        "running": running,
        "ready": _ready() if running else False,
        "pid": proc.pid if running else None,
        "exit_code": None if proc is None or running else proc.poll(),
        "chrome_bin": CHROME_BIN,
        "profile_dir": PROFILE_DIR,
        "display": DISPLAY,
        "cdp_url": f"http://{CDP_HOST}:{CDP_PORT}",
        "last_started_at": _last_started_at,
        "last_stopped_at": _last_stopped_at,
        "last_error": _last_error,
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.client_address[0]} - {fmt % args}", flush=True)

    def do_GET(self):
        if self.path in {"/health", "/status"}:
            _json_response(self, 200, _status_payload())
            return
        if self.path == "/json/version":
            try:
                with urlopen(f"http://{_cdp_probe_host()}:{CDP_PORT}/json/version", timeout=2) as resp:
                    body = resp.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                _json_response(self, 503, {"error": str(exc), **_status_payload()})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self):
        try:
            if self.path == "/start":
                _json_response(self, 200, _start_chrome())
                return
            if self.path == "/stop":
                _json_response(self, 200, _stop_chrome())
                return
            _json_response(self, 404, {"error": "not found"})
        except Exception as exc:
            _json_response(self, 500, {"error": str(exc), **_status_payload()})


def _handle_signal(signum, frame):
    try:
        _stop_chrome()
    finally:
        raise SystemExit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    os.makedirs(PROFILE_DIR, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"sgcc browser service listening on {HOST}:{PORT}; chrome launches on demand", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
