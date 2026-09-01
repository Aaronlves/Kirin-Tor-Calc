from __future__ import annotations

from pathlib import Path

from kirin_tor.authoring import (
    build_completion_candidates,
    prepare_completion_insertion,
)
from kirin_tor.diagnostics import extract_author_title, format_author_diagnostic
from kirin_tor.errors import SchemaError, SourceLocation


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
