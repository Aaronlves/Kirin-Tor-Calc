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
from .process_expression import (
    ProcessValue,
    bind_process_expression_values,
    compile_process_expression,
    evaluate_process_expression,
)
from .process_ir import (
    ActionIR,
    BooleanTypeIR,
    EventArgumentIR,
    EventIR,
    LiteralExpressionIR,
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
    AnalysisChartIR,
    AnalysisIR,
    AtScheduleIR,
    ChanceConstraintIR,
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
    ScenarioVariantIR,
    TrajectoryMeasureExpressionIR,
    VariantInputIR,
)
from .schema import require_identifier
from .scenario_measure_syntax import TRAJECTORY_MEASURE_OPERATIONS
from .scenario_validation import validate_scenario_ir
from .units import DIMENSIONLESS, UnitRegistry


def _measure_call(source: ExpressionAst) -> Optional[Tuple[str, str]]:
    match = re.fullmatch(r"([a-z_][a-z0-9_]*)\((.*)\)", source.text.strip())
    if match is None or match.group(1) not in TRAJECTORY_MEASURE_OPERATIONS:
        return None
    return match.group(1), match.group(2).strip()


def _conditional_value_arguments(
    argument: str, operation: str, location
) -> Tuple[str, str, str]:
    pieces = []
    start = 0
    round_depth = 0
    square_depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(argument):
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "," and round_depth == 0 and square_depth == 0:
            pieces.append(argument[start:index].strip())
            start = index + 1
        if round_depth < 0 or square_depth < 0:
            raise SchemaError(
                f"{operation} contains an unmatched closing bracket", location
            )
    if quoted or round_depth or square_depth:
        raise SchemaError(
            f"{operation} contains an unmatched quote or bracket", location
        )
    pieces.append(argument[start:].strip())
    if len(pieces) != 3 or not pieces[0] or not pieces[1]:
        raise SchemaError(
            f"{operation} requires VALUE, CONDITION, default = VALUE", location
        )
    default_match = re.fullmatch(r"default\s*=\s*(.+)", pieces[2], re.DOTALL)
    if default_match is None:
        raise SchemaError(
            f"{operation} requires an explicit default = VALUE", location
        )
    return pieces[0], pieces[1], default_match.group(1).strip()


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
    static_values: Optional[Mapping[SymbolRefIR, ProcessValue]] = None,
) -> Tuple[TypedExpressionIR, object]:
    expression = bind_process_expression_values(
        compile_process_expression(source, expected, symbols, registry),
        static_values or {},
    )
    if any(
        reference.kind not in {ExpressionSymbolKind.UNIT, ExpressionSymbolKind.STATIC_MEMBER}
        for reference in expression.references
    ):
        raise SchemaError(
            "scenario schedule and bound expressions must be constant", source.location
        )
    value = evaluate_process_expression(
        expression, static_values or {}, registry
    )
    return (
        TypedExpressionIR(
            expression.source,
            expression.result_type,
            expression.references,
            expression.location,
            LiteralExpressionIR(value, expression.result_type),
        ),
        value,
    )


def _positive_integer(
    source: ExpressionAst,
    name: str,
    symbols: Mapping[str, SymbolRefIR],
    registry: UnitRegistry,
    maximum: int,
    static_values: Optional[Mapping[SymbolRefIR, ProcessValue]] = None,
) -> int:
    value_type = NumberTypeIR(
        "dimensionless", DIMENSIONLESS, "positive_integer", True
    )
    _expression, value = _compile_constant(
        source, value_type, symbols, registry, static_values
    )
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
        static_values: Optional[Mapping[SymbolRefIR, ProcessValue]] = None,
    ) -> None:
        self.registry = registry
        self.processes = dict(processes)
        self.static_symbols = scenario_static_symbols(registry)
        self.static_symbols.update(static_symbols or {})
        self.static_values = dict(static_values or {})
        self.boolean = BooleanTypeIR()
        self.time = NumberTypeIR("second", registry.parse_unit("second"))
        self.probability = NumberTypeIR(
            "dimensionless",
            registry.parse_unit("dimensionless"),
            "probability",
        )

    def _compile(
        self,
        source: ExpressionAst,
        expected,
        symbols: Mapping[str, SymbolRefIR],
    ) -> TypedExpressionIR:
        return bind_process_expression_values(
            compile_process_expression(
                source, expected, symbols, self.registry
            ),
            self.static_values,
        )

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
                self._compile(
                    provided[parameter.id].value,
                    parameter.value_type,
                    symbols,
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
                    self._compile(
                        item.value,
                        declared_type,
                        {**self.static_symbols, **measure_symbols},
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
                    value = self._compile(
                        ExpressionAst(argument, item.value.location),
                        expected_type,
                        dynamic_symbols,
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
                elif operation in {"minimum_where", "last_before"}:
                    value_text, condition_text, default_text = (
                        _conditional_value_arguments(
                            argument, operation, item.location
                        )
                    )
                    value = self._compile(
                        ExpressionAst(value_text, item.value.location),
                        declared_type,
                        dynamic_symbols,
                    )
                    if operation == "minimum_where" and not isinstance(
                        value.result_type, NumberTypeIR
                    ):
                        raise SchemaError(
                            "minimum_where requires a numeric value", item.location
                        )
                    condition = self._compile(
                        ExpressionAst(condition_text, item.value.location),
                        self.boolean,
                        dynamic_symbols,
                    )
                    default = self._compile(
                        ExpressionAst(default_text, item.value.location),
                        declared_type,
                        dynamic_symbols,
                    )
                    expression = TrajectoryMeasureExpressionIR(
                        operation,
                        value=value,
                        condition=condition,
                        default=default,
                    )
                elif operation == "duration_where":
                    condition = self._compile(
                        ExpressionAst(argument, item.value.location),
                        self.boolean,
                        dynamic_symbols,
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
                    condition = self._compile(
                        ExpressionAst(match.group(1).strip(), item.value.location),
                        self.boolean,
                        dynamic_symbols,
                    )
                    default = self._compile(
                        ExpressionAst(match.group(2).strip(), item.value.location),
                        self.time,
                        dynamic_symbols,
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
                self._compile(
                    condition,
                    self.boolean,
                    {**self.static_symbols, **symbols},
                )
                for condition in item.constraints
            )
            path_constraints = tuple(
                self._compile(
                    condition,
                    self.boolean,
                    {**self.static_symbols, **symbols},
                )
                for condition in item.path_constraints
            )
            chance_constraints = []
            for constraint in item.chance_constraints:
                _threshold_expression, threshold = _compile_constant(
                    constraint.threshold,
                    self.probability,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
                assert isinstance(threshold, Fraction)
                chance_constraints.append(
                    ChanceConstraintIR(
                        constraint.comparison,
                        threshold,
                        self._compile(
                            constraint.condition,
                            self.boolean,
                            {**self.static_symbols, **symbols},
                        ),
                        constraint.location,
                    )
                )
            result.append(
                ObjectiveIR(
                    source.qualified_id,
                    item.id,
                    tuple(terms),
                    constraints,
                    path_constraints,
                    tuple(chance_constraints),
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
            input_values = []
            for name in input_map:
                if name not in provided:
                    continue
                expression, _value = _compile_constant(
                    provided[name].value,
                    input_map[name].value_type,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
                input_values.append(
                    InstanceInputIR(
                        _member(placeholder, input_map[name].ref), expression
                    )
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
                tuple(input_values),
                tuple(phase_values),
                item.location,
            )
        if len(instances) > MAX_SCENARIO_INSTANCES:
            raise SchemaError(
                f"scenario exceeds {MAX_SCENARIO_INSTANCES} instances", source.location
            )

        variants = []
        variant_ids = set()
        for item in source.variants:
            require_identifier(item.id, "scenario variant id", item.location)
            if item.id == "base":
                raise SchemaError("scenario variant id 'base' is reserved", item.location)
            if item.id in variant_ids:
                raise SchemaError(f"duplicate scenario variant {item.id!r}", item.location)
            variant_ids.add(item.id)
            bindings = []
            seen_bindings = set()
            for binding in item.inputs:
                instance = instances.get(binding.instance_id)
                if instance is None:
                    raise ReferenceError(
                        f"variant references unknown instance {binding.instance_id!r}",
                        binding.location,
                    )
                declaration = next(
                    (
                        declaration
                        for declaration in instance.process.inputs
                        if declaration.ref.member_id == binding.input_id
                    ),
                    None,
                )
                if declaration is None:
                    raise ReferenceError(
                        f"variant references unknown input {binding.instance_id}.{binding.input_id}",
                        binding.location,
                    )
                key = (binding.instance_id, binding.input_id)
                if key in seen_bindings:
                    raise SchemaError(
                        f"variant assigns input {binding.instance_id}.{binding.input_id} more than once",
                        binding.location,
                    )
                seen_bindings.add(key)
                expression, _value = _compile_constant(
                    binding.value,
                    declaration.value_type,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
                bindings.append(
                    VariantInputIR(_member(instance, declaration.ref), expression)
                )
            variants.append(
                ScenarioVariantIR(
                    scenario_id,
                    item.id,
                    tuple(bindings),
                    item.label,
                    item.location,
                )
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
                self._compile(item.guard, self.boolean, dynamic_symbols)
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
                        self._compile(
                            rule.condition,
                            self.boolean,
                            dynamic_symbols,
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
                _time_expr, time = _compile_constant(
                    item.time,
                    self.time,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
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
                _interval_expr, interval = _compile_constant(
                    item.interval,
                    self.time,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
                _start_expr, start = _compile_constant(
                    item.start,
                    self.time,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
                end = None
                if item.end is not None:
                    _end_expr, end = _compile_constant(
                        item.end,
                        self.time,
                        self.static_symbols,
                        self.registry,
                        self.static_values,
                    )
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
            _interval_expr, interval = _compile_constant(
                item.interval,
                self.time,
                self.static_symbols,
                self.registry,
                self.static_values,
            )
            _start_expr, start = _compile_constant(
                item.start,
                self.time,
                self.static_symbols,
                self.registry,
                self.static_values,
            )
            end = None
            if item.end is not None:
                _end_expr, end = _compile_constant(
                    item.end,
                    self.time,
                    self.static_symbols,
                    self.registry,
                    self.static_values,
                )
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
            condition = self._compile(
                item.condition,
                self.boolean,
                dynamic_symbols,
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
                item.start,
                self.time,
                self.static_symbols,
                self.registry,
                self.static_values,
            )
            _end_expression, end = _compile_constant(
                item.end,
                self.time,
                self.static_symbols,
                self.registry,
                self.static_values,
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
        _horizon_expr, horizon = _compile_constant(
            source.bounds.horizon,
            self.time,
            self.static_symbols,
            self.registry,
            self.static_values,
        )
        assert isinstance(horizon, Fraction)
        if horizon <= 0:
            raise DomainError("scenario horizon must be positive", source.bounds.horizon.location)
        bounds = ScenarioBoundsIR(
            horizon,
            _positive_integer(
                source.bounds.maximum_events,
                "maximum_events",
                self.static_symbols,
                self.registry,
                MAX_SCENARIO_EVENTS,
                self.static_values,
            ),
            _positive_integer(
                source.bounds.maximum_decisions,
                "maximum_decisions",
                self.static_symbols,
                self.registry,
                MAX_SCENARIO_DECISIONS,
                self.static_values,
            ),
            _positive_integer(
                source.bounds.maximum_branches,
                "maximum_branches",
                self.static_symbols,
                self.registry,
                MAX_SCENARIO_BRANCHES,
                self.static_values,
            ),
            _positive_integer(
                source.bounds.maximum_entities,
                "maximum_entities",
                self.static_symbols,
                self.registry,
                MAX_SCENARIO_INSTANCES,
                self.static_values,
            ),
        )
        if len(instances) > bounds.maximum_entities:
            raise SchemaError("scenario instances exceed maximum_entities", source.bounds.maximum_entities.location)
        if any(item.end > horizon for item in continuous_decisions):
            raise SchemaError(
                "continuous decision interval exceeds scenario horizon", source.location
            )
        stop = (
            self._compile(source.stop, self.boolean, dynamic_symbols)
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
            tuple(variants),
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
    *,
    static_symbols: Optional[Mapping[str, SymbolRefIR]] = None,
    static_values: Optional[Mapping[SymbolRefIR, ProcessValue]] = None,
) -> Tuple[ScenarioIR, ...]:
    lowerer = ScenarioLowerer(
        registry,
        processes,
        static_symbols=static_symbols,
        static_values=static_values,
    )
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
        variant_ids = source.variant_ids
        available_variants = {variant.id for variant in scenario.variants}
        unknown_variants = sorted(set(variant_ids) - available_variants)
        if unknown_variants:
            raise ReferenceError(
                f"analysis references unknown variant {unknown_variants[0]!r}",
                source.location,
            )
        if len(set(variant_ids)) != len(variant_ids):
            raise SchemaError("analysis variant ids must be unique", source.location)
        if source.operation != "optimize" and variant_ids:
            raise SchemaError(
                "variants are currently valid only for optimize analysis",
                source.location,
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
        time_grid = None
        maximum_evaluations = None
        search_fields = (
            search_method,
            source.time_tolerance,
            source.time_grid,
            source.maximum_evaluations,
        )
        if any(item is not None for item in search_fields) and (
            search_method is None or source.maximum_evaluations is None
        ):
            raise SchemaError(
                "analysis search requires method and maximum_evaluations",
                source.location,
            )
        if search_method is not None:
            if source.operation != "optimize":
                raise SchemaError("search is only valid for optimize analysis", source.location)
            if search_method not in {"adaptive_dyadic", "exact_grid"}:
                raise SchemaError(
                    f"unknown Process search method {search_method!r}", source.location
                )
            assert source.maximum_evaluations is not None
            static_symbols = scenario_static_symbols(registry)
            search_time_type = NumberTypeIR("second", registry.parse_unit("second"))
            if search_method == "adaptive_dyadic":
                if source.time_tolerance is None or source.time_grid is not None:
                    raise SchemaError(
                        "adaptive_dyadic search requires time_tolerance and forbids time_grid",
                        source.location,
                    )
                _tolerance_expression, time_tolerance = _compile_constant(
                    source.time_tolerance,
                    search_time_type,
                    static_symbols,
                    registry,
                )
                assert isinstance(time_tolerance, Fraction)
                if time_tolerance <= 0:
                    raise DomainError("time_tolerance must be positive", source.location)
            else:
                if source.time_grid is None or source.time_tolerance is not None:
                    raise SchemaError(
                        "exact_grid search requires time_grid and forbids time_tolerance",
                        source.location,
                    )
                _grid_expression, time_grid = _compile_constant(
                    source.time_grid,
                    search_time_type,
                    static_symbols,
                    registry,
                )
                assert isinstance(time_grid, Fraction)
                if time_grid <= 0:
                    raise DomainError("time_grid must be positive", source.location)
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
        charts = []
        chart_ids = set()
        measure_map = {measure.id: measure for measure in scenario.measures}
        observation_map = {
            symbol.id: symbol
            for symbol in scenario.observation_symbols
            if symbol.kind is ExpressionSymbolKind.OBSERVATION
        }
        instance_map = {instance.id: instance for instance in scenario.instances}
        action_ids = {action.id for action in scenario.actions}
        for chart in source.charts:
            require_identifier(chart.id, "analysis chart id", chart.location)
            if chart.id in chart_ids:
                raise SchemaError(f"duplicate analysis chart {chart.id!r}", chart.location)
            chart_ids.add(chart.id)
            if chart.kind not in {
                "trajectory",
                "pareto",
                "decision_surface",
                "variant_comparison",
            }:
                raise SchemaError(
                    f"unknown Process chart kind {chart.kind!r}", chart.location
                )
            if chart.kind == "trajectory" and source.operation == "steady":
                raise SchemaError(
                    "steady analysis has no time trajectory to chart",
                    chart.location,
                )
            if chart.kind != "trajectory" and source.operation != "optimize":
                raise SchemaError(
                    f"{chart.kind} chart requires an optimize analysis",
                    chart.location,
                )
            series = []
            if chart.kind == "trajectory":
                if not chart.series:
                    raise SchemaError("trajectory chart requires series", chart.location)
                for name in chart.series:
                    symbol = observation_map.get(name)
                    if symbol is None or not isinstance(symbol.value_type, NumberTypeIR):
                        raise ReferenceError(
                            f"trajectory series requires numeric observation {name!r}",
                            chart.location,
                        )
                    series.append(symbol)
                dimensions = {
                    symbol.value_type.dimension for symbol in series
                }
                if len(dimensions) != 1:
                    raise SchemaError(
                        "trajectory chart series must share one unit dimension",
                        chart.location,
                    )
            elif chart.kind == "variant_comparison":
                if not chart.series:
                    raise SchemaError(
                        "variant_comparison chart requires Measure series",
                        chart.location,
                    )
                for name in chart.series:
                    measure = measure_map.get(name)
                    if measure is None or not isinstance(measure.value_type, NumberTypeIR):
                        raise ReferenceError(
                            f"variant comparison requires numeric Measure {name!r}",
                            chart.location,
                        )
                    series.append(
                        SymbolRefIR(
                            scenario.qualified_id,
                            measure.id,
                            ExpressionSymbolKind.MEASURE,
                            measure.value_type,
                        )
                    )
                if len(
                    {
                        symbol.value_type.dimension
                        for symbol in series
                        if isinstance(symbol.value_type, NumberTypeIR)
                    }
                ) != 1:
                    raise SchemaError(
                        "variant comparison series must share one unit dimension",
                        chart.location,
                    )
            markers = []
            for marker in chart.markers:
                event = re.fullmatch(
                    r"event\s+([a-z][a-z0-9_]*)\.([a-z][a-z0-9_]*)",
                    marker,
                )
                decision = re.fullmatch(
                    r"decision\s+([a-z][a-z0-9_]*)", marker
                )
                if event:
                    instance = instance_map.get(event.group(1))
                    declaration = next(
                        (
                            item
                            for item in instance.process.events
                            if item.ref.member_id == event.group(2)
                            and item.direction is not EventDirection.INTERNAL
                        ),
                        None,
                    ) if instance is not None else None
                    if declaration is None:
                        raise ReferenceError(
                            f"chart marker requires public event {event.group(1)}.{event.group(2)}",
                            chart.location,
                        )
                    markers.append(("event", f"{event.group(1)}.{event.group(2)}"))
                elif decision and decision.group(1) in action_ids:
                    markers.append(("decision", decision.group(1)))
                else:
                    raise SchemaError(
                        "chart marker must use event INSTANCE.PUBLIC_EVENT or decision ACTION",
                        chart.location,
                    )
            x_measure = measure_map.get(chart.x) if chart.x else None
            y_measure = measure_map.get(chart.y) if chart.y else None
            value_measure = measure_map.get(chart.value) if chart.value else None
            if chart.kind == "pareto" and (
                x_measure is None or y_measure is None
            ):
                raise SchemaError("pareto chart requires x and y Measures", chart.location)
            if chart.kind == "pareto" and (
                chart.x_direction not in {"maximize", "minimize"}
                or chart.y_direction not in {"maximize", "minimize"}
            ):
                raise SchemaError(
                    "pareto chart requires explicit x_direction and y_direction",
                    chart.location,
                )
            if chart.kind != "pareto" and (
                chart.x_direction is not None or chart.y_direction is not None
            ):
                raise SchemaError(
                    "chart directions are only valid for pareto charts", chart.location
                )
            if chart.kind == "decision_surface" and value_measure is None:
                raise SchemaError(
                    "decision_surface chart requires a value Measure", chart.location
                )
            for measure in (x_measure, y_measure, value_measure):
                if measure is not None and not isinstance(measure.value_type, NumberTypeIR):
                    raise SchemaError("chart Measures must be numeric", chart.location)
            if chart.export_svg is not None and not chart.export_svg.endswith(".svg"):
                raise SchemaError("chart export_svg must end in .svg", chart.location)
            if chart.export_csv is not None and not chart.export_csv.endswith(".csv"):
                raise SchemaError("chart export_csv must end in .csv", chart.location)
            charts.append(
                AnalysisChartIR(
                    source.qualified_id,
                    chart.id,
                    chart.kind,
                    chart.label,
                    tuple(series),
                    tuple(markers),
                    x_measure.id if x_measure is not None else None,
                    y_measure.id if y_measure is not None else None,
                    value_measure.id if value_measure is not None else None,
                    chart.x_direction,
                    chart.y_direction,
                    chart.export_svg,
                    chart.export_csv,
                    chart.location,
                )
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
                variant_ids,
                search_method,
                time_tolerance,
                time_grid,
                maximum_evaluations,
                tuple(charts),
                target,
                source.location,
            )
        )
    return tuple(result)
