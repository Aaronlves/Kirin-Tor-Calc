"""Loopback-only HTTP server for the Kirin Tor browser workbench."""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .diagnostics import author_error_payload
from .errors import KTError, ParameterError
from .workbench import Workbench


MAX_REQUEST_BYTES = 16 * 1024 * 1024
ASSET_ROOT = Path(__file__).resolve().parent / "web_assets"


class WorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, workbench: Workbench, token: str):
        self.workbench = workbench
        self.token = token
        super().__init__(address, WorkbenchRequestHandler)


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    server: WorkbenchHTTPServer

    def log_message(self, format: str, *args) -> None:  # pragma: no cover - quiet product server
        return

    @property
    def _origin(self) -> str:
        host, port = self.server.server_address[:2]
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{display_host}:{port}"

    def _security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            # CodeMirror mounts its generated base and theme CSS at runtime. CSS-only inline
            # styles are allowed; scripts remain restricted to packaged same-origin assets.
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )

    def _send_json(self, payload: object, status: int = HTTPStatus.OK) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _send_bytes(self, data: bytes, media_type: str, status: int = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _authorized(self) -> bool:
        if not self._host_allowed():
            return False
        supplied = self.headers.get("X-Kirin-Token", "")
        if not secrets.compare_digest(supplied, self.server.token):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {
            self._origin,
            self._origin.replace("127.0.0.1", "localhost"),
        }:
            return False
        return True

    def _require_api_auth(self) -> bool:
        if self._authorized():
            return True
        self._send_json(
            {"status": "error", "code": "unauthorized", "message": "invalid local workbench session"},
            HTTPStatus.FORBIDDEN,
        )
        return False

    def _read_json(self) -> dict:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise ParameterError("invalid request content length") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ParameterError("request body is empty or too large")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParameterError("request body must be UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ParameterError("request body must be a JSON object")
        return payload

    def _handle_error(self, exc: Exception) -> None:
        if isinstance(exc, KTError):
            self._send_json(
                author_error_payload(exc, self.server.workbench.root),
                HTTPStatus.BAD_REQUEST,
            )
        else:
            self._send_json(
                {"status": "error", "code": "internal_operation_error", "message": str(exc)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/":
                self._serve_asset("index.html")
                return
            if parsed.path.startswith("/assets/"):
                self._serve_asset(parsed.path.removeprefix("/assets/"))
                return
            if not parsed.path.startswith("/api/") or not self._require_api_auth():
                if not parsed.path.startswith("/api/"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/api/bootstrap":
                self._send_json(self.server.workbench.bootstrap())
            elif parsed.path == "/api/document":
                self._send_json(self.server.workbench.read_document(query.get("key", [""])[0]))
            elif parsed.path == "/api/artifact":
                path, media = self.server.workbench.artifact(query.get("path", [""])[0])
                self._send_bytes(path.read_bytes(), media)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:  # product boundary translates all failures
            self._handle_error(exc)

    def _serve_asset(self, relative: str) -> None:
        path = (ASSET_ROOT / relative).resolve()
        try:
            path.relative_to(ASSET_ROOT)
        except ValueError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in {".js", ".css", ".html"}:
            media += "; charset=utf-8"
        self._send_bytes(path.read_bytes(), media)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/") or not self._require_api_auth():
            if not parsed.path.startswith("/api/"):
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            overlays = payload.get("overlays")
            if parsed.path == "/api/validate":
                result = self.server.workbench.validate(overlays)
            elif parsed.path == "/api/save":
                result = self.server.workbench.save(overlays or {}, payload.get("expected"))
            elif parsed.path == "/api/document/create":
                result = self.server.workbench.create_document(
                    str(payload.get("template", "")), str(payload.get("document_id", ""))
                )
            elif parsed.path == "/api/completions":
                result = self.server.workbench.completions(
                    str(payload.get("key", "")), str(payload.get("prefix", "")), overlays
                )
            elif parsed.path == "/api/authoring":
                result = self.server.workbench.authoring_action(
                    str(payload.get("action", "")), payload.get("payload"), overlays
                )
            elif parsed.path == "/api/recovery":
                result = self.server.workbench.save_recovery(payload.get("drafts"))
            elif parsed.path == "/api/operation":
                result = self.server.workbench.execute(
                    str(payload.get("operation", "")), payload.get("payload"), overlays
                )
            elif parsed.path == "/api/package":
                result = self.server.workbench.package_action(
                    str(payload.get("action", "")), payload.get("payload")
                )
            elif parsed.path == "/api/template":
                result = self.server.workbench.template_action(
                    str(payload.get("action", "")), payload.get("payload")
                )
            elif parsed.path == "/api/workspace/init":
                result = Workbench.initialize_workspace(str(payload.get("path", "")))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            status = (
                HTTPStatus.OK
                if parsed.path == "/api/validate"
                or not isinstance(result, dict)
                or result.get("status") != "error"
                else HTTPStatus.BAD_REQUEST
            )
            self._send_json(result, status)
        except Exception as exc:  # product boundary translates all failures
            self._handle_error(exc)


def create_web_server(root: Path, host: str = "127.0.0.1", port: int = 0) -> WorkbenchHTTPServer:
    """Create a loopback workbench server without starting its request loop."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ParameterError("the Kirin web workbench may only listen on a loopback address")
    if port < 0 or port > 65535:
        raise ParameterError("port must be between 0 and 65535")
    return WorkbenchHTTPServer((host, port), Workbench(root), secrets.token_urlsafe(32))


def run_web(
    root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    initial_document: Optional[Path] = None,
) -> None:
    """Run the local browser workbench until interrupted."""
    server = create_web_server(root, host, port)
    address_host, address_port = server.server_address[:2]
    display_host = "127.0.0.1" if address_host in {"0.0.0.0", "::"} else address_host
    base_url = f"http://{display_host}:{address_port}"
    query = {"token": server.token}
    if initial_document is not None:
        query["document"] = initial_document.resolve().relative_to(
            server.workbench.root
        ).as_posix()
    launch_url = f"{base_url}/?{urllib.parse.urlencode(query)}"
    print("Kirin Tor 图形工作台已启动")
    print(f"工作区：{server.workbench.root}")
    print(f"地址：{base_url}")
    print("按 Ctrl+C 停止")
    should_open = open_browser and not any(
        os.environ.get(name) for name in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")
    )
    if should_open:
        threading.Timer(0.15, lambda: webbrowser.open(launch_url)).start()
    else:
        print(f"打开：{launch_url}")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
