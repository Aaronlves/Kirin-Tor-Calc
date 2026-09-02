"""Kirin Tor source syntax v2.

The v2 surface is deliberately small: declarations, property assignment,
indented blocks, ``-`` list items, and statically resolved member paths.  It
lowers to the existing raw mathematical schema so the exact-number, unit, and
safety machinery remains authoritative.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .errors import SchemaError, SourceLocation
from .limits import (
    MAX_ANALYSES_PER_ENTRY,
    MAX_PROCESSES_PER_ENTRY,
    MAX_SCENARIOS_PER_ENTRY,
    MAX_STRUCTURE_DEPTH,
)
from .process_ast import ProcessAst
from .scenario_ast import AnalysisAst, ScenarioAst


IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
PATH = rf"{IDENTIFIER}(?:\.{IDENTIFIER})*"
QUOTED = r'"(?:[^"\\]|\\.)*"'
_ENTRY_RE = re.compile(rf"^@entry\s+({IDENTIFIER})(?:\s+({QUOTED}))?$")
_DECL_RE = re.compile(
    rf"^(?P<kind>{PATH})\s+(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?(?P<tail>.*)$"
)
_NAMED_BLOCK_RE = re.compile(
    rf"^(?P<kind>{PATH})\s+(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?:$"
)
_SCALAR_RE = re.compile(
    rf"^(?P<kind>input|field|output)\s+(?P<body>.+)$"
)
_FUNCTION_RE = re.compile(
    rf"^function\s+(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?"
    rf"\((?P<parameters>.*)\)\s*:\s*(?P<type>boolean|number\[{IDENTIFIER}\]|{IDENTIFIER})"
    r"\s*=\s*(?P<expression>.*)$"
)
_TYPED_VALUE_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?P<optional>\?)?(?:\s+(?P<label>{QUOTED}))?\s*:\s*"
    rf"(?P<type>boolean|number\[{IDENTIFIER}\]|{PATH})(?:\s*=\s*(?P<default>.*))?$"
)
_ASSIGN_RE = re.compile(rf"^(?P<name>{IDENTIFIER}(?:\.{IDENTIFIER})*)\s*=\s*(?P<value>.*)$")
_TABLE_POINT_RE = re.compile(
    r"^(?P<input>[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+))"
    r"\s*=\s*(?P<output>.*)$"
)
_NEXT_RE = re.compile(
    rf"^next\(\s*(?P<current>{IDENTIFIER})\s*,\s*(?P<index>{IDENTIFIER})\s*\)\s*=\s*(?P<value>.*)$"
)
_FIELD_LITERAL_RE = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+)$"
)
_PERCENT_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<number>[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+))%(?![A-Za-z0-9_])"
)
_QUANTITY_RE = re.compile(
    rf"(?<![A-Za-z0-9_.])(?P<number>[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+))\s+(?P<unit>{IDENTIFIER})(?![A-Za-z0-9_])"
)


@dataclass(frozen=True)
class _Line:
    number: int
    raw: str

    @property
    def indent(self) -> int:
        return len(self.raw) - len(self.raw.lstrip(" "))

    @property
    def text(self) -> str:
        return self.raw.lstrip(" ")


@dataclass(frozen=True)
class _Node:
    line: _Line
    children: Tuple["_Node", ...] = ()


def _location(path: Path, line: Optional[_Line] = None, field: Optional[str] = None) -> SourceLocation:
    return SourceLocation(
        path=str(path),
        field=field,
        line=line.number if line else None,
        column=line.indent + 1 if line else None,
    )


def _fail(path: Path, message: str, line: Optional[_Line] = None, field: Optional[str] = None) -> None:
    raise SchemaError(message, _location(path, line, field))


def _decode(value: str, path: Path, line: _Line) -> str:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        _fail(path, f"invalid quoted text: {exc.msg}", line)
    if not isinstance(decoded, str):
        _fail(path, "quoted text must be a string", line)
    return decoded


def _atom(value: str, path: Path, line: _Line) -> Any:
    value = value.strip()
    if not value:
        _fail(path, "value may not be empty", line)
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"'):
        return _decode(value, path, line)
    return value


def normalize_expression(
    source: str, unit_names: Optional[Iterable[str]] = None
) -> str:
    """Lower v2 percent and numeric-unit literals to the restricted core syntax."""

    allowed_units = set(unit_names or ())
    pieces = re.split(r'("(?:[^"\\]|\\.)*")', source)
    for index in range(0, len(pieces), 2):
        piece = _PERCENT_RE.sub(lambda match: f"({match.group('number')} / 100)", pieces[index])
        if allowed_units:
            previous = None
            while previous != piece:
                previous = piece
                piece = _QUANTITY_RE.sub(
                    lambda match: (
                        f"({match.group('number')} * {match.group('unit')})"
                        if match.group("unit") in allowed_units
                        else match.group(0)
                    ),
                    piece,
                )
        pieces[index] = piece
    return "".join(pieces)


def _significant(lines: Iterable[_Line], path: Path) -> List[_Line]:
    result = []
    for line in lines:
        if "\t" in line.raw:
            _fail(path, "tabs are not allowed; use spaces for indentation", line)
        if not line.text or line.text.startswith("//"):
            continue
        result.append(line)
    return result


def _nodes(lines: Iterable[_Line], path: Path) -> Tuple[_Node, ...]:
    significant = _significant(lines, path)
    if not significant:
        return ()

    def parse_from(index: int, indent: int) -> Tuple[List[_Node], int]:
        result: List[_Node] = []
        while index < len(significant):
            line = significant[index]
            if line.indent < indent:
                break
            if line.indent > indent:
                _fail(path, "unexpected indentation", line)
            index += 1
            children: List[_Node] = []
            if index < len(significant) and significant[index].indent > indent:
                children, index = parse_from(index, significant[index].indent)
            result.append(_Node(line, tuple(children)))
        return result, index

    if significant[0].indent:
        _fail(path, "top-level declarations may not be indented", significant[0])
    parsed, index = parse_from(0, 0)
    if index != len(significant):
        _fail(path, "could not parse indentation", significant[index])
    return tuple(parsed)


def _expression(node: _Node, initial: str, path: Path, field: str) -> str:
    parts = [initial.strip()]
    for child in node.children:
        if child.children:
            _fail(path, "expression continuation may not contain a nested block", child.line, field)
        parts.append(child.line.text.strip())
    value = " ".join(part for part in parts if part)
    if not value:
        _fail(path, "expression may not be empty", node.line, field)
    return normalize_expression(value)


def _label(match: re.Match[str], path: Path, line: _Line) -> Optional[str]:
    value = match.groupdict().get("label")
    return _decode(value, path, line) if value else None


def _position(positions: Dict[str, Tuple[int, int]], key: str, line: _Line) -> None:
    positions[key] = (line.number, line.indent + 1)


def _list(node: _Node, path: Path, field: str) -> List[str]:
    values = []
    for child in node.children:
        if child.children or not child.line.text.startswith("- "):
            _fail(path, "ordered lists must use '- ITEM'", child.line, field)
        value = child.line.text[2:].strip()
        if not value:
            _fail(path, "list item may not be empty", child.line, field)
        values.append(value)
    if not values:
        _fail(path, "list may not be empty", node.line, field)
    return values


def _assignments(node: _Node, path: Path, field: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for child in node.children:
        match = _ASSIGN_RE.fullmatch(child.line.text)
        if not match:
            _fail(path, "property must use NAME = VALUE", child.line, field)
        name = match.group("name")
        if name in result:
            _fail(path, f"duplicate property {name!r}", child.line, f"{field}.{name}")
        result[name] = _atom(_expression(child, match.group("value"), path, f"{field}.{name}"), path, child.line)
    return result


def _interface_assignments(
    node: _Node,
    path: Path,
    field: str,
    prefix: Tuple[str, ...] = (),
) -> Dict[str, Any]:
    """Flatten readable nested interface roles to stable dotted role paths."""

    result: Dict[str, Any] = {}
    for child in node.children:
        assignment = _ASSIGN_RE.fullmatch(child.line.text)
        block = re.fullmatch(rf"({IDENTIFIER}):", child.line.text)
        if assignment:
            role_parts = (*prefix, *assignment.group("name").split("."))
            role = ".".join(role_parts)
            value = _atom(
                _expression(child, assignment.group("value"), path, f"{field}.{role}"),
                path,
                child.line,
            )
            additions = {role: value}
        elif block:
            if not child.children:
                _fail(path, "interface role block may not be empty", child.line, field)
            if len(prefix) >= MAX_STRUCTURE_DEPTH + 2:
                _fail(
                    path,
                    f"interface role exceeds maximum depth {MAX_STRUCTURE_DEPTH + 2}",
                    child.line,
                    field,
                )
            additions = _interface_assignments(
                child,
                path,
                field,
                (*prefix, block.group(1)),
            )
        else:
            _fail(
                path,
                "interface roles require NAME = MEMBER_PATH or NAME:",
                child.line,
                field,
            )
        for role, value in additions.items():
            if role in result:
                _fail(path, f"duplicate interface role {role!r}", child.line, f"{field}.{role}")
            result[role] = value
    return result


def _object_values(node: _Node, path: Path, field: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for child in node.children:
        text = child.line.text
        assignment = _ASSIGN_RE.fullmatch(text)
        if assignment:
            name = assignment.group("name")
            if "." in name:
                _fail(path, "object properties use indentation instead of dotted assignment", child.line, field)
            value: Any = _atom(
                _expression(child, assignment.group("value"), path, f"{field}.{name}"),
                path,
                child.line,
            )
        elif text.endswith(":") and re.fullmatch(rf"{IDENTIFIER}:", text):
            name = text[:-1]
            value = _object_values(child, path, f"{field}.{name}")
        else:
            _fail(path, "object body requires NAME = VALUE or NAME:", child.line, field)
        if name in result:
            _fail(path, f"duplicate object property {name!r}", child.line, f"{field}.{name}")
        result[name] = value
    return result


def _parse_header(text: str, path: Path) -> Tuple[str, str, Optional[str], List[_Line], Dict[str, Any], Dict[str, Tuple[int, int]]]:
    lines = [_Line(index, raw.rstrip("\r")) for index, raw in enumerate(text.splitlines(), 1)]
    code = [
        line
        for line in lines
        if line.text and not line.text.startswith("//")
    ]
    if not code:
        _fail(path, "Kirin Tor document is empty")
    if code[0].text != "@kirin 2":
        _fail(path, "first declaration must be '@kirin 2'", code[0])
    if len(code) < 2:
        _fail(path, "entry declaration is missing", code[0])
    entry = _ENTRY_RE.fullmatch(code[1].text)
    if not entry:
        _fail(path, 'second declaration must be @entry ID ["LABEL"]', code[1])
    entry_id = entry.group(1)
    entry_name = _decode(entry.group(2), path, code[1]) if entry.group(2) else entry_id
    positions = {
        "schema_version": (code[0].number, 1),
        "type": (code[1].number, 1),
        "id": (code[1].number, 1),
        "name": (code[1].number, 1),
    }
    metadata: Dict[str, Any] = {}
    remaining: List[_Line] = []
    consumed_header = {code[0].number, code[1].number}
    description: Optional[str] = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.number in consumed_header or not line.text or line.text.startswith("//"):
            index += 1
            continue
        if line.indent == 0 and re.fullmatch(r"-{3,}", line.text):
            if description is not None:
                _fail(path, "only one description block is allowed", line, "description")
            fence = line.text
            body: List[str] = []
            opening = line
            index += 1
            while index < len(lines) and not (lines[index].indent == 0 and lines[index].text == fence):
                body.append(lines[index].raw)
                index += 1
            if index >= len(lines):
                _fail(path, f"description block is missing closing {fence}", opening, "description")
            description = "\n".join(body).strip("\n")
            positions["description"] = (opening.number, 1)
            index += 1
            continue
        if line.indent == 0 and line.text.startswith("@"):
            pieces = line.text.split(maxsplit=1)
            key_map = {"@game-version": "game_version", "@status": "validation_status"}
            if len(pieces) != 2 or pieces[0] not in key_map:
                _fail(path, f"unknown or incomplete directive {pieces[0]}", line)
            key = key_map[pieces[0]]
            if key in metadata:
                _fail(path, f"duplicate directive {pieces[0]}", line, key)
            metadata[key] = _decode(pieces[1], path, line) if pieces[1].startswith('"') else pieces[1]
            positions[key] = (line.number, 1)
            index += 1
            continue
        remaining.append(line)
        index += 1
    if description is not None:
        metadata["description"] = description
    return entry_id, entry_name, description, remaining, metadata, positions


def parse_kirin_v2_source(
    text: str, path: Path
) -> Tuple[
    Dict[str, Any],
    Dict[str, Tuple[int, int]],
    Tuple[ProcessAst, ...],
    Tuple[ScenarioAst, ...],
    Tuple[AnalysisAst, ...],
]:
    from .kirin_syntax import _parse_dimension_expression, _parse_input_statement, _type_spec

    entry_id, entry_name, _description, remaining, metadata, positions = _parse_header(text, path)
    nodes = _nodes(remaining, path)
    raw: Dict[str, Any] = {
        "schema_version": 1,
        "id": entry_id,
        "name": entry_name,
        "type": "entry",
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {},
        "outputs": {},
        **metadata,
    }
    semantics = {"dimensions": {}, "units": {}, "domains": {}}
    sources: List[Dict[str, Any]] = []
    aliases: Dict[str, str] = {}
    constraints: List[str] = []
    tables: Dict[str, Any] = {}
    distributions: Dict[str, Any] = {}
    recurrences: Dict[str, Any] = {}
    state_models: Dict[str, Any] = {}
    groups: Dict[str, Any] = {}
    presets: Dict[str, Any] = {}
    types: Dict[str, Any] = {}
    objects: Dict[str, Any] = {}
    cycles: Dict[str, Any] = {}
    displays: Dict[str, Tuple[str, Optional[int], _Line]] = {}
    source_ids: set[str] = set()
    chart_seen = False
    process_asts = []
    process_ids = set()
    scenario_asts = []
    scenario_ids = set()
    analysis_asts = []
    analysis_ids = set()

    reserved = {
        "dimension", "unit", "domain", "source", "alias", "input", "field", "require",
        "function", "output", "group", "preset", "table", "distribution", "recurrence",
        "state_model", "display", "chart", "type", "cycle", "process", "scenario",
        "analysis",
    }

    for node in nodes:
        text_head = node.line.text
        if text_head.startswith("process "):
            from .process_parser import _parse_process

            process_ast = _parse_process(node, path, entry_id)
            if process_ast.id in process_ids:
                _fail(
                    path,
                    f"duplicate process {process_ast.id!r}",
                    node.line,
                    f"processes.{process_ast.id}",
                )
            process_ids.add(process_ast.id)
            process_asts.append(process_ast)
            if len(process_asts) > MAX_PROCESSES_PER_ENTRY:
                _fail(
                    path,
                    f"entry exceeds {MAX_PROCESSES_PER_ENTRY} processes",
                    node.line,
                    "processes",
                )
            continue
        if text_head.startswith("scenario "):
            from .scenario_parser import _parse_scenario

            scenario_ast = _parse_scenario(node, path, entry_id)
            if scenario_ast.id in scenario_ids:
                _fail(
                    path,
                    f"duplicate scenario {scenario_ast.id!r}",
                    node.line,
                    f"scenarios.{scenario_ast.id}",
                )
            scenario_ids.add(scenario_ast.id)
            scenario_asts.append(scenario_ast)
            if len(scenario_asts) > MAX_SCENARIOS_PER_ENTRY:
                _fail(
                    path,
                    f"entry exceeds {MAX_SCENARIOS_PER_ENTRY} scenarios",
                    node.line,
                    "scenarios",
                )
            continue
        if text_head.startswith("analysis "):
            from .scenario_parser import _parse_analysis

            analysis_ast = _parse_analysis(node, path, entry_id)
            if analysis_ast.id in analysis_ids:
                _fail(
                    path,
                    f"duplicate analysis {analysis_ast.id!r}",
                    node.line,
                    f"analyses.{analysis_ast.id}",
                )
            analysis_ids.add(analysis_ast.id)
            analysis_asts.append(analysis_ast)
            if len(analysis_asts) > MAX_ANALYSES_PER_ENTRY:
                _fail(
                    path,
                    f"entry exceeds {MAX_ANALYSES_PER_ENTRY} analyses",
                    node.line,
                    "analyses",
                )
            continue
        if text_head.startswith("dimension "):
            match = re.fullmatch(rf"dimension\s+({IDENTIFIER})(?:\s+({QUOTED}))?", text_head)
            if not match or node.children:
                _fail(path, 'dimension must use dimension ID ["LABEL"]', node.line, "semantics.dimensions")
            name = match.group(1)
            if name in semantics["dimensions"]:
                _fail(path, f"duplicate dimension {name!r}", node.line, f"semantics.dimensions.{name}")
            semantics["dimensions"][name] = (
                {"name": _decode(match.group(2), path, node.line)}
                if match.group(2)
                else {}
            )
            _position(positions, f"semantics.dimensions.{name}", node.line)
            continue
        if text_head.startswith("unit "):
            match = re.fullmatch(rf"unit\s+({IDENTIFIER})\s*=\s*(.+)", text_head)
            if not match:
                _fail(path, "unit must use unit ID = DIMENSION_EXPRESSION", node.line, "semantics.units")
            name = match.group(1)
            if name in semantics["units"]:
                _fail(path, f"duplicate unit {name!r}", node.line, f"semantics.units.{name}")
            expression = _expression(node, match.group(2), path, f"semantics.units.{name}")
            dimensions, scale = _parse_dimension_expression(expression, path, node.line)
            semantics["units"][name] = {"dimensions": dimensions}
            if scale != "1":
                semantics["units"][name]["scale"] = scale
            _position(positions, f"semantics.units.{name}", node.line)
            continue
        if text_head.startswith("domain "):
            symbolic = _NAMED_BLOCK_RE.fullmatch(text_head)
            if symbolic and symbolic.group("kind") == "domain":
                if symbolic.group("name") in semantics["domains"]:
                    _fail(
                        path,
                        f"duplicate domain {symbolic.group('name')!r}",
                        node.line,
                        f"semantics.domains.{symbolic.group('name')}",
                    )
                values = []
                value_labels = {}
                for child in node.children:
                    item = re.fullmatch(
                        rf"-\s+({IDENTIFIER})(?:\s+({QUOTED}))?",
                        child.line.text,
                    )
                    if not item or child.children:
                        _fail(
                            path,
                            'symbolic domain values must use - SYMBOL ["LABEL"]',
                            child.line,
                            f"semantics.domains.{symbolic.group('name')}",
                        )
                    value = item.group(1)
                    if value in values:
                        _fail(
                            path,
                            f"duplicate symbolic domain value {value!r}",
                            child.line,
                            f"semantics.domains.{symbolic.group('name')}",
                        )
                    values.append(value)
                    if item.group(2):
                        value_labels[value] = _decode(item.group(2), path, child.line)
                    _position(
                        positions,
                        f"semantics.domains.{symbolic.group('name')}.allowed_values.{value}",
                        child.line,
                    )
                if not values:
                    _fail(
                        path,
                        "symbolic domain must declare at least one value",
                        node.line,
                        f"semantics.domains.{symbolic.group('name')}",
                    )
                data = {"value_type": "symbolic", "allowed_values": values}
                if symbolic.group("label"):
                    data["label"] = _decode(
                        symbolic.group("label"), path, node.line
                    )
                if value_labels:
                    data["value_labels"] = value_labels
                semantics["domains"][symbolic.group("name")] = data
                _position(
                    positions,
                    f"semantics.domains.{symbolic.group('name')}",
                    node.line,
                )
                continue
            if node.children:
                _fail(
                    path,
                    "numeric or boolean domain may not contain a block",
                    node.line,
                    "semantics.domains",
                )
            body = text_head[len("domain "):]
            name, data = _parse_input_statement(body, path, node.line, allow_default=False)
            if name in semantics["domains"]:
                _fail(path, f"duplicate domain {name!r}", node.line, f"semantics.domains.{name}")
            semantics["domains"][name] = data
            _position(positions, f"semantics.domains.{name}", node.line)
            continue
        if text_head.startswith("source "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "source":
                _fail(path, 'source must use source ID ["LABEL"]:', node.line, "sources")
            if match.group("name") in source_ids:
                _fail(path, f"duplicate source {match.group('name')!r}", node.line, "sources")
            source_ids.add(match.group("name"))
            values = _assignments(node, path, f"sources.{match.group('name')}")
            values.setdefault("kind", match.group("name"))
            sources.append(values)
            _position(positions, f"sources.{len(sources) - 1}", node.line)
            continue
        if text_head.startswith("alias "):
            match = re.fullmatch(rf"alias\s+(\S+)\s*=\s*({PATH})", text_head)
            if not match or node.children:
                _fail(path, "alias must use alias NAME = MEMBER_PATH", node.line, "aliases")
            if match.group(1) in aliases:
                _fail(path, f"duplicate alias {match.group(1)!r}", node.line, "aliases")
            aliases[match.group(1)] = match.group(2)
            _position(positions, f"aliases.{match.group(1)}", node.line)
            continue
        scalar = _SCALAR_RE.fullmatch(text_head)
        if scalar:
            kind = scalar.group("kind")
            body = scalar.group("body")
            if kind == "input":
                name, data = _parse_input_statement(body, path, node.line)
                if name in raw["inputs"]:
                    _fail(path, f"duplicate input {name!r}", node.line, f"inputs.{name}")
                raw["inputs"][name] = data
                _position(positions, f"inputs.{name}", node.line)
                continue
            match = re.fullmatch(
                rf"(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED}))?\s*:\s*"
                rf"(?P<type>boolean|number\[{IDENTIFIER}\]|{IDENTIFIER})\s*=\s*(?P<value>.*)",
                body,
            )
            if not match:
                _fail(path, f"{kind} must use {kind} ID [\"LABEL\"]: TYPE = EXPRESSION", node.line, f"{kind}s")
            name = match.group("name")
            if name in raw[f"{kind}s"]:
                _fail(path, f"duplicate {kind} {name!r}", node.line, f"{kind}s.{name}")
            type_data = _type_spec(match.group("type"), path, node.line)
            expression = _expression(node, match.group("value"), path, f"{kind}s.{name}")
            label = _decode(match.group("label"), path, node.line) if match.group("label") else None
            if kind == "field" and (expression in {"true", "false"} or _FIELD_LITERAL_RE.fullmatch(expression)):
                data = {
                    "kind": "value",
                    "value": True if expression == "true" else False if expression == "false" else expression,
                    "unit": type_data.get("unit", "dimensionless"),
                }
                if expression in {"true", "false"}:
                    data["value_type"] = "boolean"
            else:
                data = {
                    "expression": expression,
                    "unit": type_data.get("unit", "dimensionless"),
                }
                if kind == "field":
                    data["kind"] = "expression"
            if label is not None:
                data["label"] = label
            raw[f"{kind}s"][name] = data
            _position(positions, f"{kind}s.{name}", node.line)
            continue
        if text_head.startswith("require "):
            constraints.append(_expression(node, text_head[len("require "):], path, f"constraints.{len(constraints)}"))
            _position(positions, f"constraints.{len(constraints) - 1}", node.line)
            continue
        function = _FUNCTION_RE.fullmatch(text_head)
        if function:
            if function.group("name") in raw["functions"]:
                _fail(path, f"duplicate function {function.group('name')!r}", node.line, "functions")
            params: Dict[str, Any] = {}
            parameter_text = function.group("parameters").strip()
            if parameter_text:
                from .kirin_syntax import _parameter_items
                for item in _parameter_items(parameter_text, path, node.line):
                    name, spec = _parse_input_statement(item, path, node.line, allow_default=False, allow_label=False)
                    params[name] = spec
            type_data = _type_spec(function.group("type"), path, node.line)
            data = {
                "parameters": params,
                "expression": _expression(node, function.group("expression"), path, f"functions.{function.group('name')}"),
                "unit": type_data.get("unit", "dimensionless"),
            }
            if function.group("label"):
                data["label"] = _decode(function.group("label"), path, node.line)
            raw["functions"][function.group("name")] = data
            _position(positions, f"functions.{function.group('name')}", node.line)
            continue
        if text_head.startswith("type "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "type":
                _fail(path, 'type must use type ID ["LABEL"]:', node.line, "types")
            type_id = match.group("name")
            if type_id in types:
                _fail(path, f"duplicate type {type_id!r}", node.line, f"types.{type_id}")
            fields: Dict[str, Any] = {}
            interfaces: Dict[str, Any] = {}
            for child in node.children:
                typed = _TYPED_VALUE_RE.fullmatch(child.line.text)
                if typed:
                    if child.children:
                        _fail(path, "type field declaration may not contain a block", child.line, f"types.{type_id}")
                    field_name = typed.group("name")
                    if field_name in fields:
                        _fail(path, f"duplicate type field {field_name!r}", child.line, f"types.{type_id}")
                    field_data: Dict[str, Any] = {
                        "type": typed.group("type"),
                        "optional": bool(typed.group("optional")),
                    }
                    if typed.group("label"):
                        field_data["label"] = _decode(typed.group("label"), path, child.line)
                    if typed.group("default") is not None:
                        field_data["default"] = normalize_expression(typed.group("default").strip())
                    fields[field_name] = field_data
                    _position(positions, f"types.{type_id}.fields.{field_name}", child.line)
                    continue
                interface = re.fullmatch(rf"({IDENTIFIER}):", child.line.text)
                if interface:
                    if interface.group(1) in interfaces:
                        _fail(path, f"duplicate interface {interface.group(1)!r}", child.line, f"types.{type_id}")
                    interfaces[interface.group(1)] = _interface_assignments(
                        child, path, f"types.{type_id}.interfaces.{interface.group(1)}"
                    )
                    continue
                _fail(path, "type body requires FIELD: TYPE or INTERFACE:", child.line, f"types.{type_id}")
            if not fields:
                _fail(path, "type must declare at least one field", node.line, f"types.{type_id}")
            types[type_id] = {
                "label": _label(match, path, node.line) or type_id,
                "fields": fields,
                "interfaces": interfaces,
            }
            _position(positions, f"types.{type_id}", node.line)
            continue
        if text_head.startswith("cycle "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "cycle":
                _fail(path, 'cycle must use cycle ID ["LABEL"]:', node.line, "cycles")
            cycle_id = match.group("name")
            if cycle_id in cycles:
                _fail(path, f"duplicate cycle {cycle_id!r}", node.line, f"cycles.{cycle_id}")
            profile: Optional[str] = None
            sequence: Optional[List[str]] = None
            for child in node.children:
                assignment = _ASSIGN_RE.fullmatch(child.line.text)
                if assignment and assignment.group("name") == "using":
                    if profile is not None:
                        _fail(path, "cycle declares using more than once", child.line, f"cycles.{cycle_id}")
                    profile = assignment.group("value").strip()
                elif child.line.text == "sequence:":
                    if sequence is not None:
                        _fail(path, "cycle declares sequence more than once", child.line, f"cycles.{cycle_id}")
                    sequence = _list(child, path, f"cycles.{cycle_id}.sequence")
                else:
                    _fail(path, "cycle body requires using = PROFILE and sequence:", child.line, f"cycles.{cycle_id}")
            if not profile or not sequence:
                _fail(path, "cycle requires using and a non-empty sequence", node.line, f"cycles.{cycle_id}")
            cycles[cycle_id] = {
                "label": _label(match, path, node.line) or cycle_id,
                "profile": profile,
                "sequence": sequence,
            }
            _position(positions, f"cycles.{cycle_id}", node.line)
            continue
        if text_head.startswith("group "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "group":
                _fail(path, 'group must use group ID ["LABEL"]:', node.line, "groups")
            if match.group("name") in groups:
                _fail(path, f"duplicate group {match.group('name')!r}", node.line, "groups")
            groups[match.group("name")] = {
                "label": _label(match, path, node.line) or match.group("name"),
                "outputs": _list(node, path, f"groups.{match.group('name')}"),
            }
            _position(positions, f"groups.{match.group('name')}", node.line)
            continue
        if text_head.startswith("preset "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "preset":
                _fail(path, 'preset must use preset ID ["LABEL"]:', node.line, "presets")
            if match.group("name") in presets:
                _fail(path, f"duplicate preset {match.group('name')!r}", node.line, "presets")
            values = _assignments(node, path, f"presets.{match.group('name')}")
            presets[match.group("name")] = {
                "label": _label(match, path, node.line) or match.group("name"),
                "values": values,
            }
            _position(positions, f"presets.{match.group('name')}", node.line)
            continue
        if text_head.startswith("table "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "table":
                _fail(path, 'table must use table ID ["LABEL"]:', node.line, "tables")
            if match.group("name") in tables:
                _fail(path, f"duplicate table {match.group('name')!r}", node.line, "tables")
            values: Dict[str, Any] = {}
            points: List[List[str]] = []
            for child in node.children:
                if child.line.text == "points:":
                    for point in child.children:
                        assignment = _TABLE_POINT_RE.fullmatch(point.line.text)
                        if not assignment or point.children or not assignment.group("output").strip():
                            _fail(path, "table point must use X = Y", point.line, f"tables.{match.group('name')}.points")
                        points.append([assignment.group("input"), assignment.group("output").strip()])
                else:
                    assignment = _ASSIGN_RE.fullmatch(child.line.text)
                    if not assignment:
                        _fail(path, "table body requires input, output, and points", child.line, "tables")
                    if assignment.group("name") in values:
                        _fail(path, f"duplicate table property {assignment.group('name')!r}", child.line, "tables")
                    values[assignment.group("name")] = assignment.group("value").strip()
            tables[match.group("name")] = {
                "label": _label(match, path, node.line) or match.group("name"),
                "input_unit": values.get("input", "dimensionless"),
                "unit": values.get("output", "dimensionless"),
                "points": points,
            }
            _position(positions, f"tables.{match.group('name')}", node.line)
            continue
        if text_head.startswith("distribution "):
            match = re.fullmatch(
                rf"distribution\s+({IDENTIFIER})(?:\s+({QUOTED}))?\s*:\s*({IDENTIFIER}):",
                text_head,
            )
            if not match:
                _fail(path, 'distribution must use distribution ID ["LABEL"]: UNIT:', node.line, "distributions")
            if match.group(1) in distributions:
                _fail(path, f"duplicate distribution {match.group(1)!r}", node.line, "distributions")
            outcomes_node = next((child for child in node.children if child.line.text == "outcomes:"), None)
            if outcomes_node is None:
                _fail(path, "distribution requires outcomes:", node.line, "distributions")
            outcomes = []
            for item in _list(outcomes_node, path, f"distributions.{match.group(1)}.outcomes"):
                if item.count("@") != 1:
                    _fail(path, "distribution outcome must use VALUE @ PROBABILITY", outcomes_node.line)
                value, probability = (part.strip() for part in item.split("@", 1))
                outcomes.append({"value": normalize_expression(value), "probability": normalize_expression(probability)})
            distributions[match.group(1)] = {
                "label": _decode(match.group(2), path, node.line) if match.group(2) else match.group(1),
                "unit": match.group(3),
                "outcomes": outcomes,
            }
            _position(positions, f"distributions.{match.group(1)}", node.line)
            continue
        if text_head.startswith("recurrence "):
            match = re.fullmatch(
                rf"recurrence\s+({IDENTIFIER})(?:\s+({QUOTED}))?\s*:\s*({IDENTIFIER}):",
                text_head,
            )
            if not match:
                _fail(path, 'recurrence must use recurrence ID ["LABEL"]: UNIT:', node.line, "recurrences")
            if match.group(1) in recurrences:
                _fail(path, f"duplicate recurrence {match.group(1)!r}", node.line, "recurrences")
            data: Dict[str, Any] = {
                "label": _decode(match.group(2), path, node.line) if match.group(2) else match.group(1),
                "unit": match.group(3),
            }
            for child in node.children:
                assignment = _ASSIGN_RE.fullmatch(child.line.text)
                next_match = _NEXT_RE.fullmatch(child.line.text)
                if assignment and assignment.group("name") in {"initial", "steps"}:
                    data[assignment.group("name")] = _expression(child, assignment.group("value"), path, f"recurrences.{match.group(1)}")
                elif next_match:
                    data.update({
                        "current": next_match.group("current"),
                        "index": next_match.group("index"),
                        "next": _expression(child, next_match.group("value"), path, f"recurrences.{match.group(1)}.next"),
                    })
                else:
                    _fail(path, "recurrence requires initial, steps, and next(current, index)", child.line, "recurrences")
            recurrences[match.group(1)] = data
            _position(positions, f"recurrences.{match.group(1)}", node.line)
            continue
        if text_head.startswith("state_model "):
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "state_model":
                _fail(path, 'state_model must use state_model ID ["LABEL"]:', node.line, "state_models")
            if match.group("name") in state_models:
                _fail(path, f"duplicate state_model {match.group('name')!r}", node.line, "state_models")
            states: List[str] = []
            transitions: List[Dict[str, str]] = []
            rewards: Dict[str, Any] = {}
            for child in node.children:
                if child.line.text == "states:":
                    states = _list(child, path, f"state_models.{match.group('name')}.states")
                elif child.line.text == "transitions:":
                    for item in _list(child, path, f"state_models.{match.group('name')}.transitions"):
                        edge, separator, probability = item.partition("@")
                        source, arrow, target = edge.strip().partition("->")
                        if not separator or not arrow:
                            _fail(path, "transition must use SOURCE -> TARGET @ PROBABILITY", child.line)
                        transitions.append({
                            "source": source.strip(), "target": target.strip(),
                            "probability": normalize_expression(probability.strip()),
                        })
                elif child.line.text == "rewards:":
                    for reward in child.children:
                        reward_match = re.fullmatch(
                            rf"reward\s+({IDENTIFIER})(?:\s+({QUOTED}))?\s*:\s*({IDENTIFIER}):",
                            reward.line.text,
                        )
                        if not reward_match:
                            _fail(path, 'reward must use reward ID ["LABEL"]: UNIT:', reward.line, "state_models")
                        rewards[reward_match.group(1)] = {
                            "label": _decode(reward_match.group(2), path, reward.line) if reward_match.group(2) else reward_match.group(1),
                            "unit": reward_match.group(3),
                            "values": _assignments(reward, path, f"state_models.{match.group('name')}.rewards.{reward_match.group(1)}"),
                        }
                else:
                    _fail(path, "state_model body requires states, transitions, or rewards", child.line, "state_models")
            state_models[match.group("name")] = {
                "label": _label(match, path, node.line) or match.group("name"),
                "states": states,
                "transitions": transitions,
                "rewards": rewards,
            }
            _position(positions, f"state_models.{match.group('name')}", node.line)
            continue
        if text_head.startswith("display "):
            match = re.fullmatch(
                rf"display\s+({IDENTIFIER})\s*=\s*(number|integer|percent|coefficient_percent)(?:\s+digits\s+(\d+))?",
                text_head,
            )
            if not match or node.children:
                _fail(path, "display must use display OUTPUT = FORMAT [digits N]", node.line, "display")
            output_name = match.group(1)
            if output_name in displays:
                _fail(path, f"duplicate display for {output_name!r}", node.line, "display")
            displays[output_name] = (
                match.group(2),
                int(match.group(3)) if match.group(3) else None,
                node.line,
            )
            continue
        if text_head.startswith("chart "):
            if chart_seen:
                _fail(path, "an entry may declare only one chart", node.line, "chart")
            match = _NAMED_BLOCK_RE.fullmatch(text_head)
            if not match or match.group("kind") != "chart":
                _fail(path, 'chart must use chart ID ["LABEL"]:', node.line, "chart")
            chart_seen = True
            values: Dict[str, Any] = {}
            labels: Dict[str, str] = {}
            for child in node.children:
                if child.line.text == "y:":
                    curves = _list(child, path, "y")
                    raw["y"] = []
                    for curve in curves:
                        curve_match = re.fullmatch(rf"(.+?)(?:\s+as\s+({QUOTED}))?", curve)
                        assert curve_match is not None
                        target = curve_match.group(1).strip()
                        raw["y"].append(target)
                        if curve_match.group(2):
                            labels[target] = _decode(curve_match.group(2), path, child.line)
                else:
                    assignment = _ASSIGN_RE.fullmatch(child.line.text)
                    if not assignment:
                        _fail(path, "chart property must use NAME = VALUE", child.line, "chart")
                    values[assignment.group("name")] = assignment.group("value").strip()
            for required in ("x", "range", "points"):
                if required not in values:
                    _fail(path, f"chart is missing {required}", node.line, "chart")
            raw["x"] = values["x"]
            start, separator, end = values["range"].partition("..")
            if not separator:
                _fail(path, "chart range must use START..END", node.line, "chart")
            raw["range"] = [normalize_expression(start.strip()), normalize_expression(end.strip())]
            try:
                raw["points"] = int(values["points"])
            except ValueError:
                _fail(path, "chart points must be an integer", node.line, "chart")
            key_map = {
                "using": "preset", "title": "title", "x_label": "x_label", "y_label": "y_label",
                "export_svg": "out", "export_csv": "data_out",
            }
            for source, target in key_map.items():
                if source in values:
                    raw[target] = _atom(values[source], path, node.line)
            if labels:
                raw["curve_labels"] = labels
            if match.group("label") and "title" not in raw:
                raw["title"] = _decode(match.group("label"), path, node.line)
            _position(positions, "x", node.line)
            _position(positions, "display", node.line)
            continue

        declaration = _NAMED_BLOCK_RE.fullmatch(text_head)
        if declaration and declaration.group("kind") not in reserved:
            object_id = declaration.group("name")
            if object_id in objects:
                _fail(path, f"duplicate object {object_id!r}", node.line, f"objects.{object_id}")
            objects[object_id] = {
                "type": declaration.group("kind"),
                "label": _label(declaration, path, node.line) or object_id,
                "values": _object_values(node, path, f"objects.{object_id}.values"),
            }
            _position(positions, f"objects.{object_id}", node.line)
            continue
        _fail(path, f"unknown v2 declaration: {text_head}", node.line)

    for output_name, (display, digits, line) in displays.items():
        output = raw["outputs"].get(output_name)
        if output is None:
            _fail(path, f"display references unknown output {output_name!r}", line, "display")
        output["display"] = display
        if digits is not None:
            output["digits"] = digits
        _position(positions, f"outputs.{output_name}.display", line)

    canonical_semantics = {
        section: values for section, values in semantics.items() if values
    }
    if canonical_semantics:
        raw["semantics"] = canonical_semantics
    if sources:
        raw["sources"] = sources
    if aliases:
        raw["aliases"] = aliases
    raw["constraints"] = constraints
    for key, value in (
        ("tables", tables), ("distributions", distributions), ("recurrences", recurrences),
        ("state_models", state_models), ("groups", groups), ("presets", presets),
        ("types", types), ("objects", objects), ("cycles", cycles),
    ):
        if value:
            raw[key] = value
    return (
        raw,
        positions,
        tuple(process_asts),
        tuple(scenario_asts),
        tuple(analysis_asts),
    )


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _labeled(prefix: str, name: str, data: Dict[str, Any], suffix: str = ":") -> str:
    label = data.get("label")
    rendered = f"{prefix} {name}"
    if isinstance(label, str) and label != name:
        rendered += " " + _quoted(label)
    return rendered + suffix


def _render_expression(prefix: str, expression: str, indent: str = "") -> List[str]:
    return [f"{indent}{prefix}{expression}"]


def render_kirin_v2_document(
    raw: Dict[str, Any],
    process_asts: Tuple[ProcessAst, ...] = (),
    scenario_asts: Tuple[ScenarioAst, ...] = (),
    analysis_asts: Tuple[AnalysisAst, ...] = (),
) -> str:
    lines = ["@kirin 2"]
    entry_name = raw.get("name", raw["id"])
    header = f"@entry {raw['id']}"
    if entry_name != raw["id"]:
        header += " " + _quoted(entry_name)
    lines.append(header)
    if raw.get("game_version"):
        lines.append(f"@game-version {_quoted(str(raw['game_version']))}")
    if raw.get("validation_status"):
        lines.append(f"@status {_quoted(str(raw['validation_status']))}")
    if raw.get("description"):
        lines.extend(["", "----", str(raw["description"]), "----"])

    semantics = raw.get("semantics", {})
    for name, data in semantics.get("dimensions", {}).items():
        lines.append("")
        line = f"dimension {name}"
        label = data.get("name") if isinstance(data, dict) else None
        if label and label != name:
            line += " " + _quoted(str(label))
        lines.append(line)
    for name, data in semantics.get("units", {}).items():
        dimensions = data.get("dimensions", {})
        pieces = []
        for dimension, power in dimensions.items():
            pieces.append(dimension if str(power) == "1" else f"{dimension} ** ({power})")
        expression = " * ".join(pieces) or "dimensionless"
        scale = str(data.get("scale", "1"))
        if scale != "1":
            expression = f"{scale} * {expression}"
        lines.extend(["", f"unit {name} = {expression}"])
    for name, data in semantics.get("domains", {}).items():
        if data.get("value_type") == "symbolic":
            line = f"domain {name}"
            if data.get("label") and data.get("label") != name:
                line += " " + _quoted(str(data["label"]))
            lines.extend(["", line + ":"])
            value_labels = data.get("value_labels", {})
            for value in data.get("allowed_values", []):
                item = f"  - {value}"
                if value_labels.get(value) and value_labels[value] != value:
                    item += " " + _quoted(str(value_labels[value]))
                lines.append(item)
            continue
        type_text = "boolean" if data.get("value_type") == "boolean" else data.get("unit", "dimensionless")
        line = f"domain {name}"
        if data.get("label") and data.get("label") != name:
            line += " " + _quoted(str(data["label"]))
        line += f": {type_text}"
        if data.get("min") is not None or data.get("max") is not None:
            line += f" in {data.get('min', '*')}..{data.get('max', '*')}"
        if data.get("integer"):
            line += " integer"
        if "allowed_values" in data:
            line += " one-of [" + ", ".join(map(str, data["allowed_values"])) + "]"
        lines.extend(["", line])

    for index, source in enumerate(raw.get("sources", []), 1):
        lines.extend(["", f"source source_{index}:"])
        for key, value in source.items():
            lines.append(f"  {key} = {_quoted(value) if isinstance(value, str) else str(value).lower()}")
    for alias, target in raw.get("aliases", {}).items():
        lines.extend(["", f"alias {alias} = {target}"])

    def type_text(data: Dict[str, Any]) -> str:
        if data.get("value_type") == "boolean":
            return "boolean"
        if data.get("domain"):
            return data["domain"]
        if data.get("value_type") == "number":
            return f"number[{data.get('unit', 'dimensionless')}]"
        return data.get("unit", "dimensionless")

    def input_declaration(name: str, data: Dict[str, Any], *, label: bool = True) -> str:
        line = name
        if label and data.get("label") and data.get("label") != name:
            line += " " + _quoted(data["label"])
        line += f": {type_text(data)}"
        if data.get("default") is not None:
            value = data["default"]
            line += " = " + ("true" if value is True else "false" if value is False else str(value))
        if data.get("min") is not None or data.get("max") is not None:
            line += f" in {data.get('min', '*')}..{data.get('max', '*')}"
        if data.get("integer"):
            line += " integer"
        if "allowed_values" in data:
            rendered_values = []
            for value in data["allowed_values"]:
                rendered_values.append(
                    "true" if value is True else "false" if value is False else str(value)
                )
            line += " one-of [" + ", ".join(rendered_values) + "]"
        return line

    def collapse(expression: Any) -> str:
        return " ".join(
            line.strip() for line in str(expression).splitlines() if line.strip()
        )

    for name, data in raw.get("inputs", {}).items():
        lines.extend(["", "input " + input_declaration(name, data)])
    for expression in raw.get("constraints", []):
        lines.extend(["", f"require {expression}"])
    for name, data in raw.get("fields", {}).items():
        line = f"field {name}"
        if data.get("label") and data.get("label") != name:
            line += " " + _quoted(data["label"])
        value = data.get("value") if data.get("kind") == "value" else data.get("expression")
        if value is True:
            value = "true"
        elif value is False:
            value = "false"
        lines.extend(["", f"{line}: {data.get('unit', 'dimensionless')} = {collapse(value)}"])
    for name, data in raw.get("functions", {}).items():
        params = []
        for param, spec in data.get("parameters", {}).items():
            params.append(input_declaration(param, spec, label=False))
        line = f"function {name}"
        if data.get("label") and data.get("label") != name:
            line += " " + _quoted(data["label"])
        lines.extend(["", f"{line}({', '.join(params)}): {data.get('unit', 'dimensionless')} = {collapse(data['expression'])}"])
    for name, data in raw.get("outputs", {}).items():
        line = f"output {name}"
        if data.get("label") and data.get("label") != name:
            line += " " + _quoted(data["label"])
        lines.extend(["", f"{line}: {data.get('unit', 'dimensionless')} = {collapse(data['expression'])}"])
        if data.get("display") and (data.get("display") != "number" or data.get("digits") is not None):
            display = f"display {name} = {data['display']}"
            if data.get("digits") is not None:
                display += f" digits {data['digits']}"
            lines.append(display)

    for name, data in raw.get("types", {}).items():
        lines.extend(["", _labeled("type", name, data)])
        for field_name, field_data in data.get("fields", {}).items():
            optional = "?" if field_data.get("optional") else ""
            line = f"  {field_name}{optional}: {field_data['type']}"
            if field_data.get("default") is not None:
                default = field_data["default"]
                rendered_default = (
                    "true" if default is True else "false" if default is False else str(default)
                )
                line += f" = {rendered_default}"
            lines.append(line)
        for interface_name, mappings in data.get("interfaces", {}).items():
            lines.append(f"  {interface_name}:")

            mapping_tree: Dict[str, Any] = {}
            for role, member in mappings.items():
                cursor = mapping_tree
                parts = role.split(".")
                for part in parts[:-1]:
                    cursor = cursor.setdefault(part, {})
                cursor[parts[-1]] = member

            def render_mappings(values: Dict[str, Any], indent: str) -> None:
                for role, member in values.items():
                    if isinstance(member, dict):
                        lines.append(f"{indent}{role}:")
                        render_mappings(member, indent + "  ")
                    else:
                        lines.append(f"{indent}{role} = {member}")

            render_mappings(mapping_tree, "    ")
    for name, data in raw.get("objects", {}).items():
        lines.extend(["", _labeled(data["type"], name, data)])

        def render_values(values: Dict[str, Any], indent: str) -> None:
            for key, value in values.items():
                if isinstance(value, dict):
                    lines.append(f"{indent}{key}:")
                    render_values(value, indent + "  ")
                else:
                    rendered = "true" if value is True else "false" if value is False else str(value)
                    lines.append(f"{indent}{key} = {rendered}")

        render_values(data.get("values", {}), "  ")
    for name, data in raw.get("cycles", {}).items():
        lines.extend(["", _labeled("cycle", name, data), f"  using = {data['profile']}", "  sequence:"])
        lines.extend(f"    - {item}" for item in data["sequence"])

    if process_asts:
        from .process_renderer import render_process_ast

        for process in process_asts:
            lines.append("")
            lines.extend(render_process_ast(process))

    if scenario_asts or analysis_asts:
        from .scenario_renderer import render_analysis_ast, render_scenario_ast

        for scenario in scenario_asts:
            lines.append("")
            lines.extend(render_scenario_ast(scenario))
        for analysis in analysis_asts:
            lines.append("")
            lines.extend(render_analysis_ast(analysis))

    for name, data in raw.get("tables", {}).items():
        lines.extend(["", _labeled("table", name, data), f"  input = {data['input_unit']}", f"  output = {data['unit']}", "  points:"])
        lines.extend(f"    {x} = {y}" for x, y in data["points"])
    for name, data in raw.get("distributions", {}).items():
        lines.extend(["", _labeled("distribution", name, data, f": {data['unit']}:")])
        lines.append("  outcomes:")
        lines.extend(f"    - {item['value']} @ {item['probability']}" for item in data["outcomes"])
    for name, data in raw.get("recurrences", {}).items():
        lines.extend(["", _labeled("recurrence", name, data, f": {data['unit']}:")])
        lines.extend([
            f"  initial = {data['initial']}", f"  steps = {data['steps']}",
            f"  next({data['current']}, {data['index']}) = {data['next']}",
        ])
    for name, data in raw.get("state_models", {}).items():
        lines.extend(["", _labeled("state_model", name, data), "  states:"])
        lines.extend(f"    - {state}" for state in data["states"])
        lines.append("  transitions:")
        lines.extend(
            f"    - {item['source']} -> {item['target']} @ {item['probability']}"
            for item in data["transitions"]
        )
        if data.get("rewards"):
            lines.append("  rewards:")
            for reward_name, reward in data["rewards"].items():
                lines.append("    " + _labeled("reward", reward_name, reward, f": {reward['unit']}:") )
                lines.extend(f"      {state} = {value}" for state, value in reward["values"].items())
    for name, data in raw.get("groups", {}).items():
        lines.extend(["", _labeled("group", name, data)])
        lines.extend(f"  - {item}" for item in data["outputs"])
    for name, data in raw.get("presets", {}).items():
        lines.extend(["", _labeled("preset", name, data)])
        for key, value in data["values"].items():
            rendered = "true" if value is True else "false" if value is False else str(value)
            lines.append(f"  {key} = {rendered}")
    if raw.get("x") is not None:
        chart = {"label": raw.get("title", raw["id"])}
        lines.extend(["", _labeled("chart", "preview", chart), f"  x = {raw['x']}", f"  range = {raw['range'][0]}..{raw['range'][1]}", f"  points = {raw['points']}", "  y:"])
        labels = raw.get("curve_labels", {})
        for target in raw["y"]:
            line = f"    - {target}"
            if target in labels:
                line += " as " + _quoted(labels[target])
            lines.append(line)
        mapping = {"preset": "using", "x_label": "x_label", "y_label": "y_label", "out": "export_svg", "data_out": "export_csv"}
        for source, target in mapping.items():
            if raw.get(source):
                value = raw[source]
                lines.append(f"  {target} = {_quoted(value) if source not in {'preset'} else value}")
    return "\n".join(lines).rstrip() + "\n"
