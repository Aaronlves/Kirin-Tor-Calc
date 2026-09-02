"""Parser for bounded ``process`` blocks inside a Kirin Tor source document."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple

from .errors import SourceLocation
from .kirin_v2 import IDENTIFIER, PATH, QUOTED, _Node, _decode, _nodes, _parse_header
from .limits import (
    MAX_PROCESS_DECLARATIONS,
    MAX_PROCESS_EFFECT_DEPTH,
    MAX_PROCESS_EFFECTS,
    MAX_PROCESSES_PER_ENTRY,
)
from .process_ast import (
    ActionAst,
    BoundAst,
    BranchEffectAst,
    CancelEffectAst,
    EffectAst,
    EmitEffectAst,
    EventArgumentAst,
    EventAst,
    EventCallAst,
    EventParameterAst,
    ExpressionAst,
    FlowAst,
    HandlerAst,
    InputAst,
    KeyAst,
    LetEffectAst,
    NextEffectAst,
    ObservationAst,
    PhaseAst,
    ProbabilityCaseAst,
    ProcessAst,
    ScheduleEffectAst,
    StateAst,
    TypeAst,
    WhenEffectAst,
)
from .process_model import BranchMode, EventDirection, Reducer, ScheduleOperation


_PROCESS_HEADER_RE = re.compile(
    rf"^process\s+(?P<id>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?:$"
)
_TYPED_DECLARATION_RE = re.compile(
    rf"^(?P<id>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?\s*:\s*"
    r"(?P<body>.+)$"
)
_EVENT_RE = re.compile(
    rf"^event\s+(?P<direction>input|output|internal)\s+"
    rf"(?P<id>{IDENTIFIER})\((?P<parameters>.*)\)$"
)
_ACTION_RE = re.compile(
    rf"^action\s+(?P<id>{IDENTIFIER})\((?P<parameters>.*?)\)"
    r"(?:\s+when\s+(?P<guard>.+))?$"
)
_HANDLER_RE = re.compile(
    rf"^on\s+(?P<id>{IDENTIFIER})\((?P<parameters>.*?)\)"
    r"(?:\s+when\s+(?P<guard>.+))?:$"
)
_FLOW_RE = re.compile(
    rf"^flow\s+(?P<state>{IDENTIFIER})\("
    rf"(?P<current>{IDENTIFIER})\s*,\s*(?P<elapsed>{IDENTIFIER})\)"
    r"\s*=\s*(?P<value>.+)$"
)
_LET_RE = re.compile(
    rf"^let\s+(?P<id>{IDENTIFIER})\s*:\s*(?P<type>[^\s=]+)\s*=\s*(?P<value>.+)$"
)
_NEXT_EFFECT_RE = re.compile(
    rf"^next\s+(?P<state>{IDENTIFIER})\s*=\s*(?P<value>.+)$"
)
_SCHEDULE_RE = re.compile(
    r"^(?P<operation>schedule|replace)\s+(?P<call>.+)\s+after\s+"
    rf"(?P<delay>.+)\s+phase\s+(?P<phase>{IDENTIFIER})\s+key\s+(?P<key>.+)$"
)


def _location(
    path: Path, owner_id: str, node: _Node, field: Optional[str] = None
) -> SourceLocation:
    return SourceLocation(
        path=str(path),
        entry_id=owner_id,
        field=field,
        line=node.line.number,
        column=node.line.indent + 1,
    )


def _fail(
    path: Path,
    owner_id: str,
    node: _Node,
    message: str,
    field: Optional[str] = None,
) -> None:
    from .errors import SchemaError

    raise SchemaError(message, _location(path, owner_id, node, field))


def _expression(
    node: _Node,
    initial: str,
    path: Path,
    owner_id: str,
    field: str,
) -> ExpressionAst:
    parts = [initial.strip()]
    for child in node.children:
        if child.children:
            _fail(
                path,
                owner_id,
                child,
                "expression continuation may not contain a nested block",
                field,
            )
        parts.append(child.line.text.strip())
    text = " ".join(part for part in parts if part)
    if not text:
        _fail(path, owner_id, node, "expression may not be empty", field)
    return ExpressionAst(text, _location(path, owner_id, node, field))


def _split_top_level(
    text: str, path: Path, owner_id: str, node: _Node, field: str
) -> Tuple[str, ...]:
    if not text.strip():
        return ()
    result: List[str] = []
    start = 0
    square_depth = 0
    round_depth = 0
    quoted = False
    escaped = False
    for index, character in enumerate(text):
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
        elif character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "," and square_depth == 0 and round_depth == 0:
            item = text[start:index].strip()
            if not item:
                _fail(path, owner_id, node, "list contains an empty item", field)
            result.append(item)
            start = index + 1
        if square_depth < 0 or round_depth < 0:
            _fail(path, owner_id, node, "unmatched closing bracket", field)
    if quoted or square_depth or round_depth:
        _fail(path, owner_id, node, "unmatched quote or bracket", field)
    final = text[start:].strip()
    if not final:
        _fail(path, owner_id, node, "list contains an empty item", field)
    result.append(final)
    return tuple(result)


def _type(
    text: str, path: Path, owner_id: str, node: _Node, field: str
) -> TypeAst:
    text = text.strip()
    location = _location(path, owner_id, node, field)
    if "[" not in text:
        if not re.fullmatch(PATH, text) and text not in {"boolean", "event_id"}:
            _fail(path, owner_id, node, f"invalid process type {text!r}", field)
        return TypeAst(text, location=location)
    name, separator, arguments_text = text.partition("[")
    if not separator or not arguments_text.endswith("]") or not re.fullmatch(IDENTIFIER, name):
        _fail(path, owner_id, node, f"invalid process type {text!r}", field)
    arguments = _split_top_level(
        arguments_text[:-1], path, owner_id, node, field
    )
    if name == "number" and len(arguments) == 1:
        return TypeAst(
            name,
            (_type(arguments[0], path, owner_id, node, field),),
            location=location,
        )
    if name == "list" and len(arguments) == 2:
        try:
            capacity = int(arguments[1])
        except ValueError:
            _fail(path, owner_id, node, "list capacity must be an integer literal", field)
        return TypeAst(
            name,
            (_type(arguments[0], path, owner_id, node, field),),
            capacity,
            location,
        )
    if name == "map" and len(arguments) == 3:
        try:
            capacity = int(arguments[2])
        except ValueError:
            _fail(path, owner_id, node, "map capacity must be an integer literal", field)
        return TypeAst(
            name,
            (
                _type(arguments[0], path, owner_id, node, field),
                _type(arguments[1], path, owner_id, node, field),
            ),
            capacity,
            location,
        )
    _fail(path, owner_id, node, f"unsupported process type {text!r}", field)
    raise AssertionError("unreachable")


def _bound(
    tail: str, path: Path, owner_id: str, node: _Node, field: str
) -> Tuple[str, Optional[BoundAst]]:
    marker = 0 if tail.startswith("in ") else tail.rfind(" in ")
    if marker < 0:
        return tail.strip(), None
    bound_text = tail[marker + (3 if marker == 0 else 4) :].strip()
    if bound_text.count("..") != 1:
        return tail.strip(), None
    minimum, maximum = (part.strip() for part in bound_text.split("..", 1))
    if not minimum or not maximum:
        _fail(path, owner_id, node, "process range requires both endpoints", field)
    return (
        tail[:marker].strip(),
        BoundAst(
            ExpressionAst(
                minimum, _location(path, owner_id, node, field + ".minimum")
            ),
            ExpressionAst(
                maximum, _location(path, owner_id, node, field + ".maximum")
            ),
        ),
    )


def _type_and_tail(
    body: str, path: Path, owner_id: str, node: _Node, field: str
) -> Tuple[TypeAst, str]:
    body = body.strip()
    square_depth = 0
    type_end = len(body)
    for index, character in enumerate(body):
        if character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
            if square_depth < 0:
                _fail(path, owner_id, node, "process type has an unmatched ']'", field)
        elif square_depth == 0 and (character.isspace() or character == "="):
            type_end = index
            break
    if square_depth:
        _fail(path, owner_id, node, "process type has an unmatched '['", field)
    type_text = body[:type_end].strip()
    tail = body[type_end:].strip()
    return _type(type_text, path, owner_id, node, field), tail


def _typed_declaration(
    text: str, path: Path, owner_id: str, node: _Node, field: str
) -> Tuple[str, Optional[str], TypeAst, str]:
    match = _TYPED_DECLARATION_RE.fullmatch(text)
    if not match:
        _fail(path, owner_id, node, "typed declaration must use ID [\"LABEL\"]: TYPE", field)
    label = _decode(match.group("label"), path, node.line) if match.group("label") else None
    value_type, tail = _type_and_tail(
        match.group("body"), path, owner_id, node, field + ".type"
    )
    return (
        match.group("id"),
        label,
        value_type,
        tail,
    )


def _parameters(
    text: str,
    path: Path,
    owner_id: str,
    node: _Node,
    field: str,
    *,
    allow_reducer: bool,
) -> Tuple[EventParameterAst, ...]:
    result = []
    for item in _split_top_level(text, path, owner_id, node, field):
        match = re.fullmatch(
            rf"(?P<id>{IDENTIFIER})\s*:\s*(?P<body>.+)",
            item,
        )
        if not match:
            _fail(path, owner_id, node, "event parameter must use ID: TYPE [reduce REDUCER]", field)
        value_type, tail = _type_and_tail(
            match.group("body"), path, owner_id, node, field + ".type"
        )
        reducer_match = re.fullmatch(r"reduce\s+(sum|min|max|all|any)", tail)
        if tail and not reducer_match:
            _fail(path, owner_id, node, "event parameter tail must use reduce REDUCER", field)
        reducer = Reducer(reducer_match.group(1)) if reducer_match else None
        if reducer is not None and not allow_reducer:
            _fail(path, owner_id, node, "action parameters cannot declare a reducer", field)
        result.append(
            EventParameterAst(
                match.group("id"),
                value_type,
                reducer,
                _location(path, owner_id, node, field),
            )
        )
    return tuple(result)


def _event_call(
    text: str, path: Path, owner_id: str, node: _Node, field: str
) -> EventCallAst:
    match = re.fullmatch(rf"(?P<id>{IDENTIFIER})\((?P<arguments>.*)\)", text.strip())
    if not match:
        _fail(path, owner_id, node, "event call must use EVENT(ARGUMENTS)", field)
    arguments = []
    for item in _split_top_level(match.group("arguments"), path, owner_id, node, field):
        assignment = re.fullmatch(rf"(?P<id>{IDENTIFIER})\s*=\s*(?P<value>.+)", item)
        if not assignment:
            _fail(path, owner_id, node, "event arguments must use PARAMETER = VALUE", field)
        arguments.append(
            EventArgumentAst(
                assignment.group("id"),
                ExpressionAst(
                    assignment.group("value").strip(),
                    _location(path, owner_id, node, field),
                ),
            )
        )
    return EventCallAst(
        match.group("id"), tuple(arguments), _location(path, owner_id, node, field)
    )


def _effects(
    nodes: Tuple[_Node, ...],
    path: Path,
    owner_id: str,
    field: str,
    *,
    depth: int = 0,
    counter: Optional[List[int]] = None,
) -> Tuple[EffectAst, ...]:
    if depth > MAX_PROCESS_EFFECT_DEPTH:
        anchor = nodes[0] if nodes else None
        if anchor is not None:
            _fail(
                path,
                owner_id,
                anchor,
                f"process effects exceed nesting depth {MAX_PROCESS_EFFECT_DEPTH}",
                field,
            )
    counter = counter if counter is not None else [0]
    result: List[EffectAst] = []
    for index, node in enumerate(nodes):
        counter[0] += 1
        if counter[0] > MAX_PROCESS_EFFECTS:
            _fail(
                path,
                owner_id,
                node,
                f"process exceeds {MAX_PROCESS_EFFECTS} effects",
                field,
            )
        effect_field = f"{field}.{index}"
        text = node.line.text
        location = _location(path, owner_id, node, effect_field)
        let = _LET_RE.fullmatch(text)
        if let:
            if node.children:
                _fail(path, owner_id, node, "let effect cannot contain a block", effect_field)
            result.append(
                LetEffectAst(
                    let.group("id"),
                    _type(let.group("type"), path, owner_id, node, effect_field + ".type"),
                    _expression(node, let.group("value"), path, owner_id, effect_field + ".value"),
                    location,
                )
            )
            continue
        next_effect = _NEXT_EFFECT_RE.fullmatch(text)
        if next_effect:
            result.append(
                NextEffectAst(
                    next_effect.group("state"),
                    _expression(
                        node,
                        next_effect.group("value"),
                        path,
                        owner_id,
                        effect_field + ".value",
                    ),
                    location,
                )
            )
            continue
        if text.startswith("emit "):
            body = text[len("emit ") :]
            phase_id = None
            before_phase, separator, phase = body.rpartition(" phase ")
            if separator and re.fullmatch(IDENTIFIER, phase):
                body = before_phase
                phase_id = phase
            if node.children:
                _fail(path, owner_id, node, "emit effect cannot contain a block", effect_field)
            result.append(
                EmitEffectAst(
                    _event_call(body, path, owner_id, node, effect_field + ".call"),
                    phase_id,
                    location,
                )
            )
            continue
        schedule = _SCHEDULE_RE.fullmatch(text)
        if schedule:
            if node.children:
                _fail(path, owner_id, node, "scheduled effect cannot contain a block", effect_field)
            result.append(
                ScheduleEffectAst(
                    ScheduleOperation(schedule.group("operation")),
                    _event_call(
                        schedule.group("call"), path, owner_id, node, effect_field + ".call"
                    ),
                    _expression(
                        node,
                        schedule.group("delay"),
                        path,
                        owner_id,
                        effect_field + ".delay",
                    ),
                    schedule.group("phase"),
                    _expression(
                        node,
                        schedule.group("key"),
                        path,
                        owner_id,
                        effect_field + ".key",
                    ),
                    location,
                )
            )
            continue
        if text.startswith("cancel "):
            if node.children:
                _fail(path, owner_id, node, "cancel effect cannot contain a block", effect_field)
            result.append(
                CancelEffectAst(
                    _expression(
                        node,
                        text[len("cancel ") :],
                        path,
                        owner_id,
                        effect_field + ".key",
                    ),
                    location,
                )
            )
            continue
        when = re.fullmatch(r"when\s+(.+):", text)
        if when:
            if not node.children:
                _fail(path, owner_id, node, "when effect must contain effects", effect_field)
            result.append(
                WhenEffectAst(
                    ExpressionAst(when.group(1), location),
                    _effects(
                        node.children,
                        path,
                        owner_id,
                        effect_field + ".effects",
                        depth=depth + 1,
                        counter=counter,
                    ),
                    location,
                )
            )
            continue
        branch = re.fullmatch(
            rf"branch\s+({IDENTIFIER})\s+(independent|joint):", text
        )
        if branch:
            cases = []
            for case_index, case in enumerate(node.children):
                probability = re.fullmatch(r"probability\s+(.+):", case.line.text)
                if not probability:
                    _fail(
                        path,
                        owner_id,
                        case,
                        "branch cases must use probability EXPRESSION:",
                        effect_field,
                    )
                cases.append(
                    ProbabilityCaseAst(
                        ExpressionAst(
                            probability.group(1),
                            _location(path, owner_id, case, effect_field + ".probability"),
                        ),
                        _effects(
                            case.children,
                            path,
                            owner_id,
                            f"{effect_field}.cases.{case_index}",
                            depth=depth + 1,
                            counter=counter,
                        ),
                        _location(path, owner_id, case, effect_field),
                    )
                )
            if not cases:
                _fail(path, owner_id, node, "branch must contain probability cases", effect_field)
            result.append(
                BranchEffectAst(
                    branch.group(1),
                    BranchMode(branch.group(2)),
                    tuple(cases),
                    location,
                )
            )
            continue
        _fail(path, owner_id, node, f"unknown process effect: {text}", effect_field)
    return tuple(result)


def _parse_process(node: _Node, path: Path, owner_id: str) -> ProcessAst:
    header = _PROCESS_HEADER_RE.fullmatch(node.line.text)
    if not header:
        _fail(path, owner_id, node, 'process must use process ID ["LABEL"]:', "processes")
    process_id = header.group("id")
    process_field = f"processes.{process_id}"
    label = _decode(header.group("label"), path, node.line) if header.group("label") else None
    inputs = []
    states = []
    requirements = []
    keys = []
    phases = []
    events = []
    actions = []
    flows = []
    handlers = []
    observations = []
    declarations = 0

    for child in node.children:
        declarations += 1
        if declarations > MAX_PROCESS_DECLARATIONS:
            _fail(
                path,
                owner_id,
                child,
                f"process exceeds {MAX_PROCESS_DECLARATIONS} declarations",
                process_field,
            )
        text = child.line.text
        if text.startswith("input "):
            if child.children:
                _fail(path, owner_id, child, "process input cannot contain a block", process_field)
            item_id, item_label, value_type, tail = _typed_declaration(
                text[len("input ") :], path, owner_id, child, process_field + ".inputs"
            )
            tail, bound = _bound(
                tail, path, owner_id, child, process_field + f".inputs.{item_id}"
            )
            default = None
            if tail:
                if not tail.startswith("=") or not tail[1:].strip():
                    _fail(path, owner_id, child, "process input tail must use = DEFAULT and/or in MIN..MAX", process_field)
                default = _expression(
                    child,
                    tail[1:],
                    path,
                    owner_id,
                    process_field + f".inputs.{item_id}.default",
                )
            location = _location(
                path, owner_id, child, process_field + f".inputs.{item_id}"
            )
            inputs.append(InputAst(item_id, value_type, item_label, default, bound, location))
            continue
        if text.startswith("state "):
            item_id, item_label, value_type, tail = _typed_declaration(
                text[len("state ") :], path, owner_id, child, process_field + ".states"
            )
            tail, bound = _bound(
                tail, path, owner_id, child, process_field + f".states.{item_id}"
            )
            if not tail.startswith("=") or not tail[1:].strip():
                _fail(path, owner_id, child, "process state requires = INITIAL", process_field)
            initial = _expression(
                child,
                tail[1:],
                path,
                owner_id,
                process_field + f".states.{item_id}.initial",
            )
            location = _location(
                path, owner_id, child, process_field + f".states.{item_id}"
            )
            states.append(StateAst(item_id, value_type, initial, item_label, bound, location))
            continue
        if text.startswith("require "):
            requirements.append(
                _expression(
                    child,
                    text[len("require ") :],
                    path,
                    owner_id,
                    process_field + f".requirements.{len(requirements)}",
                )
            )
            continue
        key = re.fullmatch(rf"key\s+({IDENTIFIER})", text)
        if key and not child.children:
            keys.append(
                KeyAst(
                    key.group(1),
                    _location(
                        path,
                        owner_id,
                        child,
                        process_field + f".keys.{key.group(1)}",
                    ),
                )
            )
            continue
        phase = re.fullmatch(rf"phase\s+({IDENTIFIER})", text)
        if phase and not child.children:
            phases.append(
                PhaseAst(
                    phase.group(1),
                    _location(
                        path,
                        owner_id,
                        child,
                        process_field + f".phases.{phase.group(1)}",
                    ),
                )
            )
            continue
        event = _EVENT_RE.fullmatch(text)
        if event and not child.children:
            direction = EventDirection(event.group("direction"))
            location = _location(
                path,
                owner_id,
                child,
                process_field + f".events.{event.group('id')}",
            )
            events.append(
                EventAst(
                    event.group("id"),
                    direction,
                    _parameters(
                        event.group("parameters"),
                        path,
                        owner_id,
                        child,
                        process_field + f".events.{event.group('id')}",
                        allow_reducer=direction is EventDirection.INPUT,
                    ),
                    location,
                )
            )
            continue
        action = _ACTION_RE.fullmatch(text)
        if action and not child.children:
            location = _location(
                path,
                owner_id,
                child,
                process_field + f".actions.{action.group('id')}",
            )
            guard = (
                ExpressionAst(action.group("guard"), location)
                if action.group("guard")
                else None
            )
            actions.append(
                ActionAst(
                    action.group("id"),
                    _parameters(
                        action.group("parameters"),
                        path,
                        owner_id,
                        child,
                        process_field + f".actions.{action.group('id')}",
                        allow_reducer=False,
                    ),
                    guard,
                    location,
                )
            )
            continue
        flow = _FLOW_RE.fullmatch(text)
        if flow:
            location = _location(
                path,
                owner_id,
                child,
                process_field + f".flows.{flow.group('state')}",
            )
            flows.append(
                FlowAst(
                    flow.group("state"),
                    flow.group("current"),
                    flow.group("elapsed"),
                    _expression(
                        child,
                        flow.group("value"),
                        path,
                        owner_id,
                        process_field + f".flows.{flow.group('state')}",
                    ),
                    location,
                )
            )
            continue
        handler = _HANDLER_RE.fullmatch(text)
        if handler:
            handler_index = len(handlers)
            location = _location(
                path,
                owner_id,
                child,
                process_field + f".handlers.{handler_index}",
            )
            bindings = _split_top_level(
                handler.group("parameters"),
                path,
                owner_id,
                child,
                process_field + ".handlers",
            )
            if any(not re.fullmatch(IDENTIFIER, binding) for binding in bindings):
                _fail(path, owner_id, child, "handler parameters must be identifiers", process_field)
            handlers.append(
                HandlerAst(
                    handler.group("id"),
                    bindings,
                    ExpressionAst(handler.group("guard"), location)
                    if handler.group("guard")
                    else None,
                    _effects(
                        child.children,
                        path,
                        owner_id,
                        process_field + f".handlers.{handler_index}.effects",
                    ),
                    location,
                )
            )
            continue
        if text.startswith("observe "):
            item_id, item_label, value_type, tail = _typed_declaration(
                text[len("observe ") :],
                path,
                owner_id,
                child,
                process_field + ".observations",
            )
            if not tail.startswith("=") or not tail[1:].strip():
                _fail(path, owner_id, child, "process observation requires = EXPRESSION", process_field)
            location = _location(
                path,
                owner_id,
                child,
                process_field + f".observations.{item_id}",
            )
            observations.append(
                ObservationAst(
                    item_id,
                    value_type,
                    _expression(
                        child,
                        tail[1:],
                        path,
                        owner_id,
                        process_field + f".observations.{item_id}",
                    ),
                    item_label,
                    location,
                )
            )
            continue
        _fail(path, owner_id, child, f"unknown process declaration: {text}", process_field)

    return ProcessAst(
        owner_id,
        process_id,
        label,
        tuple(inputs),
        tuple(states),
        tuple(requirements),
        tuple(keys),
        tuple(phases),
        tuple(events),
        tuple(actions),
        tuple(flows),
        tuple(handlers),
        tuple(observations),
        _location(path, owner_id, node, process_field),
    )


def parse_process_asts(text: str, path: Path) -> Tuple[ProcessAst, ...]:
    """Parse only top-level process blocks from one complete Kirin document."""

    owner_id, _name, _description, remaining, _metadata, _positions = _parse_header(
        text, path
    )
    result = []
    for node in _nodes(remaining, path):
        if not node.line.text.startswith("process "):
            continue
        result.append(_parse_process(node, path, owner_id))
        if len(result) > MAX_PROCESSES_PER_ENTRY:
            _fail(
                path,
                owner_id,
                node,
                f"entry exceeds {MAX_PROCESSES_PER_ENTRY} processes",
                "processes",
            )
    return tuple(result)
