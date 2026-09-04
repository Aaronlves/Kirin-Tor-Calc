from __future__ import annotations

from fractions import Fraction
import json
from pathlib import Path
import re

import pytest

from kirin_tor.errors import DomainError, ProcessFuelError, SchemaError
from kirin_tor.kirin_syntax import render_kirin_document
from kirin_tor.process_analysis import (
    CompareAnalysisResult,
    CycleAnalysisResult,
    OptimizeAnalysisResult,
    ReachAnalysisResult,
    RunAnalysisResult,
    SteadyAnalysisResult,
    execute_process_analysis,
    process_analysis_result_data,
)
from kirin_tor.process_chart import (
    render_process_chart_svg,
    write_process_chart_csv,
)
from kirin_tor.process_runtime import DeterministicProcessExecutor
from kirin_tor.application import record_operation
from kirin_tor.cli import app
from kirin_tor.operations import analyze_process, process_analysis_request
from kirin_tor.records import load_run, replay
from kirin_tor.workspace import Workspace, initialize
from kirin_tor.workbench import Workbench
from conftest import make_cli_runner


runner = make_cli_runner()


def _workspace(tmp_path: Path, source: str) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(source, encoding="utf-8")
    return Workspace.load(root)


def test_scenario_constant_expressions_bind_exact_static_entry_values(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "constants.kirin").write_text(
        """@kirin 2
@entry constants

input base: probability = 1/4
field chance: probability = base + 1/4
field event_time: time = 1 second
field analysis_horizon: time = 2 second
""",
        encoding="utf-8",
    )
    (root / "entries" / "model.kirin").write_text(
        """@kirin 2
@entry static_scenario

process holder:
  input chance: probability
  state value: probability = 0
  event input apply(amount: probability)
  on apply(amount):
    next value = chance + amount
  observe current: probability = value

scenario bound_values:
  phases:
    - event
  use actor = holder:
    chance = constants.chance
  at constants.event_time phase event:
    send actor.apply(amount = constants.chance)
  measure final_value: probability = final(actor.current)
  bounds:
    horizon = constants.analysis_horizon
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 2
    maximum_entities = 1

analysis execute:
  using = bound_values
  operation = run
""",
        encoding="utf-8",
    )

    workspace = Workspace.load(root)
    scenario = workspace.scenarios["static_scenario.bound_values"]
    result = execute_process_analysis(
        workspace.analyses["static_scenario.execute"],
        scenario,
        workspace.units,
    )

    assert isinstance(result, RunAnalysisResult)
    assert scenario.bounds.horizon == 2
    assert dict(result.outcomes[0].measures)["final_value"] == 1


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
  measure hit_count: count = final(if_else(actor.did_hit, 1, 0))
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
    assert run.measure_expectations == (("hit_count", Fraction(1, 4)),)
    assert sorted(
        dict(item.measures)["hit_count"] for item in run.outcomes
    ) == [Fraction(0), Fraction(1)]
    projection = process_analysis_result_data(
        run, workspace.analyses["random.distribution"], scenario
    )
    assert projection["random_semantics"] == "strict_finite_output_expectation"
    assert projection["state_aggregation"] == "exact_measure_aware"
    assert projection["measure_expectations"] == {"hit_count": "1/4"}

    reach = execute_process_analysis(
        workspace.analyses["random.hit_chance"], scenario, workspace.units
    )
    assert isinstance(reach, ReachAnalysisResult)
    assert reach.probability == Fraction(1, 4)


def test_zero_probability_cases_do_not_consume_random_branch_fuel(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry deterministic_branch

process coin:
  state hits: count = 0 in 0..2
  event input flip()
  on flip():
    branch outcome independent:
      probability 1:
        next hits = hits + 1
      probability 0:
        next hits = hits
  observe count: count = hits

scenario two_certain_flips:
  phases:
    - event
  use actor = coin:
  at 0 second phase event:
    send actor.flip()
  at 1 second phase event:
    send actor.flip()
  measure final_hits: count = final(actor.count)
  bounds:
    horizon = 1 second
    maximum_events = 2
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1

analysis distribution:
  using = two_certain_flips
  operation = run
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios[
        "deterministic_branch.two_certain_flips"
    ]
    result = execute_process_analysis(
        workspace.analyses["deterministic_branch.distribution"],
        scenario,
        workspace.units,
    )

    assert isinstance(result, RunAnalysisResult)
    assert len(result.outcomes) == 1
    assert result.outcomes[0].probability == 1
    assert dict(result.outcomes[0].measures)["final_hits"] == 2


def test_random_distribution_reuses_exact_batch_checkpoints(
    tmp_path: Path, monkeypatch
) -> None:
    source = """@kirin 2
@entry checkpoint_tree

process coin:
  state heads: count = 0 in 0..2
  event input flip()
  on flip():
    branch outcome independent:
      probability 1/2:
        next heads = heads + 1
      probability 1/2:
        next heads = heads
  observe count: count = heads

scenario two_flips:
  phases:
    - event
  use actor = coin:
  at 0 second phase event:
    send actor.flip()
  at 1 second phase event:
    send actor.flip()
  measure final_heads: count = final(actor.count)
  bounds:
    horizon = 1 second
    maximum_events = 4
    maximum_decisions = 1
    maximum_branches = 8
    maximum_entities = 1

analysis distribution:
  using = two_flips
  operation = run
  chart complete_paths:
    kind = trajectory
    series:
      - actor.count
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["checkpoint_tree.two_flips"]
    initialize_calls = 0
    original_initialize = DeterministicProcessExecutor._initialize

    def counted_initialize(executor):
        nonlocal initialize_calls
        initialize_calls += 1
        return original_initialize(executor)

    monkeypatch.setattr(
        DeterministicProcessExecutor, "_initialize", counted_initialize
    )
    result = execute_process_analysis(
        workspace.analyses["checkpoint_tree.distribution"],
        scenario,
        workspace.units,
    )

    assert isinstance(result, RunAnalysisResult)
    assert initialize_calls == 1
    assert result.explored_branches == 6
    assert len(result.outcomes) == 4
    assert [item.probability for item in result.outcomes] == [
        Fraction(1, 4),
        Fraction(1, 4),
        Fraction(1, 4),
        Fraction(1, 4),
    ]
    assert sorted(
        dict(item.measures)["final_heads"] for item in result.outcomes
    ) == [Fraction(0), Fraction(1), Fraction(1), Fraction(2)]


def test_random_distribution_exactly_merges_equivalent_measure_states(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry aggregate_tree

process coin:
  state heads: count = 0 in 0..3
  event input flip()
  on flip():
    branch outcome independent:
      probability 1/2:
        next heads = heads + 1
      probability 1/2:
        next heads = heads
  observe count: count = heads

scenario three_flips:
  phases:
    - event
  use actor = coin:
  at 0 second phase event:
    send actor.flip()
  at 1 second phase event:
    send actor.flip()
  at 2 second phase event:
    send actor.flip()
  measure final_heads: count = final(actor.count)
  bounds:
    horizon = 2 second
    maximum_events = 3
    maximum_decisions = 1
    maximum_branches = 16
    maximum_entities = 1

analysis states:
  using = three_flips
  operation = run

analysis paths:
  using = three_flips
  operation = run
  chart complete_paths:
    kind = trajectory
    series:
      - actor.count
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["aggregate_tree.three_flips"]

    states = execute_process_analysis(
        workspace.analyses["aggregate_tree.states"],
        scenario,
        workspace.units,
    )
    assert isinstance(states, RunAnalysisResult)
    assert states.explored_branches == 12
    assert len(states.outcomes) == 4
    assert sorted(item.path_count for item in states.outcomes) == [1, 1, 3, 3]
    assert sorted(item.probability for item in states.outcomes) == [
        Fraction(1, 8),
        Fraction(1, 8),
        Fraction(3, 8),
        Fraction(3, 8),
    ]
    projection = process_analysis_result_data(
        states, workspace.analyses["aggregate_tree.states"], scenario
    )
    assert projection["source_path_count"] == 8
    assert projection["outcome_state_count"] == 4
    assert projection["equivalent_states_merged"] == 4
    assert sorted(item["source_path_count"] for item in projection["outcomes"]) == [
        1,
        1,
        3,
        3,
    ]

    paths = execute_process_analysis(
        workspace.analyses["aggregate_tree.paths"],
        scenario,
        workspace.units,
    )
    assert isinstance(paths, RunAnalysisResult)
    assert paths.explored_branches == 14
    assert len(paths.outcomes) == 8
    assert all(item.path_count == 1 for item in paths.outcomes)


def test_random_optimize_builds_exact_observable_state_policy(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry adaptive_policy

process signal_game:
  state signal: boolean = false
  state score: count = 0 in 0..1
  event input reveal()
  event input collect()
  event output scored(amount: count)
  phase public
  on reveal():
    branch result independent:
      probability 1/2:
        next signal = true
      probability 1/2:
        next signal = false
  on collect():
    next score = 1
    emit scored(amount = 1) phase public
  observe is_true: boolean = signal
  observe total: count = score

scenario react_after_reveal:
  phases:
    - random
    - decision
    - public
  use actor = signal_game:
    phase public = public
  action collect_true when actor.is_true:
    send actor.collect() phase decision
  action collect_false when not actor.is_true:
    send actor.collect() phase decision
  at 0 second phase random:
    send actor.reveal()
  decide every 1 second from 1 second until 1 second phase decision:
    - collect_true
    - collect_false
    - wait
  measure final_score: count = final(actor.total)
  measure total_score: count = sum_events(actor.scored.amount)
  objective perfect_response:
    maximize final_score
    require all_paths final_score == 1
  objective impossible_response:
    maximize final_score
    require all_paths final_score == 2
  objective maximum_total:
    maximize total_score
  bounds:
    horizon = 1 second
    maximum_events = 4
    maximum_decisions = 1
    maximum_branches = 16
    maximum_entities = 1

analysis solve:
  using = react_after_reveal
  operation = optimize
  objectives:
    - perfect_response
    - impossible_response
    - maximum_total
"""
    workspace = _workspace(tmp_path, source)
    analysis = workspace.analyses["adaptive_policy.solve"]
    scenario = workspace.scenarios["adaptive_policy.react_after_reveal"]
    result = execute_process_analysis(analysis, scenario, workspace.units)

    assert isinstance(result, OptimizeAnalysisResult)
    objective = result.variants[0].objectives[0]
    assert objective.proof.level == "exact_global"
    assert objective.proof.method == (
        "exact_observable_state_policy_dynamic_programming"
    )
    request = process_analysis_request(workspace, "adaptive_policy.solve")
    assert request["search"]["method"] == (
        "exact_observable_state_policy_dynamic_programming"
    )
    strategy = objective.optima[0]
    assert dict(strategy.measures) == {
        "final_score": Fraction(1),
        "total_score": Fraction(1),
    }
    assert len(strategy.outcomes) == 2
    assert sorted(item.probability for item in strategy.outcomes) == [
        Fraction(1, 2),
        Fraction(1, 2),
    ]
    assert len(strategy.policy_rules) == 2
    chosen_by_signal = {
        dict(rule.observations)["actor.is_true"]: rule.selected_action
        for rule in strategy.policy_rules
    }
    assert chosen_by_signal == {
        False: "collect_false",
        True: "collect_true",
    }
    projection = process_analysis_result_data(result, analysis, scenario)
    projected = projection["variants"][0]["objectives"][0][
        "optimal_strategies"
    ][0]
    assert projected["policy_semantics"] == "exact_observable_state"
    assert len(projected["policy_rules"]) == 2
    summary = projected["policy_summary"]
    assert summary[0]["time"] == "1"
    assert summary[0]["reachable_states"] == 2
    actions = {item["action"]: item for item in summary[0]["actions"]}
    assert actions["collect_true"]["observation_ranges"]["actor.is_true"] == {
        "values": [True]
    }
    assert actions["collect_false"]["observation_ranges"]["actor.is_true"] == {
        "values": [False]
    }
    impossible = result.variants[0].objectives[1]
    assert impossible.proof.level == "exact_global"
    assert impossible.optima == ()
    assert projection["variants"][0]["objectives"][1][
        "optimal_strategies"
    ] == []
    total = result.variants[0].objectives[2].optima[0]
    assert total.objective_values == (Fraction(1),)
    assert dict(total.measures)["total_score"] == 1


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
  chart value_trace:
    kind = trajectory
    series:
      - actor.current

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
    run_projection = process_analysis_result_data(
        run, workspace.analyses["policies.add_run"], scenario
    )
    assert run_projection["charts"][0]["kind"] == "trajectory"
    assert run_projection["charts"][0]["rows"][-1]["values"]["actor.current"][
        "exact"
    ] == "1"

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
    assert [variant.variant_id for variant in result.variants] == [
        "standard_brew",
        "deep_clean",
    ]
    assert result.explored_branches <= scenario.bounds.maximum_branches
    assert [item.objective_id for item in result.variants[0].objectives] == [
        "smoothest_health",
        "most_purified",
        "longest_survival",
    ]
    longest = result.variants[0].objectives[-1]
    longest_strategy = longest.optima[0]
    assert longest_strategy.run.elapsed >= 3
    assert longest_strategy.objective_values[0] == dict(longest_strategy.measures)[
        "survival_time"
    ]
    assert longest.proof.level == "best_found"
    assert longest.proof.tolerance == Fraction(1, 4)
    assert longest.proof.time_grid is None
    assert any(
        time.denominator != 1
        for time, _choice in longest_strategy.run.decisions
    )
    assert set(dict(longest_strategy.measures)) == {
        "minimum_health",
        "health_variation",
        "total_purified",
        "survival_time",
        "remaining_charges",
    }
    by_variant = {variant.variant_id: variant for variant in result.variants}
    standard_purified = dict(
        by_variant["standard_brew"].objectives[1].optima[0].measures
    )["total_purified"]
    deep_purified = dict(
        by_variant["deep_clean"].objectives[1].optima[0].measures
    )["total_purified"]
    assert deep_purified > standard_purified
    assert dict(by_variant["deep_clean"].input_overrides) == {
        "actor.clear_ratio": Fraction(13, 20),
        "actor.healing_ratio": Fraction(1, 5),
    }
    projected = process_analysis_result_data(
        result, workspace.analyses["brew.latest_death"], scenario
    )
    assert [item["variant"] for item in projected["variants"]] == [
        "standard_brew",
        "deep_clean",
    ]
    assert all(len(item["objectives"]) == 3 for item in projected["variants"])
    assert [chart["kind"] for chart in projected["charts"]] == [
        "trajectory",
        "trajectory",
        "trajectory",
        "decision_surface",
        "pareto",
        "variant_comparison",
    ]
    health_chart = projected["charts"][0]
    assert health_chart["rows"]
    assert any(marker["kind"] == "decision" for marker in health_chart["markers"])
    pareto_chart = next(chart for chart in projected["charts"] if chart["kind"] == "pareto")
    assert pareto_chart["frontier"]
    assert all(item["nondominated"] for item in pareto_chart["frontier"])
    surface = projected["charts"][3]
    assert surface["rows"]
    tradeoff = projected["charts"][4]
    assert any(row["nondominated"] for row in tradeoff["rows"])
    csv_path = write_process_chart_csv(
        health_chart, tmp_path / "health.csv"
    )
    svg_path = render_process_chart_svg(
        tradeoff, tmp_path / "tradeoff.svg"
    )
    assert csv_path.read_text(encoding="utf-8").startswith(
        "variant,objective,strategy,time"
    )
    assert "<svg" in svg_path.read_text(encoding="utf-8")


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
    require all_paths final_value >= 0
    require probability at_least 1: final_value == 1
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
    by_id = {
        item.objective_id: item for item in result.variants[0].objectives
    }
    highest = by_id["highest_bounded"]
    assert len(highest.optima) == 2
    assert {
        optimum.run.decisions for optimum in highest.optima
    } == {
        ((Fraction(0), "add"), (Fraction(1), "wait")),
        ((Fraction(0), "wait"), (Fraction(1), "add")),
    }
    assert all(dict(item.measures)["final_value"] == 1 for item in highest.optima)
    assert all(item.constraints == (True, True, True) for item in highest.optima)
    assert all(item.chance_probabilities == (Fraction(1),) for item in highest.optima)
    assert dict(by_id["fewest_additions"].optima[0].measures)["final_value"] == 0
    projection = process_analysis_result_data(
        result,
        workspace.analyses["objectives.optimize_both"],
        workspace.scenarios["objectives.choice"],
    )
    highest_projection = projection["variants"][0]["objectives"][0]
    assert highest_projection["tied_optima"] == 2
    assert highest_projection["constraint_scopes"] == [
        "single_run",
        "all_paths",
        "probability",
    ]
    assert highest_projection["chance_constraints"] == [
        {"comparison": "at_least", "threshold": "1"}
    ]
    assert len(highest_projection["optimal_strategies"]) == 2
    assert "best" not in highest_projection
    assert all(
        item.proof.level == "exact_global"
        for item in result.variants[0].objectives
    )


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
    optimum = result.variants[0].objectives[0]
    assert optimum.optima[0].run.decisions == ((Fraction(1, 4), "mark"),)
    assert dict(optimum.optima[0].measures)["timing_error"] == 0
    assert optimum.proof.level == "best_found"
    assert optimum.proof.tolerance == Fraction(1, 16)
    assert optimum.proof.time_grid is None
    assert optimum.proof.search_budget == 20
    assert optimum.proof.budget_exhausted is False
    request = process_analysis_request(
        workspace,
        "continuous_search.search",
        timeout_seconds=10,
    )
    assert request["search"] == {
        "method": "adaptive_dyadic",
        "time_tolerance": "1/16",
        "time_grid": None,
        "search_budget": 20,
        "pruning_approximation": None,
    }
    record_operation(
        workspace,
        "continuous-search",
        "process_analysis",
        request,
        lambda: analyze_process(
            workspace, "continuous_search.search", timeout_seconds=10
        ),
    )
    record = load_run(workspace, "continuous-search")
    assert record["request"]["search"] == request["search"]
    assert replay(workspace.root, "continuous-search")[
        "matches_recorded_result"
    ] is True


def test_exact_grid_search_exhausts_sparse_distinct_action_times(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry exact_grid_search

process marker:
  state marks: count = 0 in 0..2
  state timing_error: time = 0 second
  action mark() when marks < 2
  on mark():
    next timing_error = timing_error + if_else(
      marks == 0,
      abs(event.time - 1/5 second),
      abs(event.time - 4/5 second),
    )
    next marks = marks + 1
  observe count: count = marks
  observe error: time = timing_error

scenario trial:
  phases:
    - decision
  use actor = marker:
  action mark:
    send actor.mark() phase decision
  decide continuously up to 2 times from 0 second until 1 second phase decision:
    - mark
  measure mark_count: count = final(actor.count)
  measure timing_error: time = final(actor.error)
  objective best_marks:
    maximize mark_count
    then minimize timing_error
  bounds:
    horizon = 1 second
    maximum_events = 2
    maximum_decisions = 2
    maximum_branches = 128
    maximum_entities = 1

analysis search:
  using = trial
  operation = optimize
  objectives:
    - best_marks
  search:
    method = exact_grid
    time_grid = 1/10 second
    maximum_evaluations = 100
"""
    workspace = _workspace(tmp_path, source)
    analysis = workspace.analyses["exact_grid_search.search"]
    scenario = workspace.scenarios["exact_grid_search.trial"]
    result = execute_process_analysis(analysis, scenario, workspace.units)
    optimum = result.variants[0].objectives[0]
    assert optimum.optima[0].run is not None
    assert optimum.optima[0].run.decisions == (
        (Fraction(1, 5), "mark"),
        (Fraction(4, 5), "mark"),
    )
    assert dict(optimum.optima[0].measures) == {
        "mark_count": Fraction(2),
        "timing_error": Fraction(0),
    }
    assert result.explored_branches == 67
    assert optimum.proof.level == "exact_global"
    assert optimum.proof.method == "exhaustive_time_grid_plans"
    assert optimum.proof.time_grid == Fraction(1, 10)
    assert optimum.proof.tolerance is None
    assert optimum.proof.search_budget == 100

    request = process_analysis_request(
        workspace,
        "exact_grid_search.search",
        timeout_seconds=10,
    )
    assert request["search"] == {
        "method": "exact_grid",
        "time_tolerance": None,
        "time_grid": "1/10",
        "search_budget": 100,
        "pruning_approximation": None,
    }
    projection = process_analysis_result_data(result, analysis, scenario)
    assert projection["search"] == {
        "method": "exact_grid",
        "time_tolerance": None,
        "time_grid": "1/10",
        "maximum_evaluations": 100,
    }
    rendered = render_kirin_document(workspace.get_entry("exact_grid_search"))
    assert "    method = exact_grid" in rendered
    assert "    time_grid = 1/10 second" in rendered
    assert "    time_tolerance" not in rendered

    limited_workspace = _workspace(
        tmp_path / "limited",
        source.replace("maximum_evaluations = 100", "maximum_evaluations = 66"),
    )
    with pytest.raises(
        ProcessFuelError,
        match="exact_grid enumerated all candidate plans",
    ):
        execute_process_analysis(
            limited_workspace.analyses["exact_grid_search.search"],
            limited_workspace.scenarios["exact_grid_search.trial"],
            limited_workspace.units,
        )
    dense_workspace = _workspace(
        tmp_path / "dense",
        source.replace("time_grid = 1/10 second", "time_grid = 1/1000 second"),
    )
    with pytest.raises(
        ProcessFuelError,
        match="exact_grid point count exceeds maximum_evaluations",
    ):
        execute_process_analysis(
            dense_workspace.analyses["exact_grid_search.search"],
            dense_workspace.scenarios["exact_grid_search.trial"],
            dense_workspace.units,
        )
    with pytest.raises(
        SchemaError,
        match="exact_grid search requires time_grid and forbids time_tolerance",
    ):
        _workspace(
            tmp_path / "wrong-setting",
            source.replace(
                "time_grid = 1/10 second",
                "time_tolerance = 1/10 second",
            ),
        )


def test_exact_grid_memoizes_infeasible_prefixes_without_approximating_random_paths(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry exact_prefix_pruning

process charge:
  state charges: count = 1 in 0..1
  action spend() when charges > 0
  on spend():
    branch result independent:
      probability 1/2:
        next charges = 0
      probability 1/2:
        next charges = charges
  observe charges_left: count = charges

scenario trial:
  phases:
    - decision
  use actor = charge:
  action spend:
    send actor.spend() phase decision
  decide continuously up to 3 times from 0 second until 3 second phase decision:
    - spend
  measure charges_left: count = final(actor.charges_left)
  objective use_charge:
    minimize charges_left
  bounds:
    horizon = 3 second
    maximum_events = 3
    maximum_decisions = 3
    maximum_branches = 64
    maximum_entities = 1

analysis search:
  using = trial
  operation = optimize
  objectives:
    - use_charge
  search:
    method = exact_grid
    time_grid = 1 second
    maximum_evaluations = 15
"""
    workspace = _workspace(tmp_path, source)
    analysis = workspace.analyses["exact_prefix_pruning.search"]
    scenario = workspace.scenarios["exact_prefix_pruning.trial"]
    result = execute_process_analysis(analysis, scenario, workspace.units)
    optimum = result.variants[0].objectives[0]

    # There are 1 + C(4,1) + C(4,2) + C(4,3) = 15 plans.  Every
    # two-use prefix fails on the nonzero-probability path that spent the only
    # charge, so the four three-use suffixes need not execute again.
    assert result.explored_branches == 15
    assert optimum.proof.level == "exact_global"
    assert optimum.proof.candidate_plans == 15
    assert optimum.proof.executed_plans == 11
    assert optimum.proof.pruned_plans == 4
    assert len(optimum.optima) == 4
    assert {
        strategy.decisions for strategy in optimum.optima
    } == {
        ((Fraction(time), "spend"),)
        for time in range(4)
    }
    assert all(
        dict(strategy.measures)["charges_left"] == Fraction(1, 2)
        for strategy in optimum.optima
    )

    projection = process_analysis_result_data(result, analysis, scenario)
    assert projection["variants"][0]["objectives"][0]["proof"] == {
        "level": "exact_global",
        "method": "exhaustive_time_grid_plans_with_exact_finite_outcomes",
        "error_bound": None,
        "tolerance": None,
        "time_grid": "1",
        "search_budget": 15,
        "budget_exhausted": False,
        "candidate_plans": 15,
        "executed_plans": 11,
        "pruned_plans": 4,
    }


def test_continuous_plan_optimize_uses_exact_random_measure_expectations(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry random_optimize

process reward:
  state score: dimensionless = 0 in 0..2
  action risky()
  action safe()
  on risky():
    branch result independent:
      probability 1/4:
        next score = score + 2
      probability 3/4:
        next score = score
  on safe():
    next score = score + 2/5
  observe current: dimensionless = score

scenario choice:
  phases:
    - decision
  use actor = reward:
  action risky:
    send actor.risky() phase decision
  action safe:
    send actor.safe() phase decision
  decide continuously up to 1 time from 0 second until 0 second phase decision:
    - risky
    - safe
  measure final_score: dimensionless = final(actor.current)
  objective highest_expected_score:
    maximize final_score
    require final_score >= 2/5
    require probability at_least 1/4: final_score >= 2
  objective guaranteed_score:
    maximize final_score
    require all_paths final_score >= 2/5
  objective reliable_score:
    maximize final_score
    require probability at_most 1/4: final_score < 2/5
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 16
    maximum_entities = 1

analysis search:
  using = choice
  operation = optimize
  objectives:
    - highest_expected_score
    - guaranteed_score
    - reliable_score
  search:
    method = adaptive_dyadic
    time_tolerance = 1/10 second
    maximum_evaluations = 8
  chart score_paths:
    kind = trajectory
    series:
      - actor.current

analysis grid_search:
  using = choice
  operation = optimize
  objectives:
    - highest_expected_score
    - guaranteed_score
    - reliable_score
  search:
    method = exact_grid
    time_grid = 1/10 second
    maximum_evaluations = 8
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["random_optimize.choice"]
    assert len(scenario.objectives[1].path_constraints) == 1
    assert len(scenario.objectives[0].chance_constraints) == 1
    assert scenario.objectives[0].chance_constraints[0].threshold == Fraction(1, 4)
    assert scenario.objectives[2].chance_constraints[0].comparison == "at_most"
    assert "    require all_paths final_score >= 2/5" in render_kirin_document(
        workspace.get_entry("random_optimize")
    )
    assert (
        "    require probability at_least 1/4: final_score >= 2"
        in render_kirin_document(workspace.get_entry("random_optimize"))
    )
    result = execute_process_analysis(
        workspace.analyses["random_optimize.search"], scenario, workspace.units
    )
    assert isinstance(result, OptimizeAnalysisResult)
    optimum = result.variants[0].objectives[0].optima[0]
    assert optimum.run is None
    assert optimum.decisions == ((Fraction(0), "risky"),)
    assert dict(optimum.measures) == {"final_score": Fraction(1, 2)}
    assert optimum.constraints == (True, True)
    assert optimum.chance_probabilities == (Fraction(1, 4),)
    assert sorted(item.probability for item in optimum.outcomes) == [
        Fraction(1, 4),
        Fraction(3, 4),
    ]
    assert result.variants[0].objectives[0].proof.level == "exact_global"
    assert result.variants[0].objectives[0].proof.method == (
        "exhaustive_degenerate_continuous_choices_with_exact_finite_outcomes"
    )
    guaranteed = result.variants[0].objectives[1].optima[0]
    assert guaranteed.decisions == ((Fraction(0), "safe"),)
    assert dict(guaranteed.measures) == {"final_score": Fraction(2, 5)}
    assert guaranteed.constraints == (True,)
    assert [item.probability for item in guaranteed.outcomes] == [Fraction(1)]
    reliable = result.variants[0].objectives[2].optima[0]
    assert reliable.decisions == ((Fraction(0), "safe"),)
    assert reliable.constraints == (True,)
    assert reliable.chance_probabilities == (Fraction(0),)

    projection = process_analysis_result_data(
        result, workspace.analyses["random_optimize.search"], scenario
    )
    strategy = projection["variants"][0]["objectives"][0][
        "optimal_strategies"
    ][0]
    assert projection["random_semantics"] == "strict_finite_output_expectation"
    assert strategy["measure_semantics"] == "exact_expectations"
    assert strategy["measures"] == {"final_score": "1/2"}
    assert strategy["decisions"] == [{"time": "0", "choice": "risky"}]
    assert sorted(item["probability"] for item in strategy["outcomes"]) == [
        "1/4",
        "3/4",
    ]
    assert {
        row["probability"]
        for row in projection["charts"][0]["rows"]
        if row["objective"] == "highest_expected_score"
    } == {"1/4", "3/4"}
    expected_projection = projection["variants"][0]["objectives"][0]
    assert expected_projection["constraint_scopes"] == [
        "expected",
        "probability",
    ]
    assert expected_projection["chance_constraints"] == [
        {"comparison": "at_least", "threshold": "1/4"}
    ]
    assert strategy["chance_probabilities"] == ["1/4"]
    guaranteed_projection = projection["variants"][0]["objectives"][1]
    assert guaranteed_projection["constraint_scopes"] == ["all_paths"]
    assert guaranteed_projection["optimal_strategies"][0]["decisions"] == [
        {"time": "0", "choice": "safe"}
    ]
    reliable_projection = projection["variants"][0]["objectives"][2]
    assert reliable_projection["constraint_scopes"] == ["probability"]
    assert reliable_projection["chance_constraints"] == [
        {"comparison": "at_most", "threshold": "1/4"}
    ]
    assert reliable_projection["optimal_strategies"][0][
        "chance_probabilities"
    ] == ["0"]

    grid_result = execute_process_analysis(
        workspace.analyses["random_optimize.grid_search"],
        scenario,
        workspace.units,
    )
    grid_optimum = grid_result.variants[0].objectives[0]
    assert grid_optimum.optima[0].decisions == ((Fraction(0), "risky"),)
    assert dict(grid_optimum.optima[0].measures) == {
        "final_score": Fraction(1, 2)
    }
    assert grid_optimum.proof.level == "exact_global"
    assert grid_optimum.proof.method == (
        "exhaustive_time_grid_plans_with_exact_finite_outcomes"
    )
    assert grid_optimum.proof.time_grid == Fraction(1, 10)
    grid_guaranteed = grid_result.variants[0].objectives[1].optima[0]
    assert grid_guaranteed.decisions == ((Fraction(0), "safe"),)
    grid_reliable = grid_result.variants[0].objectives[2].optima[0]
    assert grid_reliable.decisions == ((Fraction(0), "safe"),)

    with pytest.raises(DomainError, match="probability.*maximum"):
        _workspace(
            tmp_path / "invalid-probability",
            source.replace(
                "require probability at_least 1/4: final_score >= 2",
                "require probability at_least 5/4: final_score >= 2",
            ),
        )
    with pytest.raises(SchemaError, match="probability constraint must use"):
        _workspace(
            tmp_path / "invalid-probability-syntax",
            source.replace(
                "require probability at_least 1/4: final_score >= 2",
                "require probability >= 1/4: final_score >= 2",
            ),
        )


def test_continuous_optimize_discards_an_unavailable_occurrence(
    tmp_path: Path,
) -> None:
    source = """@kirin 2
@entry unavailable_plan

process resource:
  state ready: boolean = false
  state score: count = 0
  action spend() when ready
  on spend():
    next score = score + 1
  observe current: count = score

scenario choice:
  phases:
    - decision
  use actor = resource:
  action spend:
    send actor.spend() phase decision
  decide continuously up to 1 time from 0 second until 0 second phase decision:
    - spend
  measure final_score: count = final(actor.current)
  objective highest:
    maximize final_score
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 4
    maximum_entities = 1

analysis search:
  using = choice
  operation = optimize
  objectives:
    - highest
  search:
    method = adaptive_dyadic
    time_tolerance = 1/10 second
    maximum_evaluations = 4
"""
    workspace = _workspace(tmp_path, source)
    scenario = workspace.scenarios["unavailable_plan.choice"]
    result = execute_process_analysis(
        workspace.analyses["unavailable_plan.search"], scenario, workspace.units
    )
    optimum = result.variants[0].objectives[0].optima[0]
    assert optimum.run is not None
    assert optimum.run.decisions == ()
    assert dict(optimum.measures) == {"final_score": Fraction(0)}
    assert result.variants[0].objectives[0].proof.level == "exact_global"


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


def test_process_analysis_cli_records_and_replays_exact_random_paths(
    tmp_path: Path, monkeypatch
) -> None:
    source = """@kirin 2
@entry run

process counter:
  input chance: probability = 1/4
  state value: count = 0
  event input add()
  on add():
    branch result independent:
      probability chance:
        next value = value + 1
      probability 1 - chance:
        next value = value
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
    maximum_branches = 4
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
    assert sorted(
        (item["probability"], item["run"]["observations"]["actor.current"])
        for item in payload["outcomes"]
    ) == [("1/4", "1"), ("3/4", "0")]
    assert payload["random_semantics"] == "strict_finite_output_expectation"
    assert payload["phases"] == ["event"]
    record = workspace.root / "runs" / "process-run.json"
    assert record.is_file()
    replayed = replay(workspace.root, "process-run")
    assert replayed["matches_recorded_result"] is True


def test_process_analysis_cli_explicitly_exports_multiple_charts(
    tmp_path: Path, monkeypatch
) -> None:
    source = """@kirin 2
@entry chart_export

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
  decide every 1 second from 0 second until 0 second phase decision:
    - add
    - wait
  measure final_value: count = final(actor.current)
  objective highest:
    maximize final_value
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 4
    maximum_entities = 1

analysis search:
  using = choice
  operation = optimize
  objectives:
    - highest
  chart trajectory:
    kind = trajectory
    series:
      - actor.current
    markers:
      - decision add
    export_svg = "results/trajectory.svg"
    export_csv = "results/trajectory.csv"
  chart tradeoff:
    kind = pareto
    x = final_value
    x_direction = maximize
    y = final_value
    y_direction = minimize
    export_svg = "results/tradeoff.svg"
    export_csv = "results/tradeoff.csv"
"""
    workspace = _workspace(tmp_path, source)
    workbench = Workbench(workspace.root)
    assert [item["value"] for item in workbench.bootstrap()["index"]["analyses"]] == [
        "chart_export.search"
    ]
    preview = workbench.execute(
        "process_analysis", {"target": "chart_export.search", "timeout": 10}
    )
    assert len(preview["charts"]) == 2
    exported = workbench.execute(
        "export_process_charts",
        {"target": "chart_export.search", "timeout": 10},
    )
    assert len(exported["artifacts"]) == 2
    monkeypatch.chdir(workspace.root)
    completed = runner.invoke(
        app,
        [
            "analyze",
            "chart_export.search",
            "--export-charts",
            "--force",
            "--json",
        ],
    )
    assert completed.exit_code == 0, completed.output
    payload = json.loads(completed.stdout)
    assert len(payload["charts"]) == 2
    for stem in ("trajectory", "tradeoff"):
        assert (workspace.root / "results" / f"{stem}.svg").is_file()
        assert (workspace.root / "results" / f"{stem}.csv").is_file()
