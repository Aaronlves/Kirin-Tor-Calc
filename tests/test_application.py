from __future__ import annotations

from pathlib import Path

from kirin_tor.application import (
    ComparisonVariant,
    build_workspace_index,
    compare_variants,
    parse_player_override_text,
    parse_override_text,
    scan_variant_comparison,
)
from kirin_tor.workspace import Workspace, build_document_draft, create_entry_template, initialize


def test_cli_and_tui_share_one_document_draft_builder(tmp_path: Path) -> None:
    root = initialize(tmp_path / "workspace")
    workspace = Workspace.load(root)
    expected = build_document_draft(
        root, "entry", "shared_model", entry_template="model"
    )

    created = create_entry_template(workspace, "model", "shared_model")

    assert created == expected.path
    assert created.read_text(encoding="utf-8") == expected.source_text


def test_player_override_text_and_workspace_index(example_workspace: Path) -> None:
    overrides = parse_override_text("combo.crit=1/4, character.attack_power=3000\nflag=true")
    assert overrides == {
        "combo.crit": "1/4",
        "character.attack_power": "3000",
        "flag": "true",
    }

    index = build_workspace_index(Workspace.load(example_workspace))
    assert any(
        item.value == "combo.total"
        and item.label == "组合期望伤害"
        and item.inputs == ("combo.crit",)
        for item in index.targets
    )
    assert any(item.value == "combo.crit" and item.label == "暴击率" for item in index.inputs)
    assert any(item.value == "presets.baseline" for item in index.presets)
    assert parse_player_override_text("暴击率=25%", index.inputs) == {"combo.crit": "1/4"}


def test_comparison_keeps_one_workspace_revision_and_reports_differences(
    example_workspace: Path,
) -> None:
    result = compare_variants(
        Workspace.load(example_workspace),
        "combo.total",
        [
            ComparisonVariant("基准", "baseline", {}),
            ComparisonVariant("高暴击", None, {"combo.crit": "1/2"}),
            ComparisonVariant("错误方案", None, {"combo.crit": "2"}),
        ],
    )

    assert result["status"] == "partial"
    assert result["variants"][0]["result"]["exact"] == "2750"
    assert result["variants"][1]["result"]["exact"] == "3300"
    assert result["variants"][1]["delta_exact"] == "550"
    assert result["variants"][1]["delta_percent"] == "20.0000000000"
    assert result["variants"][2]["status"] == "error"
    assert result["variants"][2]["error"]["code"] == "parameter_error"


def test_variant_chart_scans_player_presets_on_one_axis(example_workspace: Path) -> None:
    result = scan_variant_comparison(
        Workspace.load(example_workspace),
        "aoe_pattern.targets",
        "1:6",
        6,
        "aoe_pattern.total",
        [
            ComparisonVariant("开启天赋"),
            ComparisonVariant("关闭天赋", "no_talent"),
        ],
    )

    assert result["operation"] == "scan_compare"
    assert result["labels"] == {
        "variant_1": "开启天赋",
        "variant_2": "关闭天赋",
    }
    third_point = result["rows"][2]["values"]
    assert third_point["variant_1"]["exact"] == "390"
    assert third_point["variant_2"]["exact"] == "300"

    partial = scan_variant_comparison(
        Workspace.load(example_workspace),
        "aoe_pattern.targets",
        "1:3",
        3,
        "aoe_pattern.total",
        [
            ComparisonVariant("正常"),
            ComparisonVariant("错误参数", None, {"aoe_pattern.bonus": "2"}),
        ],
    )
    assert partial["status"] == "partial"
    assert partial["valid_points"] == {"variant_1": 3, "variant_2": 0}
    assert partial["rows"][0]["values"]["variant_1"]["error"] is None
    assert partial["rows"][0]["values"]["variant_2"]["error"] is not None
