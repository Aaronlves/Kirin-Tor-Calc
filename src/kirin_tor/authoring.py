"""Editor-only Kirin highlighting, completion indexing, and snippets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple


Highlight = Tuple[int, Optional[int], str]

_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
_QUOTED = r'"(?:[^"\\]|\\.)*"'
_FENCE_RE = re.compile(r"^-{3,}$")
_ENTRY_RE = re.compile(rf"^@entry\s+({_IDENTIFIER})$")
_SECTION_RE = re.compile(rf"^({_IDENTIFIER}):$")
_MEMBER_RE = re.compile(rf"^\s+(?P<name>{_IDENTIFIER})(?:\s+(?P<label>{_QUOTED}))?")
_ALIAS_RE = re.compile(rf"^\s+(?P<name>[^\s=]+)\s*=\s*(?P<target>{_IDENTIFIER}\.{_IDENTIFIER})")
_STRING_RE = re.compile(_QUOTED)
_NUMBER_RE = re.compile(r"(?<![\w.])(?:\d+/\d+|\d+\.\d+|\.\d+|\d+)(?:[eE][+-]?\d+)?(?![\w.])")
_BOOLEAN_RE = re.compile(r"\b(?:true|false)\b")
_QUALIFIED_RE = re.compile(rf"\b{_IDENTIFIER}\.{_IDENTIFIER}\b")
_CALL_RE = re.compile(r"(?<![.\w])([^\W\d]\w*)(?=\s*\()", re.UNICODE)
_OPERATOR_RE = re.compile(r":=|->|\.\.|==|!=|<=|>=|\*\*|[=:+\-*/<>]")


def _byte_column(line: str, character_column: int) -> int:
    return len(line[:character_column].encode("utf-8"))


def _highlight(line: str, start: int, end: Optional[int], name: str) -> Highlight:
    return (
        _byte_column(line, start),
        _byte_column(line, end) if end is not None else None,
        name,
    )


def _overlaps(start: int, end: int, ranges: Iterable[Tuple[int, int]]) -> bool:
    return any(start < existing_end and end > existing_start for existing_start, existing_end in ranges)


def highlight_kirin_source(source: str) -> Dict[int, List[Highlight]]:
    """Return TextArea-compatible byte highlights without requiring a tree-sitter grammar."""
    result: Dict[int, List[Highlight]] = {}
    prose_fence: Optional[str] = None
    current_section: Optional[str] = None
    for row, line in enumerate(source.splitlines()):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        highlights: List[Highlight] = []
        if prose_fence is not None:
            if indent == 0 and stripped == prose_fence:
                highlights.append(_highlight(line, 0, len(line), "heading.marker"))
                prose_fence = None
            elif line:
                highlights.append(_highlight(line, 0, len(line), "string.documentation"))
            result[row] = highlights
            continue
        if indent == 0 and _FENCE_RE.fullmatch(stripped):
            prose_fence = stripped
            result[row] = [_highlight(line, 0, len(line), "heading.marker")]
            continue
        if stripped.startswith("//"):
            result[row] = [_highlight(line, indent, len(line), "comment")]
            continue
        if not stripped:
            continue

        protected: List[Tuple[int, int]] = []
        for match in _STRING_RE.finditer(line):
            protected.append(match.span())

        directive = re.match(r"^\s*(@[A-Za-z][A-Za-z-]*)", line)
        if directive:
            highlights.append(_highlight(line, directive.start(1), directive.end(1), "keyword"))
            remainder = re.search(rf"\s({_IDENTIFIER})\s*$", line[directive.end(1) :])
            if remainder:
                start = directive.end(1) + remainder.start(1)
                highlights.append(_highlight(line, start, start + len(remainder.group(1)), "type"))

        section = re.match(rf"^({_IDENTIFIER})(:)$", line)
        if section:
            current_section = section.group(1)
            highlights.append(_highlight(line, section.start(1), section.end(1), "keyword"))
        elif indent == 0:
            current_section = None

        for match in _QUALIFIED_RE.finditer(line):
            if not _overlaps(*match.span(), protected):
                highlights.append(_highlight(line, match.start(), match.end(), "variable.builtin"))
        for match in _CALL_RE.finditer(line):
            if not _overlaps(*match.span(1), protected):
                highlights.append(_highlight(line, match.start(1), match.end(1), "function.call"))
        for match in _NUMBER_RE.finditer(line):
            if not _overlaps(*match.span(), protected):
                highlights.append(_highlight(line, match.start(), match.end(), "number"))
        for match in _BOOLEAN_RE.finditer(line):
            if not _overlaps(*match.span(), protected):
                highlights.append(_highlight(line, match.start(), match.end(), "boolean"))
        for match in _OPERATOR_RE.finditer(line):
            if not _overlaps(*match.span(), protected):
                highlights.append(_highlight(line, match.start(), match.end(), "operator"))

        declaration = _MEMBER_RE.match(line)
        declaration_tail = line[declaration.end() :].lstrip() if declaration else ""
        declaration_valid = False
        if current_section == "functions":
            declaration_valid = declaration_tail.startswith("(")
        elif current_section == "tables":
            declaration_valid = declaration_tail.startswith(":")
        elif current_section in {"inputs", "fields", "outputs", "groups", "presets", "display"}:
            declaration_valid = declaration_tail.startswith(":")
        elif current_section == "info":
            declaration_valid = declaration_tail.startswith("=")
        elif current_section == "dimensions":
            declaration_valid = True
        elif current_section == "units":
            declaration_valid = declaration_tail.startswith("=")
        elif current_section == "domains":
            declaration_valid = declaration_tail.startswith(":")
        if declaration and indent and declaration_valid:
            if current_section in {"functions", "tables"}:
                name_style = "function"
            elif current_section in {"dimensions", "units", "domains"}:
                name_style = "type"
            else:
                name_style = "variable.builtin"
            highlights.append(
                _highlight(line, declaration.start("name"), declaration.end("name"), name_style)
            )
        if current_section == "aliases":
            alias = re.match(r"^\s+([^\W\d]\w*)\s*=", line, re.UNICODE)
            if alias:
                highlights.append(_highlight(line, alias.start(1), alias.end(1), "variable.builtin"))
        if current_section in {"inputs", "fields", "outputs"}:
            for type_match in re.finditer(
                rf":\s*((?:number\[{_IDENTIFIER}\])|boolean|{_IDENTIFIER})", line
            ):
                highlights.append(
                    _highlight(line, type_match.start(1), type_match.end(1), "type")
                )
        if current_section == "functions":
            return_type = re.search(rf"->\s*({_IDENTIFIER})", line)
            if return_type:
                highlights.append(
                    _highlight(line, return_type.start(1), return_type.end(1), "type")
                )
        for match in _STRING_RE.finditer(line):
            highlights.append(_highlight(line, match.start(), match.end(), "string"))
        if highlights:
            result[row] = highlights
    return result


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
    _snippet(
        "图表文档",
        "图表文档",
        "plot document",
        "@kirin 1\n@plot plot_id\n\n// 中文标题\n\nx: entry.input\nrange: 0..1\npoints: 101\n\ny:\n  entry.output\n\n$0",
        3,
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
    _snippet("说明字段", "说明字段", "info", 'info:\n  note "说明" = "$0"', 16),
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
        if section not in {"inputs", "fields", "functions", "tables", "outputs"}:
            continue
        match = _MEMBER_RE.match(line)
        tail = line[match.end() :].lstrip() if match else ""
        if match and (
            (section == "functions" and tail.startswith("("))
            or (section == "tables" and tail.startswith(":"))
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
