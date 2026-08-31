from __future__ import annotations

from pathlib import Path

import pytest


pytest.importorskip("textual")
pytest.importorskip("plotext")

from textual.widgets import Select, TextArea

from kirin_tor.authoring import (
    build_completion_candidates,
    highlight_kirin_source,
    prepare_completion_insertion,
)
from kirin_tor.diagnostics import extract_author_title, format_tui_diagnostic
from kirin_tor.errors import SchemaError, SourceLocation
from kirin_tor.schema import PlotConfig
from kirin_tor.tui import KirinTUI, KirinTextArea, render_terminal_plot
from kirin_tor.workspace import initialize


def test_terminal_plot_renderer_builds_ansi_text() -> None:
    config = PlotConfig(
        id="curve",
        name="curve",
        type="plot",
        path=Path("curve.kirin"),
        raw={},
        raw_text="",
        sha256="",
        x="model.x",
        range_start="0",
        range_end="1",
        points=3,
        y=["model.result"],
        title="Preview",
        curve_labels={"model.result": "Result"},
    )
    scan = {
        "x": "model.x",
        "x_unit": "dimensionless",
        "targets": ["model.result"],
        "units": {"model.result": "dimensionless"},
        "rows": [
            {
                "x_approximate": str(index / 2),
                "values": {"model.result": {"approximate": str(index), "error": None}},
            }
            for index in range(3)
        ],
    }
    rendered = render_terminal_plot(scan, config, 50, 14)
    assert "Preview" in rendered.plain
    assert "Result" in rendered.plain


def test_chinese_title_and_full_width_punctuation_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "entries" / "model.kirin"
    source = "@kirin 1\n@entry model\n\n// 中文标题\n\ninputs：\n  x: number[dimensionless] = 1\n"
    assert extract_author_title(source, "model") == "中文标题"
    error = SchemaError(
        "expected a directive, description block, section, or KEY: VALUE",
        SourceLocation(path=str(path), entry_id="model", line=6, column=1),
    )
    rendered = format_tui_diagnostic(error, tmp_path, {path: source})
    assert "[语法错误]" in rendered
    assert "这里需要指令" in rendered
    assert "全角符号" in rendered
    assert "`：` → `:`" in rendered
    assert "entries/model.kirin:6:1" in rendered


def test_kirin_highlighting_completion_index_and_snippets(tmp_path: Path) -> None:
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
"""
    model_source = """@kirin 1
@entry model

aliases:
  技能 = base.double

outputs:
  result "总计": dimensionless = 技能(base.crit)
"""
    highlights = highlight_kirin_source(model_source)
    assert any(item[2] == "comment" for item in highlight_kirin_source(base_source)[3])
    assert any(item[2] == "variable.builtin" for item in highlights[4])
    assert any(item[2] == "string" for item in highlights[7])
    assert any(item[2] == "function.call" for item in highlights[7])
    editor = KirinTextArea.code_editor(model_source)
    assert editor._highlights == highlights

    sources = {base: base_source, model: model_source}
    label_matches = build_completion_candidates(sources, model, "暴击")
    assert label_matches[0].label == "暴击率"
    assert label_matches[0].insert_text == "base.crit"
    alias_matches = build_completion_candidates(sources, model, "技能")
    assert alias_matches[0].insert_text == "技能($0)"
    snippet_matches = build_completion_candidates(sources, model, "输出")
    assert snippet_matches[0].label == "输出章节"
    domain_matches = build_completion_candidates(sources, model, "prob")
    assert domain_matches[0].insert_text == "probability"
    builtin_matches = build_completion_candidates(sources, model, "平方根")
    assert builtin_matches[0].insert_text == "sqrt($0)"
    qualified_local = build_completion_candidates(sources, model, "model.res")
    assert qualified_local[0].insert_text == "model.result"
    inserted, cursor = prepare_completion_insertion("piecewise(\n  $0\n)", "  ")
    assert inserted == "piecewise(\n    \n  )"
    assert inserted[:cursor].endswith("    ")


@pytest.mark.asyncio
async def test_tui_validates_and_saves_new_kirin_buffer(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "workbench.kirin"
    app = KirinTUI(root, path)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause(0.8)
        assert "校验通过" in app.query_one("#status").render().plain
        await pilot.press("ctrl+s")
        await pilot.pause(0.8)
        assert path.is_file()
        assert "已保存" in app.query_one("#status").render().plain


@pytest.mark.asyncio
async def test_tui_switches_documents_without_losing_drafts_and_saves_all(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    first = root / "entries" / "first.kirin"
    second = root / "entries" / "second.kirin"
    first.write_text(
        "@kirin 1\n@entry first\n\n// 第一份\n\noutputs:\n  result: dimensionless = 1\n",
        encoding="utf-8",
    )
    second.write_text(
        "@kirin 1\n@entry second\n\n// 第二份\n\noutputs:\n  result: dimensionless = 2\n",
        encoding="utf-8",
    )
    app = KirinTUI(root, first)
    options = {value: label.plain for label, value in app._source_options()}
    assert options["entries/first.kirin"] == "第一份  ·  entries/first.kirin"
    assert options["entries/second.kirin"] == "第二份  ·  entries/second.kirin"
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause(0.3)
        editor = app.query_one("#editor", TextArea)
        editor.load_text(editor.text + "\n// first draft\n")
        await pilot.pause(0.1)

        selector = app.query_one("#source-select", Select)
        selector.value = "entries/second.kirin"
        await pilot.pause(0.2)
        assert app.source_path == second.resolve()
        editor.load_text(editor.text + "\n// second draft\n")
        await pilot.pause(0.1)

        selector.value = "entries/first.kirin"
        await pilot.pause(0.2)
        assert "// first draft" in editor.text
        await pilot.press("ctrl+s")
        await pilot.pause(0.8)

    assert "// first draft" in first.read_text(encoding="utf-8")
    assert "// second draft" in second.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_tui_shows_chinese_live_diagnostic_for_full_width_punctuation(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "broken.kirin"
    path.write_text(
        "@kirin 1\n@entry broken\n\n// 错误示例\n\ninputs：\n  x: number[dimensionless] = 1\n",
        encoding="utf-8",
    )
    app = KirinTUI(root, path)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause(0.8)
        diagnostic = app.query_one("#diagnostics").render().plain
        assert "语法错误" in diagnostic
        assert "全角符号" in diagnostic
        assert "`：` → `:`" in diagnostic


@pytest.mark.asyncio
async def test_tui_ctrl_space_inserts_chinese_alias_completion(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    base = root / "entries" / "base.kirin"
    model = root / "entries" / "model.kirin"
    base.write_text(
        """@kirin 1
@entry base

functions:
  double(value: number[dimensionless]) -> dimensionless = value * 2
""",
        encoding="utf-8",
    )
    model.write_text(
        """@kirin 1
@entry model

aliases:
  技能 = base.double

outputs:
  result: dimensionless = 技
""",
        encoding="utf-8",
    )
    app = KirinTUI(root, model)
    async with app.run_test(size=(110, 36)) as pilot:
        await pilot.pause(0.3)
        editor = app.query_one("#editor", TextArea)
        editor.move_cursor((7, len(editor.document[7])))
        await pilot.press("ctrl+space")
        await pilot.pause(0.1)
        assert app._completion_candidates[0].insert_text == "技能($0)"
        await pilot.press("enter")
        await pilot.pause(0.1)
        assert "result: dimensionless = 技能()" in editor.text
        assert editor.cursor_location == (7, len("  result: dimensionless = 技能("))
