from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import DependencyCycleError, ExpressionError, UnitError
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import evaluate
from kirin_tor.workspace import Workspace, initialize


def _recurrence_workspace(root: Path) -> Path:
    root = initialize(root)
    (root / "entries" / "recurrence_model.kirin").write_text(
        """@kirin 1
@entry recurrence_model

inputs:
  failures: nonnegative_integer = 3 in 0..5
  base_chance: probability = 1/10
  increase: probability = 1/20
  cap: probability = 3/10

recurrences:
  protected_chance "失败保护概率": dimensionless:
    initial = base_chance
    steps = failures
    next(current, index) = min(current + increase, cap)

  triangular "三角数": dimensionless:
    initial = 0
    steps = failures
    next(total, index) = total + index + 1

outputs:
  current_chance: dimensionless = protected_chance
  triangular_value: dimensionless = triangular
""",
        encoding="utf-8",
    )
    (root / "entries" / "consumer.kirin").write_text(
        """@kirin 1
@entry consumer

outputs:
  imported: dimensionless = recurrence_model.protected_chance
""",
        encoding="utf-8",
    )
    return root


def test_finite_recurrence_supports_bounded_inputs_index_and_cross_entry_use(
    tmp_path: Path,
) -> None:
    root = _recurrence_workspace(tmp_path / "recurrence")
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "recurrence_model.current_chance")["exact"] == "1/4"
    assert evaluate(Engine(workspace), "recurrence_model.triangular_value")["exact"] == "6"
    assert evaluate(Engine(workspace), "consumer.imported")["exact"] == "1/4"
    assert evaluate(
        Engine(workspace),
        "recurrence_model.current_chance",
        overrides={"recurrence_model.failures": "0"},
    )["exact"] == "1/10"
    assert evaluate(
        Engine(workspace),
        "recurrence_model.current_chance",
        overrides={"recurrence_model.failures": "5"},
    )["exact"] == "3/10"


def test_recurrence_source_round_trips(tmp_path: Path) -> None:
    root = _recurrence_workspace(tmp_path / "round-trip")
    source = root / "entries" / "recurrence_model.kirin"
    raw, _text, _digest, _positions = load_kirin_document(source)
    rendered = render_kirin_document(raw)
    rendered_path = root / "entries" / "rendered.kirin"
    rendered_path.write_text(
        rendered.replace("@entry recurrence_model", "@entry rendered"),
        encoding="utf-8",
    )
    rendered_raw, _text, _digest, _positions = load_kirin_document(rendered_path)
    assert rendered_raw["recurrences"] == raw["recurrences"]


def test_recurrence_requires_statically_bounded_nonnegative_steps(tmp_path: Path) -> None:
    root = initialize(tmp_path / "unbounded")
    path = root / "entries" / "unbounded.kirin"
    path.write_text(
        """@kirin 1
@entry unbounded

inputs:
  steps: nonnegative_integer = 2

recurrences:
  result: dimensionless:
    initial = 0
    steps = steps
    next(current, index) = current + 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ExpressionError, match="finite integer bounds"):
        Engine(Workspace.load(root)).validate_all()

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "steps: nonnegative_integer = 2",
            "steps: number[dimensionless] = -1 in -1..2 integer",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ExpressionError, match="between 0"):
        Engine(Workspace.load(root)).validate_all()


def test_recurrence_preserves_units_and_rejects_cycles(tmp_path: Path) -> None:
    root = initialize(tmp_path / "invalid")
    path = root / "entries" / "invalid.kirin"
    path.write_text(
        """@kirin 1
@entry invalid

recurrences:
  result: time:
    initial = 1 * second
    steps = 2
    next(current, index) = current + 1
""",
        encoding="utf-8",
    )
    with pytest.raises(UnitError, match="incompatible units"):
        Engine(Workspace.load(root)).validate_all()

    path.write_text(
        """@kirin 1
@entry invalid

recurrences:
  result: dimensionless:
    initial = 0
    steps = 1
    next(current, index) = result + 1
""",
        encoding="utf-8",
    )
    with pytest.raises(DependencyCycleError, match="dependency cycle"):
        Engine(Workspace.load(root)).validate_all()
