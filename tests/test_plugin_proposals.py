from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kirin_tor.errors import ProposalInvalidError, ProposalStaleError
from kirin_tor.model_catalog import model_revision
from kirin_tor.package_authoring import add_path_package
from kirin_tor.plugin_proposals import validate_plugin_proposal
from kirin_tor.templates import list_templates
from kirin_tor.workspace import Workspace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PACKAGE = PROJECT_ROOT / "examples" / "packages" / "fictional-models"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _package_template(workspace: Workspace) -> str:
    return next(
        item.value
        for item in list_templates(
            workspace.root,
            package_resolution=workspace.package_resolution,
        )
        if item.origin == "package" and item.template_id == "build"
    )


def test_plugin_proposal_validates_one_atomic_multi_document_candidate_without_writing(
    example_workspace: Path,
) -> None:
    add_path_package(example_workspace, "fictional_models", EXAMPLE_PACKAGE)
    workspace = Workspace.load(example_workspace)
    combo_path = example_workspace / "entries" / "组合模型.kirin"
    combo_source = combo_path.read_text(encoding="utf-8")
    replacement = combo_source + "\n// Plugin proposal candidate\n"
    created_source = (
        '@kirin 2\n@entry plugin_created "Plugin Created"\n\n'
        'output value "Value": dimensionless = 2\n'
    )
    request = {
        "revision": model_revision(workspace),
        "title": "Create one Build and update its companion",
        "description": "A single reviewed transaction.",
        "changes": [
            {
                "kind": "create-from-template",
                "template": _package_template(workspace),
                "document_id": "plugin_build",
                "bindings": {"coefficient": "0.5"},
            },
            {
                "kind": "create-document",
                "document_id": "plugin_created",
                "text": created_source,
            },
            {
                "kind": "replace-document",
                "key": "entries/组合模型.kirin",
                "base_sha256": _sha256(combo_source),
                "text": replacement,
            },
        ],
    }

    result = validate_plugin_proposal(workspace, request, {})

    assert result["status"] == "ok"
    assert [item["kind"] for item in result["changes"]] == [
        "create-from-template",
        "create-document",
        "replace-document",
    ]
    template_change = result["changes"][0]
    assert template_change["bindings"] == {"coefficient": "0.5"}
    assert template_change["title"] == "虚构 Build 模板"
    assert "input coefficient" in template_change["text"]
    assert "= 0.5 in 0..1" in template_change["text"]
    assert "@template-bind" not in template_change["text"]
    assert result["changes"][1]["title"] == "Plugin Created"
    assert result["changes"][2]["base_text"] == combo_source
    assert not (example_workspace / "entries" / "plugin_build.kirin").exists()
    assert not (example_workspace / "entries" / "plugin_created.kirin").exists()
    assert combo_path.read_text(encoding="utf-8") == combo_source

    assert validate_plugin_proposal(workspace, request, {}) == result


def test_plugin_proposal_uses_the_current_unsaved_overlay_as_its_replace_baseline(
    example_workspace: Path,
) -> None:
    path = example_workspace / "entries" / "组合模型.kirin"
    disk_source = path.read_text(encoding="utf-8")
    overlay_source = disk_source + "\n// current Workbench draft\n"
    overlays = {path: overlay_source}
    workspace = Workspace.load_with_overlays(example_workspace, overlays)
    candidate = overlay_source + "// proposed addition\n"

    result = validate_plugin_proposal(
        workspace,
        {
            "revision": model_revision(workspace),
            "title": "Extend current draft",
            "changes": [
                {
                    "kind": "replace-document",
                    "key": "entries/组合模型.kirin",
                    "base_sha256": _sha256(overlay_source),
                    "text": candidate,
                }
            ],
        },
        overlays,
    )

    assert result["changes"][0]["base_text"] == overlay_source
    assert result["changes"][0]["text"] == candidate
    assert path.read_text(encoding="utf-8") == disk_source


def test_plugin_proposal_rejects_stale_duplicate_or_invalid_transactions(
    example_workspace: Path,
) -> None:
    workspace = Workspace.load(example_workspace)
    revision = model_revision(workspace)
    combo_source = (
        example_workspace / "entries" / "组合模型.kirin"
    ).read_text(encoding="utf-8")

    with pytest.raises(ProposalStaleError, match="obsolete"):
        validate_plugin_proposal(
            workspace,
            {
                "revision": "0" * 64,
                "title": "Stale",
                "changes": [
                    {
                        "kind": "create-document",
                        "document_id": "stale_candidate",
                        "text": "@kirin 2\n@entry stale_candidate\n",
                    }
                ],
            },
            {},
        )

    with pytest.raises(ProposalStaleError, match="baseline changed"):
        validate_plugin_proposal(
            workspace,
            {
                "revision": revision,
                "title": "Wrong baseline",
                "changes": [
                    {
                        "kind": "replace-document",
                        "key": "entries/组合模型.kirin",
                        "base_sha256": "0" * 64,
                        "text": combo_source,
                    }
                ],
            },
            {},
        )

    duplicate = {
        "kind": "create-document",
        "document_id": "duplicate_candidate",
        "text": (
            "@kirin 2\n@entry duplicate_candidate\n\n"
            "output value: dimensionless = 1\n"
        ),
    }
    with pytest.raises(ProposalInvalidError, match="same document"):
        validate_plugin_proposal(
            workspace,
            {
                "revision": revision,
                "title": "Duplicate target",
                "changes": [duplicate, duplicate],
            },
            {},
        )

    with pytest.raises(ProposalInvalidError):
        validate_plugin_proposal(
            workspace,
            {
                "revision": revision,
                "title": "Invalid source",
                "changes": [
                    {
                        "kind": "create-document",
                        "document_id": "invalid_candidate",
                        "text": (
                            "@kirin 2\n@entry invalid_candidate\n\n"
                            "output value: damage = missing.value\n"
                        ),
                    }
                ],
            },
            {},
        )
