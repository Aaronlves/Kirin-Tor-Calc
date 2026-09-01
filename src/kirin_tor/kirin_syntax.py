"""Parser for the author-facing Kirin source format.

The parser is intentionally an adapter: it produces the same raw document
shape consumed by :func:`kirin_tor.schema.parse_document`.  Mathematical
meaning and safety checks therefore remain in the existing schema and engine.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .errors import SchemaError, SourceLocation
from .limits import MAX_SOURCE_BYTES


IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
QUOTED_STRING = r'"(?:[^"\\]|\\.)*"'
_HEADER_RE = re.compile(r"^@(entry)\s+(" + IDENTIFIER + r")$")
_SECTION_RE = re.compile(r"^(" + IDENTIFIER + r"):$$")
_KEY_VALUE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
_FENCE_RE = re.compile(r"^-{3,}$")
_TYPE = rf"(?:boolean|number\[{IDENTIFIER}\]|{IDENTIFIER})"
_INPUT_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:\s*(?P<type>{_TYPE})"
    r"(?:\s*=\s*(?P<default>\S+))?"
    r"(?:\s+in\s+(?P<range>\S+\.\.\S+))?"
    r"(?:\s+(?P<integer>integer))?"
    r"(?:\s+one-of\s+\[(?P<allowed>[^\]]*)\])?$"
)
_FIELD_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:\s*"
    rf"(?P<type>{_TYPE})\s*=\s*(?P<value>.*)$"
)
_FIELD_LITERAL_RE = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+)$"
)
_FUNCTION_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?"
    rf"\((?P<parameters>.*)\)\s*->\s*"
    rf"(?P<unit>{_TYPE})\s*=\s*(?P<expression>.*)$"
)
_OUTPUT_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:\s*"
    rf"(?P<unit>{_TYPE})\s*=\s*(?P<expression>.*)$"
)
_ALIAS_RE = re.compile(rf"^(?P<alias>[^\s=]+)\s*=\s*(?P<target>{IDENTIFIER}\.{IDENTIFIER})$")
_NAMED_BLOCK_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:$"
)
_DISPLAY_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})\s*:\s*"
    r"(?P<display>number|integer|percent|coefficient_percent)"
    r"(?:\s+digits\s+(?P<digits>\d+))?$"
)
_TABLE_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:\s*"
    rf"(?P<input>{IDENTIFIER})\s*->\s*(?P<output>{IDENTIFIER})\s*:$"
)
_DISTRIBUTION_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:\s*"
    rf"(?P<unit>{IDENTIFIER})\s*:$"
)
_RECURRENCE_RE = _DISTRIBUTION_RE
_RECURRENCE_NEXT_RE = re.compile(
    rf"^next\(\s*(?P<current>{IDENTIFIER})\s*,\s*(?P<index>{IDENTIFIER})\s*\)"
    r"\s*=\s*(?P<expression>.*)$"
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

    @property
    def blank(self) -> bool:
        return not self.text

    @property
    def comment(self) -> bool:
        return self.text.startswith("//")


@dataclass(frozen=True)
class _Statement:
    head: _Line
    continuation: Tuple[_Line, ...]

    def expression(self, initial: str) -> str:
        parts = [initial.strip()]
        parts.extend(line.text.strip() for line in self.continuation if not line.blank and not line.comment)
        return " ".join(part for part in parts if part)


def _location(path: Path, line: Optional[_Line] = None, field: Optional[str] = None) -> SourceLocation:
    return SourceLocation(
        path=str(path),
        field=field,
        line=line.number if line else None,
        column=(line.indent + 1) if line else None,
    )


def _fail(path: Path, message: str, line: Optional[_Line] = None, field: Optional[str] = None) -> None:
    raise SchemaError(message, _location(path, line, field))


def _decode_string(value: str, path: Path, line: _Line) -> str:
    value = value.strip()
    if not value:
        _fail(path, "text value may not be empty", line)
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            _fail(path, f"invalid quoted text: {exc.msg}", line)
        if not isinstance(decoded, str):
            _fail(path, "quoted text must be a string", line)
        return decoded
    return value


def _atom(value: str, path: Path, line: _Line) -> Any:
    value = value.strip()
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"'):
        return _decode_string(value, path, line)
    if not value:
        _fail(path, "value may not be empty", line)
    return value


def _source_atom(value: str, path: Path, line: _Line) -> Any:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return _decode_string(value, path, line)

    def check(item: Any) -> None:
        if item is None or isinstance(item, (str, int, bool)):
            return
        if isinstance(item, float):
            _fail(
                path,
                "source metadata may not contain floating-point JSON numbers; quote exact decimals",
                line,
            )
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(key, str) for key in item):
            for child in item.values():
                check(child)
            return
        _fail(path, "source metadata must contain JSON-compatible exact data", line)

    check(decoded)
    return decoded


def _type_spec(type_text: str, path: Path, line: _Line) -> Dict[str, Any]:
    if type_text == "boolean":
        return {"value_type": "boolean"}
    if type_text.startswith("number["):
        return {"value_type": "number", "unit": type_text[7:-1]}
    # The schema resolves this compatibility spelling as a domain when the
    # identifier names a domain, otherwise as a unit.
    return {"unit": type_text}


def _split_range(
    value: str, path: Path, line: _Line, *, allow_open: bool = False
) -> Tuple[Optional[str], Optional[str]]:
    if value.count("..") != 1:
        _fail(path, "range must use START..END", line)
    start, end = value.split("..", 1)
    if not start or not end:
        _fail(path, "range must include both START and END", line)
    if allow_open:
        minimum = None if start == "*" else start
        maximum = None if end == "*" else end
        if minimum is None and maximum is None:
            _fail(path, "range may not be open at both ends", line)
        return minimum, maximum
    if start == "*" or end == "*":
        _fail(path, "this range requires both finite endpoints", line)
    return start, end


def _allowed_values(value: str, path: Path, line: _Line) -> List[Any]:
    if not value.strip():
        return []
    result = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            _fail(path, "one-of may not contain an empty value", line)
        result.append(_atom(item, path, line))
    return result


def _parameter_items(value: str, path: Path, line: _Line) -> List[str]:
    """Split function parameters without splitting commas inside one-of lists."""
    items: List[str] = []
    start = 0
    square_depth = 0
    for index, character in enumerate(value):
        if character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
            if square_depth < 0:
                _fail(path, "function parameter list has an unmatched ']'", line, "functions")
        elif character == "," and square_depth == 0:
            item = value[start:index].strip()
            if not item:
                _fail(path, "function parameter list contains an empty parameter", line, "functions")
            items.append(item)
            start = index + 1
    if square_depth:
        _fail(path, "function parameter list has an unmatched '['", line, "functions")
    final = value[start:].strip()
    if not final:
        _fail(path, "function parameter list contains an empty parameter", line, "functions")
    items.append(final)
    return items


def _parse_input_statement(
    text: str,
    path: Path,
    line: _Line,
    *,
    allow_default: bool = True,
    allow_label: bool = True,
) -> Tuple[str, Dict[str, Any]]:
    match = _INPUT_RE.fullmatch(text)
    if not match:
        _fail(
            path,
            "input must use NAME: TYPE [= DEFAULT] [in MIN..MAX] [integer] [one-of [...]]",
            line,
        )
    assert match is not None
    data = _type_spec(match.group("type"), path, line)
    label = match.group("label")
    if label is not None:
        if not allow_label:
            _fail(path, "display labels are not allowed in this declaration", line)
        data["label"] = _decode_string(label, path, line)
    default = match.group("default")
    if default is not None:
        if not allow_default:
            _fail(path, "function parameters may not define defaults", line)
        data["default"] = _atom(default, path, line)
    range_text = match.group("range")
    if range_text:
        minimum, maximum = _split_range(range_text, path, line, allow_open=True)
        if minimum is not None:
            data["min"] = minimum
        if maximum is not None:
            data["max"] = maximum
    if match.group("integer"):
        data["integer"] = True
    allowed = match.group("allowed")
    if allowed is not None:
        data["allowed_values"] = _allowed_values(allowed, path, line)
    return match.group("name"), data


def _dimension_exponent(node: ast.AST, path: Path, line: _Line) -> Fraction:
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        return Fraction(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _dimension_exponent(node.operand, path, line)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        numerator = _dimension_exponent(node.left, path, line)
        denominator = _dimension_exponent(node.right, path, line)
        if denominator == 0:
            _fail(path, "dimension exponent denominator may not be zero", line, "units")
        return numerator / denominator
    _fail(path, "dimension exponents must be exact integers or rational numbers", line, "units")
    raise AssertionError("unreachable")


def _parse_dimension_expression(
    expression: str, path: Path, line: _Line
) -> Tuple[Dict[str, str], str]:
    try:
        root = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        _fail(path, f"invalid dimension expression: {exc.msg}", line, "units")

    def combine(left: Dict[str, Fraction], right: Dict[str, Fraction], sign: int) -> Dict[str, Fraction]:
        result = dict(left)
        for name, power in right.items():
            result[name] = result.get(name, Fraction(0)) + sign * power
            if result[name] == 0:
                del result[name]
        return result

    def visit(node: ast.AST) -> Tuple[Dict[str, Fraction], Fraction]:
        if isinstance(node, ast.Name):
            return {node.id: Fraction(1)}, Fraction(1)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            token = ast.get_source_segment(expression, node)
            try:
                scale = Fraction(token) if token is not None else Fraction(node.value)
            except (ValueError, ZeroDivisionError):
                _fail(path, "unit scale must be an exact positive number", line, "units")
            return {}, scale
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            left, left_scale = visit(node.left)
            right, right_scale = visit(node.right)
            return combine(left, right, 1), left_scale * right_scale
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, left_scale = visit(node.left)
            right, right_scale = visit(node.right)
            if right_scale == 0:
                _fail(path, "unit scale denominator may not be zero", line, "units")
            return combine(left, right, -1), left_scale / right_scale
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            base, scale = visit(node.left)
            exponent = _dimension_exponent(node.right, path, line)
            if exponent.denominator != 1 and scale != 1:
                _fail(path, "a scaled unit may only use an integer power", line, "units")
            return (
                {name: power * exponent for name, power in base.items() if power * exponent},
                scale ** exponent.numerator,
            )
        _fail(
            path,
            "dimension expression allows only names, 1, multiplication, division, and exact powers",
            line,
            "units",
        )
        raise AssertionError("unreachable")

    powers, scale = visit(root.body)
    if scale <= 0:
        _fail(path, "unit scale must be positive", line, "units")
    return (
        {name: str(power) for name, power in sorted(powers.items())},
        str(scale),
    )


def _statements(lines: Iterable[_Line], path: Path, section: str) -> List[_Statement]:
    significant = [line for line in lines if not line.blank and not line.comment]
    if not significant:
        return []
    for line in significant:
        if "\t" in line.raw:
            _fail(path, "tabs are not allowed; use spaces for indentation", line, section)
    base_indent = significant[0].indent
    if base_indent < 2:
        _fail(path, f"{section} entries must be indented by at least two spaces", significant[0], section)
    result: List[_Statement] = []
    head: Optional[_Line] = None
    continuation: List[_Line] = []
    for line in significant:
        if line.indent < base_indent:
            _fail(path, f"inconsistent indentation in {section}", line, section)
        if line.indent == base_indent:
            if head is not None:
                result.append(_Statement(head, tuple(continuation)))
            head = line
            continuation = []
        else:
            if head is None:
                _fail(path, f"unexpected continuation in {section}", line, section)
            continuation.append(line)
    if head is not None:
        result.append(_Statement(head, tuple(continuation)))
    return result


def _parse_document_structure(
    text: str, path: Path
) -> Tuple[str, str, Optional[str], Dict[str, Tuple[_Line, ...]], Dict[str, Tuple[str, _Line]], Dict[str, Tuple[int, int]]]:
    lines = [_Line(index, raw.rstrip("\r")) for index, raw in enumerate(text.splitlines(), 1)]
    code_lines = [line for line in lines if not line.blank and not line.comment]
    if not code_lines:
        _fail(path, "Kirin document is empty")
    if code_lines[0].text != "@kirin 1":
        _fail(path, "first declaration must be '@kirin 1'", code_lines[0])
    if len(code_lines) < 2:
        _fail(path, "document type declaration is missing", code_lines[0])
    header = _HEADER_RE.fullmatch(code_lines[1].text)
    if not header:
        _fail(path, "second declaration must be '@entry ID'", code_lines[1])
    if "\t" in code_lines[0].raw or "\t" in code_lines[1].raw:
        _fail(path, "tabs are not allowed; use spaces for indentation", code_lines[1])
    assert header is not None
    doc_type, doc_id = header.groups()

    first_header_index = lines.index(code_lines[0])
    second_header_index = lines.index(code_lines[1])
    consumed = {first_header_index, second_header_index}
    sections: Dict[str, Tuple[_Line, ...]] = {}
    top_values: Dict[str, Tuple[str, _Line]] = {}
    positions: Dict[str, Tuple[int, int]] = {
        "schema_version": (code_lines[0].number, code_lines[0].indent + 1),
        "type": (code_lines[1].number, code_lines[1].indent + 1),
        "id": (code_lines[1].number, code_lines[1].indent + 1),
        "name": (code_lines[1].number, code_lines[1].indent + 1),
    }
    description: Optional[str] = None

    index = 0
    while index < len(lines):
        if index in consumed:
            index += 1
            continue
        line = lines[index]
        if line.blank or line.comment:
            index += 1
            continue
        if "\t" in line.raw:
            _fail(path, "tabs are not allowed; use spaces for indentation", line)
        if line.indent:
            _fail(path, "content outside a section may not be indented", line)
        if _FENCE_RE.fullmatch(line.text):
            if description is not None:
                _fail(path, "only one document description block is allowed in v1", line, "description")
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
        if line.text.startswith("@"):
            pieces = line.text.split(maxsplit=1)
            if len(pieces) != 2:
                _fail(path, "metadata directive requires a value", line)
            directive = pieces[0][1:]
            key_map = {"game-version": "game_version", "status": "validation_status"}
            if directive not in key_map:
                _fail(path, f"unknown directive @{directive}", line)
            key = key_map[directive]
            if key in top_values:
                _fail(path, f"duplicate directive @{directive}", line, key)
            top_values[key] = (_decode_string(pieces[1], path, line), line)
            positions[key] = (line.number, line.indent + 1)
            index += 1
            continue
        section = _SECTION_RE.fullmatch(line.text)
        if section:
            name = section.group(1)
            if name in sections or name in top_values:
                _fail(path, f"duplicate section {name!r}", line, name)
            positions[name] = (line.number, 1)
            body = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if not candidate.blank and not candidate.comment and candidate.indent == 0:
                    break
                body.append(candidate)
                index += 1
            sections[name] = tuple(body)
            continue
        key_value = _KEY_VALUE_RE.fullmatch(line.text)
        if key_value:
            key, value = key_value.groups()
            if not value:
                _fail(path, f"section {key!r} requires indented content", line, key)
            if key in top_values or key in sections:
                _fail(path, f"duplicate key {key!r}", line, key)
            top_values[key] = (value, line)
            positions[key.replace("-", "_")] = (line.number, 1)
            index += 1
            continue
        _fail(path, "expected a directive, description block, section, or KEY: VALUE", line)

    return doc_type, doc_id, description, sections, top_values, positions


def _set_position(positions: Dict[str, Tuple[int, int]], key: str, line: _Line) -> None:
    positions[key] = (line.number, line.indent + 1)


def _parse_entry(
    doc_id: str,
    description: Optional[str],
    sections: Dict[str, Tuple[_Line, ...]],
    top_values: Dict[str, Tuple[str, _Line]],
    positions: Dict[str, Tuple[int, int]],
    path: Path,
) -> Dict[str, Any]:
    allowed_sections = {
        "dimensions", "units", "domains", "inputs", "constraints", "fields",
        "functions", "tables", "distributions", "recurrences", "state_models", "outputs",
        "sources", "aliases", "groups", "presets", "display", "y",
    }
    unknown = sorted(set(sections) - allowed_sections)
    if unknown:
        line = sections[unknown[0]][0] if sections[unknown[0]] else None
        _fail(path, "unknown entry section(s): " + ", ".join(unknown), line, unknown[0])
    allowed_top = {
        "game_version", "validation_status", "x", "range", "points", "preset",
        "title", "x-label", "y-label", "export-svg", "export-csv",
    }
    unknown_top = sorted(set(top_values) - allowed_top)
    if unknown_top:
        value, line = top_values[unknown_top[0]]
        _fail(path, f"unknown entry key {unknown_top[0]!r}", line, unknown_top[0])

    raw: Dict[str, Any] = {
        "schema_version": 1,
        "id": doc_id,
        "name": doc_id,
        "type": "entry",
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {},
        "outputs": {},
    }
    if description is not None:
        raw["description"] = description
    for key in ("game_version", "validation_status"):
        if key in top_values:
            raw[key] = top_values[key][0]

    for statement in _statements(sections.get("sources", ()), path, "sources"):
        if statement.continuation:
            _fail(path, "source entries must fit on one line", statement.head, "sources")
        raw.setdefault("sources", []).append(_source_atom(statement.head.text, path, statement.head))

    semantics: Dict[str, Any] = {}
    dimensions: Dict[str, Any] = {}
    for statement in _statements(sections.get("dimensions", ()), path, "dimensions"):
        if statement.continuation:
            _fail(path, "dimension declarations must fit on one line", statement.head, "dimensions")
        match = re.fullmatch(rf'(?P<name>{IDENTIFIER})(?:\s+(?P<label>"(?:[^"\\]|\\.)*"))?', statement.head.text)
        if not match:
            _fail(path, 'dimension must use NAME or NAME "DISPLAY NAME"', statement.head, "dimensions")
        assert match is not None
        name = match.group("name")
        label = match.group("label")
        if name in dimensions:
            _fail(path, f"duplicate dimension {name!r}", statement.head, f"dimensions.{name}")
        dimensions[name] = {"name": _decode_string(label, path, statement.head)} if label else {}
        _set_position(positions, f"semantics.dimensions.{name}", statement.head)
    if dimensions:
        semantics["dimensions"] = dimensions

    units: Dict[str, Any] = {}
    for statement in _statements(sections.get("units", ()), path, "units"):
        if statement.continuation or statement.head.text.count("=") != 1:
            _fail(path, "unit must use NAME = DIMENSION_EXPRESSION", statement.head, "units")
        name, expression = (part.strip() for part in statement.head.text.split("=", 1))
        if not re.fullmatch(IDENTIFIER, name) or not expression:
            _fail(path, "unit must use NAME = DIMENSION_EXPRESSION", statement.head, "units")
        if name in units:
            _fail(path, f"duplicate unit {name!r}", statement.head, f"units.{name}")
        dimensions, scale = _parse_dimension_expression(expression, path, statement.head)
        units[name] = {"dimensions": dimensions}
        if scale != "1":
            units[name]["scale"] = scale
        _set_position(positions, f"semantics.units.{name}", statement.head)
    if units:
        semantics["units"] = units

    domains: Dict[str, Any] = {}
    for statement in _statements(sections.get("domains", ()), path, "domains"):
        if statement.continuation:
            _fail(path, "domain declarations must fit on one line", statement.head, "domains")
        name, data = _parse_input_statement(
            statement.head.text, path, statement.head, allow_default=False, allow_label=False
        )
        type_text = statement.head.text.split(":", 1)[1].strip().split()[0]
        if type_text not in {"boolean"} and not type_text.startswith("number["):
            _fail(path, "domain type must be boolean or number[UNIT]", statement.head, f"domains.{name}")
        if name in domains:
            _fail(path, f"duplicate domain {name!r}", statement.head, f"domains.{name}")
        domains[name] = data
        _set_position(positions, f"semantics.domains.{name}", statement.head)
    if domains:
        semantics["domains"] = domains
    if semantics:
        raw["semantics"] = semantics

    for statement in _statements(sections.get("aliases", ()), path, "aliases"):
        if statement.continuation:
            _fail(path, "alias declarations must fit on one line", statement.head, "aliases")
        match = _ALIAS_RE.fullmatch(statement.head.text)
        if not match:
            _fail(path, "alias must use NAME = ENTRY_ID.MEMBER", statement.head, "aliases")
        assert match is not None
        alias = match.group("alias")
        if not alias.isidentifier() or alias.startswith("__"):
            _fail(path, "alias must be one Unicode identifier", statement.head, "aliases")
        aliases = raw.setdefault("aliases", {})
        if alias in aliases:
            _fail(path, f"duplicate alias {alias!r}", statement.head, f"aliases.{alias}")
        aliases[alias] = match.group("target")
        _set_position(positions, f"aliases.{alias}", statement.head)

    for statement in _statements(sections.get("inputs", ()), path, "inputs"):
        if statement.continuation:
            _fail(path, "input declarations must fit on one line", statement.head, "inputs")
        name, data = _parse_input_statement(statement.head.text, path, statement.head)
        if name in raw["inputs"]:
            _fail(path, f"duplicate input {name!r}", statement.head, f"inputs.{name}")
        raw["inputs"][name] = data
        _set_position(positions, f"inputs.{name}", statement.head)

    for statement in _statements(sections.get("constraints", ()), path, "constraints"):
        expression = statement.expression(statement.head.text)
        if not expression:
            _fail(path, "constraint may not be empty", statement.head, "constraints")
        index = len(raw["constraints"])
        raw["constraints"].append(expression)
        _set_position(positions, f"constraints.{index}", statement.head)

    for statement in _statements(sections.get("fields", ()), path, "fields"):
        match = _FIELD_RE.fullmatch(statement.head.text)
        if not match:
            _fail(path, "field must use NAME: TYPE = VALUE_OR_EXPRESSION", statement.head, "fields")
        assert match is not None
        name = match.group("name")
        if name in raw["fields"]:
            _fail(path, f"duplicate field {name!r}", statement.head, f"fields.{name}")
        type_text = match.group("type")
        type_data = _type_spec(type_text, path, statement.head)
        unit = type_data.get("unit", "dimensionless")
        value_text = match.group("value").strip()
        is_literal = not statement.continuation and (
            value_text in {"true", "false"} or _FIELD_LITERAL_RE.fullmatch(value_text)
        )
        if is_literal:
            value = _atom(match.group("value"), path, statement.head)
            data = {"kind": "value", "value": value, "unit": unit}
            if type_data.get("value_type") == "boolean":
                data["value_type"] = "boolean"
        else:
            expression = statement.expression(match.group("value"))
            if not expression:
                _fail(path, "derived field expression may not be empty", statement.head, f"fields.{name}")
            data = {"kind": "expression", "expression": expression, "unit": unit}
        if match.group("label") is not None:
            data["label"] = _decode_string(match.group("label"), path, statement.head)
        raw["fields"][name] = data
        _set_position(positions, f"fields.{name}", statement.head)
        _set_position(positions, f"fields.{name}.expression", statement.head)

    for statement in _statements(sections.get("functions", ()), path, "functions"):
        match = _FUNCTION_RE.fullmatch(statement.head.text)
        if not match:
            _fail(path, "function must use NAME(PARAMETERS) -> UNIT = EXPRESSION", statement.head, "functions")
        assert match is not None
        name = match.group("name")
        if name in raw["functions"]:
            _fail(path, f"duplicate function {name!r}", statement.head, f"functions.{name}")
        parameters: Dict[str, Any] = {}
        parameter_text = match.group("parameters").strip()
        if parameter_text:
            for item in _parameter_items(parameter_text, path, statement.head):
                parameter_name, data = _parse_input_statement(
                    item.strip(), path, statement.head, allow_default=False, allow_label=False
                )
                if parameter_name in parameters:
                    _fail(
                        path,
                        f"duplicate function parameter {parameter_name!r}",
                        statement.head,
                        f"functions.{name}.parameters.{parameter_name}",
                    )
                parameters[parameter_name] = data
                _set_position(positions, f"functions.{name}.parameters.{parameter_name}", statement.head)
        expression = statement.expression(match.group("expression"))
        if not expression:
            _fail(path, "function expression may not be empty", statement.head, f"functions.{name}")
        type_data = _type_spec(match.group("unit"), path, statement.head)
        raw["functions"][name] = {
            "parameters": parameters,
            "expression": expression,
            "unit": type_data.get("unit", "dimensionless"),
        }
        if match.group("label") is not None:
            raw["functions"][name]["label"] = _decode_string(
                match.group("label"), path, statement.head
            )
        _set_position(positions, f"functions.{name}", statement.head)
        _set_position(positions, f"functions.{name}.expression", statement.head)

    tables: Dict[str, Any] = {}
    for statement in _statements(sections.get("tables", ()), path, "tables"):
        match = _TABLE_RE.fullmatch(statement.head.text)
        if not match:
            _fail(
                path,
                'table must use ID ["LABEL"]: INPUT_UNIT -> OUTPUT_UNIT:',
                statement.head,
                "tables",
            )
        assert match is not None
        table_id = match.group("name")
        if table_id in tables:
            _fail(path, f"duplicate table {table_id!r}", statement.head, f"tables.{table_id}")
        points = []
        for point in _statements(statement.continuation, path, f"tables.{table_id}"):
            if point.continuation or point.head.text.count("=") != 1:
                _fail(
                    path,
                    "table point must use X = Y",
                    point.head,
                    f"tables.{table_id}",
                )
            x, y = (part.strip() for part in point.head.text.split("=", 1))
            if not x or not y:
                _fail(path, "table point requires X and Y", point.head, f"tables.{table_id}")
            points.append([_atom(x, path, point.head), _atom(y, path, point.head)])
            _set_position(
                positions,
                f"tables.{table_id}.points.{len(points) - 1}",
                point.head,
            )
        tables[table_id] = {
            "label": _decode_string(match.group("label"), path, statement.head)
            if match.group("label")
            else table_id,
            "input_unit": match.group("input"),
            "unit": match.group("output"),
            "points": points,
        }
        _set_position(positions, f"tables.{table_id}", statement.head)
    if tables:
        raw["tables"] = tables

    distributions: Dict[str, Any] = {}
    for statement in _statements(sections.get("distributions", ()), path, "distributions"):
        match = _DISTRIBUTION_RE.fullmatch(statement.head.text)
        if not match:
            _fail(
                path,
                'distribution must use ID ["LABEL"]: UNIT:',
                statement.head,
                "distributions",
            )
        assert match is not None
        distribution_id = match.group("name")
        if distribution_id in distributions:
            _fail(
                path,
                f"duplicate distribution {distribution_id!r}",
                statement.head,
                f"distributions.{distribution_id}",
            )
        outcomes = []
        for outcome in _statements(
            statement.continuation, path, f"distributions.{distribution_id}"
        ):
            declaration = outcome.expression(outcome.head.text)
            if declaration.count("@") != 1:
                _fail(
                    path,
                    "distribution outcome must use VALUE @ PROBABILITY",
                    outcome.head,
                    f"distributions.{distribution_id}",
                )
            value, probability = (part.strip() for part in declaration.split("@", 1))
            if not value or not probability:
                _fail(
                    path,
                    "distribution outcome requires both a value and probability",
                    outcome.head,
                    f"distributions.{distribution_id}",
                )
            outcomes.append({"value": value, "probability": probability})
            _set_position(
                positions,
                f"distributions.{distribution_id}.outcomes.{len(outcomes) - 1}",
                outcome.head,
            )
        distributions[distribution_id] = {
            "label": _decode_string(match.group("label"), path, statement.head)
            if match.group("label")
            else distribution_id,
            "unit": match.group("unit"),
            "outcomes": outcomes,
        }
        _set_position(positions, f"distributions.{distribution_id}", statement.head)
    if distributions:
        raw["distributions"] = distributions

    recurrences: Dict[str, Any] = {}
    for statement in _statements(sections.get("recurrences", ()), path, "recurrences"):
        match = _RECURRENCE_RE.fullmatch(statement.head.text)
        if not match:
            _fail(
                path,
                'recurrence must use ID ["LABEL"]: UNIT:',
                statement.head,
                "recurrences",
            )
        assert match is not None
        recurrence_id = match.group("name")
        if recurrence_id in recurrences:
            _fail(
                path,
                f"duplicate recurrence {recurrence_id!r}",
                statement.head,
                f"recurrences.{recurrence_id}",
            )
        recurrence: Dict[str, Any] = {
            "label": _decode_string(match.group("label"), path, statement.head)
            if match.group("label")
            else recurrence_id,
            "unit": match.group("unit"),
        }
        for item in _statements(
            statement.continuation, path, f"recurrences.{recurrence_id}"
        ):
            text = item.head.text
            if text.startswith("initial") and text.partition("=")[0].strip() == "initial":
                key = "initial"
                initial = text.partition("=")[2]
                expression = item.expression(initial)
                if not expression:
                    _fail(
                        path,
                        "recurrence initial expression may not be empty",
                        item.head,
                        f"recurrences.{recurrence_id}.initial",
                    )
                data = {"initial": expression}
            elif text.startswith("steps") and text.partition("=")[0].strip() == "steps":
                key = "steps"
                initial = text.partition("=")[2]
                expression = item.expression(initial)
                if not expression:
                    _fail(
                        path,
                        "recurrence steps expression may not be empty",
                        item.head,
                        f"recurrences.{recurrence_id}.steps",
                    )
                data = {"steps": expression}
            else:
                next_match = _RECURRENCE_NEXT_RE.fullmatch(text)
                if not next_match:
                    _fail(
                        path,
                        "recurrence body requires initial = EXPR, steps = EXPR, and next(CURRENT, INDEX) = EXPR",
                        item.head,
                        f"recurrences.{recurrence_id}",
                    )
                key = "next"
                expression = item.expression(next_match.group("expression"))
                if not expression:
                    _fail(
                        path,
                        "recurrence next expression may not be empty",
                        item.head,
                        f"recurrences.{recurrence_id}.next",
                    )
                data = {
                    "current": next_match.group("current"),
                    "index": next_match.group("index"),
                    "next": expression,
                }
            if key in recurrence:
                _fail(
                    path,
                    f"duplicate recurrence {key} declaration",
                    item.head,
                    f"recurrences.{recurrence_id}.{key}",
                )
            recurrence.update(data)
            _set_position(
                positions, f"recurrences.{recurrence_id}.{key}", item.head
            )
        missing = sorted(
            {"initial", "steps", "current", "index", "next"} - set(recurrence)
        )
        if missing:
            _fail(
                path,
                "recurrence is missing required declaration(s): " + ", ".join(missing),
                statement.head,
                f"recurrences.{recurrence_id}",
            )
        recurrences[recurrence_id] = recurrence
        _set_position(positions, f"recurrences.{recurrence_id}", statement.head)
    if recurrences:
        raw["recurrences"] = recurrences

    state_models: Dict[str, Any] = {}
    for statement in _statements(sections.get("state_models", ()), path, "state_models"):
        match = _NAMED_BLOCK_RE.fullmatch(statement.head.text)
        if not match:
            _fail(
                path,
                'state model must use ID ["LABEL"]:',
                statement.head,
                "state_models",
            )
        assert match is not None
        model_id = match.group("name")
        if model_id in state_models:
            _fail(
                path,
                f"duplicate state model {model_id!r}",
                statement.head,
                f"state_models.{model_id}",
            )
        blocks = {}
        for block in _statements(
            statement.continuation, path, f"state_models.{model_id}"
        ):
            block_name = block.head.text[:-1] if block.head.text.endswith(":") else ""
            if block_name not in {"states", "transitions", "rewards"}:
                _fail(
                    path,
                    "state model blocks must be states:, transitions:, or rewards:",
                    block.head,
                    f"state_models.{model_id}",
                )
            if block_name in blocks:
                _fail(
                    path,
                    f"duplicate state model block {block_name!r}",
                    block.head,
                    f"state_models.{model_id}.{block_name}",
                )
            blocks[block_name] = block
        missing = sorted({"states", "transitions"} - set(blocks))
        if missing:
            _fail(
                path,
                "state model is missing required block(s): " + ", ".join(missing),
                statement.head,
                f"state_models.{model_id}",
            )

        states = []
        for state in _statements(
            blocks["states"].continuation,
            path,
            f"state_models.{model_id}.states",
        ):
            if state.continuation or not re.fullmatch(IDENTIFIER, state.head.text):
                _fail(
                    path,
                    "state must be one plain identifier",
                    state.head,
                    f"state_models.{model_id}.states",
                )
            states.append(state.head.text)
            _set_position(
                positions,
                f"state_models.{model_id}.states.{len(states) - 1}",
                state.head,
            )

        transitions = []
        for transition in _statements(
            blocks["transitions"].continuation,
            path,
            f"state_models.{model_id}.transitions",
        ):
            declaration = transition.expression(transition.head.text)
            if declaration.count("@") != 1:
                _fail(
                    path,
                    "state transition must use SOURCE -> TARGET @ PROBABILITY",
                    transition.head,
                    f"state_models.{model_id}.transitions",
                )
            edge, probability = (part.strip() for part in declaration.split("@", 1))
            if edge.count("->") != 1 or not probability:
                _fail(
                    path,
                    "state transition must use SOURCE -> TARGET @ PROBABILITY",
                    transition.head,
                    f"state_models.{model_id}.transitions",
                )
            source, target = (part.strip() for part in edge.split("->", 1))
            if not re.fullmatch(IDENTIFIER, source) or not re.fullmatch(IDENTIFIER, target):
                _fail(
                    path,
                    "state transition endpoints must be identifiers",
                    transition.head,
                    f"state_models.{model_id}.transitions",
                )
            transitions.append(
                {"source": source, "target": target, "probability": probability}
            )
            _set_position(
                positions,
                f"state_models.{model_id}.transitions.{len(transitions) - 1}",
                transition.head,
            )

        rewards = {}
        rewards_block = blocks.get("rewards")
        if rewards_block is not None:
            for reward in _statements(
                rewards_block.continuation,
                path,
                f"state_models.{model_id}.rewards",
            ):
                reward_match = _DISTRIBUTION_RE.fullmatch(reward.head.text)
                if not reward_match:
                    _fail(
                        path,
                        'state reward must use ID ["LABEL"]: UNIT:',
                        reward.head,
                        f"state_models.{model_id}.rewards",
                    )
                assert reward_match is not None
                reward_id = reward_match.group("name")
                if reward_id in rewards:
                    _fail(
                        path,
                        f"duplicate state reward {reward_id!r}",
                        reward.head,
                        f"state_models.{model_id}.rewards.{reward_id}",
                    )
                values = {}
                for value_statement in _statements(
                    reward.continuation,
                    path,
                    f"state_models.{model_id}.rewards.{reward_id}",
                ):
                    if "=" not in value_statement.head.text:
                        _fail(
                            path,
                            "state reward value must use STATE = EXPRESSION",
                            value_statement.head,
                            f"state_models.{model_id}.rewards.{reward_id}",
                        )
                    state, initial = (
                        part.strip()
                        for part in value_statement.head.text.split("=", 1)
                    )
                    if not re.fullmatch(IDENTIFIER, state):
                        _fail(
                            path,
                            "state reward state must be an identifier",
                            value_statement.head,
                            f"state_models.{model_id}.rewards.{reward_id}",
                        )
                    expression = value_statement.expression(initial)
                    if not expression:
                        _fail(
                            path,
                            "state reward expression may not be empty",
                            value_statement.head,
                            f"state_models.{model_id}.rewards.{reward_id}",
                        )
                    if state in values:
                        _fail(
                            path,
                            f"duplicate state reward value for {state!r}",
                            value_statement.head,
                            f"state_models.{model_id}.rewards.{reward_id}.{state}",
                        )
                    values[state] = expression
                    _set_position(
                        positions,
                        f"state_models.{model_id}.rewards.{reward_id}.values.{state}",
                        value_statement.head,
                    )
                rewards[reward_id] = {
                    "label": _decode_string(
                        reward_match.group("label"), path, reward.head
                    )
                    if reward_match.group("label")
                    else reward_id,
                    "unit": reward_match.group("unit"),
                    "values": values,
                }
                _set_position(
                    positions,
                    f"state_models.{model_id}.rewards.{reward_id}",
                    reward.head,
                )
        state_models[model_id] = {
            "label": _decode_string(match.group("label"), path, statement.head)
            if match.group("label")
            else model_id,
            "states": states,
            "transitions": transitions,
            "rewards": rewards,
        }
        _set_position(positions, f"state_models.{model_id}", statement.head)
    if state_models:
        raw["state_models"] = state_models

    for statement in _statements(sections.get("outputs", ()), path, "outputs"):
        match = _OUTPUT_RE.fullmatch(statement.head.text)
        if not match:
            _fail(path, "output must use NAME: UNIT = EXPRESSION", statement.head, "outputs")
        assert match is not None
        name = match.group("name")
        if name in raw["outputs"]:
            _fail(path, f"duplicate output {name!r}", statement.head, f"outputs.{name}")
        expression = statement.expression(match.group("expression"))
        if not expression:
            _fail(path, "output expression may not be empty", statement.head, f"outputs.{name}")
        type_data = _type_spec(match.group("unit"), path, statement.head)
        raw["outputs"][name] = {
            "expression": expression,
            "unit": type_data.get("unit", "dimensionless"),
        }
        if match.group("label") is not None:
            raw["outputs"][name]["label"] = _decode_string(
                match.group("label"), path, statement.head
            )
        _set_position(positions, f"outputs.{name}", statement.head)
        _set_position(positions, f"outputs.{name}.expression", statement.head)

    groups: Dict[str, Any] = {}
    for statement in _statements(sections.get("groups", ()), path, "groups"):
        match = _NAMED_BLOCK_RE.fullmatch(statement.head.text)
        if not match:
            _fail(path, 'group must use ID ["LABEL"]:', statement.head, "groups")
        assert match is not None
        group_id = match.group("name")
        if group_id in groups:
            _fail(path, f"duplicate group {group_id!r}", statement.head, f"groups.{group_id}")
        members = []
        for member_statement in _statements(statement.continuation, path, f"groups.{group_id}"):
            if member_statement.continuation or not re.fullmatch(IDENTIFIER, member_statement.head.text):
                _fail(
                    path,
                    "group members must be local output identifiers",
                    member_statement.head,
                    f"groups.{group_id}",
                )
            members.append(member_statement.head.text)
            _set_position(
                positions,
                f"groups.{group_id}.outputs.{len(members) - 1}",
                member_statement.head,
            )
        groups[group_id] = {
            "label": _decode_string(match.group("label"), path, statement.head)
            if match.group("label")
            else group_id,
            "outputs": members,
        }
        _set_position(positions, f"groups.{group_id}", statement.head)
    if groups:
        raw["groups"] = groups

    presets: Dict[str, Any] = {}
    for statement in _statements(sections.get("presets", ()), path, "presets"):
        match = _NAMED_BLOCK_RE.fullmatch(statement.head.text)
        if not match:
            _fail(path, 'preset must use ID ["LABEL"]:', statement.head, "presets")
        assert match is not None
        preset_id = match.group("name")
        if preset_id in presets:
            _fail(
                path,
                f"duplicate preset {preset_id!r}",
                statement.head,
                f"presets.{preset_id}",
            )
        values = {}
        for value_statement in _statements(statement.continuation, path, f"presets.{preset_id}"):
            if value_statement.continuation or value_statement.head.text.count("=") != 1:
                _fail(
                    path,
                    "preset value must use PARAMETER = VALUE",
                    value_statement.head,
                    f"presets.{preset_id}",
                )
            name, value = (part.strip() for part in value_statement.head.text.split("=", 1))
            if not name or not value:
                _fail(
                    path,
                    "preset value must include both parameter and value",
                    value_statement.head,
                    f"presets.{preset_id}",
                )
            if name in values:
                _fail(
                    path,
                    f"duplicate preset value {name!r}",
                    value_statement.head,
                    f"presets.{preset_id}.values.{name}",
                )
            values[name] = _atom(value, path, value_statement.head)
            _set_position(
                positions,
                f"presets.{preset_id}.values.{name}",
                value_statement.head,
            )
        presets[preset_id] = {
            "label": _decode_string(match.group("label"), path, statement.head)
            if match.group("label")
            else preset_id,
            "values": values,
        }
        _set_position(positions, f"presets.{preset_id}", statement.head)
    if presets:
        raw["presets"] = presets

    chart_keys = {
        "x", "range", "points", "preset", "title", "x-label", "y-label",
        "export-svg", "export-csv",
    }
    chart_present = bool(chart_keys.intersection(top_values) or "y" in sections)
    if chart_present:
        required = {"x", "range", "points"}
        missing = sorted(required - set(top_values))
        if "y" not in sections:
            missing.append("y")
        if missing:
            _fail(path, "chart configuration is missing required key(s): " + ", ".join(missing))
        raw["x"] = top_values["x"][0].strip()
        range_text, range_line = top_values["range"]
        raw["range"] = list(_split_range(range_text.strip(), path, range_line))
        points_text, points_line = top_values["points"]
        try:
            raw["points"] = int(points_text)
        except ValueError:
            _fail(path, "chart points must be an integer", points_line, "points")
        key_map = {
            "preset": "preset",
            "title": "title",
            "x-label": "x_label",
            "y-label": "y_label",
            "export-svg": "out",
            "export-csv": "data_out",
        }
        for source, target in key_map.items():
            if source in top_values:
                value, line = top_values[source]
                raw[target] = _decode_string(value, path, line)
                _set_position(positions, target, line)
        raw["y"] = []
        labels: Dict[str, str] = {}
        for statement in _statements(sections.get("y", ()), path, "y"):
            if statement.continuation:
                _fail(path, "chart curve declarations must fit on one line", statement.head, "y")
            match = re.fullmatch(r'(.+?)(?:\s+as\s+("(?:[^"\\]|\\.)*"))?', statement.head.text)
            assert match is not None
            target = match.group(1).strip()
            if not target:
                _fail(path, "chart curve target may not be empty", statement.head, "y")
            raw["y"].append(target)
            label = match.group(2)
            if label:
                labels[target] = _decode_string(label, path, statement.head)
            _set_position(positions, f"y.{len(raw['y']) - 1}", statement.head)
        if labels:
            raw["curve_labels"] = labels

    for statement in _statements(sections.get("display", ()), path, "display"):
        if statement.continuation:
            _fail(path, "display declarations must fit on one line", statement.head, "display")
        match = _DISPLAY_RE.fullmatch(statement.head.text)
        if not match:
            _fail(
                path,
                "display must use OUTPUT: FORMAT [digits N]",
                statement.head,
                "display",
            )
        assert match is not None
        output_name = match.group("name")
        if output_name not in raw["outputs"]:
            _fail(
                path,
                f"display references unknown local output {output_name!r}",
                statement.head,
                f"display.{output_name}",
            )
        raw["outputs"][output_name]["display"] = match.group("display")
        if match.group("digits") is not None:
            raw["outputs"][output_name]["digits"] = int(match.group("digits"))
        _set_position(positions, f"outputs.{output_name}.display", statement.head)
    return raw


def parse_kirin_source(
    text: str, path: Path
) -> Tuple[Dict[str, Any], Dict[str, Tuple[int, int]]]:
    """Parse one Kirin source buffer into the current raw schema shape."""
    doc_type, doc_id, description, sections, top_values, positions = _parse_document_structure(text, path)
    raw = _parse_entry(doc_id, description, sections, top_values, positions, path)
    return raw, positions


def _render_atom(value: Any, *, text: bool = False) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False) if text else value
    if value is None or isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    raise SchemaError(f"cannot render unsupported Kirin value {value!r}")


def _render_type(spec: Dict[str, Any]) -> str:
    if spec.get("value_type") == "boolean":
        return "boolean"
    if spec.get("domain"):
        return str(spec["domain"])
    return f"number[{spec.get('unit', 'dimensionless')}]"


def _render_input(name: str, spec: Dict[str, Any], *, allow_default: bool = True) -> str:
    labelled_name = name
    if spec.get("label") is not None:
        labelled_name += f" {_render_atom(spec['label'], text=True)}"
    parts = [f"{labelled_name}: {_render_type(spec)}"]
    if allow_default and "default" in spec:
        parts.append(f"= {_render_atom(spec['default'])}")
    minimum = spec.get("min")
    maximum = spec.get("max")
    if minimum is not None or maximum is not None:
        parts.append(f"in {minimum if minimum is not None else '*'}..{maximum if maximum is not None else '*'}")
    if spec.get("integer"):
        parts.append("integer")
    if "allowed_values" in spec:
        allowed = ", ".join(_render_atom(item) for item in spec.get("allowed_values", []))
        parts.append(f"one-of [{allowed}]")
    unsupported = set(spec) - {
        "value_type", "domain", "unit", "default", "min", "max", "integer", "allowed_values",
        "label",
    }
    if unsupported:
        raise SchemaError(
            f"Kirin v1 renderer cannot preserve input attribute(s): {', '.join(sorted(unsupported))}"
        )
    return " ".join(parts)


def _description_block(description: str) -> List[str]:
    lines = description.splitlines()
    length = 3
    while "-" * length in lines:
        length += 1
    fence = "-" * length
    return [fence, *lines, fence]


def _render_expression(prefix: str, expression: str, indent: str = "  ") -> List[str]:
    expression_lines = expression.splitlines() or [expression]
    if len(expression_lines) == 1 and len(prefix) + len(expression_lines[0]) <= 100:
        return [prefix + expression_lines[0]]
    return [prefix.rstrip(), *(indent + "  " + line.strip() for line in expression_lines if line.strip())]


def _dimension_text(powers: Dict[str, Any]) -> str:
    if not powers:
        return "1"
    terms = []
    for name, raw_power in powers.items():
        power = Fraction(str(raw_power))
        if power == 1:
            terms.append(name)
        else:
            exponent = (
                f"({power.numerator}/{power.denominator})"
                if power.denominator != 1
                else str(power.numerator)
            )
            terms.append(f"{name} ** {exponent}")
    return " * ".join(terms)


def render_kirin_document(raw: Dict[str, Any]) -> str:
    """Render one structured schema document as canonical Kirin v1 source."""
    doc_type = raw.get("type")
    doc_id = raw.get("id")
    if raw.get("schema_version") != 1 or doc_type != "entry":
        raise SchemaError("Kirin renderer requires a schema-v1 entry")
    if not isinstance(doc_id, str):
        raise SchemaError("Kirin renderer requires a document id")
    lines = ["@kirin 1", f"@{doc_type} {doc_id}"]
    directive_map = {"game_version": "game-version", "validation_status": "status"}
    for source, directive in directive_map.items():
        if source in raw:
            lines.append(f"@{directive} {_render_atom(raw[source], text=True)}")
    lines.extend(["", f"// {str(raw.get('name', doc_id)).replace(chr(10), ' ')}"])
    if "description" in raw:
        lines.extend(["", *_description_block(str(raw["description"]))])

    if raw.get("sources"):
        lines.extend(["", "sources:"])
        for source in raw["sources"]:
            lines.append(f"  {_render_atom(source, text=isinstance(source, str))}")

    semantics = raw.get("semantics", {})
    dimensions = semantics.get("dimensions", {})
    if dimensions:
        lines.extend(["", "dimensions:"])
        for name, metadata in dimensions.items():
            label = metadata.get("name") if isinstance(metadata, dict) else None
            lines.append(f"  {name}" + (f" {_render_atom(label, text=True)}" if label else ""))
    units = semantics.get("units", {})
    if units:
        lines.extend(["", "units:"])
        for name, spec in units.items():
            dimension_text = _dimension_text(spec.get("dimensions", {}))
            scale = str(spec.get("scale", "1"))
            expression = dimension_text if scale == "1" else f"{scale} * {dimension_text}"
            lines.append(f"  {name} = {expression}")
    domains = semantics.get("domains", {})
    if domains:
        lines.extend(["", "domains:"])
        for name, spec in domains.items():
            lines.append(f"  {_render_input(name, spec, allow_default=False)}")

    if raw.get("aliases"):
        lines.extend(["", "aliases:"])
        for alias, target in raw["aliases"].items():
            lines.append(f"  {alias} = {target}")

    if raw.get("inputs"):
        lines.extend(["", "inputs:"])
        for name, spec in raw["inputs"].items():
            lines.append(f"  {_render_input(name, spec)}")
    if raw.get("constraints"):
        lines.extend(["", "constraints:"])
        for expression in raw["constraints"]:
            lines.append(f"  {' '.join(str(expression).split())}")

    fields = raw.get("fields", {})
    if fields:
        lines.extend(["", "fields:"])
        for name, spec in fields.items():
            unsupported = set(spec) - {"kind", "value", "value_type", "unit", "expression", "label"}
            if unsupported:
                raise SchemaError(
                    f"Kirin v1 renderer cannot preserve field {name!r} attribute(s): {', '.join(sorted(unsupported))}"
                )
            type_text = "boolean" if spec.get("value_type") == "boolean" else str(spec.get("unit", "dimensionless"))
            labelled_name = name
            if spec.get("label") is not None:
                labelled_name += f" {_render_atom(spec['label'], text=True)}"
            if spec.get("kind") == "value":
                lines.append(f"  {labelled_name}: {type_text} = {_render_atom(spec.get('value'))}")
            elif spec.get("kind") == "expression":
                lines.extend(
                    _render_expression(
                        f"  {labelled_name}: {type_text} = ",
                        str(spec.get("expression", "")),
                        "  ",
                    )
                )
            else:
                raise SchemaError(f"unknown field kind {spec.get('kind')!r}")

    if raw.get("functions"):
        lines.extend(["", "functions:"])
        for name, spec in raw["functions"].items():
            unsupported = set(spec) - {"parameters", "expression", "unit", "label"}
            if unsupported:
                raise SchemaError(
                    f"Kirin v1 renderer cannot preserve function {name!r} attribute(s): {', '.join(sorted(unsupported))}"
                )
            parameters = ", ".join(
                _render_input(parameter, parameter_spec, allow_default=False)
                for parameter, parameter_spec in spec.get("parameters", {}).items()
            )
            labelled_name = name
            if spec.get("label") is not None:
                labelled_name += f" {_render_atom(spec['label'], text=True)}"
            prefix = f"  {labelled_name}({parameters}) -> {spec.get('unit', 'dimensionless')} = "
            lines.extend(_render_expression(prefix, str(spec.get("expression", "")), "  "))
    if raw.get("tables"):
        lines.extend(["", "tables:"])
        for name, spec in raw["tables"].items():
            label = spec.get("label", name)
            label_suffix = f" {_render_atom(label, text=True)}" if label != name else ""
            lines.append(
                f"  {name}{label_suffix}: {spec.get('input_unit', 'dimensionless')}"
                f" -> {spec.get('unit', 'dimensionless')}:"
            )
            for x, y in spec.get("points", []):
                lines.append(f"    {_render_atom(x)} = {_render_atom(y)}")
    if raw.get("distributions"):
        lines.extend(["", "distributions:"])
        for name, spec in raw["distributions"].items():
            unsupported = set(spec) - {"label", "unit", "outcomes"}
            if unsupported:
                raise SchemaError(
                    f"Kirin v1 renderer cannot preserve distribution {name!r} attribute(s): "
                    + ", ".join(sorted(unsupported))
                )
            label = spec.get("label", name)
            label_suffix = f" {_render_atom(label, text=True)}" if label != name else ""
            lines.append(
                f"  {name}{label_suffix}: {spec.get('unit', 'dimensionless')}:"
            )
            outcomes = spec.get("outcomes", [])
            if not isinstance(outcomes, list):
                raise SchemaError(f"distribution {name!r} outcomes must be a list")
            for outcome in outcomes:
                if not isinstance(outcome, dict) or set(outcome) != {"value", "probability"}:
                    raise SchemaError(
                        f"distribution {name!r} outcomes require value and probability"
                    )
                lines.append(
                    f"    {str(outcome['value']).strip()} @ {str(outcome['probability']).strip()}"
                )
    if raw.get("recurrences"):
        lines.extend(["", "recurrences:"])
        for name, spec in raw["recurrences"].items():
            unsupported = set(spec) - {
                "label", "unit", "initial", "steps", "current", "index", "next"
            }
            if unsupported:
                raise SchemaError(
                    f"Kirin v1 renderer cannot preserve recurrence {name!r} attribute(s): "
                    + ", ".join(sorted(unsupported))
                )
            label = spec.get("label", name)
            label_suffix = f" {_render_atom(label, text=True)}" if label != name else ""
            lines.append(f"  {name}{label_suffix}: {spec.get('unit', 'dimensionless')}:")
            lines.extend(
                _render_expression("    initial = ", str(spec.get("initial", "")), "    ")
            )
            lines.extend(
                _render_expression("    steps = ", str(spec.get("steps", "")), "    ")
            )
            next_prefix = f"    next({spec.get('current')}, {spec.get('index')}) = "
            lines.extend(
                _render_expression(next_prefix, str(spec.get("next", "")), "    ")
            )
    if raw.get("state_models"):
        lines.extend(["", "state_models:"])
        for name, spec in raw["state_models"].items():
            unsupported = set(spec) - {"label", "states", "transitions", "rewards"}
            if unsupported:
                raise SchemaError(
                    f"Kirin v1 renderer cannot preserve state model {name!r} attribute(s): "
                    + ", ".join(sorted(unsupported))
                )
            label = spec.get("label", name)
            label_suffix = f" {_render_atom(label, text=True)}" if label != name else ""
            lines.extend([f"  {name}{label_suffix}:", "    states:"])
            for state in spec.get("states", []):
                lines.append(f"      {state}")
            lines.append("    transitions:")
            for transition in spec.get("transitions", []):
                lines.append(
                    f"      {transition.get('source')} -> {transition.get('target')}"
                    f" @ {transition.get('probability')}"
                )
            rewards = spec.get("rewards", {})
            if rewards:
                lines.append("    rewards:")
                for reward_id, reward in rewards.items():
                    reward_label = reward.get("label", reward_id)
                    reward_label_suffix = (
                        f" {_render_atom(reward_label, text=True)}"
                        if reward_label != reward_id
                        else ""
                    )
                    lines.append(
                        f"      {reward_id}{reward_label_suffix}:"
                        f" {reward.get('unit', 'dimensionless')}:"
                    )
                    for state, expression in reward.get("values", {}).items():
                        lines.extend(
                            _render_expression(
                                f"        {state} = ", str(expression), "        "
                            )
                        )
    if raw.get("outputs"):
        lines.extend(["", "outputs:"])
        for name, spec in raw["outputs"].items():
            unsupported = set(spec) - {"expression", "unit", "label", "display", "digits"}
            if unsupported:
                raise SchemaError(
                    f"Kirin v1 renderer cannot preserve output {name!r} attribute(s): {', '.join(sorted(unsupported))}"
                )
            labelled_name = name
            if spec.get("label") is not None:
                labelled_name += f" {_render_atom(spec['label'], text=True)}"
            prefix = f"  {labelled_name}: {spec.get('unit', 'dimensionless')} = "
            lines.extend(_render_expression(prefix, str(spec.get("expression", "")), "  "))

    if raw.get("groups"):
        lines.extend(["", "groups:"])
        for group_id, spec in raw["groups"].items():
            label = spec.get("label", group_id)
            label_suffix = f" {_render_atom(label, text=True)}" if label != group_id else ""
            lines.append(f"  {group_id}{label_suffix}:")
            for output in spec.get("outputs", []):
                lines.append(f"    {output}")

    if raw.get("presets"):
        lines.extend(["", "presets:"])
        for preset_id, spec in raw["presets"].items():
            label = spec.get("label", preset_id)
            label_suffix = f" {_render_atom(label, text=True)}" if label != preset_id else ""
            lines.append(f"  {preset_id}{label_suffix}:")
            for name, value in spec.get("values", {}).items():
                lines.append(f"    {name} = {_render_atom(value)}")

    display_items = [
        (name, spec)
        for name, spec in raw.get("outputs", {}).items()
        if spec.get("display") is not None or spec.get("digits") is not None
    ]
    if display_items:
        lines.extend(["", "display:"])
        for name, spec in display_items:
            declaration = f"  {name}: {spec.get('display', 'number')}"
            if spec.get("digits") is not None:
                declaration += f" digits {spec['digits']}"
            lines.append(declaration)

    chart_keys = {"x", "range", "points", "y"}
    if chart_keys.intersection(raw):
        missing = sorted(chart_keys - set(raw))
        if missing:
            raise SchemaError(
                "Kirin v1 renderer requires a complete chart configuration; missing: "
                + ", ".join(missing)
            )
        lines.extend(
            [
                "",
                f"x: {raw['x']}",
                f"range: {raw['range'][0]}..{raw['range'][1]}",
                f"points: {raw['points']}",
                "",
                "y:",
            ]
        )
        labels = raw.get("curve_labels", {})
        for target in raw.get("y", []):
            suffix = f" as {_render_atom(labels[target], text=True)}" if target in labels else ""
            lines.append(f"  {target}{suffix}")
        chart_options = {
            "preset": "preset",
            "title": "title",
            "x_label": "x-label",
            "y_label": "y-label",
            "out": "export-svg",
            "data_out": "export-csv",
        }
        for source, target in chart_options.items():
            if raw.get(source) is not None:
                lines.append(f"{target}: {_render_atom(raw[source], text=True)}")

    allowed = {
        "schema_version", "id", "name", "type", "description", "sources",
        "game_version", "validation_status", "semantics", "aliases", "inputs", "constraints", "fields",
        "functions", "tables", "distributions", "recurrences", "state_models", "outputs", "groups", "presets", "x", "range", "points", "y",
        "preset", "out", "data_out", "title", "x_label", "y_label", "curve_labels",
    }
    unsupported = set(raw) - allowed
    if unsupported:
        raise SchemaError(f"Kirin v1 renderer cannot preserve entry key(s): {', '.join(sorted(unsupported))}")
    return "\n".join(lines).rstrip() + "\n"


def load_kirin_document(
    path: Path, text_override: Optional[str] = None
) -> Tuple[Dict[str, Any], str, str, Dict[str, Tuple[int, int]]]:
    """Load a Kirin document from disk or an unsaved editor buffer."""
    if text_override is None:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > MAX_SOURCE_BYTES:
            raise SchemaError(
                f"Kirin source file exceeds {MAX_SOURCE_BYTES} bytes",
                SourceLocation(path=str(path)),
            )
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("Kirin source files must be UTF-8", SourceLocation(path=str(path))) from exc
    else:
        text = text_override
        raw_bytes = text.encode("utf-8")
        if len(raw_bytes) > MAX_SOURCE_BYTES:
            raise SchemaError(
                f"Kirin source buffer exceeds {MAX_SOURCE_BYTES} bytes",
                SourceLocation(path=str(path)),
            )
    raw, positions = parse_kirin_source(text, path)
    return raw, text, hashlib.sha256(raw_bytes).hexdigest(), positions
