from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import DomainError, ParameterError, SchemaError, UnitError, ValidationErrors
from kirin_tor.operations import differentiate, evaluate, scan_values
from kirin_tor.workspace import Workspace, initialize

from conftest import minimal_entry, write_yaml


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
    write_yaml(root / "entries" / "a.yaml", entry_a)
    write_yaml(root / "entries" / "b.yaml", minimal_entry("b", "x", {"x": {"default": "2"}}))
    write_yaml(root / "entries" / "combo.yaml", minimal_entry("combo", "a.x + b.x"))
    write_yaml(
        root / "scenarios" / "values.yaml",
        {
            "schema_version": 1,
            "id": "values",
            "name": "values",
            "type": "scenario",
            "values": {"a.x": "3", "b.x": "4"},
        },
    )

    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "a.result")["exact"] == "1"
    assert evaluate(Engine(workspace), "b.result")["exact"] == "2"
    assert evaluate(Engine(workspace), "combo.result", "values")["exact"] == "7"
    with pytest.raises(ParameterError, match="ambiguous"):
        evaluate(Engine(workspace), "combo.result", overrides={"x": "9"})
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(Engine(workspace), "combo.result", overrides={"a.x": "6"})


def test_user_defined_dimensions_domains_and_piecewise_values(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_yaml(root / "entries" / "semantics.yaml", _semantic_entry())
    entry = minimal_entry(
        "choice",
        "piecewise(level == 0, 0, level == 1, 10, level == 2, 20, 0)",
        {"level": {"domain": "level_choice", "default": "2"}},
    )
    write_yaml(root / "entries" / "choice.yaml", entry)
    assert evaluate(Engine(Workspace.load(root)), "choice.result")["exact"] == "20"
    with pytest.raises(ParameterError, match="not one of"):
        evaluate(Engine(Workspace.load(root)), "choice.result", overrides={"choice.level": "3"})

    duplicate = _semantic_entry("duplicate_semantics")
    duplicate["semantics"]["dimensions"]["damage"] = {"name": "Different display label"}
    write_yaml(root / "entries" / "duplicate.yaml", duplicate)
    assert Workspace.load(root).units.parse_unit("damage").render() == "damage"


def test_conflicting_semantics_report_both_sources(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_yaml(root / "entries" / "first.yaml", _semantic_entry("first"))
    second = _semantic_entry("second")
    second["semantics"]["units"]["damage"] = {"dimensions": {"time": 1}}
    write_yaml(root / "entries" / "second.yaml", second)
    with pytest.raises(SchemaError, match="conflicts with its declaration") as caught:
        Workspace.load(root)
    assert "first.yaml" in str(caught.value)
    assert "second.yaml" in str(caught.value)


def test_check_rejects_unknown_keys_and_evaluates_default_constraints(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    typo = minimal_entry("typo", "x", {"x": {"defualt": "1"}})
    write_yaml(root / "entries" / "typo.yaml", typo)
    with pytest.raises(ValidationErrors) as caught:
        Workspace.load_for_check(root)
    assert "unknown input key" in str(caught.value)
    assert ":" in str(caught.value.errors[0].location.render())

    (root / "entries" / "typo.yaml").unlink()
    constrained = minimal_entry("constrained", "x", {"x": {"default": "1"}})
    constrained["constraints"] = ["x > 2"]
    write_yaml(root / "entries" / "constrained.yaml", constrained)
    with pytest.raises(DomainError, match="domain condition failed"):
        Engine(Workspace.load(root)).validate_all()


def test_mixed_curve_units_are_explicit_warning_not_error(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_yaml(root / "entries" / "semantics.yaml", _semantic_entry())
    write_yaml(root / "entries" / "axis.yaml", minimal_entry("axis", "x", {"x": {}}))
    damage = minimal_entry("damage_curve", "base * (1 + axis.x)", unit="damage")
    damage["fields"] = {"base": {"kind": "value", "value": "10", "unit": "damage"}}
    time = minimal_entry("time_curve", "base * (1 + axis.x)", unit="time")
    time["fields"] = {"base": {"kind": "value", "value": "2", "unit": "time"}}
    write_yaml(root / "entries" / "damage.yaml", damage)
    write_yaml(root / "entries" / "time.yaml", time)
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
    write_yaml(
        root / "entries" / "formula.yaml",
        minimal_entry("formula", "x * y", {"x": {}, "y": {}}),
    )
    result = differentiate(Engine(Workspace.load(root)), "formula.result", "formula.x")
    assert result["expression"] == "formula.y"
    assert result["free_variables"] == ["formula.y"]


def test_unitful_scan_range_uses_declared_user_unit(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_yaml(root / "entries" / "semantics.yaml", _semantic_entry())
    write_yaml(
        root / "entries" / "timer.yaml",
        minimal_entry("timer", "elapsed", {"elapsed": {"unit": "time"}}, unit="time"),
    )
    result = scan_values(
        Engine(Workspace.load(root)), "timer.elapsed", "0 time:1 time", 2, ["timer.result"]
    )
    assert [row["x"] for row in result["rows"]] == ["0", "1"]


def test_exact_zero_is_unit_polymorphic_but_nonzero_is_not(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    write_yaml(root / "entries" / "semantics.yaml", _semantic_entry())
    entry = minimal_entry("zero_case", "if_else(enabled, base, 0)", unit="damage")
    entry["inputs"] = {"enabled": {"value_type": "boolean", "default": False}}
    entry["fields"] = {"base": {"kind": "value", "value": "10", "unit": "damage"}}
    entry["constraints"] = ["base >= 0"]
    write_yaml(root / "entries" / "zero.yaml", entry)
    assert evaluate(Engine(Workspace.load(root)), "zero_case.result")["exact"] == "0"

    entry["outputs"]["result"]["expression"] = "base + 1"
    write_yaml(root / "entries" / "zero.yaml", entry)
    with pytest.raises(UnitError, match="incompatible units"):
        Engine(Workspace.load(root)).validate_all()
