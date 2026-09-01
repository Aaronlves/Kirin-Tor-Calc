from __future__ import annotations

import csv
import shutil
from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.operations import evaluate, scan_grid, scan_values, solve_system
from kirin_tor.plotting import render_plot, write_scan_csv
from kirin_tor.workspace import Workspace


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = REPOSITORY_ROOT / "examples" / "酒仙系数表复现"


def _number(result: dict) -> float:
    return float(result["approximate"])


def _assert_value(engine: Engine, target: str, expected: float) -> None:
    assert _number(evaluate(engine, target)) == pytest.approx(expected, rel=1e-10, abs=1e-10)


def test_damage_and_defense_tables_match_workbook_cached_values() -> None:
    workspace = Workspace.load(EXAMPLE_ROOT)
    engine = Engine(workspace)
    assert engine.validate_all()["status"] == "ok"

    damage_values = {
        "damage_table.base_attack_power": 3475.3632608695652,
        "damage_table.haste": 0.08931818181818182,
        "damage_table.mastery": 0.2623913043478261,
        "damage_table.versatility": 0.13222222222222221,
        "damage_table.tiger_palm_coefficient": 297.06663168,
        "damage_table.tiger_palm_damage": 11689.2259163,
        "damage_table.blackout_kick_coefficient": 281.483498391,
        "damage_table.keg_smash_coefficient": 271.881792,
        "damage_table.harmonic_surge_damage": 8988.60865904,
    }
    for target, expected in damage_values.items():
        _assert_value(engine, target, expected)

    defense_values = {
        "defense_table.stagger_absorption": 0.750875871785,
        "defense_table.base_dodge": 0.288135603018,
        "defense_table.ramping_dodge": 0.2414,
        "defense_table.crit_rate": 0.337173913044,
        "defense_table.base_physical_reduction": 0.774325372365,
        "defense_table.base_magical_reduction": 0.488642382638,
        "defense_table.expected_physical_reduction": 0.901426755249,
        "defense_table.vivify_coefficient": 750.0939264,
        "defense_table.vivify_healing": 28334.7093613,
        "defense_table.celestial_brew_absorb": 143398.42853,
        "defense_table.mantra_of_tenacity_healing": 188986.379121,
    }
    for target, expected in defense_values.items():
        _assert_value(engine, target, expected)


def test_dodge_expectation_is_dynamic_and_feeds_the_defense_table() -> None:
    workspace = Workspace.load(EXAMPLE_ROOT)
    baseline = evaluate(Engine(workspace), "dodge_expectation.expected_dodge")
    no_severity = evaluate(
        Engine(workspace),
        "dodge_expectation.expected_dodge",
        overrides={"dodge_expectation.stagger_severity_bonus": "0"},
    )
    more_mastery = evaluate(
        Engine(workspace),
        "dodge_expectation.expected_dodge",
        overrides={"damage_table.mastery_rating": "1000"},
    )
    assert float(baseline["approximate"]) == pytest.approx(0.513206348075, rel=1e-10)
    assert baseline["formatted"] == "51.32%"
    assert float(no_severity["approximate"]) == pytest.approx(0.470923646427, rel=1e-10)
    assert float(more_mastery["approximate"]) == pytest.approx(0.528299367690, rel=1e-10)

    less_dodge_reduction = evaluate(
        Engine(workspace),
        "defense_table.expected_physical_reduction",
        overrides={"dodge_expectation.stagger_severity_bonus": "0"},
    )
    baseline_reduction = evaluate(
        Engine(workspace), "defense_table.expected_physical_reduction"
    )
    assert float(less_dodge_reduction["approximate"]) < float(
        baseline_reduction["approximate"]
    )


def test_brewmaster_sources_groups_and_presets_are_player_visible_metadata() -> None:
    workspace = Workspace.load(EXAMPLE_ROOT)
    assert workspace.get_preset("builds.current").label == "当前表格"
    assert workspace.get_preset("single_target").qualified_id == "builds.single_target"
    assert workspace.entries["damage_table"].groups["predicted_damage"].label == "预测伤害"
    assert workspace.entries["defense_table"].groups["mitigation"].label == "减伤与躲闪"
    assert workspace.entries["aoe_table"].groups["dpc"].label == "DPC"
    for entry_id in ("damage_table", "defense_table", "aoe_table", "dodge_expectation"):
        source = workspace.entries[entry_id].sources[0]
        assert source["verified_at"] == "2026-09-01"
        assert source["game_version"] == "12.0.1.65617"


def test_real_brewmaster_model_supports_linked_solve_and_two_stat_grid() -> None:
    workspace = Workspace.load(EXAMPLE_ROOT)
    solved = solve_system(
        Engine(workspace),
        [
            ("damage_table.base_attack_power", "15986671/4600 attack_power"),
            ("damage_table.versatility", "119/900"),
        ],
        ["damage_table.mastery_rating", "damage_table.versatility_rating"],
    )
    values = solved["solutions"][0]["values"]
    assert values["damage_table.mastery_rating"]["exact"] == "609"
    assert values["damage_table.versatility_rating"]["exact"] == "714"

    grid = scan_grid(
        Engine(workspace),
        "damage_table.mastery_rating",
        "500:700",
        3,
        "damage_table.versatility_rating",
        "600:800",
        3,
        "damage_table.tiger_palm_damage",
    )
    assert grid["valid_points"] == 9
    assert grid["rows"][0]["value"]["formatted"] == "11,256"
    assert grid["rows"][-1]["value"]["formatted"] == "12,039"


def test_aoe_table_matches_workbook_at_representative_target_counts() -> None:
    targets = [
        "aoe_table.tiger_palm_total",
        "aoe_table.blackout_kick_total",
        "aoe_table.niuzao_aoe_total",
        "aoe_table.breath_of_fire_direct_total",
        "aoe_table.empty_keg_total",
        "aoe_table.blackout_kick_dpc",
        "aoe_table.tiger_palm_dpc",
        "aoe_table.burst_blackout_kick_dpc",
        "aoe_table.burst_keg_smash_dpc",
        "aoe_table.counter_tiger_palm_dpe",
    ]
    scan = scan_values(
        Engine(Workspace.load(EXAMPLE_ROOT)),
        "aoe_table.targets",
        "1:20",
        20,
        targets,
    )
    assert len(scan["rows"]) == 20
    assert all(
        value["error"] is None
        for row in scan["rows"]
        for value in row["values"].values()
    )

    expected_rows = {
        1: [397.229750318, 376.392391, 510.250160974, 578.514921739,
            765.375241461, 470.490488751, 496.537187898, 980.740649724,
            1136.17799627, 39.7229750318],
        3: [397.229750318, 1129.177173, 1530.75048292, 1246.52641333,
            2259.38771279, 1411.47146625, 695.152063057, 2942.22194917,
            2499.65088957, 55.6121650445],
        8: [397.229750318, 1129.177173, 4082.00128779, 2010.26630637,
            2259.38771279, 1728.59495532, 1025.30513301, 5810.59624311,
            4670.94746078, 82.0244106409],
        20: [397.229750318, 1129.177173, 6641.75036453, 3036.35243465,
             2259.38771279, 2084.27286516, 1390.30412611, 8726.02322969,
             7044.58524131, 111.224330089],
    }
    for target_count, expected_values in expected_rows.items():
        row = scan["rows"][target_count - 1]
        assert float(row["x_approximate"]) == target_count
        actual_values = [float(row["values"][target]["approximate"]) for target in targets]
        assert actual_values == pytest.approx(expected_values, rel=1e-9, abs=1e-9)


def test_aoe_plot_performs_a_real_scan_and_export(tmp_path: Path) -> None:
    copied_root = tmp_path / "酒仙系数表复现"
    shutil.copytree(EXAMPLE_ROOT, copied_root, ignore=shutil.ignore_patterns("results"))
    workspace = Workspace.load(copied_root)
    plot = workspace.get_chart("aoe_table")
    scan = scan_values(
        Engine(workspace),
        plot.x,
        f"{plot.range_start}:{plot.range_end}",
        plot.points,
        plot.y,
        plot.preset,
    )

    csv_path = write_scan_csv(scan, copied_root / "results" / "aoe-dpc.csv")
    svg_path = render_plot(
        scan,
        copied_root / "results" / "aoe-dpc.svg",
        title=plot.title,
        x_label=plot.x_label,
        y_label=plot.y_label,
        curve_labels=plot.curve_labels,
    )

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 20
    assert rows[0]["x"] == "1"
    assert rows[-1]["x"] == "20"
    assert svg_path.read_text(encoding="utf-8").lstrip().startswith("<?xml")
