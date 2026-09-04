from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.errors import PluginError
from kirin_tor.package_authoring import add_path_package
from kirin_tor.plugin_artifacts import protocol_artifacts
from kirin_tor.plugin_authoring import (
    bundle_plugin,
    check_plugin,
    create_plugin_template,
    test_plugin as run_plugin_test,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_generated_protocol_artifacts_are_current() -> None:
    for relative, expected in protocol_artifacts().items():
        assert (PROJECT_ROOT / relative).read_text(encoding="utf-8") == expected

    protocol_schema = json.loads(
        (PROJECT_ROOT / "schemas" / "plugin-v2" / "protocol.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert {
        "activation",
        "actionRequest",
        "actionResultMessage",
        "actionErrorMessage",
        "jobUpdate",
        "pluginToHostMessage",
        "hostToPluginMessage",
    } <= set(protocol_schema["$defs"])
    sdk_types = (
        PROJECT_ROOT / "sdk" / "plugin" / "kirin-plugin-sdk.d.mts"
    ).read_text(encoding="utf-8")
    assert '"evaluate-many": {' in sdk_types
    assert '"model.query": {' in sdk_types


def test_plugin_new_check_test_and_bundle_are_offline_and_deterministic(
    example_workspace: Path,
    tmp_path: Path,
) -> None:
    root = tmp_path / "example-plugin"
    created = create_plugin_template(root, "community.example-plugin")
    assert created["id"] == "community.example-plugin"
    plugin_source = (root / "web" / "plugin.js").read_text(encoding="utf-8")
    assert "createKirinPlugin" in plugin_source
    assert "postMessage" not in plugin_source
    assert check_plugin(root)["content_sha256"] == created["content_sha256"]

    tested = run_plugin_test(root, example_workspace)
    assert tested["suite"] == "offline-protocol-v2"
    assert {item["status"] for item in tested["tests"]} == {"passed"}
    assert not (example_workspace / "kirin.plugins.toml").exists()

    (root / "package.json").write_text(
        json.dumps({"scripts": {"postinstall": "exit 99"}}), encoding="utf-8"
    )
    first = bundle_plugin(root, tmp_path / "first.ktplugin.zip")
    second = bundle_plugin(root, tmp_path / "second.ktplugin.zip")
    assert first["bundle_sha256"] == second["bundle_sha256"]
    assert (tmp_path / "first.ktplugin.zip").read_bytes() == (
        tmp_path / "second.ktplugin.zip"
    ).read_bytes()
    with pytest.raises(PluginError, match="already exists"):
        bundle_plugin(root, tmp_path / "first.ktplugin.zip")
    replaced = bundle_plugin(
        root, tmp_path / "first.ktplugin.zip", force=True
    )
    assert replaced["bundle_sha256"] == first["bundle_sha256"]
    with pytest.raises(PluginError, match="outside"):
        bundle_plugin(root, root / "dist" / "inside.ktplugin.zip")


def test_reference_plugin_passes_interfaces_in_disposable_workspace(
    example_workspace: Path,
) -> None:
    package = PROJECT_ROOT / "examples" / "packages" / "fictional-models"
    plugin = PROJECT_ROOT / "examples" / "plugins" / "fictional-talent-tree"
    add_path_package(example_workspace, "fictional_models", package)

    result = run_plugin_test(plugin, example_workspace)

    assert result["compatibility"]["compatible"] is True
    assert result["compatibility"]["interfaces"][0]["status"] == "satisfied"


def test_reference_plugin_uses_generated_sdk_without_handwritten_protocol() -> None:
    source = (
        PROJECT_ROOT
        / "examples"
        / "plugins"
        / "fictional-talent-tree"
        / "web"
        / "plugin.js"
    ).read_text(encoding="utf-8")

    assert "createKirinPlugin" in source
    assert "postMessage" not in source
    assert "addEventListener(\"message\"" not in source
    assert "pending" not in source
    assert "kirin-workbench-plugin" not in source
