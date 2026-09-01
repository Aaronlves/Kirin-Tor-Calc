from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.errors import PluginError
from kirin_tor.plugin_manifest import (
    WORKSPACE_PLUGIN_LOCK,
    WORKSPACE_PLUGIN_REQUIREMENTS,
    canonical_plugin_sha256,
    load_plugin_manifest,
)
from kirin_tor.plugin_store import PluginManager
from kirin_tor.workspace import initialize


def _plugin(root: Path, *, plugin_id: str = "community.example-talents") -> Path:
    web = root / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><script src="plugin.js" type="module"></script>',
        encoding="utf-8",
    )
    (web / "plugin.js").write_text(
        'parent.postMessage({protocol:"kirin-workbench-plugin",api:1,type:"ready"}, "*");\n',
        encoding="utf-8",
    )
    manifest = {
        "schema": 1,
        "id": plugin_id,
        "name": "Example Talent Workbench",
        "version": "1.0.0",
        "api": "1",
        "description": "A fixture plugin.",
        "license": "MIT",
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
