from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from kirin_tor.errors import SchemaError, UnsupportedError
from kirin_tor.kirin_syntax import parse_kirin_source, render_kirin_document
from kirin_tor.process_measure import evaluate_process_measures
from kirin_tor.process_runtime import run_process_scenario
from kirin_tor.workspace import Workspace, initialize


def _workspace(tmp_path: Path, source: str) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(source, encoding="utf-8")
    return Workspace.load(root)


def test_typed_measures_use_only_public_trajectory_and_output_events(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry measures

dimension vitality "Vitality"
unit hp = vitality
unit hp_squared = vitality ** 2

process actor:
  state health: hp = 10 hp
  phase public
  event input hit(amount: hp)
  event input purify()
  event output purified(amount: hp)
  on hit(amount):
    next health = health - amount
  on purify():
    emit purified(amount = 2 hp) phase public
  observe remaining_health: hp = health

scenario trial:
  phases:
    - incoming
    - public
  use actor = actor:
    phase public = public
  at 1 second phase incoming:
    send actor.hit(amount = 3 hp)
  at 2 second phase incoming:
    send actor.purify()
  at 3 second phase incoming:
    send actor.hit(amount = 4 hp)
  measure final_health: hp = final(actor.remaining_health)
  measure minimum_health: hp = minimum_over_time(actor.remaining_health)
  measure minimum_while_safe: hp = minimum_where(if_else(actor.remaining_health < 8 hp, actor.remaining_health, 100 hp), actor.remaining_health >= 5 hp, default = -1 hp)
  measure minimum_while_impossible: hp = minimum_where(actor.remaining_health, actor.remaining_health < 0 hp, default = 99 hp)
  measure maximum_health: hp = maximum_over_time(actor.remaining_health)
  measure health_range: hp = maximum_health - minimum_health
  measure health_drawdown: hp = maximum_drawdown(actor.remaining_health)
  measure health_variation: hp = total_variation(actor.remaining_health)
  measure health_variance: hp_squared = variance_over_time(actor.remaining_health)
  measure total_purified: hp = sum_events(actor.purified.amount)
  measure purification_count: count = count_events(actor.purified)
  measure low_health_time: time = duration_where(actor.remaining_health < 8 hp)
  measure critical_time: time = first_time(actor.remaining_health < 5 hp, default = horizon)
  measure never_zero: time = first_time(actor.remaining_health == 0 hp, default = horizon)
  measure health_before_critical: hp = last_before(actor.remaining_health, actor.remaining_health < 5 hp, default = -1 hp)
  measure health_before_missing: hp = last_before(actor.remaining_health, actor.remaining_health == 0 hp, default = actor.remaining_health)
  measure no_preceding_health: hp = last_before(actor.remaining_health, actor.remaining_health <= 10 hp, default = 99 hp)
  measure survival_time: time = stop_time()
  bounds:
    horizon = 4 second
    maximum_events = 4
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    parsed = parse_kirin_source(source, Path("measures.kirin"))
    rendered = render_kirin_document(parsed)
    assert (
        parse_kirin_source(rendered, Path("rendered.kirin")).scenario_asts
        == parsed.scenario_asts
    )
    scenario = workspace.scenarios["measures.trial"]
    result = run_process_scenario(scenario, workspace.units)
    values = dict(evaluate_process_measures(scenario, result, workspace.units))
    assert values == {
        "final_health": Fraction(3),
        "minimum_health": Fraction(3),
        "minimum_while_safe": Fraction(7),
        "minimum_while_impossible": Fraction(99),
        "maximum_health": Fraction(10),
        "health_range": Fraction(7),
        "health_drawdown": Fraction(7),
        "health_variation": Fraction(7),
        "health_variance": Fraction(99, 16),
        "total_purified": Fraction(2),
        "purification_count": Fraction(1),
        "low_health_time": Fraction(3),
        "critical_time": Fraction(3),
        "never_zero": Fraction(4),
        "health_before_critical": Fraction(7),
        "health_before_missing": Fraction(3),
        "no_preceding_health": Fraction(99),
        "survival_time": Fraction(4),
    }
    assert [(event.event_id, event.time) for event in result.output_events] == [
        ("purified", Fraction(2))
    ]
    assert result.observation_samples[0].phase == "initial"
    assert result.observation_samples[-1].time == 4


def test_first_time_requires_explicit_missing_value(tmp_path: Path) -> None:
    source = """@kirin 2
@entry invalid

process flag:
  state active: boolean = false
  observe is_active: boolean = active

scenario trial:
  phases:
    - event
  use actor = flag:
  measure activation: time = first_time(actor.is_active)
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    with pytest.raises(SchemaError, match="explicit default"):
        _workspace(tmp_path, source)


@pytest.mark.parametrize("operation", ["minimum_where", "last_before"])
def test_conditional_value_measure_requires_explicit_missing_value(
    tmp_path: Path, operation: str
) -> None:
    source = f"""@kirin 2
@entry invalid

process actor:
  state value: count = 1
  observe current: count = value

scenario trial:
  phases:
    - event
  use actor = actor:
  measure selected: count = {operation}(actor.current, actor.current > 0)
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    with pytest.raises(SchemaError, match="default"):
        _workspace(tmp_path, source)


def test_interval_measure_refuses_unproved_unrestricted_flow(tmp_path: Path) -> None:
    source = """@kirin 2
@entry flowing

dimension resource "Resource"
unit resource = resource

process pool:
  state amount: resource = 0 resource
  flow amount(current, elapsed) = current + elapsed * 1 resource / second
  observe current: resource = amount

scenario trial:
  phases:
    - event
  use actor = pool:
  measure maximum_amount: resource = maximum_over_time(actor.current)
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["flowing.trial"]
    result = run_process_scenario(scenario, workspace.units)
    with pytest.raises(UnsupportedError, match="cannot claim an exact result"):
        evaluate_process_measures(scenario, result, workspace.units)
