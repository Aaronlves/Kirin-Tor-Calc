"""Kirin completion indexing and authoring snippets for the browser editor."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_FENCE_RE = re.compile(r"^-{3,}$")
_ENTRY_RE = re.compile(rf"^@entry\s+({_IDENTIFIER})$")
_SECTION_RE = re.compile(rf"^({_IDENTIFIER}):$")
_MEMBER_RE = re.compile(rf"^\s+(?P<name>{_IDENTIFIER})(?:\s+(?P<label>{_QUOTED}))?")
_ALIAS_RE = re.compile(rf"^\s+(?P<name>[^\s=]+)\s*=\s*(?P<target>{_IDENTIFIER}\.{_IDENTIFIER})")
@dataclass(frozen=True)
class CompletionCandidate:
    label: str
    detail: str
    insert_text: str
    kind: str
    terms: Tuple[str, ...]
    priority: int = 100


@dataclass(frozen=True)
class _Member:
    entry_id: str
    name: str
    kind: str
    label: Optional[str]

    @property
    def canonical(self) -> str:
        return f"{self.entry_id}.{self.name}"


_KIND_LABELS = {
    "inputs": "输入",
    "fields": "字段",
    "functions": "函数",
    "tables": "查表",
    "distributions": "有限分布",
    "recurrences": "有限递推",
    "state_models": "有限状态模型",
    "outputs": "输出",
    "alias": "别名",
    "dimensions": "量纲",
    "units": "单位",
    "domains": "值域",
    "builtin": "内置函数",
    "keyword": "关键字",
    "snippet": "片段",
}


def _snippet(label: str, trigger: str, english: str, text: str, priority: int) -> CompletionCandidate:
    return CompletionCandidate(label, f"片段 · {english}", text, "snippet", (trigger, english), priority)


SNIPPETS = (
    _snippet(
        "条目文档",
        "条目文档",
        "entry document",
        "@kirin 1\n@entry entry_id\n\n// 中文标题\n\n$0",
        1,
    ),
    _snippet("输入章节", "输入", "inputs", 'inputs:\n  name "显示名": number[dimensionless] = $0', 10),
    _snippet("别名章节", "别名", "aliases", "aliases:\n  中文名 = entry.member$0", 11),
    _snippet("字段章节", "字段", "fields", 'fields:\n  value "显示名": dimensionless = $0', 12),
    _snippet(
        "函数章节",
        "函数",
        "functions",
        'functions:\n  function_name "显示名"(arg: number[dimensionless]) -> dimensionless =\n    $0',
        13,
    ),
    _snippet(
        "查表章节",
        "查表",
        "tables",
        'tables:\n  table_name "显示名": dimensionless -> dimensionless:\n    1 = $0',
        14,
    ),
    _snippet(
        "有限分布章节",
        "有限分布",
        "distributions",
        'distributions:\n  result_distribution "显示名": dimensionless:\n    0 @ 1 - probability_value\n    1 @ $0',
        14,
    ),
    _snippet(
        "有限递推章节",
        "有限递推",
        "recurrences",
        'recurrences:\n  recurrence_name "显示名": dimensionless:\n    initial = 0\n    steps = bounded_count\n    next(current, index) = $0',
        14,
    ),
    _snippet(
        "有限状态模型章节",
        "有限状态",
        "state_models",
        "state_models:\n  model_name:\n    states:\n      first\n      second\n    transitions:\n      first -> second @ probability_value\n      second -> first @ $0",
        14,
    ),
    _snippet("输出章节", "输出", "outputs", 'outputs:\n  result "显示名": dimensionless = $0', 14),
    _snippet("分组章节", "分组", "groups", 'groups:\n  group_id "显示名":\n    result$0', 15),
    _snippet(
        "参数方案章节",
        "参数方案",
        "presets",
        'presets:\n  preset_id "显示名":\n    entry.input = $0',
        16,
    ),
    _snippet("显示章节", "显示", "display", "display:\n  result: number digits $0", 17),
    _snippet("约束章节", "约束", "constraints", "constraints:\n  $0", 15),
    _snippet("来源章节", "来源", "sources", 'sources:\n  {"kind":"note","citation":"$0"}', 17),
    _snippet("长说明块", "长说明", "description", "---\n$0\n---", 18),
    _snippet(
        "图表配置",
        "图表",
        "plot",
        "x: entry.input\nrange: 0..1\npoints: 101\n\ny:\n  entry.output\n\nexport-svg: \"results/chart.svg\"\nexport-csv: \"results/chart.csv\"$0",
        20,
    ),
    _snippet(
        "分段公式",
        "分段",
        "piecewise",
        "piecewise(\n  condition, value,\n  $0\n)",
        21,
    ),
    _snippet("条件公式", "条件", "if_else", "if_else(condition, when_true, $0)", 22),
)


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
    CompletionCandidate(
        "稳态概率",
        "状态模型函数 · steady_probability",
        "steady_probability(model, $0)",
        "builtin",
        ("steady_probability", "稳态概率"),
        24,
    ),
    CompletionCandidate(
        "稳态奖励",
        "状态模型函数 · steady_reward",
        "steady_reward(model, $0)",
        "builtin",
        ("steady_reward", "稳态奖励", "长期期望"),
        24,
    ),
    CompletionCandidate(
        "到达概率",
        "状态模型函数 · hitting_probability",
        "hitting_probability(model, start, $0)",
        "builtin",
        ("hitting_probability", "到达概率", "吸收概率"),
        24,
    ),
    CompletionCandidate(
        "期望步数",
        "状态模型函数 · expected_steps",
        "expected_steps(model, start, $0)",
        "builtin",
        ("expected_steps", "期望步数", "到达步数"),
        24,
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


def completion_prefix(line: str, column: int) -> Tuple[str, int]:
    """Return the Unicode identifier/member prefix ending at the cursor and its start column."""
    before = line[:column]
    match = re.search(r"[\w.]*$", before, re.UNICODE)
    prefix = match.group(0) if match else ""
    return prefix, column - len(prefix)


def _decode_label(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, str) and decoded else None


def _index_source(
    source: str,
) -> Tuple[Optional[str], List[_Member], Dict[str, str], List[Tuple[str, str]]]:
    entry_id = None
    section = None
    section_member_indent = None
    members: List[_Member] = []
    aliases: Dict[str, str] = {}
    semantics: List[Tuple[str, str]] = []
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
        header = _ENTRY_RE.fullmatch(stripped)
        if header:
            entry_id = header.group(1)
            continue
        if indent == 0:
            section_match = _SECTION_RE.fullmatch(stripped)
            section = section_match.group(1) if section_match else None
            section_member_indent = None
            continue
        if entry_id is None:
            continue
        if section == "aliases":
            match = _ALIAS_RE.match(line)
            if match:
                aliases[match.group("name")] = match.group("target")
            continue
        if section in {"dimensions", "units", "domains"}:
            match = _MEMBER_RE.match(line)
            tail = line[match.end() :].lstrip() if match else ""
            valid = (
                section == "dimensions"
                or (section == "units" and tail.startswith("="))
                or (section == "domains" and tail.startswith(":"))
            )
            if match and valid:
                semantics.append((match.group("name"), section))
            continue
        if section not in {
            "inputs", "fields", "functions", "tables", "distributions", "recurrences",
            "state_models", "outputs"
        }:
            continue
        if section_member_indent is None:
            section_member_indent = indent
        if indent != section_member_indent:
            continue
        match = _MEMBER_RE.match(line)
        tail = line[match.end() :].lstrip() if match else ""
        if match and (
            (section == "functions" and tail.startswith("("))
            or (
                section in {"tables", "distributions", "recurrences", "state_models"}
                and tail.startswith(":")
            )
            or (section in {"inputs", "fields", "outputs"} and tail.startswith(":"))
        ):
            members.append(
                _Member(entry_id, match.group("name"), section, _decode_label(match.group("label")))
            )
    return entry_id, members, aliases, semantics


def build_completion_candidates(
    sources: Mapping[Path, str],
    current_path: Path,
    prefix: str,
    limit: int = 60,
) -> List[CompletionCandidate]:
    """Build resilient completion candidates from valid or incomplete Kirin buffers."""
    all_members: List[_Member] = []
    all_semantics: List[Tuple[str, str]] = []
    current_entry = None
    current_aliases: Dict[str, str] = {}
    for path, source in sources.items():
        entry_id, members, aliases, semantics = _index_source(source)
        all_members.extend(members)
        all_semantics.extend(semantics)
        if path.resolve() == current_path.resolve():
            current_entry = entry_id
            current_aliases = aliases
    member_by_target = {member.canonical: member for member in all_members}
    candidates: List[CompletionCandidate] = []

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
            )
        )

    for member in all_members:
        local = member.entry_id == current_entry
        typed_qualified_local = bool(
            local and prefix.casefold().startswith(f"{member.entry_id}.".casefold())
        )
        reference = member.name if local and not typed_qualified_local else member.canonical
        inserted = f"{reference}($0)" if member.kind == "functions" else reference
        candidates.append(
            CompletionCandidate(
                member.label or reference,
                f"{_KIND_LABELS[member.kind]} · {member.canonical}",
                inserted,
                member.kind,
                tuple(
                    item
                    for item in (member.name, member.canonical, member.label)
                    if item
                ),
                30 if local else 50,
            )
        )
    for name, kind in all_semantics:
        candidates.append(
            CompletionCandidate(
                name,
                f"{_KIND_LABELS[kind]} · {name}",
                name,
                kind,
                (name, _KIND_LABELS[kind]),
                28,
            )
        )
    candidates.extend(BUILTIN_COMPLETIONS)
    candidates.extend(SNIPPETS)

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
        key = (candidate.insert_text, candidate.kind)
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
