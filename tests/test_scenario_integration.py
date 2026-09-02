from __future__ import annotations

from pathlib import Path
import re

import pytest

from kirin_tor.errors import SchemaError
from kirin_tor.kirin_syntax import parse_kirin_source, render_kirin_document
from kirin_tor.workspace import Workspace, initialize


def _brewmaster_source() -> str:
    project_root = Path(__file__).resolve().parents[1]
    document = (project_root / "docs" / "bounded-process-paper-models.md").read_text(
        encoding="utf-8"
    )
    block = next(
        value
        for value in re.findall(r"```text\n(.*?)```", document, re.DOTALL)
        if "scenario brewmaster_survival" in value
    )
    return "@kirin 2\n@entry brewmaster\n\n" + block


def test_brewmaster_scenario_and_analysis_parse_lower_and_round_trip(tmp_path: Path) -> None:
    source = _brewmaster_source()
    parsed = parse_kirin_source(source, Path("brewmaster.kirin"))
    assert [item.id for item in parsed.scenario_asts] == ["brewmaster_survival"]
    assert [item.id for item in parsed.analysis_asts] == ["latest_death"]
    rendered = render_kirin_document(parsed)
    reparsed = parse_kirin_source(rendered, Path("rendered.kirin"))
    assert reparsed.scenario_asts == parsed.scenario_asts
    assert reparsed.analysis_asts == parsed.analysis_asts

    root = initialize(tmp_path / "scenario-workspace")
    (root / "entries" / "brewmaster.kirin").write_text(source, encoding="utf-8")
    workspace = Workspace.load(root)
    scenario = workspace.scenarios["brewmaster.brewmaster_survival"]
    analysis = workspace.analyses["brewmaster.latest_death"]
    assert [phase.id for phase in scenario.phases] == [
        "periodic_tick",
        "incoming",
        "readiness",
        "decision",
    ]
    assert scenario.bounds.horizon == 60
    assert analysis.scenario_id == scenario.qualified_id
    assert analysis.objective_ids == (
        "smoothest_health",
        "most_purified",
        "longest_survival",
    )
    assert [item.id for item in scenario.objectives] == list(analysis.objective_ids)


def test_scenario_requires_complete_local_phase_mapping(tmp_path: Path) -> None:
    source = _brewmaster_source().replace("    phase readiness = readiness\n", "")
    root = initialize(tmp_path / "missing-phase")
    (root / "entries" / "brewmaster.kirin").write_text(source, encoding="utf-8")
    with pytest.raises(SchemaError, match="phase bindings do not match"):
        Workspace.load(root)


def test_scenario_preflights_static_event_fuel(tmp_path: Path) -> None:
    source = _brewmaster_source().replace("maximum_events = 1000", "maximum_events = 10")
    root = initialize(tmp_path / "event-fuel")
    (root / "entries" / "brewmaster.kirin").write_text(source, encoding="utf-8")
    with pytest.raises(SchemaError, match="external schedules alone exceed"):
        Workspace.load(root)


def test_scenario_rejects_same_batch_cross_event_state_writes(tmp_path: Path) -> None:
    source = """@kirin 2
@entry conflict

process counter:
  state value: count = 0
  event input first()
  event input second()
  on first():
    next value = value + 1
  on second():
    next value = value + 2
  observe current: count = value

scenario collision:
  phases:
    - event
  use target = counter:
  at 0 second phase event:
    send target.first()
    send target.second()
  bounds:
    horizon = 1 second
    maximum_events = 2
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    root = initialize(tmp_path / "batch-conflict")
    (root / "entries" / "conflict.kirin").write_text(source, encoding="utf-8")
    with pytest.raises(SchemaError, match="state 'value'.*more than one event"):
        Workspace.load(root)
