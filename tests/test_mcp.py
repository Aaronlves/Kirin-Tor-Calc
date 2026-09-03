from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from kirin_tor.mcp_server import KirinMCPServer, PROTOCOL_VERSION


def request(
    server: KirinMCPServer,
    request_id: int,
    method: str,
    params: dict | None = None,
) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            **({} if params is None else {"params": params}),
        }
    )
    assert response is not None
    return response


def initialize(server: KirinMCPServer, protocol: str = PROTOCOL_VERSION) -> dict:
    return request(
        server,
        1,
        "initialize",
        {
            "protocolVersion": protocol,
            "capabilities": {},
            "clientInfo": {"name": "kirin-test-client", "version": "1"},
        },
    )


def call_tool(server: KirinMCPServer, name: str, arguments: dict) -> dict:
    response = request(
        server,
        10,
        "tools/call",
        {"name": name, "arguments": arguments},
    )
    assert "error" not in response
    return response["result"]


def test_mcp_lifecycle_tools_and_resources(example_workspace: Path) -> None:
    server = KirinMCPServer(example_workspace)

    malformed_notification_shape = server.handle_message(
        {"jsonrpc": "1.0", "method": "notifications/initialized"}
    )
    assert malformed_notification_shape is not None
    assert malformed_notification_shape["error"]["code"] == -32600
    premature = request(server, 1, "tools/list")
    assert premature["error"]["code"] == -32600
    modern_probe = request(server, 2, "server/discover")
    assert modern_probe["error"]["code"] == -32601

    initialized = initialize(server, "2026-07-28")
    assert initialized["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert initialized["result"]["capabilities"] == {"resources": {}, "tools": {}}
    assert initialized["result"]["serverInfo"]["name"] == "kirin-tor"
    assert server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ) is None
    assert request(server, 3, "ping")["result"] == {}

    listed_tools = request(server, 4, "tools/list")["result"]["tools"]
    assert [item["name"] for item in listed_tools] == [
        "kirin_check",
        "kirin_validate_source",
        "kirin_evaluate",
        "kirin_explain",
        "kirin_apply_source",
    ]
    apply_schema = next(
        item["inputSchema"]
        for item in listed_tools
        if item["name"] == "kirin_apply_source"
    )
    assert apply_schema["required"] == ["path", "source", "expected_sha256"]

    resources = request(server, 5, "resources/list")["result"]["resources"]
    assert {item["uri"] for item in resources} >= {
        "kirin://workspace/manifest",
        "kirin://workspace/index",
        "kirin://language/authoring-contract",
    }
    source_resource = next(
        item
        for item in resources
        if item.get("_meta", {}).get("kirinTor", {}).get("key")
        == "entries/组合模型.kirin"
    )
    assert len(source_resource["_meta"]["kirinTor"]["sourceSha256"]) == 64
    read_source = request(
        server,
        6,
        "resources/read",
        {"uri": source_resource["uri"]},
    )["result"]["contents"][0]
    assert read_source["text"].startswith("@kirin 2\n")
    assert read_source["_meta"]["kirinTor"]["sourceSha256"] == source_resource[
        "_meta"
    ]["kirinTor"]["sourceSha256"]

    manifest = request(
        server,
        7,
        "resources/read",
        {"uri": "kirin://workspace/manifest"},
    )["result"]["contents"][0]
    manifest_payload = json.loads(manifest["text"])
    assert manifest_payload["workspace"] == str(example_workspace.resolve())
    assert len(manifest_payload["revision"]) == 64

    index = request(
        server,
        8,
        "resources/read",
        {"uri": "kirin://workspace/index"},
    )["result"]["contents"][0]
    assert any(item["value"] == "combo.total" for item in json.loads(index["text"])["targets"])
    contract = request(
        server,
        9,
        "resources/read",
        {"uri": "kirin://language/authoring-contract"},
    )["result"]["contents"][0]
    assert json.loads(contract["text"])["version"] == 1
    assert request(
        server,
        10,
        "resources/read",
        {"uri": "kirin://source/..%2Fsecret"},
    )["error"]["code"] == -32002
    assert request(server, 11, "resources/templates/list")["result"] == {
        "resourceTemplates": []
    }
    bad_cursor = request(server, 12, "resources/list", {"cursor": {"bad": True}})
    assert bad_cursor["error"]["code"] == -32602


def test_mcp_tools_validate_compute_and_apply_with_hash_guard(
    example_workspace: Path,
) -> None:
    server = KirinMCPServer(example_workspace)
    initialize(server)

    checked = call_tool(server, "kirin_check", {})
    assert checked["isError"] is False
    assert checked["structuredContent"]["status"] == "ok"
    evaluated = call_tool(server, "kirin_evaluate", {"target": "combo.total"})
    assert evaluated["structuredContent"]["exact"] == "2420"
    explained = call_tool(server, "kirin_explain", {"target": "combo.total"})
    assert explained["structuredContent"]["status"] == "ok"

    invalid = call_tool(
        server,
        "kirin_validate_source",
        {
            "path": "entries/mcp_added.kirin",
            "source": "@kirin 2\n@entry mcp_added\noutput result: dimensionless = missing\n",
        },
    )
    assert invalid["isError"] is True
    assert invalid["structuredContent"]["status"] == "error"
    assert not (example_workspace / "entries" / "mcp_added.kirin").exists()
    empty = call_tool(
        server,
        "kirin_validate_source",
        {"path": "entries/mcp_added.kirin", "source": ""},
    )
    assert empty["isError"] is True
    invalid_apply = call_tool(
        server,
        "kirin_apply_source",
        {
            "path": "entries/mcp_added.kirin",
            "source": "@kirin 2\n@entry mcp_added\noutput result: dimensionless = missing\n",
            "expected_sha256": "",
        },
    )
    assert invalid_apply["isError"] is True
    assert not (example_workspace / "entries" / "mcp_added.kirin").exists()

    source = "@kirin 2\n@entry mcp_added\n\noutput result: dimensionless = 7\n"
    validated = call_tool(
        server,
        "kirin_validate_source",
        {"path": "entries/mcp_added.kirin", "source": source},
    )
    assert validated["isError"] is False
    assert validated["structuredContent"]["status"] == "ok"
    applied = call_tool(
        server,
        "kirin_apply_source",
        {
            "path": "entries/mcp_added.kirin",
            "source": source,
            "expected_sha256": "",
        },
    )
    assert applied["isError"] is False
    digest = applied["structuredContent"]["saved"][0]["source_sha256"]
    assert len(digest) == 64
    assert (example_workspace / "entries" / "mcp_added.kirin").read_text(
        encoding="utf-8"
    ) == source

    stale_create = call_tool(
        server,
        "kirin_apply_source",
        {
            "path": "entries/mcp_added.kirin",
            "source": source,
            "expected_sha256": "",
        },
    )
    assert stale_create["isError"] is True
    assert stale_create["structuredContent"]["code"] == "workspace_error"

    updated_source = source.replace("= 7", "= 8")
    updated = call_tool(
        server,
        "kirin_apply_source",
        {
            "path": "entries/mcp_added.kirin",
            "source": updated_source,
            "expected_sha256": digest,
        },
    )
    assert updated["isError"] is False
    assert (example_workspace / "entries" / "mcp_added.kirin").read_text(
        encoding="utf-8"
    ) == updated_source

    escaped = call_tool(
        server,
        "kirin_apply_source",
        {
            "path": "../outside.kirin",
            "source": source,
            "expected_sha256": "",
        },
    )
    assert escaped["isError"] is True
    assert not (example_workspace.parent / "outside.kirin").exists()

    invalid_arguments = request(
        server,
        20,
        "tools/call",
        {"name": "kirin_check", "arguments": {"surprise": True}},
    )
    assert invalid_arguments["error"]["code"] == -32602

    (example_workspace / "entries" / "mcp_added.kirin").write_text(
        "@kirin 2\n@entry mcp_added\noutput result: dimensionless = missing\n",
        encoding="utf-8",
    )
    broken_check = call_tool(server, "kirin_check", {})
    assert broken_check["isError"] is True
    assert broken_check["structuredContent"]["code"] == "expression_error"


def test_mcp_cli_stdio_is_newline_delimited_json_only(example_workspace: Path) -> None:
    messages = [
        "not-json",
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "stdio-test", "version": "1"},
                },
            }
        ),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "kirin_tor.cli",
            "mcp",
            str(example_workspace),
        ],
        input="\n".join(messages) + "\n",
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    responses = [json.loads(line) for line in completed.stdout.splitlines()]
    assert len(responses) == 3
    assert responses[0]["error"]["code"] == -32700
    assert responses[1]["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert responses[2]["result"]["tools"][0]["name"] == "kirin_check"
