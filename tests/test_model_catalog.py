from __future__ import annotations

import json
from pathlib import Path

import pytest

from kirin_tor.errors import ParameterError, StaleRevisionError
from kirin_tor.model_catalog import MODEL_DESCRIPTOR_KINDS, ModelCatalog
from kirin_tor.package_authoring import add_path_package
from kirin_tor.package_manifest import current_feature_line
from kirin_tor.workbench import Workbench
from kirin_tor.workspace import initialize


def _large_interface_package(root: Path, count: int = 275) -> Path:
    root.mkdir(parents=True)
    (root / "kirin.package.toml").write_text(
        f'''schema = 2
name = "community.large-catalog"
version = "1.0.0"
namespace = "large_catalog"
description = "Large Catalog fixture"
license = "MIT"
requires_kirin = "{current_feature_line()}"

[interfaces."fictional.large-model"]
revision = 3
documents = []
document_prefixes = ["large_catalog_item_"]
''',
        encoding="utf-8",
    )
    entries = root / "entries"
    entries.mkdir()
    for index in range(count):
        (entries / f"item_{index:03d}.kirin").write_text(
            "@kirin 2\n"
            f"@entry large_catalog_item_{index:03d} \"Item {index:03d}\"\n\n"
            f"output value: dimensionless = {index}\n",
            encoding="utf-8",
        )
    return root


def test_catalog_covers_declared_kinds_and_revision_bound_queries(
    example_workspace: Path,
) -> None:
    workbench = Workbench(example_workspace)
    summary = workbench.bootstrap()["catalog"]
    revision = summary["revision"]

    assert set(summary["descriptor_kinds"]) == set(MODEL_DESCRIPTOR_KINDS)
    assert summary["counts"]["entry"] == 7
    queried = workbench.model_action(
        "model.query",
        {"revision": revision, "kind": ["output"], "limit": 1},
    )
    assert queried["count"] == 1
    assert queried["total"] == 2
    assert queried["next_cursor"]
    second = workbench.model_action(
        "model.query",
        {
            "revision": revision,
            "kind": ["output"],
            "limit": 1,
            "cursor": queried["next_cursor"],
        },
    )
    assert [queried["items"][0]["id"], second["items"][0]["id"]] == [
        "aoe_pattern.total",
        "combo.total",
    ]
    with pytest.raises(ParameterError, match="does not match"):
        workbench.model_action(
            "model.query",
            {
                "revision": revision,
                "kind": ["input"],
                "limit": 1,
                "cursor": queried["next_cursor"],
            },
        )
    with pytest.raises(StaleRevisionError):
        workbench.model_action(
            "model.get",
            {"revision": "0" * 64, "id": "combo.total", "kind": "output"},
        )
    combo_path = example_workspace / "entries" / "组合模型.kirin"
    changed = combo_path.read_text(encoding="utf-8").replace(
        "probability = 0.10", "probability = 0.11"
    )
    with pytest.raises(StaleRevisionError):
        workbench.model_action(
            "model.get",
            {"revision": revision, "id": "combo.total", "kind": "output"},
            {"entries/组合模型.kirin": changed},
        )

    selected = workbench.model_action(
        "model.get",
        {"revision": revision, "id": "combo.total", "kind": "output"},
    )["descriptor"]
    assert selected["dependencies"] == [
        "combo.crit",
        "skill_a.expected",
        "skill_b.expected",
    ]
    dependency_graph = workbench.model_action(
        "model.dependencies",
        {
            "revision": revision,
            "id": "combo.total",
            "kind": "output",
            "depth": 2,
        },
    )
    assert {edge["source"] for edge in dependency_graph["edges"]} >= {
        "combo.crit",
        "skill_a.expected",
        "skill_b.expected",
    }
    document = workbench.model_action(
        "model.document",
        {"revision": revision, "id": "combo"},
    )
    assert document["document"]["kind"] == "entry"
    assert {item["kind"] for item in document["descriptors"]} >= {
        "entry",
        "input",
        "output",
        "static_chart",
    }
    capabilities = workbench.model_action(
        "model.capabilities", {"revision": revision}
    )
    assert capabilities["actions"]["model.query"]["handler"] == "catalog"
    assert capabilities["limits"]["max_model_query_limit"] == 100


def test_catalog_materializes_static_structured_and_nested_descriptor_kinds(
    example_workspace: Path,
) -> None:
    (example_workspace / "entries" / "catalog_shapes.kirin").write_text(
        '''@kirin 2
@entry catalog_shapes "Catalog shapes"

dimension catalog_amount
unit catalog_amount = catalog_amount
domain catalog_rank: dimensionless in 1..3 integer

source evidence:
  kind = "note"
  citation = "Catalog fixture"

type tuning:
  multiplier: dimensionless = 1

type ability:
  amount: catalog_amount
  tuning: tuning

ability sample:
  amount = 10
  tuning:
    multiplier = 3/2

input rank: catalog_rank = 2
field base: catalog_amount = 10
function scale(n: dimensionless): catalog_amount = base * n

table coefficients:
  input = dimensionless
  output = dimensionless
  points:
    1 = 1
    3 = 2

distribution roll: catalog_amount:
  outcomes:
    - 0 @ 1/2
    - 10 @ 1/2

output result: catalog_amount = scale(interpolate(coefficients, rank))

group summary "Summary":
  - result

preset high "High":
  catalog_shapes.rank = 3

chart preview "Preview":
  x = catalog_shapes.rank
  range = 1..3
  points = 3
  y:
    - catalog_shapes.result
''',
        encoding="utf-8",
    )
    rotation = example_workspace / "entries" / "循环分析.kirin"
    rotation.write_text(
        rotation.read_text(encoding="utf-8").replace(
            "  state mana: mana = maximum_mana in 0..maximum_mana\n",
            "  event input tick()\n"
            "  state mana: mana = maximum_mana in 0..maximum_mana\n",
        ).replace(
            "  action arcane_blast:\n",
            "  variant cheap:\n"
            "    actor.blast_cost = 5 mana\n\n"
            "  action arcane_blast:\n",
        ).replace(
            "  bounds:\n",
            "  objective maximize_ending:\n"
            "    maximize ending_mana\n\n"
            "  bounds:\n",
        ).rstrip()
        + '''
  chart mana_trace "Mana trace":
    kind = trajectory
    series:
      - actor.current_mana
''',
        encoding="utf-8",
    )

    catalog = ModelCatalog(Workbench(example_workspace).workspace())
    actual = {item["kind"] for item in catalog.descriptors}
    expected = {
        "dimension", "unit", "domain", "source", "type", "type_field", "object",
        "object_field", "input", "field", "function", "table", "distribution",
        "output", "group", "preset", "static_chart", "process", "process_input",
        "process_state", "process_event", "process_action", "process_observe", "scenario",
        "scenario_instance", "scenario_variant", "scenario_policy", "scenario_decision",
        "scenario_measure", "scenario_objective", "analysis", "analysis_chart",
    }
    assert actual >= expected
    nested = next(
        item
        for item in catalog.descriptors
        if item["id"] == "catalog_shapes.sample.tuning.multiplier"
    )
    assert nested["kind"] == "object_field"
    assert nested["payload"]["field_path"] == ["tuning", "multiplier"]


def test_catalog_pages_past_the_old_snapshot_limit_without_source_disclosure(
    tmp_path: Path,
) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _large_interface_package(tmp_path / "package")
    add_path_package(workspace, "large", package)
    workbench = Workbench(workspace)
    summary = workbench.bootstrap()["catalog"]
    revision = summary["revision"]

    assert summary["counts"]["entry"] == 275
    assert summary["interfaces"][0]["id"] == "fictional.large-model"
    assert str(tmp_path) not in json.dumps(summary)
    cursor = None
    items = []
    while True:
        page = workbench.model_action(
            "model.query",
            {
                "revision": revision,
                "kind": ["entry"],
                "interface": "fictional.large-model",
                "interface_revision": 3,
                "limit": 100,
                "cursor": cursor,
            },
        )
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(items) == 275
    assert len({item["id"] for item in items}) == 275
    assert [item["id"] for item in items] == sorted(item["id"] for item in items)
    assert all(item["interfaces"] == [{"id": "fictional.large-model", "revision": 3}] for item in items)
    rendered = json.dumps(items)
    assert str(tmp_path) not in rendered
    assert "raw_text" not in rendered
    assert "@kirin" not in rendered

    catalog = ModelCatalog(workbench.workspace())
    assert catalog.revision == revision
