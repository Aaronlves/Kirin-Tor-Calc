from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import ReferenceError, SchemaError
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import evaluate, explain, scan_values
from kirin_tor.workspace import Workspace, initialize


ENTRY_SOURCE = """@kirin 1
@entry model
@template model

// Model title is an author comment, not schema data.

----
Exact model description.
This line is ordinary text: ---
\tTabs inside prose are preserved.
----

inputs:
  x: number[dimensionless] = 0.25 in 0..1

fields:
  base: dimensionless = 2
  scaled: dimensionless :=
    base * (1 + x)

constraints:
  x >= 0
  x <= 1

functions:
  multiply(n: number[dimensionless]) -> dimensionless =
    scaled * n

outputs:
  result: dimensionless = scaled
  doubled: dimensionless = multiply(2)
"""


def test_kirin_entry_scenario_and_plot_use_existing_engine(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(ENTRY_SOURCE, encoding="utf-8")
    (root / "scenarios" / "baseline.kirin").write_text(
        """@kirin 1
@scenario baseline

// Baseline

values:
  model.x = 0.5
""",
        encoding="utf-8",
    )
    (root / "plots" / "curve.kirin").write_text(
        """@kirin 1
@plot curve

// Curve

x: model.x
range: 0..1
points: 3

y:
  model.result as "Result"

scenario: baseline
title: "Preview"
x-label: "Input"
y-label: "Value"
export-svg: "results/curve.svg"
export-csv: "results/curve.csv"
""",
        encoding="utf-8",
    )

    workspace = Workspace.load(root)
    result = Engine(workspace).validate_all()
    assert result["status"] == "ok"
    assert workspace.get_entry("model").raw["description"].endswith("Tabs inside prose are preserved.")
    assert workspace.get_entry("model").name == "model"
    assert evaluate(Engine(workspace), "model.result", "baseline")["exact"] == "3"
    assert evaluate(Engine(workspace), "model.doubled", "baseline")["exact"] == "6"

    plot = workspace.get_plot("curve")
    scan = scan_values(
        Engine(workspace), plot.x, f"{plot.range_start}:{plot.range_end}", plot.points, plot.y
    )
    assert [row["values"]["model.result"]["exact"] for row in scan["rows"]] == ["2", "3", "4"]
    assert plot.curve_labels == {"model.result": "Result"}


def test_kirin_reports_source_line_and_rejects_unknown_sections(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "broken.kirin"
    path.write_text(
        """@kirin 1
@entry broken

unknown:
  value
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="unknown entry section") as caught:
        Workspace.load(root)
    assert caught.value.location.path == str(path)
    assert caught.value.location.field == "unknown"


def test_workspace_overlay_validates_without_writing(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "draft.kirin"
    workspace = Workspace.load_with_overlay(root, path, ENTRY_SOURCE.replace("@entry model", "@entry draft"))
    assert "draft" in workspace.entries
    assert not path.exists()


def test_fractional_unit_and_parameter_one_of_round_trip(tmp_path: Path) -> None:
    raw = {
        "schema_version": 1,
        "id": "semantics",
        "name": "semantics",
        "type": "entry",
        "semantics": {
            "dimensions": {"length": {}},
            "units": {"root_length": {"dimensions": {"length": "1/2"}}},
        },
        "inputs": {},
        "constraints": [],
        "fields": {},
        "functions": {
            "choose": {
                "parameters": {
                    "n": {
                        "value_type": "number",
                        "unit": "dimensionless",
                        "allowed_values": ["0", "1", "2"],
                    },
                    "enabled": {"value_type": "boolean"},
                },
                "expression": "if_else(enabled, n, 0)",
                "unit": "dimensionless",
                "label": "选择",
            }
        },
        "outputs": {},
    }
    path = tmp_path / "semantics.kirin"
    path.write_text(render_kirin_document(raw), encoding="utf-8")
    parsed, _text, _digest, _positions = load_kirin_document(path)
    assert parsed == raw


def test_workspace_marker_requires_a_known_initial_package(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    marker = root / "kirin.workspace"
    marker.write_text("@kirin-workspace 1\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="requires initial-package"):
        Workspace.load(root)

    marker.write_text("@kirin-workspace 1\ninitial-package: mystery\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="must be one of"):
        Workspace.load(root)


def test_chinese_local_aliases_and_member_labels(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "base.kirin").write_text(
        """@kirin 1
@entry base

inputs:
  amount "基础值": number[dimensionless] = 2

functions:
  double "翻倍"(value: number[dimensionless]) -> dimensionless = value * 2
""",
        encoding="utf-8",
    )
    (root / "entries" / "model.kirin").write_text(
        """@kirin 1
@entry model

aliases:
  基础 = base.amount
  加倍 = base.double

outputs:
  result "总计": dimensionless = 加倍(基础)
""",
        encoding="utf-8",
    )

    workspace = Workspace.load(root)
    engine = Engine(workspace)
    assert engine.validate_all()["status"] == "ok"
    assert workspace.get_entry("model").aliases == {"基础": "base.amount", "加倍": "base.double"}
    assert workspace.get_entry("base").inputs["amount"].label == "基础值"
    assert evaluate(engine, "model.result")["exact"] == "4"
    assert explain(engine, "model.result")["label"] == "总计"

    scan = scan_values(engine, "base.amount", "1:2", 2, ["model.result"])
    assert scan["x_display_label"] == "基础值"
    assert scan["labels"] == {"model.result": "总计"}


def test_alias_cannot_conflict_with_a_formal_member(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    path = root / "entries" / "collision.kirin"
    path.write_text(
        """@kirin 1
@entry collision

aliases:
  x = collision.result

inputs:
  x: number[dimensionless] = 1

outputs:
  result: dimensionless = x
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="conflicts with a declared member"):
        Workspace.load(root)


def test_unused_alias_target_is_still_validated(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "model.kirin").write_text(
        """@kirin 1
@entry model

aliases:
  缺失 = missing.value

outputs:
  result: dimensionless = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ReferenceError, match="missing reference"):
        Engine(Workspace.load(root)).validate_all()
