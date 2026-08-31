from __future__ import annotations

import json
from pathlib import Path

from kirin_tor.cli import app
from kirin_tor.engine import Engine
from kirin_tor.operations import evaluate, scan_values
from kirin_tor.workspace import Workspace, initialize

from conftest import make_cli_runner, write_yaml


runner = make_cli_runner()


def _entry(entry_id: str, **sections) -> dict:
    document = {
        "schema_version": 1,
        "id": entry_id,
        "name": entry_id,
        "type": "entry",
        "template": "data",
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {},
        "outputs": {},
    }
    document.update(sections)
    return document


def _build_capability_workspace(root: Path) -> Path:
    initialize(root, "wow")
    entries = root / "entries"

    write_yaml(
        entries / "character.yaml",
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

    write_yaml(
        entries / "talent_a.yaml",
        _entry(
            "talent_a",
            template="skill",
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
    write_yaml(
        entries / "talent_b.yaml",
        _entry(
            "talent_b",
            template="skill",
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

    write_yaml(
        entries / "talent_selection.yaml",
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
                    "unit": "dimensionless",
                },
                "talent_b_enabled": {
                    "expression": "choose_talent_b",
                    "unit": "dimensionless",
                },
            },
        ),
    )

    write_yaml(
        entries / "skill.yaml",
        _entry(
            "skill",
            template="skill",
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

    write_yaml(
        entries / "combo.yaml",
        _entry(
            "combo",
            template="model",
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

    write_yaml(
        entries / "target_curve.yaml",
        _entry(
            "target_curve",
            template="model",
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

    write_yaml(
        root / "scenarios" / "alternate_talents.yaml",
        {
            "schema_version": 1,
            "id": "alternate_talents",
            "name": "alternate_talents",
            "type": "scenario",
            "values": {"choose_talent_a": False, "choose_talent_b": True},
        },
    )
    write_yaml(
        root / "plots" / "target_scaling.yaml",
        {
            "schema_version": 1,
            "id": "target_scaling",
            "name": "target_scaling",
            "type": "plot",
            "x": "targets",
            "range": ["1", "10"],
            "points": 10,
            "y": ["target_curve.total"],
            "out": "results/target-scaling.svg",
            "data_out": "results/target-scaling.csv",
        },
    )
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
        Engine(Workspace.load(root)), "skill.damage", scenario="alternate_talents"
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

    plotted = runner.invoke(app, ["plot", "--config", "target_scaling", "--json"])
    assert plotted.exit_code == 0, plotted.output
    payload = json.loads(plotted.stdout)
    assert Path(payload["out"]).read_text(encoding="utf-8").lstrip().startswith("<?xml")
    csv_lines = Path(payload["data_out"]).read_text(encoding="utf-8").splitlines()
    assert len(csv_lines) == 11
