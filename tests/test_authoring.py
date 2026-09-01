from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.authoring import (
    AuthoringSource,
    build_authoring_index,
    build_completion_candidates,
    format_kirin_source,
    prepare_completion_insertion,
    rename_authoring_symbol,
)
from kirin_tor.diagnostics import extract_author_title, format_author_diagnostic
from kirin_tor.errors import ParameterError, SchemaError, SourceLocation, WorkspaceError


def test_chinese_title_and_full_width_punctuation_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "model.kirin"
    source = "@kirin 1\n@entry model\n\n// 中文标题\n\ninputs：\n  x: number[dimensionless] = 1\n"
    assert extract_author_title(source, "model") == "中文标题"
    error = SchemaError(
        "expected a directive, description block, section, or KEY: VALUE",
        SourceLocation(path=str(path), entry_id="model", line=6, column=1),
    )
    rendered = format_author_diagnostic(error, tmp_path, {path: source})
    assert "[语法错误]" in rendered
    assert "全角符号" in rendered
    assert "`：` → `:`" in rendered


def test_completion_index_and_snippets(tmp_path: Path) -> None:
    base = tmp_path / "entries" / "base.kirin"
    model = tmp_path / "entries" / "model.kirin"
    base_source = """@kirin 1
@entry base

// 基础

dimensions:
  damage "伤害"

units:
  damage = damage

domains:
  probability: number[dimensionless] in 0..1

inputs:
  crit "暴击率": number[dimensionless] = 0.25

functions:
  double "翻倍"(value: number[dimensionless]) -> dimensionless = value * 2

distributions:
  roll "结果分布": dimensionless:
    0 @ 1 - crit
    1 @ crit

recurrences:
  bounded_total "有限递推结果": dimensionless:
    initial = 0
    steps = 2
    next(current, index) = current + index

state_models:
  cycle "状态循环":
    states:
      ready
    transitions:
      ready -> ready @ 1
"""
    model_source = """@kirin 1
@entry model

aliases:
  技能 = base.double

outputs:
  result "总计": dimensionless = 技能(base.crit)
"""
    sources = {base: base_source, model: model_source}
    assert build_completion_candidates(sources, model, "暴击")[0].insert_text == "base.crit"
    assert build_completion_candidates(sources, model, "技能")[0].insert_text == "技能($0)"
    assert build_completion_candidates(sources, model, "输出")[0].label == "输出章节"
    assert build_completion_candidates(sources, model, "平方根")[0].insert_text == "sqrt($0)"
    assert build_completion_candidates(sources, model, "结果分布")[0].insert_text == "base.roll"
    assert build_completion_candidates(sources, model, "分布期望")[0].insert_text == "expectation($0)"
    assert build_completion_candidates(sources, model, "有限分布")[0].label == "有限分布章节"
    assert build_completion_candidates(sources, model, "有限递推结果")[0].insert_text == "base.bounded_total"
    assert build_completion_candidates(sources, model, "状态循环")[0].insert_text == "base.cycle"
    assert build_completion_candidates(sources, model, "稳态概率")[0].insert_text == "steady_probability(model, $0)"
    assert build_completion_candidates(sources, model, "有限状态")[0].label == "有限状态模型章节"
    inserted, cursor = prepare_completion_insertion("piecewise(\n  $0\n)", "  ")
    assert inserted == "piecewise(\n    \n  )"
    assert inserted[:cursor].endswith("    ")


def test_authoring_index_tracks_definitions_aliases_references_and_safe_rename() -> None:
    skill = AuthoringSource(
        "entries/skill.kirin",
        "entries/skill.kirin",
        """@kirin 1
@entry skill

functions:
  expected(c: probability) -> damage = 1000 * (1 + c)
""",
    )
    combo = AuthoringSource(
        "entries/combo.kirin",
        "entries/combo.kirin",
        """@kirin 1
@entry combo

aliases:
  技能 = skill.expected

inputs:
  crit: probability = 0.1

outputs:
  total "总计": damage = 技能(crit)

groups:
  damage:
    total

display:
  total: integer

y:
  combo.total
""",
    )
    index = build_authoring_index([skill, combo])
    total = next(item for item in index["symbols"] if item["id"] == "combo.total")
    assert total["label"] == "总计"
    assert total["unit"] == "damage"
    skill_references = [item for item in index["references"] if item["symbol_id"] == "skill.expected"]
    assert {(item["text"], item["via_alias"]) for item in skill_references} == {
        ("skill.expected", False),
        ("技能", True),
    }
    assert sum(item["symbol_id"] == "combo.total" for item in index["references"]) == 3

    renamed = rename_authoring_symbol([skill, combo], "combo.total", "combined_total")
    assert renamed["edits"] == 4
    rendered = renamed["changes"][0]["text"]
    assert 'combined_total "总计"' in rendered
    assert "    combined_total" in rendered
    assert "  combined_total: integer" in rendered
    assert "  combo.combined_total" in rendered
    with pytest.raises(ParameterError, match="already exists"):
        rename_authoring_symbol([skill, combo], "combo.total", "crit")
    read_only_skill = AuthoringSource(skill.key, skill.path, skill.text, True)
    with pytest.raises(WorkspaceError, match="read-only"):
        rename_authoring_symbol([read_only_skill, combo], "skill.expected", "average")


def test_safe_formatter_preserves_prose_and_comments() -> None:
    source = "@kirin 1  \n@entry model\n\n\n\n// 注释  \n---\n保留尾随空格  \n---\n\toutputs:\n\t\tresult: dimensionless = 1  \n"
    rendered = format_kirin_source(source)
    assert rendered.startswith("@kirin 1\n@entry model\n\n\n// 注释\n")
    assert "保留尾随空格  \n" in rendered
    assert "  outputs:\n    result: dimensionless = 1\n" in rendered


def test_authoring_references_respect_bounded_expression_and_state_names() -> None:
    source = AuthoringSource(
        "entries/model.kirin",
        "entries/model.kirin",
        """@kirin 1
@entry model

inputs:
  index: nonnegative_integer = 1
  chance: probability = 0.5

state_models:
  cycle:
    states:
      ready
    transitions:
      ready -> ready @ chance

outputs:
  total: dimensionless = sum(index, index, 0, 2)
""",
    )
    index = build_authoring_index([source])
    assert not any(item["symbol_id"] == "model.index" for item in index["references"])
    chance_references = [item for item in index["references"] if item["symbol_id"] == "model.chance"]
    assert [(item["location"]["line"], item["text"]) for item in chance_references] == [(13, "chance")]
