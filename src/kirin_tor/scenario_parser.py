"""Parser for typed ``scenario`` and ``analysis`` declarations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .errors import SchemaError, SourceLocation
from .kirin_v2 import IDENTIFIER, PATH, QUOTED, _Node, _decode, _nodes, _parse_header
from .limits import (
    MAX_SCENARIO_ACTIONS,
    MAX_SCENARIO_INSTANCES,
    MAX_SCENARIO_PHASES,
    MAX_SCENARIO_SCHEDULES,
)
from .process_ast import EventArgumentAst, EventCallAst, ExpressionAst
from .process_parser import _split_top_level
from .scenario_ast import (
    AnalysisAst,
    AtScheduleAst,
    CompositeActionAst,
    ConnectionAst,
    DecisionScheduleAst,
    EventEndpointAst,
    EveryScheduleAst,
    InstanceInputAst,
    InstancePhaseAst,
    PolicyAst,
    PolicyRuleAst,
    ProcessInstanceAst,
    ScenarioAst,
    ScenarioBoundsAst,
    ScenarioPhaseAst,
    ScenarioSendAst,
)


_SCENARIO_HEADER = re.compile(
    rf"^scenario\s+(?P<id>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?:$"
)
_ANALYSIS_HEADER = re.compile(
    rf"^analysis\s+(?P<id>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?:$"
)
_EVERY = re.compile(
    rf"^every\s+(?P<interval>.+?)\s+from\s+(?P<start>.+?)"
    rf"(?:\s+until\s+(?P<end>.+?))?\s+phase\s+(?P<phase>{IDENTIFIER}):$"
)
_DECIDE = re.compile(
    rf"^decide\s+every\s+(?P<interval>.+?)\s+from\s+(?P<start>.+?)"
    rf"(?:\s+until\s+(?P<end>.+?))?\s+phase\s+(?P<phase>{IDENTIFIER}):$"
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
    path: Path, owner_id: str, node: _Node, message: str, field: Optional[str] = None
) -> None:
    raise SchemaError(message, _location(path, owner_id, node, field))


def _expr(path: Path, owner_id: str, node: _Node, text: str, field: str) -> ExpressionAst:
    if node.children:
        _fail(path, owner_id, node, "expression line cannot contain a nested block", field)
    text = text.strip()
    if not text:
        _fail(path, owner_id, node, "expression may not be empty", field)
    return ExpressionAst(text, _location(path, owner_id, node, field))


def _endpoint(
    text: str, path: Path, owner_id: str, node: _Node, field: str
) -> EventEndpointAst:
    match = re.fullmatch(rf"({IDENTIFIER})\.({IDENTIFIER})", text.strip())
    if not match:
        _fail(path, owner_id, node, "event endpoint must use INSTANCE.EVENT", field)
    return EventEndpointAst(
        match.group(1), match.group(2), _location(path, owner_id, node, field)
    )


def _send(
    node: _Node,
    path: Path,
    owner_id: str,
    field: str,
    *,
    default_phase: Optional[str] = None,
) -> ScenarioSendAst:
    if node.children or not node.line.text.startswith("send "):
        _fail(path, owner_id, node, "scenario event must use send INSTANCE.EVENT(ARGUMENTS)", field)
    body = node.line.text[len("send ") :]
    phase_id = default_phase
    before_phase, separator, candidate = body.rpartition(" phase ")
    if separator and re.fullmatch(IDENTIFIER, candidate):
        body = before_phase
        if default_phase is not None and candidate != default_phase:
            _fail(
                path,
                owner_id,
                node,
                "scheduled send phase must match its containing schedule",
                field,
            )
        phase_id = candidate
    match = re.fullmatch(
        rf"(?P<instance>{IDENTIFIER})\.(?P<event>{IDENTIFIER})\((?P<arguments>.*)\)",
        body.strip(),
    )
    if not match:
        _fail(path, owner_id, node, "scenario event must use INSTANCE.EVENT(ARGUMENTS)", field)
    arguments = []
    for item in _split_top_level(match.group("arguments"), path, owner_id, node, field):
        assignment = re.fullmatch(rf"({IDENTIFIER})\s*=\s*(.+)", item)
        if not assignment:
            _fail(path, owner_id, node, "event arguments must use PARAMETER = VALUE", field)
        arguments.append(
            EventArgumentAst(
                assignment.group(1),
                ExpressionAst(
                    assignment.group(2).strip(),
                    _location(path, owner_id, node, field),
                ),
            )
        )
    location = _location(path, owner_id, node, field)
    return ScenarioSendAst(
        match.group("instance"),
        EventCallAst(match.group("event"), tuple(arguments), location),
        phase_id,
        location,
    )


def _sends(
    nodes: Tuple[_Node, ...],
    path: Path,
    owner_id: str,
    field: str,
    *,
    default_phase: Optional[str] = None,
) -> Tuple[ScenarioSendAst, ...]:
    if not nodes:
        raise SchemaError(f"{field} must contain at least one send")
    return tuple(
        _send(
            node,
            path,
            owner_id,
            f"{field}.{index}",
            default_phase=default_phase,
        )
        for index, node in enumerate(nodes)
    )


def _parse_scenario(node: _Node, path: Path, owner_id: str) -> ScenarioAst:
    header = _SCENARIO_HEADER.fullmatch(node.line.text)
    if not header:
        _fail(path, owner_id, node, 'scenario must use scenario ID ["LABEL"]:', "scenarios")
    scenario_id = header.group("id")
    base = f"scenarios.{scenario_id}"
    label = _decode(header.group("label"), path, node.line) if header.group("label") else None
    phases: List[ScenarioPhaseAst] = []
    instances: List[ProcessInstanceAst] = []
    connections: List[ConnectionAst] = []
    schedules: List[object] = []
    actions: List[CompositeActionAst] = []
    policies: List[PolicyAst] = []
    decisions: List[DecisionScheduleAst] = []
    stop = None
    bounds = None

    for index, child in enumerate(node.children):
        text = child.line.text
        field = f"{base}.{index}"
        if text == "phases:":
            if phases:
                _fail(path, owner_id, child, "scenario phases may be declared only once", field)
            for phase_node in child.children:
                match = re.fullmatch(rf"-\s+({IDENTIFIER})", phase_node.line.text)
                if not match or phase_node.children:
                    _fail(path, owner_id, phase_node, "scenario phase must use - PHASE", field)
                phases.append(
                    ScenarioPhaseAst(match.group(1), _location(path, owner_id, phase_node, field))
                )
            if not phases:
                _fail(path, owner_id, child, "scenario must declare at least one phase", field)
            if len(phases) > MAX_SCENARIO_PHASES:
                _fail(path, owner_id, child, f"scenario exceeds {MAX_SCENARIO_PHASES} phases", field)
            continue
        use = re.fullmatch(rf"use\s+({IDENTIFIER})\s*=\s*({PATH}):", text)
        if use:
            input_bindings = []
            phase_bindings = []
            for binding in child.children:
                phase = re.fullmatch(
                    rf"phase\s+({IDENTIFIER})\s*=\s*({IDENTIFIER})", binding.line.text
                )
                if phase:
                    phase_bindings.append(
                        InstancePhaseAst(
                            phase.group(1),
                            phase.group(2),
                            _location(path, owner_id, binding, field),
                        )
                    )
                    continue
                value = re.fullmatch(rf"({IDENTIFIER})\s*=\s*(.+)", binding.line.text)
                if not value:
                    _fail(path, owner_id, binding, "instance binding must use INPUT = VALUE or phase LOCAL = GLOBAL", field)
                input_bindings.append(
                    InstanceInputAst(
                        value.group(1),
                        _expr(path, owner_id, binding, value.group(2), field),
                        _location(path, owner_id, binding, field),
                    )
                )
            instances.append(
                ProcessInstanceAst(
                    use.group(1),
                    use.group(2),
                    tuple(input_bindings),
                    tuple(phase_bindings),
                    _location(path, owner_id, child, field),
                )
            )
            if len(instances) > MAX_SCENARIO_INSTANCES:
                _fail(path, owner_id, child, f"scenario exceeds {MAX_SCENARIO_INSTANCES} instances", field)
            continue
        connect = re.fullmatch(r"connect\s+(.+?)\s*->\s*(.+)", text)
        if connect:
            if child.children:
                _fail(path, owner_id, child, "connect cannot contain a block", field)
            connections.append(
                ConnectionAst(
                    _endpoint(connect.group(1), path, owner_id, child, field),
                    _endpoint(connect.group(2), path, owner_id, child, field),
                    _location(path, owner_id, child, field),
                )
            )
            continue
        at = re.fullmatch(rf"at\s+(.+?)\s+phase\s+({IDENTIFIER}):", text)
        if at:
            schedules.append(
                AtScheduleAst(
                    ExpressionAst(at.group(1), _location(path, owner_id, child, field)),
                    at.group(2),
                    _sends(child.children, path, owner_id, field, default_phase=at.group(2)),
                    _location(path, owner_id, child, field),
                )
            )
            continue
        every = _EVERY.fullmatch(text)
        if every:
            schedules.append(
                EveryScheduleAst(
                    ExpressionAst(every.group("interval"), _location(path, owner_id, child, field)),
                    ExpressionAst(every.group("start"), _location(path, owner_id, child, field)),
                    ExpressionAst(every.group("end"), _location(path, owner_id, child, field))
                    if every.group("end")
                    else None,
                    every.group("phase"),
                    _sends(child.children, path, owner_id, field, default_phase=every.group("phase")),
                    _location(path, owner_id, child, field),
                )
            )
            if len(schedules) > MAX_SCENARIO_SCHEDULES:
                _fail(path, owner_id, child, f"scenario exceeds {MAX_SCENARIO_SCHEDULES} schedules", field)
            continue
        action = re.fullmatch(rf"action\s+({IDENTIFIER})(?:\s+when\s+(.+))?:", text)
        if action:
            actions.append(
                CompositeActionAst(
                    action.group(1),
                    ExpressionAst(action.group(2), _location(path, owner_id, child, field))
                    if action.group(2)
                    else None,
                    _sends(child.children, path, owner_id, field),
                    _location(path, owner_id, child, field),
                )
            )
            if len(actions) > MAX_SCENARIO_ACTIONS:
                _fail(path, owner_id, child, f"scenario exceeds {MAX_SCENARIO_ACTIONS} actions", field)
            continue
        policy = re.fullmatch(rf"policy\s+({IDENTIFIER}):", text)
        if policy:
            rules = []
            sequence = []
            for rule in child.children:
                if rule.line.text == "sequence:":
                    if rules or sequence:
                        _fail(path, owner_id, rule, "policy sequence cannot be combined with rules", field)
                    for option in rule.children:
                        match = re.fullmatch(rf"-\s+({IDENTIFIER}|wait)", option.line.text)
                        if not match or option.children:
                            _fail(path, owner_id, option, "policy sequence item must use - ACTION or - wait", field)
                        sequence.append(match.group(1))
                    if not sequence:
                        _fail(path, owner_id, rule, "policy sequence may not be empty", field)
                    continue
                choose = re.fullmatch(
                    rf"choose\s+({IDENTIFIER}|wait)\s+when\s+(.+)", rule.line.text
                )
                otherwise = re.fullmatch(
                    rf"otherwise\s+({IDENTIFIER}|wait)", rule.line.text
                )
                if choose and not rule.children:
                    rules.append(
                        PolicyRuleAst(
                            choose.group(1),
                            ExpressionAst(choose.group(2), _location(path, owner_id, rule, field)),
                            _location(path, owner_id, rule, field),
                        )
                    )
                elif otherwise and not rule.children:
                    rules.append(
                        PolicyRuleAst(
                            otherwise.group(1),
                            None,
                            _location(path, owner_id, rule, field),
                        )
                    )
                else:
                    _fail(path, owner_id, rule, "policy rule must use choose ACTION when CONDITION or otherwise ACTION", field)
            if not rules and not sequence:
                _fail(path, owner_id, child, "policy may not be empty", field)
            if rules and any(rule.condition is None for rule in rules[:-1]):
                _fail(path, owner_id, child, "otherwise must be the final policy rule", field)
            policies.append(
                PolicyAst(
                    policy.group(1),
                    tuple(rules),
                    tuple(sequence),
                    _location(path, owner_id, child, field),
                )
            )
            continue
        decide = _DECIDE.fullmatch(text)
        if decide:
            options = []
            for option in child.children:
                match = re.fullmatch(rf"-\s+({IDENTIFIER}|wait)", option.line.text)
                if not match or option.children:
                    _fail(path, owner_id, option, "decision option must use - ACTION or - wait", field)
                options.append(match.group(1))
            if not options:
                _fail(path, owner_id, child, "decision must declare at least one option", field)
            decisions.append(
                DecisionScheduleAst(
                    ExpressionAst(decide.group("interval"), _location(path, owner_id, child, field)),
                    ExpressionAst(decide.group("start"), _location(path, owner_id, child, field)),
                    ExpressionAst(decide.group("end"), _location(path, owner_id, child, field))
                    if decide.group("end")
                    else None,
                    decide.group("phase"),
                    tuple(options),
                    _location(path, owner_id, child, field),
                )
            )
            continue
        if text.startswith("stop when "):
            if stop is not None:
                _fail(path, owner_id, child, "scenario stop may be declared only once", field)
            stop = _expr(path, owner_id, child, text[len("stop when ") :], field)
            continue
        if text == "bounds:":
            if bounds is not None:
                _fail(path, owner_id, child, "scenario bounds may be declared only once", field)
            values: Dict[str, ExpressionAst] = {}
            for bound in child.children:
                match = re.fullmatch(rf"({IDENTIFIER})\s*=\s*(.+)", bound.line.text)
                if not match:
                    _fail(path, owner_id, bound, "bound must use NAME = VALUE", field)
                if match.group(1) in values:
                    _fail(path, owner_id, bound, f"duplicate scenario bound {match.group(1)!r}", field)
                values[match.group(1)] = _expr(path, owner_id, bound, match.group(2), field)
            required = {
                "horizon",
                "maximum_events",
                "maximum_decisions",
                "maximum_branches",
                "maximum_entities",
            }
            if set(values) != required:
                missing = sorted(required - set(values))
                unknown = sorted(set(values) - required)
                detail = (["missing " + ", ".join(missing)] if missing else []) + (["unknown " + ", ".join(unknown)] if unknown else [])
                _fail(path, owner_id, child, "scenario bounds do not match: " + "; ".join(detail), field)
            bounds = ScenarioBoundsAst(
                values["horizon"],
                values["maximum_events"],
                values["maximum_decisions"],
                values["maximum_branches"],
                values["maximum_entities"],
                _location(path, owner_id, child, field),
            )
            continue
        _fail(path, owner_id, child, f"unknown scenario declaration: {text}", field)

    if not phases:
        _fail(path, owner_id, node, "scenario must declare phases", base)
    if bounds is None:
        _fail(path, owner_id, node, "scenario must declare all execution bounds", base)
    return ScenarioAst(
        owner_id=owner_id,
        id=scenario_id,
        label=label,
        phases=tuple(phases),
        instances=tuple(instances),
        connections=tuple(connections),
        schedules=tuple(schedules),
        actions=tuple(actions),
        policies=tuple(policies),
        decisions=tuple(decisions),
        stop=stop,
        bounds=bounds,
        location=_location(path, owner_id, node, base),
    )


def _parse_analysis(node: _Node, path: Path, owner_id: str) -> AnalysisAst:
    header = _ANALYSIS_HEADER.fullmatch(node.line.text)
    if not header:
        _fail(path, owner_id, node, 'analysis must use analysis ID ["LABEL"]:', "analyses")
    analysis_id = header.group("id")
    base = f"analyses.{analysis_id}"
    values: Dict[str, object] = {}
    for child in node.children:
        text = child.line.text
        if text == "policies:":
            if "policies" in values or "policy" in values:
                _fail(path, owner_id, child, "analysis policies may be declared only once", base)
            policy_ids = []
            for policy in child.children:
                match = re.fullmatch(rf"-\s+({IDENTIFIER})", policy.line.text)
                if not match or policy.children:
                    _fail(path, owner_id, policy, "analysis policy must use - POLICY", base)
                policy_ids.append(match.group(1))
            if not policy_ids:
                _fail(path, owner_id, child, "analysis policies may not be empty", base)
            values["policies"] = tuple(policy_ids)
            continue
        if child.children:
            _fail(path, owner_id, child, "analysis declaration cannot contain a block", base)
        objective = re.fullmatch(r"(objective|then)\s+(maximize|minimize)\s+(.+)", text)
        if objective:
            key = objective.group(1)
            if key in values:
                _fail(path, owner_id, child, f"duplicate analysis {key}", base)
            values[key] = (
                objective.group(2),
                ExpressionAst(objective.group(3), _location(path, owner_id, child, base)),
            )
            continue
        target = re.fullmatch(r"target\s*=\s*(.+)", text)
        if target:
            if "target" in values:
                _fail(path, owner_id, child, "duplicate analysis target", base)
            values["target"] = ExpressionAst(
                target.group(1), _location(path, owner_id, child, base)
            )
            continue
        assignment = re.fullmatch(rf"(using|operation|policy)\s*=\s*({PATH})", text)
        if not assignment:
            _fail(path, owner_id, child, f"unknown analysis declaration: {text}", base)
        if assignment.group(1) in values:
            _fail(path, owner_id, child, f"duplicate analysis {assignment.group(1)}", base)
        values[assignment.group(1)] = assignment.group(2)
    if "using" not in values or "operation" not in values:
        _fail(path, owner_id, node, "analysis requires using and operation", base)
    if "policy" in values and "policies" in values:
        _fail(path, owner_id, node, "use policy or policies, not both", base)
    operation = str(values["operation"])
    if operation not in {"run", "compare", "optimize", "reach", "steady", "cycle"}:
        _fail(path, owner_id, node, f"unknown analysis operation {operation!r}", base)
    objective_value = values.get("objective")
    tie_value = values.get("then")
    return AnalysisAst(
        owner_id,
        analysis_id,
        _decode(header.group("label"), path, node.line) if header.group("label") else None,
        str(values["using"]),
        operation,
        (
            (str(values["policy"]),)
            if "policy" in values
            else tuple(values.get("policies", ()))
        ),
        objective_value[0] if isinstance(objective_value, tuple) else None,
        objective_value[1] if isinstance(objective_value, tuple) else None,
        tie_value[0] if isinstance(tie_value, tuple) else None,
        tie_value[1] if isinstance(tie_value, tuple) else None,
        values.get("target") if isinstance(values.get("target"), ExpressionAst) else None,
        _location(path, owner_id, node, base),
    )


def parse_scenario_asts(text: str, path: Path) -> Tuple[ScenarioAst, ...]:
    owner_id, _name, _description, remaining, _metadata, _positions = _parse_header(text, path)
    return tuple(
        _parse_scenario(node, path, owner_id)
        for node in _nodes(remaining, path)
        if node.line.text.startswith("scenario ")
    )


def parse_analysis_asts(text: str, path: Path) -> Tuple[AnalysisAst, ...]:
    owner_id, _name, _description, remaining, _metadata, _positions = _parse_header(text, path)
    return tuple(
        _parse_analysis(node, path, owner_id)
        for node in _nodes(remaining, path)
        if node.line.text.startswith("analysis ")
    )
