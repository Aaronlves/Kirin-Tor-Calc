from __future__ import annotations

import json
from pathlib import Path

from kirin_tor.cli import app
from kirin_tor.engine import Engine
from kirin_tor.operations import scan_grid, solve_system
from kirin_tor.workspace import Workspace, initialize

from conftest import make_cli_runner


def _workspace(tmp_path: Path) -> Path:
    root = initialize(tmp_path / "advanced")
    (root / "entries" / "build_math.kirin").write_text(
        """@kirin 2
@entry build_math

input power "主属性": number[dimensionless] = 2 in 0..10

input speed "急速": number[dimensionless] = 1 in 0..10

output total "总收益": dimensionless = 2 * power + speed

output balance "属性差": dimensionless = power - speed
""",
        encoding="utf-8",
    )
    return root


def test_two_axis_grid_and_system_solve_are_exact(tmp_path: Path) -> None:
    workspace = Workspace.load(_workspace(tmp_path))
    grid = scan_grid(
        Engine(workspace),
        "build_math.power",
        "1:3",
        3,
        "build_math.speed",
        "1:2",
        2,
        "build_math.total",
    )
    assert grid["points"] == 6
    assert grid["valid_points"] == 6
    assert [row["value"]["exact"] for row in grid["rows"]] == ["3", "5", "7", "4", "6", "8"]

    solved = solve_system(
        Engine(workspace),
        [("build_math.total", "9"), ("build_math.balance", "1")],
        ["build_math.power", "build_math.speed"],
    )
    assert solved["solution_kind"] == "exact"
    values = solved["solutions"][0]["values"]
    assert values["build_math.power"]["exact"] == "10/3"
    assert values["build_math.speed"]["exact"] == "7/3"


def test_grid_and_system_solve_cli_commands_are_recordable_and_replayable(
    tmp_path: Path, monkeypatch
) -> None:
    root = _workspace(tmp_path)
    monkeypatch.chdir(root)
    runner = make_cli_runner()

    grid = runner.invoke(
        app,
        [
            "grid",
            "--x", "build_math.power",
            "--x-range", "1:3",
            "--x-points", "3",
            "--y", "build_math.speed",
            "--y-range", "1:2",
            "--y-points", "2",
            "--result", "build_math.total",
            "--out", "results/grid.csv",
            "--save-run", "grid_run",
            "--json",
        ],
    )
    assert grid.exit_code == 0, grid.output
    assert json.loads(grid.stdout)["valid_points"] == 6
    replay = runner.invoke(app, ["replay", "grid_run", "--json"])
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.stdout)["matches_recorded_result"] is True

    system = runner.invoke(
        app,
        [
            "solve-system",
            "--equation", "build_math.total=9",
            "--equation", "build_math.balance=1",
            "--var", "build_math.power",
            "--var", "build_math.speed",
            "--save-run", "system_run",
            "--json",
        ],
    )
    assert system.exit_code == 0, system.output
    assert json.loads(system.stdout)["solution_kind"] == "exact"
    replay = runner.invoke(app, ["replay", "system_run", "--json"])
    assert replay.exit_code == 0, replay.output
    assert json.loads(replay.stdout)["matches_recorded_result"] is True
