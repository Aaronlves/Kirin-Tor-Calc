from __future__ import annotations

import shutil
from inspect import signature
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner


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


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_yaml(path: Path, content: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8")


def minimal_entry(entry_id: str, expression: str, inputs=None, unit: str = "dimensionless") -> dict:
    return {
        "schema_version": 1,
        "id": entry_id,
        "name": entry_id,
        "type": "entry",
        "template": "model",
        "inputs": inputs or {},
        "fields": {},
        "functions": {},
        "outputs": {"result": {"expression": expression, "unit": unit}},
    }
