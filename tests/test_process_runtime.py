from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import re

import pytest

from kirin_tor.errors import ProcessExecutionError, ProcessFuelError
from kirin_tor.process_runtime import run_process_scenario
from kirin_tor.workspace import Workspace, initialize


def _workspace(tmp_path: Path, source: str) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(source, encoding="utf-8")
    return Workspace.load(root)


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


def test_deterministic_brewmaster_run_uses_phase_order_and_damage_reducer(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, _brewmaster_source())
    scenario = workspace.scenarios["brewmaster.brewmaster_survival"]
    result = run_process_scenario(
        scenario,
        workspace.units,
        selector=lambda _index, _time, _schedule, _available, _values: "wait",
    )

    assert result.elapsed == 3
    assert result.stopped is True
    assert result.stop_reason == "condition"
    assert dict(result.observations)["actor.alive"] is False
    assert dict(result.observations)["brew.count"] == 2
    handled_at_three = [
        item
        for item in result.trace
        if item.time == 3 and item.kind == "handled" and item.member_id == "incoming_damage"
    ]
    assert len(handled_at_three) == 1
    assert len(dict(handled_at_three[0].details)["sources"].split(",")) == 2

    replay = run_process_scenario(
        scenario,
        workspace.units,
        selector=lambda _index, _time, _schedule, _available, _values: "wait",
    )
    assert replay == result


def test_flow_and_sequential_keyed_schedule_use_exact_time(tmp_path: Path) -> None:
    source = """@kirin 2
@entry flow

dimension resource
unit resource = resource
unit resource_per_time = resource / time

process reservoir:
  input rate: resource_per_time
  state amount: resource = 0 resource in 0 resource..100 resource
  event input start()
  event internal reset()
  key reset_slot
  phase readiness
  flow amount(current, elapsed) = min(100 resource, current + rate * elapsed)
  on start():
    replace reset() after 3 second phase readiness key reset_slot
  on reset():
    next amount = 0 resource
  observe current: resource = amount

scenario exact:
  phases:
    - external
    - readiness
  use actor = reservoir:
    rate = 10 resource_per_time
    phase readiness = readiness
  at 0 second phase external:
    send actor.start()
  bounds:
    horizon = 5 second
    maximum_events = 3
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    result = run_process_scenario(workspace.scenarios["flow.exact"], workspace.units)
    assert result.elapsed == 5
    assert dict(result.observations)["actor.current"] == 20
    assert any(item.kind == "replace" and item.time == 0 for item in result.trace)
    assert any(item.kind == "state" and item.time == 3 for item in result.trace)


def test_dynamic_scheduling_exhausts_event_fuel_without_partial_success(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry fuel

process pulse:
  event input start()
  event internal again()
  key next_pulse
  phase tick
  on start():
    schedule again() after 1 second phase tick key next_pulse
  on again():
    schedule again() after 1 second phase tick key next_pulse
  observe alive: boolean = true

scenario bounded:
  phases:
    - tick
  use actor = pulse:
    phase tick = tick
  at 0 second phase tick:
    send actor.start()
  bounds:
    horizon = 10 second
    maximum_events = 3
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    with pytest.raises(ProcessFuelError, match="maximum_events exhausted at 4/3"):
        run_process_scenario(workspace.scenarios["fuel.bounded"], workspace.units)


def test_fixed_policy_selecting_unavailable_process_action_fails(tmp_path: Path) -> None:
    source = """@kirin 2
@entry guard

process bank:
  state amount: count = 0
  action spend() when amount >= 1
  on spend():
    next amount = amount - 1
  observe current: count = amount

scenario choice:
  phases:
    - decision
  use actor = bank:
  action spend:
    send actor.spend() phase decision
  decide every 1 second from 0 second until 0 second phase decision:
    - spend
    - wait
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 2
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    with pytest.raises(ProcessExecutionError, match="Process action 'spend' is unavailable"):
        run_process_scenario(
            workspace.scenarios["guard.choice"],
            workspace.units,
            selector=lambda *_arguments: "spend",
        )
