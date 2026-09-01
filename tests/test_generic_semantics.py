from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.application import record_operation
from kirin_tor.engine import Engine
from kirin_tor.errors import DomainError, ParameterError, SchemaError, UnitError, ValidationErrors
from kirin_tor.operations import differentiate, evaluate, scan_values, solve_equation
from kirin_tor.records import load_run, replay
from kirin_tor.workspace import Workspace, initialize


def test_scaled_units_convert_exactly_across_eval_scan_and_solve(tmp_path: Path) -> None:
    root = initialize(tmp_path / "scaled-units")
    (root / "entries" / "time_math.kirin").write_text(
        """@kirin 1
@entry time_math

dimensions:
  time

units:
  second = time
  millisecond = 1/1000 * time

inputs:
  latency: number[millisecond] = 500 in 0..1000 integer

fields:
  base: second = 1

tables:
  latency_bonus "延迟换算": millisecond -> millisecond:
    0 = 0
    1000 = 500

outputs:
  total_seconds: second = base + latency
  total_milliseconds: millisecond = base + latency
  literal_conversion: second = 500 * millisecond
  interpolated_milliseconds: millisecond = interpolate(latency_bonus, latency)
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    engine = Engine(workspace)
    assert engine.validate_all()["status"] == "ok"
    assert evaluate(engine, "time_math.total_seconds")["exact"] == "3/2"
    assert evaluate(engine, "time_math.total_milliseconds")["exact"] == "1500"
    assert evaluate(engine, "time_math.literal_conversion")["exact"] == "1/2"
    assert evaluate(engine, "time_math.interpolated_milliseconds")["exact"] == "250"

    scan = scan_values(
        Engine(workspace),
        "time_math.latency",
        "0:1000",
        3,
        ["time_math.total_seconds"],
    )
    assert [row["x"] for row in scan["rows"]] == ["0", "500", "1000"]
    assert [row["values"]["time_math.total_seconds"]["exact"] for row in scan["rows"]] == [
        "1",
        "3/2",
        "2",
    ]

    solved = solve_equation(
        Engine(workspace),
        "time_math.total_seconds",
        "time_math.latency",
        "1.75 second",
        "0:1000",
    )
    assert solved["solutions"][0]["exact"] == "750"

    request = {
        "target": "time_math.total_seconds",
        "preset": None,
        "overrides": {"time_math.latency": "750"},
        "precision": 30,
        "display_digits": 12,
        "timeout_seconds": 10.0,
    }
    record_operation(
        workspace,
        "scaled_eval",
        "eval",
        request,
        lambda: evaluate(
            Engine(workspace),
            "time_math.total_seconds",
            overrides={"time_math.latency": "750"},
        ),
    )
    assert load_run(root, "scaled_eval")["request"]["effective_parameters"] == {
        "time_math.latency": "750"
    }
    assert replay(root, "scaled_eval")["matches_recorded_result"] is True

from conftest import minimal_entry, write_kirin


def _semantic_entry(entry_id: str = "semantics") -> dict:
    return {
        "schema_version": 1,
        "id": entry_id,
        "name": entry_id,
        "type": "entry",
        "semantics": {
            "dimensions": {"damage": {}, "time": {}, "attack_power": {}},
            "units": {
                "damage": {"dimensions": {"damage": 1}},
                "time": {"dimensions": {"time": 1}},
                "attack_power": {"dimensions": {"attack_power": 1}},
                "damage_per_attack_power": {
                    "dimensions": {"damage": 1, "attack_power": -1}
                },
            },
            "domains": {
                "level_choice": {
                    "value_type": "number",
                    "unit": "dimensionless",
                    "integer": True,
                    "allowed_values": [0, 1, 2],
                }
            },
        },
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {},
        "outputs": {},
    }


def test_inputs_are_entry_qualified_and_short_names_must_be_unambiguous(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    entry_a = minimal_entry("a", "x", {"x": {"default": "1"}})
    entry_a["constraints"] = ["x <= 5"]
    write_kirin(root / "entries" / "a.kirin", entry_a)
    write_kirin(root / "entries" / "b.kirin", minimal_entry("b", "x", {"x": {"default": "2"}}))
    combo = minimal_entry("combo", "a.x + b.x")
    combo["presets"] = {
        "values": {
            "label": "values",
            "values": {"a.x": "3", "b.x": "4"},
        }
    }
    write_kirin(root / "entries" / "combo.kirin", combo)

    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "a.result")["exact"] == "1"
    assert evaluate(Engine(workspace), "b.result")["exact"] == "2"
    assert evaluate(Engine(workspace), "combo.result", "combo.values")["exact"] == "7"
    with pytest.raises(ParameterError, match="ambiguous"):
        evaluate(Engine(workspace), "combo.result", overrides={"x": "9"})
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(Engine(workspace), "combo.result", overrides={"a.x": "6"})


def test_user_defined_dimensions_domains_and_piecewise_values(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_kirin(root / "entries" / "semantics.kirin", _semantic_entry())
    entry = minimal_entry(
        "choice",
        "piecewise(level == 0, 0, level == 1, 10, level == 2, 20, 0)",
        {"level": {"domain": "level_choice", "default": "2"}},
    )
    write_kirin(root / "entries" / "choice.kirin", entry)
    assert evaluate(Engine(Workspace.load(root)), "choice.result")["exact"] == "20"
    with pytest.raises(ParameterError, match="not one of"):
        evaluate(Engine(Workspace.load(root)), "choice.result", overrides={"choice.level": "3"})

    duplicate = _semantic_entry("duplicate_semantics")
    duplicate["semantics"]["dimensions"]["damage"] = {"name": "Different display label"}
    write_kirin(root / "entries" / "duplicate.kirin", duplicate)
    assert Workspace.load(root).units.parse_unit("damage").render() == "damage"


def test_conflicting_semantics_report_both_sources(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_kirin(root / "entries" / "first.kirin", _semantic_entry("first"))
    second = _semantic_entry("second")
    second["semantics"]["units"]["damage"] = {"dimensions": {"time": 1}}
    write_kirin(root / "entries" / "second.kirin", second)
    with pytest.raises(SchemaError, match="conflicts with its declaration") as caught:
        Workspace.load(root)
    assert "first.kirin" in str(caught.value)
    assert "second.kirin" in str(caught.value)


def test_check_rejects_unknown_keys_and_evaluates_default_constraints(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "typo.kirin").write_text(
        "@kirin 1\n@entry typo\n\ninputs:\n  x: number[dimensionless] defualt 1\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationErrors) as caught:
        Workspace.load_for_check(root)
    assert "input must use" in str(caught.value)
    assert ":" in str(caught.value.errors[0].location.render())

    (root / "entries" / "typo.kirin").unlink()
    constrained = minimal_entry("constrained", "x", {"x": {"default": "1"}})
    constrained["constraints"] = ["x > 2"]
    write_kirin(root / "entries" / "constrained.kirin", constrained)
    with pytest.raises(DomainError, match="domain condition failed"):
        Engine(Workspace.load(root)).validate_all()


def test_mixed_curve_units_are_explicit_warning_not_error(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_kirin(root / "entries" / "semantics.kirin", _semantic_entry())
    write_kirin(root / "entries" / "axis.kirin", minimal_entry("axis", "x", {"x": {}}))
    damage = minimal_entry("damage_curve", "base * (1 + axis.x)", unit="damage")
    damage["fields"] = {"base": {"kind": "value", "value": "10", "unit": "damage"}}
    time = minimal_entry("time_curve", "base * (1 + axis.x)", unit="time")
    time["fields"] = {"base": {"kind": "value", "value": "2", "unit": "time"}}
    write_kirin(root / "entries" / "damage.kirin", damage)
    write_kirin(root / "entries" / "time.kirin", time)
    result = scan_values(
        Engine(Workspace.load(root)),
        "axis.x",
        "0:1",
        2,
        ["damage_curve.result", "time_curve.result"],
    )
    assert result["units"] == {"damage_curve.result": "damage", "time_curve.result": "time"}
    assert result["warnings"] == [
        "curves use different units; no implicit conversion was performed"
    ]


def test_derivative_keeps_other_declared_variables(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_kirin(
        root / "entries" / "formula.kirin",
        minimal_entry("formula", "x * y", {"x": {}, "y": {}}),
    )
    result = differentiate(Engine(Workspace.load(root)), "formula.result", "formula.x")
    assert result["expression"] == "formula.y"
    assert result["free_variables"] == ["formula.y"]


def test_unitful_scan_range_uses_declared_user_unit(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_kirin(root / "entries" / "semantics.kirin", _semantic_entry())
    write_kirin(
        root / "entries" / "timer.kirin",
        minimal_entry("timer", "elapsed", {"elapsed": {"unit": "time"}}, unit="time"),
    )
    result = scan_values(
        Engine(Workspace.load(root)), "timer.elapsed", "0 time:1 time", 2, ["timer.result"]
    )
    assert [row["x"] for row in result["rows"]] == ["0", "1"]


def test_exact_zero_is_unit_polymorphic_but_nonzero_is_not(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_kirin(root / "entries" / "semantics.kirin", _semantic_entry())
    entry = minimal_entry("zero_case", "if_else(enabled, base, 0)", unit="damage")
    entry["inputs"] = {"enabled": {"value_type": "boolean", "default": False}}
    entry["fields"] = {"base": {"kind": "value", "value": "10", "unit": "damage"}}
    entry["constraints"] = ["base >= 0"]
    write_kirin(root / "entries" / "zero.kirin", entry)
    assert evaluate(Engine(Workspace.load(root)), "zero_case.result")["exact"] == "0"

    entry["outputs"]["result"]["expression"] = "base + 1"
    write_kirin(root / "entries" / "zero.kirin", entry)
    with pytest.raises(UnitError, match="incompatible units"):
        Engine(Workspace.load(root)).validate_all()
