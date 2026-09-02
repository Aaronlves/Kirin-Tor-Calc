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
    source = "@kirin 2\n@entry model\n\n// 中文标题\n\ninput x： number[dimensionless] = 1\n"
    assert extract_author_title(source, "model") == "中文标题"
    error = SchemaError(
        "unknown v2 declaration",
        SourceLocation(path=str(path), entry_id="model", line=6, column=1),
    )
    rendered = format_author_diagnostic(error, tmp_path, {path: source})
    assert "[语法错误]" in rendered
    assert "全角符号" in rendered
    assert "`：` → `:`" in rendered


def test_completion_index_and_snippets(tmp_path: Path) -> None:
    base = tmp_path / "entries" / "base.kirin"
    model = tmp_path / "entries" / "model.kirin"
    base_source = """@kirin 2
@entry base

dimension damage "伤害"

unit damage = damage

domain probability: dimensionless in 0..1

input crit "暴击率": number[dimensionless] = 0.25

function double "翻倍"(value: number[dimensionless]): dimensionless = value * 2

distribution roll "结果分布": dimensionless:
  outcomes:
    - 0 @ 1 - crit
    - 1 @ crit
"""
    model_source = """@kirin 2
@entry model

alias 技能 = base.double

output result "总计": dimensionless = 技能(base.crit)
"""
    sources = {base: base_source, model: model_source}
    assert build_completion_candidates(sources, model, "暴击")[0].insert_text == "base.crit"
    assert build_completion_candidates(sources, model, "技能")[0].insert_text == "技能($0)"
    assert build_completion_candidates(sources, model, "输出")[0].label == "输出声明"
    assert build_completion_candidates(sources, model, "平方根")[0].insert_text == "sqrt($0)"
    assert build_completion_candidates(sources, model, "结果分布")[0].insert_text == "base.roll"
    assert build_completion_candidates(sources, model, "分布期望")[0].insert_text == "expectation($0)"
    assert build_completion_candidates(sources, model, "有限分布")[0].label == "有限分布声明"
    assert build_completion_candidates(sources, model, "过程")[0].insert_text.startswith(
        "process mechanism:"
    )
    assert build_completion_candidates(sources, model, "场景")[0].insert_text.startswith(
        "scenario trial:"
    )
    inserted, cursor = prepare_completion_insertion("piecewise(\n  $0\n)", "  ")
    assert inserted == "piecewise(\n    \n  )"
    assert inserted[:cursor].endswith("    ")


def test_authoring_index_tracks_definitions_aliases_references_and_safe_rename() -> None:
    skill = AuthoringSource(
        "entries/skill.kirin",
        "entries/skill.kirin",
        """@kirin 2
@entry skill

function expected(c: probability): damage = 1000 * (1 + c)
""",
    )
    combo = AuthoringSource(
        "entries/combo.kirin",
        "entries/combo.kirin",
        """@kirin 2
@entry combo

alias 技能 = skill.expected

input crit: probability = 0.1

output total "总计": damage = 技能(crit)

group damage:
  - total

display total = integer

chart preview:
  x = combo.crit
  range = 0..1
  points = 2
  y:
    - combo.total
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
    assert "  - combined_total" in rendered
    assert "display combined_total = integer" in rendered
    assert "    - combo.combined_total" in rendered
    with pytest.raises(ParameterError, match="already exists"):
        rename_authoring_symbol([skill, combo], "combo.total", "crit")
    read_only_skill = AuthoringSource(skill.key, skill.path, skill.text, True)
    with pytest.raises(WorkspaceError, match="read-only"):
        rename_authoring_symbol([read_only_skill, combo], "skill.expected", "average")


def test_safe_formatter_preserves_prose_and_comments() -> None:
    source = "@kirin 2  \n@entry model\n\n\n\n// 注释  \n---\n保留尾随空格  \n---\n\toutput result: dimensionless = 1  \n"
    rendered = format_kirin_source(source)
    assert rendered.startswith("""@kirin 2
@entry model
""")
    assert "保留尾随空格  \n" in rendered
    assert "  output result: dimensionless = 1\n" in rendered


def test_authoring_references_respect_bounded_aggregate_local_names() -> None:
    source = AuthoringSource(
        "entries/model.kirin",
        "entries/model.kirin",
        """@kirin 2
@entry model

input index: nonnegative_integer = 1

input chance: probability = 0.5

output total: dimensionless = sum(index, index, 0, 2)

output chance_copy: probability = chance
""",
    )
    index = build_authoring_index([source])
    assert not any(item["symbol_id"] == "model.index" for item in index["references"])
    chance_references = [item for item in index["references"] if item["symbol_id"] == "model.chance"]
    assert [(item["location"]["line"], item["text"]) for item in chance_references] == [(10, "chance")]


def test_authoring_completes_and_indexes_multi_level_object_paths(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "skills.kirin"
    source = """@kirin 2
@entry skills

type coefficient:
  direct: dimensionless
  periodic "周期伤害": dimensionless

type skill:
  coefficient: coefficient

skill arcane_blast "奥术冲击":
  coefficient:
    direct = 100
    periodic = 25

output dot: dimensionless = arcane_blast.coefficient.periodic
"""
    completed = build_completion_candidates({path: source}, path, "周期伤害")
    assert completed[0].insert_text == "arcane_blast.coefficient.periodic"

    index = build_authoring_index(
        [AuthoringSource("entries/skills.kirin", "entries/skills.kirin", source)]
    )
    assert any(
        item["id"] == "skills.arcane_blast.coefficient.periodic"
        for item in index["symbols"]
    )
    assert any(
        item["symbol_id"] == "skills.arcane_blast.coefficient.periodic"
        and item["text"] == "arcane_blast.coefficient.periodic"
        for item in index["references"]
    )
