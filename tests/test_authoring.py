from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.authoring import (
    AuthoringSource,
    BUILTIN_COMPLETIONS,
    build_authoring_index,
    build_completion_candidates,
    format_kirin_source,
    prepare_completion_insertion,
    rename_authoring_symbol,
)
from kirin_tor.authoring_contract import PROCESS_EXPRESSION_BUILTINS, public_authoring_contract
from kirin_tor.diagnostics import extract_author_title, format_author_diagnostic
from kirin_tor.errors import ParameterError, SchemaError, SourceLocation, WorkspaceError
from kirin_tor.scenario_measure_syntax import (
    TRAJECTORY_MEASURE_OPERATIONS,
    TRAJECTORY_MEASURE_SYNTAX,
)


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

    labeled = '@kirin 2\n@entry model\ninput x "说明（临时）"： number[dimensionless] = 1\n'
    rendered_label = format_author_diagnostic(
        SchemaError(
            "unknown v2 declaration",
            SourceLocation(path=str(path), entry_id="model", line=3, column=1),
        ),
        tmp_path,
        {path: labeled},
    )
    assert "`：` → `:`" in rendered_label
    assert "`（`" not in rendered_label
    assert "`）`" not in rendered_label

    percent = '@kirin 2\n@entry model\ninput x: probability = 50％ // 说明（不改）\n'
    rendered_percent = format_author_diagnostic(
        SchemaError(
            "invalid expression",
            SourceLocation(path=str(path), entry_id="model", line=3, column=24),
        ),
        tmp_path,
        {path: percent},
    )
    assert "`％` → `%`" in rendered_percent
    assert "`（`" not in rendered_percent


def test_completion_index_and_snippets(tmp_path: Path) -> None:
    base = tmp_path / "entries" / "base.kirin"
    model = tmp_path / "entries" / "model.kirin"
    base_source = """@kirin 2
@entry base

dimension damage "伤害"

unit damage = damage

domain probability "概率": dimensionless in 0..1

type effect "效果字段":
  amount "效果数值": damage
  enabled? "是否启用": boolean

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
    probability = next(
        item
        for item in build_completion_candidates(sources, model, "概率")
        if item.kind == "domain"
    )
    assert probability.insert_text == "probability"
    assert probability.kind == "domain"
    effect = build_completion_candidates(sources, model, "效果字段")[0]
    assert effect.insert_text == "base.effect"
    assert effect.kind == "type"
    amount = build_completion_candidates(sources, model, "效果数值")[0]
    assert amount.insert_text == "amount"
    assert amount.kind == "type_field"
    assert amount.detail == "类型字段 · base.effect.amount · damage"
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
    conditional_measure = build_completion_candidates(
        sources, model, "条件筛选最小值"
    )[0]
    assert conditional_measure.insert_text.startswith("minimum_where(")
    assert conditional_measure.kind == "measure"
    inserted, cursor = prepare_completion_insertion("piecewise(\n  $0\n)", "  ")
    assert inserted == "piecewise(\n    \n  )"
    assert inserted[:cursor].endswith("    ")


def test_trajectory_measure_authoring_and_help_cover_language_contract() -> None:
    assert {item.name for item in TRAJECTORY_MEASURE_SYNTAX} == (
        TRAJECTORY_MEASURE_OPERATIONS
    )
    completion_names = {
        item.insert_text.split("(", 1)[0]
        for item in BUILTIN_COMPLETIONS
        if item.kind == "measure"
    }
    assert completion_names == TRAJECTORY_MEASURE_OPERATIONS

    reference_path = (
        Path(__file__).parents[1] / "frontend" / "src" / "syntax-reference.json"
    )
    sections = json.loads(reference_path.read_text(encoding="utf-8"))
    process = next(item for item in sections if item["id"] == "process")
    assert TRAJECTORY_MEASURE_OPERATIONS <= set(process["keywords"])
    visible_help = "\n".join((*process["rules"], process["code"]))
    assert all(name in visible_help for name in TRAJECTORY_MEASURE_OPERATIONS)

    catalog = json.loads(
        (
            Path(__file__).parents[1]
            / "frontend"
            / "src"
            / "syntax-reference-catalog.json"
        ).read_text(encoding="utf-8")
    )
    process_catalog = next(item for item in catalog if item["sectionId"] == "process")
    measure_reference = next(
        item
        for item in process_catalog["symbols"]
        if item["id"] == "scenario-measures-objectives"
    )
    structured_help = "\n".join(
        [
            measure_reference["signature"],
            *(field["value"] for field in measure_reference["fields"]),
            *(field["description"] for field in measure_reference["fields"]),
        ]
    )
    assert all(name in structured_help for name in TRAJECTORY_MEASURE_OPERATIONS)


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
    periodic_field = next(
        item for item in index["symbols"] if item["id"] == "skills.coefficient.periodic"
    )
    assert periodic_field["label"] == "周期伤害"
    assert periodic_field["kind"] == "type_field"
    assert periodic_field["unit"] == "dimensionless"
    assert any(
        item["id"] == "skills.arcane_blast.coefficient.periodic"
        for item in index["symbols"]
    )
    assert any(
        item["symbol_id"] == "skills.arcane_blast.coefficient.periodic"
        and item["text"] == "arcane_blast.coefficient.periodic"
        for item in index["references"]
    )


def test_contextual_completion_covers_dynamic_language_and_opaque_regions(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "dynamic.kirin"
    source = """@kirin 2
@entry dynamic

process counter:
  sta
  on tick():
    next value = siz

scenario trial:
  phases:
    - event
  use actor = counter:
  measure current: count = actor.cur
  bounds:
    horizon = 1 sec

analysis run:
  using = trial
  operation = opt

// state should stay ordinary author text
---
state should also stay ordinary author text
---
"""
    sources = {path: source}
    assert build_completion_candidates(sources, path, "sta", 5, 6)[0].insert_text.startswith("state ")
    assert build_completion_candidates(sources, path, "siz", 7, 21)[0].insert_text == "size($0)"
    assert build_completion_candidates(sources, path, "sec", 15, 20)[0].insert_text == "second"
    assert build_completion_candidates(sources, path, "opt", 19, 18)[0].insert_text == "optimize"
    assert build_completion_candidates(sources, path, "state", 21, 9) == []
    assert build_completion_candidates(sources, path, "state", 23, 9) == []

    scoped = tmp_path / "entries" / "scoped.kirin"
    scoped_source = """@kirin 2
@entry scoped

input static_value: count = 1

process first:
  input value: probability = 0.5
  state local: count = 0
  event input tick()
  on tick():
    next local = 1

process second:
  state foreign: count = 0

source proof:
  cit
"""
    scoped_sources = {scoped: scoped_source}
    assert build_completion_candidates(scoped_sources, scoped, "local", 11, 19)[0].insert_text == "local"
    assert build_completion_candidates(scoped_sources, scoped, "foreign", 11, 19) == []
    assert build_completion_candidates(scoped_sources, scoped, "static_value", 11, 19) == []
    type_items = build_completion_candidates(scoped_sources, scoped, "", 7, 16)
    type_insertions = {item.insert_text for item in type_items}
    assert "probability" in type_insertions
    assert "map[$0, value_type, capacity]" in type_insertions
    assert build_completion_candidates(scoped_sources, scoped, "cit", 17, 6)[0].insert_text == 'citation = "$0"'
    assert build_completion_candidates(scoped_sources, scoped, "sqrt", 17, 6) == []

    library = tmp_path / "entries" / "library.kirin"
    report = tmp_path / "entries" / "report.kirin"
    library_source = """@kirin 2
@entry library

process counter:
  state value: count = 0
  observe current: count = value

scenario trial:
  phases:
    - event
  use actor = counter:
  measure result: count = final(actor.current)
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    report_source = """@kirin 2
@entry report

analysis run:
  using = library.trial
  operation = run
  chart trace:
    kind = trajectory
    series:
      - actor.cur
"""
    cross_source_items = build_completion_candidates(
        {library: library_source, report: report_source},
        report,
        "actor.cur",
        10,
        18,
    )
    assert cross_source_items[0].insert_text == "actor.current"


def test_contextual_completion_keeps_process_only_types_out_of_static_declarations(
    tmp_path: Path,
) -> None:
    static_path = tmp_path / "entries" / "static.kirin"
    static_source = """@kirin 2
@entry static

input values: ma
"""
    static_items = build_completion_candidates(
        {static_path: static_source}, static_path, "ma", 4, 17
    )
    assert "map[$0, value_type, capacity]" not in {
        item.insert_text for item in static_items
    }

    process_path = tmp_path / "entries" / "process.kirin"
    process_source = """@kirin 2
@entry process_types

process machine:
  state values: ma
"""
    process_items = build_completion_candidates(
        {process_path: process_source}, process_path, "ma", 5, 19
    )
    assert "map[$0, value_type, capacity]" in {
        item.insert_text for item in process_items
    }


def test_contextual_completion_preserves_trailing_lines_and_stops_at_new_declarations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "entries" / "incomplete.kirin"
    after_prose = """@kirin 2
@entry after_prose

---
author notes
---
"""
    trailing_items = build_completion_candidates(
        {path: after_prose}, path, "", 7, 1
    )
    assert any(item.insert_text.startswith("process ") for item in trailing_items)

    after_incomplete_expression = """@kirin 2
@entry incomplete

output broken: dimensionless = max(

pro
"""
    declaration_items = build_completion_candidates(
        {path: after_incomplete_expression}, path, "pro", 6, 4
    )
    assert any(item.insert_text.startswith("process ") for item in declaration_items)
    assert not any(
        item.insert_text.startswith("product(") for item in declaration_items
    )


def test_prose_examples_do_not_override_scenario_instance_bindings(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "opaque.kirin"
    source = """@kirin 2
@entry opaque

process real:
  state value: count = 0
  observe actual: count = value

process fake:
  state value: count = 0
  observe phantom: count = value

scenario trial:
  phases:
    - event
  use actor = real:
  measure result: count = final(actor.actual)
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1

---
scenario trial:
  use actor = fake:
---
"""
    index = build_authoring_index([
        AuthoringSource(str(path), str(path), source)
    ])
    actual = next(
        item for item in index["symbols"]
        if item["kind"] == "process_observation" and item["name"] == "actual"
    )
    reference = next(
        item for item in index["references"]
        if item["text"] == "actor.actual"
    )
    assert reference["symbol_id"] == actual["id"]

    draft = source.replace("actor.actual", "actor.ac")
    line_number, line_text = next(
        (number, line)
        for number, line in enumerate(draft.splitlines(), 1)
        if "actor.ac" in line
    )
    insertions = {
        item.insert_text
        for item in build_completion_candidates(
            {path: draft}, path, "actor.ac", line_number, len(line_text) + 1
        )
    }
    assert "actor.actual" in insertions
    assert "actor.phantom" not in insertions


def test_dynamic_authoring_index_tracks_process_and_scenario_symbols() -> None:
    source = AuthoringSource(
        "entries/dynamic.kirin",
        "entries/dynamic.kirin",
        """@kirin 2
@entry dynamic

process counter:
  state value: count = 0
  event input tick()
  on tick():
    next value = value + 1
  observe current: count = value

scenario trial:
  phases:
    - event
  use actor = counter:
  measure result: count = final(actor.current)
  objective best:
    maximize result
  bounds:
    horizon = 1 second
    maximum_events = 2
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1

analysis optimize_trial:
  using = trial
  operation = optimize
  objectives:
    - best
""",
    )
    index = build_authoring_index([source])
    by_kind = {item["kind"]: item for item in index["symbols"]}
    assert by_kind["process_state"]["name"] == "value"
    assert by_kind["process_event"]["name"] == "tick"
    assert by_kind["process_observation"]["name"] == "current"
    assert by_kind["scenario_instance"]["name"] == "actor"
    assert by_kind["scenario_measure"]["name"] == "result"
    assert by_kind["scenario_objective"]["name"] == "best"
    references = {(item["text"], item["symbol_id"]) for item in index["references"]}
    assert ("tick", by_kind["process_event"]["id"]) in references
    assert ("value", by_kind["process_state"]["id"]) in references
    assert ("actor.current", by_kind["process_observation"]["id"]) in references
    assert ("result", by_kind["scenario_measure"]["id"]) in references
    assert ("best", by_kind["scenario_objective"]["id"]) in references


def test_guarded_scenario_action_is_indexed_referenced_and_completed(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "guarded.kirin"
    source = """@kirin 2
@entry guarded

process machine:
  event input tick()

scenario trial:
  phases:
    - decision
  use actor = machine:
  action guarded_action when true:
    send actor.tick() phase decision
  policy default:
    choose guarded_action when true
  decide every 1 second from 0 second until 0 second phase decision:
    - guarded_action
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1
"""
    index = build_authoring_index([
        AuthoringSource(str(path), str(path), source)
    ])
    action = next(
        item for item in index["symbols"]
        if item["kind"] == "scenario_action"
    )
    assert action["name"] == "guarded_action"
    assert [
        item["text"]
        for item in index["references"]
        if item["symbol_id"] == action["id"]
    ] == ["guarded_action", "guarded_action"]

    draft = source.replace(
        "choose guarded_action when true",
        "choose guarded",
    )
    line_number, line_text = next(
        (number, line)
        for number, line in enumerate(draft.splitlines(), 1)
        if "choose guarded" in line
    )
    insertions = {
        item.insert_text
        for item in build_completion_candidates(
            {path: draft}, path, "guarded", line_number, len(line_text) + 1
        )
    }
    assert "guarded_action" in insertions
    assert "guarded_action($0)" not in insertions


def test_contextual_completion_respects_event_directions_and_process_locals(
    tmp_path: Path,
) -> None:
    path = tmp_path / "entries" / "events.kirin"
    source = """@kirin 2
@entry events

process machine:
  input amount: count = 1
  state total: count = 0
  key timer_key
  phase local_phase
  event input inc(value: count)
  event output changed(value: count, flag: boolean)
  event internal wake()
  action apply(value: count) when val
  flow total(current, elapsed) = cur
  on inc(value):
    let local: count = value
    when true:
      let inner: count = local
      next total = inn
    emit cha
    emit changed(value = loc, flag = true)
    schedule wak
    schedule wake() after tot
    replace wake() after loc phase local_phase key timer_key
    next total = loc
    loc
  on app
  on inc(value) when val

scenario demo:
  phases:
    - event
  use actor = machine:
    phase local_phase = event
  connect actor.cha
  connect actor.changed -> actor.inc
  at 0 second phase event:
    send actor.inc
  action invoke:
    send actor.app
  decide after actor.cha
  measure event_total: count = sum_events(actor.changed.value)
  measure event_count: count = count_events(actor.changed)

analysis view:
  using = demo
  operation = run
  chart trace:
    kind = trajectory
    markers:
      - event actor.cha
"""
    sources = {path: source}

    def at(fragment: str) -> tuple[int, int]:
        line_number, line_text = next(
            (number, line)
            for number, line in enumerate(source.splitlines(), 1)
            if fragment in line
        )
        return line_number, len(line_text) + 1

    def insertions(
        prefix: str,
        fragment: str,
        *,
        cursor_after: str | None = None,
    ) -> set[str]:
        line_number, column = at(fragment)
        if cursor_after is not None:
            line_text = source.splitlines()[line_number - 1]
            column = line_text.index(cursor_after) + len(cursor_after) + 1
        return {
            item.insert_text
            for item in build_completion_candidates(
                sources, path, prefix, line_number, column
            )
        }

    assert "changed($0)" in insertions("cha", "emit cha")
    assert insertions("inc", "emit cha") == set()
    assert "wake($0)" in insertions("wak", "schedule wak")
    assert insertions("changed", "schedule wak") == set()
    assert "total" in insertions("tot", "schedule wake() after tot")
    assert "size($0)" in insertions("siz", "schedule wake() after tot")
    assert "local" in insertions("loc", "schedule wake() after tot")
    assert "local" in insertions(
        "loc",
        "emit changed(value = loc",
        cursor_after="emit changed(value = loc",
    )
    assert "local" in insertions(
        "loc",
        "replace wake() after loc",
        cursor_after="replace wake() after loc",
    )
    assert insertions("local", "    loc") == set()
    assert "apply($0)" in insertions("app", "  on app")
    assert insertions("changed", "  on app") == set()
    assert "value" in insertions("val", "on inc(value) when val")
    assert "event.id" in insertions("event.", "on inc(value) when val")

    assert "value" in insertions("val", "next total = loc")
    assert "local" in insertions("loc", "next total = loc")
    assert "event.time" in insertions("event.", "next total = loc")
    assert "inner" in insertions("inn", "next total = inn")
    assert insertions("inner", "emit cha") == set()
    assert "value" in insertions("val", "action apply")
    assert "current" in insertions("cur", "flow total")

    key_source = source.replace(
        "replace wake() after loc phase local_phase key timer_key",
        "replace wake() after loc phase local_phase key ",
    )
    key_line_number, key_line_text = next(
        (number, line)
        for number, line in enumerate(key_source.splitlines(), 1)
        if "replace wake() after loc" in line
    )
    key_insertions = {
        item.insert_text
        for item in build_completion_candidates(
            {path: key_source}, path, "", key_line_number, len(key_line_text) + 1
        )
    }
    assert {"timer_key", "event.id"} <= key_insertions
    assert {"local", "total", "size($0)"}.isdisjoint(key_insertions)

    event_key_source = key_source.replace(
        "phase local_phase key ",
        "phase local_phase key event.",
    )
    event_key_line = event_key_source.splitlines()[key_line_number - 1]
    event_key_insertions = {
        item.insert_text
        for item in build_completion_candidates(
            {path: event_key_source},
            path,
            "event.",
            key_line_number,
            len(event_key_line) + 1,
        )
    }
    assert "event.id" in event_key_insertions
    assert "event.time" not in event_key_insertions

    assert "actor.changed" in insertions("actor.cha", "connect actor.cha")
    assert insertions("actor.inc", "connect actor.cha") == set()
    assert "actor.inc" in insertions("actor.inc", "connect actor.changed -> actor.inc")
    assert insertions("actor.changed", "connect actor.changed -> actor.inc") == set()
    assert "actor.inc($0)" in insertions("actor.inc", "send actor.inc")
    assert insertions("actor.apply", "send actor.inc") == set()
    assert "actor.apply($0)" in insertions("actor.app", "send actor.app")
    assert "actor.inc($0)" in insertions("actor.inc", "send actor.app")
    assert "actor.changed" in insertions("actor.cha", "decide after actor.cha")
    assert "actor.inc" in insertions("actor.inc", "decide after actor.cha")
    assert insertions("actor.wake", "decide after actor.cha") == set()
    measure_line, measure_text = next(
        (number, line)
        for number, line in enumerate(source.splitlines(), 1)
        if "sum_events(actor.changed.value)" in line
    )
    measure_column = measure_text.index("actor.changed") + len("actor.cha") + 1
    measure_items = {
        item.insert_text
        for item in build_completion_candidates(
            sources, path, "actor.cha", measure_line, measure_column
        )
    }
    assert "actor.changed.value" in measure_items
    assert "actor.changed" not in measure_items
    assert "actor.changed.flag" not in measure_items
    count_line, count_text = next(
        (number, line)
        for number, line in enumerate(source.splitlines(), 1)
        if "count_events(actor.changed)" in line
    )
    count_column = count_text.index("actor.changed") + len("actor.cha") + 1
    count_items = {
        item.insert_text
        for item in build_completion_candidates(
            sources, path, "actor.cha", count_line, count_column
        )
    }
    assert "actor.changed" in count_items
    assert "actor.changed.value" not in count_items
    assert not any(item.startswith("actor.inc") for item in measure_items)
    assert "actor.changed" in insertions("actor.cha", "- event actor.cha")
    assert insertions("actor.wake", "- event actor.cha") == set()


def test_multiline_expression_completion_preserves_expression_dialect(
    tmp_path: Path,
) -> None:
    static_path = tmp_path / "entries" / "static.kirin"
    static_source = """@kirin 2
@entry static

output total: dimensionless = max(
  sq
"""
    static_items = build_completion_candidates(
        {static_path: static_source}, static_path, "sq", 5, 5
    )
    assert static_items[0].insert_text == "sqrt($0)"
    assert build_completion_candidates(
        {static_path: static_source}, static_path, "sum", 5, 5
    )[0].insert_text == "sum(expression, index, lower, $0)"

    process_path = tmp_path / "entries" / "process.kirin"
    process_source = """@kirin 2
@entry process_model

process machine:
  state total: count = 0
  observe current: count = max(
    siz
"""
    process_items = build_completion_candidates(
        {process_path: process_source}, process_path, "siz", 7, 8
    )
    assert process_items[0].insert_text == "size($0)"
    assert build_completion_candidates(
        {process_path: process_source}, process_path, "sum", 7, 8
    )[0].insert_text == "sum($0)"

    static_operator_source = """@kirin 2
@entry static_operator

output total: dimensionless = 1 +
  sq
"""
    assert build_completion_candidates(
        {static_path: static_operator_source}, static_path, "sq", 5, 5
    )[0].insert_text == "sqrt($0)"

    process_operator_source = """@kirin 2
@entry process_operator

process machine:
  state total: count = 0
  event input tick()
  on tick():
    next total = max(1, 2) +
      siz
"""
    assert build_completion_candidates(
        {process_path: process_operator_source}, process_path, "siz", 9, 10
    )[0].insert_text == "size($0)"

    indexed = build_authoring_index([
        AuthoringSource(
            "entries/overloads.kirin",
            "entries/overloads.kirin",
            """@kirin 2
@entry overloads

output static_total: dimensionless = sum(1, index, 0, 1)

process machine:
  state values: list[count, 2] = empty()
  observe dynamic_total: count = sum(values)
""",
        )
    ])
    sum_references = {
        reference["symbol_id"]
        for reference in indexed["references"]
        if reference["text"] == "sum"
    }
    assert sum_references == {"builtin:static:sum", "builtin:process:sum"}
    sum_signatures = {
        item["scope"]: item["signature"]
        for item in indexed["builtins"]
        if item["name"] == "sum"
    }
    assert sum_signatures == {
        "static": "sum(expression, index, lower, …)",
        "process": "sum(values)",
    }


def test_authoring_contract_matches_process_builtins_and_reference_catalog() -> None:
    from kirin_tor.process_expression import _BUILTINS

    contract = public_authoring_contract()
    assert contract["version"] == 1
    assert set(PROCESS_EXPRESSION_BUILTINS) == _BUILTINS
    assert "^" not in contract["tokens"]["operators"]
    assert "**" in contract["tokens"]["operators"]
    assert "if" not in contract["tokens"]["keywords"]
    assert "else" not in contract["tokens"]["keywords"]
    assert "to" in contract["tokens"]["keywords"]
    assert contract["tokens"]["directives"] == ["kirin", "entry", "game-version", "status"]
    assert contract["tokens"]["literals"] == ["true", "false"]
    assert contract["tokens"]["compound_keywords"] == ["one-of"]
    assert contract["reference_identities"]["process_event"] == {
        "topic": "process",
        "symbol": "process-declarations",
    }

    catalog = json.loads(
        (
            Path(__file__).parents[1]
            / "frontend"
            / "src"
            / "syntax-reference-catalog.json"
        ).read_text(encoding="utf-8")
    )
    process_expressions = next(
        symbol
        for group in catalog
        for symbol in group["symbols"]
        if symbol["id"] == "process-expressions"
    )
    visible = json.dumps(process_expressions, ensure_ascii=False)
    assert all(name in visible for name in PROCESS_EXPRESSION_BUILTINS)
