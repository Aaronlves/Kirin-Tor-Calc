from __future__ import annotations

import csv
from pathlib import Path

import pytest
import sympy as sp

from kirin_tor.engine import Engine
from kirin_tor.errors import ParameterError
from kirin_tor.operations import differentiate, evaluate, scan_values, solve_equation, transform
from kirin_tor.plotting import render_plot, write_scan_csv
from kirin_tor.records import replay, save_run
from kirin_tor.workspace import Workspace

from conftest import load_kirin, write_kirin


def test_required_math_acceptance(example_workspace: Path) -> None:
    engine = Engine(Workspace.load(example_workspace))

    numeric = evaluate(engine, "combo.total", scenario="baseline")
    assert numeric["exact"] == "2750"
    assert numeric["unit"] == "damage"

    symbolic = transform(engine, "simplify", "combo.total", scenario="baseline", keep={"crit"})
    prepared = engine.prepare("combo.total", scenario_id="baseline", keep={"crit"})
    crit = engine.input_symbol("combo.crit", prepared.value.inputs["combo.crit"])
    assert sp.simplify(prepared.expr - 2200 * (1 + crit)) == 0

    factored = transform(engine, "factor", "combo.total", keep={"crit"})
    assert factored["expression"] == "2200*(combo.crit + 1)"

    derivative = differentiate(engine, "combo.total", "crit")
    assert derivative["expression"] == "2200"
    assert derivative["unit"] == "damage"

    solved = solve_equation(engine, "combo.total", "crit", "3000 damage", "0:1")
    assert solved["solution_kind"] == "exact"
    assert sp.Rational(solved["solutions"][0]["exact"]) == sp.Rational(4, 11)

    scan = scan_values(engine, "crit", "0:0.6", 61, ["combo.total"], "baseline")
    assert scan["rows"][0]["values"]["combo.total"]["exact"] == "2200"
    assert scan["rows"][-1]["values"]["combo.total"]["exact"] == "3520"
    direct = evaluate(engine, "combo.total", overrides={"crit": scan["rows"][25]["x"]})
    assert direct["exact"] == scan["rows"][25]["values"]["combo.total"]["exact"]

    decimal = evaluate(engine, "0.1 + 0.2")
    assert sp.Rational(decimal["exact"]) == sp.Rational(3, 10)


def test_unified_entry_supports_multiline_boolean_constraints_and_piecewise(
    example_workspace: Path,
) -> None:
    engine = Engine(Workspace.load(example_workspace))
    enabled = evaluate(engine, "aoe_pattern.total")
    prepared = engine.prepare("aoe_pattern.total", require_numeric=True)
    assert sp.simplify(prepared.expr - 130 * sp.sqrt(30)) == 0
    assert enabled["unit"] == "damage"

    disabled = evaluate(
        Engine(Workspace.load(example_workspace)), "aoe_pattern.total", "no_talent"
    )
    assert disabled["exact"] == "400"

    with pytest.raises(ParameterError, match="below minimum"):
        evaluate(
            Engine(Workspace.load(example_workspace)),
            "aoe_pattern.total",
            overrides={"targets": "0", "talent_enabled": "true"},
        )

    branch = evaluate(
        Engine(Workspace.load(example_workspace)),
        "piecewise(1 < 0, 10, 1 == 1, 20, 30)",
    )
    assert branch["exact"] == "20"


def test_display_name_and_file_move_do_not_break_stable_reference(example_workspace: Path) -> None:
    old_path = example_workspace / "entries" / "技能甲.kirin"
    content = load_kirin(old_path)
    content["name"] = "完全不同的中文显示名"
    moved = example_workspace / "entries" / "重新整理" / "任意文件名.kirin"
    write_kirin(moved, content)
    old_path.unlink()

    result = evaluate(Engine(Workspace.load(example_workspace)), "combo.total", scenario="baseline")
    assert result["exact"] == "2750"


def test_plot_and_csv_use_scan_data(example_workspace: Path) -> None:
    scan = scan_values(
        Engine(Workspace.load(example_workspace)), "crit", "0:0.6", 7, ["combo.total"], "baseline"
    )
    csv_path = write_scan_csv(scan, example_workspace / "results" / "数据.csv")
    svg_path = render_plot(scan, example_workspace / "results" / "曲线.svg")
    png_path = render_plot(scan, example_workspace / "results" / "曲线.png")
    assert svg_path.read_text(encoding="utf-8").lstrip().startswith("<?xml")
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["combo.total"] == scan["rows"][0]["values"]["combo.total"]["exact"]
    assert rows[-1]["combo.total"] == scan["rows"][-1]["values"]["combo.total"]["exact"]


def test_saved_run_replays_embedded_old_definitions(example_workspace: Path) -> None:
    workspace = Workspace.load(example_workspace)
    result = evaluate(Engine(workspace), "combo.total", scenario="baseline")
    request = {
        "target": "combo.total",
        "precision": 30,
        "display_digits": 12,
        "timeout_seconds": 10.0,
        "effective_parameters": result["parameters"],
    }
    save_run(workspace, "before_change", "eval", request, result, result["dependency_ids"])

    skill_path = example_workspace / "entries" / "技能甲.kirin"
    skill = load_kirin(skill_path)
    skill["fields"]["base_damage"]["value"] = "1100"
    write_kirin(skill_path, skill)
    current = evaluate(Engine(Workspace.load(example_workspace)), "combo.total", scenario="baseline")
    assert current["exact"] == "2875"

    # Replay discovers only the marker and record; even an invalid current source file is ignored.
    skill_path.write_text("this is no longer valid Kirin source", encoding="utf-8")
    replayed = replay(example_workspace, "before_change")
    assert replayed["used_embedded_definitions"] is True
    assert replayed["matches_recorded_result"] is True
    assert replayed["replayed_result"]["exact"] == "2750"
