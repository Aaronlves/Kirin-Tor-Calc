from __future__ import annotations

from pathlib import Path

import pytest


pytest.importorskip("textual")
pytest.importorskip("plotext")

from textual.widgets import Input, OptionList, Select, Static, TextArea

from kirin_tor.tui import KirinTUI
from kirin_tor.tui_components import DEFAULT_SCENARIO, NewDocumentScreen, VariantRow
from kirin_tor.workspace import initialize


@pytest.mark.asyncio
async def test_workbench_calculates_and_compares_player_variants(example_workspace: Path) -> None:
    source = example_workspace / "entries" / "组合模型.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.8)
        app.query_one("#target-select", Select).value = "combo.total"
        await pilot.pause(0.1)
        input_help = app.query_one("#calculation-input-help", Static).render().plain
        assert "暴击率（combo.crit）" in input_help
        rows = list(app.query(VariantRow))
        rows[0].query_one(".variant-name", Input).value = "基准"
        rows[0].query_one(".variant-scenario", Select).value = "baseline"
        rows[1].query_one(".variant-name", Input).value = "高暴击"
        rows[1].query_one(".variant-scenario", Select).value = DEFAULT_SCENARIO
        rows[1].query_one(".variant-overrides", Input).value = "暴击率=50%"

        app.action_calculate()
        await pilot.pause(1.2)

        assert app._last_comparison is not None
        variants = app._last_comparison["variants"]
        assert variants[0]["result"]["exact"] == "2750"
        assert variants[1]["result"]["exact"] == "3300"
        assert variants[1]["delta_percent"] == "20.0000000000"
        assert "已保存文档" in app.query_one("#calculation-details", Static).render().plain


@pytest.mark.asyncio
async def test_workbench_solves_a_player_target_from_the_baseline_variant(
    example_workspace: Path,
) -> None:
    source = example_workspace / "entries" / "组合模型.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(150, 44)) as pilot:
        await pilot.pause(0.8)
        app.query_one("#target-select", Select).value = "combo.total"
        await pilot.pause(0.1)
        app.query_one("#solve-variable", Select).value = "combo.crit"
        app.query_one("#solve-equals", Input).value = "3000 damage"
        app.query_one("#solve-range", Input).value = "0:1"
        first = list(app.query(VariantRow))[0]
        first.query_one(".variant-name", Input).value = "基准配装"
        first.query_one(".variant-scenario", Select).value = "baseline"

        app.action_solve_target()
        await pilot.pause(1.2)

        result = app.query_one("#solve-result", Static).render().plain
        assert "基准配装" in result
        assert "combo.crit = 4/11" in result


@pytest.mark.asyncio
async def test_new_document_is_a_draft_until_validated_save(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    existing = root / "entries" / "existing.kirin"
    existing.write_text(
        "@kirin 1\n@entry existing\n\noutputs:\n  result: dimensionless = 1\n",
        encoding="utf-8",
    )
    app = KirinTUI(root, existing)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.5)
        app.action_new_document()
        await pilot.pause(0.1)
        assert isinstance(app.screen, NewDocumentScreen)
        app.screen.query_one("#new-kind", Select).value = "model"
        app.screen.query_one("#new-id", Input).value = "player_build"
        await pilot.pause(0.1)
        await pilot.click("#new-create")
        await pilot.pause(0.2)

        created = root / "entries" / "player_build.kirin"
        assert app.source_path == created.resolve()
        assert created.resolve() in app._buffers
        assert not created.exists()

        await pilot.press("ctrl+s")
        await pilot.pause(0.9)
        assert created.is_file()
        assert "@entry player_build" in created.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_ad_hoc_chart_can_be_saved_as_plot_source_draft(example_workspace: Path) -> None:
    source = example_workspace / "entries" / "组合模型.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.8)
        app.query_one("#scan-x-select", Select).value = "combo.crit"
        app.query_one("#scan-y-select", Select).value = "combo.total"
        app.query_one("#scan-range", Input).value = "0:1/2"
        app.query_one("#scan-points", Input).value = "6"
        app.query_one("#scan-scenario", Select).value = "baseline"

        app.action_run_scan()
        await pilot.pause(1.2)

        assert app._last_scan is not None
        assert app._last_scan["points"] == 6
        assert app._last_scan["rows"][-1]["values"]["combo.total"]["exact"] == "3300"

        app.query_one("#scan-plot-id", Input).value = "crit_comparison"
        app.action_create_plot_draft()
        await pilot.pause(0.3)
        plot_path = example_workspace / "plots" / "crit_comparison.kirin"
        assert app.source_path == plot_path.resolve()
        assert not plot_path.exists()
        assert "x: combo.crit" in app._buffers[plot_path.resolve()]
        assert "scenario: baseline" in app._buffers[plot_path.resolve()]


@pytest.mark.asyncio
async def test_saved_plot_exports_real_svg_and_csv_files(example_workspace: Path) -> None:
    source = example_workspace / "plots" / "暴击曲线.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.8)
        app.action_export()
        await pilot.pause(2.0)

        svg = example_workspace / "results" / "damage.svg"
        csv = example_workspace / "results" / "damage.csv"
        assert svg.is_file() and svg.stat().st_size > 0
        assert csv.is_file() and "combo.total" in csv.read_text(encoding="utf-8")
        assert "已导出" in app.query_one("#status", Static).render().plain


@pytest.mark.asyncio
async def test_chart_compares_the_variants_from_the_calculate_page(
    example_workspace: Path,
) -> None:
    source = example_workspace / "entries" / "通用分段模型.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(150, 44)) as pilot:
        await pilot.pause(0.8)
        rows = list(app.query(VariantRow))
        rows[0].query_one(".variant-name", Input).value = "开启天赋"
        rows[0].query_one(".variant-scenario", Select).value = DEFAULT_SCENARIO
        rows[1].query_one(".variant-name", Input).value = "关闭天赋"
        rows[1].query_one(".variant-scenario", Select).value = "no_talent"
        app.query_one("#scan-x-select", Select).value = "aoe_pattern.targets"
        app.query_one("#scan-y-select", Select).value = "aoe_pattern.total"
        app.query_one("#scan-range", Input).value = "1:6"
        app.query_one("#scan-points", Input).value = "6"

        app.action_run_variant_scan()
        await pilot.pause(1.2)

        assert app._last_scan is not None
        assert app._last_scan["operation"] == "scan_compare"
        assert app._last_scan["rows"][2]["values"]["variant_1"]["exact"] == "390"
        assert app._last_scan["rows"][2]["values"]["variant_2"]["exact"] == "300"
        assert "使用计算页中的方案设置" in app.query_one("#chart-status", Static).render().plain

        app.query_one("#scan-plot-id", Input).value = "unsupported_multi_variant"
        app.action_create_plot_draft()
        assert not (example_workspace / "plots" / "unsupported_multi_variant.kirin").exists()
        assert "多方案比较图只能在工作台中查看" in app.query_one("#chart-status", Static).render().plain


@pytest.mark.asyncio
async def test_saved_comparison_run_replays_from_the_runs_view(example_workspace: Path) -> None:
    source = example_workspace / "entries" / "组合模型.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.8)
        app.query_one("#target-select", Select).value = "combo.total"
        rows = list(app.query(VariantRow))
        rows[0].query_one(".variant-scenario", Select).value = "baseline"
        rows[1].query_one(".variant-overrides", Input).value = "combo.crit=1/2"
        app.action_calculate()
        await pilot.pause(1.1)

        app.query_one("#run-id", Input).value = "comparison_one"
        app.action_save_run()
        await pilot.pause(1.1)

        assert (example_workspace / "runs" / "comparison_one.json").is_file()
        app._selected_run_id = "comparison_one"
        app.action_replay_run()
        await pilot.pause(1.1)
        details = app.query_one("#run-details", Static).render().plain
        assert "结果一致：是" in details
        assert "环境一致：是" in details


@pytest.mark.asyncio
async def test_diagnostics_aggregate_files_and_open_the_source_location(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    first = root / "entries" / "first.kirin"
    second = root / "entries" / "second.kirin"
    first.write_text("@kirin 1\n@entry first\n\ninputs：\n", encoding="utf-8")
    second.write_text("@kirin 1\n@entry second\n\n@unknown value\n", encoding="utf-8")
    app = KirinTUI(root, first)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.9)
        assert len(app._diagnostic_errors) == 2
        assert app.query_one("#diagnostic-list", OptionList).option_count == 2

        target_error = next(
            error for error in app._diagnostic_errors if error.location.path == str(second)
        )
        app._open_diagnostic(target_error)
        await pilot.pause(0.3)

        assert app.source_path == second.resolve()
        editor = app.query_one("#editor", TextArea)
        assert editor.cursor_location[0] == (target_error.location.line or 1) - 1


@pytest.mark.asyncio
async def test_workbench_uses_compact_layout_and_disables_motion_in_tests(
    example_workspace: Path,
) -> None:
    source = example_workspace / "entries" / "组合模型.kirin"
    app = KirinTUI(example_workspace, source)
    async with app.run_test(size=(78, 28)) as pilot:
        await pilot.pause(0.6)
        assert app.screen.has_class("narrow")
        assert app.motion_mode == "off"
        assert app.query_one("#brand", Static).size.width > 0
        assert app.query_one("#comparison-results").size.height > 0
