from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import ReferenceError, SchemaError
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import evaluate
from kirin_tor.workspace import Workspace, initialize


SOURCE = """@kirin 2
@entry typed_objects "类型化对象"

dimension resource "资源"
unit resource = resource

type modifier:
  multiplier: dimensionless = 1

type skill:
  cost: resource
  occupies: time
  tuning: modifier

input haste "急速": probability = 0 in 0..1

skill burn "消耗技能":
  cost = 60
  occupies = 2 second / (1 + haste)
  tuning:
    multiplier = 3/2

output adjusted_cost "调整后消耗": resource = burn.cost * burn.tuning.multiplier
output duration "持续时间": time = burn.occupies
output minute_fraction: dimensionless = 25%
"""


def _workspace(tmp_path: Path) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "typed_objects.kirin").write_text(
        SOURCE, encoding="utf-8"
    )
    return Workspace.load(root)


def test_v2_typed_objects_nested_paths_and_literals(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "typed_objects.burn.cost")["exact"] == "60"
    assert evaluate(Engine(workspace), "typed_objects.adjusted_cost")["exact"] == "90"
    assert evaluate(Engine(workspace), "typed_objects.duration")["exact"] == "2"
    assert evaluate(Engine(workspace), "typed_objects.minute_fraction")["exact"] == "1/4"


def test_v2_closed_objects_and_private_paths_fail(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    with pytest.raises(ReferenceError, match="has no field"):
        evaluate(Engine(workspace), "typed_objects.burn.unknown")

    source = SOURCE.replace(
        "  tuning:\n    multiplier = 3/2\n",
        "  tuning:\n    multiplier = 3/2\n  unknown = 1\n",
    )
    root = initialize(tmp_path / "unknown")
    (root / "entries" / "unknown.kirin").write_text(source, encoding="utf-8")
    with pytest.raises(SchemaError, match="unknown field"):
        Engine(Workspace.load(root)).validate_all()


def test_v2_renderer_round_trips_public_source(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    document = workspace.entries["typed_objects"]
    rendered = render_kirin_document(load_kirin_document(document.path))
    target = workspace.root / "entries" / "rendered.kirin"
    target.write_text(
        rendered.replace("@entry typed_objects", "@entry rendered"),
        encoding="utf-8",
    )
    loaded = load_kirin_document(target)
    assert loaded.raw["types"] == document.raw["types"]
    assert loaded.raw["objects"] == document.raw["objects"]


def test_v2_renderer_rejects_unsupported_type_metadata(tmp_path: Path) -> None:
    raw = deepcopy(_workspace(tmp_path).entries["typed_objects"].raw)
    raw["types"]["skill"]["behavior"] = {"cost": "cost"}
    with pytest.raises(SchemaError, match="unsupported properties: behavior"):
        render_kirin_document(raw)


def test_type_declaration_accepts_fields_only(tmp_path: Path) -> None:
    root = initialize(tmp_path / "invalid-type-block")
    (root / "entries" / "removed.kirin").write_text(
        """@kirin 2
@entry invalid_type_block

type sample:
  value: dimensionless
  behavior:
    role = value
""",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="type body requires FIELD: TYPE"):
        Workspace.load(root)


def test_public_parser_rejects_v1(tmp_path: Path) -> None:
    root = initialize(tmp_path / "v1")
    (root / "entries" / "old.kirin").write_text(
        "@kirin 1\n@entry old\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="@kirin 2"):
        Workspace.load(root)
