from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from kirin_tor.cli import app
from kirin_tor.workspace import Workspace

from conftest import load_kirin, make_cli_runner, minimal_entry, write_kirin


runner = make_cli_runner()


def test_cli_json_stdout_exit_codes_and_stderr(example_workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(example_workspace)
    success = runner.invoke(app, ["eval", "combo.total", "--preset", "baseline", "--json"])
    assert success.exit_code == 0, success.output
    payload = json.loads(success.stdout)
    assert payload["exact"] == "2750"
    assert success.stderr == ""

    failure = runner.invoke(app, ["eval", "missing.output", "--json"])
    assert failure.exit_code == 1
    error_payload = json.loads(failure.stdout)
    assert error_payload["status"] == "error"
    assert "Error [" in failure.stderr

    recorded_failure = runner.invoke(
        app, ["eval", "missing.output", "--save-run", "failed_attempt", "--json"]
    )
    assert recorded_failure.exit_code == 1
    record = json.loads((example_workspace / "runs" / "failed_attempt.json").read_text(encoding="utf-8"))
    assert record["status"] == "error"
    assert record["definitions"]
    replayed_failure = runner.invoke(app, ["replay", "failed_attempt", "--json"])
    assert replayed_failure.exit_code == 0, replayed_failure.stderr
    replay_payload = json.loads(replayed_failure.stdout)
    assert replay_payload["matches_recorded_result"] is True
    assert replay_payload["replayed_result"]["status"] == "error"


def test_cli_help_new_check_and_chinese_paths(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path / "包含中文的目录"
    initialized = runner.invoke(app, ["init", str(outside)])
    assert initialized.exit_code == 0, initialized.output
    monkeypatch.chdir(outside)
    created = runner.invoke(
        app, ["new", "entry", "fictional_skill", "--template", "data"]
    )
    assert created.exit_code == 0, created.output
    created_path = outside / "entries" / "fictional_skill.kirin"
    assert created_path.is_file()
    created_document = Workspace.load(outside).get_entry("fictional_skill")
    assert created_document.type == "entry"
    assert created_document.template == "data"
    checked = runner.invoke(app, ["check", "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["status"] == "ok"
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "Kirin Tor" in help_result.stdout


def test_tui_command_accepts_workspace_directory_without_chdir(
    example_workspace: Path, monkeypatch
) -> None:
    captured = {}

    def fake_run_tui(root: Path, source) -> None:
        captured["root"] = root
        captured["source"] = source

    monkeypatch.setattr("kirin_tor.tui.run_tui", fake_run_tui)
    launched = runner.invoke(app, ["tui", str(example_workspace)])
    assert launched.exit_code == 0, launched.output
    assert captured == {"root": example_workspace.resolve(), "source": None}


def test_installed_entry_point_runs_outside_source_tree(tmp_path: Path) -> None:
    executable = shutil.which("kt")
    if executable is None:
        if sys.platform == "win32":
            candidate = Path(sys.executable).parent / "Scripts" / "kt.exe"
        else:
            candidate = Path(sys.executable).parent / "kt"
        if candidate.is_file():
            executable = str(candidate)
    assert executable is not None
    completed = subprocess.run(
        [executable, "version"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "0.2.0"


def test_cli_scan_timeout_path_boundary_and_no_clobber(example_workspace: Path, monkeypatch) -> None:
    monkeypatch.chdir(example_workspace)
    base = [
        "scan", "--x", "combo.crit", "--range", "0:1", "--points", "2",
        "--y", "combo.total", "--json",
    ]
    timed_out = runner.invoke(app, [*base, "--timeout", "0.000000001"])
    assert timed_out.exit_code == 1
    assert json.loads(timed_out.stdout)["code"] == "timeout"

    escaped = runner.invoke(app, [*base, "--out", "../escape.csv"])
    assert escaped.exit_code == 1
    assert "leaves the workspace" in escaped.stderr
    assert not (example_workspace.parent / "escape.csv").exists()

    first = runner.invoke(app, [*base, "--out", "results/protected.csv"])
    assert first.exit_code == 0, first.stderr
    second = runner.invoke(app, [*base, "--out", "results/protected.csv"])
    assert second.exit_code == 1
    assert "already exists" in second.stderr
    forced = runner.invoke(app, [*base, "--out", "results/protected.csv", "--force"])
    assert forced.exit_code == 0, forced.stderr


def test_new_game_neutral_templates_and_wow_data_package(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "工作区"
    initialized = runner.invoke(app, ["init", str(root), "--package", "wow"])
    assert initialized.exit_code == 0, initialized.output
    package = root / "entries" / "wow_semantics.kirin"
    assert package.is_file()
    package_document = load_kirin(package)
    assert package_document["type"] == "entry"
    assert "attack_power" in package_document["semantics"]["dimensions"]

    monkeypatch.chdir(root)
    for kind, item_id, folder in (
        ("entry", "generic", "entries"),
        ("plot", "curve", "plots"),
    ):
        created = runner.invoke(app, ["new", kind, item_id])
        assert created.exit_code == 0, created.output
        assert (root / folder / f"{item_id}.kirin").is_file()
    assert {path.name for path in root.iterdir() if path.is_dir()} == {
        "entries",
        "plots",
        "results",
        "runs",
    }


def test_check_aggregates_independent_math_errors_as_json(example_workspace: Path, monkeypatch) -> None:
    write_kirin(
        example_workspace / "entries" / "broken_a.kirin",
        minimal_entry("broken_a", "missing_a.result"),
    )
    write_kirin(
        example_workspace / "entries" / "broken_b.kirin",
        minimal_entry("broken_b", "missing_b.result"),
    )
    monkeypatch.chdir(example_workspace)
    checked = runner.invoke(app, ["check", "--json"])
    assert checked.exit_code == 1
    payload = json.loads(checked.stdout)
    assert payload["code"] == "validation_errors"
    assert len(payload["errors"]) >= 2
    assert all("line" in error["location"] for error in payload["errors"][:2])


def test_incomplete_solve_keeps_structured_result_and_nonzero_exit(
    example_workspace: Path, monkeypatch
) -> None:
    write_kirin(
        example_workspace / "entries" / "identity.kirin",
        minimal_entry("identity", "x - x", {"x": {}}),
    )
    monkeypatch.chdir(example_workspace)
    solved = runner.invoke(
        app,
        ["solve", "identity.result", "--var", "identity.x", "--equals", "0", "--json"],
    )
    assert solved.exit_code == 1
    payload = json.loads(solved.stdout)
    assert payload["status"] == "incomplete"
    assert payload["solution_kind"] == "incomplete"
    assert "internal_operation_error" not in solved.stderr
