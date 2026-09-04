from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kirin_tor.errors import PluginError
from kirin_tor.limits import (
    MAX_COMPARISON_VARIANTS,
    MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS,
    MAX_SCAN_POINTS,
    PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS,
)
from kirin_tor.plugin_manifest import (
    WORKSPACE_PLUGIN_LOCK,
    WORKSPACE_PLUGIN_REQUIREMENTS,
    canonical_plugin_sha256,
    load_plugin_manifest,
)
from kirin_tor.plugin_store import PluginManager
from kirin_tor.plugin_protocol import (
    PLUGIN_ACTIONS,
    PLUGIN_PERMISSIONS,
    plugin_protocol_descriptor,
)
from kirin_tor.workspace import initialize
from kirin_tor.package_authoring import add_path_package
from kirin_tor.package_manifest import current_feature_line


def _plugin(
    root: Path,
    *,
    plugin_id: str = "community.example-talents",
    required_interfaces: tuple[tuple[str, int], ...] = (),
    kirin_feature: str | None = None,
) -> Path:
    web = root / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><script src="plugin.js" type="module"></script>',
        encoding="utf-8",
    )
    (web / "plugin.js").write_text(
        'parent.postMessage({protocol:"kirin-workbench-plugin",api:2,type:"ready"}, "*");\n',
        encoding="utf-8",
    )
    manifest = {
        "schema": 2,
        "id": plugin_id,
        "name": "Example Talent Workbench",
        "version": "1.0.0",
        "api": "2",
        "description": "A fixture plugin.",
        "license": "MIT",
        "requires": {
            "kirin_feature": kirin_feature or current_feature_line(),
            "interfaces": [
                {"id": interface_id, "revision": revision}
                for interface_id, revision in required_interfaces
            ],
        },
        "contributes": {
            "renderers": [
                {
                    "id": f"{plugin_id}.talent-tree",
                    "title": "天赋树",
                    "entry": "web/index.html",
                    "priority": 50,
                    "match": {
                        "document_ids": ["skill_a"],
                        "document_id_prefixes": ["fictional_"],
                        "package_names": [],
                    },
                    "permissions": ["document.read", "source.navigate"],
                }
            ],
            "views": [
                {
                    "id": f"{plugin_id}.builds",
                    "title": "Build",
                    "entry": "web/index.html",
                    "permissions": ["workspace.summary"],
                }
            ],
            "tools": [
                {
                    "id": f"{plugin_id}.audit",
                    "title": "检查",
                    "entry": "web/index.html",
                    "permissions": ["document.read"],
                }
            ],
            "commands": [
                {
                    "id": f"{plugin_id}.open-builds",
                    "title": "打开 Build",
                    "description": "Open the contributed view.",
                    "action": "open-view",
                    "target": f"{plugin_id}.builds",
                }
            ],
            "profiles": [
                {
                    "id": f"{plugin_id}.authoring",
                    "title": "天赋创作",
                    "description": "Talent authoring layout.",
                    "views": ["documents", f"{plugin_id}.builds", "graph"],
                    "tools": [f"{plugin_id}.audit", "runs", "plugins"],
                    "default_view": "documents",
                    "document_focus_mode": "split",
                }
            ],
        },
    }
    (root / "kirin.plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return root


def _interface_package(root: Path, *, revision: int) -> Path:
    root.mkdir(parents=True)
    (root / "kirin.package.toml").write_text(
        f'''schema = 2
name = "community.interface-provider"
version = "1.0.0"
namespace = "interface_provider"
description = "Interface fixture"
license = "MIT"
requires_kirin = "{current_feature_line()}"

[interfaces."fictional.theorycraft-model"]
revision = {revision}
documents = ["interface_provider_contract"]
document_prefixes = []
''',
        encoding="utf-8",
    )
    entries = root / "entries"
    entries.mkdir()
    (entries / "contract.kirin").write_text(
        "@kirin 2\n@entry interface_provider_contract\n\n"
        "output value: dimensionless = 1\n",
        encoding="utf-8",
    )
    return root


def test_plugin_manifest_is_strict_and_digest_covers_static_assets(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugin")
    manifest = load_plugin_manifest(root)
    assert manifest.id == "community.example-talents"
    assert manifest.contributes.renderers[0].match.document_id_prefixes == ("fictional_",)
    before = canonical_plugin_sha256(root)
    (root / "web" / "plugin.js").write_text("// changed\n", encoding="utf-8")
    assert canonical_plugin_sha256(root) != before

    raw = json.loads((root / "kirin.plugin.json").read_text(encoding="utf-8"))
    raw["hook"] = "run-me"
    (root / "kirin.plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PluginError, match="unknown plugin manifest field"):
        load_plugin_manifest(root)


def test_plugin_manifest_accepts_granular_workbench_bridge_permissions(
    tmp_path: Path,
) -> None:
    root = _plugin(tmp_path / "plugin")
    raw = json.loads((root / "kirin.plugin.json").read_text(encoding="utf-8"))
    raw["contributes"]["renderers"][0]["permissions"] = [
        "workspace.summary",
        "model.read",
        "document.read",
        "draft.read",
        "draft.propose",
        "source.navigate",
        "operation.evaluate",
        "operation.explain",
        "operation.compare",
        "operation.scan",
        "operation.solve",
        "operation.analyze",
    ]
    (root / "kirin.plugin.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    manifest = load_plugin_manifest(root)

    assert manifest.contributes.renderers[0].permissions == tuple(
        raw["contributes"]["renderers"][0]["permissions"]
    )


def test_plugin_protocol_descriptor_is_the_self_consistent_public_contract() -> None:
    descriptor = plugin_protocol_descriptor()

    assert descriptor["api"] == "2"
    assert set(descriptor["permissions"]) == set(PLUGIN_PERMISSIONS)
    assert descriptor["actions"] == {
        name: dict(capability) for name, capability in sorted(PLUGIN_ACTIONS.items())
    }
    assert all(
        capability["permission"] in descriptor["permissions"]
        for capability in descriptor["actions"].values()
    )
    assert all(
        (capability["handler"] in {"host", "catalog"} and "operation" not in capability)
        or (capability["handler"] == "operation" and capability.get("operation"))
        for capability in descriptor["actions"].values()
    )
    assert descriptor["limits"]["max_comparison_variants"] == MAX_COMPARISON_VARIANTS == 8
    assert descriptor["limits"]["max_scan_points"] == MAX_SCAN_POINTS
    assert (
        descriptor["limits"]["standard_operation_timeout_seconds"]
        == PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS
    )
    assert (
        descriptor["limits"]["analysis_timeout_seconds"]
        == MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS
    )

    descriptor["actions"].clear()
    assert plugin_protocol_descriptor()["actions"]


def test_workbench_plugin_adapter_covers_every_declared_action_once() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "frontend"
        / "src"
        / "components"
        / "PluginSurface.tsx"
    ).read_text(encoding="utf-8")
    handled = re.findall(r'if \(action === "([a-z-]+)"\)', source)

    assert set(handled) == {
        name
        for name, capability in PLUGIN_ACTIONS.items()
        if capability["handler"] in {"host", "operation"}
    }
    assert len(handled) == len(set(handled))
    assert source.count("controller.operation(operationName(),") == sum(
        capability["handler"] == "operation" for capability in PLUGIN_ACTIONS.values()
    )
    assert "controller.modelCatalog(action, payload)" in source
    assert any(
        capability["handler"] == "catalog"
        for capability in PLUGIN_ACTIONS.values()
    )
    assert "MAX_COMPARISON_VARIANTS" not in source


def test_plugin_manifest_rejects_direct_write_and_unbounded_operation_permissions(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugin")
    raw = json.loads((root / "kirin.plugin.json").read_text(encoding="utf-8"))
    raw["contributes"]["renderers"][0]["permissions"] = ["operation.execute"]
    (root / "kirin.plugin.json").write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(PluginError, match="unknown plugin permission"):
        load_plugin_manifest(root)

    raw["contributes"]["renderers"][0]["permissions"] = ["source.write"]
    (root / "kirin.plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PluginError, match="unknown plugin permission"):
        load_plugin_manifest(root)


def test_plugin_manifest_rejects_unknown_targets_and_unsafe_entries(tmp_path: Path) -> None:
    root = _plugin(tmp_path / "plugin")
    raw = json.loads((root / "kirin.plugin.json").read_text(encoding="utf-8"))
    raw["contributes"]["commands"][0]["target"] = "community.missing.view"
    (root / "kirin.plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PluginError, match="targets unknown"):
        load_plugin_manifest(root)

    raw["contributes"]["commands"][0]["target"] = "community.example-talents.builds"
    raw["contributes"]["views"][0]["entry"] = "../outside.html"
    (root / "kirin.plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PluginError, match="stay under web"):
        load_plugin_manifest(root)


def test_local_plugin_install_enable_disable_and_safe_mode(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    source = _plugin(tmp_path / "plugin")
    approval_home = tmp_path / "approvals"
    manager = PluginManager(workspace, approval_home=approval_home)

    added = manager.add_path("talents", source)
    assert (workspace / WORKSPACE_PLUGIN_REQUIREMENTS).is_file()
    assert (workspace / WORKSPACE_PLUGIN_LOCK).is_file()
    assert added["plugins"][0]["status"] == "active"
    assert added["protocol"] == plugin_protocol_descriptor()
    assert added["plugins"][0]["approved"] is True
    assert len(added["contributions"]["renderers"]) == 1
    digest = added["plugins"][0]["content_sha256"]
    assert manager.asset(digest, "web/index.html").is_file()

    disabled = manager.set_enabled("talents", False)
    assert disabled["plugins"][0]["status"] == "disabled"
    assert disabled["contributions"]["views"] == []
    enabled = manager.set_enabled("talents", True)
    assert enabled["plugins"][0]["status"] == "active"

    safe = PluginManager(workspace, safe_mode=True, approval_home=approval_home).summary()
    assert safe["plugins"][0]["status"] == "safe-mode"
    assert all(not group for group in safe["contributions"].values())
    with pytest.raises(PluginError, match="not available"):
        PluginManager(workspace, safe_mode=True, approval_home=approval_home).asset(
            digest, "web/index.html"
        )
    (approval_home / "plugin-approvals.json").write_text("not-json", encoding="utf-8")
    safe_with_broken_user_state = PluginManager(
        workspace, safe_mode=True, approval_home=approval_home
    ).summary()
    assert safe_with_broken_user_state["plugins"][0]["status"] == "safe-mode"


def test_plugin_interfaces_gate_activation_with_explicit_diagnostics(tmp_path: Path) -> None:
    interface = (("fictional.theorycraft-model", 1),)

    missing_workspace = initialize(tmp_path / "missing-workspace")
    missing = PluginManager(
        missing_workspace, approval_home=tmp_path / "missing-approvals"
    ).add_path(
        "plugin",
        _plugin(tmp_path / "missing-plugin", required_interfaces=interface),
    )
    assert missing["plugins"][0]["status"] == "incompatible"
    assert missing["plugins"][0]["compatibility"]["interfaces"][0]["status"] == "missing"
    assert missing["contributions"]["renderers"] == []

    mismatch_workspace = initialize(tmp_path / "mismatch-workspace")
    add_path_package(
        mismatch_workspace,
        "provider",
        _interface_package(tmp_path / "mismatch-package", revision=2),
    )
    mismatch = PluginManager(
        mismatch_workspace, approval_home=tmp_path / "mismatch-approvals"
    ).add_path(
        "plugin",
        _plugin(tmp_path / "mismatch-plugin", required_interfaces=interface),
    )
    compatibility = mismatch["plugins"][0]["compatibility"]
    assert mismatch["plugins"][0]["status"] == "incompatible"
    assert compatibility["interfaces"][0]["status"] == "revision-mismatch"
    assert compatibility["interfaces"][0]["providers"][0]["interface"]["revision"] == 2

    satisfied_workspace = initialize(tmp_path / "satisfied-workspace")
    add_path_package(
        satisfied_workspace,
        "provider",
        _interface_package(tmp_path / "satisfied-package", revision=1),
    )
    satisfied = PluginManager(
        satisfied_workspace, approval_home=tmp_path / "satisfied-approvals"
    ).add_path(
        "plugin",
        _plugin(tmp_path / "satisfied-plugin", required_interfaces=interface),
    )
    assert satisfied["plugins"][0]["status"] == "active"
    assert satisfied["plugins"][0]["compatibility"]["status"] == "satisfied"
    assert satisfied["contributions"]["renderers"]

    feature_workspace = initialize(tmp_path / "feature-workspace")
    feature = PluginManager(
        feature_workspace, approval_home=tmp_path / "feature-approvals"
    ).add_path(
        "plugin",
        _plugin(tmp_path / "feature-plugin", kirin_feature="99.0"),
    )
    assert feature["plugins"][0]["status"] == "incompatible"
    assert (
        feature["plugins"][0]["compatibility"]["kirin_feature"]["status"]
        == "kirin-incompatible"
    )


def test_workspace_files_cannot_approve_unseen_executable_content(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    source = _plugin(tmp_path / "plugin")
    approved_home = tmp_path / "approved"
    installed = PluginManager(workspace, approval_home=approved_home).add_path("talents", source)
    assert installed["plugins"][0]["status"] == "active"

    unapproved = PluginManager(workspace, approval_home=tmp_path / "fresh-user").summary()
    assert unapproved["plugins"][0]["status"] == "unapproved"
    assert unapproved["plugins"][0]["active"] is False
    assert unapproved["contributions"]["renderers"] == []

    PluginManager(workspace, approval_home=approved_home).set_enabled("talents", False)
    fresh_manager = PluginManager(workspace, approval_home=tmp_path / "fresh-user")
    with pytest.raises(PluginError, match="not approved"):
        fresh_manager.set_enabled("talents", True)


def test_plugin_update_locks_and_approves_a_new_snapshot(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    source = _plugin(tmp_path / "plugin")
    manager = PluginManager(workspace, approval_home=tmp_path / "approvals")
    before = manager.add_path("talents", source)["plugins"][0]["content_sha256"]
    (source / "web" / "plugin.js").write_text("// version two\n", encoding="utf-8")
    raw = json.loads((source / "kirin.plugin.json").read_text(encoding="utf-8"))
    raw["version"] = "1.0.1"
    (source / "kirin.plugin.json").write_text(json.dumps(raw), encoding="utf-8")

    updated = manager.update_path("talents")
    after = updated["plugins"][0]["content_sha256"]
    assert after != before
    assert updated["plugins"][0]["version"] == "1.0.1"
    assert updated["plugins"][0]["status"] == "active"
    assert manager.verify()["plugins"][0]["content_sha256"] == after


def test_plugin_cache_tampering_disables_contributions(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    manager = PluginManager(workspace, approval_home=tmp_path / "approvals")
    added = manager.add_path("talents", _plugin(tmp_path / "plugin"))
    digest = added["plugins"][0]["content_sha256"]
    (workspace / ".kirin" / "plugins" / digest / "web" / "plugin.js").write_text(
        "// tampered\n", encoding="utf-8"
    )
    summary = manager.summary()
    assert summary["plugins"][0]["status"] == "invalid"
    assert summary["contributions"]["renderers"] == []
    with pytest.raises(PluginError, match="failed its content digest"):
        manager.verify()


def test_safe_mode_keeps_the_core_available_with_broken_plugin_control_files(
    tmp_path: Path,
) -> None:
    workspace = initialize(tmp_path / "workspace")
    (workspace / WORKSPACE_PLUGIN_REQUIREMENTS).write_text("not valid toml = [", encoding="utf-8")
    summary = PluginManager(
        workspace,
        safe_mode=True,
        approval_home=tmp_path / "broken-approval-is-not-read",
    ).summary()
    assert summary["safe_mode"] is True
    assert summary["plugins"] == []
    assert summary["contributions"]["views"] == []
    assert "invalid kirin.plugins.toml" in summary["error"]
