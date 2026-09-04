"""Kirin Tor completion indexing and authoring snippets for the browser editor."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import ParameterError, WorkspaceError
from .authoring_contract import (
    AUTHORING_SNIPPETS,
    PROCESS_EXPRESSION_BUILTINS,
    RUNTIME_MEASURE_SYMBOLS,
    TYPE_KEYWORDS,
)
from .scenario_measure_syntax import TRAJECTORY_MEASURE_SYNTAX

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_FENCE_RE = re.compile(r"^-{3,}$")
_ENTRY_RE = re.compile(rf"^@entry\s+({_IDENTIFIER})(?:\s+({_QUOTED}))?$")
_MEMBER_RE = re.compile(rf"^\s+(?P<name>{_IDENTIFIER})(?:\s+(?P<label>{_QUOTED}))?")
_ALIAS_RE = re.compile(
    rf"^alias\s+(?P<name>[^\s=]+)\s*=\s*"
    rf"(?P<target>{_IDENTIFIER}(?:\.{_IDENTIFIER})+)"
)
_REFERENCE_RE = re.compile(
    rf"(?<![\w.])(?P<token>{_IDENTIFIER}(?:\.{_IDENTIFIER})+|[^\W\d]\w*)(?![\w.])",
    re.UNICODE,
)


@dataclass(frozen=True)
class AuthoringSource:
    key: str
    path: str
    text: str
    read_only: bool = False


@dataclass(frozen=True)
class CompletionCandidate:
    label: str
    detail: str
    insert_text: str
    kind: str
    terms: Tuple[str, ...]
    priority: int = 100
    contexts: Tuple[str, ...] = ("all",)
    reference_topic: Optional[str] = None
    reference_symbol: Optional[str] = None
    signature: Optional[str] = None


@dataclass(frozen=True)
class _Member:
    entry_id: str
    name: str
    kind: str
    label: Optional[str]
    value_type: Optional[str] = None
    container: Optional[str] = None
    signature: Optional[str] = None
    event_direction: Optional[str] = None
    event_parameters: Tuple[Tuple[str, str], ...] = ()

    @property
    def canonical(self) -> str:
        return f"{self.entry_id}.{self.name}"


_KIND_LABELS = {
    "aliases": "别名",
    "inputs": "输入",
    "fields": "字段",
    "functions": "函数",
    "tables": "查表",
    "distributions": "有限分布",
    "outputs": "输出",
    "objects": "类型化对象",
    "object_fields": "对象属性",
    "type_fields": "类型字段",
    "processes": "过程",
    "scenarios": "场景",
    "analyses": "分析",
    "types": "结构类型",
    "alias": "别名",
    "dimensions": "量纲",
    "units": "单位",
    "domains": "值域",
    "constraints": "约束",
    "sources": "来源",
    "groups": "分组",
    "presets": "参数方案",
    "display": "显示",
    "y": "图表曲线",
    "builtin": "内置函数",
    "keyword": "关键字",
    "snippet": "片段",
    "process_inputs": "Process 输入",
    "process_states": "Process 状态",
    "process_events": "Process 事件",
    "process_actions": "Process Action",
    "process_observations": "Process Observation",
    "process_keys": "Process key",
    "process_phases": "Process phase",
    "scenario_instances": "Scenario 实例",
    "scenario_variants": "Scenario Variant",
    "scenario_actions": "Scenario Action",
    "scenario_policies": "Scenario Policy",
    "scenario_measures": "Scenario Measure",
    "scenario_objectives": "Scenario Objective",
    "analysis_charts": "Analysis Chart",
}

_COMPLETION_KINDS = {
    "inputs": "input",
    "fields": "field",
    "functions": "function",
    "tables": "table",
    "distributions": "distribution",
    "outputs": "output",
    "objects": "object",
    "object_fields": "object_field",
    "types": "type",
    "type_fields": "type_field",
    "processes": "process",
    "scenarios": "scenario",
    "analyses": "analysis",
    "process_inputs": "variable",
    "process_states": "variable",
    "process_events": "function",
    "process_actions": "function",
    "process_observations": "variable",
    "process_keys": "variable",
    "process_phases": "variable",
    "scenario_instances": "namespace",
    "scenario_variants": "variable",
    "scenario_actions": "function",
    "scenario_policies": "variable",
    "scenario_measures": "variable",
    "scenario_objectives": "variable",
    "analysis_charts": "variable",
}

_DECLARATION_KIND = {
    "input": "inputs",
    "field": "fields",
    "function": "functions",
    "table": "tables",
    "distribution": "distributions",
    "output": "outputs",
    "type": "types",
    "process": "processes",
    "scenario": "scenarios",
    "analysis": "analyses",
}

_RESERVED_DECLARATIONS = {
    "dimension", "unit", "domain", "source", "alias", "input", "field",
    "require", "function", "output", "group", "preset", "table",
    "distribution", "display", "chart", "type",
    "process", "scenario", "analysis",
}


def _snippet(
    label: str,
    trigger: str,
    english: str,
    text: str,
    priority: int,
    contexts: Tuple[str, ...] = ("all",),
    reference_topic: Optional[str] = None,
    reference_symbol: Optional[str] = None,
) -> CompletionCandidate:
    return CompletionCandidate(
        label,
        f"片段 · {english}",
        text,
        "snippet",
        (trigger, english),
        priority,
        contexts,
        reference_topic,
        reference_symbol,
    )


SNIPPETS = tuple(_snippet(*spec) for spec in AUTHORING_SNIPPETS)


BUILTIN_COMPLETIONS = (
    CompletionCandidate("绝对值", "内置函数 · abs", "abs($0)", "builtin", ("abs", "绝对值"), 24),
    CompletionCandidate("平方根", "内置函数 · sqrt", "sqrt($0)", "builtin", ("sqrt", "平方根", "根号"), 24),
    CompletionCandidate("最小值", "内置函数 · min", "min($0)", "builtin", ("min", "最小值"), 24),
    CompletionCandidate("最大值", "内置函数 · max", "max($0)", "builtin", ("max", "最大值"), 24),
    CompletionCandidate("向下取整", "内置函数 · floor", "floor($0)", "builtin", ("floor", "向下取整"), 24),
    CompletionCandidate("向上取整", "内置函数 · ceil", "ceil($0)", "builtin", ("ceil", "向上取整"), 24),
    CompletionCandidate(
        "有限求和",
        "内置函数 · sum",
        "sum(expression, index, lower, $0)",
        "builtin",
        ("sum", "求和", "有限求和"),
        24,
    ),
    CompletionCandidate(
        "有限连乘",
        "内置函数 · product",
        "product(expression, index, lower, $0)",
        "builtin",
        ("product", "连乘", "有限连乘"),
        24,
    ),
    CompletionCandidate(
        "精确查表",
        "内置函数 · lookup",
        "lookup(table_name, $0)",
        "builtin",
        ("lookup", "查表", "精确查表"),
        24,
    ),
    CompletionCandidate(
        "线性插值",
        "内置函数 · interpolate",
        "interpolate(table_name, $0)",
        "builtin",
        ("interpolate", "插值", "线性插值"),
        24,
    ),
    CompletionCandidate(
        "分布期望",
        "内置函数 · expectation",
        "expectation($0)",
        "builtin",
        ("expectation", "期望", "分布期望"),
        24,
    ),
    CompletionCandidate(
        "分布方差",
        "内置函数 · variance",
        "variance($0)",
        "builtin",
        ("variance", "方差", "分布方差"),
        24,
    ),
    CompletionCandidate(
        "结果概率",
        "内置函数 · probability",
        "probability(distribution, $0)",
        "builtin",
        ("probability", "概率", "结果概率"),
        24,
    ),
    CompletionCandidate(
        "映射分布",
        "分布函数 · map",
        "map(distribution, value, $0)",
        "builtin",
        ("map", "映射", "分布映射"),
        24,
    ),
    CompletionCandidate(
        "独立分布求和",
        "分布函数 · independent_sum",
        "independent_sum(first_distribution, $0)",
        "builtin",
        ("independent_sum", "独立", "卷积"),
        24,
    ),
    CompletionCandidate(
        "独立重复求和",
        "分布函数 · repeat_sum",
        "repeat_sum(distribution, $0)",
        "builtin",
        ("repeat_sum", "重复试验", "重复求和"),
        24,
    ),
    CompletionCandidate(
        "条件分布",
        "分布函数 · condition",
        "condition(distribution, value, $0)",
        "builtin",
        ("condition", "条件分布", "条件化"),
        24,
    ),
    *(
        CompletionCandidate(
            item.label,
            f"轨迹 Measure · {item.name}",
            item.insertion,
            "measure",
            (item.name, item.label, *item.terms),
            23,
        )
        for item in TRAJECTORY_MEASURE_SYNTAX
    ),
    CompletionCandidate("布尔真", "关键字 · true", "true", "keyword", ("true", "真"), 26),
    CompletionCandidate("布尔假", "关键字 · false", "false", "keyword", ("false", "假"), 26),
    CompletionCandidate(
        "无量纲数值类型",
        "类型 · number[dimensionless]",
        "number[dimensionless]",
        "keyword",
        ("number", "dimensionless", "数值", "无量纲"),
        27,
    ),
    CompletionCandidate("布尔类型", "类型 · boolean", "boolean", "keyword", ("boolean", "布尔"), 27),
    CompletionCandidate("整数约束", "关键字 · integer", "integer", "keyword", ("integer", "整数"), 27),
    CompletionCandidate(
        "有限允许值",
        "关键字 · one-of",
        "one-of [$0]",
        "keyword",
        ("one-of", "允许值", "枚举"),
        27,
    ),
)


def _completion_name(candidate: CompletionCandidate) -> str:
    match = re.match(_IDENTIFIER, candidate.insert_text)
    return match.group(0) if match else candidate.insert_text


_enriched_builtins: list[CompletionCandidate] = []
for _candidate in BUILTIN_COMPLETIONS:
    _name = _completion_name(_candidate)
    if _candidate.kind == "measure":
        _contexts = ("measure_expr",)
        _topic, _symbol = "process", "scenario-measures-objectives"
    elif _candidate.kind == "keyword" and _name in {"true", "false"}:
        _contexts = ("static_expr", "process_expr", "measure_expr")
        _topic, _symbol = "semantics", "scalar-expression"
    elif _candidate.kind == "keyword":
        _contexts = (
            "type", "process_type", "static_expr", "process_expr", "measure_expr"
        )
        _topic, _symbol = "semantics", "scalar-expression"
    else:
        _contexts = ("static_expr",)
        _topic = "distributions" if _name in {
            "expectation", "variance", "probability", "map", "independent_sum",
            "repeat_sum", "condition",
        } else "tables" if _name in {"lookup", "interpolate"} else "members"
        _symbol = (
            "distribution-observers" if _name in {"expectation", "variance", "probability"}
            else "distribution-transforms" if _name in {"map", "independent_sum", "repeat_sum", "condition"}
            else "table-functions" if _name in {"lookup", "interpolate"}
            else "scalar-expression"
        )
    _enriched_builtins.append(replace(
        _candidate,
        contexts=_contexts,
        reference_topic=_topic,
        reference_symbol=_symbol,
        signature=_candidate.insert_text.replace("$0", "…"),
    ))

for _name, _signature in PROCESS_EXPRESSION_BUILTINS.items():
    _insertion = f"{_name}($0)" if _signature != f"{_name}()" else f"{_name}()$0"
    _enriched_builtins.append(CompletionCandidate(
        _name,
        f"Process 内建函数 · {_signature}",
        _insertion,
        "builtin",
        (_name, _signature, "Process", "集合"),
        24,
        ("process_expr", "measure_expr"),
        "process",
        "process-expressions",
        _signature,
    ))

for _type_name in TYPE_KEYWORDS:
    if any(
        _completion_name(candidate) == _type_name
        and {"type", "process_type"}.issubset(candidate.contexts)
        for candidate in _enriched_builtins
    ):
        continue
    _insertion = {
        "number": "number[$0]",
        "list": "list[$0, capacity]",
        "map": "map[$0, value_type, capacity]",
    }.get(_type_name, _type_name)
    _enriched_builtins.append(CompletionCandidate(
        _type_name,
        f"官方类型 · {_type_name}",
        _insertion,
        "type",
        (_type_name, "类型"),
        27,
        ("process_type",)
        if _type_name in {"event_id", "list", "map"}
        else ("type", "process_type", "static_expr", "process_expr", "measure_expr")
        if _type_name in {"second", "millisecond"}
        else ("type", "process_type"),
        "process" if _type_name in {"event_id", "list", "map"} else "semantics",
        "process-types" if _type_name in {"event_id", "list", "map"} else "scalar-expression",
        _type_name,
    ))

for _name, _description in RUNTIME_MEASURE_SYMBOLS.items():
    _enriched_builtins.append(CompletionCandidate(
        _name,
        f"Scenario 运行时符号 · {_description}",
        _name,
        "variable",
        (_name, _description, "运行时"),
        22,
        ("measure_expr",),
        "process",
        "process-expressions",
        _name,
    ))

_enriched_builtins.extend(
    CompletionCandidate(
        value,
        f"允许值 · {detail}",
        value,
        "enum",
        (value, detail),
        20,
        contexts,
        "process",
        reference,
        value,
    )
    for value, detail, contexts, reference in (
        *((value, "Analysis operation", ("analysis_operation",), "analysis") for value in ("run", "compare", "optimize", "reach", "steady", "cycle")),
        *((value, "Analysis chart kind", ("analysis_chart_kind",), "analysis-chart") for value in ("trajectory", "decision_surface", "pareto", "variant_comparison")),
        *((value, "优化方向", ("analysis_chart_direction",), "analysis-chart") for value in ("maximize", "minimize")),
        *((value, "Analysis search method", ("analysis_search_method",), "analysis") for value in ("adaptive_dyadic", "exact_grid")),
        *((value, "显示格式", ("display_format",), "display") for value in ("number", "integer", "percent", "coefficient_percent")),
        *((value, "Process event direction", ("process_event_direction",), "process-declarations") for value in ("input", "output", "internal")),
        *((value, "Process reducer", ("process_reducer",), "process-declarations") for value in ("sum", "min", "max", "all", "any")),
        *((value, "Process branch mode", ("process_branch_mode",), "process-effects") for value in ("independent", "joint")),
    )
)

BUILTIN_COMPLETIONS = tuple(_enriched_builtins)


def completion_prefix(line: str, column: int) -> Tuple[str, int]:
    """Return the Unicode identifier/member prefix ending at the cursor and its start column."""
    before = line[:column]
    match = re.search(r"[\w.]*$", before, re.UNICODE)
    prefix = match.group(0) if match else ""
    return prefix, column - len(prefix)


@dataclass(frozen=True)
class CompletionSite:
    contexts: Tuple[str, ...]
    replace_start_column: int
    line: int
    column: int
    container: Optional[str] = None
    object_type: Optional[str] = None


def _line_lexical_context(text: str, column: int) -> Optional[str]:
    """Return comment/string when the cursor is inside an opaque line region."""

    before = text[: max(0, column - 1)]
    quoted = False
    escaped = False
    index = 0
    while index < len(before):
        character = before[index]
        if quoted:
            if character == '"' and not escaped:
                quoted = False
            escaped = character == "\\" and not escaped
            if character != "\\":
                escaped = False
            index += 1
            continue
        if character == '"':
            quoted = True
            index += 1
            continue
        if character == "/" and index + 1 < len(before) and before[index + 1] == "/":
            return "comment"
        index += 1
    return "string" if quoted else None


def _authoring_block_stack(lines: Sequence[str], before_line: int) -> list[tuple[int, str]]:
    stack: list[tuple[int, str]] = []
    prose_fence: Optional[str] = None
    for raw in lines[: max(0, before_line - 1)]:
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            continue
        if not stripped or stripped.startswith("//"):
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stripped.endswith(":"):
            stack.append((indent, stripped))
    return stack


def _unclosed_delimiter_line(
    lines: Sequence[str], current_line: int, current_column: int
) -> Optional[int]:
    """Return the line containing the innermost unmatched expression delimiter."""

    stack: list[tuple[str, int]] = []
    prose_fence: Optional[str] = None
    pairs = {")": "(", "]": "[", "}": "{"}
    for line_number, raw in enumerate(lines[:current_line], 1):
        text = raw[: max(0, current_column - 1)] if line_number == current_line else raw
        stripped = text.lstrip()
        indent = len(text) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            continue
        if stack and stripped and not stripped.startswith("//"):
            opening_line = stack[-1][1]
            opening_raw = lines[opening_line - 1]
            opening_indent = len(opening_raw) - len(opening_raw.lstrip())
            if line_number > opening_line and indent <= opening_indent:
                stack.clear()
        quoted = False
        escaped = False
        index = 0
        while index < len(text):
            character = text[index]
            if quoted:
                if character == '"' and not escaped:
                    quoted = False
                escaped = character == "\\" and not escaped
                if character != "\\":
                    escaped = False
                index += 1
                continue
            if character == '"':
                quoted = True
            elif text.startswith("//", index):
                break
            elif character in "([{":
                stack.append((character, line_number))
            elif character in pairs and stack and stack[-1][0] == pairs[character]:
                stack.pop()
            index += 1
    return stack[-1][1] if stack else None


def _indented_expression_owner(
    lines: Sequence[str], current_line: int, current_indent: int
) -> Optional[int]:
    """Find the declaration/effect whose parser children are expression continuations."""

    if current_indent <= 0:
        return None
    for line_number in range(current_line - 1, 0, -1):
        raw = lines[line_number - 1]
        stripped = raw.lstrip()
        if not stripped or stripped.startswith("//"):
            continue
        indent = len(raw) - len(stripped)
        if indent >= current_indent:
            continue
        if stripped.endswith(":"):
            return None
        if "=" in stripped or re.match(
            r"^(?:require|next|let|flow|observe|measure|stop|schedule|replace)\b",
            stripped,
        ):
            return line_number
        return None
    return None


def completion_site(source: str, line: int, column: int) -> CompletionSite:
    """Classify one incomplete cursor position without accepting invalid source."""

    lines = source.split("\n")
    entry_match = next(
        (match for item in lines if (match := _ENTRY_RE.fullmatch(item.strip()))),
        None,
    )
    entry_id = entry_match.group(1) if entry_match else None
    line_number = min(max(1, line), len(lines))
    text = lines[line_number - 1]
    column_number = min(max(1, column), len(text) + 1)
    prefix, start = completion_prefix(text, column_number - 1)

    prose_fence: Optional[str] = None
    for raw in lines[: line_number - 1]:
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
        elif indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
    if prose_fence is not None:
        return CompletionSite(("prose",), start + 1, line_number, column_number)
    lexical = _line_lexical_context(text, column_number)
    if lexical:
        return CompletionSite((lexical,), start + 1, line_number, column_number)

    before = text[: column_number - 1]
    stripped_before = before.lstrip()
    indent = len(before) - len(stripped_before)
    stack = _authoring_block_stack(lines, line_number)
    while stack and stack[-1][0] >= indent:
        stack.pop()
    top = next((value for level, value in stack if level == 0), "")
    nearest = stack[-1][1] if stack else ""
    top_kind = top.split(None, 1)[0] if top else ""
    continuation_line = _unclosed_delimiter_line(lines, line_number, column_number)
    if continuation_line is None or continuation_line == line_number:
        continuation_line = _indented_expression_owner(lines, line_number, indent)
    continuation_text = lines[continuation_line - 1].lstrip() if continuation_line else ""
    continuation_context: Optional[Tuple[str, ...]] = None
    if continuation_line is not None and continuation_line < line_number:
        type_continuation = bool(
            re.match(r"^(?:input|state|event|action|let|observe)\b", continuation_text)
            and ":" in continuation_text
            and "=" not in continuation_text
        )
        if type_continuation:
            continuation_context = (
                ("process_type",) if top_kind == "process" else ("type",)
            )
        elif top_kind == "process":
            continuation_context = ("process_expr",)
        elif top_kind == "scenario":
            continuation_context = (
                ("measure_expr",)
                if continuation_text.startswith("measure ")
                else ("process_expr",)
            )
        elif top_kind == "analysis":
            continuation_context = ("process_expr", "reference")
        else:
            continuation_context = ("static_expr",)

    if continuation_context is not None:
        contexts = continuation_context
    elif indent == 0:
        if stripped_before.startswith("@") or line_number <= 2:
            contexts = ("document",)
        elif re.match(r"^(input|field|function|output)\b", stripped_before):
            contexts = ("static_expr",) if "=" in stripped_before else ("type",) if ":" in stripped_before else ("top",)
        elif stripped_before.startswith("require "):
            contexts = ("static_expr",)
        elif stripped_before.startswith("alias ") and "=" in stripped_before:
            contexts = ("reference",)
        elif stripped_before.startswith("display ") and "=" in stripped_before:
            contexts = ("display_format", "reference")
        else:
            contexts = ("top",)
        return CompletionSite(contexts, start + 1, line_number, column_number)

    elif top_kind == "process":
        if re.match(r"^on\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_handler_trigger",)
        elif re.match(r"^emit\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_emit_event",)
        elif re.match(r"^(?:schedule|replace)\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_schedule_event",)
        elif re.match(r"^(?:next|flow)\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_state_target",)
        elif re.search(r"\bphase\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_phase_target",)
        elif re.match(
            r"^(?:schedule|replace)\b.*\bkey\s+[A-Za-z0-9_.]*$",
            stripped_before,
        ):
            contexts = ("process_key_target",)
        elif re.match(r"^cancel\s+", stripped_before):
            contexts = ("process_key_target",)
        elif re.match(r"^(?:emit|schedule|replace)\b.*\(", stripped_before):
            contexts = ("process_expr",)
        elif re.match(r"^(?:schedule|replace)\b.*\bafter\s+", stripped_before):
            contexts = ("process_expr",)
        elif stripped_before.startswith("probability "):
            contexts = ("process_expr",)
        elif re.search(r"\breduce\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_reducer",)
        elif re.match(r"^event\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_event_direction",)
        elif re.match(r"^branch\s+[A-Za-z_][A-Za-z0-9_]*\s+[A-Za-z_]*$", stripped_before):
            contexts = ("process_branch_mode",)
        elif re.search(r"(?:=|\bwhen\b|\bin\b)\s*[^:]*$", stripped_before) or stripped_before.startswith("require "):
            contexts = ("process_expr",)
        elif nearest.startswith("branch "):
            contexts = ("process_probability",)
        elif nearest.startswith(("on ", "when ", "probability ")):
            contexts = ("process_effect",)
        elif ":" in stripped_before and stripped_before.startswith(("input ", "state ", "event ", "action ", "let ", "observe ")):
            contexts = ("process_type",)
        else:
            contexts = ("process_decl",)
    elif top_kind == "scenario":
        if stripped_before.startswith("measure ") and "=" in stripped_before:
            contexts = (
                ("measure_sum_event_parameter",)
                if re.search(r"\bsum_events\([^)]*$", stripped_before)
                else ("measure_count_event",)
                if re.search(r"\bcount_events\([^)]*$", stripped_before)
                else ("measure_expr",)
            )
        elif stripped_before.startswith("connect "):
            contexts = (
                ("scenario_connect_target",)
                if "->" in stripped_before
                else ("scenario_connect_source",)
            )
        elif stripped_before.startswith("decide after "):
            contexts = ("scenario_public_event",)
        elif stripped_before.startswith("send "):
            contexts = (
                ("scenario_send_action",)
                if nearest.startswith("action ")
                else ("scenario_send_scheduled",)
            )
        elif re.match(r"^use\s+[A-Za-z_][A-Za-z0-9_]*\s*=", stripped_before):
            contexts = ("process_reference",)
        elif nearest == "bounds:":
            contexts = ("process_expr", "scenario_bounds")
        elif nearest.startswith("use "):
            contexts = ("scenario_binding", "process_expr")
        elif nearest.startswith("policy "):
            contexts = ("scenario_policy", "process_expr")
        elif nearest.startswith(("action ", "at ", "every ")):
            contexts = ("process_expr",)
        elif nearest.startswith("decide "):
            contexts = ("scenario_decision_option",)
        elif re.search(r"(?:=|\bwhen\b|\bfrom\b|\buntil\b)\s*[^:]*$", stripped_before):
            contexts = ("process_expr",)
        else:
            contexts = ("scenario_decl",)
    elif top_kind == "analysis":
        if nearest == "search:":
            if re.match(r"^\s*method\s*=", before):
                contexts = ("analysis_search_method",)
            else:
                contexts = ("analysis_search", "process_expr")
        elif any(value.startswith("chart ") for _level, value in stack):
            if re.match(r"^\s*kind\s*=", before):
                contexts = ("analysis_chart_kind",)
            elif re.match(r"^\s*[xy]_direction\s*=", before):
                contexts = ("analysis_chart_direction",)
            elif re.match(r"^\s*-\s+event\s+", before):
                contexts = ("analysis_public_event",)
            else:
                contexts = ("analysis_chart", "reference")
        elif re.match(r"^\s*operation\s*=", before):
            contexts = ("analysis_operation",)
        elif re.match(r"^\s*using\s*=", before):
            contexts = ("scenario_reference",)
        else:
            contexts = ("analysis_decl", "reference")
    elif top_kind == "type":
        contexts = ("type_field", "type")
    elif top_kind == "source":
        contexts = ("source_body",)
    elif top_kind == "group":
        contexts = ("group_body", "reference")
    elif top_kind in {"table", "distribution", "chart", "preset"}:
        contexts = (f"{top_kind}_body", "static_expr", "reference")
    elif top:
        contexts = ("object_field", "static_expr", "type")
    else:
        contexts = ("top",)
    top_declaration = _top_declaration(top) if top else None
    container = (
        f"{entry_id}.{top_declaration['name']}"
        if entry_id and top_declaration and top_declaration["kind"] in {"processes", "scenarios", "analyses"}
        else None
    )
    object_type = (
        top_declaration["keyword"]
        if top_declaration and top_declaration["kind"] == "objects"
        else None
    )
    return CompletionSite(contexts, start + 1, line_number, column_number, container, object_type)


def _process_local_candidates(
    source: str, site: Optional[CompletionSite]
) -> list[CompletionCandidate]:
    """Project locals that are valid at one Process expression/effect cursor."""

    if site is None or site.container is None:
        return []
    lines = source.splitlines()
    if not lines or site.line > len(lines):
        return []
    process_start: Optional[int] = None
    child_indent: Optional[int] = None
    for index, raw in enumerate(lines[: site.line], 1):
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)
        if indent == 0 and stripped:
            declaration = _top_declaration(stripped)
            candidate = (
                f"{site.container.split('.', 1)[0]}.{declaration['name']}"
                if declaration and declaration["kind"] == "processes"
                else None
            )
            process_start = index if candidate == site.container else None
            child_indent = None
        elif process_start is not None and stripped and not stripped.startswith("//"):
            child_indent = indent if child_indent is None else child_indent
    if process_start is None or child_indent is None:
        return []

    current_text = lines[site.line - 1][: max(0, site.column - 1)]
    current_indent = len(current_text) - len(current_text.lstrip())
    locals_by_name: dict[str, tuple[str, str, Tuple[str, ...]]] = {}

    def add(
        name: str,
        detail: str,
        signature: str,
        contexts: Tuple[str, ...] = ("process_expr",),
    ) -> None:
        if re.fullmatch(_IDENTIFIER, name):
            locals_by_name[name] = (detail, signature, contexts)

    # Action parameters and flow locals exist only in their declaration expression.
    action = re.match(
        rf"^\s*action\s+{_IDENTIFIER}\((?P<parameters>.*?)\).*?\bwhen\b",
        current_text,
    )
    if action:
        for name in re.findall(rf"({_IDENTIFIER})\s*:", action.group("parameters")):
            add(name, "Process action 参数", action.group(0).strip())
    flow = re.match(
        rf"^\s*flow\s+{_IDENTIFIER}\(\s*(?P<current>{_IDENTIFIER})\s*,\s*"
        rf"(?P<elapsed>{_IDENTIFIER})\s*\)\s*=",
        current_text,
    )
    if flow:
        add(flow.group("current"), "Process flow 当前值", flow.group(0).strip())
        add(flow.group("elapsed"), "Process flow 经过时间", flow.group(0).strip())

    active_handler: Optional[tuple[int, int, str]] = None
    for index in range(process_start + 1, site.line + 1):
        raw = lines[index - 1]
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)
        if not stripped or stripped.startswith("//"):
            continue
        if indent == child_indent:
            handler = re.match(
                rf"^on\s+{_IDENTIFIER}\((?P<bindings>.*?)\)(?:\s+when\s+.*?)?:?$",
                stripped,
            )
            active_handler = (
                (index, indent, stripped)
                if handler and (index == site.line or stripped.endswith(":"))
                else None
            )
    if active_handler is not None:
        handler_line, handler_indent, handler_signature = active_handler
        handler = re.match(
            rf"^on\s+{_IDENTIFIER}\((?P<bindings>.*?)\)", handler_signature
        )
        assert handler is not None
        for name in re.findall(_IDENTIFIER, handler.group("bindings")):
            add(name, "Process handler 参数", handler_signature)
        locals_by_name["event.id"] = (
            "Process handler 事件身份",
            "event.id",
            ("process_expr", "process_key_target"),
        )
        locals_by_name["event.time"] = (
            "Process handler 事件时间",
            "event.time",
            ("process_expr",),
        )

        # A let is visible after its declaration while the cursor remains in the
        # same effect sequence (or one of that sequence's nested blocks).
        for index in range(handler_line + 1, site.line):
            raw = lines[index - 1]
            stripped = raw.lstrip()
            indent = len(raw) - len(stripped)
            local = re.match(
                rf"^let\s+(?P<name>{_IDENTIFIER})\s*:\s*(?P<type>[^\s=]+)\s*=",
                stripped,
            )
            if local is None:
                continue
            parent_indent = handler_indent
            for parent_index in range(index - 1, handler_line - 1, -1):
                parent_raw = lines[parent_index - 1]
                parent_stripped = parent_raw.lstrip()
                parent_level = len(parent_raw) - len(parent_stripped)
                if parent_stripped.endswith(":") and parent_level < indent:
                    parent_indent = parent_level
                    break
            scope_ended = any(
                candidate.strip()
                and not candidate.lstrip().startswith("//")
                and len(candidate) - len(candidate.lstrip()) <= parent_indent
                for candidate in lines[index: site.line]
            )
            if not scope_ended and indent <= current_indent:
                add(
                    local.group("name"),
                    f"Process let 局部值 · {local.group('type')}",
                    stripped.split("=", 1)[0].rstrip(),
                )

    return [
        CompletionCandidate(
            name,
            detail,
            name,
            "variable",
            (name, detail, "局部"),
            4,
            contexts,
            "process",
            "process-declarations",
            signature,
        )
        for name, (detail, signature, contexts) in locals_by_name.items()
    ]


def _decode_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, str) and decoded else None


def _top_declaration(line: str) -> Optional[dict[str, Any]]:
    """Recognize one tolerant v2 top-level declaration for authoring projections."""

    scalar = re.match(
        rf"^(input|field|output)\s+({_IDENTIFIER})(?:\s+({_QUOTED}))?\s*:",
        line,
    )
    if scalar:
        return {
            "keyword": scalar.group(1),
            "kind": _DECLARATION_KIND[scalar.group(1)],
            "name": scalar.group(2),
            "label": _decode_label(scalar.group(3)),
            "start": scalar.start(2),
            "end": scalar.end(2),
        }
    function = re.match(
        rf"^function\s+({_IDENTIFIER})(?:\s+({_QUOTED}))?\s*\((.*?)\)\s*:",
        line,
    )
    if function:
        return {
            "keyword": "function",
            "kind": "functions",
            "name": function.group(1),
            "label": _decode_label(function.group(2)),
            "parameters": re.findall(rf"({_IDENTIFIER})\s*:", function.group(3)),
            "start": function.start(1),
            "end": function.end(1),
        }
    semantic = re.match(
        rf"^(dimension|unit|domain)\s+({_IDENTIFIER})(?:\s+({_QUOTED}))?",
        line,
    )
    if semantic:
        return {
            "keyword": semantic.group(1),
            "kind": semantic.group(1) + "s",
            "name": semantic.group(2),
            "label": _decode_label(semantic.group(3)),
            "start": semantic.start(2),
            "end": semantic.end(2),
        }
    named = re.match(
        rf"^({_IDENTIFIER}(?:\.{_IDENTIFIER})*)\s+({_IDENTIFIER})"
        rf"(?:\s+({_QUOTED}))?(?=\s*:)",
        line,
    )
    if named:
        keyword = named.group(1)
        kind = _DECLARATION_KIND.get(keyword)
        if kind is None and keyword not in _RESERVED_DECLARATIONS:
            kind = "objects"
        if kind is not None:
            return {
                "keyword": keyword,
                "kind": kind,
                "name": named.group(2),
                "label": _decode_label(named.group(3)),
                "start": named.start(2),
                "end": named.end(2),
            }
    return None


def _type_fields(lines: Sequence[str]) -> dict[str, list[tuple[str, str, Optional[str]]]]:
    result: dict[str, list[tuple[str, str, Optional[str]]]] = {}
    active: Optional[str] = None
    child_indent: Optional[int] = None
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if not stripped or stripped.startswith("//"):
            continue
        if indent == 0:
            declaration = _top_declaration(stripped)
            active = declaration["name"] if declaration and declaration["kind"] == "types" else None
            child_indent = None
            if active:
                result.setdefault(active, [])
            continue
        if active is None:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        field = re.match(
            rf"^({_IDENTIFIER})\??(?:\s+({_QUOTED}))?\s*:\s*"
            rf"(boolean|number\[{_IDENTIFIER}\]|{_IDENTIFIER}(?:\.{_IDENTIFIER})*)",
            stripped,
        )
        if field:
            result[active].append(
                (field.group(1), field.group(3), _decode_label(field.group(2)))
            )
    return result


def _dynamic_declarations(source: str, entry_id: Optional[str]) -> list[dict[str, Any]]:
    """Index named declarations inside Process, Scenario and Analysis blocks."""

    if entry_id is None:
        return []
    result: list[dict[str, Any]] = []
    active_kind: Optional[str] = None
    active_name: Optional[str] = None
    child_indent: Optional[int] = None
    prose_fence: Optional[str] = None

    def add(
        line_number: int,
        line: str,
        indent: int,
        match: re.Match[str],
        kind: str,
        name_group: str = "name",
        label_group: Optional[str] = "label",
        event_direction: Optional[str] = None,
        event_parameters: Tuple[Tuple[str, str], ...] = (),
    ) -> None:
        name = match.group(name_group)
        label_text = match.groupdict().get(label_group) if label_group else None
        result.append({
            "id": f"{entry_id}.{active_name}:{kind}:{name}",
            "entry_id": entry_id,
            "container": f"{entry_id}.{active_name}",
            "container_kind": active_kind,
            "name": name,
            "label": _decode_label(label_text) or name,
            "kind": kind,
            "signature": line.strip(),
            "event_direction": event_direction,
            "event_parameters": event_parameters,
            "line": line_number,
            "start": indent + match.start(name_group),
            "end": indent + match.end(name_group),
        })

    for line_number, line in enumerate(source.splitlines(), 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            continue
        if not stripped or stripped.startswith("//"):
            continue
        if indent == 0:
            declaration = _top_declaration(stripped)
            if declaration and declaration["kind"] in {"processes", "scenarios", "analyses"}:
                active_kind = declaration["kind"]
                active_name = declaration["name"]
            else:
                active_kind = None
                active_name = None
            child_indent = None
            continue
        if active_kind is None or active_name is None:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue

        if active_kind == "processes":
            typed = re.match(
                rf"^(?P<kind>input|state|observe)\s+(?P<name>{_IDENTIFIER})"
                rf"(?:\s+(?P<label>{_QUOTED}))?\s*:",
                stripped,
            )
            if typed:
                add(line_number, line, indent, typed, {
                    "input": "process_input",
                    "state": "process_state",
                    "observe": "process_observation",
                }[typed.group("kind")])
                continue
            event = re.match(
                rf"^event\s+(?P<direction>input|output|internal)\s+"
                rf"(?P<name>{_IDENTIFIER})\((?P<parameters>.*)\)$",
                stripped,
            )
            if event:
                add(
                    line_number,
                    line,
                    indent,
                    event,
                    "process_event",
                    label_group=None,
                    event_direction=event.group("direction"),
                    event_parameters=_parameter_declarations(event.group("parameters")),
                )
                continue
            action = re.match(rf"^action\s+(?P<name>{_IDENTIFIER})\(", stripped)
            if action:
                add(line_number, line, indent, action, "process_action", label_group=None)
                continue
            slot = re.match(rf"^(?P<kind>key|phase)\s+(?P<name>{_IDENTIFIER})$", stripped)
            if slot:
                add(line_number, line, indent, slot, f"process_{slot.group('kind')}", label_group=None)
                continue
        elif active_kind == "scenarios":
            use = re.match(rf"^use\s+(?P<name>{_IDENTIFIER})\s*=", stripped)
            if use:
                add(line_number, line, indent, use, "scenario_instance", label_group=None)
                continue
            action = re.match(
                rf"^action\s+(?P<name>{_IDENTIFIER})(?:\s+when\s+.+)?:$",
                stripped,
            )
            if action:
                add(line_number, line, indent, action, "scenario_action", label_group=None)
                continue
            named = re.match(
                rf"^(?P<kind>variant|policy|objective)\s+(?P<name>{_IDENTIFIER})"
                rf"(?:\s+(?P<label>{_QUOTED}))?\s*:",
                stripped,
            )
            if named:
                add(line_number, line, indent, named, f"scenario_{named.group('kind')}")
                continue
            measure = re.match(
                rf"^measure\s+(?P<name>{_IDENTIFIER})(?:\s+(?P<label>{_QUOTED}))?\s*:",
                stripped,
            )
            if measure:
                add(line_number, line, indent, measure, "scenario_measure")
                continue
        elif active_kind == "analyses":
            chart = re.match(
                rf"^chart\s+(?P<name>{_IDENTIFIER})(?:\s+(?P<label>{_QUOTED}))?\s*:",
                stripped,
            )
            if chart:
                add(line_number, line, indent, chart, "analysis_chart")
    return result


@lru_cache(maxsize=512)
def _dynamic_bindings(source: str, entry_id: Optional[str]) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    instances: dict[str, dict[str, str]] = {}
    analyses: dict[str, str] = {}
    if entry_id is None:
        return instances, analyses
    active_kind: Optional[str] = None
    active_container: Optional[str] = None
    child_indent: Optional[int] = None
    prose_fence: Optional[str] = None
    for line in source.splitlines():
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            continue
        if not stripped or stripped.startswith("//"):
            continue
        if indent == 0:
            declaration = _top_declaration(stripped)
            if declaration and declaration["kind"] in {"scenarios", "analyses"}:
                active_kind = declaration["kind"]
                active_container = f"{entry_id}.{declaration['name']}"
            else:
                active_kind = None
                active_container = None
            child_indent = None
            continue
        if active_container is None:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        if active_kind == "scenarios":
            use = re.match(
                rf"^use\s+(?P<instance>{_IDENTIFIER})\s*=\s*"
                rf"(?P<target>{_IDENTIFIER}(?:\.{_IDENTIFIER})?):",
                stripped,
            )
            if use:
                target = use.group("target")
                instances.setdefault(active_container, {})[use.group("instance")] = (
                    target if "." in target else f"{entry_id}.{target}"
                )
        elif active_kind == "analyses":
            using = re.match(
                rf"^using\s*=\s*(?P<target>{_IDENTIFIER}(?:\.{_IDENTIFIER})?)$",
                stripped,
            )
            if using:
                target = using.group("target")
                analyses[active_container] = target if "." in target else f"{entry_id}.{target}"
    return instances, analyses


@lru_cache(maxsize=512)
def _index_source(
    source: str,
) -> Tuple[Optional[str], List[_Member], Dict[str, str], List[Tuple[str, str, Optional[str]]]]:
    entry_id: Optional[str] = None
    members: List[_Member] = []
    aliases: Dict[str, str] = {}
    semantics: List[Tuple[str, str, Optional[str]]] = []
    lines = source.splitlines()
    types = _type_fields(lines)
    prose_fence: Optional[str] = None

    def add_object_fields(object_name: str, type_name: str, prefix: str = "", seen=()) -> None:
        local_type = type_name.rsplit(".", 1)[-1]
        if local_type in seen:
            return
        for field_name, field_type, label in types.get(local_type, []):
            path = ".".join(part for part in (object_name, prefix, field_name) if part)
            if field_type.rsplit(".", 1)[-1] in types:
                add_object_fields(
                    object_name,
                    field_type,
                    ".".join(part for part in (prefix, field_name) if part),
                    (*seen, local_type),
                )
            elif entry_id is not None:
                members.append(_Member(entry_id, path, "object_fields", label, field_type))

    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            continue
        if not stripped or stripped.startswith("//"):
            continue
        header = _ENTRY_RE.fullmatch(stripped)
        if header:
            entry_id = header.group(1)
            continue
        if indent != 0 or entry_id is None:
            continue
        alias = _ALIAS_RE.match(stripped)
        if alias:
            aliases[alias.group("name")] = alias.group("target")
            continue
        declaration = _top_declaration(stripped)
        if declaration is None:
            continue
        kind = declaration["kind"]
        name = declaration["name"]
        if kind in {"dimensions", "units", "domains"}:
            semantics.append((name, kind, declaration["label"]))
        elif kind == "types":
            members.append(_Member(entry_id, name, kind, declaration["label"], signature=_member_signature(line)))
            for field_name, field_type, label in types.get(name, []):
                members.append(
                    _Member(
                        entry_id,
                        f"{name}.{field_name}",
                        "type_fields",
                        label,
                        field_type,
                    )
                )
        elif kind in {
            "inputs", "fields", "functions", "tables", "distributions",
            "outputs", "objects", "processes", "scenarios", "analyses",
        }:
            members.append(_Member(entry_id, name, kind, declaration["label"], signature=_member_signature(line)))
            if kind == "objects":
                add_object_fields(name, declaration["keyword"])
    dynamic_kinds = {
        "process_input": "process_inputs",
        "process_state": "process_states",
        "process_event": "process_events",
        "process_action": "process_actions",
        "process_observation": "process_observations",
        "process_key": "process_keys",
        "process_phase": "process_phases",
        "scenario_instance": "scenario_instances",
        "scenario_variant": "scenario_variants",
        "scenario_action": "scenario_actions",
        "scenario_policy": "scenario_policies",
        "scenario_measure": "scenario_measures",
        "scenario_objective": "scenario_objectives",
        "analysis_chart": "analysis_charts",
    }
    for declaration in _dynamic_declarations(source, entry_id):
        members.append(_Member(
            entry_id,
            f"{declaration['container'].split('.', 1)[1]}.{declaration['name']}",
            dynamic_kinds[declaration["kind"]],
            declaration["label"],
            container=declaration["container"],
            signature=declaration["signature"],
            event_direction=declaration.get("event_direction"),
            event_parameters=declaration.get("event_parameters", ()),
        ))
    return entry_id, members, aliases, semantics


def _location(source: AuthoringSource, line: int, start: int, end: int) -> dict:
    return {
        "key": source.key,
        "path": source.path,
        "line": line,
        "column": start + 1,
        "end_column": end + 1,
        "read_only": source.read_only,
    }


def _masked_code(line: str) -> str:
    """Mask strings and comments while preserving source columns."""
    result = list(line)
    quoted = False
    escaped = False
    index = 0
    while index < len(line):
        character = line[index]
        if quoted:
            result[index] = " "
            if character == '"' and not escaped:
                quoted = False
            escaped = character == "\\" and not escaped
            if character != "\\":
                escaped = False
            index += 1
            continue
        if character == '"':
            quoted = True
            result[index] = " "
            index += 1
            continue
        if character == "/" and index + 1 < len(line) and line[index + 1] == "/":
            for masked in range(index, len(line)):
                result[masked] = " "
            break
        index += 1
    return "".join(result)


def _member_signature(line: str) -> str:
    stripped = line.strip()
    if "=" in stripped:
        return stripped.split("=", 1)[0].rstrip()
    return stripped


def _member_unit(section: str, line: str) -> Optional[str]:
    stripped = line.strip()
    if section in {"objects", "types"}:
        return None
    if ":" not in stripped:
        return None
    tail = stripped.split(":", 1)[1]
    if section == "distributions":
        return tail.rstrip(":").strip() or None
    if "=" in tail:
        tail = tail.split("=", 1)[0]
    return tail.strip().rstrip(":") or None


def _function_parameters(line: str) -> list[str]:
    match = re.search(r"\((.*?)\)\s*:", line)
    if not match:
        return []
    return re.findall(rf"({_IDENTIFIER})\s*:", match.group(1))


def _parameter_declarations(text: str) -> Tuple[Tuple[str, str], ...]:
    items: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(text):
        if character in "[()":
            depth += 1
        elif character in "])":
            depth = max(0, depth - 1)
        elif character == "," and depth == 0:
            items.append(text[start:index])
            start = index + 1
    items.append(text[start:])
    result = []
    for item in items:
        match = re.fullmatch(
            rf"\s*(?P<name>{_IDENTIFIER})\s*:\s*(?P<type>.+?)"
            rf"(?:\s+reduce\s+{_IDENTIFIER})?\s*",
            item,
        )
        if match:
            result.append((match.group("name"), match.group("type").strip()))
    return tuple(result)


@lru_cache(maxsize=512)
def _scan_authoring_source(source: AuthoringSource) -> dict:
    entry_id: Optional[str] = None
    aliases: dict[str, str] = {}
    symbols: list[dict[str, Any]] = []
    definitions: dict[int, list[tuple[int, int]]] = {}
    member_headers: dict[int, dict[str, Any]] = {}
    prose_fence: Optional[str] = None
    active_object: Optional[str] = None
    object_indent: Optional[int] = None
    object_path: list[tuple[int, str]] = []
    active_type: Optional[str] = None
    type_field_indent: Optional[int] = None

    def add_symbol(symbol: dict[str, Any], start: int, end: int) -> None:
        symbols.append(symbol)
        definitions.setdefault(symbol["definition"]["line"], []).append((start, end))

    for line_number, line in enumerate(source.text.splitlines(), 1):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            continue
        if not stripped or stripped.startswith("//"):
            continue
        header = _ENTRY_RE.fullmatch(stripped)
        if header:
            entry_id = header.group(1)
            start = line.index(entry_id)
            label = _decode_label(header.group(2)) or entry_id
            add_symbol(
                {
                    "id": f"entry:{entry_id}",
                    "name": entry_id,
                    "label": label,
                    "kind": "entry",
                    "entry_id": entry_id,
                    "detail": f"文档 · {entry_id}",
                    "signature": f"@entry {entry_id}",
                    "definition": _location(source, line_number, start, start + len(entry_id)),
                    "renameable": False,
                    "outline": True,
                    "outline_level": 0,
                },
                start,
                start + len(entry_id),
            )
            continue
        if entry_id is None:
            continue
        if indent == 0:
            active_object = None
            object_indent = None
            object_path = []
            active_type = None
            type_field_indent = None
            alias = _ALIAS_RE.match(stripped)
            if alias:
                name = alias.group("name")
                target = alias.group("target")
                aliases[name] = target
                start = alias.start("name")
                add_symbol(
                    {
                        "id": f"alias:{entry_id}:{name}",
                        "name": name,
                        "label": name,
                        "kind": "alias",
                        "entry_id": entry_id,
                        "detail": f"别名 · {name} → {target}",
                        "signature": f"{name} = {target}",
                        "target": target,
                        "definition": _location(source, line_number, start, alias.end("name")),
                        "renameable": False,
                        "outline": True,
                        "outline_level": 2,
                    },
                    start,
                    alias.end("name"),
                )
                continue
            declaration = _top_declaration(stripped)
            if declaration is None:
                continue
            name = declaration["name"]
            section = declaration["kind"]
            start = declaration["start"]
            end = declaration["end"]
            if section in {"dimensions", "units", "domains"}:
                kind = declaration["keyword"]
                add_symbol(
                    {
                        "id": f"semantic:{kind}:{name}",
                        "name": name,
                        "label": declaration["label"] or name,
                        "kind": kind,
                        "entry_id": entry_id,
                        "detail": f"{_KIND_LABELS[section]} · {name}",
                        "signature": line.strip(),
                        "definition": _location(source, line_number, start, end),
                        "renameable": False,
                        "outline": True,
                        "outline_level": 1,
                    },
                    start,
                    end,
                )
                continue
            if section not in {
                "inputs", "fields", "functions", "tables", "distributions",
                "outputs", "objects", "types", "processes", "scenarios", "analyses",
            }:
                continue
            kind = {
                "processes": "process",
                "scenarios": "scenario",
                "analyses": "analysis",
            }.get(section, section[:-1] if section.endswith("s") else section)
            canonical = f"{entry_id}.{name}"
            parameters = declaration.get("parameters", [])
            symbol = {
                "id": canonical,
                "name": name,
                "label": declaration["label"] or name,
                "kind": kind,
                "entry_id": entry_id,
                "detail": f"{_KIND_LABELS[section]} · {canonical}",
                "signature": _member_signature(line),
                "unit": _member_unit(section, line),
                "parameters": parameters,
                "definition": _location(source, line_number, start, end),
                "renameable": section in {
                    "inputs", "fields", "functions", "tables", "distributions",
                    "outputs",
                } and not source.read_only,
                "outline": True,
                "outline_level": 1,
            }
            add_symbol(symbol, start, end)
            member_headers[line_number] = {
                "indent": indent,
                "parameters": parameters,
                "symbol_id": canonical,
            }
            if section == "objects":
                active_object = name
            elif section == "types":
                active_type = name
            continue
        if active_type is not None:
            if type_field_indent is None:
                type_field_indent = indent
            if indent != type_field_indent:
                continue
            field = re.match(
                rf"^({_IDENTIFIER})\??(?:\s+({_QUOTED}))?\s*:\s*"
                rf"(boolean|number\[{_IDENTIFIER}\]|{_IDENTIFIER}(?:\.{_IDENTIFIER})*)",
                stripped,
            )
            if field is None:
                continue
            field_name = field.group(1)
            field_type = field.group(3)
            canonical = f"{entry_id}.{active_type}.{field_name}"
            start = indent + field.start(1)
            end = indent + field.end(1)
            add_symbol(
                {
                    "id": canonical,
                    "name": f"{active_type}.{field_name}",
                    "label": _decode_label(field.group(2)) or field_name,
                    "kind": "type_field",
                    "entry_id": entry_id,
                    "detail": f"类型字段 · {canonical}",
                    "signature": _member_signature(stripped),
                    "unit": field_type,
                    "parameters": [],
                    "definition": _location(source, line_number, start, end),
                    "renameable": False,
                    "outline": False,
                    "outline_level": 2,
                },
                start,
                end,
            )
            continue
        if active_object is None:
            continue
        if object_indent is None:
            object_indent = indent
        while object_path and object_path[-1][0] >= indent:
            object_path.pop()
        nested = re.match(rf"^({_IDENTIFIER})\s*:$", stripped)
        if nested:
            object_path.append((indent, nested.group(1)))
            continue
        assignment = re.match(rf"^({_IDENTIFIER})\s*=", stripped)
        if not assignment:
            continue
        property_name = assignment.group(1)
        path = [item[1] for item in object_path] + [property_name]
        canonical = ".".join((entry_id, active_object, *path))
        start = indent + assignment.start(1)
        end = indent + assignment.end(1)
        add_symbol(
            {
                "id": canonical,
                "name": ".".join((active_object, *path)),
                "label": property_name,
                "kind": "object_field",
                "entry_id": entry_id,
                "detail": f"对象属性 · {canonical}",
                "signature": line.strip(),
                "unit": None,
                "parameters": [],
                "definition": _location(source, line_number, start, end),
                "renameable": False,
                "outline": False,
                "outline_level": 2,
            },
            start,
            end,
        )
    dynamic_labels = {
        "process_input": "Process 输入",
        "process_state": "Process 状态",
        "process_event": "Process 事件",
        "process_action": "Process Action",
        "process_observation": "Process Observation",
        "process_key": "Process key",
        "process_phase": "Process phase",
        "scenario_instance": "Scenario 实例",
        "scenario_variant": "Scenario Variant",
        "scenario_action": "Scenario Action",
        "scenario_policy": "Scenario Policy",
        "scenario_measure": "Scenario Measure",
        "scenario_objective": "Scenario Objective",
        "analysis_chart": "Analysis Chart",
    }
    dynamic_scopes: dict[str, dict[str, str]] = {}
    source_lines = source.text.splitlines()
    for declaration in _dynamic_declarations(source.text, entry_id):
        line_text = source_lines[declaration["line"] - 1]
        parameters_match = re.search(r"\((.*?)\)", declaration["signature"])
        parameters = (
            re.findall(rf"({_IDENTIFIER})\s*:", parameters_match.group(1))
            if parameters_match
            else []
        )
        symbol = {
            "id": declaration["id"],
            "name": declaration["name"],
            "label": declaration["label"],
            "kind": declaration["kind"],
            "entry_id": declaration["entry_id"],
            "container_id": declaration["container"],
            "detail": f"{dynamic_labels[declaration['kind']]} · {declaration['container']}.{declaration['name']}",
            "signature": declaration["signature"],
            "event_direction": declaration.get("event_direction"),
            "event_parameters": [
                {"name": name, "type": value_type}
                for name, value_type in declaration.get("event_parameters", ())
            ],
            "unit": _member_unit("dynamic", line_text),
            "parameters": parameters,
            "definition": _location(
                source,
                declaration["line"],
                declaration["start"],
                declaration["end"],
            ),
            "renameable": False,
            "outline": True,
            "outline_level": 2,
        }
        add_symbol(symbol, declaration["start"], declaration["end"])
        dynamic_scopes.setdefault(declaration["container"], {})[declaration["name"]] = declaration["id"]
    instance_bindings, analysis_bindings = _dynamic_bindings(source.text, entry_id)
    return {
        "source": source,
        "entry_id": entry_id,
        "aliases": aliases,
        "symbols": symbols,
        "definitions": definitions,
        "member_headers": member_headers,
        "dynamic_scopes": dynamic_scopes,
        "instance_bindings": instance_bindings,
        "analysis_bindings": analysis_bindings,
    }


def _builtin_authoring_items() -> list[dict]:
    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for candidate in BUILTIN_COMPLETIONS:
        if candidate.kind not in {"builtin", "measure", "variable"}:
            continue
        match = re.match(rf"({_IDENTIFIER})", candidate.insert_text)
        if not match:
            continue
        name = match.group(1)
        scope = (
            "measure"
            if candidate.kind == "measure"
            else "runtime"
            if candidate.kind == "variable"
            else "process"
            if "process_expr" in candidate.contexts and "static_expr" not in candidate.contexts
            else "static"
        )
        if (scope, name) in seen:
            continue
        seen.add((scope, name))
        signature = candidate.signature or candidate.insert_text.replace("$0", "…")
        result.append(
            {
                "id": f"builtin:{scope}:{name}",
                "name": name,
                "scope": scope,
                "label": candidate.label,
                "kind": candidate.kind,
                "detail": candidate.detail,
                "signature": signature,
                "reference_topic": candidate.reference_topic,
                "reference_symbol": candidate.reference_symbol,
            }
        )
    return result


def _reference_start(line: str, _section: Optional[str], _is_member_header: bool) -> Optional[int]:
    return None if line.lstrip().startswith("@") else 0


def build_authoring_index(sources: Sequence[AuthoringSource]) -> dict:
    """Build a tolerant symbol/reference projection from complete or incomplete drafts."""
    scans = [_scan_authoring_source(source) for source in sources]
    symbols = [symbol for scan in scans for symbol in scan["symbols"]]
    symbol_by_id = {symbol["id"]: symbol for symbol in symbols}
    local_members: dict[str, dict[str, str]] = {}
    unique_inputs: dict[str, list[str]] = {}
    semantic_names: dict[str, list[str]] = {}
    for symbol in symbols:
        entry_id = symbol.get("entry_id")
        if entry_id and symbol["kind"] in {
            "input", "field", "function", "table", "distribution", "output",
            "type", "object", "object_field", "process", "scenario", "analysis",
        }:
            local_members.setdefault(entry_id, {})[symbol["name"]] = symbol["id"]
        if symbol["kind"] == "input":
            unique_inputs.setdefault(symbol["name"], []).append(symbol["id"])
        if symbol["kind"] in {"dimension", "unit", "domain"}:
            semantic_names.setdefault(symbol["name"], []).append(symbol["id"])

    dynamic_scopes = {
        container: members
        for scan in scans
        for container, members in scan["dynamic_scopes"].items()
    }
    instance_bindings = {
        container: members
        for scan in scans
        for container, members in scan["instance_bindings"].items()
    }
    analysis_bindings = {
        container: target
        for scan in scans
        for container, target in scan["analysis_bindings"].items()
    }

    builtins = _builtin_authoring_items()
    builtins_by_name: dict[str, list[dict]] = {}
    for item in builtins:
        builtins_by_name.setdefault(item["name"], []).append(item)

    def builtin_id(name: str, contexts: Sequence[str]) -> Optional[str]:
        choices = builtins_by_name.get(name, [])
        preferred = (
            ("runtime", "measure", "process")
            if "measure_expr" in contexts
            else ("process",)
            if "process_expr" in contexts
            else ("static",)
        )
        for scope in preferred:
            item = next((candidate for candidate in choices if candidate["scope"] == scope), None)
            if item is not None:
                return item["id"]
        return None
    references: list[dict[str, Any]] = []
    for scan in scans:
        source: AuthoringSource = scan["source"]
        entry_id: Optional[str] = scan["entry_id"]
        aliases: dict[str, str] = scan["aliases"]
        prose_fence: Optional[str] = None
        active_parameters: set[str] = set()
        active_indent: Optional[int] = None
        active_container: Optional[str] = None
        for line_number, line in enumerate(source.text.splitlines(), 1):
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if prose_fence is not None:
                if indent == 0 and stripped == prose_fence:
                    prose_fence = None
                continue
            if indent == 0 and _FENCE_RE.fullmatch(stripped):
                prose_fence = stripped
                continue
            if not stripped or stripped.startswith("//"):
                continue
            if indent == 0:
                declaration = _top_declaration(stripped)
                active_container = (
                    f"{entry_id}.{declaration['name']}"
                    if entry_id
                    and declaration
                    and declaration["kind"] in {"processes", "scenarios", "analyses"}
                    else None
                )
                if stripped.startswith("@"):
                    continue
            header = scan["member_headers"].get(line_number)
            if active_indent is not None and indent <= active_indent and header is None:
                active_parameters = set()
                active_indent = None
            if header is not None:
                active_parameters = set(header["parameters"])
                active_indent = header["indent"] if active_parameters else None
            line_parameters = set(active_parameters)
            next_match = re.search(r"\bnext\s*\((.*?)\)\s*=", line)
            if next_match:
                line_parameters.update(re.findall(_IDENTIFIER, next_match.group(1)))
            start = _reference_start(line, None, header is not None)
            if start is None:
                continue
            masked = _masked_code(line)
            if start:
                masked = " " * start + masked[start:]
            for bound in re.finditer(
                rf"\b(?:sum|product|map|condition)\s*\([^,]+,\s*({_IDENTIFIER})\b",
                masked,
            ):
                line_parameters.add(bound.group(1))
            definitions = scan["definitions"].get(line_number, [])
            for match in _REFERENCE_RE.finditer(masked):
                if any(match.start("token") >= left and match.end("token") <= right for left, right in definitions):
                    continue
                token = match.group("token")
                if token in line_parameters:
                    continue
                symbol_id: Optional[str] = None
                via_alias = False

                if active_container and "." not in token:
                    symbol_id = dynamic_scopes.get(active_container, {}).get(token)
                    if symbol_id is None and active_container in analysis_bindings:
                        scenario_target = analysis_bindings[active_container]
                        symbol_id = dynamic_scopes.get(scenario_target, {}).get(token)
                elif active_container and "." in token:
                    instance, member_path = token.split(".", 1)
                    scenario_target = (
                        analysis_bindings.get(active_container, active_container)
                    )
                    process_target = instance_bindings.get(scenario_target, {}).get(instance)
                    if process_target:
                        member = member_path.split(".", 1)[0]
                        symbol_id = dynamic_scopes.get(process_target, {}).get(member)
                if symbol_id is not None:
                    pass
                elif "." in token and token in symbol_by_id:
                    symbol_id = token
                elif entry_id and token in aliases and aliases[token] in symbol_by_id:
                    symbol_id = aliases[token]
                    via_alias = True
                elif entry_id and token in local_members.get(entry_id, {}):
                    symbol_id = local_members[entry_id][token]
                elif "." in token:
                    prefixes = [
                        candidate
                        for candidate in symbol_by_id
                        if token.startswith(candidate + ".")
                    ]
                    if prefixes:
                        symbol_id = max(prefixes, key=len)
                elif len(unique_inputs.get(token, [])) == 1:
                    symbol_id = unique_inputs[token][0]
                elif len(semantic_names.get(token, [])) == 1:
                    symbol_id = semantic_names[token][0]
                elif token in RUNTIME_MEASURE_SYMBOLS:
                    token_site = completion_site(source.text, line_number, match.end("token") + 1)
                    if "measure_expr" in token_site.contexts:
                        symbol_id = builtin_id(token, token_site.contexts)
                elif token in builtins_by_name:
                    token_site = completion_site(source.text, line_number, match.end("token") + 1)
                    symbol_id = builtin_id(token, token_site.contexts)
                if symbol_id is None:
                    continue
                references.append(
                    {
                        "symbol_id": symbol_id,
                        "text": token,
                        "location": _location(
                            source,
                            line_number,
                            match.start("token"),
                            match.end("token"),
                        ),
                        "via_alias": via_alias,
                    }
                )
    symbols.sort(key=lambda item: (item["definition"]["key"], item["definition"]["line"], item["definition"]["column"]))
    references.sort(key=lambda item: (item["location"]["key"], item["location"]["line"], item["location"]["column"]))
    return {"symbols": symbols, "references": references, "builtins": builtins}


def _source_offset(text: str, line: int, column: int) -> int:
    lines = text.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        raise ParameterError("authoring edit line is outside the document")
    return sum(len(item) for item in lines[: line - 1]) + max(0, column - 1)


def rename_authoring_symbol(sources: Sequence[AuthoringSource], symbol_id: str, new_name: str) -> dict:
    """Return validated textual rename candidates without writing source files."""
    if not re.fullmatch(_IDENTIFIER, new_name):
        raise ParameterError("new symbol name must be an ASCII identifier")
    index = build_authoring_index(sources)
    symbol = next((item for item in index["symbols"] if item["id"] == symbol_id), None)
    if symbol is None:
        raise WorkspaceError(f"unknown authoring symbol: {symbol_id}")
    if not symbol.get("renameable"):
        raise WorkspaceError(f"symbol is read-only or cannot be renamed: {symbol_id}")
    entry_id = symbol["entry_id"]
    replacement_id = f"{entry_id}.{new_name}"
    if replacement_id != symbol_id and any(item["id"] == replacement_id for item in index["symbols"]):
        raise ParameterError(f"symbol already exists: {replacement_id}")

    edits: dict[str, list[tuple[dict, str]]] = {
        symbol["definition"]["key"]: [(symbol["definition"], new_name)]
    }
    for reference in index["references"]:
        if reference["symbol_id"] != symbol_id or reference.get("via_alias"):
            continue
        location = reference["location"]
        if location["read_only"]:
            raise WorkspaceError(f"rename would modify read-only source: {location['path']}")
        text = reference["text"]
        replacement = f"{entry_id}.{new_name}" if "." in text else new_name
        edits.setdefault(location["key"], []).append((location, replacement))

    source_by_key = {source.key: source for source in sources}
    changes = []
    edit_count = 0
    for key, items in edits.items():
        source = source_by_key.get(key)
        if source is None or source.read_only:
            raise WorkspaceError(f"rename target is not writable: {key}")
        unique: dict[tuple[int, int, int], tuple[dict, str]] = {}
        for location, replacement in items:
            unique[(location["line"], location["column"], location["end_column"])] = (location, replacement)
        rendered = source.text
        positioned = []
        for location, replacement in unique.values():
            start = _source_offset(source.text, location["line"], location["column"])
            end = _source_offset(source.text, location["line"], location["end_column"])
            positioned.append((start, end, replacement))
        for start, end, replacement in sorted(positioned, reverse=True):
            rendered = rendered[:start] + replacement + rendered[end:]
        if rendered != source.text:
            edit_count += len(positioned)
            changes.append({"key": key, "path": source.path, "before": source.text, "text": rendered})
    return {"status": "ok", "symbol": symbol_id, "renamed_to": replacement_id, "edits": edit_count, "changes": changes}


def format_kirin_source(source: str) -> str:
    """Normalize safe whitespace without re-rendering comments or prose blocks."""
    rendered: list[str] = []
    prose_fence: Optional[str] = None
    blank_count = 0
    for raw_line in source.splitlines():
        stripped = raw_line.lstrip()
        indent = len(raw_line) - len(stripped)
        if prose_fence is not None:
            rendered.append(raw_line)
            if indent == 0 and stripped == prose_fence:
                prose_fence = None
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            rendered.append(raw_line.rstrip())
            blank_count = 0
            continue
        leading = raw_line[:indent].replace("\t", "  ")
        line = leading + stripped.rstrip()
        if line:
            rendered.append(line)
            blank_count = 0
        elif blank_count < 2:
            rendered.append("")
            blank_count += 1
    return "\n".join(rendered).rstrip() + "\n"


def build_completion_candidates(
    sources: Mapping[Path, str],
    current_path: Path,
    prefix: str,
    line: Optional[int] = None,
    column: Optional[int] = None,
    limit: int = 60,
) -> List[CompletionCandidate]:
    """Build resilient completion candidates from valid or incomplete Kirin Tor buffers."""
    all_members: List[_Member] = []
    all_semantics: List[Tuple[str, str, Optional[str]]] = []
    current_entry = None
    current_aliases: Dict[str, str] = {}
    current_source = ""
    all_instances: dict[str, dict[str, str]] = {}
    all_analyses: dict[str, str] = {}
    non_numeric_types = {"boolean", "event_id"}
    for path, source in sources.items():
        entry_id, members, aliases, semantics = _index_source(source)
        all_members.extend(members)
        all_semantics.extend(semantics)
        instances, analyses = _dynamic_bindings(source, entry_id)
        all_instances.update(instances)
        all_analyses.update(analyses)
        for match in re.finditer(
            rf"(?m)^domain\s+(?P<name>{_IDENTIFIER})(?:\s+{_QUOTED})?\s*:\s*$",
            source,
        ):
            name = match.group("name")
            non_numeric_types.add(name)
            if entry_id:
                non_numeric_types.add(f"{entry_id}.{name}")
        if path.resolve() == current_path.resolve():
            current_entry = entry_id
            current_aliases = aliases
            current_source = source
    for member in all_members:
        if member.kind == "types":
            non_numeric_types.update((member.name, member.canonical))

    def numeric_event_parameter(value_type: str) -> bool:
        normalized = value_type.replace(" ", "")
        return not (
            normalized in non_numeric_types
            or normalized.rsplit(".", 1)[-1] in non_numeric_types
            or normalized.startswith(("list[", "map["))
        )
    site = completion_site(current_source, line, column) if line is not None and column is not None else None
    active_contexts = set(site.contexts if site else ("all",))
    if active_contexts & {"comment", "string", "prose"}:
        return []
    member_by_target = {member.canonical: member for member in all_members}
    candidates: List[CompletionCandidate] = _process_local_candidates(current_source, site)

    for alias, target in current_aliases.items():
        target_member = member_by_target.get(target)
        is_function = target_member is not None and target_member.kind == "functions"
        inserted = f"{alias}($0)" if is_function else alias
        label = target_member.label if target_member and target_member.label else alias
        candidates.append(
            CompletionCandidate(
                label,
                f"别名 · {alias} → {target}",
                inserted,
                "alias",
                tuple(item for item in (alias, label, target) if item),
                0,
                ("static_expr", "reference"),
                "aliases",
                "alias",
                f"{alias} = {target}",
            )
        )

    for member in all_members:
        if (
            site
            and site.container in all_analyses
            and member.container == all_analyses[site.container]
            and member.kind.startswith("scenario_")
        ):
            continue
        if member.kind == "type_fields":
            if site and site.object_type and "object_field" in active_contexts:
                owner = member.name.rsplit(".", 1)[0]
                qualified_owner = member.canonical.rsplit(".", 1)[0]
                if site.object_type not in {owner, qualified_owner}:
                    continue
            field_name = member.name.rsplit(".", 1)[-1]
            detail = f"{_KIND_LABELS[member.kind]} · {member.canonical}"
            if member.value_type:
                detail += f" · {member.value_type}"
            candidates.append(
                CompletionCandidate(
                    member.label or field_name,
                    detail,
                    field_name,
                    _COMPLETION_KINDS[member.kind],
                    tuple(
                        item
                        for item in (
                            field_name,
                            member.name,
                            member.canonical,
                            member.label,
                            member.value_type,
                        )
                        if item
                    ),
                    45,
                    ("object_field", "reference"),
                    "structures",
                    "type",
                    member.canonical,
                )
            )
            continue
        local = member.entry_id == current_entry
        same_container = bool(site and member.container and site.container == member.container)
        if site is not None and member.container is not None and not same_container:
            # Nested declarations are only legal in their own block. Scenario and
            # Analysis access them through the instance/using projections below.
            continue
        typed_qualified_local = bool(
            local and prefix.casefold().startswith(f"{member.entry_id}.".casefold())
        )
        reference = (
            member.name.rsplit(".", 1)[-1]
            if same_container
            else member.name if local and not typed_qualified_local and member.container is None
            else member.canonical
        )
        call_kinds = {"functions", "process_events", "process_actions"}
        inserted = f"{reference}($0)" if member.kind in call_kinds else reference
        dynamic_contexts = {
            "process_inputs": ("process_expr",),
            "process_states": ("process_expr", "process_state_target"),
            "process_actions": ("process_handler_trigger",),
            "process_observations": (),
            "process_keys": ("process_key_target",),
            "process_phases": ("process_phase_target", "scenario_binding"),
            "scenario_instances": ("scenario_decl", "measure_expr", "reference"),
            "scenario_variants": ("analysis_decl", "reference"),
            "scenario_actions": ("scenario_policy", "scenario_decision_option", "reference"),
            "scenario_policies": ("analysis_decl", "reference"),
            "scenario_measures": ("measure_expr", "scenario_decl", "analysis_chart", "reference"),
            "scenario_objectives": ("analysis_decl", "reference"),
            "analysis_charts": ("reference",),
        }
        if member.kind == "process_events":
            event_contexts = []
            if member.event_direction in {"input", "internal"}:
                event_contexts.append("process_handler_trigger")
            if member.event_direction in {"output", "internal"}:
                event_contexts.append("process_emit_event")
            if member.event_direction == "internal":
                event_contexts.append("process_schedule_event")
            contexts: Optional[Tuple[str, ...]] = tuple(event_contexts)
        else:
            contexts = dynamic_contexts.get(member.kind)
        candidates.append(
            CompletionCandidate(
                member.label or reference,
                f"{_KIND_LABELS[member.kind]} · {member.canonical}",
                inserted,
                _COMPLETION_KINDS.get(member.kind, member.kind),
                tuple(
                    item
                    for item in (member.name, member.canonical, member.label)
                    if item
                ),
                30 if local else 50,
                contexts if contexts is not None else (
                    ("type", "process_type", "reference")
                    if member.kind == "types"
                    else ("scenario_reference", "reference")
                    if member.kind == "scenarios"
                    else ("process_reference", "reference")
                    if member.kind == "processes"
                    else ("reference",)
                    if member.kind == "analyses"
                    else ("static_expr", "reference")
                ),
                "structures" if member.kind in {"types", "objects", "object_fields"}
                else "process" if member.kind in {"processes", "scenarios", "analyses"} or contexts
                else "members",
                "type" if member.kind == "types"
                else "object" if member.kind in {"objects", "object_fields"}
                else "process-declarations" if member.kind == "processes"
                else "scenario" if member.kind == "scenarios"
                else "analysis" if member.kind == "analyses"
                else "process-declarations" if member.kind.startswith("process_")
                else "scenario" if member.kind.startswith("scenario_")
                else "analysis-chart" if member.kind == "analysis_charts"
                else member.kind[:-1] if member.kind.endswith("s") else member.kind,
                member.signature or (f"{reference}()" if member.kind in call_kinds else reference),
            )
        )
    if site and site.container and current_entry:
        scenario_container = all_analyses.get(site.container, site.container)
        for instance, process_container in all_instances.get(scenario_container, {}).items():
            candidates.append(CompletionCandidate(
                instance,
                f"Scenario 实例 · {instance} → {process_container}",
                instance,
                "namespace",
                (instance, process_container, "实例"),
                18,
                ("scenario_decl", "measure_expr", "analysis_chart", "reference"),
                "process",
                "scenario",
                instance,
            ))
            for member in (item for item in all_members if item.container == process_container):
                short = member.name.rsplit(".", 1)[-1]
                projected = f"{instance}.{short}"
                if member.kind == "process_events":
                    call_contexts = []
                    path_contexts = []
                    if member.event_direction == "input":
                        call_contexts.extend((
                            "scenario_send_scheduled",
                            "scenario_send_action",
                        ))
                        path_contexts.extend((
                            "scenario_connect_target",
                            "scenario_public_event",
                            "analysis_public_event",
                        ))
                    elif member.event_direction == "output":
                        path_contexts.extend((
                            "scenario_connect_source",
                            "scenario_public_event",
                            "analysis_public_event",
                            "measure_count_event",
                        ))
                    for insertion, projected_contexts in (
                        (f"{projected}($0)", call_contexts),
                        (projected, path_contexts),
                    ):
                        if not projected_contexts:
                            continue
                        candidates.append(CompletionCandidate(
                            member.label or projected,
                            f"实例成员 · {projected} → {member.canonical}",
                            insertion,
                            _COMPLETION_KINDS.get(member.kind, "variable"),
                            (projected, short, member.label or ""),
                            16,
                            tuple(projected_contexts),
                            "process",
                            "process-declarations",
                            member.signature or projected,
                        ))
                    if member.event_direction == "output":
                        for parameter, value_type in member.event_parameters:
                            if not numeric_event_parameter(value_type):
                                continue
                            parameter_path = f"{projected}.{parameter}"
                            candidates.append(CompletionCandidate(
                                parameter_path,
                                f"输出事件数值参数 · {parameter_path} · {value_type}",
                                parameter_path,
                                "variable",
                                (parameter_path, projected, parameter, value_type),
                                15,
                                ("measure_sum_event_parameter",),
                                "process",
                                "scenario-measures-objectives",
                                parameter_path,
                            ))
                    continue
                contexts = (
                    ("scenario_send_action",)
                    if member.kind == "process_actions"
                    else ("measure_expr", "analysis_chart")
                    if member.kind == "process_observations"
                    else ("scenario_decl",)
                    if member.kind == "process_inputs"
                    else ()
                )
                is_call = member.kind == "process_actions"
                candidates.append(CompletionCandidate(
                    member.label or projected,
                    f"实例成员 · {projected} → {member.canonical}",
                    f"{projected}($0)" if is_call else projected,
                    _COMPLETION_KINDS.get(member.kind, "variable"),
                    (projected, short, member.label or ""),
                    16,
                    contexts,
                    "process",
                    "process-declarations",
                    member.signature or projected,
                ))
                if member.kind in {"process_inputs", "process_phases"}:
                    binding_text = (
                        f"{short} = $0"
                        if member.kind == "process_inputs"
                        else f"phase {short} = $0"
                    )
                    candidates.append(CompletionCandidate(
                        member.label or short,
                        f"实例绑定 · {instance} → {member.canonical}",
                        binding_text,
                        "property",
                        (short, member.label or "", "绑定", "phase"),
                        12,
                        ("scenario_binding",),
                        "process",
                        "scenario",
                        binding_text.replace("$0", "…"),
                    ))
        if site.container in all_analyses:
            for member in (
                item
                for item in all_members
                if item.container == scenario_container
                and item.kind in {
                    "scenario_variants", "scenario_policies", "scenario_measures",
                    "scenario_objectives", "scenario_actions",
                }
            ):
                short = member.name.rsplit(".", 1)[-1]
                candidates.append(CompletionCandidate(
                    member.label or short,
                    f"所选 Scenario 成员 · {short} → {member.canonical}",
                    short,
                    _COMPLETION_KINDS.get(member.kind, "variable"),
                    (short, member.label or "", member.canonical),
                    14,
                    ("analysis_decl", "analysis_chart", "reference"),
                    "process",
                    "scenario-measures-objectives"
                    if member.kind in {"scenario_measures", "scenario_objectives"}
                    else "scenario",
                    short,
                ))
    for name, kind, label in all_semantics:
        semantic_contexts = (
            (
                "type", "process_type", "static_expr", "process_expr",
                "measure_expr", "reference",
            )
            if kind == "units"
            else ("type", "process_type", "reference")
        )
        candidates.append(
            CompletionCandidate(
                label or name,
                f"{_KIND_LABELS[kind]} · {name}",
                name,
                _COMPLETION_KINDS.get(kind, kind[:-1] if kind.endswith("s") else kind),
                tuple(item for item in (name, label, _KIND_LABELS[kind]) if item),
                28,
                semantic_contexts,
                "semantics",
                "dimension" if kind == "dimensions" else "unit" if kind == "units" else "numeric-domain",
                name,
            )
        )
    candidates.extend(BUILTIN_COMPLETIONS)
    candidates.extend(SNIPPETS)

    if site is not None:
        candidates = [
            candidate
            for candidate in candidates
            if "all" in candidate.contexts or active_contexts.intersection(candidate.contexts)
        ]

    normalized = prefix.casefold()

    def score(candidate: CompletionCandidate) -> Tuple[int, int, str]:
        terms = [term.casefold() for term in candidate.terms]
        if not normalized:
            match_rank = 0
        elif any(term == normalized for term in terms):
            match_rank = 0
        elif any(term.startswith(normalized) for term in terms):
            match_rank = 1
        else:
            match_rank = 2
        return match_rank, candidate.priority, candidate.label.casefold()

    if normalized:
        candidates = [
            candidate
            for candidate in candidates
            if any(normalized in term.casefold() for term in candidate.terms)
        ]
    seen = set()
    result = []
    for candidate in sorted(candidates, key=score):
        key = (
            candidate.insert_text,
            candidate.kind,
            candidate.detail if candidate.kind == "type_field" else "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def prepare_completion_insertion(text: str, indent: str) -> Tuple[str, int]:
    """Apply the current line indentation and return text plus the $0 cursor offset."""
    indented = text.replace("\n", "\n" + indent)
    cursor = indented.find("$0")
    if cursor < 0:
        cursor = len(indented)
        return indented, cursor
    return indented.replace("$0", "", 1), cursor
