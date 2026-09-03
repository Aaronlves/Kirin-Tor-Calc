"""Thin MCP SDK adapter for one Kirin Tor workspace."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Mapping
from urllib.parse import quote

import anyio
from mcp import MCPError
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    LATEST_PROTOCOL_VERSION,
    Annotations,
    CallToolRequestParams,
    CallToolResult,
    ListResourceTemplatesResult,
    ListResourcesResult,
    ListToolsResult,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
    Tool,
    ToolAnnotations,
)

from . import __version__
from .authoring_contract import public_authoring_contract
from .errors import KTError
from .workbench import Workbench


PROTOCOL_VERSION = LATEST_PROTOCOL_VERSION
JsonObject = dict[str, object]


def _source_uri(key: str) -> str:
    return "kirin://source/" + quote(key, safe="")


def _json_text(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _tool_result(payload: Mapping[str, object], *, is_error: bool = False) -> CallToolResult:
    structured = dict(payload)
    return CallToolResult(
        content=[TextContent(text=_json_text(structured))],
        structuredContent=structured,
        isError=is_error,
    )


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


def _reject_unknown(arguments: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(arguments) - allowed)
    if unknown:
        raise MCPError(
            INVALID_PARAMS,
            "unknown tool argument(s): " + ", ".join(unknown),
        )


def _required_string(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise MCPError(INVALID_PARAMS, f"{name} must be a non-empty string")
    return value


def _required_text(arguments: Mapping[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise MCPError(INVALID_PARAMS, f"{name} must be a string")
    return value


def _optional_string(arguments: Mapping[str, object], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise MCPError(INVALID_PARAMS, f"{name} must be a non-empty string when provided")
    return value


def _optional_number(arguments: Mapping[str, object], name: str) -> object | None:
    value = arguments.get(name)
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise MCPError(INVALID_PARAMS, f"{name} must be a finite number when provided")
    return value


def _optional_integer(arguments: Mapping[str, object], name: str) -> int | None:
    value = arguments.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise MCPError(INVALID_PARAMS, f"{name} must be an integer when provided")
    return value


class KirinMCPServer(Server[object]):
    """Serve bounded Kirin resources and tools through the official MCP SDK."""

    def __init__(self, root: Path):
        self.workbench = Workbench(root, safe_mode=True)
        super().__init__(
            name="kirin-tor",
            title="Kirin Tor Workspace",
            description="Bounded access to one durable Kirin Tor workspace.",
            version=__version__,
            instructions=(
                "Kirin resources expose the current durable .kirin sources only. "
                "Use kirin_validate_source before kirin_apply_source, and pass the "
                "current source_sha256 when replacing an existing source. Package "
                "sources are read-only; browser-unsaved buffers are outside this server."
            ),
            on_list_tools=self._handle_list_tools,
            on_call_tool=self._handle_call_tool,
            on_list_resources=self._handle_list_resources,
            on_list_resource_templates=self._handle_list_resource_templates,
            on_read_resource=self._handle_read_resource,
        )

    @property
    def root(self) -> Path:
        return self.workbench.root

    @staticmethod
    def _tool_catalog() -> list[Tool]:
        read_only = ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        )
        no_arguments = {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        return [
            Tool(
                name="kirin_check",
                title="Check Kirin workspace",
                description=(
                    "Validate every durable workspace and locked-Package source without "
                    "writing files."
                ),
                inputSchema=no_arguments,
                annotations=read_only,
            ),
            Tool(
                name="kirin_validate_source",
                title="Validate Kirin source draft",
                description=(
                    "Validate one proposed entries/**/*.kirin source as an in-memory "
                    "overlay over the current durable workspace. Nothing is written."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Workspace-relative entries/**/*.kirin path.",
                        },
                        "source": {"type": "string", "description": "Complete source text."},
                    },
                    "required": ["path", "source"],
                    "additionalProperties": False,
                },
                annotations=read_only,
            ),
            Tool(
                name="kirin_evaluate",
                title="Evaluate Kirin target",
                description=(
                    "Evaluate one validated static output using exact Kirin semantics. "
                    "This does not create a run record or export an artifact."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "minLength": 1},
                        "preset": {"type": "string", "minLength": 1},
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
                annotations=read_only,
            ),
            Tool(
                name="kirin_explain",
                title="Explain Kirin target",
                description=(
                    "Return a target's expanded expression, inputs, retained conditions, "
                    "units, and dependencies without writing files."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "minLength": 1},
                        "timeout": {"type": "number"},
                    },
                    "required": ["target"],
                    "additionalProperties": False,
                },
                annotations=read_only,
            ),
            Tool(
                name="kirin_apply_source",
                title="Validate and apply Kirin source",
                description=(
                    "Validate one complete source against the workspace, check its expected "
                    "disk hash, then atomically create or replace that entries/**/*.kirin file."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "minLength": 1,
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
                annotations=ToolAnnotations(
                    readOnlyHint=False,
                    destructiveHint=True,
                    idempotentHint=False,
                    openWorldHint=False,
                ),
            ),
        ]

    def _resource_catalog(self) -> list[Resource]:
        resources = [
            Resource(
                uri="kirin://workspace/manifest",
                name="workspace-manifest",
                title="Kirin Tor workspace manifest",
                description="Durable source catalog, hashes, and workspace revision.",
                mimeType="application/json",
                annotations=Annotations(audience=["assistant"], priority=1.0),
            ),
            Resource(
                uri="kirin://workspace/index",
                name="workspace-index",
                title="Validated Kirin Tor workspace index",
                description="Targets, inputs, presets, charts, analyses, and document IDs.",
                mimeType="application/json",
                annotations=Annotations(audience=["assistant"], priority=0.9),
            ),
            Resource(
                uri="kirin://language/authoring-contract",
                name="authoring-contract",
                title="Kirin Tor authoring contract",
                description="Official editor vocabulary, snippets, signatures, and references.",
                mimeType="application/json",
                annotations=Annotations(audience=["assistant"], priority=0.8),
            ),
        ]
        for raw in self.workbench.list_documents()["documents"]:
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
                Resource(
                    uri=_source_uri(key),
                    name=key,
                    title=str(item["title"]),
                    description=(
                        "Locked Package Kirin source"
                        if item["read_only"]
                        else "Writable Kirin source"
                    ),
                    mimeType="text/x-kirin",
                    annotations=Annotations(audience=["assistant"], priority=0.9),
                    _meta={"kirinTor": metadata},
                )
            )
        return resources

    def _read_resource(self, uri: str) -> ReadResourceResult:
        if uri == "kirin://workspace/manifest":
            state = self.workbench.workspace_state()
            payload = {
                "status": "ok",
                "workspace": str(self.root),
                "revision": state["revision"],
                "documents": self.workbench.list_documents()["documents"],
            }
            return ReadResourceResult(
                contents=[
                    TextResourceContents(
                        uri=uri,
                        mimeType="application/json",
                        text=_json_text(payload),
                    )
                ]
            )
        if uri == "kirin://workspace/index":
            validation = self.workbench.validate()
            if validation.get("status") != "ok":
                raise MCPError(
                    INTERNAL_ERROR,
                    "workspace is invalid; call kirin_check for diagnostics",
                    _validation_summary(validation),
                )
            return ReadResourceResult(
                contents=[
                    TextResourceContents(
                        uri=uri,
                        mimeType="application/json",
                        text=_json_text(validation["index"]),
                    )
                ]
            )
        if uri == "kirin://language/authoring-contract":
            return ReadResourceResult(
                contents=[
                    TextResourceContents(
                        uri=uri,
                        mimeType="application/json",
                        text=_json_text(public_authoring_contract()),
                    )
                ]
            )
        resource = next(
            (item for item in self._resource_catalog() if str(item.uri) == uri),
            None,
        )
        if resource is None or not uri.startswith("kirin://source/"):
            raise MCPError(INVALID_PARAMS, "resource not found", {"uri": uri})
        metadata = resource.meta or {}
        kirin_metadata = metadata.get("kirinTor", {})
        key = kirin_metadata.get("key") if isinstance(kirin_metadata, dict) else None
        if not isinstance(key, str):
            raise MCPError(INVALID_PARAMS, "resource not found", {"uri": uri})
        document = self.workbench.read_document(key)
        return ReadResourceResult(
            contents=[
                TextResourceContents(
                    uri=uri,
                    mimeType="text/x-kirin",
                    text=document["text"],
                    _meta={"kirinTor": kirin_metadata},
                )
            ]
        )

    def _call_tool(self, name: str, arguments: Mapping[str, object]) -> CallToolResult:
        known = {item.name for item in self._tool_catalog()}
        if name not in known:
            raise MCPError(INVALID_PARAMS, f"unknown tool: {name}")
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
                        raise MCPError(
                            INVALID_PARAMS,
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
                    expected
                    and (
                        len(expected) != 64
                        or any(character not in "0123456789abcdef" for character in expected)
                    )
                ):
                    raise MCPError(
                        INVALID_PARAMS,
                        "expected_sha256 must be a lowercase SHA-256 digest or the empty string",
                    )
                result = self.workbench.save({path: source}, {path: expected})
            else:  # pragma: no cover - catalog and dispatcher are defined together
                raise MCPError(INVALID_PARAMS, f"unknown tool: {name}")
        except KTError as exc:
            return _tool_result(exc.as_dict(), is_error=True)
        result_object = dict(result)
        return _tool_result(
            result_object,
            is_error=result_object.get("status") == "error",
        )

    async def _handle_list_tools(self, _context: object, _params: object) -> ListToolsResult:
        return ListToolsResult(tools=self._tool_catalog())

    async def _handle_call_tool(
        self,
        _context: object,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        arguments = params.arguments or {}
        if not isinstance(arguments, dict):  # pragma: no cover - enforced by SDK models
            raise MCPError(INVALID_PARAMS, "tool arguments must be an object")
        return self._call_tool(params.name, arguments)

    async def _handle_list_resources(
        self,
        _context: object,
        _params: object,
    ) -> ListResourcesResult:
        return ListResourcesResult(resources=self._resource_catalog())

    async def _handle_read_resource(
        self,
        _context: object,
        params: ReadResourceRequestParams,
    ) -> ReadResourceResult:
        return self._read_resource(str(params.uri))

    async def _handle_list_resource_templates(
        self,
        _context: object,
        _params: object,
    ) -> ListResourceTemplatesResult:
        return ListResourceTemplatesResult(resourceTemplates=[])


def run_mcp_server(root: Path) -> None:
    """Run the configured workspace adapter through the SDK stdio transport."""

    server = KirinMCPServer(root)

    async def serve() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )

    anyio.run(serve)
