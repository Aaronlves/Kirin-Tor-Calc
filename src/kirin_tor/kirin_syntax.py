"""Shared scalar grammar and the sole public Kirin Tor source-v2 gateway."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .errors import SchemaError, SourceLocation
from .limits import MAX_SOURCE_BYTES
from .process_ast import ProcessAst
from .scenario_ast import AnalysisAst, ScenarioAst


IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
QUOTED_STRING = r'"(?:[^"\\]|\\.)*"'
_TYPE = rf"(?:boolean|number\[{IDENTIFIER}\]|{IDENTIFIER})"
_INPUT_RE = re.compile(
    rf"^(?P<name>{IDENTIFIER})(?:\s+(?P<label>{QUOTED_STRING}))?\s*:\s*(?P<type>{_TYPE})"
    r"(?:\s*=\s*(?P<default>\S+))?"
    r"(?:\s+in\s+(?P<range>\S+\.\.\S+))?"
    r"(?:\s+(?P<integer>integer))?"
    r"(?:\s+one-of\s+\[(?P<allowed>[^\]]*)\])?$"
)


@dataclass(frozen=True)
class ParsedKirinSource:
    """One parsed source with typed declarations kept outside the raw schema."""

    raw: Dict[str, Any]
    positions: Dict[str, Tuple[int, int]]
    process_asts: Tuple[ProcessAst, ...] = ()
    scenario_asts: Tuple[ScenarioAst, ...] = ()
    analysis_asts: Tuple[AnalysisAst, ...] = ()


@dataclass(frozen=True)
class LoadedKirinDocument:
    """Loaded source text, digest, static raw schema, and typed declarations."""

    raw: Dict[str, Any]
    text: str
    sha256: str
    positions: Dict[str, Tuple[int, int]]
    process_asts: Tuple[ProcessAst, ...] = ()
    scenario_asts: Tuple[ScenarioAst, ...] = ()
    analysis_asts: Tuple[AnalysisAst, ...] = ()


@dataclass(frozen=True)
class _Line:
    number: int
    raw: str

    @property
    def indent(self) -> int:
        return len(self.raw) - len(self.raw.lstrip(" "))


def _location(
    path: Path, line: Optional[_Line] = None, field: Optional[str] = None
) -> SourceLocation:
    return SourceLocation(
        path=str(path),
        field=field,
        line=line.number if line else None,
        column=(line.indent + 1) if line else None,
    )


def _fail(
    path: Path,
    message: str,
    line: Optional[_Line] = None,
    field: Optional[str] = None,
) -> None:
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


def _type_spec(type_text: str, path: Path, line: _Line) -> Dict[str, Any]:
    if type_text == "boolean":
        return {"value_type": "boolean"}
    if type_text.startswith("number["):
        return {"value_type": "number", "unit": type_text[7:-1]}
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
    """Split parameters without splitting commas inside a one-of list."""

    items: List[str] = []
    start = 0
    square_depth = 0
    for index, character in enumerate(value):
        if character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
            if square_depth < 0:
                _fail(
                    path,
                    "function parameter list has an unmatched ']'",
                    line,
                    "functions",
                )
        elif character == "," and square_depth == 0:
            item = value[start:index].strip()
            if not item:
                _fail(
                    path,
                    "function parameter list contains an empty parameter",
                    line,
                    "functions",
                )
            items.append(item)
            start = index + 1
    if square_depth:
        _fail(
            path,
            "function parameter list has an unmatched '['",
            line,
            "functions",
        )
    final = value[start:].strip()
    if not final:
        _fail(
            path,
            "function parameter list contains an empty parameter",
            line,
            "functions",
        )
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
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int)
        and not isinstance(node.value, bool)
    ):
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
    _fail(
        path,
        "dimension exponents must be exact integers or rational numbers",
        line,
        "units",
    )
    raise AssertionError("unreachable")


def _parse_dimension_expression(
    expression: str, path: Path, line: _Line
) -> Tuple[Dict[str, str], str]:
    try:
        root = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        _fail(path, f"invalid dimension expression: {exc.msg}", line, "units")

    def combine(
        left: Dict[str, Fraction], right: Dict[str, Fraction], sign: int
    ) -> Dict[str, Fraction]:
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
                {
                    name: power * exponent
                    for name, power in base.items()
                    if power * exponent
                },
                scale**exponent.numerator,
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


def parse_kirin_source(
    text: str, path: Path
) -> ParsedKirinSource:
    """Parse the sole public Kirin Tor v2 source format."""

    from .kirin_v2 import parse_kirin_v2_source

    raw, positions, process_asts, scenario_asts, analysis_asts = parse_kirin_v2_source(
        text, path
    )
    return ParsedKirinSource(
        raw, positions, process_asts, scenario_asts, analysis_asts
    )


def render_kirin_document(document: Any) -> str:
    """Render the sole public Kirin Tor v2 source format."""

    from .kirin_v2 import render_kirin_v2_document

    if isinstance(document, dict):
        raw = document
        process_asts: Tuple[ProcessAst, ...] = ()
        scenario_asts: Tuple[ScenarioAst, ...] = ()
        analysis_asts: Tuple[AnalysisAst, ...] = ()
    else:
        raw = document.raw
        process_asts = tuple(getattr(document, "process_asts", ()))
        scenario_asts = tuple(getattr(document, "scenario_asts", ()))
        analysis_asts = tuple(getattr(document, "analysis_asts", ()))
    return render_kirin_v2_document(
        raw, process_asts, scenario_asts, analysis_asts
    )


def load_kirin_document(
    path: Path, text_override: Optional[str] = None
) -> LoadedKirinDocument:
    """Load one source file or unsaved editor buffer with a stable digest."""

    if text_override is None:
        raw_bytes = path.read_bytes()
        if len(raw_bytes) > MAX_SOURCE_BYTES:
            raise SchemaError(
                f"Kirin Tor source file exceeds {MAX_SOURCE_BYTES} bytes",
                SourceLocation(path=str(path)),
            )
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError(
                "Kirin Tor source files must be UTF-8",
                SourceLocation(path=str(path)),
            ) from exc
    else:
        text = text_override
        raw_bytes = text.encode("utf-8")
        if len(raw_bytes) > MAX_SOURCE_BYTES:
            raise SchemaError(
                f"Kirin Tor source buffer exceeds {MAX_SOURCE_BYTES} bytes",
                SourceLocation(path=str(path)),
            )
    parsed = parse_kirin_source(text, path)
    return LoadedKirinDocument(
        parsed.raw,
        text,
        hashlib.sha256(raw_bytes).hexdigest(),
        parsed.positions,
        parsed.process_asts,
        parsed.scenario_asts,
        parsed.analysis_asts,
    )
