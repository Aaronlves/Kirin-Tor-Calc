from __future__ import annotations

from pathlib import Path

from kirin_tor.engine import Engine
from kirin_tor.operations import evaluate, scan_values
from kirin_tor.workspace import Workspace, initialize


def _build_wow_mechanics_workspace(root: Path) -> Path:
    root = initialize(root)
    (root / "entries" / "fixture_game_semantics.kirin").write_text(
        """@kirin 1
@entry fixture_game_semantics

// Test-owned fictional game semantics; not supplied by the Kirin core.

dimensions:
  damage
  armor

units:
  damage = damage
  armor = armor
  damage_per_time = damage / time
""",
        encoding="utf-8",
    )
    (root / "entries" / "combat_math.kirin").write_text(
        """@kirin 1
@entry combat_math
@game-version representative
@status capability_test

// 魔兽世界式机制的抽象能力测试；数值为虚构测试数据。

units:
  per_time = 1 / time

inputs:
  crit "暴击率": probability = 0.25
  target_health "目标生命比例": probability = 1
  targets "目标数量": nonnegative_integer = 1 in 1..20
  haste "急速": number[dimensionless] = 0.25 in 0..3
  duration "持续时间": number[time] = 12 in 0..60
  charges "充能数": nonnegative_integer = 2 in 1..5
  proc_chance "触发概率": probability = 0.10
  attempt_rate "每秒触发机会": number[per_time] = 2 in 0..100
  armor_value "目标护甲": number[armor] = 1000 in 0..1000000
  stacks "层数": nonnegative_integer = 7 in 0..20

fields:
  hit: damage = 1000
  crit_multiplier: dimensionless = 2
  execute_multiplier: dimensionless = 23/20
  dot_tick: damage = 100
  tick_interval: time = 2
  cooldown: time = 30
  proc_damage: damage = 500
  armor_constant: armor = 1000
  bounce_decay: dimensionless = 1/2

outputs:
  expected_hit "单次期望伤害": damage =
    hit * (1 + crit * (crit_multiplier - 1))
  execute_hit "斩杀阶段期望伤害": damage =
    expected_hit * if_else(target_health < 0.30, execute_multiplier, 1)
  aoe_total "软上限范围伤害": damage =
    piecewise(
    targets <= 5, expected_hit * targets,
    expected_hit * (5 + sqrt(targets - 5))
    )
  periodic_total "急速后的周期总伤害": damage =
    dot_tick * floor(duration / (tick_interval / (1 + haste)))
  charge_dps "充能等效秒伤": damage_per_time =
    expected_hit * charges / cooldown
  proc_dps "触发效果等效秒伤": damage_per_time =
    proc_damage * proc_chance * attempt_rate
  mitigated_hit "护甲减伤后伤害": damage =
    expected_hit * armor_constant / (armor_value + armor_constant)
  capped_stack_multiplier "封顶层数倍率": dimensionless =
    1 + min(stacks, 4) / 20
  expected_bounce_total "递减弹射总伤害": damage =
    sum(hit * bounce_decay ** i, i, 0, 3)
""",
        encoding="utf-8",
    )
    return root


def test_wow_like_expected_and_equivalent_mechanics_are_expressible(
    tmp_path: Path,
) -> None:
    root = _build_wow_mechanics_workspace(tmp_path / "wow-mechanics")
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"

    expected = {
        "combat_math.expected_hit": "1250",
        "combat_math.execute_hit": "1250",
        "combat_math.aoe_total": "1250",
        "combat_math.periodic_total": "700",
        "combat_math.charge_dps": "250/3",
        "combat_math.proc_dps": "100",
        "combat_math.mitigated_hit": "625",
        "combat_math.capped_stack_multiplier": "6/5",
        "combat_math.expected_bounce_total": "1875",
    }
    for target, exact in expected.items():
        assert evaluate(Engine(Workspace.load(root)), target)["exact"] == exact

    execute = evaluate(
        Engine(Workspace.load(root)),
        "combat_math.execute_hit",
        overrides={"combat_math.target_health": "1/5"},
    )
    assert execute["exact"] == "2875/2"


def test_wow_like_target_scaling_can_be_scanned_without_simulation(
    tmp_path: Path,
) -> None:
    root = _build_wow_mechanics_workspace(tmp_path / "wow-scan")
    scan = scan_values(
        Engine(Workspace.load(root)),
        "combat_math.targets",
        "1:9",
        9,
        ["combat_math.aoe_total"],
    )

    values = [row["values"]["combat_math.aoe_total"]["exact"] for row in scan["rows"]]
    assert values[:5] == ["1250", "2500", "3750", "5000", "6250"]
    assert values[-1] == "8750"
