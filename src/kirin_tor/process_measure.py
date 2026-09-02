"""Typed exact trajectory Measure evaluation for bounded Process runs."""

from __future__ import annotations

from fractions import Fraction
from typing import Dict, Tuple

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
