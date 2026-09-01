from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import DomainError, ExpressionError, SchemaError, UnitError
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import evaluate, explain
from kirin_tor.workspace import Workspace, initialize


def _distribution_workspace(root: Path) -> Path:
    root = initialize(root)
    (root / "entries" / "semantics.kirin").write_text(
        """@kirin 1
@entry semantics

dimensions:
  damage

units:
  damage = damage
  damage_squared = damage ** 2
""",
        encoding="utf-8",
    )
    (root / "entries" / "proc_model.kirin").write_text(
        """@kirin 1
@entry proc_model

inputs:
  proc_chance "触发概率": probability = 0.25

fields:
  proc_damage: damage = 100

distributions:
  proc_result "触发结果": damage:
    0 @ 1 - proc_chance
    proc_damage @ proc_chance

outputs:
  expected_damage: damage = expectation(proc_result)
  damage_variance: damage_squared = variance(proc_result)
  proc_probability: dimensionless = probability(proc_result, proc_damage)
  zero_probability: dimensionless = probability(proc_result, 0)
  two_proc_expectation: damage = expectation(independent_sum(proc_result, proc_result))
  three_proc_expectation: damage = expectation(repeat_sum(proc_result, 3))
  three_proc_variance: damage_squared = variance(repeat_sum(proc_result, 3))
  exactly_two_procs: dimensionless = probability(repeat_sum(proc_result, 3), 200 * damage)
  mapped_proc_count: dimensionless = expectation(map(repeat_sum(proc_result, 3), result, result / proc_damage))
  conditional_damage: damage = expectation(condition(repeat_sum(proc_result, 3), result, result > 0))
""",
        encoding="utf-8",
    )
    (root / "entries" / "consumer.kirin").write_text(
        """@kirin 1
@entry consumer

outputs:
  imported_expectation: damage = expectation(proc_model.proc_result)
""",
        encoding="utf-8",
    )
    return root


def test_finite_distribution_expectation_variance_probability_and_dependencies(
    tmp_path: Path,
) -> None:
    root = _distribution_workspace(tmp_path / "distribution")
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"

    expected = {
        "proc_model.expected_damage": "25",
        "proc_model.damage_variance": "1875",
        "proc_model.proc_probability": "1/4",
        "proc_model.zero_probability": "3/4",
        "proc_model.two_proc_expectation": "50",
        "proc_model.three_proc_expectation": "75",
        "proc_model.three_proc_variance": "5625",
        "proc_model.exactly_two_procs": "9/64",
        "proc_model.mapped_proc_count": "3/4",
        "proc_model.conditional_damage": "4800/37",
        "consumer.imported_expectation": "25",
    }
    for target, exact in expected.items():
        assert evaluate(Engine(workspace), target)["exact"] == exact

    imported = explain(Engine(workspace), "consumer.imported_expectation")
    assert imported["dependency_ids"] == ["consumer", "proc_model"]


def test_distribution_source_round_trips_without_losing_outcomes(tmp_path: Path) -> None:
    root = _distribution_workspace(tmp_path / "round-trip")
    source = root / "entries" / "proc_model.kirin"
    raw, _text, _digest, _positions = load_kirin_document(source)
    rendered = render_kirin_document(raw)
    rendered_path = root / "entries" / "rendered.kirin"
    rendered_path.write_text(
        rendered.replace("@entry proc_model", "@entry rendered"),
        encoding="utf-8",
    )

    rendered_raw, _text, _digest, _positions = load_kirin_document(rendered_path)
    assert rendered_raw["distributions"] == raw["distributions"]


def test_distribution_probabilities_are_checked_at_defaults_and_overrides(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "invalid-probability")
    path = root / "entries" / "invalid.kirin"
    path.write_text(
        """@kirin 1
@entry invalid

inputs:
  p: number[dimensionless] = 3/2

distributions:
  result: dimensionless:
    0 @ 1 - p
    1 @ p

outputs:
  expected: dimensionless = expectation(result)
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    with pytest.raises(DomainError, match="domain condition failed"):
        Engine(workspace).validate_all()

    path.write_text(path.read_text(encoding="utf-8").replace("= 3/2", "= 1/2"), encoding="utf-8")
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(
            Engine(workspace),
            "invalid.expected",
            overrides={"invalid.p": "2"},
        )


def test_distribution_rejects_invalid_total_units_and_direct_scalar_use(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "invalid-distributions")
    path = root / "entries" / "invalid.kirin"
    path.write_text(
        """@kirin 1
@entry invalid

distributions:
  result: dimensionless:
    0 @ 1/2
    1 @ 1/4
""",
        encoding="utf-8",
    )
    with pytest.raises(DomainError, match="domain condition failed"):
        Engine(Workspace.load(root)).validate_all()

    path.write_text(
        """@kirin 1
@entry invalid

distributions:
  result: time:
    1 @ 1
""",
        encoding="utf-8",
    )
    with pytest.raises(UnitError, match="declared unit"):
        Engine(Workspace.load(root)).validate_all()

    path.write_text(
        """@kirin 1
@entry invalid

distributions:
  result: dimensionless:
    1 @ 1

outputs:
  invalid_use: dimensionless = result
""",
        encoding="utf-8",
    )
    with pytest.raises(ExpressionError, match="must be observed"):
        Engine(Workspace.load(root)).validate_all()


def test_distribution_syntax_requires_value_probability_pairs(tmp_path: Path) -> None:
    root = initialize(tmp_path / "invalid-syntax")
    (root / "entries" / "invalid.kirin").write_text(
        """@kirin 1
@entry invalid

distributions:
  result: dimensionless:
    1 = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="VALUE @ PROBABILITY"):
        Workspace.load(root)


def test_distribution_transform_counts_are_bounded_and_conditions_are_nonempty(tmp_path: Path) -> None:
    root = _distribution_workspace(tmp_path / "transform-boundaries")
    path = root / "entries" / "invalid_transform.kirin"
    path.write_text(
        """@kirin 1
@entry invalid_transform

inputs:
  repetitions: nonnegative_integer = 2 in 0..4

outputs:
  dynamic_repeat: damage =
    expectation(repeat_sum(proc_model.proc_result, repetitions))
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "invalid_transform.dynamic_repeat")["exact"] == "50"
    assert evaluate(
        Engine(workspace),
        "invalid_transform.dynamic_repeat",
        overrides={"invalid_transform.repetitions": "3"},
    )["exact"] == "75"

    path.write_text(
        """@kirin 1
@entry invalid_transform

outputs:
  impossible_condition: damage =
    expectation(condition(proc_model.proc_result, result, result > 1000 * damage))
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(Engine(workspace), "invalid_transform.impossible_condition")
