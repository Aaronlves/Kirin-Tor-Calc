from __future__ import annotations

import json
from pathlib import Path

from kirin_tor.cli import app

from conftest import make_cli_runner


runner = make_cli_runner()


def test_replay_reports_version_drift_without_using_current_entries(
    example_workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(example_workspace)
    recorded = runner.invoke(
        app,
        [
            "eval", "combo.total", "--preset", "baseline",
            "--save-run", "versioned", "--json",
        ],
    )
    assert recorded.exit_code == 0, recorded.stderr
    record_path = example_workspace / "runs" / "versioned.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["run_format_version"] == 2
    assert all("source_text" in snapshot for snapshot in record["definitions"])
    record["software"]["sympy"] = "0.0-test-drift"
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    (example_workspace / "entries" / "技能甲.kirin").write_text(
        "not valid Kirin source", encoding="utf-8"
    )
    replayed = runner.invoke(app, ["replay", "versioned", "--json"])
    assert replayed.exit_code == 0, replayed.stderr
    payload = json.loads(replayed.stdout)
    assert payload["matches_recorded_result"] is True
    assert payload["environment_match"] is False
    assert payload["version_drift"]["sympy"]["recorded"] == "0.0-test-drift"


def test_plot_record_hashes_and_regenerates_artifacts_from_snapshots(
    example_workspace: Path, monkeypatch
) -> None:
    monkeypatch.chdir(example_workspace)
    plotted = runner.invoke(
        app,
        [
            "plot", "--x", "combo.crit", "--range", "0:0.6", "--points", "7",
            "--y", "combo.total", "--preset", "baseline",
            "--out", "results/recorded.svg", "--data-out", "results/recorded.csv",
            "--save-run", "plot_record", "--json",
        ],
    )
    assert plotted.exit_code == 0, plotted.stderr
    record = json.loads(
        (example_workspace / "runs" / "plot_record.json").read_text(encoding="utf-8")
    )
    assert record["artifacts"]["out"]["sha256"]
    assert record["artifacts"]["data_out"]["sha256"]

    (example_workspace / "entries" / "组合模型.kirin").write_text(
        "not valid Kirin source", encoding="utf-8"
    )
    replayed = runner.invoke(
        app,
        [
            "replay", "plot_record", "--regenerate-artifacts",
            "--out", "results/replayed.svg", "--data-out", "results/replayed.csv",
            "--json",
        ],
    )
    assert replayed.exit_code == 0, replayed.stderr
    payload = json.loads(replayed.stdout)
    assert payload["matches_recorded_result"] is True
    assert (example_workspace / "results" / "replayed.svg").read_text(encoding="utf-8").startswith("<?xml")
    assert (example_workspace / "results" / "replayed.csv").is_file()
    assert payload["regenerated_artifacts"]["hashes"]["out"]["sha256"]
