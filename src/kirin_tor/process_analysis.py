"""Exact bounded analysis operations over the unified Process runtime."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations, combinations_with_replacement, product
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import sympy as sp

from .errors import (
    InfeasibleDecisionError,
    ProcessExecutionError,
    ProcessFuelError,
    UnsupportedError,
)
from .process_expression import ProcessValue, evaluate_process_expression
from .process_expression import FrozenMapValue, ProcessEventId
from .process_ir import BranchEffectIR, EffectIR, NumberTypeIR, WhenEffectIR
from .process_runtime import (
    ContinuousDecisionChoice,
    DeterministicProcessExecutor,
    ProcessRunResult,
    run_process_scenario,
    selector_for_policy,
)
from .process_measure import (
    advance_process_measure_state,
    evaluate_process_measures,
    evaluate_process_measures_from_state,
    initialize_process_measure_state,
    process_measure_state_signature,
)
from .scenario_ir import (
    AnalysisIR,
    AtScheduleIR,
    ContinuousDecisionIR,
    EveryScheduleIR,
    ObjectiveIR,
    PolicyIR,
    ScenarioIR,
    TrajectoryMeasureExpressionIR,
)
from .units import UnitRegistry


@dataclass(frozen=True)
class WeightedProcessRun:
    probability: Fraction
    result: ProcessRunResult
    measures: Tuple[Tuple[str, ProcessValue], ...] = ()
    path_count: int = 1


@dataclass(frozen=True, slots=True)
class AdaptiveDecisionRule:
    """One reachable information state in an exact adaptive policy."""

    decision_index: int
    time: Fraction
    schedule_kind: str
    schedule_index: int
    observations: Tuple[Tuple[str, ProcessValue], ...]
    history: Tuple[Tuple[Fraction, str], ...]
    available_actions: Tuple[str, ...]
    optimal_actions: Tuple[str, ...]
    selected_action: str


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
    candidate_plans: Optional[int] = None
    executed_plans: Optional[int] = None
    pruned_plans: int = 0

    def __post_init__(self) -> None:
        if self.level not in {
            "exact_global",
            "global_with_error_bound",
            "best_found",
        }:
            raise ValueError(f"unknown solver proof level {self.level!r}")
        if self.level == "global_with_error_bound" and self.error_bound is None:
            raise ValueError("global_with_error_bound requires an error bound")
        if self.candidate_plans is None:
            if self.executed_plans is not None or self.pruned_plans:
                raise ValueError(
                    "plan proof counts require candidate_plans"
                )
        elif (
            self.executed_plans is None
            or min(
                self.candidate_plans,
                self.executed_plans,
                self.pruned_plans,
            )
            < 0
            or self.executed_plans + self.pruned_plans
            != self.candidate_plans
        ):
            raise ValueError(
                "candidate_plans must equal executed_plans plus pruned_plans"
            )


@dataclass(frozen=True)
class OptimalStrategyResult:
    run: Optional[ProcessRunResult]
    measures: Tuple[Tuple[str, ProcessValue], ...]
    objective_values: Tuple[ProcessValue, ...]
    constraints: Tuple[bool, ...]
    outcomes: Tuple[WeightedProcessRun, ...] = ()
    decisions: Tuple[Tuple[Fraction, str], ...] = ()
    chance_probabilities: Tuple[Fraction, ...] = ()
    policy_rules: Tuple[AdaptiveDecisionRule, ...] = ()


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
class _PlanEvaluation:
    decisions: Tuple[Tuple[Fraction, str], ...]
    measures: Tuple[Tuple[str, ProcessValue], ...]
    run: Optional[ProcessRunResult] = None
    outcomes: Tuple[WeightedProcessRun, ...] = ()


@dataclass(frozen=True)
class _PlanEvaluationAttempt:
    evaluation: Optional[_PlanEvaluation]
    infeasible_prefix: Optional[Tuple[ContinuousDecisionChoice, ...]] = None


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
    def __init__(
        self,
        index: int,
        time: Fraction,
        schedule: object,
        available: Tuple[str, ...],
        observations: Mapping[str, ProcessValue],
        history: Tuple[Tuple[Fraction, str], ...],
    ):
        self.index = index
        self.time = time
        self.schedule = schedule
        self.available = available
        self.observations = tuple(sorted(observations.items()))
        self.history = history


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


def scenario_has_random_branches(scenario: ScenarioIR) -> bool:
    """Expose the validated random-branch classification to request projections."""

    return _has_random(scenario)


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
    input_overrides: Optional[Mapping[Tuple[str, str], ProcessValue]] = None,
    continuous_choices: Sequence[ContinuousDecisionChoice] = (),
    aggregate_equivalent_states: bool = False,
    decision_selector_override=None,
) -> Tuple[Tuple[WeightedProcessRun, ...], int]:
    if policy is not None and decision_selector_override is not None:
        raise ProcessExecutionError(
            "random distribution received two decision selectors"
        )
    decision_selector = (
        decision_selector_override
        if decision_selector_override is not None
        else selector_for_policy(policy, registry) if policy else None
    )
    if not _has_random(scenario):
        result = run_process_scenario(
            scenario,
            registry,
            selector=decision_selector,
            reach_target=reach_target,
            include_trace=include_trace,
            initial_state_overrides=initial_state_overrides,
            input_overrides=input_overrides,
            maximum_batches=maximum_batches,
            continuous_choices=continuous_choices,
        )
        measures = (
            evaluate_process_measures(scenario, result, registry)
            if evaluate_measures
            else ()
        )
        return (WeightedProcessRun(Fraction(1), result, measures),), 1

    initial = DeterministicProcessExecutor(
        scenario,
        registry,
        selector=decision_selector,
        reach_target=reach_target,
        include_trace=include_trace,
        initial_state_overrides=initial_state_overrides,
        input_overrides=input_overrides,
        continuous_choices=continuous_choices,
    )
    initial.start()
    frontier: List[
        Tuple[DeterministicProcessExecutor, Fraction, int, int]
    ] = [
        (initial, Fraction(1), 0, 1)
    ]
    outcomes: List[WeightedProcessRun] = []
    explored = 0

    def finish(
        executor: DeterministicProcessExecutor,
        weight: Fraction,
        path_count: int,
    ) -> None:
        result = executor.result()
        measures = (
            evaluate_process_measures(scenario, result, registry)
            if evaluate_measures
            else ()
        )
        outcomes.append(
            WeightedProcessRun(weight, result, measures, path_count)
        )

    while frontier:
        next_frontier: List[
            Tuple[DeterministicProcessExecutor, Fraction, int, int]
        ] = []
        for (
            checkpoint,
            checkpoint_weight,
            processed_batches,
            checkpoint_path_count,
        ) in frontier:
            if checkpoint.is_complete:
                finish(
                    checkpoint, checkpoint_weight, checkpoint_path_count
                )
                continue
            if (
                maximum_batches is not None
                and processed_batches >= maximum_batches
            ):
                checkpoint.stop_reason = "batch_limit"
                finish(
                    checkpoint, checkpoint_weight, checkpoint_path_count
                )
                continue

            batch_pending: List[Tuple[Tuple[int, ...], Fraction]] = [
                ((), checkpoint_weight)
            ]
            while batch_pending:
                prefix, weight = batch_pending.pop()
                trial = checkpoint.clone()
                first_branch_index = trial.branch_decision_count

                def choose_branch(
                    index, _event, _branch, probabilities, _environment
                ):
                    local_index = index - first_branch_index
                    if local_index < 0:
                        raise ProcessExecutionError(
                            "random batch branch index moved backward",
                            scenario.location,
                        )
                    if local_index >= len(prefix):
                        possible = tuple(
                            index
                            for index, probability in enumerate(probabilities)
                            if probability
                        )
                        if len(possible) == 1:
                            return possible[0]
                        raise _NeedBranch(probabilities)
                    return prefix[local_index]

                trial.branch_selector = choose_branch
                try:
                    ran_batch = trial.run_next_batch()
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
                    batch_pending.extend(
                        (prefix + (index,), weight * probability)
                        for index, probability in reversed(choices)
                    )
                    continue

                next_batch_count = processed_batches + int(ran_batch)
                if (
                    trial.is_complete
                    or maximum_batches is not None
                    and next_batch_count >= maximum_batches
                ):
                    if not trial.is_complete:
                        trial.stop_reason = "batch_limit"
                    finish(trial, weight, checkpoint_path_count)
                else:
                    next_frontier.append(
                        (
                            trial,
                            weight,
                            next_batch_count,
                            checkpoint_path_count,
                        )
                    )

        if aggregate_equivalent_states and next_frontier:
            grouped: Dict[
                Tuple[object, ...],
                Tuple[DeterministicProcessExecutor, Fraction, int, int],
            ] = {}
            for executor, weight, batch_count, path_count in next_frontier:
                result = executor.result()
                signature = (
                    executor.continuation_signature(),
                    process_measure_state_signature(
                        scenario, result, registry
                    ),
                )
                existing = grouped.get(signature)
                if existing is None:
                    grouped[signature] = (
                        executor,
                        weight,
                        batch_count,
                        path_count,
                    )
                    continue
                (
                    representative,
                    existing_weight,
                    existing_batch_count,
                    existing_path_count,
                ) = existing
                assert existing_batch_count == batch_count
                grouped[signature] = (
                    representative,
                    existing_weight + weight,
                    batch_count,
                    existing_path_count + path_count,
                )
            frontier = list(grouped.values())
        else:
            frontier = next_frontier
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


def _conditions_hold(
    conditions,
    measures: Mapping[str, ProcessValue],
    registry: UnitRegistry,
) -> Tuple[bool, ...]:
    result = []
    for constraint in conditions:
        environment = {
            reference: measures[reference.id]
            for reference in constraint.references
            if reference.id in measures
        }
        value = evaluate_process_expression(constraint, environment, registry)
        assert isinstance(value, bool)
        result.append(value)
    return tuple(result)


def _chance_constraint_passes(
    comparison: str, probability: Fraction, threshold: Fraction
) -> bool:
    if comparison == "at_least":
        return probability >= threshold
    assert comparison == "at_most"
    return probability <= threshold


def _single_run_chance_constraints(
    objective: ObjectiveIR,
    measures: Mapping[str, ProcessValue],
    registry: UnitRegistry,
) -> Tuple[Tuple[Fraction, ...], Tuple[bool, ...]]:
    probabilities = tuple(
        Fraction(
            int(
                _conditions_hold(
                    (constraint.condition,), measures, registry
                )[0]
            )
        )
        for constraint in objective.chance_constraints
    )
    return probabilities, tuple(
        _chance_constraint_passes(
            constraint.comparison, probability, constraint.threshold
        )
        for constraint, probability in zip(
            objective.chance_constraints, probabilities
        )
    )


def _random_chance_constraints(
    objective: ObjectiveIR,
    outcomes: Sequence[WeightedProcessRun],
    registry: UnitRegistry,
) -> Tuple[Tuple[Fraction, ...], Tuple[bool, ...]]:
    probabilities = tuple(
        sum(
            (
                outcome.probability
                for outcome in outcomes
                if _conditions_hold(
                    (constraint.condition,),
                    dict(outcome.measures),
                    registry,
                )[0]
            ),
            Fraction(0),
        )
        for constraint in objective.chance_constraints
    )
    return probabilities, tuple(
        _chance_constraint_passes(
            constraint.comparison, probability, constraint.threshold
        )
        for constraint, probability in zip(
            objective.chance_constraints, probabilities
        )
    )


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
            ordinary_constraints = _conditions_hold(
                (*objective.constraints, *objective.path_constraints),
                measures,
                registry,
            )
            chance_probabilities, chance_constraints = (
                _single_run_chance_constraints(objective, measures, registry)
            )
            constraints = ordinary_constraints + chance_constraints
            if all(constraints):
                feasible.append(
                    (
                        _objective_values(objective, measures),
                        measure_values,
                        constraints,
                        chance_probabilities,
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
            for values, _measures, _constraints, _probabilities, _result in feasible
        )
        best = [
            item
            for item in feasible
            if _objective_key(objective, item[0]) == best_key
        ]
        # Sorting makes the projection reproducible, but every semantic tie is
        # returned. Enumeration order is never promoted to an author preference.
        best.sort(key=lambda item: item[4].decisions)
        optimized.append(
            ObjectiveOptimizationResult(
                objective_id,
                tuple(
                    OptimalStrategyResult(
                        run,
                        measures,
                        values,
                        constraints,
                        chance_probabilities=probabilities,
                    )
                    for values, measures, constraints, probabilities, run in best
                ),
                proof,
            )
        )
    return tuple(optimized)


def _select_stochastic_objectives(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    complete: Sequence[
        Tuple[
            Tuple[Tuple[str, ProcessValue], ...],
            Tuple[Tuple[Fraction, str], ...],
            Tuple[WeightedProcessRun, ...],
        ]
    ],
    proof: SolverProof,
) -> Tuple[ObjectiveOptimizationResult, ...]:
    """Optimize precommitted plans over exact finite output expectations."""

    if not complete:
        raise ProcessExecutionError("optimization produced no feasible policy", analysis.location)
    declarations = {item.id: item for item in scenario.objectives}
    optimized = []
    for objective_id in analysis.objective_ids:
        objective = declarations[objective_id]
        feasible = []
        for measure_values, decisions, outcomes in complete:
            measures = dict(measure_values)
            referenced = {
                reference.id
                for constraint in objective.constraints
                for reference in constraint.references
            }
            missing = sorted(referenced - measures.keys())
            if missing:
                raise UnsupportedError(
                    "random optimize constraints may reference only numeric Measures "
                    "interpreted as exact expectations; unsupported: "
                    + ", ".join(missing),
                    objective.location,
                )
            expected_constraints = _conditions_hold(
                objective.constraints,
                measures,
                registry,
            )
            path_constraints = tuple(
                all(
                    _conditions_hold(
                        (constraint,),
                        dict(outcome.measures),
                        registry,
                    )[0]
                    for outcome in outcomes
                )
                for constraint in objective.path_constraints
            )
            chance_probabilities, chance_constraints = _random_chance_constraints(
                objective, outcomes, registry
            )
            constraints = (
                expected_constraints + path_constraints + chance_constraints
            )
            if all(constraints):
                feasible.append(
                    (
                        _objective_values(objective, measures),
                        measure_values,
                        constraints,
                        chance_probabilities,
                        decisions,
                        outcomes,
                    )
                )
        if not feasible:
            raise ProcessExecutionError(
                f"objective {objective_id!r} has no strategy satisfying all constraints",
                objective.location,
            )
        best_key = max(
            _objective_key(objective, values)
            for (
                values,
                _measures,
                _constraints,
                _probabilities,
                _decisions,
                _outcomes,
            ) in feasible
        )
        best = [
            item
            for item in feasible
            if _objective_key(objective, item[0]) == best_key
        ]
        best.sort(key=lambda item: item[4])
        optimized.append(
            ObjectiveOptimizationResult(
                objective_id,
                tuple(
                    OptimalStrategyResult(
                        None,
                        measures,
                        values,
                        constraints,
                        outcomes,
                        decisions,
                        probabilities,
                    )
                    for (
                        values,
                        measures,
                        constraints,
                        probabilities,
                        decisions,
                        outcomes,
                    ) in best
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

        def choose(index, time, schedule, available, values, history):
            if index >= len(prefix):
                raise _NeedDecision(
                    index,
                    time,
                    schedule,
                    available,
                    values,
                    tuple(item for item in history if item[1] != "wait"),
                )
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


@dataclass(frozen=True, slots=True)
class _AdaptivePolicySolution:
    objective_values: Tuple[ProcessValue, ...]


def _decision_schedule_identity(
    scenario: ScenarioIR, schedule: object
) -> Tuple[str, int]:
    sources = (
        ("fixed", scenario.decisions),
        ("event", scenario.event_decisions),
        ("condition", scenario.condition_decisions),
    )
    for kind, declarations in sources:
        for index, declaration in enumerate(declarations):
            if declaration is schedule:
                return kind, index
    raise ProcessExecutionError(
        "adaptive decision does not belong to the scenario"
    )


def _optimize_stochastic_policy(
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
    """Solve a finite fully observable random policy by exact backward recursion.

    Expected lexicographic objectives and all-path constraints decompose over
    independent future information states.  Expected-value and chance
    constraints do not, so they remain intentionally outside this proof mode.
    """

    if scenario.continuous_decisions:
        raise UnsupportedError(
            "exact adaptive policy optimization uses fixed, event, or condition "
            "decision points, not free continuous decision times",
            analysis.location,
        )
    if not (
        scenario.decisions
        or scenario.event_decisions
        or scenario.condition_decisions
    ):
        raise UnsupportedError(
            "adaptive policy optimization requires at least one reachable decision",
            analysis.location,
        )
    declarations = {item.id: item for item in scenario.objectives}
    preserve_paths = any(
        chart.kind == "trajectory" for chart in analysis.charts
    )
    optimized = []
    total_explored = 0

    for objective_id in analysis.objective_ids:
        objective = declarations[objective_id]
        if objective.constraints:
            raise UnsupportedError(
                "exact adaptive policy optimization does not accept constraints "
                "over global expectations; use require all_paths for a guarantee",
                objective.location,
            )
        if objective.chance_constraints:
            raise UnsupportedError(
                "exact adaptive policy optimization does not yet accept chance "
                "constraints because they couple otherwise independent information states",
                objective.location,
            )

        explored = 0
        measure_declarations = {
            measure.id: measure for measure in scenario.measures
        }
        additive_term_ids = {
            term.measure_id
            for term in objective.terms
            if isinstance(
                measure_declarations[term.measure_id].expression,
                TrajectoryMeasureExpressionIR,
            )
            and measure_declarations[
                term.measure_id
            ].expression.operation in {"sum_events", "count_events"}
        }
        required_measure_ids = tuple(
            dict.fromkeys(
                (
                    *(
                        term.measure_id
                        for term in objective.terms
                        if term.measure_id not in additive_term_ids
                    ),
                    *(
                        reference.id
                        for constraint in objective.path_constraints
                        for reference in constraint.references
                        if reference.kind.value == "measure"
                    ),
                )
            )
        )
        tracked_measure_ids = tuple(
            dict.fromkeys(
                (
                    *(term.measure_id for term in objective.terms),
                    *(
                        reference.id
                        for constraint in objective.path_constraints
                        for reference in constraint.references
                        if reference.kind.value == "measure"
                    ),
                )
            )
        )
        required_signature_ids: set[str] = set()
        memo: Dict[
            Tuple[object, ...], Optional[_AdaptivePolicySolution]
        ] = {}
        rule_catalog: Dict[Tuple[object, ...], AdaptiveDecisionRule] = {}

        def consume_branches(count: int) -> None:
            nonlocal explored
            explored += count
            if explored > scenario.bounds.maximum_branches:
                raise ProcessFuelError(
                    "maximum_branches exhausted while solving exact adaptive policy: "
                    f"{explored}/{scenario.bounds.maximum_branches}",
                    analysis.location,
                )

        def solve_checkpoint(
            checkpoint: DeterministicProcessExecutor,
            measure_state,
        ) -> Optional[_AdaptivePolicySolution]:
            result = checkpoint.result()
            required_signatures = tuple(
                item
                for item in measure_state.signatures
                if item[0] in required_signature_ids
            )
            signature: Tuple[object, ...] = (
                checkpoint.policy_state_signature(),
                required_signatures,
            )
            if preserve_paths:
                signature += (result.observation_samples,)
            if signature in memo:
                return memo[signature]
            if checkpoint.is_complete:
                measures = evaluate_process_measures_from_state(
                    scenario, result, measure_state, registry
                )
                if not all(
                    _conditions_hold(
                        objective.path_constraints,
                        dict(measures),
                        registry,
                    )
                ):
                    memo[signature] = None
                    return None
                terminal_values = _objective_values(
                    objective, dict(measures)
                )
                solution = _AdaptivePolicySolution(
                    tuple(
                        Fraction(0)
                        if term.measure_id in additive_term_ids
                        else value
                        for term, value in zip(
                            objective.terms, terminal_values
                        )
                    )
                )
                memo[signature] = solution
                return solution

            first_branch_index = checkpoint.branch_decision_count
            first_decision_index = checkpoint.decision_count
            parent_signatures = dict(measure_state.signatures)

            def lift_from_child(
                child: Optional[_AdaptivePolicySolution], child_state
            ) -> Optional[_AdaptivePolicySolution]:
                if child is None:
                    return None
                child_signatures = dict(child_state.signatures)
                return _AdaptivePolicySolution(
                    tuple(
                        value
                        + child_signatures[term.measure_id][1]
                        - parent_signatures[term.measure_id][1]
                        if term.measure_id in additive_term_ids
                        else value
                        for term, value in zip(
                            objective.terms, child.objective_values
                        )
                    )
                )

            def solve_batch(
                branch_prefix: Tuple[int, ...] = (),
                decision_prefix: Tuple[str, ...] = (),
            ) -> Optional[_AdaptivePolicySolution]:
                trial = checkpoint.clone()

                def choose_branch(
                    index, _event, _branch, probabilities, _environment
                ):
                    local_index = index - first_branch_index
                    if local_index >= len(branch_prefix):
                        possible = tuple(
                            index
                            for index, probability in enumerate(probabilities)
                            if probability
                        )
                        if len(possible) == 1:
                            return possible[0]
                        raise _NeedBranch(probabilities)
                    return branch_prefix[local_index]

                def choose_decision(
                    index, time, schedule, available, values, history
                ):
                    local_index = index - first_decision_index
                    if local_index >= len(decision_prefix):
                        if len(available) == 1:
                            return available[0]
                        raise _NeedDecision(
                            index,
                            time,
                            schedule,
                            available,
                            values,
                            tuple(item for item in history if item[1] != "wait"),
                        )
                    return decision_prefix[local_index]

                trial.branch_selector = choose_branch
                trial.selector = choose_decision
                branch_request = None
                decision_request = None
                try:
                    trial.run_next_batch()
                except _NeedBranch as need:
                    branch_request = need.probabilities
                except _NeedDecision as need:
                    decision_request = (
                        need.index,
                        need.time,
                        need.schedule,
                        need.available,
                        need.observations,
                        need.history,
                    )

                # Recurse only after the control-flow exception has left its
                # handler.  Otherwise every child keeps the complete parent
                # traceback alive until the Bellman subtree returns, which is
                # needlessly expensive for large exact policy trees.
                if branch_request is not None:
                    choices = tuple(
                        (index, probability)
                        for index, probability in enumerate(branch_request)
                        if probability
                    )
                    consume_branches(len(choices))
                    branch_solutions = []
                    for index, probability in choices:
                        child = solve_batch(
                            branch_prefix + (index,), decision_prefix
                        )
                        if child is None:
                            return None
                        branch_solutions.append((probability, child))
                    return _AdaptivePolicySolution(
                        tuple(
                            sum(
                                (
                                    probability
                                    * child.objective_values[index]
                                    for probability, child in branch_solutions
                                ),
                                Fraction(0),
                            )
                            for index in range(len(objective.terms))
                        )
                    )

                if decision_request is not None:
                    (
                        decision_index,
                        decision_time,
                        decision_schedule,
                        decision_available,
                        decision_observations,
                        decision_history,
                    ) = decision_request
                    consume_branches(len(decision_available))
                    candidates = []
                    for action in decision_available:
                        child = solve_batch(
                            branch_prefix, decision_prefix + (action,)
                        )
                        if child is not None:
                            candidates.append((action, child))
                    if not candidates:
                        return None
                    best_key = max(
                        _objective_key(objective, child.objective_values)
                        for _action, child in candidates
                    )
                    tied = tuple(
                        (action, child)
                        for action, child in candidates
                        if _objective_key(
                            objective, child.objective_values
                        ) == best_key
                    )
                    selected_action, representative = tied[0]
                    schedule_kind, schedule_index = (
                        _decision_schedule_identity(
                            scenario, decision_schedule
                        )
                    )
                    current_rule = AdaptiveDecisionRule(
                        decision_index,
                        decision_time,
                        schedule_kind,
                        schedule_index,
                        decision_observations,
                        decision_history,
                        decision_available,
                        tuple(action for action, _child in tied),
                        selected_action,
                    )
                    rule_key = (
                        current_rule.decision_index,
                        current_rule.time,
                        current_rule.schedule_kind,
                        current_rule.schedule_index,
                        current_rule.observations,
                        current_rule.available_actions,
                    )
                    existing_rule = rule_catalog.get(rule_key)
                    if (
                        existing_rule is not None
                        and existing_rule.selected_action
                        != current_rule.selected_action
                    ):
                        raise UnsupportedError(
                            "adaptive policy encountered one public information state "
                            "with incompatible optimal actions; expose the hidden "
                            "state as an observation",
                            analysis.location,
                        )
                    rule_catalog[rule_key] = current_rule
                    return representative

                next_measure_state = advance_process_measure_state(
                    measure_state,
                    scenario,
                    trial.result(),
                    registry,
                )
                return lift_from_child(
                    solve_checkpoint(trial, next_measure_state),
                    next_measure_state,
                )

            solution = solve_batch()
            memo[signature] = solution
            return solution

        initial = DeterministicProcessExecutor(
            scenario,
            registry,
            input_overrides=input_overrides,
            include_trace=include_trace,
        )
        initial.start()
        initial_measure_state = initialize_process_measure_state(
            scenario,
            initial.result(),
            registry,
            tracked_measure_ids,
        )
        required_signature_ids.update(
            name
            for name, _signature in process_measure_state_signature(
                scenario,
                initial.result(),
                registry,
                required_measure_ids,
            )
        )
        solution = solve_checkpoint(initial, initial_measure_state)
        if solution is None:
            optimized.append(
                ObjectiveOptimizationResult(
                    objective_id,
                    (),
                    SolverProof(
                        "exact_global",
                        "exact_observable_state_policy_dynamic_programming",
                        search_budget=scenario.bounds.maximum_branches,
                    ),
                )
            )
            total_explored += max(explored, 1)
            continue

        public_rule_lookup = dict(rule_catalog)
        memo.clear()
        rule_catalog.clear()
        reached_rule_keys = set()

        def select_adaptive(
            index, time, schedule, available, values, history
        ) -> str:
            if len(available) == 1:
                return available[0]
            schedule_kind, schedule_index = _decision_schedule_identity(
                scenario, schedule
            )
            key = (
                index,
                time,
                schedule_kind,
                schedule_index,
                tuple(sorted(values.items())),
                available,
            )
            try:
                rule = public_rule_lookup[key]
            except KeyError as error:
                raise ProcessExecutionError(
                    "exact adaptive policy omitted a reachable public information state",
                    analysis.location,
                ) from error
            reached_rule_keys.add(key)
            return rule.selected_action

        outcomes, distribution_explored = _run_distribution(
            scenario,
            registry,
            policy=None,
            include_trace=include_trace,
            input_overrides=input_overrides,
            aggregate_equivalent_states=not preserve_paths,
            decision_selector_override=select_adaptive,
        )
        expected_measures = _measure_expectations(scenario, outcomes)
        objective_values = _objective_values(
            objective, dict(expected_measures)
        )
        if objective_values != solution.objective_values:
            raise ProcessExecutionError(
                "adaptive policy replay disagrees with its exact Bellman value",
                analysis.location,
            )
        constraints = (True,) * len(objective.path_constraints)
        reached_rules = tuple(
            sorted(
                (public_rule_lookup[key] for key in reached_rule_keys),
                key=lambda item: (
                    item.time,
                    item.decision_index,
                    repr(item.observations),
                ),
            )
        )
        optimized.append(
            ObjectiveOptimizationResult(
                objective_id,
                (
                    OptimalStrategyResult(
                        None,
                        expected_measures,
                        objective_values,
                        constraints,
                        outcomes,
                        policy_rules=reached_rules,
                    ),
                ),
                SolverProof(
                    "exact_global",
                    "exact_observable_state_policy_dynamic_programming",
                    search_budget=scenario.bounds.maximum_branches,
                ),
            )
        )
        total_explored += max(explored, 1) + distribution_explored

    return tuple(optimized), total_explored, ()


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
    *,
    allow_same_time: bool = True,
):
    yield ()
    choose_times = combinations_with_replacement if allow_same_time else combinations
    for count in range(1, schedule.maximum_occurrences + 1):
        for selected_times in choose_times(times, count):
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
    *,
    allow_same_time: bool = True,
):
    if index == len(schedules):
        yield tuple(
            sorted(
                prefix,
                key=lambda item: (
                    item.time,
                    schedules[item.schedule_index].phase.index,
                    item.schedule_index,
                ),
            )
        )
        return
    for local in _schedule_candidate_plans(
        index,
        schedules[index],
        points[index],
        allow_same_time=allow_same_time,
    ):
        yield from _combined_continuous_plans(
            schedules,
            points,
            index + 1,
            prefix + local,
            allow_same_time=allow_same_time,
        )


def _validate_continuous_plan_search(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
) -> bool:
    choice_sources = (
        *scenario.decisions,
        *scenario.event_decisions,
        *scenario.condition_decisions,
    )
    stochastic = _has_random(scenario)
    if stochastic and choice_sources:
        raise UnsupportedError(
            "random continuous-plan optimization cannot yet mix in fixed, event, "
            "or condition decision declarations",
            analysis.location,
        )
    if any(
        len(schedule.action_ids) + int(getattr(schedule, "allow_wait", False)) > 1
        for schedule in choice_sources
    ):
        raise UnsupportedError(
            "continuous-time optimization cannot yet mix free times with another "
            "branching decision source",
            analysis.location,
        )
    return stochastic


def _evaluate_continuous_plan(
    scenario: ScenarioIR,
    registry: UnitRegistry,
    input_overrides: Mapping[Tuple[str, str], ProcessValue],
    include_trace: bool,
    plan: Tuple[ContinuousDecisionChoice, ...],
    stochastic: bool,
    aggregate_equivalent_states: bool,
) -> _PlanEvaluationAttempt:
    decisions = tuple((item.time, item.action_id) for item in plan)
    try:
        if stochastic:
            outcomes, _random_explored = _run_distribution(
                scenario,
                registry,
                policy=None,
                include_trace=include_trace,
                input_overrides=input_overrides,
                continuous_choices=plan,
                aggregate_equivalent_states=aggregate_equivalent_states,
            )
            return _PlanEvaluationAttempt(
                _PlanEvaluation(
                    decisions,
                    _measure_expectations(scenario, outcomes),
                    outcomes=outcomes,
                )
            )
        run = run_process_scenario(
            scenario,
            registry,
            include_trace=include_trace,
            continuous_choices=plan,
            input_overrides=input_overrides,
        )
        return _PlanEvaluationAttempt(
            _PlanEvaluation(
                run.decisions,
                evaluate_process_measures(scenario, run, registry),
                run=run,
            )
        )
    except InfeasibleDecisionError as error:
        index = error.plan_choice_index
        prefix = (
            plan[: index + 1]
            if index is not None and 0 <= index < len(plan)
            else None
        )
        return _PlanEvaluationAttempt(None, prefix)


def _has_infeasible_prefix(
    plan: Tuple[ContinuousDecisionChoice, ...],
    infeasible_prefixes: set[Tuple[ContinuousDecisionChoice, ...]],
) -> bool:
    """Return whether an exact earlier failure proves this plan infeasible."""

    return any(
        plan[:prefix_length] in infeasible_prefixes
        for prefix_length in range(1, len(plan) + 1)
    )


def _finish_continuous_plan_search(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    evaluations: Sequence[_PlanEvaluation],
    proof: SolverProof,
    stochastic: bool,
    evaluated: int,
) -> Tuple[
    Tuple[ObjectiveOptimizationResult, ...],
    int,
    Tuple[SearchCandidateResult, ...],
]:
    if stochastic:
        objectives = _select_stochastic_objectives(
            analysis,
            scenario,
            registry,
            tuple(
                (item.measures, item.decisions, item.outcomes)
                for item in evaluations
            ),
            proof,
        )
    else:
        deterministic = []
        for item in evaluations:
            assert item.run is not None
            deterministic.append((item.measures, item.run))
        objectives = _select_objectives(
            analysis,
            scenario,
            registry,
            tuple(deterministic),
            proof,
        )
    return (
        objectives,
        max(evaluated, 1),
        tuple(
            SearchCandidateResult(item.decisions, item.measures)
            for item in evaluations
        ),
    )


def _exact_grid_times(
    schedule: ContinuousDecisionIR,
    time_grid: Fraction,
    maximum_points: int,
) -> Tuple[Fraction, ...]:
    start_ratio = schedule.start / time_grid
    end_ratio = schedule.end / time_grid
    first_index = (
        start_ratio.numerator + start_ratio.denominator - 1
    ) // start_ratio.denominator
    last_index = end_ratio.numerator // end_ratio.denominator
    if first_index > last_index:
        return ()
    point_count = last_index - first_index + 1
    if point_count > maximum_points:
        raise ProcessFuelError(
            "exact_grid point count exceeds maximum_evaluations before candidate "
            f"enumeration: {point_count}/{maximum_points}",
            schedule.location,
        )
    return tuple(
        Fraction(index) * time_grid
        for index in range(first_index, last_index + 1)
    )


def _optimize_exact_grid(
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
    assert analysis.time_grid is not None
    assert analysis.maximum_evaluations is not None
    stochastic = _validate_continuous_plan_search(analysis, scenario)
    points = tuple(
        _exact_grid_times(
            schedule,
            analysis.time_grid,
            analysis.maximum_evaluations,
        )
        for schedule in scenario.continuous_decisions
    )
    evaluations = []
    candidate_plans = 0
    executed_plans = 0
    pruned_plans = 0
    infeasible_prefixes: set[Tuple[ContinuousDecisionChoice, ...]] = set()
    aggregate_equivalent_states = stochastic and not any(
        chart.kind == "trajectory" for chart in analysis.charts
    )
    for plan in _combined_continuous_plans(
        scenario.continuous_decisions,
        points,
        allow_same_time=False,
    ):
        if candidate_plans >= analysis.maximum_evaluations:
            raise ProcessFuelError(
                "maximum_evaluations exhausted before exact_grid enumerated all "
                f"candidate plans: {candidate_plans}/{analysis.maximum_evaluations}",
                analysis.location,
            )
        candidate_plans += 1
        if _has_infeasible_prefix(plan, infeasible_prefixes):
            pruned_plans += 1
            continue
        executed_plans += 1
        attempt = _evaluate_continuous_plan(
            scenario,
            registry,
            input_overrides,
            include_trace,
            plan,
            stochastic,
            aggregate_equivalent_states,
        )
        if attempt.infeasible_prefix is not None:
            infeasible_prefixes.add(attempt.infeasible_prefix)
        if attempt.evaluation is not None:
            evaluations.append(attempt.evaluation)
    method = "exhaustive_time_grid_plans"
    if stochastic:
        method += "_with_exact_finite_outcomes"
    return _finish_continuous_plan_search(
        analysis,
        scenario,
        registry,
        evaluations,
        SolverProof(
            "exact_global",
            method,
            time_grid=analysis.time_grid,
            search_budget=analysis.maximum_evaluations,
            candidate_plans=candidate_plans,
            executed_plans=executed_plans,
            pruned_plans=pruned_plans,
        ),
        stochastic,
        candidate_plans,
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
    if analysis.search_method == "exact_grid":
        return _optimize_exact_grid(
            analysis,
            scenario,
            registry,
            input_overrides,
            include_trace,
        )
    if analysis.search_method != "adaptive_dyadic":
        raise UnsupportedError(
            "continuous-time optimization requires adaptive_dyadic or exact_grid "
            "search settings",
            analysis.location,
        )
    assert analysis.time_tolerance is not None
    assert analysis.maximum_evaluations is not None
    stochastic = _validate_continuous_plan_search(analysis, scenario)
    semantic_times = _scheduled_times(scenario)
    seen = set()
    evaluations = []
    candidate_plans = 0
    executed_plans = 0
    pruned_plans = 0
    infeasible_prefixes: set[Tuple[ContinuousDecisionChoice, ...]] = set()
    aggregate_equivalent_states = stochastic and not any(
        chart.kind == "trajectory" for chart in analysis.charts
    )
    depth = 0
    budget_exhausted = False
    while candidate_plans < analysis.maximum_evaluations:
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
            if candidate_plans >= analysis.maximum_evaluations:
                budget_exhausted = True
                break
            candidate_plans += 1
            if _has_infeasible_prefix(plan, infeasible_prefixes):
                pruned_plans += 1
                continue
            executed_plans += 1
            attempt = _evaluate_continuous_plan(
                scenario,
                registry,
                input_overrides,
                include_trace,
                plan,
                stochastic,
                aggregate_equivalent_states,
            )
            if attempt.infeasible_prefix is not None:
                infeasible_prefixes.add(attempt.infeasible_prefix)
            if attempt.evaluation is not None:
                evaluations.append(attempt.evaluation)
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
    if candidate_plans >= analysis.maximum_evaluations:
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
    if stochastic:
        method += "_with_exact_finite_outcomes"
    proof = SolverProof(
        level,
        method,
        tolerance=analysis.time_tolerance,
        search_budget=analysis.maximum_evaluations,
        budget_exhausted=budget_exhausted,
        candidate_plans=candidate_plans,
        executed_plans=executed_plans,
        pruned_plans=pruned_plans,
    )
    return _finish_continuous_plan_search(
        analysis,
        scenario,
        registry,
        evaluations,
        proof,
        stochastic,
        candidate_plans,
    )


def _optimize(
    analysis: AnalysisIR,
    scenario: ScenarioIR,
    registry: UnitRegistry,
    include_trace: bool,
) -> OptimizeAnalysisResult:
    stochastic = _has_random(scenario)
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
        elif stochastic:
            objectives, explored, candidates = _optimize_stochastic_policy(
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
                aggregate_equivalent_states=not any(
                    chart.kind == "trajectory" for chart in analysis.charts
                ),
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
            aggregate_equivalent_states=not any(
                chart.kind == "trajectory" for chart in analysis.charts
            ),
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
            aggregate_equivalent_states=not any(
                chart.kind == "trajectory" for chart in analysis.charts
            ),
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


def _weighted_outcome_data(item: WeightedProcessRun) -> dict:
    return {
        "probability": _value_data(item.probability),
        "source_path_count": item.path_count,
        "measures": {
            name: _value_data(value)
            for name, value in item.measures
        },
        "run": _run_data(item.result),
    }


def _adaptive_rule_data(item: AdaptiveDecisionRule) -> dict:
    return {
        "decision_index": item.decision_index,
        "time": _value_data(item.time),
        "schedule": {
            "kind": item.schedule_kind,
            "index": item.schedule_index,
        },
        "observations": {
            name: _value_data(value) for name, value in item.observations
        },
        "history": [
            {"time": _value_data(time), "choice": choice}
            for time, choice in item.history
        ],
        "available_actions": list(item.available_actions),
        "optimal_actions": list(item.optimal_actions),
        "selected_action": item.selected_action,
    }


def _adaptive_policy_summary_data(
    rules: Sequence[AdaptiveDecisionRule],
) -> list[dict]:
    grouped: Dict[Fraction, List[AdaptiveDecisionRule]] = {}
    for rule in rules:
        grouped.setdefault(rule.time, []).append(rule)
    rows = []
    for time, time_rules in sorted(grouped.items()):
        action_ids = tuple(
            dict.fromkeys(rule.selected_action for rule in time_rules)
        )
        actions = []
        for action_id in action_ids:
            selected = tuple(
                rule
                for rule in time_rules
                if rule.selected_action == action_id
            )
            observation_names = tuple(
                sorted(
                    {
                        name
                        for rule in selected
                        for name, value in rule.observations
                        if isinstance(value, (Fraction, bool))
                        and name
                        not in {
                            "elapsed",
                            "event_count",
                            "decision_count",
                            "horizon",
                        }
                    }
                )
            )
            ranges = {}
            for name in observation_names:
                values = tuple(
                    dict(rule.observations)[name] for rule in selected
                )
                if all(isinstance(value, bool) for value in values):
                    ranges[name] = {
                        "values": sorted(set(values)),
                    }
                else:
                    ranges[name] = {
                        "minimum": _value_data(min(values)),
                        "maximum": _value_data(max(values)),
                    }
            actions.append(
                {
                    "action": action_id,
                    "reachable_states": len(selected),
                    "observation_ranges": ranges,
                }
            )
        rows.append(
            {
                "time": _value_data(time),
                "reachable_states": len(time_rules),
                "actions": actions,
            }
        )
    return rows


def _outcome_set_data(
    outcomes: Sequence[WeightedProcessRun],
) -> dict:
    """Project exact outcome states without calling them raw random paths."""

    source_path_count = sum(item.path_count for item in outcomes)
    outcome_state_count = len(outcomes)
    return {
        "outcomes": [_weighted_outcome_data(item) for item in outcomes],
        "source_path_count": source_path_count,
        "outcome_state_count": outcome_state_count,
        "equivalent_states_merged": source_path_count - outcome_state_count,
    }


def _optimal_strategy_data(optimum: OptimalStrategyResult) -> dict:
    data = {
        "objective_values": [
            _value_data(value) for value in optimum.objective_values
        ],
        "constraints": list(optimum.constraints),
        "measures": {
            name: _value_data(value) for name, value in optimum.measures
        },
        "chance_probabilities": [
            _value_data(value) for value in optimum.chance_probabilities
        ],
    }
    if optimum.run is not None:
        data["run"] = _run_data(optimum.run)
    else:
        data["decisions"] = [
            {"time": _value_data(time), "choice": choice}
            for time, choice in optimum.decisions
        ]
        data.update(_outcome_set_data(optimum.outcomes))
        data["measure_semantics"] = "exact_expectations"
        if optimum.policy_rules:
            data["policy_semantics"] = "exact_observable_state"
            data["policy_rules"] = [
                _adaptive_rule_data(rule) for rule in optimum.policy_rules
            ]
            data["policy_summary"] = _adaptive_policy_summary_data(
                optimum.policy_rules
            )
            data["representative_policy"] = (
                "selected_action chooses one exact representative when "
                "optimal_actions contains ties"
            )
    return data


def process_analysis_result_data(
    result: ProcessAnalysisResult,
    analysis: AnalysisIR,
    scenario: ScenarioIR,
) -> dict:
    """Convert exact result objects to the stable JSON/record projection."""

    objective_declarations = {item.id: item for item in scenario.objectives}
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
        "state_aggregation": (
            "disabled_for_trajectory_charts"
            if _has_random(scenario)
            and any(chart.kind == "trajectory" for chart in analysis.charts)
            else "exact_measure_aware"
            if _has_random(scenario)
            else "not_applicable"
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
            "time_grid": _value_data(analysis.time_grid),
            "maximum_evaluations": analysis.maximum_evaluations,
        }
    if isinstance(result, RunAnalysisResult):
        base.update(
            {
                "explored_branches": result.explored_branches,
                **_outcome_set_data(result.outcomes),
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
                **_outcome_set_data(item.result.outcomes),
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
                                "constraint_scopes": [
                                    *(
                                        [
                                            "expected"
                                            if _has_random(scenario)
                                            else "single_run"
                                        ]
                                        * len(
                                            objective_declarations[
                                                item.objective_id
                                            ].constraints
                                        )
                                    ),
                                    *(
                                        ["all_paths"]
                                        * len(
                                            objective_declarations[
                                                item.objective_id
                                            ].path_constraints
                                        )
                                    ),
                                    *(
                                        ["probability"]
                                        * len(
                                            objective_declarations[
                                                item.objective_id
                                            ].chance_constraints
                                        )
                                    ),
                                ],
                                "chance_constraints": [
                                    {
                                        "comparison": constraint.comparison,
                                        "threshold": _value_data(
                                            constraint.threshold
                                        ),
                                    }
                                    for constraint in objective_declarations[
                                        item.objective_id
                                    ].chance_constraints
                                ],
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
                                    "candidate_plans": item.proof.candidate_plans,
                                    "executed_plans": item.proof.executed_plans,
                                    "pruned_plans": item.proof.pruned_plans,
                                },
                                "tied_optima": len(item.optima),
                                "optimal_strategies": [
                                    _optimal_strategy_data(optimum)
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
                **_outcome_set_data(result.outcomes),
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
