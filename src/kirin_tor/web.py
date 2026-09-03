"""Loopback-only HTTP server for the Kirin Tor browser workbench."""

from __future__ import annotations

import json
import mimetypes
import multiprocessing as mp
import os
import queue
import secrets
import signal
import subprocess
import threading
import time
import urllib.parse
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from .diagnostics import author_error_payload
from .errors import KTError, ParameterError, WorkspaceError
from .workbench import Workbench
from .workbench_preferences import save_default_workspace
from .workspace import Workspace


MAX_REQUEST_BYTES = 16 * 1024 * 1024
ASSET_ROOT = Path(__file__).resolve().parent / "web_assets"


def _operation_job_entry(result_queue, root: str, operation: str, payload: dict, overlays: dict) -> None:
    if os.name == "posix":
        os.setsid()
    try:
        result_queue.put({"kind": "result", "result": Workbench(Path(root)).execute(operation, payload, overlays)})
    except KTError as exc:
        result_queue.put({"kind": "error", "error": author_error_payload(exc, Path(root))})
    except BaseException as exc:  # process boundary must serialize unexpected failures
        result_queue.put({
            "kind": "error",
            "error": {"status": "error", "code": "internal_operation_error", "message": str(exc)},
        })


class OperationJobManager:
    """Own cancellable workbench operation processes for the local web session."""

    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}

    def _prune(self) -> None:
        cutoff = time.monotonic() - 300
        expired = [job_id for job_id, job in self._jobs.items() if job.get("finished_at", float("inf")) < cutoff]
        for job_id in expired:
            job = self._jobs.pop(job_id)
            job["queue"].close()

    def start(self, operation: str, payload: object, overlays: object) -> dict:
        with self._lock:
            self._prune()
            running = sum(job["state"] in {"queued", "running"} for job in self._jobs.values())
            if running >= 8:
                raise ParameterError("too many workbench operations are already running")
            job_id = uuid.uuid4().hex
            context = mp.get_context("spawn" if os.name == "nt" else "fork")
            result_queue = context.Queue(maxsize=1)
            process = context.Process(
                target=_operation_job_entry,
                args=(
                    result_queue,
                    str(self.root),
                    operation,
                    dict(payload) if isinstance(payload, dict) else {},
                    dict(overlays) if isinstance(overlays, dict) else {},
                ),
                daemon=False,
            )
            process.start()
            self._jobs[job_id] = {
                "id": job_id,
                "operation": operation,
                "state": "running",
                "stage": "executing",
                "started_at": time.time(),
                "process": process,
                "queue": result_queue,
            }
            return self.status(job_id)

    def _finish_from_message(self, job: dict, message: dict) -> None:
        process = job["process"]
        process.join(timeout=0.2)
        job["state"] = "completed" if message.get("kind") == "result" else "failed"
        job["stage"] = job["state"]
        job["result"] = message.get("result")
        job["error"] = message.get("error")
        job["finished_at"] = time.monotonic()

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ParameterError(f"unknown operation job: {job_id}")
            if job["state"] == "running":
                message = None
                try:
                    message = job["queue"].get_nowait()
                except queue.Empty:
                    if not job["process"].is_alive():
                        try:
                            message = job["queue"].get(timeout=0.05)
                        except queue.Empty:
                            message = {
                                "kind": "error",
                                "error": {
                                    "status": "error",
                                    "code": "operation_worker_exit",
                                    "message": f"operation worker exited with code {job['process'].exitcode}",
                                },
                            }
                if message is not None:
                    self._finish_from_message(job, message)
            response = {
                "status": "ok",
                "job_id": job["id"],
                "operation": job["operation"],
                "state": job["state"],
                "stage": job["stage"],
                "started_at": job["started_at"],
                "cancellable": job["state"] == "running",
            }
            if job.get("result") is not None:
                response["result"] = job["result"]
            if job.get("error") is not None:
                response["error"] = job["error"]
            return response

    def _terminate(self, process) -> None:
        if not process.is_alive():
            return
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                process.terminate()
        else:  # terminate the job process and any mathematical worker it started
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=3,
            )
        process.join(timeout=1)
        if process.is_alive():
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    process.kill()
            else:
                process.kill()
            process.join(timeout=1)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise ParameterError(f"unknown operation job: {job_id}")
            if job["state"] == "running":
                self._terminate(job["process"])
                job["state"] = "cancelled"
                job["stage"] = "cancelled"
                job["finished_at"] = time.monotonic()
                job["error"] = {
                    "status": "error",
                    "code": "operation_cancelled",
                    "message": "operation was cancelled by the author",
                    "author_message": "操作已取消。",
                }
            return self.status(job_id)

    def has_running_jobs(self) -> bool:
        """Return whether a live operation still belongs to this workspace."""

        with self._lock:
            for job_id in list(self._jobs):
                self.status(job_id)
            return any(job["state"] in {"queued", "running"} for job in self._jobs.values())

    def close(self) -> None:
        with self._lock:
            for job in self._jobs.values():
                if job["state"] == "running":
                    self._terminate(job["process"])
                job["queue"].close()


class WorkbenchHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # The production frontend loads multiple code-split modules in parallel.
    # Python's default backlog of five can reset otherwise valid loopback
    # connections during startup or rapid reloads.
    request_queue_size = 128

    def __init__(
        self,
        address,
        workbench: Workbench,
        token: str,
        *,
        preference_home: Optional[Path] = None,
    ):
        self.workspace_lock = threading.RLock()
        self.workbench = workbench
        self.token = token
        self.safe_mode = workbench.plugins.safe_mode
        self.plugin_approval_home = workbench.plugins.approvals.home
        self.preference_home = preference_home
        self.operation_jobs = OperationJobManager(workbench.root)
        super().__init__(address, WorkbenchRequestHandler)

    def switch_workspace(self, path: str) -> dict:
        """Atomically replace the workspace owned by this authenticated session."""

        if not path.strip():
            raise ParameterError("workspace path must be non-empty")
        candidate = Path(path).expanduser().resolve()
        if not candidate.exists():
            raise WorkspaceError(f"workspace path does not exist: {candidate}")
        if candidate.is_file():
            if candidate.suffix.lower() != ".kirin":
                raise WorkspaceError(f"workspace source must be a .kirin file: {candidate}")
            candidate = candidate.parent
        elif not candidate.is_dir():
            raise WorkspaceError(f"workspace path must be a directory: {candidate}")
        root = Workspace.find_root(candidate)

        with self.workspace_lock:
            previous = self.workbench.root
            if root == previous:
                save_default_workspace(root, self.preference_home)
                return {
                    "status": "ok",
                    "workspace": str(root),
                    "previous_workspace": str(previous),
                    "changed": False,
                }
            if self.operation_jobs.has_running_jobs():
                raise WorkspaceError(
                    "finish or cancel running workbench operations before switching workspaces"
                )

            replacement = Workbench(
                root,
                safe_mode=self.safe_mode,
                plugin_approval_home=self.plugin_approval_home,
            )
            save_default_workspace(root, self.preference_home)
            previous_jobs = self.operation_jobs
            self.workbench = replacement
            self.operation_jobs = OperationJobManager(root)
            previous_jobs.close()
            return {
                "status": "ok",
                "workspace": str(root),
                "previous_workspace": str(previous),
                "changed": True,
            }

    def server_close(self) -> None:
        self.operation_jobs.close()
        super().server_close()


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
            "connect-src 'self'; frame-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
        )

    def _plugin_security_headers(self) -> None:
        sources = [self._origin]
        localhost = self._origin.replace("127.0.0.1", "localhost")
        if localhost != sources[0]:
            sources.append(localhost)
        local_sources = " ".join(sources)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # Sandboxed frames have an opaque `null` origin. Static plugin files contain no
        # workspace data or credentials; this narrowly permits module-script imports while
        # connect-src remains disabled and authenticated APIs still require the host token.
        self.send_header("Access-Control-Allow-Origin", "null")
        self.send_header("Vary", "Origin")
        self.send_header(
            "Content-Security-Policy",
            f"default-src 'none'; script-src {local_sources}; "
            f"style-src {local_sources} 'unsafe-inline'; img-src {local_sources} data:; "
            f"font-src {local_sources}; connect-src 'none'; media-src {local_sources}; "
            f"base-uri 'none'; form-action 'none'; frame-ancestors {local_sources}",
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

    def _send_plugin_bytes(
        self, data: bytes, media_type: str, status: int = HTTPStatus.OK
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(data)))
        self._plugin_security_headers()
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
            if parsed.path.startswith("/plugins/"):
                self._serve_plugin_asset(parsed.path.removeprefix("/plugins/"))
                return
            if not parsed.path.startswith("/api/") or not self._require_api_auth():
                if not parsed.path.startswith("/api/"):
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            query = urllib.parse.parse_qs(parsed.query)
            with self.server.workspace_lock:
                if parsed.path == "/api/bootstrap":
                    self._send_json(self.server.workbench.bootstrap())
                elif parsed.path == "/api/workspace/state":
                    self._send_json(self.server.workbench.workspace_state())
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

    def _serve_plugin_asset(self, relative: str) -> None:
        digest, separator, asset = relative.partition("/")
        if not separator or len(digest) != 64 or not asset:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            path = self.server.workbench.plugin_asset(digest, urllib.parse.unquote(asset))
        except KTError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() in {".js", ".mjs"}:
            media = "text/javascript"
        if path.suffix.lower() in {".js", ".mjs", ".css", ".html", ".json", ".svg"}:
            media += "; charset=utf-8"
        self._send_plugin_bytes(path.read_bytes(), media)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if not parsed.path.startswith("/api/") or not self._require_api_auth():
            if not parsed.path.startswith("/api/"):
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            overlays = payload.get("overlays")
            with self.server.workspace_lock:
                if parsed.path == "/api/validate":
                    result = self.server.workbench.validate(overlays)
                elif parsed.path == "/api/save":
                    result = self.server.workbench.save(overlays or {}, payload.get("expected"))
                elif parsed.path == "/api/document/create":
                    result = self.server.workbench.create_document(
                        str(payload.get("template", "")), str(payload.get("document_id", ""))
                    )
                elif parsed.path == "/api/document/action":
                    result = self.server.workbench.document_action(
                        str(payload.get("action", "")), payload.get("payload"), overlays
                    )
                elif parsed.path == "/api/document/projection":
                    result = self.server.workbench.document_projection(
                        str(payload.get("key", "")), overlays
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
                elif parsed.path == "/api/operation/job":
                    action = str(payload.get("action", ""))
                    if action == "start":
                        result = self.server.operation_jobs.start(
                            str(payload.get("operation", "")), payload.get("payload"), overlays
                        )
                    elif action == "status":
                        result = self.server.operation_jobs.status(str(payload.get("job_id", "")))
                    elif action == "cancel":
                        result = self.server.operation_jobs.cancel(str(payload.get("job_id", "")))
                    else:
                        raise ParameterError(f"unknown operation job action: {action}")
                elif parsed.path == "/api/package":
                    result = self.server.workbench.package_action(
                        str(payload.get("action", "")), payload.get("payload")
                    )
                elif parsed.path == "/api/plugin":
                    result = self.server.workbench.plugin_action(
                        str(payload.get("action", "")), payload.get("payload")
                    )
                elif parsed.path == "/api/template":
                    result = self.server.workbench.template_action(
                        str(payload.get("action", "")), payload.get("payload")
                    )
                elif parsed.path == "/api/workspace/init":
                    result = Workbench.initialize_workspace(str(payload.get("path", "")))
                elif parsed.path == "/api/workspace/open":
                    result = self.server.switch_workspace(str(payload.get("path", "")))
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


def create_web_server(
    root: Path,
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    safe_mode: bool = False,
    plugin_approval_home: Optional[Path] = None,
    preference_home: Optional[Path] = None,
) -> WorkbenchHTTPServer:
    """Create a loopback workbench server without starting its request loop."""
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ParameterError("the Kirin Tor web workbench may only listen on a loopback address")
    if port < 0 or port > 65535:
        raise ParameterError("port must be between 0 and 65535")
    return WorkbenchHTTPServer(
        (host, port),
        Workbench(
            root,
            safe_mode=safe_mode,
            plugin_approval_home=plugin_approval_home,
        ),
        secrets.token_urlsafe(32),
        preference_home=preference_home,
    )


def run_web(
    root: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
    initial_document: Optional[Path] = None,
    safe_mode: bool = False,
) -> None:
    """Run the local browser workbench until interrupted."""
    server = create_web_server(root, host, port, safe_mode=safe_mode)
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
    if safe_mode:
        print("安全模式：第三方 Workbench Plugins 已禁用")
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
