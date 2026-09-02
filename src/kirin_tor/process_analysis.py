"""Exact bounded analysis operations over the unified Process runtime."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations_with_replacement, product
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import sympy as sp

from .errors import ProcessExecutionError, ProcessFuelError, UnsupportedError
from .process_expression import ProcessValue, evaluate_process_expression
from .process_expression import FrozenMapValue, ProcessEventId
from .process_ir import BranchEffectIR, EffectIR, NumberTypeIR, WhenEffectIR
from .process_runtime import (
    ContinuousDecisionChoice,
    ProcessRunResult,
    run_process_scenario,
    selector_for_policy,
)
from .process_measure import evaluate_process_measures
from .scenario_ir import (
    AnalysisIR,
    AtScheduleIR,
    ContinuousDecisionIR,
    EveryScheduleIR,
    ObjectiveIR,
    PolicyIR,
    ScenarioIR,
)
from .units import UnitRegistry


@dataclass(frozen=True)
class WeightedProcessRun:
    probability: Fraction
    result: ProcessRunResult
    measures: Tuple[Tuple[str, ProcessValue], ...] = ()


@dataclass(frozen=True)
class RunAnalysisResult:
    analysis_id: str
    operation: str
    outcomes: Tuple[WeightedProcessRun, ...]
    explored_branches: int
    measure_expectations: Tuple[Tuple[str, Fraction], ...] = ()


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
class SolverProof:
    level: str
    method: str
    error_bound: Optional[Fraction] = None
    tolerance: Optional[Fraction] = None
    time_grid: Optional[Fraction] = None
    search_budget: Optional[int] = None
    budget_exhausted: bool = False

    def __post_init__(self) -> None:
        if self.level not in {
            "exact_global",
            "global_with_error_bound",
            "best_found",
        }:
            raise ValueError(f"unknown solver proof level {self.level!r}")
        if self.level == "global_with_error_bound" and self.error_bound is None:
            raise ValueError("global_with_error_bound requires an error bound")


@dataclass(frozen=True)
class OptimalStrategyResult:
    run: ProcessRunResult
    measures: Tuple[Tuple[str, ProcessValue], ...]
    objective_values: Tuple[ProcessValue, ...]
    constraints: Tuple[bool, ...]


@dataclass(frozen=True)
class ObjectiveOptimizationResult:
    objective_id: str
    optima: Tuple[OptimalStrategyResult, ...]
    proof: SolverProof


@dataclass(frozen=True)
class SearchCandidateResult:
    decisions: Tuple[Tuple[Fraction, str], ...]
    measures: Tuple[Tuple[str, ProcessValue], ...]


@dataclass(frozen=True)
class VariantOptimizationResult:
    variant_id: str
    input_overrides: Tuple[Tuple[str, ProcessValue], ...]
    objectives: Tuple[ObjectiveOptimizationResult, ...]
    explored_branches: int
    candidates: Tuple[SearchCandidateResult, ...]


@dataclass(frozen=True)
class OptimizeAnalysisResult:
    analysis_id: str
    operation: str
    variants: Tuple[VariantOptimizationResult, ...]
    explored_branches: int


@dataclass(frozen=True)
class ReachAnalysisResult:
    analysis_id: str
    operation: str
    probability: Fraction
    outcomes: Tuple[WeightedProcessRun, ...]
    explored_branches: int
    measure_expectations: Tuple[Tuple[str, Fraction], ...] = ()


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
    evaluate_measures: bool = True,
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
        measures = (
            evaluate_process_measures(scenario, result, registry)
            if evaluate_measures
            else ()
        )
        return (WeightedProcessRun(Fraction(1), result, measures),), 1

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
        measures = (
            evaluate_process_measures(scenario, result, registry)
            if evaluate_measures
            else ()
        )
        outcomes.append(WeightedProcessRun(weight, result, measures))
    total = sum((item.probability for item in outcomes), Fraction(0))
    if total != 1:
        raise ProcessExecutionError(
            f"random Process outcomes do not normalize exactly; got {total}",
            scenario.location,
        )
    return tuple(outcomes), max(explored, 1)


def _measure_expectations(
    scenario: ScenarioIR, outcomes: Sequence[WeightedProcessRun]
) -> Tuple[Tuple[str, Fraction], ...]:
    numeric_ids = {
        measure.id
        for measure in scenario.measures
        if isinstance(measure.value_type, NumberTypeIR)
    }
    return tuple(
        (
            measure.id,
            sum(
                (
                    outcome.probability * dict(outcome.measures)[measure.id]
                    for outcome in outcomes
                ),
                Fraction(0),
            ),
        )
        for measure in scenario.measures
        if measure.id in numeric_ids
    )


def _objective_values(
    objective: ObjectiveIR, measures: Mapping[str, ProcessValue]
) -> Tuple[ProcessValue, ...]:
    return tuple(measures[term.measure_id] for term in objective.terms)


def _objective_key(objective: ObjectiveIR, values: Tuple[ProcessValue, ...]):
    return tuple(
        value if term.direction == "maximize" else -value
        for term, value in zip(objective.terms, values)
    )


def _constraints_hold(
    objective: ObjectiveIR,
    measures: Mapping[str, ProcessValue],
    registry: UnitRegistry,
) -> Tuple[bool, ...]:
    result = []
    for constraint in objective.constraints:
        environment = {
            reference: measures[reference.id]
            for reference in constraint.references
            if reference.id in measures
        }
        value = evaluate_process_expression(constraint, environment, registry)
        assert isinstance(value, bool)
        result.append(value)
    return tuple(result)


def _select_objectives(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    complete: Sequence[
        Tuple[Tuple[Tuple[str, ProcessValue], ...], ProcessRunResult]
    ],
    proof: SolverProof,
) -> Tuple[ObjectiveOptimizationResult, ...]:
    if not complete:
        raise ProcessExecutionError("optimization produced no feasible policy", analysis.location)
    declarations = {item.id: item for item in scenario.objectives}
    optimized = []
    for objective_id in analysis.objective_ids:
        objective = declarations[objective_id]
        feasible = []
        for measure_values, result in complete:
            measures = dict(measure_values)
            constraints = _constraints_hold(objective, measures, registry)
            if all(constraints):
                feasible.append(
                    (
                        _objective_values(objective, measures),
                        measure_values,
                        constraints,
                        result,
                    )
                )
        if not feasible:
            raise ProcessExecutionError(
                f"objective {objective_id!r} has no strategy satisfying all constraints",
                objective.location,
            )
        best_key = max(
            _objective_key(objective, values)
            for values, _measures, _constraints, _result in feasible
        )
        best = [
            item
            for item in feasible
            if _objective_key(objective, item[0]) == best_key
        ]
        # Sorting makes the projection reproducible, but every semantic tie is
        # returned. Enumeration order is never promoted to an author preference.
        best.sort(key=lambda item: item[3].decisions)
        optimized.append(
            ObjectiveOptimizationResult(
                objective_id,
                tuple(
                    OptimalStrategyResult(run, measures, values, constraints)
                    for values, measures, constraints, run in best
                ),
                proof,
            )
        )
    return tuple(optimized)


def _optimize_finite(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    input_overrides: Mapping[Tuple[str, str], ProcessValue],
    include_trace: bool,
) -> Tuple[
    Tuple[ObjectiveOptimizationResult, ...],
    int,
    Tuple[SearchCandidateResult, ...],
]:
    pending: List[Tuple[str, ...]] = [()]
    complete: List[
        Tuple[Tuple[Tuple[str, ProcessValue], ...], ProcessRunResult]
    ] = []
    explored = 0
    while pending:
        prefix = pending.pop()

        def choose(index, _time, _schedule, available, _values):
            if index >= len(prefix):
                raise _NeedDecision(available)
            return prefix[index]

        try:
            result = run_process_scenario(
                scenario,
                registry,
                selector=choose,
                include_trace=include_trace,
                input_overrides=input_overrides,
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
        complete.append((evaluate_process_measures(scenario, result, registry), result))
    return (
        _select_objectives(
            analysis,
            scenario,
            registry,
            complete,
            SolverProof(
                "exact_global",
                "exhaustive_finite_policy_enumeration",
                search_budget=scenario.bounds.maximum_branches,
            ),
        ),
        max(explored, 1),
        tuple(
            SearchCandidateResult(run.decisions, measures)
            for measures, run in complete
        ),
    )


def _scheduled_times(scenario: ScenarioIR) -> Tuple[Fraction, ...]:
    result = set()
    for schedule in scenario.schedules:
        if isinstance(schedule, AtScheduleIR):
            result.add(schedule.time)
            continue
        assert isinstance(schedule, EveryScheduleIR)
        end = min(
            scenario.bounds.horizon,
            schedule.end if schedule.end is not None else scenario.bounds.horizon,
        )
        current = schedule.start
        while current <= end:
            result.add(current)
            current += schedule.interval
    return tuple(sorted(result))


def _refined_times(
    schedule: ContinuousDecisionIR,
    semantic_times: Sequence[Fraction],
    depth: int,
) -> Tuple[Fraction, ...]:
    points = {
        schedule.start,
        schedule.end,
        (schedule.start + schedule.end) / 2,
        *(
            time
            for time in semantic_times
            if schedule.start <= time <= schedule.end
        ),
    }
    for _ in range(depth):
        ordered = sorted(points)
        points.update(
            (left + right) / 2
            for left, right in zip(ordered, ordered[1:])
        )
    return tuple(sorted(points))


def _schedule_candidate_plans(
    schedule_index: int,
    schedule: ContinuousDecisionIR,
    times: Sequence[Fraction],
):
    yield ()
    for count in range(1, schedule.maximum_occurrences + 1):
        for selected_times in combinations_with_replacement(times, count):
            for selected_actions in product(schedule.action_ids, repeat=count):
                yield tuple(
                    ContinuousDecisionChoice(schedule_index, time, action)
                    for time, action in zip(selected_times, selected_actions)
                )


def _combined_continuous_plans(
    schedules: Sequence[ContinuousDecisionIR],
    points: Sequence[Sequence[Fraction]],
    index: int = 0,
    prefix: Tuple[ContinuousDecisionChoice, ...] = (),
):
    if index == len(schedules):
        yield tuple(
            sorted(
                prefix,
                key=lambda item: (item.time, item.schedule_index),
            )
        )
        return
    for local in _schedule_candidate_plans(index, schedules[index], points[index]):
        yield from _combined_continuous_plans(
            schedules, points, index + 1, prefix + local
        )


def _optimize_continuous(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    input_overrides: Mapping[Tuple[str, str], ProcessValue],
    include_trace: bool,
) -> Tuple[
    Tuple[ObjectiveOptimizationResult, ...],
    int,
    Tuple[SearchCandidateResult, ...],
]:
    if analysis.search_method != "adaptive_dyadic":
        raise UnsupportedError(
            "continuous-time optimization requires adaptive_dyadic search settings",
            analysis.location,
        )
    assert analysis.time_tolerance is not None
    assert analysis.maximum_evaluations is not None
    choice_sources = (
        *scenario.decisions,
        *scenario.event_decisions,
        *scenario.condition_decisions,
    )
    if any(
        len(schedule.action_ids) + int(getattr(schedule, "allow_wait", False)) > 1
        for schedule in choice_sources
    ):
        raise UnsupportedError(
            "continuous-time optimization cannot yet mix free times with another branching decision source",
            analysis.location,
        )
    semantic_times = _scheduled_times(scenario)
    seen = set()
    complete = []
    evaluated = 0
    depth = 0
    budget_exhausted = False
    while evaluated < analysis.maximum_evaluations:
        points = tuple(
            _refined_times(schedule, semantic_times, depth)
            for schedule in scenario.continuous_decisions
        )
        found_new = False
        for plan in _combined_continuous_plans(
            scenario.continuous_decisions, points
        ):
            canonical = tuple(
                (item.schedule_index, item.time, item.action_id) for item in plan
            )
            if canonical in seen:
                continue
            seen.add(canonical)
            found_new = True
            if evaluated >= analysis.maximum_evaluations:
                budget_exhausted = True
                break
            evaluated += 1
            try:
                run = run_process_scenario(
                    scenario,
                    registry,
                    include_trace=include_trace,
                    continuous_choices=plan,
                    input_overrides=input_overrides,
                )
            except ProcessExecutionError as exc:
                if "unavailable action" in exc.message or "is unavailable" in exc.message:
                    continue
                raise
            complete.append(
                (evaluate_process_measures(scenario, run, registry), run)
            )
        maximum_gap = max(
            (
                max(
                    (right - left for left, right in zip(items, items[1:])),
                    default=Fraction(0),
                )
                for items in points
            ),
            default=Fraction(0),
        )
        if maximum_gap <= analysis.time_tolerance:
            break
        if not found_new:
            break
        depth += 1
    if evaluated >= analysis.maximum_evaluations:
        budget_exhausted = True
    degenerate = all(
        schedule.start == schedule.end
        for schedule in scenario.continuous_decisions
    )
    level = "exact_global" if degenerate and not budget_exhausted else "best_found"
    method = (
        "exhaustive_degenerate_continuous_choices"
        if level == "exact_global"
        else "adaptive_dyadic_candidate_search"
    )
    return (
        _select_objectives(
            analysis,
            scenario,
            registry,
            complete,
            SolverProof(
                level,
                method,
                tolerance=analysis.time_tolerance,
                search_budget=analysis.maximum_evaluations,
                budget_exhausted=budget_exhausted,
            ),
        ),
        max(evaluated, 1),
        tuple(
            SearchCandidateResult(run.decisions, measures)
            for measures, run in complete
        ),
    )


def _optimize(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    include_trace: bool,
) -> OptimizeAnalysisResult:
    if _has_random(scenario):
        raise UnsupportedError(
            "optimize currently requires a deterministic Process scenario; use compare/reach for exact random policies",
            analysis.location,
        )
    declarations = {variant.id: variant for variant in scenario.variants}
    selected = analysis.variant_ids or ("base",)
    variants = []
    total_explored = 0
    for variant_id in selected:
        if variant_id == "base":
            input_overrides = {}
            rendered_overrides = ()
        else:
            variant = declarations[variant_id]
            input_overrides = {
                (binding.input.instance_id, binding.input.member.member_id):
                evaluate_process_expression(binding.value, {}, registry)
                for binding in variant.inputs
            }
            rendered_overrides = tuple(
                (
                    f"{binding.input.instance_id}.{binding.input.member.member_id}",
                    input_overrides[(
                        binding.input.instance_id,
                        binding.input.member.member_id,
                    )],
                )
                for binding in variant.inputs
            )
        if scenario.continuous_decisions:
            objectives, explored, candidates = _optimize_continuous(
                analysis, scenario, registry, input_overrides, include_trace
            )
        else:
            objectives, explored, candidates = _optimize_finite(
                analysis, scenario, registry, input_overrides, include_trace
            )
        total_explored += explored
        variants.append(
            VariantOptimizationResult(
                variant_id,
                rendered_overrides,
                objectives,
                explored,
                candidates,
            )
        )
    return OptimizeAnalysisResult(
        analysis.qualified_id,
        analysis.operation,
        tuple(variants),
        total_explored,
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
            evaluate_measures=False,
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
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    include_trace: bool,
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
            include_trace=include_trace,
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
        return _optimize(analysis, scenario, registry, include_trace)
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
                        _measure_expectations(scenario, outcomes),
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
            _measure_expectations(scenario, outcomes),
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
            analysis.qualified_id,
            analysis.operation,
            outcomes,
            explored,
            _measure_expectations(scenario, outcomes),
        )
    if analysis.operation == "steady":
        return _steady(analysis, scenario, registry)
    if analysis.operation == "cycle":
        return _cycle(analysis, scenario, registry, include_trace)
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
        "observation_samples": [
            {
                "index": sample.index,
                "time": _value_data(sample.time),
                "phase": sample.phase,
                "values": {
                    name: _value_data(value) for name, value in sample.values
                },
            }
            for sample in result.observation_samples
        ],
        "output_events": [
            {
                "event_id": event.id.value,
                "time": _value_data(event.time),
                "phase": event.phase,
                "instance": event.instance_id,
                "member": event.event_id,
                "arguments": {
                    name: _value_data(value) for name, value in event.arguments
                },
            }
            for event in result.output_events
        ],
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
        "random_semantics": (
            "strict_finite_output_expectation"
            if _has_random(scenario)
            else "deterministic_scenario"
        ),
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
    if analysis.search_method is not None:
        base["search"] = {
            "method": analysis.search_method,
            "time_tolerance": _value_data(analysis.time_tolerance),
            "maximum_evaluations": analysis.maximum_evaluations,
        }
    if isinstance(result, RunAnalysisResult):
        base.update(
            {
                "explored_branches": result.explored_branches,
                "outcomes": [
                    {
                        "probability": _value_data(item.probability),
                        "measures": {
                            name: _value_data(value)
                            for name, value in item.measures
                        },
                        "run": _run_data(item.result),
                    }
                    for item in result.outcomes
                ],
                "measure_expectations": {
                    name: _value_data(value)
                    for name, value in result.measure_expectations
                },
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
                        "measures": {
                            name: _value_data(value)
                            for name, value in outcome.measures
                        },
                        "run": _run_data(outcome.result),
                    }
                    for outcome in item.result.outcomes
                ],
                "measure_expectations": {
                    name: _value_data(value)
                    for name, value in item.result.measure_expectations
                },
            }
            for item in result.policies
        ]
    elif isinstance(result, OptimizeAnalysisResult):
        base.update(
            {
                "explored_branches": result.explored_branches,
                "variants": [
                    {
                        "variant": variant.variant_id,
                        "input_overrides": {
                            name: _value_data(value)
                            for name, value in variant.input_overrides
                        },
                        "explored_branches": variant.explored_branches,
                        "objectives": [
                            {
                                "objective": item.objective_id,
                                "proof": {
                                    "level": item.proof.level,
                                    "method": item.proof.method,
                                    "error_bound": _value_data(item.proof.error_bound)
                                    if item.proof.error_bound is not None
                                    else None,
                                    "tolerance": _value_data(item.proof.tolerance)
                                    if item.proof.tolerance is not None
                                    else None,
                                    "time_grid": _value_data(item.proof.time_grid)
                                    if item.proof.time_grid is not None
                                    else None,
                                    "search_budget": item.proof.search_budget,
                                    "budget_exhausted": item.proof.budget_exhausted,
                                },
                                "tied_optima": len(item.optima),
                                "optimal_strategies": [
                                    {
                                        "objective_values": [
                                            _value_data(value)
                                            for value in optimum.objective_values
                                        ],
                                        "constraints": list(optimum.constraints),
                                        "measures": {
                                            name: _value_data(value)
                                            for name, value in optimum.measures
                                        },
                                        "run": _run_data(optimum.run),
                                    }
                                    for optimum in item.optima
                                ],
                            }
                            for item in variant.objectives
                        ],
                    }
                    for variant in result.variants
                ],
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
                        "measures": {
                            name: _value_data(value)
                            for name, value in item.measures
                        },
                        "run": _run_data(item.result),
                    }
                    for item in result.outcomes
                ],
                "measure_expectations": {
                    name: _value_data(value)
                    for name, value in result.measure_expectations
                },
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
    if analysis.charts:
        from .process_chart import process_charts_data

        base["charts"] = process_charts_data(result, analysis, scenario)
    return base
