from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import re

from kirin_tor.process_analysis import (
    CompareAnalysisResult,
    CycleAnalysisResult,
    OptimizeAnalysisResult,
    ReachAnalysisResult,
    RunAnalysisResult,
    SteadyAnalysisResult,
    execute_process_analysis,
)
from kirin_tor.cli import app
from kirin_tor.records import replay
from kirin_tor.workspace import Workspace, initialize
from conftest import make_cli_runner


runner = make_cli_runner()


def _workspace(tmp_path: Path, source: str) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(source, encoding="utf-8")
    return Workspace.load(root)


def test_random_run_and_reach_preserve_exact_finite_probabilities(tmp_path: Path) -> None:
    source = """@kirin 2
@entry random

process coin:
  input chance: probability = 1/4
  state hit: boolean = false
  event input flip()
  on flip():
    branch outcome independent:
      probability chance:
        next hit = true
      probability 1 - chance:
        next hit = false
  observe did_hit: boolean = hit

scenario one_flip:
  phases:
    - event
  use actor = coin:
  at 0 second phase event:
    send actor.flip()
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 4
    maximum_entities = 1

analysis distribution:
  using = one_flip
  operation = run

analysis hit_chance:
  using = one_flip
  operation = reach
  target = actor.did_hit
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["random.one_flip"]
    run = execute_process_analysis(
        workspace.analyses["random.distribution"], scenario, workspace.units
    )
    assert isinstance(run, RunAnalysisResult)
    assert sorted(item.probability for item in run.outcomes) == [
        Fraction(1, 4),
        Fraction(3, 4),
    ]
    assert sum((item.probability for item in run.outcomes), Fraction(0)) == 1

    reach = execute_process_analysis(
        workspace.analyses["random.hit_chance"], scenario, workspace.units
    )
    assert isinstance(reach, ReachAnalysisResult)
    assert reach.probability == Fraction(1, 4)


def test_source_policies_drive_run_and_compare_without_host_callbacks(tmp_path: Path) -> None:
    source = """@kirin 2
@entry policies

process counter:
  state value: count = 0
  event input add()
  on add():
    next value = value + 1
  observe current: count = value

scenario choice:
  phases:
    - decision
  use actor = counter:
  action add:
    send actor.add() phase decision
  policy add_once:
    sequence:
      - add
  policy wait_once:
    otherwise wait
  decide every 1 second from 0 second until 0 second phase decision:
    - add
    - wait
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 4
    maximum_entities = 1

analysis add_run:
  using = choice
  operation = run
  policy = add_once

analysis comparison:
  using = choice
  operation = compare
  policies:
    - add_once
    - wait_once
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["policies.choice"]
    run = execute_process_analysis(
        workspace.analyses["policies.add_run"], scenario, workspace.units
    )
    assert isinstance(run, RunAnalysisResult)
    assert dict(run.outcomes[0].result.observations)["actor.current"] == 1

    comparison = execute_process_analysis(
        workspace.analyses["policies.comparison"], scenario, workspace.units
    )
    assert isinstance(comparison, CompareAnalysisResult)
    values = {
        item.policy_id: dict(item.result.outcomes[0].result.observations)[
            "actor.current"
        ]
        for item in comparison.policies
    }
    assert values == {"add_once": Fraction(1), "wait_once": Fraction(0)}


def test_bounded_optimizer_finds_a_globally_best_brewmaster_timing(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    document = (project_root / "docs" / "bounded-process-paper-models.md").read_text(
        encoding="utf-8"
    )
    block = next(
        value
        for value in re.findall(r"```text\n(.*?)```", document, re.DOTALL)
        if "scenario brewmaster_survival" in value
    )
    workspace = _workspace(tmp_path, "@kirin 2\n@entry brew\n\n" + block)
    scenario = workspace.scenarios["brew.brewmaster_survival"]
    result = execute_process_analysis(
        workspace.analyses["brew.latest_death"], scenario, workspace.units
    )
    assert isinstance(result, OptimizeAnalysisResult)
    assert result.explored_branches <= scenario.bounds.maximum_branches
    assert [item.objective_id for item in result.objectives] == [
        "smoothest_health",
        "most_purified",
        "longest_survival",
    ]
    longest = result.objectives[-1]
    assert longest.best.elapsed >= 3
    assert longest.objective_values[0] == dict(longest.measures)["survival_time"]
    assert longest.proof.level == "best_found"
    assert longest.proof.tolerance == Fraction(1, 4)
    assert longest.proof.time_grid is None
    assert any(time.denominator != 1 for time, _choice in longest.best.decisions)
    assert set(dict(longest.measures)) == {
        "minimum_health",
        "health_variation",
        "total_purified",
        "survival_time",
        "remaining_charges",
    }


def test_named_objectives_apply_constraints_and_optimize_independently(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry objectives

process counter:
  state value: count = 0
  event input add()
  on add():
    next value = value + 1
  observe current: count = value

scenario choice:
  phases:
    - decision
  use actor = counter:
  action add:
    send actor.add() phase decision
  decide every 1 second from 0 second until 1 second phase decision:
    - add
    - wait
  measure final_value: count = final(actor.current)
  measure additions: count = final(decision_count)
  objective highest_bounded:
    maximize final_value
    then minimize additions
    require final_value <= 1
  objective fewest_additions:
    minimize final_value
    then minimize additions
  bounds:
    horizon = 1 second
    maximum_events = 2
    maximum_decisions = 2
    maximum_branches = 16
    maximum_entities = 1

analysis optimize_both:
  using = choice
  operation = optimize
  objectives:
    - highest_bounded
    - fewest_additions
"""
    workspace = _workspace(tmp_path, source)
    result = execute_process_analysis(
        workspace.analyses["objectives.optimize_both"],
        workspace.scenarios["objectives.choice"],
        workspace.units,
    )
    assert isinstance(result, OptimizeAnalysisResult)
    by_id = {item.objective_id: item for item in result.objectives}
    assert dict(by_id["highest_bounded"].measures)["final_value"] == 1
    assert by_id["highest_bounded"].constraints == (True,)
    assert dict(by_id["fewest_additions"].measures)["final_value"] == 0
    assert all(item.proof.level == "exact_global" for item in result.objectives)


def test_continuous_time_search_uses_exact_non_grid_runtime_times_and_is_labeled(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry continuous_search

process marker:
  state marked: boolean = false
  state marked_at: time = 0 second
  event input mark()
  on mark() when not marked:
    next marked = true
    next marked_at = event.time
  observe time: time = marked_at

scenario trial:
  phases:
    - decision
  use actor = marker:
  action mark:
    send actor.mark() phase decision
  decide continuously up to 1 time from 0 second until 1 second phase decision:
    - mark
  measure mark_time: time = final(actor.time)
  measure timing_error: time = abs(mark_time - 1/4 second)
  objective closest:
    minimize timing_error
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 32
    maximum_entities = 1

analysis search:
  using = trial
  operation = optimize
  objectives:
    - closest
  search:
    method = adaptive_dyadic
    time_tolerance = 1/16 second
    maximum_evaluations = 20
"""
    workspace = _workspace(tmp_path, source)
    result = execute_process_analysis(
        workspace.analyses["continuous_search.search"],
        workspace.scenarios["continuous_search.trial"],
        workspace.units,
    )
    assert isinstance(result, OptimizeAnalysisResult)
    optimum = result.objectives[0]
    assert optimum.best.decisions == ((Fraction(1, 4), "mark"),)
    assert dict(optimum.measures)["timing_error"] == 0
    assert optimum.proof.level == "best_found"
    assert optimum.proof.tolerance == Fraction(1, 16)
    assert optimum.proof.time_grid is None
    assert optimum.proof.search_budget == 20
    assert optimum.proof.budget_exhausted is False


def test_steady_proves_a_unique_finite_process_distribution(tmp_path: Path) -> None:
    source = """@kirin 2
@entry steady

process coin_state:
  state active: boolean = false
  event input step()
  on step():
    branch next_state joint:
      probability 1/4:
        next active = true
      probability 3/4:
        next active = false
  observe is_active: boolean = active

scenario chain:
  phases:
    - step
  use actor = coin_state:
  every 1 second from 0 second phase step:
    send actor.step()
  bounds:
    horizon = 1 second
    maximum_events = 2
    maximum_decisions = 1
    maximum_branches = 8
    maximum_entities = 1

analysis stationary:
  using = chain
  operation = steady
"""
    workspace = _workspace(tmp_path, source)
    result = execute_process_analysis(
        workspace.analyses["steady.stationary"],
        workspace.scenarios["steady.chain"],
        workspace.units,
    )
    assert isinstance(result, SteadyAnalysisResult)
    probabilities = {
        dict(state)["actor.active"]: probability
        for state, probability in zip(result.states, result.probabilities)
    }
    assert probabilities == {False: Fraction(3, 4), True: Fraction(1, 4)}


def test_cycle_proves_an_exact_finite_repeated_state(tmp_path: Path) -> None:
    source = """@kirin 2
@entry periodic

process toggle:
  state active: boolean = false
  event input step()
  on step():
    next active = not active
  observe is_active: boolean = active

scenario alternating:
  phases:
    - step
  use actor = toggle:
  at 0 second phase step:
    send actor.step()
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 4
    maximum_entities = 1

analysis period:
  using = alternating
  operation = cycle
"""
    workspace = _workspace(tmp_path, source)
    result = execute_process_analysis(
        workspace.analyses["periodic.period"],
        workspace.scenarios["periodic.alternating"],
        workspace.units,
    )
    assert isinstance(result, CycleAnalysisResult)
    assert result.preperiod == 0
    assert result.period == 2


def test_process_analysis_cli_records_and_replays_source_snapshots(
    tmp_path: Path, monkeypatch
) -> None:
    source = """@kirin 2
@entry run

process counter:
  state value: count = 0
  event input add()
  on add():
    next value = value + 1
  observe current: count = value

scenario once:
  phases:
    - event
  use actor = counter:
  at 0 second phase event:
    send actor.add()
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1

analysis execute:
  using = once
  operation = run
"""
    workspace = _workspace(tmp_path, source)
    monkeypatch.chdir(workspace.root)
    completed = runner.invoke(
        app,
        ["analyze", "run.execute", "--save-run", "process-run", "--json"],
    )
    assert completed.exit_code == 0, completed.output
    payload = json.loads(completed.stdout)
    assert payload["outcomes"][0]["run"]["observations"]["actor.current"] == "1"
    assert payload["phases"] == ["event"]
    record = workspace.root / "runs" / "process-run.json"
    assert record.is_file()
    replayed = replay(workspace.root, "process-run")
    assert replayed["matches_recorded_result"] is True
