from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from kirin_tor.errors import UnsupportedError
from kirin_tor.process_runtime import (
    ContinuousDecisionChoice,
    run_process_scenario,
)
from kirin_tor.workspace import Workspace, initialize


def _workspace(tmp_path: Path, source: str) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(source, encoding="utf-8")
    return Workspace.load(root)


def test_decision_can_be_triggered_after_a_public_event(tmp_path: Path) -> None:
    source = """@kirin 2
@entry after_event

process counter:
  state value: count = 0
  event input pulse()
  event input add()
  on add():
    next value = value + 1
  observe current: count = value

scenario trial:
  phases:
    - event
    - decision
  use actor = counter:
  action add:
    send actor.add() phase decision
  at 1 second phase event:
    send actor.pulse()
  decide after actor.pulse phase decision:
    - add
  measure final_value: count = final(actor.current)
  bounds:
    horizon = 2 second
    maximum_events = 2
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    result = run_process_scenario(
        workspace.scenarios["after_event.trial"], workspace.units
    )
    assert result.decisions == ((Fraction(1), "add"),)
    assert dict(result.observations)["actor.current"] == 1


def test_decision_can_be_triggered_by_an_event_state_crossing(tmp_path: Path) -> None:
    source = """@kirin 2
@entry crossing

dimension vitality
unit hp = vitality

process actor:
  state health: hp = 10 hp
  event input hit(amount: hp)
  event input heal(amount: hp)
  on hit(amount):
    next health = health - amount
  on heal(amount):
    next health = health + amount
  observe current: hp = health
  observe critical: boolean = health <= 4 hp

scenario trial:
  phases:
    - incoming
    - decision
  use actor = actor:
  action heal:
    send actor.heal(amount = 1 hp) phase decision
  at 1 second phase incoming:
    send actor.hit(amount = 6 hp)
  decide when actor.critical phase decision:
    - heal
  measure final_health: hp = final(actor.current)
  bounds:
    horizon = 2 second
    maximum_events = 2
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    result = run_process_scenario(
        workspace.scenarios["crossing.trial"], workspace.units
    )
    assert result.decisions == ((Fraction(1), "heal"),)
    assert dict(result.observations)["actor.current"] == 5


def test_runtime_accepts_bounded_exact_continuous_action_times(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry continuous

process counter:
  state value: count = 0
  event input add()
  on add():
    next value = value + 1
  observe current: count = value

scenario trial:
  phases:
    - decision
  use actor = counter:
  action add:
    send actor.add() phase decision
  decide continuously up to 2 times from 0 second until 2 second phase decision:
    - add
  measure final_value: count = final(actor.current)
  bounds:
    horizon = 2 second
    maximum_events = 2
    maximum_decisions = 2
    maximum_branches = 32
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["continuous.trial"]
    result = run_process_scenario(
        scenario,
        workspace.units,
        continuous_choices=(
            ContinuousDecisionChoice(0, Fraction(1, 3), "add"),
            ContinuousDecisionChoice(0, Fraction(7, 4), "add"),
        ),
    )
    assert result.decisions == (
        (Fraction(1, 3), "add"),
        (Fraction(7, 4), "add"),
    )
    assert dict(result.observations)["actor.current"] == 2


def test_affine_flow_condition_crossing_uses_its_exact_time(tmp_path: Path) -> None:
    source = """@kirin 2
@entry affine_crossing

dimension resource
unit resource = resource
unit resource_per_time = resource / time

process pool:
  input rate: resource_per_time = 1 resource_per_time
  state amount: resource = 0 resource
  state marked_at: time = 0 second
  flow amount(current, elapsed) = current + elapsed * rate
  event input mark()
  on mark():
    next marked_at = event.time
  observe current: resource = amount
  observe time: time = marked_at

scenario trial:
  phases:
    - decision
  use actor = pool:
  action mark:
    send actor.mark() phase decision
  decide when actor.current >= 3 resource phase decision:
    - mark
  measure mark_time: time = final(actor.time)
  bounds:
    horizon = 5 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    result = run_process_scenario(
        workspace.scenarios["affine_crossing.trial"], workspace.units
    )
    assert result.decisions == ((Fraction(3), "mark"),)
    assert dict(result.observations)["actor.time"] == 3


def test_unproved_flow_condition_crossing_is_rejected(tmp_path: Path) -> None:
    source = """@kirin 2
@entry nonlinear_crossing

dimension resource
unit resource = resource
unit resource_per_time = resource / time

process pool:
  state amount: resource = 0 resource
  flow amount(current, elapsed) = min(10 resource, current + elapsed * 1 resource_per_time)
  event input noop()
  observe current: resource = amount

scenario trial:
  phases:
    - decision
  use actor = pool:
  action noop:
    send actor.noop() phase decision
  decide when actor.current >= 1 resource phase decision:
    - noop
  bounds:
    horizon = 2 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    with pytest.raises(UnsupportedError, match="not proven affine"):
        run_process_scenario(
            workspace.scenarios["nonlinear_crossing.trial"], workspace.units
        )
