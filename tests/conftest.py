from __future__ import annotations

import shutil
from inspect import signature
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_ROOT = PROJECT_ROOT / "examples" / "虚构技能工作区"


def make_cli_runner() -> CliRunner:
    """Create a runner across Click versions with separate stderr capture."""
    options = {}
    if "mix_stderr" in signature(CliRunner).parameters:
        options["mix_stderr"] = False
    return CliRunner(**options)


@pytest.fixture
def example_workspace(tmp_path: Path) -> Path:
    destination = tmp_path / "中文工作区"
    shutil.copytree(EXAMPLE_ROOT, destination)
    for path in (destination / "runs").glob("*"):
        path.unlink()
    for path in (destination / "results").glob("*"):
        path.unlink()
    return destination


def load_kirin(path: Path) -> dict:
    return load_kirin_document(path).raw


def write_kirin(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_kirin_document(content), encoding="utf-8")


def minimal_entry(entry_id: str, expression: str, inputs=None, unit: str = "dimensionless") -> dict:
    return {
        "schema_version": 1,
        "id": entry_id,
        "name": entry_id,
        "type": "entry",
        "inputs": inputs or {},
        "fields": {},
        "functions": {},
        "outputs": {"result": {"expression": expression, "unit": unit}},
    }
