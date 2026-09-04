"""Typed exact trajectory Measure evaluation for bounded Process runs."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Optional, Sequence, Tuple

from .errors import ProcessExecutionError, UnsupportedError
from .process_expression import (
    ProcessValue,
    evaluate_process_expression,
    validate_process_value,
)
from .process_model import ExpressionSymbolKind
from .scenario_ir import (
    DerivedMeasureExpressionIR,
    MeasureIR,
    ScenarioIR,
    TrajectoryMeasureExpressionIR,
)
from .process_runtime import ProcessObservationSample, ProcessRunResult
from .units import UnitRegistry


def _sample_environment(
    scenario: ScenarioIR, sample: ProcessObservationSample
) -> Dict[object, ProcessValue]:
    values = dict(sample.values)
    return {
        symbol: values[symbol.id]
        for symbol in scenario.observation_symbols
        if symbol.id in values
    }


def _trajectory_value(
    measure: MeasureIR,
    expression: TrajectoryMeasureExpressionIR,
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
) -> ProcessValue:
    operation = expression.operation
    samples = result.observation_samples
    if not samples:
        raise ProcessExecutionError("Process run contains no observation samples")
    if operation in {
        "minimum_over_time",
        "minimum_where",
        "maximum_over_time",
        "maximum_drawdown",
        "total_variation",
        "variance_over_time",
        "duration_where",
        "first_time",
        "last_before",
    } and any(instance.process.flows for instance in scenario.instances):
        raise UnsupportedError(
            f"{operation} cannot claim an exact result for an unrestricted continuous flow",
            measure.location,
        )
    if operation == "stop_time":
        return result.elapsed
    if operation in {"sum_events", "count_events"}:
        assert expression.event is not None
        selected = tuple(
            event
            for event in result.output_events
            if event.instance_id == expression.event.instance_id
            and event.event_id == expression.event.member.member_id
        )
        if operation == "count_events":
            return Fraction(len(selected))
        assert expression.parameter_id is not None
        return sum(
            (
                dict(event.arguments)[expression.parameter_id]
                for event in selected
            ),
            Fraction(0),
        )
    assert expression.value is not None
    evaluated = tuple(
        evaluate_process_expression(
            expression.value,
            _sample_environment(scenario, sample),
            registry,
        )
        for sample in samples
    )
    if operation == "final":
        return evaluated[-1]
    if operation == "minimum_over_time":
        return min(evaluated)
    if operation == "minimum_where":
        assert expression.condition is not None
        conditions = tuple(
            evaluate_process_expression(
                expression.condition,
                _sample_environment(scenario, sample),
                registry,
            )
            for sample in samples
        )
        selected = tuple(
            value
            for value, condition in zip(evaluated, conditions)
            if condition is True
        )
        if selected:
            return min(selected)
        assert expression.default is not None
        return evaluate_process_expression(
            expression.default,
            _sample_environment(scenario, samples[-1]),
            registry,
        )
    if operation == "maximum_over_time":
        return max(evaluated)
    if operation == "maximum_drawdown":
        peak = evaluated[0]
        drawdown = Fraction(0)
        for value in evaluated[1:]:
            peak = max(peak, value)
            drawdown = max(drawdown, peak - value)
        return drawdown
    if operation == "total_variation":
        return sum(
            (
                abs(right - left)
                for left, right in zip(evaluated, evaluated[1:])
            ),
            Fraction(0),
        )
    if operation == "variance_over_time":
        duration = samples[-1].time - samples[0].time
        if duration == 0:
            return Fraction(0)
        weighted_total = sum(
            (
                evaluated[index] * (samples[index + 1].time - sample.time)
                for index, sample in enumerate(samples[:-1])
            ),
            Fraction(0),
        )
        mean = weighted_total / duration
        return sum(
            (
                (evaluated[index] - mean) ** 2
                * (samples[index + 1].time - sample.time)
                for index, sample in enumerate(samples[:-1])
            ),
            Fraction(0),
        ) / duration
    if operation == "duration_where":
        total = Fraction(0)
        for index, sample in enumerate(samples[:-1]):
            if evaluated[index] is True:
                total += samples[index + 1].time - sample.time
        return total
    if operation == "first_time":
        for sample, value in zip(samples, evaluated):
            if value is True:
                return sample.time
        assert expression.default is not None
        return evaluate_process_expression(
            expression.default,
            _sample_environment(scenario, samples[-1]),
            registry,
        )
    if operation == "last_before":
        assert expression.condition is not None
        for index, sample in enumerate(samples):
            condition = evaluate_process_expression(
                expression.condition,
                _sample_environment(scenario, sample),
                registry,
            )
            if condition is True:
                if index > 0:
                    return evaluated[index - 1]
                break
        assert expression.default is not None
        return evaluate_process_expression(
            expression.default,
            _sample_environment(scenario, samples[-1]),
            registry,
        )
    raise ProcessExecutionError(f"unknown trajectory Measure operation {operation!r}")


def _trajectory_state_signature(
    measure: MeasureIR,
    expression: TrajectoryMeasureExpressionIR,
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
) -> Tuple[object, ...]:
    """Return the exact history state sufficient to continue one Measure.

    This is deliberately richer than the Measure's current value.  For
    example, future maximum drawdown depends on both the running peak and the
    drawdown so far, while future variance depends on its two time integrals.
    """

    operation = expression.operation
    samples = result.observation_samples
    if not samples:
        raise ProcessExecutionError("Process run contains no observation samples")
    if operation in {
        "minimum_over_time",
        "minimum_where",
        "maximum_over_time",
        "maximum_drawdown",
        "total_variation",
        "variance_over_time",
        "duration_where",
        "first_time",
        "last_before",
    } and any(instance.process.flows for instance in scenario.instances):
        raise UnsupportedError(
            f"{operation} cannot claim an exact result for an unrestricted continuous flow",
            measure.location,
        )
    if operation == "stop_time":
        return (operation, result.elapsed)
    if operation in {"sum_events", "count_events"}:
        assert expression.event is not None
        selected = tuple(
            event
            for event in result.output_events
            if event.instance_id == expression.event.instance_id
            and event.event_id == expression.event.member.member_id
        )
        if operation == "count_events":
            return (operation, len(selected))
        assert expression.parameter_id is not None
        return (
            operation,
            sum(
                (
                    dict(event.arguments)[expression.parameter_id]
                    for event in selected
                ),
                Fraction(0),
            ),
        )
    assert expression.value is not None
    if operation == "final":
        return (
            operation,
            evaluate_process_expression(
                expression.value,
                _sample_environment(scenario, samples[-1]),
                registry,
            ),
        )
    environments = tuple(
        _sample_environment(scenario, sample) for sample in samples
    )
    evaluated = tuple(
        evaluate_process_expression(expression.value, environment, registry)
        for environment in environments
    )
    if operation == "minimum_over_time":
        return (operation, min(evaluated))
    if operation == "maximum_over_time":
        return (operation, max(evaluated))
    if operation == "minimum_where":
        assert expression.condition is not None
        selected = tuple(
            value
            for value, environment in zip(evaluated, environments)
            if evaluate_process_expression(
                expression.condition, environment, registry
            )
            is True
        )
        return (operation, min(selected) if selected else None)
    if operation == "maximum_drawdown":
        peak = evaluated[0]
        drawdown = Fraction(0)
        for value in evaluated[1:]:
            peak = max(peak, value)
            drawdown = max(drawdown, peak - value)
        return (operation, peak, drawdown)
    if operation == "total_variation":
        total = sum(
            (
                abs(right - left)
                for left, right in zip(evaluated, evaluated[1:])
            ),
            Fraction(0),
        )
        return (operation, evaluated[-1], total)
    if operation == "variance_over_time":
        weighted_total = sum(
            (
                evaluated[index] * (samples[index + 1].time - sample.time)
                for index, sample in enumerate(samples[:-1])
            ),
            Fraction(0),
        )
        weighted_squares = sum(
            (
                evaluated[index] ** 2
                * (samples[index + 1].time - sample.time)
                for index, sample in enumerate(samples[:-1])
            ),
            Fraction(0),
        )
        return (
            operation,
            samples[0].time,
            samples[-1].time,
            evaluated[-1],
            weighted_total,
            weighted_squares,
        )
    if operation == "duration_where":
        total = sum(
            (
                samples[index + 1].time - sample.time
                for index, sample in enumerate(samples[:-1])
                if evaluated[index] is True
            ),
            Fraction(0),
        )
        return (operation, evaluated[-1], total)
    if operation == "first_time":
        first = next(
            (
                sample.time
                for sample, value in zip(samples, evaluated)
                if value is True
            ),
            None,
        )
        return (operation, first)
    if operation == "last_before":
        assert expression.condition is not None
        for index, environment in enumerate(environments):
            if evaluate_process_expression(
                expression.condition, environment, registry
            ) is not True:
                continue
            return (
                operation,
                "fixed" if index > 0 else "default_at_end",
                evaluated[index - 1] if index > 0 else None,
            )
        return (operation, "pending", evaluated[-1])
    raise ProcessExecutionError(f"unknown trajectory Measure operation {operation!r}")


def process_measure_state_signature(
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
    measure_ids: Optional[Sequence[str]] = None,
) -> Tuple[Tuple[str, Tuple[object, ...]], ...]:
    """Return exact sufficient history state for all trajectory Measures.

    Equal signatures are necessary before two runtime continuations may be
    merged without changing any declared Measure.  Runtime continuation state
    must still be equal as a separate condition.
    """

    selected = _selected_trajectory_measures(scenario, measure_ids)
    return tuple(
        (
            measure.id,
            _trajectory_state_signature(
                measure,
                measure.expression,
                scenario,
                result,
                registry,
            ),
        )
        for measure in selected
    )


def _selected_trajectory_measures(
    scenario: ScenarioIR,
    measure_ids: Optional[Sequence[str]],
) -> Tuple[MeasureIR, ...]:
    if measure_ids is None:
        return tuple(
            measure
            for measure in scenario.measures
            if isinstance(
                measure.expression, TrajectoryMeasureExpressionIR
            )
        )
    declarations = {measure.id: measure for measure in scenario.measures}
    required = set()

    def visit(measure_id: str) -> None:
        if measure_id in required:
            return
        required.add(measure_id)
        expression = declarations[measure_id].expression
        if not isinstance(expression, DerivedMeasureExpressionIR):
            return
        for reference in expression.value.references:
            if reference.kind is ExpressionSymbolKind.MEASURE:
                visit(reference.id)

    for measure_id in measure_ids:
        visit(measure_id)
    return tuple(
        measure
        for measure in scenario.measures
        if measure.id in required
        and isinstance(measure.expression, TrajectoryMeasureExpressionIR)
    )


@dataclass(frozen=True)
class ProcessMeasureState:
    """Incremental sufficient history for a selected Measure dependency set."""

    measure_ids: Tuple[str, ...]
    sample_count: int
    output_event_count: int
    last_sample_time: Fraction
    signatures: Tuple[Tuple[str, Tuple[object, ...]], ...]


def initialize_process_measure_state(
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
    measure_ids: Sequence[str],
) -> ProcessMeasureState:
    if not result.observation_samples:
        raise ProcessExecutionError("Process run contains no observation samples")
    return ProcessMeasureState(
        tuple(measure_ids),
        len(result.observation_samples),
        len(result.output_events),
        result.observation_samples[-1].time,
        process_measure_state_signature(
            scenario, result, registry, measure_ids
        ),
    )


def advance_process_measure_state(
    state: ProcessMeasureState,
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
) -> ProcessMeasureState:
    """Advance sufficient Measure history using only newly appended records."""

    samples = result.observation_samples[state.sample_count :]
    events = result.output_events[state.output_event_count :]
    signatures = dict(state.signatures)
    declarations = {
        measure.id: measure
        for measure in _selected_trajectory_measures(
            scenario, state.measure_ids
        )
    }

    for measure_id, measure in declarations.items():
        expression = measure.expression
        assert isinstance(expression, TrajectoryMeasureExpressionIR)
        operation = expression.operation
        previous = signatures[measure_id]
        if operation == "stop_time":
            signatures[measure_id] = (operation, result.elapsed)
            continue
        if operation in {"sum_events", "count_events"}:
            assert expression.event is not None
            selected = tuple(
                event
                for event in events
                if event.instance_id == expression.event.instance_id
                and event.event_id == expression.event.member.member_id
            )
            if operation == "count_events":
                signatures[measure_id] = (
                    operation,
                    previous[1] + len(selected),
                )
            else:
                assert expression.parameter_id is not None
                signatures[measure_id] = (
                    operation,
                    previous[1]
                    + sum(
                        (
                            dict(event.arguments)[expression.parameter_id]
                            for event in selected
                        ),
                        Fraction(0),
                    ),
                )
            continue
        if not samples:
            continue
        assert expression.value is not None
        environments = tuple(
            _sample_environment(scenario, sample) for sample in samples
        )
        evaluated = tuple(
            evaluate_process_expression(
                expression.value, environment, registry
            )
            for environment in environments
        )
        if operation == "final":
            signatures[measure_id] = (operation, evaluated[-1])
        elif operation == "minimum_over_time":
            signatures[measure_id] = (
                operation,
                min(previous[1], *evaluated),
            )
        elif operation == "maximum_over_time":
            signatures[measure_id] = (
                operation,
                max(previous[1], *evaluated),
            )
        elif operation == "minimum_where":
            assert expression.condition is not None
            selected_values = tuple(
                value
                for value, environment in zip(evaluated, environments)
                if evaluate_process_expression(
                    expression.condition, environment, registry
                )
                is True
            )
            candidates = (
                (() if previous[1] is None else (previous[1],))
                + selected_values
            )
            signatures[measure_id] = (
                operation,
                min(candidates) if candidates else None,
            )
        elif operation == "maximum_drawdown":
            peak, drawdown = previous[1], previous[2]
            for value in evaluated:
                peak = max(peak, value)
                drawdown = max(drawdown, peak - value)
            signatures[measure_id] = (operation, peak, drawdown)
        elif operation == "total_variation":
            last, total = previous[1], previous[2]
            for value in evaluated:
                total += abs(value - last)
                last = value
            signatures[measure_id] = (operation, last, total)
        elif operation == "variance_over_time":
            start, last_time, last, total, squares = previous[1:]
            for sample, value in zip(samples, evaluated):
                duration = sample.time - last_time
                total += last * duration
                squares += last ** 2 * duration
                last_time = sample.time
                last = value
            signatures[measure_id] = (
                operation,
                start,
                last_time,
                last,
                total,
                squares,
            )
        elif operation == "duration_where":
            last, total = previous[1], previous[2]
            last_time = state.last_sample_time
            for sample, value in zip(samples, evaluated):
                if last is True:
                    total += sample.time - last_time
                last_time = sample.time
                last = value
            signatures[measure_id] = (operation, last, total)
        elif operation == "first_time":
            first = previous[1]
            if first is None:
                first = next(
                    (
                        sample.time
                        for sample, value in zip(samples, evaluated)
                        if value is True
                    ),
                    None,
                )
            signatures[measure_id] = (operation, first)
        elif operation == "last_before":
            if previous[1] in {"fixed", "default_at_end"}:
                continue
            assert previous[1] == "pending"
            assert expression.condition is not None
            prior_value = previous[2]
            fixed = None
            for value, environment in zip(evaluated, environments):
                if evaluate_process_expression(
                    expression.condition, environment, registry
                ) is True:
                    fixed = prior_value
                    break
                prior_value = value
            signatures[measure_id] = (
                (operation, "fixed", fixed)
                if fixed is not None
                else (operation, "pending", evaluated[-1])
            )
        else:
            raise ProcessExecutionError(
                f"unknown trajectory Measure operation {operation!r}"
            )

    last_sample_time = (
        samples[-1].time if samples else state.last_sample_time
    )
    return ProcessMeasureState(
        state.measure_ids,
        len(result.observation_samples),
        len(result.output_events),
        last_sample_time,
        tuple(
            (measure.id, signatures[measure.id])
            for measure in declarations.values()
        ),
    )


def evaluate_process_measures(
    scenario: ScenarioIR,
    result: ProcessRunResult,
    registry: UnitRegistry,
) -> Tuple[Tuple[str, ProcessValue], ...]:
    """Evaluate every source Measure without exposing private Process state."""

    declarations = {measure.id: measure for measure in scenario.measures}
    values: Dict[str, ProcessValue] = {}
    visiting = set()

    def evaluate(measure_id: str) -> ProcessValue:
        if measure_id in values:
            return values[measure_id]
        if measure_id in visiting:
            raise ProcessExecutionError(
                f"cyclic Measure dependency involving {measure_id!r}"
            )
        visiting.add(measure_id)
        measure = declarations[measure_id]
        expression = measure.expression
        if isinstance(expression, TrajectoryMeasureExpressionIR):
            value = _trajectory_value(
                measure, expression, scenario, result, registry
            )
        else:
            assert isinstance(expression, DerivedMeasureExpressionIR)
            environment = {
                reference: evaluate(reference.id)
                for reference in expression.value.references
                if reference.kind is ExpressionSymbolKind.MEASURE
            }
            value = evaluate_process_expression(
                expression.value, environment, registry
            )
        validate_process_value(value, measure.value_type, registry, measure.location)
        visiting.remove(measure_id)
        values[measure_id] = value
        return value

    return tuple((measure.id, evaluate(measure.id)) for measure in scenario.measures)


def evaluate_process_measures_from_state(
    scenario: ScenarioIR,
    result: ProcessRunResult,
    state: ProcessMeasureState,
    registry: UnitRegistry,
) -> Tuple[Tuple[str, ProcessValue], ...]:
    """Evaluate the state's selected Measures and their exact dependencies."""

    signatures = dict(state.signatures)
    declarations = {measure.id: measure for measure in scenario.measures}
    selected_trajectory = _selected_trajectory_measures(
        scenario, state.measure_ids
    )
    missing = [
        measure.id
        for measure in selected_trajectory
        if measure.id not in signatures
    ]
    if missing:
        raise ProcessExecutionError(
            "incremental Measure state is missing: " + ", ".join(missing)
        )
    final_environment = _sample_environment(
        scenario, result.observation_samples[-1]
    )
    values: Dict[str, ProcessValue] = {}
    visiting = set()

    def trajectory_value(measure: MeasureIR) -> ProcessValue:
        expression = measure.expression
        assert isinstance(expression, TrajectoryMeasureExpressionIR)
        signature = signatures[measure.id]
        operation = expression.operation
        if operation in {
            "stop_time",
            "sum_events",
            "final",
            "minimum_over_time",
            "maximum_over_time",
        }:
            return signature[1]
        if operation == "count_events":
            return Fraction(signature[1])
        if operation == "minimum_where":
            if signature[1] is not None:
                return signature[1]
            assert expression.default is not None
            return evaluate_process_expression(
                expression.default, final_environment, registry
            )
        if operation in {
            "maximum_drawdown",
            "total_variation",
            "duration_where",
        }:
            return signature[2]
        if operation == "variance_over_time":
            _name, start, end, _last, total, squares = signature
            duration = end - start
            if duration == 0:
                return Fraction(0)
            mean = total / duration
            return squares / duration - mean ** 2
        if operation == "first_time":
            if signature[1] is not None:
                return signature[1]
            assert expression.default is not None
            return evaluate_process_expression(
                expression.default, final_environment, registry
            )
        if operation == "last_before":
            if signature[1] == "fixed":
                return signature[2]
            assert expression.default is not None
            return evaluate_process_expression(
                expression.default, final_environment, registry
            )
        raise ProcessExecutionError(
            f"unknown trajectory Measure operation {operation!r}"
        )

    def evaluate(measure_id: str) -> ProcessValue:
        if measure_id in values:
            return values[measure_id]
        if measure_id in visiting:
            raise ProcessExecutionError(
                f"cyclic Measure dependency involving {measure_id!r}"
            )
        visiting.add(measure_id)
        measure = declarations[measure_id]
        expression = measure.expression
        if isinstance(expression, TrajectoryMeasureExpressionIR):
            value = trajectory_value(measure)
        else:
            assert isinstance(expression, DerivedMeasureExpressionIR)
            environment = {
                reference: evaluate(reference.id)
                for reference in expression.value.references
                if reference.kind is ExpressionSymbolKind.MEASURE
            }
            value = evaluate_process_expression(
                expression.value, environment, registry
            )
        validate_process_value(
            value, measure.value_type, registry, measure.location
        )
        visiting.remove(measure_id)
        values[measure_id] = value
        return value

    return tuple(
        (measure_id, evaluate(measure_id))
        for measure_id in state.measure_ids
    )
