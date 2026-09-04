from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.errors import InvalidRequestError, LimitExceededError, PluginError
from kirin_tor.limits import (
    MAX_PLUGIN_PREFERENCE_DEPTH,
    MAX_PLUGIN_PREFERENCE_VALUE_BYTES,
)
from kirin_tor.plugin_preferences import PluginPreferences
from kirin_tor.workspace import initialize


PLUGIN_ID = "community.preference-fixture"


def test_plugin_preferences_are_bounded_and_namespaced_by_workspace_and_plugin(
    tmp_path: Path,
) -> None:
    first_workspace = initialize(tmp_path / "first-workspace")
    second_workspace = initialize(tmp_path / "second-workspace")
    home = tmp_path / "user-state"
    first = PluginPreferences(first_workspace, home)

    saved = first.set(
        PLUGIN_ID,
        1,
        "ui.layout",
        {"compact": True, "columns": ["name", "value"]},
    )
    assert saved["status"] == "ok"
    assert first.get(PLUGIN_ID, 1, "ui.layout") == {
        "status": "ok",
        "key": "ui.layout",
        "found": True,
        "value": {"compact": True, "columns": ["name", "value"]},
    }
    assert PluginPreferences(second_workspace, home).get(
        PLUGIN_ID, 1, "ui.layout"
    )["found"] is False
    assert first.get("community.other-plugin", 1, "ui.layout")["found"] is False

    deleted = first.delete(PLUGIN_ID, 1, "ui.layout")
    assert deleted["removed"] is True
    assert first.get(PLUGIN_ID, 1, "ui.layout")["found"] is False
    assert first.clear(PLUGIN_ID) is True
    assert first.clear(PLUGIN_ID) is False


def test_plugin_preference_schema_change_resets_only_that_namespace(
    tmp_path: Path,
) -> None:
    workspace = initialize(tmp_path / "workspace")
    preferences = PluginPreferences(workspace, tmp_path / "user-state")
    preferences.set(PLUGIN_ID, 1, "ui.compact", True)

    assert preferences.get(PLUGIN_ID, 2, "ui.compact")["found"] is False
    stored = json.loads(next(preferences.directory.glob("*.json")).read_text())
    assert stored["preference_schema"] == 2
    assert stored["values"] == {}


def test_plugin_preferences_reject_unsafe_json_and_resource_overflow(
    tmp_path: Path,
) -> None:
    workspace = initialize(tmp_path / "workspace")
    preferences = PluginPreferences(workspace, tmp_path / "user-state")

    with pytest.raises(InvalidRequestError, match="preference key"):
        preferences.set(PLUGIN_ID, 1, "../outside", True)
    with pytest.raises(InvalidRequestError, match="finite"):
        preferences.set(PLUGIN_ID, 1, "ui.number", float("nan"))
    with pytest.raises(LimitExceededError, match="value exceeds"):
        preferences.set(
            PLUGIN_ID,
            1,
            "ui.large",
            "x" * (MAX_PLUGIN_PREFERENCE_VALUE_BYTES + 1),
        )

    nested: object = True
    for _ in range(MAX_PLUGIN_PREFERENCE_DEPTH + 1):
        nested = {"next": nested}
    with pytest.raises(LimitExceededError, match="nesting depth"):
        preferences.set(PLUGIN_ID, 1, "ui.deep", nested)


def test_plugin_preferences_fail_closed_on_corrupt_external_state(
    tmp_path: Path,
) -> None:
    workspace = initialize(tmp_path / "workspace")
    preferences = PluginPreferences(workspace, tmp_path / "user-state")
    preferences.set(PLUGIN_ID, 1, "ui.compact", True)
    path = next(preferences.directory.glob("*.json"))
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(PluginError, match="cannot read local Plugin preferences"):
        preferences.get(PLUGIN_ID, 1, "ui.compact")
