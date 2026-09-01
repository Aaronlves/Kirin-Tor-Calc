"""Chinese presentation of stable Kirin Tor errors for the authoring workbench."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, Optional

from .errors import KTError, SourceLocation, ValidationErrors


ERROR_TITLES = {
    "workspace_error": "工作区错误",
    "package_error": "社区 Package 错误",
    "schema_error": "语法错误",
    "expression_error": "公式错误",
    "reference_error": "引用错误",
    "dependency_cycle": "循环依赖",
    "unit_error": "单位错误",
    "parameter_error": "参数错误",
    "domain_error": "值域错误",
    "timeout": "计算超时",
    "unsupported": "暂不支持",
    "validation_errors": "校验错误",
}

FULL_WIDTH_PUNCTUATION = {
    "：": ":",
    "，": ",",
    "（": "(",
    "）": ")",
    "＝": "=",
    "“": '"',
    "”": '"',
    "。": ".",
}


def extract_author_title(source: str, fallback: str) -> str:
    """Use the first non-empty // comment as a presentation-only document title."""
    for raw_line in source.splitlines():
        line = raw_line.lstrip()
        if line.startswith("//"):
            title = "".join(character for character in line[2:].strip() if character.isprintable())
            if title:
                return title[:120]
    return fallback


def _translated_message(message: str, code: str) -> str:
    exact_prefixes = (
        ("first declaration must be", "文件第一条声明必须是 `@kirin 1`。"),
        ("second declaration must be", "第二条声明必须指定 `@entry` 及其正式 ID。"),
        ("input must use", "输入声明格式不正确。应写为 `ID [\"标签\"]: 类型 [= 默认值] [in 下限..上限]`。"),
        ("field must use", "字段声明格式不正确。字段应使用 `名称: 类型 = 值或公式`。"),
        ("function must use", "函数声明格式不正确。应写为 `ID [\"标签\"](参数) -> 单位 = 公式`。"),
        ("output must use", "输出声明格式不正确。应写为 `ID [\"标签\"]: 单位 = 公式`。"),
        ("alias must use", "别名声明格式不正确。应写为 `中文别名 = entry.member`。"),
        ("tabs are not allowed", "结构化语法中不能使用 Tab，请改用空格缩进。"),
        ("content outside a section may not be indented", "章节之外的内容不能缩进。"),
        ("expected a directive", "这里需要指令、说明块、章节或 `键: 值`。"),
        ("plot is missing required key", "图表缺少必要配置。"),
    )
    for prefix, translated in exact_prefixes:
        if message.startswith(prefix):
            return translated

    patterns = (
        (r"^unknown directive @(.+)$", lambda m: f"未知指令 `@{m.group(1)}`。"),
        (r"^unknown entry section\(s\): (.+)$", lambda m: f"未知条目章节：{m.group(1)}。"),
        (r"^unknown plot (?:section|key) '([^']+)'$", lambda m: f"未知章节或配置项 `{m.group(1)}`。"),
        (r"^duplicate (.+)$", lambda m: f"存在重复声明：{m.group(1)}。"),
        (r"^undeclared variable '([^']+)'$", lambda m: f"没有声明变量 `{m.group(1)}`，请检查拼写或增加别名。"),
        (r"^missing reference to entry '([^']+)'$", lambda m: f"找不到条目 `{m.group(1)}`。"),
        (r"^entry '([^']+)' has no (.+) '([^']+)'$", lambda m: f"条目 `{m.group(1)}` 中没有{m.group(2)} `{m.group(3)}`。"),
        (r"^unsupported unit '([^']+)'", lambda m: f"没有声明单位 `{m.group(1)}`。"),
        (r"^parameter '([^']+)' is ambiguous", lambda m: f"参数 `{m.group(1)}` 有多个候选，请使用正式限定名。"),
        (r"^undeclared parameter '([^']+)'$", lambda m: f"没有声明参数 `{m.group(1)}`。"),
    )
    for pattern, render in patterns:
        match = re.match(pattern, message)
        if match:
            return render(match)

    fallbacks = {
        "workspace_error": "工作区无法加载或不符合约定。",
        "package_error": "社区 Package 的声明、版本、依赖、缓存或内容校验失败。",
        "schema_error": "源文件不符合 Kirin 语法或结构约定。",
        "expression_error": "公式无法解析，或使用了不允许的结构。",
        "reference_error": "引用无法解析到正式条目或成员。",
        "dependency_cycle": "定义之间形成了循环依赖。",
        "unit_error": "单位或量纲不兼容。",
        "parameter_error": "参数缺失、冲突或超出允许范围。",
        "domain_error": "数值不满足声明的值域或公式定义域。",
        "timeout": "计算超过时间限制并已终止。",
        "unsupported": "当前版本不支持这个操作。",
    }
    return fallbacks.get(code, "发生了无法完成校验的错误。")


def _location_text(location: Optional[SourceLocation], root: Optional[Path]) -> Optional[str]:
    if location is None:
        return None
    rendered_path = location.path
    if rendered_path and root is not None:
        try:
            rendered_path = str(Path(rendered_path).resolve().relative_to(root.resolve()))
        except (OSError, ValueError):
            pass
    if rendered_path and location.line is not None:
        rendered_path += f":{location.line}"
        if location.column is not None:
            rendered_path += f":{location.column}"
    parts = []
    if rendered_path:
        parts.append(rendered_path)
    if location.entry_id:
        parts.append(f"条目 {location.entry_id}")
    if location.field:
        parts.append(f"字段 {location.field}")
    return " · ".join(parts) if parts else None


def _source_line(
    location: Optional[SourceLocation], sources: Optional[Mapping[Path, str]]
) -> Optional[str]:
    if location is None or location.path is None or location.line is None or not sources:
        return None
    target = Path(location.path).resolve()
    source = next((text for path, text in sources.items() if path.resolve() == target), None)
    if source is None:
        return None
    lines = source.splitlines()
    if 1 <= location.line <= len(lines):
        return lines[location.line - 1]
    return None


def _punctuation_suggestion(line: Optional[str]) -> Optional[str]:
    if line is None:
        return None
    replacements = []
    for source, target in FULL_WIDTH_PUNCTUATION.items():
        if source in line and (source, target) not in replacements:
            replacements.append((source, target))
    if not replacements:
        return None
    rendered = "、".join(f"`{source}` → `{target}`" for source, target in replacements)
    return f"检测到可能误用的全角符号：{rendered}。"


def _format_one(
    error: KTError,
    root: Optional[Path],
    sources: Optional[Mapping[Path, str]],
) -> str:
    title = ERROR_TITLES.get(error.code, "错误")
    location = _location_text(error.location, root)
    translated = _translated_message(error.message, error.code)
    lines = [f"[{title}] {translated}"]
    if location:
        lines.insert(0, location)
    suggestion = _punctuation_suggestion(_source_line(error.location, sources))
    if suggestion:
        lines.append(f"建议：{suggestion}")
    lines.append(f"技术详情：{error.message}")
    return "\n".join(lines)


def format_author_diagnostic(
    error: KTError,
    root: Optional[Path] = None,
    sources: Optional[Mapping[Path, str]] = None,
) -> str:
    """Render one or many stable errors as Chinese author-facing diagnostics."""
    if isinstance(error, ValidationErrors):
        blocks = [_format_one(item, root, sources) for item in error.errors]
        return f"发现 {len(blocks)} 个校验错误：\n\n" + "\n\n".join(blocks)
    return _format_one(error, root, sources)


def author_error_payload(
    error: KTError,
    root: Optional[Path] = None,
    sources: Optional[Mapping[Path, str]] = None,
) -> dict:
    """Add presentation text without changing stable error codes or fields."""
    payload = error.as_dict()
    if isinstance(error, ValidationErrors):
        payload["errors"] = [
            author_error_payload(item, root, sources) for item in error.errors
        ]
    payload["author_message"] = format_author_diagnostic(error, root, sources)
    return payload
