"""Exact bounded analysis operations over the unified Process runtime."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import sympy as sp

from .errors import ProcessExecutionError, ProcessFuelError, UnsupportedError
from .process_expression import ProcessValue, evaluate_process_expression
from .process_expression import FrozenMapValue, ProcessEventId
from .process_ir import BranchEffectIR, EffectIR, WhenEffectIR
from .process_runtime import (
    ProcessRunResult,
    run_process_scenario,
    selector_for_policy,
)
from .scenario_ir import AnalysisIR, PolicyIR, ScenarioIR
from .units import UnitRegistry


@dataclass(frozen=True)
class WeightedProcessRun:
    probability: Fraction
    result: ProcessRunResult


@dataclass(frozen=True)
class RunAnalysisResult:
    analysis_id: str
    operation: str
    outcomes: Tuple[WeightedProcessRun, ...]
    explored_branches: int


@dataclass(frozen=True)
class PolicyComparison:
    policy_id: str
    result: RunAnalysisResult


@dataclass(frozen=True)
class CompareAnalysisResult:
    analysis_id: str
    operation: str
    policies: Tuple[PolicyComparison, ...]


@dataclass(frozen=True)
class OptimizeAnalysisResult:
    analysis_id: str
    operation: str
    best: ProcessRunResult
    objective_values: Tuple[ProcessValue, ...]
    explored_branches: int
    tied_optima: int


@dataclass(frozen=True)
class ReachAnalysisResult:
    analysis_id: str
    operation: str
    probability: Fraction
    outcomes: Tuple[WeightedProcessRun, ...]
    explored_branches: int


@dataclass(frozen=True)
class SteadyAnalysisResult:
    analysis_id: str
    operation: str
    states: Tuple[Tuple[Tuple[str, ProcessValue], ...], ...]
    probabilities: Tuple[Fraction, ...]
    transition_matrix: Tuple[Tuple[Fraction, ...], ...]


@dataclass(frozen=True)
class CycleAnalysisResult:
    analysis_id: str
    operation: str
    preperiod: int
    period: int
    states: Tuple[Tuple[Tuple[str, Tuple[Tuple[str, ProcessValue], ...]], ...], ...]
    runs: Tuple[ProcessRunResult, ...]


ProcessAnalysisResult = object


class _NeedBranch(Exception):
    def __init__(self, probabilities: Tuple[Fraction, ...]):
        self.probabilities = probabilities


class _NeedDecision(Exception):
    def __init__(self, available: Tuple[str, ...]):
        self.available = available


def _nested(effects: Sequence[EffectIR]):
    for effect in effects:
        yield effect
        if isinstance(effect, WhenEffectIR):
            yield from _nested(effect.effects)
        elif isinstance(effect, BranchEffectIR):
            for case in effect.cases:
                yield from _nested(case.effects)


def _has_random(scenario: ScenarioIR) -> bool:
    return any(
        isinstance(effect, BranchEffectIR)
        for instance in scenario.instances
        for handler in instance.process.handlers
        for effect in _nested(handler.effects)
    )


def _policy(scenario: ScenarioIR, policy_ids: Sequence[str]) -> Optional[PolicyIR]:
    if not policy_ids:
        return None
    policies = {item.id: item for item in scenario.policies}
    return policies[policy_ids[0]]


def _run_distribution(
    scenario: ScenarioIR,
    registry: UnitRegistry,
    *,
    policy: Optional[PolicyIR],
    reach_target=None,
    include_trace: bool = True,
    initial_state_overrides: Optional[
        Mapping[Tuple[str, str], ProcessValue]
    ] = None,
    maximum_batches: Optional[int] = None,
) -> Tuple[Tuple[WeightedProcessRun, ...], int]:
    decision_selector = selector_for_policy(policy, registry) if policy else None
    if not _has_random(scenario):
        result = run_process_scenario(
            scenario,
            registry,
            selector=decision_selector,
            reach_target=reach_target,
            include_trace=include_trace,
            initial_state_overrides=initial_state_overrides,
            maximum_batches=maximum_batches,
        )
        return (WeightedProcessRun(Fraction(1), result),), 1

    pending: List[Tuple[Tuple[int, ...], Fraction]] = [((), Fraction(1))]
    outcomes: List[WeightedProcessRun] = []
    explored = 0
    while pending:
        prefix, weight = pending.pop()

        def choose_branch(index, _event, _branch, probabilities, _environment):
            if index >= len(prefix):
                raise _NeedBranch(probabilities)
            return prefix[index]

        try:
            result = run_process_scenario(
                scenario,
                registry,
                selector=decision_selector,
                branch_selector=choose_branch,
                reach_target=reach_target,
                include_trace=include_trace,
                initial_state_overrides=initial_state_overrides,
                maximum_batches=maximum_batches,
            )
        except _NeedBranch as need:
            choices = [
                (index, probability)
                for index, probability in enumerate(need.probabilities)
                if probability
            ]
            explored += len(choices)
            if explored > scenario.bounds.maximum_branches:
                raise ProcessFuelError(
                    "maximum_branches exhausted while expanding random outcomes: "
                    f"{explored}/{scenario.bounds.maximum_branches}",
                    scenario.location,
                )
            pending.extend(
                (prefix + (index,), weight * probability)
                for index, probability in reversed(choices)
            )
            continue
        outcomes.append(WeightedProcessRun(weight, result))
    total = sum((item.probability for item in outcomes), Fraction(0))
    if total != 1:
        raise ProcessExecutionError(
            f"random Process outcomes do not normalize exactly; got {total}",
            scenario.location,
        )
    return tuple(outcomes), max(explored, 1)


def _result_values(
    scenario: ScenarioIR, result: ProcessRunResult
) -> Dict[object, ProcessValue]:
    values = dict(result.observations)
    return {
        symbol: values[symbol.id]
        for symbol in scenario.observation_symbols
        if symbol.id in values
    }


def _objective_values(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
) -> Tuple[ProcessValue, ...]:
    objectives = tuple(
        item
        for item in (analysis.objective, analysis.tie_break)
        if item is not None
    )
    environment = _result_values(scenario, result)
    return tuple(
        evaluate_process_expression(item.value, environment, registry)
        for item in objectives
    )


def _objective_key(analysis: AnalysisIR, values: Tuple[ProcessValue, ...]):
    objectives = tuple(
        item
        for item in (analysis.objective, analysis.tie_break)
        if item is not None
    )
    return tuple(
        value if objective.direction == "maximize" else -value
        for objective, value in zip(objectives, values)
    )


def _optimize(
    analysis: AnalysisIR, scenario: ScenarioIR, registry: UnitRegistry
) -> OptimizeAnalysisResult:
    if _has_random(scenario):
        raise UnsupportedError(
            "optimize currently requires a deterministic Process scenario; use compare/reach for exact random policies",
            analysis.location,
        )
    pending: List[Tuple[str, ...]] = [()]
    complete: List[Tuple[Tuple[ProcessValue, ...], ProcessRunResult]] = []
    explored = 0
    while pending:
        prefix = pending.pop()

        def choose(index, _time, _schedule, available, _values):
            if index >= len(prefix):
                raise _NeedDecision(available)
            return prefix[index]

        try:
            result = run_process_scenario(
                scenario, registry, selector=choose, include_trace=True
            )
        except _NeedDecision as need:
            explored += len(need.available)
            if explored > scenario.bounds.maximum_branches:
                raise ProcessFuelError(
                    "maximum_branches exhausted while expanding policy choices: "
                    f"{explored}/{scenario.bounds.maximum_branches}",
                    analysis.location,
                )
            pending.extend(prefix + (choice,) for choice in reversed(need.available))
            continue
        complete.append((_objective_values(analysis, scenario, result, registry), result))
    if not complete:
        raise ProcessExecutionError("optimization produced no complete policy", analysis.location)
    best_key = max(_objective_key(analysis, values) for values, _result in complete)
    best = [
        (values, result)
        for values, result in complete
        if _objective_key(analysis, values) == best_key
    ]
    # Decision sequences are a stable final tie breaker only for presentation;
    # semantic equality is entirely determined by declared objectives.
    best.sort(key=lambda item: item[1].decisions)
    return OptimizeAnalysisResult(
        analysis.qualified_id,
        analysis.operation,
        best[0][1],
        best[0][0],
        max(explored, 1),
        len(best),
    )


def _finite_states(
    scenario: ScenarioIR, registry: UnitRegistry
) -> Tuple[Tuple[Tuple[str, ProcessValue], ...], ...]:
    from itertools import product
    from .process_ir import BooleanTypeIR, NumberTypeIR, SymbolicTypeIR, SymbolRefIR
    from .process_model import ExpressionSymbolKind

    initial = run_process_scenario(
        scenario, registry, maximum_batches=0, include_trace=False
    )
    instance_inputs = {
        instance_id: dict(values) for instance_id, values in initial.inputs
    }

    members = []
    domains = []
    for instance in scenario.instances:
        for state in instance.process.states:
            name = f"{instance.id}.{state.ref.member_id}"
            if isinstance(state.value_type, BooleanTypeIR):
                values: Tuple[ProcessValue, ...] = (False, True)
            elif isinstance(state.value_type, SymbolicTypeIR):
                values = tuple(
                    registry.domains[state.value_type.domain_id].allowed_values
                )
            elif isinstance(state.value_type, NumberTypeIR) and state.value_type.integer:
                if state.bound is None or state.bound.minimum is None or state.bound.maximum is None:
                    raise UnsupportedError(
                        "steady integer states require explicit finite minimum and maximum bounds",
                        state.location,
                    )
                environment = {
                    SymbolRefIR(
                        instance.process.qualified_id,
                        declaration.ref.member_id,
                        ExpressionSymbolKind.INPUT,
                        declaration.value_type,
                    ): instance_inputs[instance.id][declaration.ref.member_id]
                    for declaration in instance.process.inputs
                }
                minimum = evaluate_process_expression(
                    state.bound.minimum, environment, registry
                )
                maximum = evaluate_process_expression(
                    state.bound.maximum, environment, registry
                )
                assert isinstance(minimum, Fraction) and isinstance(maximum, Fraction)
                step = registry.scale(state.value_type.unit_name, state.location)
                if (
                    minimum > maximum
                    or (minimum / step).denominator != 1
                    or (maximum / step).denominator != 1
                ):
                    raise UnsupportedError(
                        "steady integer state bounds must align to exact unit steps",
                        state.location,
                    )
                values = tuple(
                    Fraction(index) * step
                    for index in range(
                        int(minimum / step), int(maximum / step) + 1
                    )
                )
            else:
                raise UnsupportedError(
                    "steady requires boolean, finite symbolic, or explicitly bounded integer state",
                    state.location,
                )
            members.append(name)
            domains.append(values)
    count = 1
    for domain in domains:
        count *= len(domain)
    if count == 0 or count > scenario.bounds.maximum_branches:
        raise ProcessFuelError(
            "finite steady state space exceeds maximum_branches: "
            f"{count}/{scenario.bounds.maximum_branches}",
            scenario.location,
        )
    return tuple(
        tuple(zip(members, values)) for values in product(*domains)
    )


def _steady(
    analysis: AnalysisIR, scenario: ScenarioIR, registry: UnitRegistry
) -> SteadyAnalysisResult:
    if scenario.decisions or scenario.connections or scenario.stop is not None:
        raise UnsupportedError(
            "steady requires a closed scenario without decisions, connections, or stop",
            analysis.location,
        )
    if any(instance.process.flows for instance in scenario.instances):
        raise UnsupportedError("steady does not accept continuous flow", analysis.location)
    if not scenario.schedules:
        raise UnsupportedError("steady requires an external step event", analysis.location)
    first_time = min(
        schedule.time if hasattr(schedule, "time") else schedule.start
        for schedule in scenario.schedules
    )
    if first_time != 0:
        raise UnsupportedError("steady step events must begin at time zero", analysis.location)
    states = _finite_states(scenario, registry)
    index = {state: position for position, state in enumerate(states)}
    matrix: List[List[Fraction]] = [
        [Fraction(0) for _ in states] for _ in states
    ]
    for source_index, state in enumerate(states):
        overrides = {
            tuple(name.split(".", 1)): value for name, value in state
        }
        outcomes, _explored = _run_distribution(
            scenario,
            registry,
            policy=None,
            include_trace=False,
            initial_state_overrides=overrides,
            maximum_batches=1,
        )
        for outcome in outcomes:
            final_states = dict(outcome.result.states)
            target = tuple(
                (name, dict(final_states[instance_id])[state_id])
                for name, _value in state
                for instance_id, state_id in (name.split(".", 1),)
            )
            if target not in index:
                raise ProcessExecutionError(
                    "steady transition left the declared finite state space",
                    analysis.location,
                )
            matrix[source_index][index[target]] += outcome.probability
        if sum(matrix[source_index], Fraction(0)) != 1:
            raise ProcessExecutionError(
                "steady transition row does not normalize", analysis.location
            )
    size = len(states)
    variables = sp.symbols(f"p0:{size}")
    equations = [
        sp.Eq(
            variables[column],
            sum(
                variables[row]
                * sp.Rational(
                    matrix[row][column].numerator,
                    matrix[row][column].denominator,
                )
                for row in range(size)
            ),
        )
        for column in range(size)
    ]
    equations.append(sp.Eq(sum(variables), 1))
    solution = sp.linsolve(
        [equation.lhs - equation.rhs for equation in equations], variables
    )
    if solution is sp.EmptySet or len(solution) != 1:
        raise ProcessExecutionError(
            "steady distribution is nonexistent or non-unique", analysis.location
        )
    vector = next(iter(solution))
    if any(value.free_symbols or not value.is_Rational for value in vector):
        raise ProcessExecutionError(
            "steady distribution is not uniquely rational", analysis.location
        )
    probabilities = tuple(Fraction(int(value.p), int(value.q)) for value in vector)
    if any(value < 0 for value in probabilities):
        raise ProcessExecutionError(
            "steady solution contains a negative probability", analysis.location
        )
    return SteadyAnalysisResult(
        analysis.qualified_id,
        analysis.operation,
        states,
        probabilities,
        tuple(tuple(row) for row in matrix),
    )


def _cycle(
    analysis: AnalysisIR, scenario: ScenarioIR, registry: UnitRegistry
) -> CycleAnalysisResult:
    if _has_random(scenario):
        raise UnsupportedError("cycle requires a deterministic scenario", analysis.location)
    if scenario.stop is not None:
        raise UnsupportedError("cycle does not accept a stop condition", analysis.location)
    policy = _policy(scenario, analysis.policy_ids)
    selector = selector_for_policy(policy, registry) if policy is not None else None
    initial = run_process_scenario(
        scenario,
        registry,
        selector=selector,
        maximum_batches=0,
        include_trace=False,
    )
    current = initial.states
    seen = {current: 0}
    states = [current]
    runs = []
    for cycle_index in range(1, scenario.bounds.maximum_branches + 1):
        overrides = {
            (instance_id, state_id): value
            for instance_id, instance_states in current
            for state_id, value in instance_states
        }
        result = run_process_scenario(
            scenario,
            registry,
            selector=selector,
            initial_state_overrides=overrides,
            include_trace=True,
        )
        if result.pending_schedule_count:
            raise UnsupportedError(
                "cycle boundary has pending scheduled events; choose a closed cycle horizon",
                analysis.location,
            )
        next_state = result.states
        runs.append(result)
        if next_state in seen:
            preperiod = seen[next_state]
            return CycleAnalysisResult(
                analysis.qualified_id,
                analysis.operation,
                preperiod,
                cycle_index - preperiod,
                tuple(states),
                tuple(runs),
            )
        seen[next_state] = cycle_index
        states.append(next_state)
        current = next_state
    raise ProcessFuelError(
        "maximum_branches exhausted before proving a repeated cycle state",
        analysis.location,
    )


def execute_process_analysis(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    *,
    include_trace: bool = True,
) -> ProcessAnalysisResult:
    """Dispatch a validated analysis without changing Scenario authority."""

    if analysis.scenario_id != scenario.qualified_id:
        raise ProcessExecutionError("analysis/scenario identity mismatch", analysis.location)
    if analysis.operation == "optimize":
        return _optimize(analysis, scenario, registry)
    if analysis.operation == "compare":
        comparisons = []
        for policy_id in analysis.policy_ids:
            policy = _policy(scenario, (policy_id,))
            outcomes, explored = _run_distribution(
                scenario,
                registry,
                policy=policy,
                include_trace=include_trace,
            )
            comparisons.append(
                PolicyComparison(
                    policy_id,
                    RunAnalysisResult(
                        analysis.qualified_id,
                        "run",
                        outcomes,
                        explored,
                    ),
                )
            )
        return CompareAnalysisResult(
            analysis.qualified_id, analysis.operation, tuple(comparisons)
        )
    if analysis.operation == "reach":
        policy = _policy(scenario, analysis.policy_ids)
        outcomes, explored = _run_distribution(
            scenario,
            registry,
            policy=policy,
            reach_target=analysis.target,
            include_trace=include_trace,
        )
        probability = sum(
            (
                item.probability
                for item in outcomes
                if item.result.target_reached
                or (analysis.target is None and item.result.stopped)
            ),
            Fraction(0),
        )
        return ReachAnalysisResult(
            analysis.qualified_id,
            analysis.operation,
            probability,
            outcomes,
            explored,
        )
    if analysis.operation == "run":
        policy = _policy(scenario, analysis.policy_ids)
        outcomes, explored = _run_distribution(
            scenario,
            registry,
            policy=policy,
            include_trace=include_trace,
        )
        return RunAnalysisResult(
            analysis.qualified_id, analysis.operation, outcomes, explored
        )
    if analysis.operation == "steady":
        return _steady(analysis, scenario, registry)
    if analysis.operation == "cycle":
        return _cycle(analysis, scenario, registry)
    raise UnsupportedError(
        f"unsupported Process analysis operation {analysis.operation!r}",
        analysis.location,
    )


def _value_data(value: ProcessValue):
    if isinstance(value, Fraction):
        return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    if isinstance(value, ProcessEventId):
        return {"event_id": value.value}
    if isinstance(value, FrozenMapValue):
        return [
            {"key": _value_data(key), "value": _value_data(item)}
            for key, item in value.entries
        ]
    if isinstance(value, tuple):
        return [_value_data(item) for item in value]
    return value


def _run_data(result: ProcessRunResult) -> dict:
    return {
        "scenario": result.scenario_id,
        "elapsed": _value_data(result.elapsed),
        "stopped": result.stopped,
        "stop_reason": result.stop_reason,
        "target_reached": result.target_reached,
        "event_count": result.event_count,
        "decision_count": result.decision_count,
        "branch_count": result.branch_count,
        "pending_schedule_count": result.pending_schedule_count,
        "inputs": {
            instance_id: {name: _value_data(value) for name, value in values}
            for instance_id, values in result.inputs
        },
        "states": {
            instance_id: {name: _value_data(value) for name, value in values}
            for instance_id, values in result.states
        },
        "observations": {
            name: _value_data(value) for name, value in result.observations
        },
        "decisions": [
            {"time": _value_data(time), "choice": choice}
            for time, choice in result.decisions
        ],
        "trace": [
            {
                "index": item.index,
                "time": _value_data(item.time),
                "phase": item.phase,
                "kind": item.kind,
                "event_id": item.event_id,
                "instance": item.instance_id,
                "member": item.member_id,
                "details": dict(item.details),
            }
            for item in result.trace
        ],
    }


def process_analysis_result_data(
    result: ProcessAnalysisResult,
    analysis: AnalysisIR,
    scenario: ScenarioIR,
) -> dict:
    """Convert exact result objects to the stable JSON/record projection."""

    base = {
        "status": "ok",
        "operation": "process_analysis",
        "analysis": analysis.qualified_id,
        "analysis_operation": analysis.operation,
        "scenario": scenario.qualified_id,
        "phases": [phase.id for phase in scenario.phases],
        "bounds": {
            "horizon": _value_data(scenario.bounds.horizon),
            "maximum_events": scenario.bounds.maximum_events,
            "maximum_decisions": scenario.bounds.maximum_decisions,
            "maximum_branches": scenario.bounds.maximum_branches,
            "maximum_entities": scenario.bounds.maximum_entities,
        },
        "dependency_ids": sorted(
            {analysis.owner_id, scenario.owner_id}
            | {instance.process.owner_id for instance in scenario.instances}
        ),
    }
    if isinstance(result, RunAnalysisResult):
        base.update(
            {
                "explored_branches": result.explored_branches,
                "outcomes": [
                    {
                        "probability": _value_data(item.probability),
                        "run": _run_data(item.result),
                    }
                    for item in result.outcomes
                ],
            }
        )
    elif isinstance(result, CompareAnalysisResult):
        base["policies"] = [
            {
                "policy": item.policy_id,
                "explored_branches": item.result.explored_branches,
                "outcomes": [
                    {
                        "probability": _value_data(outcome.probability),
                        "run": _run_data(outcome.result),
                    }
                    for outcome in item.result.outcomes
                ],
            }
            for item in result.policies
        ]
    elif isinstance(result, OptimizeAnalysisResult):
        base.update(
            {
                "explored_branches": result.explored_branches,
                "tied_optima": result.tied_optima,
                "objective_values": [
                    _value_data(value) for value in result.objective_values
                ],
                "best": _run_data(result.best),
            }
        )
    elif isinstance(result, ReachAnalysisResult):
        base.update(
            {
                "probability": _value_data(result.probability),
                "explored_branches": result.explored_branches,
                "outcomes": [
                    {
                        "probability": _value_data(item.probability),
                        "run": _run_data(item.result),
                    }
                    for item in result.outcomes
                ],
            }
        )
    elif isinstance(result, SteadyAnalysisResult):
        base.update(
            {
                "states": [
                    {name: _value_data(value) for name, value in state}
                    for state in result.states
                ],
                "probabilities": [
                    _value_data(value) for value in result.probabilities
                ],
                "transition_matrix": [
                    [_value_data(value) for value in row]
                    for row in result.transition_matrix
                ],
            }
        )
    elif isinstance(result, CycleAnalysisResult):
        base.update(
            {
                "preperiod": result.preperiod,
                "period": result.period,
                "states": [
                    {
                        instance_id: {
                            name: _value_data(value) for name, value in values
                        }
                        for instance_id, values in state
                    }
                    for state in result.states
                ],
                "runs": [_run_data(run) for run in result.runs],
            }
        )
    else:
        raise TypeError(f"unsupported Process analysis result {type(result).__name__}")
    return base
