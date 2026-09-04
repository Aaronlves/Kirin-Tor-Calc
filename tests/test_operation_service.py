from __future__ import annotations

from pathlib import Path

import pytest

from kirin_tor.errors import (
    InvalidRequestError,
    LimitExceededError,
    StaleRevisionError,
    UnknownIdentityError,
)
from kirin_tor.model_catalog import model_revision
from kirin_tor.operation_service import PluginOperationService
from kirin_tor.operations import evaluate, evaluate_many
from kirin_tor.engine import Engine
from kirin_tor.workspace import Workspace


def test_evaluate_many_matches_individual_evaluation_with_one_shared_engine(
    example_workspace: Path,
) -> None:
    workspace = Workspace.load(example_workspace)
    targets = ["combo.total", "aoe_pattern.total"]
    result = evaluate_many(Engine(workspace), targets)

    assert [item["target"] for item in result["results"]] == targets
    assert [item["exact"] for item in result["results"]] == [
        evaluate(Engine(workspace), target)["exact"] for target in targets
    ]
    assert result["targets"] == targets


def test_plugin_operation_service_enforces_revision_identity_and_host_controls(
    example_workspace: Path,
) -> None:
    workspace = Workspace.load(example_workspace)
    service = PluginOperationService(workspace)
    result = service.execute(
        "evaluate-many",
        {
            "revision": service.revision,
            "targets": ["combo.total", "aoe_pattern.total"],
            "overrides": {"combo.crit": "50%"},
        },
    )

    assert result["operation"] == "evaluate-many"
    assert result["revision"] == model_revision(workspace)
    assert result["applied"]["overrides"] == {"combo.crit": "1/2"}
    assert result["result"]["results"][0]["exact"] == "3300"
    assert result["result"]["results"][1]["target"] == "aoe_pattern.total"
    assert len(result["operation_id"]) == 32
    assert result["provenance"]["targets"][0]["origin"]["scope"] == "workspace"

    with pytest.raises(StaleRevisionError):
        service.execute(
            "evaluate",
            {"revision": "0" * 64, "target": "combo.total"},
        )
    with pytest.raises(UnknownIdentityError):
        service.execute(
            "evaluate",
            {"revision": service.revision, "target": "combo.missing"},
        )
    with pytest.raises(InvalidRequestError, match="unknown request field"):
        service.execute(
            "evaluate",
            {
                "revision": service.revision,
                "target": "combo.total",
                "precision": 100,
            },
        )
    with pytest.raises(InvalidRequestError, match="job execution"):
        service.execute(
            "analyze",
            {"revision": service.revision, "target": "rotation_analysis.simulation"},
        )


def test_plugin_operation_service_rejects_published_limits(
    example_workspace: Path,
) -> None:
    service = PluginOperationService(Workspace.load(example_workspace))
    with pytest.raises(InvalidRequestError, match="unique"):
        service.execute(
            "evaluate-many",
            {
                "revision": service.revision,
                "targets": ["combo.total", "combo.total"],
            },
        )
    with pytest.raises(LimitExceededError, match="total points"):
        service.execute(
            "grid",
            {
                "revision": service.revision,
                "target": "aoe_pattern.total",
                "x": "aoe_pattern.bonus",
                "x_range": "0:1",
                "x_points": 101,
                "y": "aoe_pattern.targets",
                "y_range": "1:100",
                "y_points": 100,
            },
        )
