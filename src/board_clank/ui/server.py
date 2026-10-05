"""Loopback GUI. Bind the selected socket first, then serve it."""

from __future__ import annotations

import json
import re
import socket
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from board_clank.paths import REPO_ROOT
from board_clank.ui.pages import about_page, activity_page, lead_page, leads_page, outcome_page, overview_page
from board_clank.ui.ports import LOOPBACK, PortOccupied, select_bound_socket
from board_clank.ui.receipt import clear_receipt, write_receipt
from board_clank.ui.service import ResearchSurface, SurfaceError, UiIdentity
from board_clank.ui.standards import PROTOTYPE_BASE_SHA, PROTOTYPE_BASE_TREE

_LEAD_ID = re.compile(r"^lead_[0-9a-f]{24}$")
BrowserOpener = Callable[[str], object]
Probe = Callable[[str, int], bool]


class LoopbackServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self, bound: socket.socket, handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(bound.getsockname(), handler, bind_and_activate=False)
        self.socket.close()
        self.socket = bound
        host, port = bound.getsockname()[:2]
        self.server_name = host
        self.server_port = port


class RunningUI:
    def __init__(self, server: LoopbackServer, thread: threading.Thread, receipt: Path, url: str, ready: bool) -> None:
        self.server = server
        self.thread = thread
        self.receipt = receipt
        self.url = url
        self.ready = ready
        self.host = server.server_name
        self.port = server.server_port

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        clear_receipt(self.receipt)


def git_identity(root: Path | None = None) -> tuple[str, str]:
    repo = root or REPO_ROOT

    def rev(spec: str) -> str:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", spec],
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return "UNKNOWN"
        if proc.returncode != 0:
            return "UNKNOWN"
        return proc.stdout.strip() or "UNKNOWN"

    return rev("HEAD"), rev("HEAD^{tree}")


def probe_ready(host: str, port: int, *, timeout: float = 3.0) -> bool:
    if host != LOOPBACK:
        return False
    deadline = time.monotonic() + timeout
    url = f"http://{host}:{port}/healthz"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.05)
    return False


def open_browser_when_ready(host: str, port: int, *, opener: BrowserOpener, probe: Probe) -> bool:
    if host != LOOPBACK or not probe(host, port):
        return False
    opener(f"http://{host}:{port}/")
    return True


def _handler(surface: ResearchSurface) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _html(self, status: int, page: str) -> None:
            self._send(status, page.encode("utf-8"), "text/html; charset=utf-8")

        def _json(self, payload: dict) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self._send(200, body, "application/json")

        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            identity = surface.identity
            try:
                if path == "/healthz":
                    self._json(surface.health())
                    return
                if path == "/":
                    self._html(200, overview_page(surface.overview()))
                    return
                if path == "/leads":
                    self._html(200, leads_page(surface.leads_by_queue("active"), identity, archive=False))
                    return
                if path == "/archive":
                    self._html(200, leads_page(surface.leads_by_queue("archive"), identity, archive=True))
                    return
                if path == "/activity":
                    self._html(200, activity_page(surface.activity(), identity))
                    return
                if path == "/about":
                    self._html(200, about_page(surface.overview()))
                    return
                if path.startswith("/leads/"):
                    lead_id = path.removeprefix("/leads/").strip("/")
                    if not _LEAD_ID.fullmatch(lead_id):
                        self._html(404, lead_page(None, identity))
                        return
                    self._html(200, lead_page(surface.lead(lead_id), identity))
                    return
            except SurfaceError as exc:
                self._html(409, outcome_page(identity, {"success": False, "committed": False, "action": "read", "message": "read not committed", "reason": exc.reason, "lead": None}))
                return
            self._html(404, outcome_page(identity, {"success": False, "committed": False, "action": "read", "message": "read not committed", "reason": "not_found", "lead": None}))

        def do_POST(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            identity = surface.identity
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
            form = urllib.parse.parse_qs(raw, keep_blank_values=True)
            try:
                if path == "/import":
                    jsonl = (form.get("jsonl") or [""])[0]
                    outcome = surface.import_candidates(jsonl)
                    self._html(200, outcome_page(identity, outcome))
                    return
                qualify = re.fullmatch(r"/leads/(lead_[0-9a-f]{24})/qualify", path)
                if qualify:
                    outcome = surface.qualify(qualify.group(1))
                    self._html(200, outcome_page(identity, outcome))
                    return
                reject = re.fullmatch(r"/leads/(lead_[0-9a-f]{24})/reject", path)
                if reject:
                    reason = (form.get("reason") or [""])[0]
                    outcome = surface.reject(reject.group(1), reason)
                    self._html(200, outcome_page(identity, outcome))
                    return
            except SurfaceError as exc:
                self._html(409, outcome_page(identity, {"success": False, "committed": False, "action": "mutate", "message": "mutate not committed", "reason": exc.reason, "lead": None}))
                return
            self._html(404, outcome_page(identity, {"success": False, "committed": False, "action": "mutate", "message": "mutate not committed", "reason": "not_found", "lead": None}))

        def do_PUT(self) -> None:  # noqa: N802
            self.send_error(405)

    return Handler


def start_ui(
    canonical_db: str | Path,
    research_db: str | Path,
    *,
    port: int | None = None,
    open_browser: bool = False,
    browser_opener: BrowserOpener | None = None,
    probe: Probe | None = None,
    runtime_dir: str | Path | None = None,
    app_sha: str | None = None,
    app_tree: str | None = None,
) -> RunningUI:
    sha = app_sha
    tree = app_tree
    if sha is None or tree is None:
        discovered_sha, discovered_tree = git_identity()
        sha = sha or discovered_sha
        tree = tree or discovered_tree
    if sha == PROTOTYPE_BASE_SHA and tree in {None, "", "UNKNOWN"}:
        tree = PROTOTYPE_BASE_TREE
    identity = UiIdentity(app_sha=sha or "UNKNOWN", app_tree=tree or "UNKNOWN")
    surface = ResearchSurface(canonical_db, research_db, identity)
    bound = select_bound_socket(port)
    host, selected = bound.getsockname()[:2]
    if host != LOOPBACK:
        bound.close()
        raise PortOccupied(selected, f"refusing non-loopback bind {host}")
    identity.bind_host = host
    identity.bind_port = int(selected)
    server = LoopbackServer(bound, _handler(surface))
    thread = threading.Thread(target=server.serve_forever, name="board-clank-ui", daemon=True)
    thread.start()
    ready = (probe or probe_ready)(host, int(selected))
    receipt_dir = Path(runtime_dir) if runtime_dir is not None else Path.cwd() / ".runtime"
    receipt = receipt_dir / "board-clank-ui.json"
    write_receipt(receipt, host=host, port=int(selected), app_sha=identity.app_sha)
    if open_browser and ready:
        open_browser_when_ready(
            host,
            int(selected),
            opener=browser_opener or webbrowser.open,
            probe=probe or probe_ready,
        )
    return RunningUI(server, thread, receipt, f"http://{host}:{selected}/", ready)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="board-clank ui")
    parser.add_argument("--db", required=True, help="Canonical Board database path")
    parser.add_argument("--research-db", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--runtime-dir")
    args = parser.parse_args(argv)
    if args.port == 0:
        print(json.dumps({"status": "refused", "reason": "explicit port 0 is not a selected port"}, sort_keys=True))
        return 2
    try:
        running = start_ui(
            args.db,
            args.research_db,
            port=args.port,
            open_browser=not args.no_browser,
            runtime_dir=args.runtime_dir,
        )
    except (PortOccupied, SurfaceError) as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}, indent=2, sort_keys=True))
        return 2
    if not running.ready:
        print(json.dumps({"status": "refused", "reason": "health check failed", "url": running.url}, indent=2, sort_keys=True))
        running.close()
        return 1
    print(json.dumps({
        "status": "serving",
        "url": running.url,
        "host": running.host,
        "port": running.port,
        "browser": not args.no_browser,
    }, indent=2, sort_keys=True))
    try:
        while running.thread.is_alive():
            running.thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        running.close()
    return 0
