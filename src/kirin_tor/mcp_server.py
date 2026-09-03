"""Thin, dependency-free MCP stdio adapter for one Kirin Tor workspace."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import BinaryIO, Dict, Mapping, Optional, TextIO, Union
from urllib.parse import quote

from . import __version__
from .authoring_contract import public_authoring_contract
from .errors import KTError
from .workbench import Workbench


PROTOCOL_VERSION = "2025-11-25"
MAX_MCP_MESSAGE_BYTES = 8_000_000
JsonObject = Dict[str, object]
InputStream = Union[BinaryIO, TextIO]
OutputStream = Union[BinaryIO, TextIO]


class MCPProtocolError(Exception):
    """A JSON-RPC error that belongs to the MCP transport contract."""

    def __init__(self, code: int, message: str, data: object = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _source_uri(key: str) -> str:
    return "kirin://source/" + quote(key, safe="")


def _json_text(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _tool_result(payload: JsonObject, *, is_error: bool = False) -> JsonObject:
    return {
        "content": [{"type": "text", "text": _json_text(payload)}],
        "structuredContent": payload,
        "isError": is_error,
    }


def _validation_summary(payload: Mapping[str, object]) -> JsonObject:
    keys = (
        "status",
        "documents",
        "checked",
        "code",
        "message",
        "location",
        "errors",
        "author_message",
    )
    return {key: payload[key] for key in keys if key in payload}


def _object_arguments(params: Mapping[str, object]) -> JsonObject:
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        raise MCPProtocolError(-32602, "tool arguments must be an object")
    return dict(arguments)


def _reject_unknown(arguments: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise MCPProtocolError(
            -32602,
            "unknown tool argument(s): " + ", ".join(unknown),
        )


def _required_string(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise MCPProtocolError(-32602, f"{name} must be a non-empty string")
    return value


def _required_text(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise MCPProtocolError(-32602, f"{name} must be a string")
    return value


def _optional_string(arguments: Mapping[str, object], name: str) -> Optional[str]:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise MCPProtocolError(-32602, f"{name} must be a non-empty string when provided")
    return value


def _optional_number(arguments: Mapping[str, object], name: str) -> Optional[object]:
    value = arguments.get(name)
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise MCPProtocolError(-32602, f"{name} must be a number when provided")
    return value


def _optional_integer(arguments: Mapping[str, object], name: str) -> Optional[int]:
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MCPProtocolError(-32602, f"{name} must be an integer when provided")
    return value


class KirinMCPServer:
    """Serve bounded resources and tools without creating another source model."""

    def __init__(self, root: Path):
        self.workbench = Workbench(root, safe_mode=True)
        self._initialize_seen = False

    @property
    def root(self) -> Path:
        return self.workbench.root

    def _initialize(self, params: Mapping[str, object]) -> JsonObject:
        if self._initialize_seen:
            raise MCPProtocolError(-32600, "server is already initialized")
        requested = params.get("protocolVersion")
        capabilities = params.get("capabilities")
        client_info = params.get("clientInfo")
        if not isinstance(requested, str) or not requested:
            raise MCPProtocolError(-32602, "protocolVersion must be a non-empty string")
        if not isinstance(capabilities, dict):
            raise MCPProtocolError(-32602, "capabilities must be an object")
        if not isinstance(client_info, dict):
            raise MCPProtocolError(-32602, "clientInfo must be an object")
        if not isinstance(client_info.get("name"), str) or not isinstance(
            client_info.get("version"), str
        ):
            raise MCPProtocolError(-32602, "clientInfo requires string name and version")
        self._initialize_seen = True
        return {
            "protocolVersion": (
                requested if requested == PROTOCOL_VERSION else PROTOCOL_VERSION
            ),
            "capabilities": {"resources": {}, "tools": {}},
            "serverInfo": {
                "name": "kirin-tor",
                "title": "Kirin Tor Workspace",
                "version": __version__,
            },
            "instructions": (
                "Kirin resources expose the current durable .kirin sources only. "
                "Use kirin_validate_source before kirin_apply_source, and pass the "
                "current source_sha256 when replacing an existing source. Package "
                "sources are read-only; browser-unsaved buffers are outside this server."
            ),
        }

    @staticmethod
    def _tool_catalog() -> list[JsonObject]:
        no_arguments = {"type": "object", "additionalProperties": False}
        return [
            {
                "name": "kirin_check",
                "title": "Check Kirin workspace",
                "description": (
                    "Validate every durable workspace and locked-Package source without "
                    "writing files."
                ),
                "inputSchema": no_arguments,
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "kirin_validate_source",
                "title": "Validate Kirin source draft",
                "description": (
                    "Validate one proposed entries/**/*.kirin source as an in-memory "
                    "overlay over the current durable workspace. Nothing is written."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Workspace-relative entries/**/*.kirin path.",
                        },
                        "source": {"type": "string", "description": "Complete source text."},
                    },
                    "required": ["path", "source"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "kirin_evaluate",
                "title": "Evaluate Kirin target",
                "description": (
                    "Evaluate one validated static output using exact Kirin semantics. "
                    "This does not create a run record or export an artifact."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": "Qualified ENTRY.OUTPUT target.",
                        },
                        "preset": {"type": "string"},
                        "overrides": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Qualified input names mapped to exact Kirin values.",
                        },
                        "precision": {"type": "integer"},
                        "display_digits": {"type": "integer"},
                        "timeout": {"type": "number"},
                    },
                    "required": ["target"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "kirin_explain",
                "title": "Explain Kirin target",
                "description": (
                    "Return a target's expanded expression, inputs, retained conditions, "
                    "units, and dependencies without writing files."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "timeout": {"type": "number"},
                    },
                    "required": ["target"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            {
                "name": "kirin_apply_source",
                "title": "Validate and apply Kirin source",
                "description": (
                    "Validate one complete source against the workspace, check its expected "
                    "disk hash, then atomically create or replace that entries/**/*.kirin file."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Workspace-relative entries/**/*.kirin path.",
                        },
                        "source": {"type": "string", "description": "Complete source text."},
                        "expected_sha256": {
                            "type": "string",
                            "pattern": "^(?:[0-9a-f]{64})?$",
                            "description": (
                                "Current source hash, or the empty string only when creating "
                                "a new path."
                            ),
                        },
                    },
                    "required": ["path", "source", "expected_sha256"],
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": True,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
            },
        ]

    def _resource_catalog(self) -> list[JsonObject]:
        documents = self.workbench.list_documents()["documents"]
        resources: list[JsonObject] = [
            {
                "uri": "kirin://workspace/manifest",
                "name": "workspace-manifest",
                "title": "Kirin Tor workspace manifest",
                "description": "Durable source catalog, hashes, and workspace revision.",
                "mimeType": "application/json",
                "annotations": {"audience": ["assistant"], "priority": 1.0},
            },
            {
                "uri": "kirin://workspace/index",
                "name": "workspace-index",
                "title": "Validated Kirin Tor workspace index",
                "description": "Targets, inputs, presets, charts, analyses, and document IDs.",
                "mimeType": "application/json",
                "annotations": {"audience": ["assistant"], "priority": 0.9},
            },
            {
                "uri": "kirin://language/authoring-contract",
                "name": "authoring-contract",
                "title": "Kirin Tor authoring contract",
                "description": "Official editor vocabulary, snippets, signatures, and references.",
                "mimeType": "application/json",
                "annotations": {"audience": ["assistant"], "priority": 0.8},
            },
        ]
        for raw in documents:
            item = dict(raw)
            key = str(item["key"])
            package = item.get("package") if isinstance(item.get("package"), dict) else None
            metadata: JsonObject = {
                "key": key,
                "sourceSha256": str(item["source_sha256"]),
                "readOnly": bool(item["read_only"]),
            }
            if package is not None:
                metadata["package"] = {
                    field: package[field]
                    for field in ("name", "version", "content_sha256")
                    if field in package
                }
            resources.append(
                {
                    "uri": _source_uri(key),
                    "name": key,
                    "title": str(item["title"]),
                    "description": (
                        "Locked Package Kirin source" if item["read_only"] else "Writable Kirin source"
                    ),
                    "mimeType": "text/x-kirin",
                    "annotations": {"audience": ["assistant"], "priority": 0.9},
                    "_meta": {"kirinTor": metadata},
                }
            )
        return resources

    def _read_resource(self, uri: str) -> JsonObject:
        if uri == "kirin://workspace/manifest":
            state = self.workbench.workspace_state()
            catalog = self.workbench.list_documents()["documents"]
            payload = {
                "status": "ok",
                "workspace": str(self.root),
                "revision": state["revision"],
                "documents": catalog,
            }
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": _json_text(payload),
                    }
                ]
            }
        if uri == "kirin://workspace/index":
            validation = self.workbench.validate()
            if validation.get("status") != "ok":
                raise MCPProtocolError(
                    -32603,
                    "workspace is invalid; call kirin_check for diagnostics",
                    _validation_summary(validation),
                )
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": _json_text(validation["index"]),
                    }
                ]
            }
        if uri == "kirin://language/authoring-contract":
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": _json_text(public_authoring_contract()),
                    }
                ]
            }
        resource = next(
            (item for item in self._resource_catalog() if item["uri"] == uri),
            None,
        )
        if resource is None or not str(resource["uri"]).startswith("kirin://source/"):
            raise MCPProtocolError(-32002, "resource not found", {"uri": uri})
        metadata = resource.get("_meta", {})
        kirin_metadata = metadata.get("kirinTor", {}) if isinstance(metadata, dict) else {}
        key = kirin_metadata.get("key") if isinstance(kirin_metadata, dict) else None
        if not isinstance(key, str):
            raise MCPProtocolError(-32002, "resource not found", {"uri": uri})
        document = self.workbench.read_document(key)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/x-kirin",
                    "text": document["text"],
                    "_meta": {"kirinTor": kirin_metadata},
                }
            ]
        }

    def _call_tool(self, name: str, params: Mapping[str, object]) -> JsonObject:
        known = {item["name"] for item in self._tool_catalog()}
        if name not in known:
            raise MCPProtocolError(-32602, f"unknown tool: {name}")
        arguments = _object_arguments(params)
        try:
            if name == "kirin_check":
                _reject_unknown(arguments, set())
                result = _validation_summary(self.workbench.validate())
            elif name == "kirin_validate_source":
                _reject_unknown(arguments, {"path", "source"})
                path = _required_string(arguments, "path")
                source = _required_text(arguments, "source")
                result = _validation_summary(self.workbench.validate({path: source}))
            elif name == "kirin_evaluate":
                allowed = {
                    "target",
                    "preset",
                    "overrides",
                    "precision",
                    "display_digits",
                    "timeout",
                }
                _reject_unknown(arguments, allowed)
                payload: JsonObject = {"target": _required_string(arguments, "target")}
                preset = _optional_string(arguments, "preset")
                if preset is not None:
                    payload["preset"] = preset
                overrides = arguments.get("overrides")
                if overrides is not None:
                    if not isinstance(overrides, dict) or any(
                        not isinstance(key, str) or not isinstance(value, str)
                        for key, value in overrides.items()
                    ):
                        raise MCPProtocolError(
                            -32602,
                            "overrides must map string input names to string values",
                        )
                    payload["overrides"] = overrides
                for field in ("precision", "display_digits"):
                    value = _optional_integer(arguments, field)
                    if value is not None:
                        payload[field] = value
                timeout = _optional_number(arguments, "timeout")
                if timeout is not None:
                    payload["timeout"] = timeout
                result = self.workbench.execute("eval", payload)
            elif name == "kirin_explain":
                _reject_unknown(arguments, {"target", "timeout"})
                payload = {"target": _required_string(arguments, "target")}
                timeout = _optional_number(arguments, "timeout")
                if timeout is not None:
                    payload["timeout"] = timeout
                result = self.workbench.execute("explain", payload)
            elif name == "kirin_apply_source":
                _reject_unknown(arguments, {"path", "source", "expected_sha256"})
                path = _required_string(arguments, "path")
                source = _required_text(arguments, "source")
                expected = arguments.get("expected_sha256")
                if not isinstance(expected, str) or (
                    expected and (
                        len(expected) != 64
                        or any(character not in "0123456789abcdef" for character in expected)
                    )
                ):
                    raise MCPProtocolError(
                        -32602,
                        "expected_sha256 must be a lowercase SHA-256 digest or the empty string",
                    )
                result = self.workbench.save({path: source}, {path: expected})
            else:  # pragma: no cover - catalog and dispatcher are defined together
                raise MCPProtocolError(-32602, f"unknown tool: {name}")
        except KTError as exc:
            return _tool_result(exc.as_dict(), is_error=True)
        result_object = dict(result)
        return _tool_result(
            result_object,
            is_error=result_object.get("status") == "error",
        )

    @staticmethod
    def _params(message: Mapping[str, object]) -> JsonObject:
        params = message.get("params", {})
        if params is None:
            return {}
        if not isinstance(params, dict):
            raise MCPProtocolError(-32602, "params must be an object")
        return dict(params)

    @staticmethod
    def _reject_cursor(params: Mapping[str, object]) -> None:
        cursor = params.get("cursor")
        if cursor is not None and cursor != "":
            raise MCPProtocolError(-32602, "pagination cursor is not supported")

    def _dispatch(self, method: str, params: Mapping[str, object]) -> JsonObject:
        if method == "initialize":
            return self._initialize(params)
        if method == "server/discover":
            raise MCPProtocolError(-32601, "method not found")
        if method == "ping":
            return {}
        if not self._initialize_seen:
            raise MCPProtocolError(-32600, "server has not been initialized")
        if method == "tools/list":
            self._reject_cursor(params)
            return {"tools": self._tool_catalog()}
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                raise MCPProtocolError(-32602, "tool name must be a non-empty string")
            return self._call_tool(name, params)
        if method == "resources/list":
            self._reject_cursor(params)
            return {"resources": self._resource_catalog()}
        if method == "resources/templates/list":
            self._reject_cursor(params)
            return {"resourceTemplates": []}
        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str) or not uri:
                raise MCPProtocolError(-32602, "resource uri must be a non-empty string")
            return self._read_resource(uri)
        raise MCPProtocolError(-32601, "method not found")

    @staticmethod
    def _error_response(
        request_id: object,
        code: int,
        message: str,
        data: object = None,
    ) -> JsonObject:
        error: JsonObject = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    def handle_message(self, message: object) -> Optional[JsonObject]:
        if not isinstance(message, dict):
            return self._error_response(None, -32600, "invalid request")
        request_id = message.get("id")
        is_notification = "id" not in message
        valid_id = (
            request_id is None
            or (isinstance(request_id, (str, int, float)) and not isinstance(request_id, bool))
        )
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return self._error_response(
                request_id if valid_id else None,
                -32600,
                "invalid request",
            )
        if not valid_id:
            return self._error_response(None, -32600, "invalid request id")
        method = str(message["method"])
        try:
            params = self._params(message)
            if is_notification:
                return None
            result = self._dispatch(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except MCPProtocolError as exc:
            return None if is_notification else self._error_response(
                request_id,
                exc.code,
                exc.message,
                exc.data,
            )
        except KTError as exc:
            return None if is_notification else self._error_response(
                request_id,
                -32603,
                "Kirin Tor request failed",
                exc.as_dict(),
            )
        except Exception as exc:  # pragma: no cover - last-resort protocol containment
            sys.stderr.write(
                f"Kirin Tor MCP internal error: {type(exc).__name__}: {exc}\n"
            )
            sys.stderr.flush()
            return None if is_notification else self._error_response(
                request_id,
                -32603,
                "internal Kirin Tor MCP error",
            )


def _write_message(stream: OutputStream, message: Mapping[str, object]) -> None:
    rendered = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        stream.write(rendered.encode("utf-8"))
    except TypeError:
        stream.write(rendered)
    stream.flush()


def _line_ends_message(raw: Union[bytes, str]) -> bool:
    return raw.endswith(b"\n") if isinstance(raw, bytes) else raw.endswith("\n")


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"invalid JSON constant: {value}")


def serve_stdio(
    server: KirinMCPServer,
    input_stream: InputStream,
    output_stream: OutputStream,
) -> None:
    """Serve newline-delimited UTF-8 JSON-RPC until the client closes stdin."""

    while True:
        raw = input_stream.readline(MAX_MCP_MESSAGE_BYTES + 1)
        if raw in {b"", ""}:
            return
        if len(raw) > MAX_MCP_MESSAGE_BYTES:
            while raw and not _line_ends_message(raw):
                raw = input_stream.readline(MAX_MCP_MESSAGE_BYTES + 1)
            _write_message(
                output_stream,
                server._error_response(None, -32600, "MCP message exceeds size limit"),
            )
            continue
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            message = json.loads(text, parse_constant=_reject_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            _write_message(
                output_stream,
                server._error_response(None, -32700, "parse error"),
            )
            continue
        response = server.handle_message(message)
        if response is not None:
            _write_message(output_stream, response)


def run_mcp_server(root: Path) -> None:
    """Run the configured workspace adapter on the process stdio streams."""

    serve_stdio(KirinMCPServer(root), sys.stdin.buffer, sys.stdout.buffer)
