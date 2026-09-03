from __future__ import annotations

import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client, MCPError, StdioServerParameters

from kirin_tor.mcp_server import KirinMCPServer, PROTOCOL_VERSION


def test_mcp_sdk_lifecycle_tools_and_resources(example_workspace: Path) -> None:
    async def exercise() -> None:
        server = KirinMCPServer(example_workspace)
        async with Client(server, raise_exceptions=True) as client:
            assert client.protocol_version == PROTOCOL_VERSION
            assert client.server_info is not None
            assert client.server_info.name == "kirin-tor"
            assert client.server_capabilities is not None
            assert client.server_capabilities.tools is not None
            assert client.server_capabilities.resources is not None
            listed_tools = (await client.list_tools()).tools
            assert [item.name for item in listed_tools] == [
                "kirin_check",
                "kirin_validate_source",
                "kirin_evaluate",
                "kirin_explain",
                "kirin_apply_source",
            ]
            apply_schema = next(
                item.input_schema
                for item in listed_tools
                if item.name == "kirin_apply_source"
            )
            assert apply_schema["required"] == ["path", "source", "expected_sha256"]
            assert apply_schema["additionalProperties"] is False

            resources = (await client.list_resources()).resources
            assert {str(item.uri) for item in resources} >= {
                "kirin://workspace/manifest",
                "kirin://workspace/index",
                "kirin://language/authoring-contract",
            }
            source_resource = next(
                item
                for item in resources
                if (item.meta or {}).get("kirinTor", {}).get("key")
                == "entries/组合模型.kirin"
            )
            source_metadata = (source_resource.meta or {})["kirinTor"]
            assert len(source_metadata["sourceSha256"]) == 64
            read_source = (await client.read_resource(str(source_resource.uri))).contents[0]
            assert read_source.text.startswith("@kirin 2\n")
            assert (read_source.meta or {})["kirinTor"]["sourceSha256"] == source_metadata[
                "sourceSha256"
            ]

            manifest = (
                await client.read_resource("kirin://workspace/manifest")
            ).contents[0]
            manifest_payload = json.loads(manifest.text)
            assert manifest_payload["workspace"] == str(example_workspace.resolve())
            assert len(manifest_payload["revision"]) == 64

            index = (await client.read_resource("kirin://workspace/index")).contents[0]
            assert any(
                item["value"] == "combo.total"
                for item in json.loads(index.text)["targets"]
            )
            contract = (
                await client.read_resource("kirin://language/authoring-contract")
            ).contents[0]
            assert json.loads(contract.text)["version"] == 1
            assert (await client.list_resource_templates()).resource_templates == []

            with pytest.raises(MCPError) as missing_resource:
                await client.read_resource("kirin://source/..%2Fsecret")
            assert missing_resource.value.code == -32602

    anyio.run(exercise)


def test_mcp_tools_validate_compute_and_apply_with_hash_guard(
    example_workspace: Path,
) -> None:
    async def exercise() -> None:
        server = KirinMCPServer(example_workspace)
        async with Client(server, raise_exceptions=True) as client:
            checked = await client.call_tool("kirin_check", {})
            assert checked.is_error is False
            assert checked.structured_content["status"] == "ok"
            evaluated = await client.call_tool(
                "kirin_evaluate", {"target": "combo.total"}
            )
            assert evaluated.structured_content["exact"] == "2420"
            explained = await client.call_tool(
                "kirin_explain", {"target": "combo.total"}
            )
            assert explained.structured_content["status"] == "ok"

            invalid = await client.call_tool(
                "kirin_validate_source",
                {
                    "path": "entries/mcp_added.kirin",
                    "source": (
                        "@kirin 2\n@entry mcp_added\n"
                        "output result: dimensionless = missing\n"
                    ),
                },
            )
            assert invalid.is_error is True
            assert invalid.structured_content["status"] == "error"
            assert not (example_workspace / "entries" / "mcp_added.kirin").exists()
            empty = await client.call_tool(
                "kirin_validate_source",
                {"path": "entries/mcp_added.kirin", "source": ""},
            )
            assert empty.is_error is True
            invalid_apply = await client.call_tool(
                "kirin_apply_source",
                {
                    "path": "entries/mcp_added.kirin",
                    "source": (
                        "@kirin 2\n@entry mcp_added\n"
                        "output result: dimensionless = missing\n"
                    ),
                    "expected_sha256": "",
                },
            )
            assert invalid_apply.is_error is True
            assert not (example_workspace / "entries" / "mcp_added.kirin").exists()

            source = "@kirin 2\n@entry mcp_added\n\noutput result: dimensionless = 7\n"
            validated = await client.call_tool(
                "kirin_validate_source",
                {"path": "entries/mcp_added.kirin", "source": source},
            )
            assert validated.is_error is False
            assert validated.structured_content["status"] == "ok"
            applied = await client.call_tool(
                "kirin_apply_source",
                {
                    "path": "entries/mcp_added.kirin",
                    "source": source,
                    "expected_sha256": "",
                },
            )
            assert applied.is_error is False
            digest = applied.structured_content["saved"][0]["source_sha256"]
            assert len(digest) == 64
            assert (example_workspace / "entries" / "mcp_added.kirin").read_text(
                encoding="utf-8"
            ) == source

            refreshed = (await client.list_resources(cache_mode="reload")).resources
            assert any(
                (item.meta or {}).get("kirinTor", {}).get("key")
                == "entries/mcp_added.kirin"
                for item in refreshed
            )

            stale_create = await client.call_tool(
                "kirin_apply_source",
                {
                    "path": "entries/mcp_added.kirin",
                    "source": source,
                    "expected_sha256": "",
                },
            )
            assert stale_create.is_error is True
            assert stale_create.structured_content["code"] == "workspace_error"

            updated_source = source.replace("= 7", "= 8")
            updated = await client.call_tool(
                "kirin_apply_source",
                {
                    "path": "entries/mcp_added.kirin",
                    "source": updated_source,
                    "expected_sha256": digest,
                },
            )
            assert updated.is_error is False
            assert (example_workspace / "entries" / "mcp_added.kirin").read_text(
                encoding="utf-8"
            ) == updated_source

            escaped = await client.call_tool(
                "kirin_apply_source",
                {
                    "path": "../outside.kirin",
                    "source": source,
                    "expected_sha256": "",
                },
            )
            assert escaped.is_error is True
            assert not (example_workspace.parent / "outside.kirin").exists()

            with pytest.raises(MCPError) as invalid_arguments:
                await client.call_tool("kirin_check", {"surprise": True})
            assert invalid_arguments.value.code == -32602

            (example_workspace / "entries" / "mcp_added.kirin").write_text(
                "@kirin 2\n@entry mcp_added\noutput result: dimensionless = missing\n",
                encoding="utf-8",
            )
            broken_check = await client.call_tool("kirin_check", {})
            assert broken_check.is_error is True
            assert broken_check.structured_content["code"] == "expression_error"

    anyio.run(exercise)


def test_mcp_cli_stdio_works_with_official_client(example_workspace: Path) -> None:
    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "kirin_tor.cli",
                "mcp",
                str(example_workspace),
            ],
            cwd=example_workspace,
        )
        async with Client(parameters, raise_exceptions=True) as client:
            assert client.protocol_version == PROTOCOL_VERSION
            assert client.server_info is not None
            assert client.server_info.name == "kirin-tor"
            assert (await client.list_tools()).tools[0].name == "kirin_check"
            manifest = (
                await client.read_resource("kirin://workspace/manifest")
            ).contents[0]
            assert json.loads(manifest.text)["workspace"] == str(
                example_workspace.resolve()
            )

    anyio.run(exercise)
