from __future__ import annotations

import json
from pathlib import Path

from kirin_tor.cli import app
from kirin_tor.engine import Engine
from kirin_tor.operations import evaluate, scan_values
from kirin_tor.workspace import Workspace, initialize

from conftest import make_cli_runner, write_kirin


runner = make_cli_runner()


def _entry(entry_id: str, **sections) -> dict:
    document = {
        "schema_version": 1,
        "id": entry_id,
        "name": entry_id,
        "type": "entry",
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {},
        "outputs": {},
    }
    document.update(sections)
    return document


def _build_capability_workspace(root: Path) -> Path:
    initialize(root)
    entries = root / "entries"

    (entries / "fixture_game_semantics.kirin").write_text(
        """@kirin 2
@entry fixture_game_semantics

dimension damage

dimension attack_power

unit damage = damage

unit attack_power = attack_power

unit damage_per_attack_power = attack_power ** (-1) * damage
""",
        encoding="utf-8",
    )

    write_kirin(
        entries / "character.kirin",
        _entry(
            "character",
            inputs={
                "attack_power": {"unit": "attack_power", "default": "3000", "min": "0"},
                "versatility": {"domain": "probability", "default": "0.10"},
            },
            fields={
                "attack_power_with_versatility": {
                    "kind": "expression",
                    "expression": "attack_power * (1 + versatility)",
                    "unit": "attack_power",
                }
            },
            outputs={
                "effective_attack_power": {
                    "expression": "attack_power_with_versatility",
                    "unit": "attack_power",
                }
            },
        ),
    )

    write_kirin(
        entries / "talent_a.kirin",
        _entry(
            "talent_a",
            fields={
                "modifier": {
                    "kind": "value",
                    "value": "1/5",
                    "unit": "dimensionless",
                }
            },
            outputs={
                "multiplier": {
                    "expression": "1 + modifier",
                    "unit": "dimensionless",
                }
            },
        ),
    )
    write_kirin(
        entries / "talent_b.kirin",
        _entry(
            "talent_b",
            fields={
                "modifier": {
                    "kind": "value",
                    "value": "1/10",
                    "unit": "dimensionless",
                }
            },
            outputs={
                "multiplier": {
                    "expression": "1 + modifier",
                    "unit": "dimensionless",
                }
            },
        ),
    )

    write_kirin(
        entries / "talent_selection.kirin",
        _entry(
            "talent_selection",
            inputs={
                "choose_talent_a": {
                    "value_type": "boolean",
                    "unit": "dimensionless",
                    "default": True,
                },
                "choose_talent_b": {
                    "value_type": "boolean",
                    "unit": "dimensionless",
                    "default": False,
                },
            },
            outputs={
                "talent_a_enabled": {
                    "expression": "choose_talent_a",
                    "value_type": "boolean",
                    "unit": "dimensionless",
                },
                "talent_b_enabled": {
                    "expression": "choose_talent_b",
                    "value_type": "boolean",
                    "unit": "dimensionless",
                },
            },
            presets={
                "alternate_talents": {
                    "label": "alternate_talents",
                    "values": {
                        "choose_talent_a": False,
                        "choose_talent_b": True,
                    },
                }
            },
        ),
    )

    write_kirin(
        entries / "skill.kirin",
        _entry(
            "skill",
            fields={
                "coefficient": {
                    "kind": "value",
                    "value": "1/2",
                    "unit": "damage_per_attack_power",
                }
            },
            outputs={
                "damage": {
                    "expression": (
                        "character.effective_attack_power * coefficient *\n"
                        "if_else(talent_selection.talent_a_enabled, talent_a.multiplier, 1) *\n"
                        "if_else(talent_selection.talent_b_enabled, talent_b.multiplier, 1)"
                    ),
                    "unit": "damage",
                }
            },
        ),
    )

    write_kirin(
        entries / "combo.kirin",
        _entry(
            "combo",
            fields={
                "first_hit": {
                    "kind": "expression",
                    "expression": "skill.damage",
                    "unit": "damage",
                },
                "attack_power_conversion": {
                    "kind": "value",
                    "value": "1/10",
                    "unit": "damage_per_attack_power",
                },
            },
            outputs={
                "total": {
                    "expression": (
                        "first_hit +\n"
                        "2 * skill.damage +\n"
                        "character.effective_attack_power * attack_power_conversion"
                    ),
                    "unit": "damage",
                }
            },
        ),
    )

    write_kirin(
        entries / "target_curve.kirin",
        _entry(
            "target_curve",
            inputs={
                "targets": {
                    "unit": "dimensionless",
                    "default": "1",
                    "min": "1",
                    "max": "10",
                }
            },
            outputs={
                "total": {
                    "expression": (
                        "piecewise(\n"
                        "  targets <= 3, combo.total * targets,\n"
                        "  targets <= 5, combo.total * (3 + (targets - 3) / 2),\n"
                        "  combo.total * (4 + sqrt(targets - 5))\n"
                        ")"
                    ),
                    "unit": "damage",
                }
            },
        ),
    )

    target_curve_path = root / "entries" / "target_curve.kirin"
    target_curve = target_curve_path.read_text(encoding="utf-8").rstrip()
    target_curve += """

chart preview:
  x = target_curve.targets
  range = 1..10
  points = 10
  y:
    - target_curve.total
  export_svg = "results/target-scaling.svg"
  export_csv = "results/target-scaling.csv"
"""
    target_curve_path.write_text(target_curve, encoding="utf-8")
    return root


def test_character_talents_selection_and_complex_composition(tmp_path: Path) -> None:
    root = _build_capability_workspace(tmp_path / "capability-workspace")
    engine = Engine(Workspace.load(root))
    checked = engine.validate_all()
    assert checked["status"] == "ok"

    character = evaluate(engine, "character.effective_attack_power")
    assert character["exact"] == "3300"

    default_skill = evaluate(Engine(Workspace.load(root)), "skill.damage")
    assert default_skill["exact"] == "1980"
    alternate_skill = evaluate(
        Engine(Workspace.load(root)),
        "skill.damage",
        preset="talent_selection.alternate_talents",
    )
    assert alternate_skill["exact"] == "1815"

    combo = evaluate(Engine(Workspace.load(root)), "combo.total")
    assert combo["exact"] == "6270"
    assert set(combo["dependency_ids"]) == {
        "character",
        "combo",
        "skill",
        "talent_a",
        "talent_b",
        "talent_selection",
    }


def test_piecewise_curve_scan_and_cli_plot(tmp_path: Path, monkeypatch) -> None:
    root = _build_capability_workspace(tmp_path / "curve-workspace")
    scan = scan_values(
        Engine(Workspace.load(root)),
        "targets",
        "1:10",
        10,
        ["target_curve.total"],
    )
    values = [row["values"]["target_curve.total"]["exact"] for row in scan["rows"]]
    assert values[:6] == ["6270", "12540", "18810", "21945", "25080", "31350"]
    assert values[-1] == "6270*sqrt(5) + 25080"

    monkeypatch.chdir(root)
    checked = runner.invoke(app, ["check", "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["status"] == "ok"

    plotted = runner.invoke(app, ["plot", "--config", "target_curve", "--json"])
    assert plotted.exit_code == 0, plotted.output
    payload = json.loads(plotted.stdout)
    assert Path(payload["out"]).read_text(encoding="utf-8").lstrip().startswith("<?xml")
    csv_lines = Path(payload["data_out"]).read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 11
