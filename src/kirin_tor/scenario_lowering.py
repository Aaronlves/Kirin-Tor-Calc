"""Resolve Scenario/Analysis AST against workspace Process declarations."""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Dict, Mapping, Optional, Sequence, Tuple

from .errors import DomainError, ReferenceError, SchemaError
from .limits import (
    MAX_SCENARIO_BRANCHES,
    MAX_SCENARIO_DECISIONS,
    MAX_SCENARIO_EVENTS,
    MAX_SCENARIO_INSTANCES,
)
from .process_ast import ExpressionAst
from .process_expression import compile_process_expression, evaluate_process_expression
from .process_ir import (
    ActionIR,
    BooleanTypeIR,
    EventArgumentIR,
    EventIR,
    NumberTypeIR,
    ProcessIR,
    ProcessMemberRefIR,
    SymbolRefIR,
    TypedExpressionIR,
)
from .process_model import EventDirection, ExpressionSymbolKind
from .process_crossing import supports_exact_affine_crossing
from .process_lowering import ProcessLowerer
from .scenario_ast import AnalysisAst, AtScheduleAst, EveryScheduleAst, ScenarioAst, ScenarioSendAst
from .scenario_ir import (
    AnalysisIR,
    AtScheduleIR,
    CompositeActionIR,
    ConditionDecisionIR,
    ConnectionIR,
    ContinuousDecisionIR,
    DecisionScheduleIR,
    EveryScheduleIR,
    EventDecisionIR,
    DerivedMeasureExpressionIR,
    InstanceInputIR,
    InstanceMemberRefIR,
    InstancePhaseIR,
    MeasureIR,
    ObjectiveIR,
    ObjectiveTermIR,
    PolicyIR,
    PolicyRuleIR,
    ProcessInstanceIR,
    ScenarioBoundsIR,
    ScenarioCallIR,
    ScenarioIR,
    ScenarioPhaseIR,
    TrajectoryMeasureExpressionIR,
)
from .schema import require_identifier
from .scenario_validation import validate_scenario_ir
from .units import DIMENSIONLESS, UnitRegistry


_TRAJECTORY_MEASURE_OPERATIONS = frozenset(
    {
        "final",
        "minimum_over_time",
        "maximum_over_time",
        "maximum_drawdown",
        "total_variation",
        "variance_over_time",
        "sum_events",
        "count_events",
        "duration_where",
        "first_time",
        "stop_time",
    }
)


def _measure_call(source: ExpressionAst) -> Optional[Tuple[str, str]]:
    match = re.fullmatch(r"([a-z_][a-z0-9_]*)\((.*)\)", source.text.strip())
    if match is None or match.group(1) not in _TRAJECTORY_MEASURE_OPERATIONS:
        return None
    return match.group(1), match.group(2).strip()


def scenario_static_symbols(registry: UnitRegistry) -> Dict[str, SymbolRefIR]:
    """Return closed symbolic-domain members available in scenario expressions."""

    from .process_ir import SymbolicTypeIR

    result: Dict[str, SymbolRefIR] = {}
    candidates: Dict[str, list[SymbolRefIR]] = {}
    for domain_id, domain in registry.domains.items():
        if domain.value_type != "symbolic":
            continue
        value_type = SymbolicTypeIR(domain_id)
        for value in domain.allowed_values:
            assert isinstance(value, str)
            reference = SymbolRefIR(
                f"@domain.{domain_id}",
                value,
                ExpressionSymbolKind.STATIC_MEMBER,
                value_type,
            )
            result[f"{domain_id}.{value}"] = reference
            candidates.setdefault(value, []).append(reference)
    for value, references in candidates.items():
        if len(references) == 1:
            result[value] = references[0]
    return result


def _resolve_path(owner_id: str, path: str, values: Mapping[str, object], kind: str):
    candidates = (path, f"{owner_id}.{path}") if "." in path else (f"{owner_id}.{path}", path)
    for candidate in candidates:
        if candidate in values:
            return values[candidate]
    raise ReferenceError(f"unknown {kind} {path!r}")


def _member(instance: ProcessInstanceIR, ref: ProcessMemberRefIR) -> InstanceMemberRefIR:
    return InstanceMemberRefIR(instance.scenario_id, instance.id, ref)


def _compile_constant(
    source: ExpressionAst,
    expected,
    symbols: Mapping[str, SymbolRefIR],
    registry: UnitRegistry,
) -> Tuple[TypedExpressionIR, object]:
    expression = compile_process_expression(source, expected, symbols, registry)
    if any(
        reference.kind not in {ExpressionSymbolKind.UNIT, ExpressionSymbolKind.STATIC_MEMBER}
        for reference in expression.references
    ):
        raise SchemaError(
            "scenario schedule and bound expressions must be constant", source.location
        )
    return expression, evaluate_process_expression(expression, {}, registry)


def _positive_integer(
    source: ExpressionAst,
    name: str,
    symbols: Mapping[str, SymbolRefIR],
    registry: UnitRegistry,
    maximum: int,
) -> int:
    value_type = NumberTypeIR(
        "dimensionless", DIMENSIONLESS, "positive_integer", True
    )
    _expression, value = _compile_constant(source, value_type, symbols, registry)
    assert isinstance(value, Fraction)
    integer = int(value)
    if integer > maximum:
        raise SchemaError(f"{name} exceeds implementation limit {maximum}", source.location)
    return integer


class ScenarioLowerer:
    def __init__(
        self,
        registry: UnitRegistry,
        processes: Mapping[str, ProcessIR],
        *,
        static_symbols: Optional[Mapping[str, SymbolRefIR]] = None,
    ) -> None:
        self.registry = registry
        self.processes = dict(processes)
        self.static_symbols = dict(static_symbols or scenario_static_symbols(registry))
        self.boolean = BooleanTypeIR()
        self.time = NumberTypeIR("second", registry.parse_unit("second"))

    def _process(self, source: ScenarioAst, path: str) -> ProcessIR:
        return _resolve_path(source.owner_id, path, self.processes, "process")

    def _call(
        self,
        source: ScenarioSendAst,
        instances: Mapping[str, ProcessInstanceIR],
        phases: Mapping[str, ScenarioPhaseIR],
        symbols: Mapping[str, SymbolRefIR],
        *,
        allow_action: bool,
    ) -> ScenarioCallIR:
        instance = instances.get(source.instance_id)
        if instance is None:
            raise ReferenceError(
                f"scenario send references unknown instance {source.instance_id!r}",
                source.location,
            )
        process = instance.process
        declarations: Dict[str, object] = {event.ref.member_id: event for event in process.events}
        if allow_action:
            declarations.update({action.ref.member_id: action for action in process.actions})
        declaration = declarations.get(source.call.event_id)
        if declaration is None:
            raise ReferenceError(
                f"instance {instance.id!r} has no sendable member {source.call.event_id!r}",
                source.location,
            )
        if isinstance(declaration, EventIR):
            if declaration.direction is not EventDirection.INPUT:
                raise SchemaError("scenario can send only input events", source.location)
            parameters = declaration.parameters
            target = declaration.ref
        else:
            assert isinstance(declaration, ActionIR)
            parameters = declaration.parameters
            target = declaration.ref
        if source.phase_id is None:
            raise SchemaError("scenario send must have an explicit phase", source.location)
        phase = phases.get(source.phase_id)
        if phase is None:
            raise ReferenceError(f"unknown scenario phase {source.phase_id!r}", source.location)
        provided = {argument.parameter_id: argument for argument in source.call.arguments}
        if len(provided) != len(source.call.arguments):
            raise SchemaError("scenario event has duplicate arguments", source.location)
        expected = {parameter.id for parameter in parameters}
        if set(provided) != expected:
            missing = sorted(expected - set(provided))
            unknown = sorted(set(provided) - expected)
            details = (["missing " + ", ".join(missing)] if missing else []) + (["unknown " + ", ".join(unknown)] if unknown else [])
            raise SchemaError(
                f"scenario event arguments do not match: {'; '.join(details)}",
                source.location,
            )
        arguments = tuple(
            EventArgumentIR(
                parameter.id,
                compile_process_expression(
                    provided[parameter.id].value,
                    parameter.value_type,
                    symbols,
                    self.registry,
                ),
            )
            for parameter in parameters
        )
        return ScenarioCallIR(
            _member(instance, target), parameters, arguments, phase, source.location
        )

    def _output_event(
        self,
        text: str,
        instances: Mapping[str, ProcessInstanceIR],
        location,
        *,
        with_parameter: bool,
    ) -> Tuple[InstanceMemberRefIR, Optional[EventParameterIR]]:
        pieces = text.strip().split(".")
        expected = 3 if with_parameter else 2
        if len(pieces) != expected or any(not re.fullmatch(r"[a-z][a-z0-9_]*", item) for item in pieces):
            form = "INSTANCE.EVENT.PARAMETER" if with_parameter else "INSTANCE.EVENT"
            raise SchemaError(f"event Measure requires {form}", location)
        instance = instances.get(pieces[0])
        if instance is None:
            raise ReferenceError(
                f"event Measure references unknown instance {pieces[0]!r}", location
            )
        event = next(
            (
                item
                for item in instance.process.events
                if item.ref.member_id == pieces[1]
                and item.direction is EventDirection.OUTPUT
            ),
            None,
        )
        if event is None:
            raise ReferenceError(
                f"event Measure requires public output event {pieces[0]}.{pieces[1]}",
                location,
            )
        parameter = None
        if with_parameter:
            parameter = next(
                (item for item in event.parameters if item.id == pieces[2]), None
            )
            if parameter is None:
                raise ReferenceError(
                    f"output event {pieces[0]}.{pieces[1]} has no parameter {pieces[2]!r}",
                    location,
                )
        return _member(instance, event.ref), parameter

    @staticmethod
    def _decision_actions(options: Sequence[str], actions: Mapping[str, object], location):
        action_ids = tuple(option for option in options if option != "wait")
        unknown = sorted(set(action_ids) - set(actions))
        if unknown:
            raise ReferenceError(
                f"decision references unknown action {unknown[0]!r}", location
            )
        if len(set(options)) != len(options):
            raise SchemaError("decision options must be unique", location)
        return action_ids, "wait" in options

    @staticmethod
    def _require_compatible_type(actual, expected, message: str, location) -> None:
        if isinstance(actual, NumberTypeIR) and isinstance(expected, NumberTypeIR):
            if actual.dimension == expected.dimension and (
                not expected.integer or actual.integer
            ):
                return
        elif actual == expected:
            return
        raise SchemaError(message, location)

    def _lower_measures(
        self,
        source: ScenarioAst,
        instances: Mapping[str, ProcessInstanceIR],
        dynamic_symbols: Mapping[str, SymbolRefIR],
    ) -> Tuple[MeasureIR, ...]:
        type_lowerer = ProcessLowerer(self.registry)
        declared_types = {}
        measure_symbols = {}
        locations = {}
        for item in source.measures:
            require_identifier(item.id, "measure id", item.location)
            if item.id in declared_types:
                raise SchemaError(f"duplicate scenario measure {item.id!r}", item.location)
            value_type = type_lowerer._type(item.value_type)
            declared_types[item.id] = value_type
            locations[item.id] = item.location
            measure_symbols[item.id] = SymbolRefIR(
                source.qualified_id,
                item.id,
                ExpressionSymbolKind.MEASURE,
                value_type,
            )

        result = []
        for item in source.measures:
            declared_type = declared_types[item.id]
            call = _measure_call(item.value)
            if call is None:
                expression = DerivedMeasureExpressionIR(
                    compile_process_expression(
                        item.value,
                        declared_type,
                        {**self.static_symbols, **measure_symbols},
                        self.registry,
                    )
                )
            else:
                operation, argument = call
                if operation in {
                    "final",
                    "minimum_over_time",
                    "maximum_over_time",
                    "maximum_drawdown",
                    "total_variation",
                    "variance_over_time",
                }:
                    if not argument:
                        raise SchemaError(f"{operation} requires one value", item.location)
                    expected_type = (
                        None if operation == "variance_over_time" else declared_type
                    )
                    value = compile_process_expression(
                        ExpressionAst(argument, item.value.location),
                        expected_type,
                        dynamic_symbols,
                        self.registry,
                    )
                    if operation != "final" and not isinstance(
                        value.result_type, NumberTypeIR
                    ):
                        raise SchemaError(
                            f"{operation} requires a numeric value", item.location
                        )
                    if operation == "variance_over_time":
                        assert isinstance(value.result_type, NumberTypeIR)
                        variance_type = NumberTypeIR(
                            value.result_type.dimension.power(Fraction(2)).render(),
                            value.result_type.dimension.power(Fraction(2)),
                        )
                        self._require_compatible_type(
                            variance_type,
                            declared_type,
                            "variance_over_time Measure type must square its value unit",
                            item.location,
                        )
                    expression = TrajectoryMeasureExpressionIR(operation, value=value)
                elif operation == "duration_where":
                    condition = compile_process_expression(
                        ExpressionAst(argument, item.value.location),
                        self.boolean,
                        dynamic_symbols,
                        self.registry,
                    )
                    self._require_compatible_type(
                        self.time,
                        declared_type,
                        "duration_where Measure must have a time type",
                        item.location,
                    )
                    expression = TrajectoryMeasureExpressionIR(
                        operation, value=condition
                    )
                elif operation == "first_time":
                    match = re.fullmatch(
                        r"(?s)(.+),\s*default\s*=\s*(.+)", argument
                    )
                    if match is None:
                        raise SchemaError(
                            "first_time requires an explicit default = TIME",
                            item.location,
                        )
                    condition = compile_process_expression(
                        ExpressionAst(match.group(1).strip(), item.value.location),
                        self.boolean,
                        dynamic_symbols,
                        self.registry,
                    )
                    default = compile_process_expression(
                        ExpressionAst(match.group(2).strip(), item.value.location),
                        self.time,
                        dynamic_symbols,
                        self.registry,
                    )
                    self._require_compatible_type(
                        self.time,
                        declared_type,
                        "first_time Measure must have a time type",
                        item.location,
                    )
                    expression = TrajectoryMeasureExpressionIR(
                        operation, value=condition, default=default
                    )
                elif operation == "stop_time":
                    if argument:
                        raise SchemaError("stop_time does not accept arguments", item.location)
                    self._require_compatible_type(
                        self.time,
                        declared_type,
                        "stop_time Measure must have a time type",
                        item.location,
                    )
                    expression = TrajectoryMeasureExpressionIR(operation)
                elif operation == "count_events":
                    event, _parameter = self._output_event(
                        argument, instances, item.location, with_parameter=False
                    )
                    count_type = NumberTypeIR(
                        "dimensionless", DIMENSIONLESS, "count", True
                    )
                    self._require_compatible_type(
                        count_type,
                        declared_type,
                        "count_events Measure must have an integer count type",
                        item.location,
                    )
                    expression = TrajectoryMeasureExpressionIR(
                        operation, event=event
                    )
                else:
                    assert operation == "sum_events"
                    event, parameter = self._output_event(
                        argument, instances, item.location, with_parameter=True
                    )
                    assert parameter is not None
                    if not isinstance(parameter.value_type, NumberTypeIR):
                        raise SchemaError(
                            "sum_events requires a numeric output-event parameter",
                            item.location,
                        )
                    self._require_compatible_type(
                        parameter.value_type,
                        declared_type,
                        "sum_events Measure type must match its event parameter",
                        item.location,
                    )
                    expression = TrajectoryMeasureExpressionIR(
                        operation,
                        event=event,
                        parameter_id=parameter.id,
                    )
            result.append(
                MeasureIR(
                    source.qualified_id,
                    item.id,
                    declared_type,
                    expression,
                    item.label,
                    item.location,
                )
            )

        dependencies = {
            measure.id: tuple(
                reference.id
                for reference in (
                    measure.expression.value.references
                    if isinstance(measure.expression, DerivedMeasureExpressionIR)
                    else ()
                )
                if reference.kind is ExpressionSymbolKind.MEASURE
            )
            for measure in result
        }
        visiting = set()
        complete = set()

        def visit(measure_id: str) -> None:
            if measure_id in complete:
                return
            if measure_id in visiting:
                raise SchemaError(
                    f"cyclic Measure dependency involving {measure_id!r}",
                    locations[measure_id],
                )
            visiting.add(measure_id)
            for dependency in dependencies[measure_id]:
                visit(dependency)
            visiting.remove(measure_id)
            complete.add(measure_id)

        for measure_id in dependencies:
            visit(measure_id)
        return tuple(result)

    def _lower_objectives(
        self, source: ScenarioAst, measures: Sequence[MeasureIR]
    ) -> Tuple[ObjectiveIR, ...]:
        measure_map = {measure.id: measure for measure in measures}
        symbols = {
            measure.id: SymbolRefIR(
                source.qualified_id,
                measure.id,
                ExpressionSymbolKind.MEASURE,
                measure.value_type,
            )
            for measure in measures
        }
        result = []
        seen = set()
        for item in source.objectives:
            require_identifier(item.id, "objective id", item.location)
            if item.id in seen:
                raise SchemaError(f"duplicate scenario objective {item.id!r}", item.location)
            seen.add(item.id)
            terms = []
            for term in item.terms:
                measure = measure_map.get(term.measure_id)
                if measure is None:
                    raise ReferenceError(
                        f"objective {item.id!r} references unknown Measure {term.measure_id!r}",
                        term.location,
                    )
                if not isinstance(measure.value_type, NumberTypeIR):
                    raise SchemaError(
                        "objective terms must reference numeric Measures", term.location
                    )
                terms.append(ObjectiveTermIR(term.direction, term.measure_id))
            constraints = tuple(
                compile_process_expression(
                    condition,
                    self.boolean,
                    {**self.static_symbols, **symbols},
                    self.registry,
                )
                for condition in item.constraints
            )
            result.append(
                ObjectiveIR(
                    source.qualified_id,
                    item.id,
                    tuple(terms),
                    constraints,
                    item.label,
                    item.location,
                )
            )
        return tuple(result)

    def lower(self, source: ScenarioAst) -> ScenarioIR:
        require_identifier(source.owner_id, "scenario owner id", source.location)
        require_identifier(source.id, "scenario id", source.location)
        scenario_id = source.qualified_id
        phase_ids = [item.id for item in source.phases]
        if len(set(phase_ids)) != len(phase_ids):
            raise SchemaError("scenario phase ids must be unique", source.location)
        phases = {
            item.id: ScenarioPhaseIR(scenario_id, item.id, index)
            for index, item in enumerate(source.phases)
        }
        instances: Dict[str, ProcessInstanceIR] = {}
        for item in source.instances:
            require_identifier(item.id, "scenario instance id", item.location)
            if item.id in instances:
                raise SchemaError(f"duplicate scenario instance {item.id!r}", item.location)
            process = self._process(source, item.process_path)
            input_map = {value.ref.member_id: value for value in process.inputs}
            provided = {binding.input_id: binding for binding in item.inputs}
            if len(provided) != len(item.inputs):
                raise SchemaError(f"instance {item.id!r} has duplicate input bindings", item.location)
            unknown = sorted(set(provided) - set(input_map))
            missing = sorted(
                name
                for name, declaration in input_map.items()
                if name not in provided and declaration.default is None
            )
            if unknown or missing:
                details = (["missing " + ", ".join(missing)] if missing else []) + (["unknown " + ", ".join(unknown)] if unknown else [])
                raise SchemaError(
                    f"instance {item.id!r} input bindings do not match: {'; '.join(details)}",
                    item.location,
                )
            phase_map = {value.ref.member_id: value for value in process.phases}
            provided_phases = {binding.process_phase_id: binding for binding in item.phases}
            if len(provided_phases) != len(item.phases):
                raise SchemaError(f"instance {item.id!r} has duplicate phase bindings", item.location)
            if set(provided_phases) != set(phase_map):
                missing_phases = sorted(set(phase_map) - set(provided_phases))
                unknown_phases = sorted(set(provided_phases) - set(phase_map))
                details = (["missing " + ", ".join(missing_phases)] if missing_phases else []) + (["unknown " + ", ".join(unknown_phases)] if unknown_phases else [])
                raise SchemaError(
                    f"instance {item.id!r} phase bindings do not match: {'; '.join(details)}",
                    item.location,
                )
            placeholder = ProcessInstanceIR(scenario_id, item.id, process, (), (), item.location)
            input_values = tuple(
                InstanceInputIR(
                    _member(placeholder, input_map[name].ref),
                    compile_process_expression(
                        provided[name].value,
                        input_map[name].value_type,
                        self.static_symbols,
                        self.registry,
                    ),
                )
                for name in input_map
                if name in provided
            )
            phase_values = []
            for name, process_phase in phase_map.items():
                scenario_phase_id = provided_phases[name].scenario_phase_id
                scenario_phase = phases.get(scenario_phase_id)
                if scenario_phase is None:
                    raise ReferenceError(
                        f"unknown scenario phase {scenario_phase_id!r}",
                        provided_phases[name].location,
                    )
                phase_values.append(
                    InstancePhaseIR(_member(placeholder, process_phase.ref), scenario_phase)
                )
            instances[item.id] = ProcessInstanceIR(
                scenario_id,
                item.id,
                process,
                input_values,
                tuple(phase_values),
                item.location,
            )
        if len(instances) > MAX_SCENARIO_INSTANCES:
            raise SchemaError(
                f"scenario exceeds {MAX_SCENARIO_INSTANCES} instances", source.location
            )

        observation_symbols: Dict[str, SymbolRefIR] = {}
        for instance in instances.values():
            for observation in instance.process.observations:
                name = f"{instance.id}.{observation.ref.member_id}"
                observation_symbols[name] = SymbolRefIR(
                    scenario_id,
                    name,
                    ExpressionSymbolKind.OBSERVATION,
                    observation.value_type,
                )
        runtime_symbols = {
            "elapsed": SymbolRefIR(
                scenario_id, "elapsed", ExpressionSymbolKind.RUNTIME, self.time
            ),
            "event_count": SymbolRefIR(
                scenario_id,
                "event_count",
                ExpressionSymbolKind.RUNTIME,
                NumberTypeIR("dimensionless", DIMENSIONLESS, "count", True),
            ),
            "decision_count": SymbolRefIR(
                scenario_id,
                "decision_count",
                ExpressionSymbolKind.RUNTIME,
                NumberTypeIR("dimensionless", DIMENSIONLESS, "count", True),
            ),
            "horizon": SymbolRefIR(
                scenario_id, "horizon", ExpressionSymbolKind.RUNTIME, self.time
            ),
        }
        dynamic_symbols = {
            **self.static_symbols,
            **observation_symbols,
            **runtime_symbols,
        }

        connections = []
        for item in source.connections:
            source_instance = instances.get(item.source.instance_id)
            target_instance = instances.get(item.target.instance_id)
            if source_instance is None or target_instance is None:
                raise ReferenceError("connection references an unknown process instance", item.location)
            outputs = {
                event.ref.member_id: event
                for event in source_instance.process.events
                if event.direction is EventDirection.OUTPUT
            }
            inputs = {
                event.ref.member_id: event
                for event in target_instance.process.events
                if event.direction is EventDirection.INPUT
            }
            output = outputs.get(item.source.member_id)
            target = inputs.get(item.target.member_id)
            if output is None or target is None:
                raise ReferenceError("connection must link an output event to an input event", item.location)
            if tuple((p.id, p.value_type) for p in output.parameters) != tuple(
                (p.id, p.value_type) for p in target.parameters
            ):
                raise SchemaError("connected event parameters are not type-compatible", item.location)
            connections.append(
                ConnectionIR(_member(source_instance, output.ref), _member(target_instance, target.ref), item.location)
            )

        actions: Dict[str, CompositeActionIR] = {}
        for item in source.actions:
            if item.id in actions:
                raise SchemaError(f"duplicate scenario action {item.id!r}", item.location)
            actions[item.id] = CompositeActionIR(
                scenario_id,
                item.id,
                compile_process_expression(item.guard, self.boolean, dynamic_symbols, self.registry)
                if item.guard is not None
                else None,
                tuple(
                    self._call(send, instances, phases, dynamic_symbols, allow_action=True)
                    for send in item.sends
                ),
                item.location,
            )

        policies: Dict[str, PolicyIR] = {}
        for item in source.policies:
            if item.id in policies:
                raise SchemaError(f"duplicate scenario policy {item.id!r}", item.location)
            choices = tuple(rule.action_id for rule in item.rules) + item.sequence
            unknown = sorted(
                choice for choice in set(choices) if choice != "wait" and choice not in actions
            )
            if unknown:
                raise ReferenceError(
                    f"policy {item.id!r} references unknown action {unknown[0]!r}",
                    item.location,
                )
            policies[item.id] = PolicyIR(
                scenario_id,
                item.id,
                tuple(
                    PolicyRuleIR(
                        rule.action_id,
                        compile_process_expression(
                            rule.condition,
                            self.boolean,
                            dynamic_symbols,
                            self.registry,
                        )
                        if rule.condition is not None
                        else None,
                    )
                    for rule in item.rules
                ),
                item.sequence,
                item.location,
            )

        schedules = []
        for item in source.schedules:
            if isinstance(item, AtScheduleAst):
                _time_expr, time = _compile_constant(item.time, self.time, self.static_symbols, self.registry)
                assert isinstance(time, Fraction)
                if time < 0:
                    raise DomainError("scenario event time cannot be negative", item.location)
                phase = phases.get(item.phase_id)
                if phase is None:
                    raise ReferenceError(f"unknown scenario phase {item.phase_id!r}", item.location)
                schedules.append(
                    AtScheduleIR(
                        time,
                        phase,
                        tuple(self._call(send, instances, phases, self.static_symbols, allow_action=False) for send in item.sends),
                        item.location,
                    )
                )
            else:
                assert isinstance(item, EveryScheduleAst)
                _interval_expr, interval = _compile_constant(item.interval, self.time, self.static_symbols, self.registry)
                _start_expr, start = _compile_constant(item.start, self.time, self.static_symbols, self.registry)
                end = None
                if item.end is not None:
                    _end_expr, end = _compile_constant(item.end, self.time, self.static_symbols, self.registry)
                assert isinstance(interval, Fraction) and isinstance(start, Fraction)
                if interval <= 0 or start < 0 or (end is not None and end < start):
                    raise DomainError("periodic schedule requires interval > 0 and 0 <= start <= end", item.location)
                phase = phases.get(item.phase_id)
                if phase is None:
                    raise ReferenceError(f"unknown scenario phase {item.phase_id!r}", item.location)
                schedules.append(
                    EveryScheduleIR(
                        interval,
                        start,
                        end,
                        phase,
                        tuple(self._call(send, instances, phases, self.static_symbols, allow_action=False) for send in item.sends),
                        item.location,
                    )
                )

        decisions = []
        for item in source.decisions:
            _interval_expr, interval = _compile_constant(item.interval, self.time, self.static_symbols, self.registry)
            _start_expr, start = _compile_constant(item.start, self.time, self.static_symbols, self.registry)
            end = None
            if item.end is not None:
                _end_expr, end = _compile_constant(item.end, self.time, self.static_symbols, self.registry)
            assert isinstance(interval, Fraction) and isinstance(start, Fraction)
            if interval <= 0 or start < 0 or (end is not None and end < start):
                raise DomainError("decision schedule requires interval > 0 and 0 <= start <= end", item.location)
            phase = phases.get(item.phase_id)
            if phase is None:
                raise ReferenceError(f"unknown scenario phase {item.phase_id!r}", item.location)
            action_ids, allow_wait = self._decision_actions(
                item.options, actions, item.location
            )
            decisions.append(
                DecisionScheduleIR(
                    interval,
                    start,
                    end,
                    phase,
                    action_ids,
                    allow_wait,
                    item.location,
                )
            )

        event_decisions = []
        for item in source.event_decisions:
            instance = instances.get(item.source.instance_id)
            if instance is None:
                raise ReferenceError(
                    f"event decision references unknown instance {item.source.instance_id!r}",
                    item.location,
                )
            event = next(
                (
                    event
                    for event in instance.process.events
                    if event.ref.member_id == item.source.member_id
                    and event.direction is not EventDirection.INTERNAL
                ),
                None,
            )
            if event is None:
                raise ReferenceError(
                    "event decision requires a public input or output event",
                    item.location,
                )
            phase = phases.get(item.phase_id)
            if phase is None:
                raise ReferenceError(
                    f"unknown scenario phase {item.phase_id!r}", item.location
                )
            action_ids, allow_wait = self._decision_actions(
                item.options, actions, item.location
            )
            event_decisions.append(
                EventDecisionIR(
                    _member(instance, event.ref),
                    phase,
                    action_ids,
                    allow_wait,
                    item.location,
                )
            )

        condition_decisions = []
        for item in source.condition_decisions:
            phase = phases.get(item.phase_id)
            if phase is None:
                raise ReferenceError(
                    f"unknown scenario phase {item.phase_id!r}", item.location
                )
            action_ids, allow_wait = self._decision_actions(
                item.options, actions, item.location
            )
            condition = compile_process_expression(
                item.condition,
                self.boolean,
                dynamic_symbols,
                self.registry,
            )
            has_flow = any(
                instance.process.flows for instance in instances.values()
            )
            condition_decisions.append(
                ConditionDecisionIR(
                    condition,
                    phase,
                    action_ids,
                    allow_wait,
                    has_flow
                    and supports_exact_affine_crossing(
                        condition, tuple(instances.values())
                    ),
                    item.location,
                )
            )

        continuous_decisions = []
        for item in source.continuous_decisions:
            if item.maximum_occurrences <= 0:
                raise SchemaError(
                    "continuous decision maximum occurrences must be positive",
                    item.location,
                )
            _start_expression, start = _compile_constant(
                item.start, self.time, self.static_symbols, self.registry
            )
            _end_expression, end = _compile_constant(
                item.end, self.time, self.static_symbols, self.registry
            )
            assert isinstance(start, Fraction) and isinstance(end, Fraction)
            if start < 0 or end < start:
                raise DomainError(
                    "continuous decision requires 0 <= start <= end", item.location
                )
            phase = phases.get(item.phase_id)
            if phase is None:
                raise ReferenceError(
                    f"unknown scenario phase {item.phase_id!r}", item.location
                )
            action_ids, allow_wait = self._decision_actions(
                item.options, actions, item.location
            )
            assert not allow_wait
            continuous_decisions.append(
                ContinuousDecisionIR(
                    item.maximum_occurrences,
                    start,
                    end,
                    phase,
                    action_ids,
                    item.location,
                )
            )

        assert source.bounds is not None
        _horizon_expr, horizon = _compile_constant(source.bounds.horizon, self.time, self.static_symbols, self.registry)
        assert isinstance(horizon, Fraction)
        if horizon <= 0:
            raise DomainError("scenario horizon must be positive", source.bounds.horizon.location)
        bounds = ScenarioBoundsIR(
            horizon,
            _positive_integer(source.bounds.maximum_events, "maximum_events", self.static_symbols, self.registry, MAX_SCENARIO_EVENTS),
            _positive_integer(source.bounds.maximum_decisions, "maximum_decisions", self.static_symbols, self.registry, MAX_SCENARIO_DECISIONS),
            _positive_integer(source.bounds.maximum_branches, "maximum_branches", self.static_symbols, self.registry, MAX_SCENARIO_BRANCHES),
            _positive_integer(source.bounds.maximum_entities, "maximum_entities", self.static_symbols, self.registry, MAX_SCENARIO_INSTANCES),
        )
        if len(instances) > bounds.maximum_entities:
            raise SchemaError("scenario instances exceed maximum_entities", source.bounds.maximum_entities.location)
        if any(item.end > horizon for item in continuous_decisions):
            raise SchemaError(
                "continuous decision interval exceeds scenario horizon", source.location
            )
        stop = (
            compile_process_expression(source.stop, self.boolean, dynamic_symbols, self.registry)
            if source.stop is not None
            else None
        )
        measures = self._lower_measures(source, instances, dynamic_symbols)
        objectives = self._lower_objectives(source, measures)
        scenario = ScenarioIR(
            source.owner_id,
            source.id,
            source.label,
            tuple(phases.values()),
            tuple(instances.values()),
            tuple(connections),
            tuple(schedules),
            tuple(actions.values()),
            tuple(policies.values()),
            tuple(decisions),
            tuple(event_decisions),
            tuple(condition_decisions),
            tuple(continuous_decisions),
            tuple(observation_symbols.values()) + tuple(runtime_symbols.values()),
            measures,
            objectives,
            stop,
            bounds,
            location=source.location,
        )
        validate_scenario_ir(scenario)
        return scenario


def lower_scenario_asts(
    sources: Sequence[ScenarioAst],
    registry: UnitRegistry,
    processes: Mapping[str, ProcessIR],
) -> Tuple[ScenarioIR, ...]:
    lowerer = ScenarioLowerer(registry, processes)
    result = []
    seen = set()
    for source in sources:
        if source.qualified_id in seen:
            raise SchemaError(f"duplicate scenario {source.qualified_id!r}", source.location)
        seen.add(source.qualified_id)
        result.append(lowerer.lower(source))
    return tuple(result)


def lower_analysis_asts(
    sources: Sequence[AnalysisAst],
    registry: UnitRegistry,
    scenarios: Mapping[str, ScenarioIR],
) -> Tuple[AnalysisIR, ...]:
    result = []
    seen = set()
    for source in sources:
        if source.qualified_id in seen:
            raise SchemaError(f"duplicate analysis {source.qualified_id!r}", source.location)
        seen.add(source.qualified_id)
        scenario = _resolve_path(source.owner_id, source.scenario_path, scenarios, "scenario")
        symbols = {symbol.id: symbol for symbol in scenario.observation_symbols}
        target = (
            compile_process_expression(
                source.target, BooleanTypeIR(), symbols, registry
            )
            if source.target is not None
            else None
        )
        objective_ids = source.objective_ids
        available_objectives = {objective.id for objective in scenario.objectives}
        unknown_objectives = sorted(set(objective_ids) - available_objectives)
        if unknown_objectives:
            raise ReferenceError(
                f"analysis references unknown objective {unknown_objectives[0]!r}",
                source.location,
            )
        if len(set(objective_ids)) != len(objective_ids):
            raise SchemaError("analysis objective ids must be unique", source.location)
        if source.operation == "optimize" and not objective_ids:
            raise SchemaError("optimize analysis requires objectives", source.location)
        if source.operation != "optimize" and objective_ids:
            raise SchemaError(
                "objectives are only valid for optimize analysis", source.location
            )
        policy_ids = source.policy_ids
        available_policies = {policy.id for policy in scenario.policies}
        unknown_policies = sorted(set(policy_ids) - available_policies)
        if unknown_policies:
            raise ReferenceError(
                f"analysis references unknown policy {unknown_policies[0]!r}",
                source.location,
            )
        if source.operation == "compare" and len(policy_ids) < 2:
            raise SchemaError("compare analysis requires at least two policies", source.location)
        if source.operation != "compare" and len(policy_ids) > 1:
            raise SchemaError(
                f"{source.operation} analysis accepts at most one policy",
                source.location,
            )
        if source.operation == "optimize" and policy_ids:
            raise SchemaError(
                "optimize searches decisions and cannot also select a fixed policy",
                source.location,
            )
        if source.operation == "steady" and policy_ids:
            raise SchemaError("steady does not accept a decision policy", source.location)
        if source.operation != "reach" and target is not None:
            raise SchemaError("target is only valid for reach analysis", source.location)
        if source.operation == "reach" and target is None and scenario.stop is None:
            raise SchemaError(
                "reach analysis requires target or a scenario stop condition",
                source.location,
            )
        search_method = source.search_method
        time_tolerance = None
        maximum_evaluations = None
        search_fields = (
            search_method,
            source.time_tolerance,
            source.maximum_evaluations,
        )
        if any(item is not None for item in search_fields) and not all(
            item is not None for item in search_fields
        ):
            raise SchemaError(
                "analysis search requires method, time_tolerance, and maximum_evaluations",
                source.location,
            )
        if search_method is not None:
            if source.operation != "optimize":
                raise SchemaError("search is only valid for optimize analysis", source.location)
            if search_method != "adaptive_dyadic":
                raise SchemaError(
                    f"unknown Process search method {search_method!r}", source.location
                )
            assert source.time_tolerance is not None
            assert source.maximum_evaluations is not None
            static_symbols = scenario_static_symbols(registry)
            _tolerance_expression, time_tolerance = _compile_constant(
                source.time_tolerance,
                NumberTypeIR("second", registry.parse_unit("second")),
                static_symbols,
                registry,
            )
            assert isinstance(time_tolerance, Fraction)
            if time_tolerance <= 0:
                raise DomainError("time_tolerance must be positive", source.location)
            maximum_evaluations = _positive_integer(
                source.maximum_evaluations,
                "maximum_evaluations",
                static_symbols,
                registry,
                MAX_SCENARIO_BRANCHES,
            )
            if maximum_evaluations > scenario.bounds.maximum_branches:
                raise SchemaError(
                    "maximum_evaluations cannot exceed scenario maximum_branches",
                    source.location,
                )
        if scenario.continuous_decisions and source.operation == "optimize" and search_method is None:
            raise SchemaError(
                "continuous-time optimize requires explicit search settings",
                source.location,
            )
        if search_method is not None and not scenario.continuous_decisions:
            raise SchemaError(
                "search settings require a continuous decision declaration",
                source.location,
            )
        result.append(
            AnalysisIR(
                source.owner_id,
                source.id,
                source.label,
                scenario.qualified_id,
                source.operation,
                policy_ids,
                objective_ids,
                search_method,
                time_tolerance,
                maximum_evaluations,
                target,
                source.location,
            )
        )
    return tuple(result)
