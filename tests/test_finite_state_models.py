from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import DependencyCycleError, DomainError, SchemaError, UnitError
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import evaluate, explain
from kirin_tor.workspace import Workspace, initialize


def _state_workspace(root: Path) -> Path:
    root = initialize(root)
    (root / "entries" / "semantics.kirin").write_text(
        """@kirin 2
@entry semantics

dimension damage

unit damage = damage
""",
        encoding="utf-8",
    )
    (root / "entries" / "state_model.kirin").write_text(
        """@kirin 2
@entry state_model

input proc_chance: probability = 1/4

field hit: damage = 100

output ready_probability: dimensionless = steady_probability(proc_cycle, ready)

output cooldown_probability: dimensionless = steady_probability(proc_cycle, cooldown)

output steady_damage: damage = steady_reward(proc_cycle, damage_reward)

output reaches_cooldown: dimensionless = hitting_probability(proc_cycle, ready, cooldown)

output steps_to_cooldown: dimensionless = expected_steps(proc_cycle, ready, cooldown)

output steps_to_ready: dimensionless = expected_steps(proc_cycle, cooldown, ready)

state_model proc_cycle "触发循环":
  states:
    - ready
    - cooldown
  transitions:
    - ready -> ready @ 1 - proc_chance
    - ready -> cooldown @ proc_chance
    - cooldown -> ready @ 1
  rewards:
    reward damage_reward "状态伤害": damage:
      ready = hit
      cooldown = 0
""",
        encoding="utf-8",
    )
    (root / "entries" / "consumer.kirin").write_text(
        """@kirin 2
@entry consumer

output imported: dimensionless = steady_probability(state_model.proc_cycle, cooldown)
""",
        encoding="utf-8",
    )
    return root


def test_state_model_solves_steady_rewards_and_hitting_queries(tmp_path: Path) -> None:
    root = _state_workspace(tmp_path / "states")
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    expected = {
        "state_model.ready_probability": "4/5",
        "state_model.cooldown_probability": "1/5",
        "state_model.steady_damage": "80",
        "state_model.reaches_cooldown": "1",
        "state_model.steps_to_cooldown": "4",
        "state_model.steps_to_ready": "1",
        "consumer.imported": "1/5",
    }
    for target, exact in expected.items():
        assert evaluate(Engine(workspace), target)["exact"] == exact
    explained = explain(Engine(workspace), "consumer.imported")
    assert explained["dependency_ids"] == ["consumer", "state_model"]


def test_state_model_source_round_trips(tmp_path: Path) -> None:
    root = _state_workspace(tmp_path / "round-trip")
    source = root / "entries" / "state_model.kirin"
    loaded = load_kirin_document(source)
    rendered = render_kirin_document(loaded)
    rendered_path = root / "entries" / "rendered.kirin"
    rendered_path.write_text(
        rendered.replace("@entry state_model", "@entry rendered"),
        encoding="utf-8",
    )
    rendered_loaded = load_kirin_document(rendered_path)
    assert rendered_loaded.raw["state_models"] == loaded.raw["state_models"]


def test_state_model_validates_probability_rows_and_reward_coverage(tmp_path: Path) -> None:
    root = initialize(tmp_path / "invalid")
    path = root / "entries" / "invalid.kirin"
    path.write_text(
        """@kirin 2
@entry invalid

state_model model:
  states:
    - a
    - b
  transitions:
    - a -> a @ 1/2
    - b -> b @ 1
""",
        encoding="utf-8",
    )
    with pytest.raises(DomainError, match="domain condition failed"):
        Engine(Workspace.load(root)).validate_all()

    path.write_text(
        """@kirin 2
@entry invalid

state_model model:
  states:
    - a
    - b
  transitions:
    - a -> b @ 1
    - b -> a @ 1
  rewards:
    reward value: dimensionless:
      a = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="must cover every state"):
        Workspace.load(root)


def test_state_queries_reject_nonunique_or_unreachable_systems(tmp_path: Path) -> None:
    root = initialize(tmp_path / "nonunique")
    path = root / "entries" / "model.kirin"
    path.write_text(
        """@kirin 2
@entry model

output invalid_steady: dimensionless = steady_probability(split, left)

state_model split:
  states:
    - left
    - right
  transitions:
    - left -> left @ 1
    - right -> right @ 1
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    assert evaluate(
        Engine(workspace), "hitting_probability(model.split, left, left)"
    )["exact"] == "1"
    assert evaluate(
        Engine(workspace), "expected_steps(model.split, left, left)"
    )["exact"] == "0"
    with pytest.raises(DomainError, match="not uniquely determined"):
        Engine(workspace).validate_all()

    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "steady_probability(split, left)",
            "hitting_probability(split, left, right)",
        ),
        encoding="utf-8",
    )
    with pytest.raises(DomainError, match="not uniquely determined"):
        Engine(Workspace.load(root)).validate_all()


def test_state_model_preserves_reward_units_and_detects_cycles(tmp_path: Path) -> None:
    root = initialize(tmp_path / "units")
    path = root / "entries" / "invalid.kirin"
    path.write_text(
        """@kirin 2
@entry invalid

state_model model:
  states:
    - only
  transitions:
    - only -> only @ 1
  rewards:
    reward duration: time:
      only = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(UnitError, match="declared unit"):
        Engine(Workspace.load(root)).validate_all()

    path.write_text(
        """@kirin 2
@entry invalid

state_model model:
  states:
    - only
  transitions:
    - only -> only @ 1
  rewards:
    reward value: dimensionless:
      only = steady_reward(model, value)
""",
        encoding="utf-8",
    )
    with pytest.raises(DependencyCycleError, match="dependency cycle"):
        Engine(Workspace.load(root)).validate_all()


def test_symbolic_hitting_query_keeps_singularity_as_domain_condition(tmp_path: Path) -> None:
    root = _state_workspace(tmp_path / "symbolic")
    workspace = Workspace.load(root)
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(
            Engine(workspace),
            "state_model.steps_to_cooldown",
            overrides={"state_model.proc_chance": "0"},
        )
