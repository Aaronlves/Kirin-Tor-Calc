from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.errors import ParameterError
from kirin_tor.workbench import Workbench
from kirin_tor.workspace import initialize


def _workspace(tmp_path: Path) -> Path:
    root = initialize(tmp_path / "workbench")
    (root / "entries" / "build_math.kirin").write_text(
        """@kirin 1
@entry build_math

// Build math

inputs:
  power "主属性": number[dimensionless] = 2 in 0..10
  speed "急速": number[dimensionless] = 1 in 0..10

outputs:
  total "总收益": dimensionless = 2 * power + speed
  balance "属性差": dimensionless = power - speed

x: build_math.power
range: 1..3
points: 3

y:
  build_math.total
export-svg: "results/build.svg"
""",
        encoding="utf-8",
    )
    return root


def test_workbench_exposes_every_cli_calculation_family(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    workbench = Workbench(root)

    assert workbench.execute("version")["version"]
    assert workbench.execute("list")["documents"][0]["path"] == "entries/build_math.kirin"
    assert "@entry build_math" in workbench.execute(
        "show", {"document": "entries/build_math.kirin"}
    )["text"]
    assert workbench.execute("check")["status"] == "ok"
    assert workbench.execute("explain", {"target": "build_math.total"})["target"] == "build_math.total"
    graph = workbench.execute("relationship_graph")
    assert {node["id"] for node in graph["nodes"]} >= {
        "build_math.power", "build_math.speed", "build_math.total"
    }
    assert {edge["id"] for edge in graph["edges"]} >= {
        "build_math.power->build_math.total",
        "build_math.speed->build_math.total",
    }
    plot_preview = workbench.execute("preview_plot", {"config": "build_math"})
    assert plot_preview["operation"] == "preview_plot"
    assert plot_preview["valid_points"] == {"build_math.total": 3}
    assert not (root / "results" / "build.svg").exists()

    evaluated = workbench.execute(
        "eval", {"target": "build_math.total", "save_run": "web_eval"}
    )
    assert evaluated["exact"] == "5"
    compared = workbench.execute(
        "compare",
        {
            "target": "build_math.total",
            "variants": [
                {"name": "默认"},
                {"name": "高主属性", "overrides": {"build_math.power": "4"}},
            ],
        },
    )
    assert compared["variants"][1]["result"]["exact"] == "9"
    comparison_chart = workbench.execute(
        "scan_compare",
        {
            "x": "build_math.power",
            "range": "1:3",
            "points": 3,
            "target": "build_math.total",
            "variants": [
                {"name": "默认"},
                {"name": "高速", "overrides": {"build_math.speed": "2"}},
            ],
            "save_run": "web_comparison_chart",
        },
    )
    assert comparison_chart["operation"] == "scan_compare"
    assert comparison_chart["labels"] == {
        "variant_1": "默认",
        "variant_2": "高速",
    }

    for operation in ("simplify", "expand", "factor"):
        assert workbench.execute(operation, {"target": "build_math.total"})["operation"] == operation
    derivative = workbench.execute(
        "diff", {"target": "build_math.total", "variable": "build_math.power"}
    )
    assert derivative["expression"] == "2"
    solved = workbench.execute(
        "solve",
        {
            "target": "build_math.total",
            "variable": "build_math.power",
            "equals": "9",
            "range": "0:10",
        },
    )
    assert solved["solutions"][0]["exact"] == "4"
    system = workbench.execute(
        "solve_system",
        {
            "equations": "build_math.total=9;build_math.balance=1",
            "variables": "build_math.power,build_math.speed",
        },
    )
    assert system["solution_kind"] == "exact"

    scan = workbench.execute(
        "scan",
        {
            "x": "build_math.power",
            "range": "1:3",
            "points": 3,
            "targets": "build_math.total,build_math.balance",
        },
    )
    assert scan["valid_points"] == {
        "build_math.total": 3,
        "build_math.balance": 3,
    }
    outside = tmp_path / "outside.csv"
    outside_request = {
        "x": "build_math.power",
        "range": "1:2",
        "points": 2,
        "targets": "build_math.total",
        "out": str(outside),
    }
    with pytest.raises(ParameterError, match="leaves the workspace"):
        workbench.execute("scan", outside_request)
    workbench.execute(
        "scan",
        {**outside_request, "allow_outside_workspace": True},
    )
    assert outside.is_file()
    grid = workbench.execute(
        "grid",
        {
            "x": "build_math.power",
            "x_range": "1:3",
            "x_points": 3,
            "y": "build_math.speed",
            "y_range": "1:2",
            "y_points": 2,
            "target": "build_math.total",
        },
    )
    assert grid["valid_points"] == 6
    plotted = workbench.execute(
        "plot",
        {
            "x": "build_math.power",
            "range": "1:3",
            "points": 3,
            "targets": "build_math.total,build_math.balance",
            "out": "results/web.svg",
            "data_out": "results/web.csv",
        },
    )
    assert (root / "results" / "web.svg").is_file()
    assert plotted["data_out"].endswith("web.csv")

    replayed = workbench.execute("replay", {"run_id": "web_eval"})
    assert replayed["matches_recorded_result"] is True
    comparison_replay = workbench.execute(
        "replay", {"run_id": "web_comparison_chart"}
    )
    assert comparison_replay["matches_recorded_result"] is True
