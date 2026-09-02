"""Resolve Scenario/Analysis AST against workspace Process declarations."""

from __future__ import annotations

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
from .scenario_ast import AnalysisAst, AtScheduleAst, EveryScheduleAst, ScenarioAst, ScenarioSendAst
from .scenario_ir import (
    AnalysisIR,
    AtScheduleIR,
    CompositeActionIR,
    ConnectionIR,
    DecisionScheduleIR,
    EveryScheduleIR,
    InstanceInputIR,
    InstanceMemberRefIR,
    InstancePhaseIR,
    ObjectiveIR,
    PolicyIR,
    PolicyRuleIR,
    ProcessInstanceIR,
    ScenarioBoundsIR,
    ScenarioCallIR,
    ScenarioIR,
    ScenarioPhaseIR,
)
from .schema import require_identifier
from .scenario_validation import validate_scenario_ir
from .units import DIMENSIONLESS, UnitRegistry


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
            action_ids = tuple(option for option in item.options if option != "wait")
            unknown = sorted(set(action_ids) - set(actions))
            if unknown:
                raise ReferenceError(f"decision references unknown action {unknown[0]!r}", item.location)
            decisions.append(
                DecisionScheduleIR(
                    interval,
                    start,
                    end,
                    phase,
                    action_ids,
                    "wait" in item.options,
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
        stop = (
            compile_process_expression(source.stop, self.boolean, dynamic_symbols, self.registry)
            if source.stop is not None
            else None
        )
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
            tuple(observation_symbols.values()) + tuple(runtime_symbols.values()),
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
        objective = (
            ObjectiveIR(
                source.objective_direction or "maximize",
                compile_process_expression(source.objective, None, symbols, registry),
            )
            if source.objective is not None
            else None
        )
        tie_break = (
            ObjectiveIR(
                source.tie_break_direction or "maximize",
                compile_process_expression(source.tie_break, None, symbols, registry),
            )
            if source.tie_break is not None
            else None
        )
        target = (
            compile_process_expression(
                source.target, BooleanTypeIR(), symbols, registry
            )
            if source.target is not None
            else None
        )
        if source.operation == "optimize" and objective is None:
            raise SchemaError("optimize analysis requires an objective", source.location)
        if source.operation != "optimize" and objective is not None:
            raise SchemaError(
                "objective is only valid for optimize analysis", source.location
            )
        if objective is not None and not isinstance(
            objective.value.result_type, NumberTypeIR
        ):
            raise SchemaError(
                "maximize/minimize objectives must be numeric", source.objective.location
            )
        if tie_break is not None and not isinstance(
            tie_break.value.result_type, NumberTypeIR
        ):
            raise SchemaError(
                "maximize/minimize tie-break objectives must be numeric",
                source.tie_break.location,
            )
        if source.operation != "optimize" and tie_break is not None:
            raise SchemaError("then is only valid for optimize analysis", source.location)
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
        result.append(
            AnalysisIR(
                source.owner_id,
                source.id,
                source.label,
                scenario.qualified_id,
                source.operation,
                policy_ids,
                objective,
                tie_break,
                target,
                source.location,
            )
        )
    return tuple(result)
