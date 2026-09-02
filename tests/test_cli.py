from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from kirin_tor import __version__
from kirin_tor.cli import app
from kirin_tor.workspace import Workspace, initialize

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
    checked = runner.invoke(app, ["check", "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["status"] == "ok"
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "Kirin Tor" in help_result.stdout
    assert "web" in help_result.stdout
    assert "tui" not in help_result.stdout.lower()


def test_web_command_accepts_workspace_directory_without_chdir(
    example_workspace: Path, tmp_path: Path, monkeypatch
) -> None:
    captured = {}
    preferences_home = tmp_path / "workbench-user"
    monkeypatch.setenv("KIRIN_WORKBENCH_HOME", str(preferences_home))

    def fake_run_web(
        root: Path,
        *,
        port: int,
        open_browser: bool,
        initial_document,
        safe_mode: bool,
    ) -> None:
        captured["root"] = root
        captured["port"] = port
        captured["open_browser"] = open_browser
        captured["initial_document"] = initial_document
        captured["safe_mode"] = safe_mode

    monkeypatch.setattr("kirin_tor.web.run_web", fake_run_web)
    launched = runner.invoke(app, ["web", str(example_workspace), "--port", "8123", "--no-open"])
    assert launched.exit_code == 0, launched.output
    assert captured == {
        "root": example_workspace.resolve(),
        "port": 8123,
        "open_browser": False,
        "initial_document": None,
        "safe_mode": False,
    }
    preferences = json.loads(
        (preferences_home / "workbench-preferences.json").read_text(encoding="utf-8")
    )
    assert preferences == {
        "schema": 1,
        "default_workspace": str(example_workspace.resolve()),
    }

    source = example_workspace / "entries" / "组合模型.kirin"
    launched = runner.invoke(app, ["web", str(source), "--no-open"])
    assert launched.exit_code == 0, launched.output
    assert captured["initial_document"] == source.resolve()

    launched = runner.invoke(app, ["web", str(example_workspace), "--safe-mode", "--no-open"])
    assert launched.exit_code == 0, launched.output
    assert captured["safe_mode"] is True

    missing = runner.invoke(app, ["web", str(example_workspace / "missing.kirin"), "--no-open"])
    assert missing.exit_code == 1
    assert "existing .kirin file" in missing.stderr


def test_web_command_resolves_current_saved_and_chosen_workspaces(
    example_workspace: Path, tmp_path: Path, monkeypatch
) -> None:
    captured = {}
    preferences_home = tmp_path / "workbench-user"
    outside = tmp_path / "outside"
    outside.mkdir()
    other_workspace = tmp_path / "另一个工作区"
    selected_workspace = tmp_path / "首次选择"
    initialize(other_workspace)
    monkeypatch.setenv("KIRIN_WORKBENCH_HOME", str(preferences_home))

    def fake_run_web(
        root: Path,
        *,
        port: int,
        open_browser: bool,
        initial_document,
        safe_mode: bool,
    ) -> None:
        captured["root"] = root

    monkeypatch.setattr("kirin_tor.web.run_web", fake_run_web)

    launched = runner.invoke(app, ["web", str(example_workspace), "--no-open"])
    assert launched.exit_code == 0, launched.output
    monkeypatch.chdir(outside)
    launched = runner.invoke(app, ["web", "--no-open"])
    assert launched.exit_code == 0, launched.output
    assert captured["root"] == example_workspace.resolve()

    monkeypatch.chdir(other_workspace)
    launched = runner.invoke(app, ["web", "--no-open"])
    assert launched.exit_code == 0, launched.output
    assert captured["root"] == other_workspace.resolve()

    monkeypatch.chdir(outside)
    launched = runner.invoke(
        app,
        ["web", "--choose", "--no-open"],
        input=f"{selected_workspace}\ny\n",
    )
    assert launched.exit_code == 0, launched.output
    assert captured["root"] == selected_workspace.resolve()
    assert (selected_workspace / "kirin.workspace").is_file()
    preferences = json.loads(
        (preferences_home / "workbench-preferences.json").read_text(encoding="utf-8")
    )
    assert preferences["default_workspace"] == str(selected_workspace.resolve())

    first_run_home = tmp_path / "first-run-user"
    first_run_workspace = tmp_path / "首次启动"
    monkeypatch.setenv("KIRIN_WORKBENCH_HOME", str(first_run_home))
    launched = runner.invoke(
        app,
        ["web", "--no-open"],
        input=f"{first_run_workspace}\ny\n",
    )
    assert launched.exit_code == 0, launched.output
    assert captured["root"] == first_run_workspace.resolve()
    assert (first_run_workspace / "kirin.workspace").is_file()

    conflict = runner.invoke(
        app,
        ["web", str(example_workspace), "--choose", "--no-open"],
    )
    assert conflict.exit_code == 1
    assert "cannot be used together" in conflict.stderr


def test_local_workbench_plugin_cli_workflow(
    example_workspace: Path,
    tmp_path: Path,
    monkeypatch,
) -> None:
    plugin = Path(__file__).resolve().parents[1] / "examples" / "plugins" / "fictional-talent-tree"
    monkeypatch.chdir(example_workspace)
    monkeypatch.setenv("KIRIN_PLUGIN_HOME", str(tmp_path / "plugin-user"))

    added = runner.invoke(app, ["plugin", "add-path", "talents", str(plugin), "--json"])
    assert added.exit_code == 0, added.output
    payload = json.loads(added.stdout)
    assert payload["plugins"][0]["status"] == "active"
    assert payload["contributions"]["renderers"][0]["id"].endswith(".talent-tree")

    disabled = runner.invoke(app, ["plugin", "disable", "talents", "--json"])
    assert disabled.exit_code == 0, disabled.output
    assert json.loads(disabled.stdout)["plugins"][0]["status"] == "disabled"
    enabled = runner.invoke(app, ["plugin", "enable", "talents", "--json"])
    assert enabled.exit_code == 0, enabled.output
    assert json.loads(enabled.stdout)["plugins"][0]["status"] == "active"

    verified = runner.invoke(app, ["plugin", "verify", "--json"])
    assert verified.exit_code == 0, verified.output
    listed = runner.invoke(app, ["plugin", "list"])
    assert listed.exit_code == 0, listed.output
    assert "community.fictional-talents@1.0.0" in listed.stdout

    removed = runner.invoke(app, ["plugin", "remove", "talents", "--json"])
    assert removed.exit_code == 0, removed.output
    assert json.loads(removed.stdout)["plugins"] == []


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
    assert completed.stdout.strip() == __version__


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


def test_new_workspace_and_templates_are_game_neutral(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "工作区"
    initialized = runner.invoke(app, ["init", str(root)])
    assert initialized.exit_code == 0, initialized.output
    assert not list((root / "entries").glob("*.kirin"))
    assert (root / "kirin.workspace").read_text(encoding="utf-8") == "@kirin-workspace 1\n"

    monkeypatch.chdir(root)
    for item_id, template in (
        ("generic", "model"),
        ("curve", "chart"),
    ):
        created = runner.invoke(app, ["new", "entry", item_id, "--template", template])
        assert created.exit_code == 0, created.output
        assert (root / "entries" / f"{item_id}.kirin").is_file()
    assert {path.name for path in root.iterdir() if path.is_dir()} == {
        "entries",
        "results",
        "runs",
    }


def test_package_author_and_local_consumer_cli_workflow(tmp_path: Path, monkeypatch) -> None:
    package = tmp_path / "community-package"
    created = runner.invoke(
        app,
        [
            "package",
            "new",
            str(package),
            "--name",
            "community.example",
            "--namespace",
            "community_example",
        ],
    )
    assert created.exit_code == 0, created.output
    assert (package / "kirin.package.toml").is_file()
    assert (package / ".github" / "workflows" / "validate.yml").is_file()
    assert (package / "templates" / "entries" / "consumer.kirin").is_file()

    checked = runner.invoke(app, ["package", "check", str(package), "--json"])
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["validation"]["status"] == "ok"

    workspace = tmp_path / "workspace"
    assert runner.invoke(app, ["init", str(workspace)]).exit_code == 0
    monkeypatch.chdir(workspace)
    added = runner.invoke(
        app, ["package", "add-path", "example", str(package), "--json"]
    )
    assert added.exit_code == 0, added.output
    payload = json.loads(added.stdout)
    assert payload["packages"][0]["name"] == "community.example"
    assert (workspace / "kirin.packages.toml").is_file()
    assert (workspace / "kirin.lock").is_file()
    documents = runner.invoke(app, ["list", "--json"])
    assert documents.exit_code == 0, documents.output
    packaged_document = json.loads(documents.stdout)["documents"][0]
    assert packaged_document["read_only"] is True
    assert packaged_document["package_origin"]["source"].startswith("path:")
    explained = runner.invoke(
        app, ["explain", "community_example_example.result", "--json"]
    )
    assert explained.exit_code == 0, explained.output
    assert json.loads(explained.stdout)["provenance"][0]["package"]["version"] == "1.0.0"

    listed = runner.invoke(app, ["package", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout)["packages"][0]["direct"] is True
    verified = runner.invoke(app, ["package", "verify", "--json"])
    assert verified.exit_code == 0, verified.output

    recorded = runner.invoke(
        app,
        [
            "eval",
            "community_example_example.result",
            "--save-run",
            "package-result",
            "--json",
        ],
    )
    assert recorded.exit_code == 0, recorded.output
    run = json.loads((workspace / "runs" / "package-result.json").read_text(encoding="utf-8"))
    package_snapshot = next(
        item for item in run["definitions"] if item["id"] == "community_example_example"
    )
    assert package_snapshot["package"]["name"] == "community.example"

    removed = runner.invoke(app, ["package", "remove", "example", "--json"])
    assert removed.exit_code == 0, removed.output
    assert json.loads(removed.stdout)["packages"] == []
    replayed = runner.invoke(app, ["replay", "package-result", "--json"])
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.stdout)["matches_recorded_result"] is True


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
