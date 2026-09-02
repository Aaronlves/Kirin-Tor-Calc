"""Structural lowering and name resolution from process AST to process IR.

This stage resolves declared types, members, event arguments, phases, keys, and
expression dependencies. Full expression result-type inference, transition
conflict analysis, and execution deliberately remain later stages.
"""

from __future__ import annotations

import ast as python_ast
from typing import Dict, Iterable, Mapping, Optional, Sequence, Set, Tuple

from .errors import ExpressionError, SchemaError, SourceLocation
from .expression import ALLOWED_NODES
from .kirin_v2 import normalize_expression
from .limits import (
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    MAX_DIRECT_DEPENDENCIES,
    MAX_EXPRESSION_LENGTH,
    MAX_MODEL_INPUTS,
    MAX_PROCESS_COLLECTION_CAPACITY,
)
from .process_ast import (
    BranchEffectAst,
    CancelEffectAst,
    EffectAst,
    EmitEffectAst,
    EventCallAst,
    ExpressionAst,
    LetEffectAst,
    NextEffectAst,
    ProcessAst,
    ScheduleEffectAst,
    TypeAst,
    WhenEffectAst,
)
from .process_ir import (
    ActionIR,
    BooleanTypeIR,
    BoundIR,
    BranchEffectIR,
    CancelEffectIR,
    EffectIR,
    EmitEffectIR,
    EventArgumentIR,
    EventCallIR,
    EventIR,
    EventIdScheduleKeyIR,
    EventIdTypeIR,
    EventParameterIR,
    FlowIR,
    HandlerIR,
    InputIR,
    KeyIR,
    LetEffectIR,
    ListTypeIR,
    MapTypeIR,
    NextEffectIR,
    NumberTypeIR,
    ObjectTypeIR,
    ObservationIR,
    PhaseIR,
    ProbabilityCaseIR,
    ProcessIR,
    ProcessMemberRefIR,
    ScheduleEffectIR,
    ScheduleKeyIR,
    StateIR,
    StaticScheduleKeyIR,
    SymbolicTypeIR,
    SymbolRefIR,
    TypedExpressionIR,
    ValueTypeIR,
    WhenEffectIR,
)
from .process_model import (
    EventDirection,
    ExpressionSymbolKind,
    ProcessMemberKind,
    Reducer,
)
from .schema import require_identifier
from .units import DIMENSIONLESS, DomainSpec, UnitRegistry


_PROCESS_EXPRESSION_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "argmax",
        "argmin",
        "ceil",
        "contains",
        "empty",
        "filter",
        "floor",
        "get",
        "if_else",
        "max",
        "min",
        "put",
        "remove",
        "size",
        "sqrt",
        "sum",
    }
)


def _error(message: str, location: Optional[SourceLocation]) -> SchemaError:
    return SchemaError(message, location)


def _depth(node: python_ast.AST) -> int:
    children = list(python_ast.iter_child_nodes(node))
    return 1 if not children else 1 + max(_depth(child) for child in children)


def _attribute_path(node: python_ast.AST, location: Optional[SourceLocation]) -> str:
    parts = []
    candidate = node
    while isinstance(candidate, python_ast.Attribute):
        if candidate.attr.startswith("__"):
            raise ExpressionError("private expression paths are not allowed", location)
        parts.append(candidate.attr)
        candidate = candidate.value
    if not isinstance(candidate, python_ast.Name) or candidate.id.startswith("__"):
        raise ExpressionError("expression paths must begin with a declared name", location)
    parts.append(candidate.id)
    return ".".join(reversed(parts))


class ProcessLowerer:
    """Resolve one process against the existing unit/domain/type authority."""

    def __init__(
        self,
        registry: UnitRegistry,
        *,
        object_types: Iterable[str] = (),
        static_symbols: Optional[Mapping[str, SymbolRefIR]] = None,
    ) -> None:
        self.registry = registry
        self.object_types = frozenset(object_types)
        self.static_symbols = dict(static_symbols or {})
        self._boolean = BooleanTypeIR()
        probability = registry.domains["probability"]
        self._probability = self._domain_type("probability", probability)
        self._time = NumberTypeIR("second", registry.parse_unit("second"))

    def _domain_type(self, domain_id: str, domain: DomainSpec) -> ValueTypeIR:
        if domain.value_type == "boolean":
            return BooleanTypeIR(domain_id)
        if domain.value_type == "symbolic":
            return SymbolicTypeIR(domain_id)
        if domain.value_type == "number":
            return NumberTypeIR(
                domain.unit_name,
                self.registry.parse_unit(domain.unit_name),
                domain_id,
                domain.integer,
            )
        raise _error(f"domain {domain_id!r} has unsupported process value type", None)

    def _type(self, node: TypeAst) -> ValueTypeIR:
        if node.name == "boolean" and not node.arguments and node.capacity is None:
            return BooleanTypeIR()
        if node.name == "event_id" and not node.arguments and node.capacity is None:
            return EventIdTypeIR()
        if node.name == "number":
            if len(node.arguments) != 1 or node.capacity is not None:
                raise _error("number process type requires exactly one unit", node.location)
            unit_name = node.arguments[0].name
            if node.arguments[0].arguments or node.arguments[0].capacity is not None:
                raise _error("number unit must be a plain unit name", node.location)
            return NumberTypeIR(
                unit_name,
                self.registry.parse_unit(unit_name, node.location),
            )
        if node.name in {"list", "map"}:
            if node.capacity is None or node.capacity <= 0:
                raise _error("process collection capacity must be positive", node.location)
            if node.capacity > MAX_PROCESS_COLLECTION_CAPACITY:
                raise _error(
                    "process collection capacity exceeds "
                    f"{MAX_PROCESS_COLLECTION_CAPACITY}",
                    node.location,
                )
            if node.name == "list" and len(node.arguments) == 1:
                return ListTypeIR(self._type(node.arguments[0]), node.capacity)
            if node.name == "map" and len(node.arguments) == 2:
                return MapTypeIR(
                    self._type(node.arguments[0]),
                    self._type(node.arguments[1]),
                    node.capacity,
                )
            raise _error(f"invalid {node.name} process type", node.location)
        if node.arguments or node.capacity is not None:
            raise _error(f"unsupported generic process type {node.name!r}", node.location)
        if node.name in self.registry.domains:
            return self._domain_type(node.name, self.registry.domains[node.name])
        if node.name in self.registry.units:
            return NumberTypeIR(
                node.name, self.registry.parse_unit(node.name, node.location)
            )
        if node.name in self.object_types:
            return ObjectTypeIR(node.name)
        raise _error(f"unknown process type {node.name!r}", node.location)

    def _expression(
        self,
        source: ExpressionAst,
        result_type: ValueTypeIR,
        symbols: Mapping[str, SymbolRefIR],
    ) -> TypedExpressionIR:
        normalized = normalize_expression(source.text, self.registry.units)
        if len(normalized) > MAX_EXPRESSION_LENGTH:
            raise ExpressionError(
                f"expression exceeds {MAX_EXPRESSION_LENGTH} characters",
                source.location,
            )
        try:
            tree = python_ast.parse(normalized, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(
                f"invalid expression syntax at column {exc.offset}: {exc.msg}",
                source.location,
            ) from exc
        nodes = list(python_ast.walk(tree))
        if len(nodes) > MAX_AST_NODES:
            raise ExpressionError(
                f"expression exceeds {MAX_AST_NODES} AST nodes", source.location
            )
        for node in nodes:
            if type(node) not in ALLOWED_NODES:
                raise ExpressionError(
                    f"expression syntax {type(node).__name__} is not allowed",
                    source.location,
                )
        if _depth(tree) > MAX_AST_DEPTH:
            raise ExpressionError(
                f"expression exceeds AST depth {MAX_AST_DEPTH}", source.location
            )

        attribute_bases = {
            id(node.value)
            for node in nodes
            if isinstance(node, python_ast.Attribute)
        }
        call_functions = {
            id(node.func)
            for node in nodes
            if isinstance(node, python_ast.Call)
        }
        references: Dict[
            Tuple[str, str, ExpressionSymbolKind], SymbolRefIR
        ] = {}

        def include(reference: SymbolRefIR) -> None:
            references[(reference.owner_id, reference.id, reference.kind)] = reference

        for node in nodes:
            if isinstance(node, python_ast.Call):
                if node.keywords:
                    raise ExpressionError(
                        "keyword arguments are not allowed", source.location
                    )
                if isinstance(node.func, python_ast.Name):
                    function_name = node.func.id
                elif isinstance(node.func, python_ast.Attribute):
                    function_name = _attribute_path(node.func, source.location)
                else:
                    raise ExpressionError(
                        "only declared named functions are allowed", source.location
                    )
                if function_name in _PROCESS_EXPRESSION_BUILTINS:
                    continue
                function = symbols.get(function_name)
                if function is None or function.kind is not ExpressionSymbolKind.FUNCTION:
                    raise ExpressionError(
                        f"undeclared process function {function_name!r}",
                        source.location,
                    )
                include(function)
            elif (
                isinstance(node, python_ast.Attribute)
                and id(node) not in attribute_bases
                and id(node) not in call_functions
            ):
                name = _attribute_path(node, source.location)
                reference = symbols.get(name)
                if reference is None:
                    raise ExpressionError(
                        f"undeclared process value {name!r}", source.location
                    )
                include(reference)
            elif (
                isinstance(node, python_ast.Name)
                and id(node) not in attribute_bases
                and id(node) not in call_functions
            ):
                name = node.id
                if name in {"true", "false", "empty"}:
                    continue
                reference = symbols.get(name)
                if reference is None and name in self.registry.units:
                    reference = SymbolRefIR(
                        "@units",
                        name,
                        ExpressionSymbolKind.UNIT,
                        NumberTypeIR(name, self.registry.parse_unit(name, source.location)),
                    )
                if reference is None:
                    raise ExpressionError(
                        f"undeclared process value {name!r}", source.location
                    )
                include(reference)
        if len(references) > MAX_DIRECT_DEPENDENCIES:
            raise ExpressionError(
                f"expression exceeds {MAX_DIRECT_DEPENDENCIES} direct dependencies",
                source.location,
            )
        ordered = tuple(
            references[key]
            for key in sorted(
                references, key=lambda value: (value[0], value[1], value[2].value)
            )
        )
        return TypedExpressionIR(normalized, result_type, ordered, source.location)

    def _member(
        self, process_id: str, member_id: str, kind: ProcessMemberKind
    ) -> ProcessMemberRefIR:
        return ProcessMemberRefIR(process_id, member_id, kind)

    def _register_members(self, source: ProcessAst) -> None:
        namespaces: Sequence[
            Tuple[str, Sequence[Tuple[ProcessMemberKind, Sequence[object]]]]
        ] = (
            (
                "value",
                (
                    (ProcessMemberKind.INPUT, source.inputs),
                    (ProcessMemberKind.STATE, source.states),
                ),
            ),
            (
                "trigger",
                (
                    (ProcessMemberKind.EVENT, source.events),
                    (ProcessMemberKind.ACTION, source.actions),
                ),
            ),
            ("key", ((ProcessMemberKind.KEY, source.keys),)),
            ("phase", ((ProcessMemberKind.PHASE, source.phases),)),
            (
                "observation",
                ((ProcessMemberKind.OBSERVATION, source.observations),),
            ),
        )
        for namespace, declarations in namespaces:
            members: Dict[str, ProcessMemberKind] = {}
            for kind, values in declarations:
                for value in values:
                    member_id = getattr(value, "id")
                    location = getattr(value, "location")
                    require_identifier(member_id, f"process {kind.value} id", location)
                    if member_id in members:
                        raise _error(
                            f"duplicate process {namespace} {member_id!r}; already "
                            f"declared as {members[member_id].value}",
                            location,
                        )
                    members[member_id] = kind

    def _parameters(
        self, owner_id: str, parameters
    ) -> Tuple[Tuple[EventParameterIR, ...], Dict[str, SymbolRefIR]]:
        result = []
        symbols: Dict[str, SymbolRefIR] = {}
        for parameter in parameters:
            require_identifier(parameter.id, "event parameter id", parameter.location)
            if parameter.id in symbols:
                raise _error(
                    f"duplicate event parameter {parameter.id!r}", parameter.location
                )
            value_type = self._type(parameter.value_type)
            result.append(
                EventParameterIR(
                    parameter.id,
                    value_type,
                    parameter.reducer,
                    parameter.location,
                )
            )
            symbols[parameter.id] = SymbolRefIR(
                owner_id,
                parameter.id,
                ExpressionSymbolKind.EVENT_PARAMETER,
                value_type,
            )
        return tuple(result), symbols

    def _key(
        self,
        source: ExpressionAst,
        keys: Mapping[str, ProcessMemberRefIR],
        event_symbols: Mapping[str, SymbolRefIR],
    ) -> ScheduleKeyIR:
        text = source.text.strip()
        if text == "event.id":
            event_id = event_symbols.get("event.id")
            if event_id is None:
                raise _error("event.id is only available inside a handler", source.location)
            return EventIdScheduleKeyIR(
                self._expression(source, EventIdTypeIR(), event_symbols)
            )
        key = keys.get(text)
        if key is None:
            raise _error(
                "schedule key must be event.id or a declared process key",
                source.location,
            )
        return StaticScheduleKeyIR(key)

    def _event_call(
        self,
        source: EventCallAst,
        events: Mapping[str, EventIR],
        symbols: Mapping[str, SymbolRefIR],
    ) -> EventCallIR:
        event = events.get(source.event_id)
        if event is None:
            raise _error(
                f"process event call references unknown event {source.event_id!r}",
                source.location,
            )
        provided = {}
        for argument in source.arguments:
            if argument.parameter_id in provided:
                raise _error(
                    f"duplicate event argument {argument.parameter_id!r}",
                    argument.value.location,
                )
            provided[argument.parameter_id] = argument
        expected = {parameter.id for parameter in event.parameters}
        if set(provided) != expected:
            missing = sorted(expected - set(provided))
            extra = sorted(set(provided) - expected)
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unknown " + ", ".join(extra))
            raise _error(
                f"event {source.event_id!r} arguments do not match: "
                + "; ".join(details),
                source.location,
            )
        arguments = tuple(
            EventArgumentIR(
                parameter.id,
                self._expression(
                    provided[parameter.id].value, parameter.value_type, symbols
                ),
            )
            for parameter in event.parameters
        )
        return EventCallIR(event.ref, arguments, source.location)

    def _effects(
        self,
        sources: Sequence[EffectAst],
        process_id: str,
        base_symbols: Mapping[str, SymbolRefIR],
        states: Mapping[str, StateIR],
        events: Mapping[str, EventIR],
        phases: Mapping[str, ProcessMemberRefIR],
        keys: Mapping[str, ProcessMemberRefIR],
        event_symbols: Mapping[str, SymbolRefIR],
    ) -> Tuple[EffectIR, ...]:
        symbols = dict(base_symbols)
        symbols.update(event_symbols)
        result = []
        for source in sources:
            if isinstance(source, LetEffectAst):
                require_identifier(source.id, "process local id", source.location)
                if source.id in symbols:
                    raise _error(
                        f"process local {source.id!r} shadows a declared value",
                        source.location,
                    )
                value_type = self._type(source.value_type)
                value = self._expression(source.value, value_type, symbols)
                symbol = SymbolRefIR(
                    process_id,
                    source.id,
                    ExpressionSymbolKind.LOCAL,
                    value_type,
                )
                result.append(LetEffectIR(symbol, value, source.location))
                symbols[source.id] = symbol
                continue
            if isinstance(source, NextEffectAst):
                state = states.get(source.state_id)
                if state is None:
                    raise _error(
                        f"next references unknown owned state {source.state_id!r}",
                        source.location,
                    )
                result.append(
                    NextEffectIR(
                        state.ref,
                        self._expression(source.value, state.value_type, symbols),
                        source.location,
                    )
                )
                continue
            if isinstance(source, EmitEffectAst):
                call = self._event_call(source.call, events, symbols)
                event = events[call.event.member_id]
                if event.direction is EventDirection.INPUT:
                    raise _error("a process cannot emit its own input event", source.location)
                phase = None
                if source.phase_id is not None:
                    phase = phases.get(source.phase_id)
                    if phase is None:
                        raise _error(
                            f"emit references unknown phase {source.phase_id!r}",
                            source.location,
                        )
                result.append(EmitEffectIR(call, phase, source.location))
                continue
            if isinstance(source, ScheduleEffectAst):
                call = self._event_call(source.call, events, symbols)
                event = events[call.event.member_id]
                if event.direction is not EventDirection.INTERNAL:
                    raise _error(
                        "only internal events can be scheduled or replaced",
                        source.location,
                    )
                phase = phases.get(source.phase_id)
                if phase is None:
                    raise _error(
                        f"schedule references unknown phase {source.phase_id!r}",
                        source.location,
                    )
                result.append(
                    ScheduleEffectIR(
                        source.operation,
                        call,
                        self._expression(source.delay, self._time, symbols),
                        phase,
                        self._key(source.key, keys, event_symbols),
                        source.location,
                    )
                )
                continue
            if isinstance(source, CancelEffectAst):
                result.append(
                    CancelEffectIR(
                        self._key(source.key, keys, event_symbols),
                        source.location,
                    )
                )
                continue
            if isinstance(source, WhenEffectAst):
                result.append(
                    WhenEffectIR(
                        self._expression(source.condition, self._boolean, symbols),
                        self._effects(
                            source.effects,
                            process_id,
                            symbols,
                            states,
                            events,
                            phases,
                            keys,
                            event_symbols,
                        ),
                        source.location,
                    )
                )
                continue
            if isinstance(source, BranchEffectAst):
                require_identifier(source.id, "process branch id", source.location)
                cases = tuple(
                    ProbabilityCaseIR(
                        self._expression(
                            case.probability, self._probability, symbols
                        ),
                        self._effects(
                            case.effects,
                            process_id,
                            symbols,
                            states,
                            events,
                            phases,
                            keys,
                            event_symbols,
                        ),
                        case.location,
                    )
                    for case in source.cases
                )
                result.append(
                    BranchEffectIR(source.id, source.mode, cases, source.location)
                )
                continue
            raise _error(f"unsupported process effect {type(source).__name__}", None)
        return tuple(result)

    def lower(self, source: ProcessAst) -> ProcessIR:
        require_identifier(source.owner_id, "process owner id", source.location)
        require_identifier(source.id, "process id", source.location)
        process_id = source.qualified_id
        self._register_members(source)
        if len(source.inputs) > MAX_MODEL_INPUTS:
            raise _error(
                f"process exceeds {MAX_MODEL_INPUTS} inputs", source.location
            )

        input_types = {item.id: self._type(item.value_type) for item in source.inputs}
        state_types = {item.id: self._type(item.value_type) for item in source.states}
        base_symbols = dict(self.static_symbols)
        for item in source.inputs:
            base_symbols[item.id] = SymbolRefIR(
                process_id,
                item.id,
                ExpressionSymbolKind.INPUT,
                input_types[item.id],
            )
        inputs = tuple(
            InputIR(
                self._member(process_id, item.id, ProcessMemberKind.INPUT),
                input_types[item.id],
                item.label,
                self._expression(item.default, input_types[item.id], base_symbols)
                if item.default is not None
                else None,
                BoundIR(
                    self._expression(
                        item.bound.minimum, input_types[item.id], base_symbols
                    )
                    if item.bound and item.bound.minimum
                    else None,
                    self._expression(
                        item.bound.maximum, input_types[item.id], base_symbols
                    )
                    if item.bound and item.bound.maximum
                    else None,
                )
                if item.bound
                else None,
                item.location,
            )
            for item in source.inputs
        )
        initial_symbols = dict(base_symbols)
        states = tuple(
            StateIR(
                self._member(process_id, item.id, ProcessMemberKind.STATE),
                state_types[item.id],
                self._expression(item.initial, state_types[item.id], initial_symbols),
                item.label,
                BoundIR(
                    self._expression(
                        item.bound.minimum, state_types[item.id], initial_symbols
                    )
                    if item.bound and item.bound.minimum
                    else None,
                    self._expression(
                        item.bound.maximum, state_types[item.id], initial_symbols
                    )
                    if item.bound and item.bound.maximum
                    else None,
                )
                if item.bound
                else None,
                item.location,
            )
            for item in source.states
        )
        for item in states:
            base_symbols[item.ref.member_id] = SymbolRefIR(
                process_id,
                item.ref.member_id,
                ExpressionSymbolKind.STATE,
                item.value_type,
            )

        keys = {
            item.id: self._member(process_id, item.id, ProcessMemberKind.KEY)
            for item in source.keys
        }
        phases = {
            item.id: self._member(process_id, item.id, ProcessMemberKind.PHASE)
            for item in source.phases
        }

        events: Dict[str, EventIR] = {}
        event_parameter_symbols: Dict[str, Dict[str, SymbolRefIR]] = {}
        for item in source.events:
            parameters, parameter_symbols = self._parameters(
                f"{process_id}.{item.id}", item.parameters
            )
            for parameter in parameters:
                if parameter.reducer is None:
                    continue
                if item.direction is not EventDirection.INPUT:
                    raise _error(
                        "only input event parameters can declare a reducer",
                        parameter.location,
                    )
                numeric = isinstance(parameter.value_type, NumberTypeIR)
                boolean = isinstance(parameter.value_type, BooleanTypeIR)
                if parameter.reducer in {Reducer.SUM, Reducer.MIN, Reducer.MAX} and not numeric:
                    raise _error(
                        f"reducer {parameter.reducer.value} requires a numeric parameter",
                        parameter.location,
                    )
                if parameter.reducer in {Reducer.ALL, Reducer.ANY} and not boolean:
                    raise _error(
                        f"reducer {parameter.reducer.value} requires a boolean parameter",
                        parameter.location,
                    )
            event = EventIR(
                self._member(process_id, item.id, ProcessMemberKind.EVENT),
                item.direction,
                parameters,
                item.location,
            )
            events[item.id] = event
            event_parameter_symbols[item.id] = parameter_symbols

        actions: Dict[str, ActionIR] = {}
        action_parameter_symbols: Dict[str, Dict[str, SymbolRefIR]] = {}
        for item in source.actions:
            parameters, parameter_symbols = self._parameters(
                f"{process_id}.{item.id}", item.parameters
            )
            if any(parameter.reducer is not None for parameter in parameters):
                raise _error(
                    "action parameters cannot declare a reducer", item.location
                )
            if set(parameter_symbols) & set(base_symbols):
                duplicate = sorted(set(parameter_symbols) & set(base_symbols))[0]
                raise _error(
                    f"action parameter {duplicate!r} shadows a process value",
                    item.location,
                )
            guard_symbols = dict(base_symbols)
            guard_symbols.update(parameter_symbols)
            action = ActionIR(
                self._member(process_id, item.id, ProcessMemberKind.ACTION),
                parameters,
                self._expression(item.guard, self._boolean, guard_symbols)
                if item.guard is not None
                else None,
                item.location,
            )
            actions[item.id] = action
            action_parameter_symbols[item.id] = parameter_symbols

        requirements = tuple(
            self._expression(item, self._boolean, initial_symbols)
            for item in source.requirements
        )
        state_map = {item.ref.member_id: item for item in states}
        flows = []
        seen_flows: Set[str] = set()
        for item in source.flows:
            state = state_map.get(item.state_id)
            if state is None:
                raise _error(
                    f"flow references unknown owned state {item.state_id!r}",
                    item.location,
                )
            if not isinstance(state.value_type, NumberTypeIR):
                raise _error("flow state must be numeric", item.location)
            if item.state_id in seen_flows:
                raise _error(
                    f"state {item.state_id!r} declares more than one flow",
                    item.location,
                )
            if item.current_id == item.elapsed_id or {
                item.current_id,
                item.elapsed_id,
            } & set(base_symbols):
                raise _error("flow local names must be distinct and cannot shadow values", item.location)
            current = SymbolRefIR(
                f"{process_id}.flow.{item.state_id}",
                item.current_id,
                ExpressionSymbolKind.LOCAL,
                state.value_type,
            )
            elapsed = SymbolRefIR(
                f"{process_id}.flow.{item.state_id}",
                item.elapsed_id,
                ExpressionSymbolKind.LOCAL,
                self._time,
            )
            flow_symbols = dict(base_symbols)
            flow_symbols[item.current_id] = current
            flow_symbols[item.elapsed_id] = elapsed
            flows.append(
                FlowIR(
                    state.ref,
                    current,
                    elapsed,
                    self._expression(item.value, state.value_type, flow_symbols),
                    item.location,
                )
            )
            seen_flows.add(item.state_id)

        handlers = []
        event_context = {
            "event.id": SymbolRefIR(
                process_id,
                "event.id",
                ExpressionSymbolKind.EVENT_CONTEXT,
                EventIdTypeIR(),
            ),
            "event.time": SymbolRefIR(
                process_id,
                "event.time",
                ExpressionSymbolKind.EVENT_CONTEXT,
                self._time,
            ),
        }
        for item in source.handlers:
            if item.trigger_id in events:
                trigger = events[item.trigger_id].ref
                if events[item.trigger_id].direction is EventDirection.OUTPUT:
                    raise _error("output events cannot have process handlers", item.location)
                parameter_symbols = event_parameter_symbols[item.trigger_id]
                expected_bindings = tuple(
                    parameter.id for parameter in events[item.trigger_id].parameters
                )
            elif item.trigger_id in actions:
                trigger = actions[item.trigger_id].ref
                parameter_symbols = action_parameter_symbols[item.trigger_id]
                expected_bindings = tuple(
                    parameter.id for parameter in actions[item.trigger_id].parameters
                )
            else:
                raise _error(
                    f"handler references unknown event or action {item.trigger_id!r}",
                    item.location,
                )
            if item.parameter_bindings != expected_bindings:
                raise _error(
                    f"handler parameters for {item.trigger_id!r} must be "
                    + ", ".join(expected_bindings),
                    item.location,
                )
            duplicate = set(parameter_symbols) & set(base_symbols)
            if duplicate:
                raise _error(
                    f"handler parameter {sorted(duplicate)[0]!r} shadows a process value",
                    item.location,
                )
            handler_symbols = dict(base_symbols)
            handler_symbols.update(parameter_symbols)
            handler_symbols.update(event_context)
            handlers.append(
                HandlerIR(
                    trigger,
                    tuple(parameter_symbols[name] for name in expected_bindings),
                    self._expression(item.guard, self._boolean, handler_symbols)
                    if item.guard is not None
                    else None,
                    self._effects(
                        item.effects,
                        process_id,
                        handler_symbols,
                        state_map,
                        events,
                        phases,
                        keys,
                        event_context,
                    ),
                    item.location,
                )
            )

        observations = tuple(
            ObservationIR(
                self._member(
                    process_id, item.id, ProcessMemberKind.OBSERVATION
                ),
                self._type(item.value_type),
                self._expression(
                    item.value, self._type(item.value_type), base_symbols
                ),
                item.label,
                item.location,
            )
            for item in source.observations
        )
        return ProcessIR(
            source.owner_id,
            source.id,
            source.label,
            inputs,
            states,
            requirements,
            tuple(KeyIR(keys[item.id], item.location) for item in source.keys),
            tuple(PhaseIR(phases[item.id], item.location) for item in source.phases),
            tuple(events[item.id] for item in source.events),
            tuple(actions[item.id] for item in source.actions),
            tuple(flows),
            tuple(handlers),
            observations,
            location=source.location,
        )


def lower_process_asts(
    sources: Sequence[ProcessAst],
    registry: UnitRegistry,
    *,
    object_types: Iterable[str] = (),
    static_symbols: Optional[Mapping[str, SymbolRefIR]] = None,
) -> Tuple[ProcessIR, ...]:
    """Lower a set of process declarations and reject duplicate canonical IDs."""

    seen = set()
    result = []
    lowerer = ProcessLowerer(
        registry, object_types=object_types, static_symbols=static_symbols
    )
    for source in sources:
        if source.qualified_id in seen:
            raise _error(
                f"duplicate process {source.qualified_id!r}", source.location
            )
        seen.add(source.qualified_id)
        result.append(lowerer.lower(source))
    return tuple(result)
