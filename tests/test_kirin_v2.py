from __future__ import annotations

from pathlib import Path
import json

import pytest

from kirin_tor.engine import Engine
from kirin_tor.errors import DomainError, ReferenceError, SchemaError, UnitError, ValidationErrors
from kirin_tor.cli import app
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.operations import analyze_cycle, evaluate
from kirin_tor.workspace import Workspace, initialize
from kirin_tor.workbench import Workbench

from conftest import make_cli_runner


runner = make_cli_runner()


SOURCE = """@kirin 2
@entry rotation "循环模型"

dimension resource "资源"
unit resource = resource
unit resource_per_time = resource / time

type skill:
  cost: resource
  occupies: time
  cycle_step:
    cost = cost
    occupies = occupies

type profile:
  initial: resource
  maximum: resource
  regeneration: resource_per_time
  cycle_profile:
    initial = initial
    maximum = maximum
    regeneration = regeneration

input haste "急速": probability = 0 in 0..1

skill burn "消耗技能":
  cost = 60
  occupies = 2 second / (1 + haste)

skill balanced "平衡技能":
  cost = 20
  occupies = 2 second

skill impossible "超过上限":
  cost = 120
  occupies = 1 second

profile static "无法回复":
  initial = 50
  maximum = 100
  regeneration = 0

profile standard "默认角色":
  initial = 100
  maximum = 100
  regeneration = 10

cycle waiting "需要等待":
  using = standard
  sequence:
    - burn
    - burn

cycle continuous "无需等待":
  using = standard
  sequence:
    - balanced

cycle exceeds_maximum "超过资源上限":
  using = standard
  sequence:
    - impossible

cycle cannot_recover "资源无法回复":
  using = static
  sequence:
    - burn

output burn_cost "技能消耗": resource = burn.cost
output minute_fraction: dimensionless = 25%
"""


MULTI_RESOURCE_SOURCE = """@kirin 2
@entry vector_rotation "多资源循环"

dimension mana
dimension energy
dimension charge
unit mana = mana
unit energy = energy
unit charge = charge
unit mana_per_time = mana / time
unit energy_per_time = energy / time
unit charge_per_time = charge / time

type skill:
  mana_cost: mana = 0
  energy_cost: energy = 0
  charge_cost: charge = 0
  charge_gain: charge = 0
  occupies: time
  cycle_step:
    occupies = occupies
    spends:
      mana = mana_cost
      energy = energy_cost
      charge = charge_cost
    gains:
      charge = charge_gain

type profile:
  mana_initial: mana
  mana_maximum: mana
  mana_regeneration: mana_per_time
  energy_initial: energy
  energy_maximum: energy
  energy_regeneration: energy_per_time
  charge_initial: charge
  charge_maximum: charge
  charge_regeneration: charge_per_time
  cycle_profile:
    resources:
      mana:
        initial = mana_initial
        maximum = mana_maximum
        regeneration = mana_regeneration
      energy:
        initial = energy_initial
        maximum = energy_maximum
        regeneration = energy_regeneration
      charge:
        initial = charge_initial
        maximum = charge_maximum
        regeneration = charge_regeneration

skill generator "生成技能":
  mana_cost = 30
  energy_cost = 20
  charge_gain = 1
  occupies = 1 second

skill finisher "终结技能":
  charge_cost = 2
  occupies = 1 second

skill dual_burn "双资源消耗":
  mana_cost = 60
  energy_cost = 30
  occupies = 1 second

profile character "角色状态":
  mana_initial = 100
  mana_maximum = 100
  mana_regeneration = 10
  energy_initial = 40
  energy_maximum = 100
  energy_regeneration = 5
  charge_initial = 0
  charge_maximum = 4
  charge_regeneration = 0

cycle generated "生成后消耗":
  using = character
  sequence:
    - generator
    - generator
    - finisher

cycle insufficient_charge "层数不足":
  using = character
  sequence:
    - generator
    - finisher

cycle joint_wait "联合等待":
  using = character
  sequence:
    - dual_burn
    - dual_burn
"""


READINESS_SOURCE = """@kirin 2
@entry readiness_rotation "冷却与充能循环"

dimension resource
unit resource = resource
unit resource_per_time = resource / time

type cooldown_skill:
  cost: resource = 0
  occupies: time
  cooldown: time = 0 second
  cycle_step:
    occupies = occupies
    cooldown = cooldown
    spends:
      resource = cost

type charged_skill:
  occupies: time
  maximum_charges: positive_integer
  recharge: time
  cycle_step:
    occupies = occupies
    charges:
      maximum = maximum_charges
      recharge = recharge

type profile:
  initial: resource
  maximum: resource
  regeneration: resource_per_time
  cycle_profile:
    resources:
      resource:
        initial = initial
        maximum = maximum
        regeneration = regeneration

cooldown_skill burst "爆发技能":
  cost = 1
  occupies = 1 second
  cooldown = 5 second

cooldown_skill filler "填充技能":
  occupies = 2 second

charged_skill charged_strike "充能打击":
  occupies = 1 second
  maximum_charges = 2
  recharge = 5 second

charged_skill quick_strike "快速充能打击":
  occupies = 1 second
  maximum_charges = 1
  recharge = 1 second

profile character "角色状态":
  initial = 1
  maximum = 1
  regeneration = 1/4

cycle cooldown_wait "冷却等待":
  using = character
  sequence:
    - burst
    - filler

cycle cooldown_ready "冷却自然完成":
  using = character
  sequence:
    - burst
    - filler
    - filler

cycle charge_wait "充能等待":
  using = character
  sequence:
    - charged_strike
    - readiness_rotation.charged_strike

cycle charge_ready "充能自然完成":
  using = character
  sequence:
    - quick_strike
"""


def _workspace(tmp_path: Path) -> Workspace:
    root = initialize(tmp_path / "workspace")
    (root / "entries" / "rotation.kirin").write_text(SOURCE, encoding="utf-8")
    return Workspace.load(root)


def test_v2_typed_objects_nested_paths_and_literals(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    assert Engine(workspace).validate_all()["status"] == "ok"
    assert evaluate(Engine(workspace), "rotation.burn.cost")["exact"] == "60"
    assert evaluate(Engine(workspace), "rotation.burn_cost")["exact"] == "60"
    assert evaluate(Engine(workspace), "rotation.minute_fraction")["exact"] == "1/4"


def test_v2_cycle_reports_wait_and_continuous_cases(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    waiting = analyze_cycle(Engine(workspace), "rotation.waiting")
    assert waiting["cycle_status"] == "waiting"
    assert waiting["first_wait"]["step"] == 3
    assert waiting["first_wait"]["cycle"] == 2
    assert waiting["first_wait"]["position"] == 1
    assert waiting["first_wait"]["action"] == "burn"
    assert waiting["first_wait"]["duration"] == "4"
    assert waiting["first_wait"]["resource"] == "20"
    assert waiting["first_wait"]["limiting_resources"] == ["resource"]
    assert waiting["wait_per_cycle"] == "8"
    assert waiting["wait_per_minute"] == "40"
    assert waiting["cycle_duration"] == "12"

    continuous = analyze_cycle(Engine(workspace), "rotation.continuous")
    assert continuous["cycle_status"] == "continuous"
    assert continuous["cycle_duration"] == "2"

    exceeds = analyze_cycle(Engine(workspace), "rotation.exceeds_maximum")
    assert exceeds["cycle_status"] == "blocked"
    assert exceeds["blocked_at"]["step"] == 1
    assert exceeds["blocked_at"]["reason"] == "cost_exceeds_maximum"

    exhausted = analyze_cycle(Engine(workspace), "rotation.cannot_recover")
    assert exhausted["cycle_status"] == "blocked"
    assert exhausted["blocked_at"]["step"] == 1
    assert exhausted["blocked_at"]["reason"] == "resource_cannot_recover"

    faster = analyze_cycle(
        Engine(workspace), "rotation.waiting", overrides={"rotation.haste": "1/2"}
    )
    assert faster["parameters"]["rotation.haste"] == "1/2"
    assert faster["first_wait"]["step"] == 2
    assert faster["first_wait"]["duration"] == "2/3"


def test_v2_multi_resource_cycle_spends_gains_waits_and_blocks(
    tmp_path: Path, monkeypatch
) -> None:
    root = initialize(tmp_path / "multi-resource")
    path = root / "entries" / "vector_rotation.kirin"
    path.write_text(MULTI_RESOURCE_SOURCE, encoding="utf-8")
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"

    result = analyze_cycle(Engine(workspace), "vector_rotation.generated")
    assert result["cycle_status"] == "waiting"
    assert result["resource_count"] == 3
    assert result["resource_units"] == {
        "charge": "charge",
        "energy": "energy",
        "mana": "mana",
    }
    assert result["first_wait"]["step"] == 4
    assert result["first_wait"]["duration"] == "1"
    assert result["first_wait"]["limiting_resources"] == ["energy"]
    assert result["first_wait"]["resource_failures"] == [
        {
            "resource": "energy",
            "available": "15",
            "required": "20",
            "unit": "energy",
        }
    ]

    blocked = analyze_cycle(
        Engine(workspace), "vector_rotation.insufficient_charge"
    )
    assert blocked["cycle_status"] == "blocked"
    assert blocked["blocked_at"]["step"] == 2
    assert blocked["blocked_at"]["reason"] == "resource_cannot_recover"
    assert blocked["blocked_at"]["resource_id"] == "charge"

    joint = analyze_cycle(Engine(workspace), "vector_rotation.joint_wait")
    assert joint["cycle_status"] == "waiting"
    assert joint["first_wait"]["step"] == 2
    assert joint["first_wait"]["duration"] == "3"
    assert joint["first_wait"]["limiting_resources"] == ["energy"]
    assert [
        failure["resource"] for failure in joint["first_wait"]["resource_failures"]
    ] == ["energy", "mana"]

    raw, _text, _digest, _positions = load_kirin_document(path)
    rendered = render_kirin_document(raw)
    assert "    resources:\n      mana:\n        initial = mana_initial" in rendered
    assert "    spends:\n      mana = mana_cost" in rendered
    rendered_path = root / "entries" / "rendered.kirin"
    rendered_path.write_text(
        rendered.replace("@entry vector_rotation", "@entry vector_rendered", 1),
        encoding="utf-8",
    )
    rendered_raw, _text, _digest, _positions = load_kirin_document(rendered_path)
    assert rendered_raw["types"] == raw["types"]

    rendered_path.unlink()
    monkeypatch.chdir(root)
    saved = runner.invoke(
        app,
        ["cycle", "vector_rotation.generated", "--save-run", "multi", "--json"],
    )
    assert saved.exit_code == 0, saved.output
    replayed = runner.invoke(app, ["replay", "multi", "--json"])
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.stdout)["matches_recorded_result"] is True


def test_v2_cycle_cooldowns_and_sequential_charges_share_the_timeline(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "readiness")
    (root / "entries" / "readiness_rotation.kirin").write_text(
        READINESS_SOURCE, encoding="utf-8"
    )
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"

    cooldown = analyze_cycle(
        Engine(workspace), "readiness_rotation.cooldown_wait"
    )
    assert cooldown["cycle_status"] == "waiting"
    assert cooldown["cooldown_action_count"] == 1
    assert cooldown["charge_action_count"] == 0
    assert cooldown["first_wait"]["step"] == 3
    assert cooldown["first_wait"]["duration"] == "2"
    assert cooldown["first_wait"]["resource_failures"] == [
        {
            "resource": "resource",
            "available": "3/4",
            "required": "1",
            "unit": "resource",
        }
    ]
    assert cooldown["first_wait"]["readiness_failures"] == [
        {
            "kind": "cooldown",
            "action": "burst",
            "remaining": "2",
            "unit": "second",
        }
    ]
    assert cooldown["first_wait"]["limiting_constraints"] == [
        "cooldown:burst"
    ]
    assert cooldown["wait_per_cycle"] == "2"

    cooldown_ready = analyze_cycle(
        Engine(workspace), "readiness_rotation.cooldown_ready"
    )
    assert cooldown_ready["cycle_status"] == "continuous"
    assert cooldown_ready["first_wait"] is None

    charges = analyze_cycle(Engine(workspace), "readiness_rotation.charge_wait")
    assert charges["cycle_status"] == "waiting"
    assert charges["cooldown_action_count"] == 0
    assert charges["charge_action_count"] == 1
    assert charges["first_wait"]["step"] == 3
    assert charges["first_wait"]["duration"] == "3"
    assert charges["first_wait"]["readiness_failures"] == [
        {
            "kind": "charge",
            "action": "charged_strike",
            "remaining": "3",
            "unit": "second",
            "available": 0,
            "required": 1,
        }
    ]
    assert charges["first_wait"]["limiting_constraints"] == [
        "charge:charged_strike"
    ]

    charge_ready = analyze_cycle(
        Engine(workspace), "readiness_rotation.charge_ready"
    )
    assert charge_ready["cycle_status"] == "continuous"
    assert charge_ready["first_wait"] is None


def test_v2_cycle_can_start_with_partially_empty_charges(tmp_path: Path) -> None:
    root = initialize(tmp_path / "initial-charges")
    source = READINESS_SOURCE.replace(
        "  maximum_charges: positive_integer\n",
        "  initial_charges: count\n  maximum_charges: positive_integer\n",
        1,
    ).replace(
        "    charges:\n      maximum = maximum_charges\n",
        "    charges:\n      initial = initial_charges\n      maximum = maximum_charges\n",
        1,
    ).replace(
        "  maximum_charges = 2\n",
        "  initial_charges = 0\n  maximum_charges = 2\n",
        1,
    )
    (root / "entries" / "rotation.kirin").write_text(source, encoding="utf-8")
    result = analyze_cycle(
        Engine(Workspace.load(root)), "readiness_rotation.charge_wait"
    )
    assert result["first_wait"]["step"] == 1
    assert result["first_wait"]["duration"] == "5"
    assert result["first_wait"]["limiting_constraints"] == [
        "charge:charged_strike"
    ]


def test_v2_cycle_charge_contract_and_values_are_bounded(tmp_path: Path) -> None:
    missing_root = initialize(tmp_path / "missing-recharge")
    (missing_root / "entries" / "rotation.kirin").write_text(
        READINESS_SOURCE.replace("      recharge = recharge\n", "", 1),
        encoding="utf-8",
    )
    with pytest.raises((SchemaError, ValidationErrors), match="missing role.*recharge"):
        Engine(Workspace.load(missing_root)).validate_all()

    noninteger_root = initialize(tmp_path / "noninteger-charges")
    (noninteger_root / "entries" / "rotation.kirin").write_text(
        READINESS_SOURCE.replace(
            "  maximum_charges: positive_integer\n",
            "  maximum_charges: dimensionless\n",
            1,
        ).replace("  maximum_charges = 2\n", "  maximum_charges = 3/2\n", 1),
        encoding="utf-8",
    )
    with pytest.raises((DomainError, ValidationErrors), match="charges.maximum must be an integer"):
        analyze_cycle(Engine(Workspace.load(noninteger_root)), "readiness_rotation.charge_wait")

    excessive_root = initialize(tmp_path / "excessive-charges")
    (excessive_root / "entries" / "rotation.kirin").write_text(
        READINESS_SOURCE.replace("  maximum_charges = 2\n", "  maximum_charges = 65\n", 1),
        encoding="utf-8",
    )
    with pytest.raises(DomainError, match="charges.maximum exceeds 64"):
        analyze_cycle(Engine(Workspace.load(excessive_root)), "readiness_rotation.charge_wait")


def test_v2_multi_resource_cycle_rejects_unknown_resources_and_wrong_units(
    tmp_path: Path,
) -> None:
    unknown_root = initialize(tmp_path / "unknown-resource")
    (unknown_root / "entries" / "rotation.kirin").write_text(
        MULTI_RESOURCE_SOURCE.replace(
            "      charge = charge_gain", "      combo = charge_gain", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises((SchemaError, ValidationErrors), match="undeclared resource.*combo"):
        Engine(Workspace.load(unknown_root)).validate_all()

    unit_root = initialize(tmp_path / "wrong-effect-unit")
    (unit_root / "entries" / "rotation.kirin").write_text(
        MULTI_RESOURCE_SOURCE.replace(
            "  energy_cost: energy = 0", "  energy_cost: mana = 0", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises((UnitError, ValidationErrors), match="effect for resource 'energy'"):
        Engine(Workspace.load(unit_root)).validate_all()


def test_v2_multi_resource_cycle_enforces_resource_limit(tmp_path: Path) -> None:
    resource_ids = [f"resource_{index}" for index in range(65)]
    profile_fields = "\n".join(
        line
        for resource_id in resource_ids
        for line in (
            f"  {resource_id}_initial: resource",
            f"  {resource_id}_maximum: resource",
            f"  {resource_id}_regeneration: resource_per_time",
        )
    )
    resource_mappings = "\n".join(
        line
        for resource_id in resource_ids
        for line in (
            f"      {resource_id}:",
            f"        initial = {resource_id}_initial",
            f"        maximum = {resource_id}_maximum",
            f"        regeneration = {resource_id}_regeneration",
        )
    )
    profile_values = "\n".join(
        line
        for resource_id in resource_ids
        for line in (
            f"  {resource_id}_initial = 0",
            f"  {resource_id}_maximum = 100",
            f"  {resource_id}_regeneration = 1",
        )
    )
    source = f"""@kirin 2
@entry too_many_resources

dimension resource
unit resource = resource
unit resource_per_time = resource / time

type action:
  occupies: time
  cycle_step:
    occupies = occupies

type profile:
{profile_fields}
  cycle_profile:
    resources:
{resource_mappings}

action idle:
  occupies = 1 second

profile character:
{profile_values}

cycle main:
  using = character
  sequence:
    - idle
"""
    root = initialize(tmp_path / "resource-limit")
    (root / "entries" / "limit.kirin").write_text(source, encoding="utf-8")
    with pytest.raises(SchemaError, match="exceeds 64 resources"):
        Engine(Workspace.load(root)).validate_all()


def test_v2_closed_objects_and_private_paths_fail(tmp_path: Path) -> None:
    source = SOURCE.replace(
        "  occupies = 2 second / (1 + haste)\n\nskill balanced",
        "  occupies = 2 second / (1 + haste)\n  typo = 1\n\nskill balanced",
        1,
    )
    root = initialize(tmp_path / "invalid")
    path = root / "entries" / "rotation.kirin"
    path.write_text(source, encoding="utf-8")
    workspace = Workspace.load(root)
    with pytest.raises(SchemaError, match="unknown field"):
        Engine(workspace).validate_all()
    with pytest.raises(ReferenceError, match="private"):
        Engine(workspace).resolve_target("rotation.burn.__class__")


def test_v2_renderer_round_trips_public_source(tmp_path: Path) -> None:
    path = tmp_path / "source.kirin"
    path.write_text(SOURCE, encoding="utf-8")
    raw, _text, _digest, _positions = load_kirin_document(path)
    rendered = render_kirin_document(raw)
    assert rendered.startswith('@kirin 2\n@entry rotation "循环模型"\n')
    rendered_path = tmp_path / "rendered.kirin"
    rendered_path.write_text(rendered, encoding="utf-8")
    rendered_raw, _text, _digest, _positions = load_kirin_document(rendered_path)
    assert rendered_raw == raw


def test_v2_cross_entry_nested_types_paths_and_aliases(tmp_path: Path) -> None:
    root = initialize(tmp_path / "nested")
    (root / "entries" / "definitions.kirin").write_text(
        """@kirin 2
@entry definitions

dimension damage
dimension resource
unit damage = damage
unit resource = resource

type coefficient:
  direct: damage
  periodic: damage

type skill:
  cost: resource
  coefficient: coefficient
""",
        encoding="utf-8",
    )
    (root / "entries" / "abilities.kirin").write_text(
        """@kirin 2
@entry abilities

definitions.skill arcane_blast "奥术冲击":
  cost = 30
  coefficient:
    direct = 1000
    periodic = 250
""",
        encoding="utf-8",
    )
    (root / "entries" / "summary.kirin").write_text(
        """@kirin 2
@entry summary

alias 周期伤害 = abilities.arcane_blast.coefficient.periodic
output dot: damage = 周期伤害
""",
        encoding="utf-8",
    )
    workspace = Workspace.load(root)
    assert Engine(workspace).validate_all()["status"] == "ok"
    result = evaluate(
        Engine(workspace), "abilities.arcane_blast.coefficient.periodic"
    )
    assert result["exact"] == "250"
    assert evaluate(Engine(workspace), "summary.dot")["exact"] == "250"


def test_v2_cycle_can_reference_separate_type_object_and_profile_entries(
    tmp_path: Path, monkeypatch
) -> None:
    root = initialize(tmp_path / "separate-cycle")
    (root / "entries" / "definitions.kirin").write_text(
        """@kirin 2
@entry definitions

dimension resource
unit resource = resource
unit resource_per_time = resource / time

type skill:
  cost: resource
  occupies: time
  cycle_step:
    cost = cost
    occupies = occupies

type profile:
  initial: resource
  maximum: resource
  regeneration: resource_per_time
  cycle_profile:
    initial = initial
    maximum = maximum
    regeneration = regeneration
""",
        encoding="utf-8",
    )
    (root / "entries" / "abilities.kirin").write_text(
        """@kirin 2
@entry abilities

definitions.skill arcane_blast "奥术冲击":
  cost = 60
  occupies = 2 second
""",
        encoding="utf-8",
    )
    (root / "entries" / "characters.kirin").write_text(
        """@kirin 2
@entry characters

definitions.profile mage "角色资源":
  initial = 100
  maximum = 100
  regeneration = 10
""",
        encoding="utf-8",
    )
    (root / "entries" / "rotation.kirin").write_text(
        """@kirin 2
@entry rotation

cycle main "主要循环":
  using = characters.mage
  sequence:
    - abilities.arcane_blast
    - abilities.arcane_blast
""",
        encoding="utf-8",
    )

    workspace = Workspace.load(root)
    result = analyze_cycle(Engine(workspace), "rotation.main")
    assert result["cycle_status"] == "waiting"
    assert result["first_wait"]["step"] == 3
    assert result["dependency_ids"] == [
        "abilities",
        "characters",
        "definitions",
        "rotation",
    ]

    monkeypatch.chdir(root)
    saved = runner.invoke(app, ["cycle", "rotation.main", "--save-run", "cross-entry", "--json"])
    assert saved.exit_code == 0, saved.output
    replayed = runner.invoke(app, ["replay", "cross-entry", "--json"])
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.stdout)["matches_recorded_result"] is True


def test_v2_cycle_cli_workbench_index_and_replay(tmp_path: Path, monkeypatch) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.chdir(workspace.root)
    result = runner.invoke(
        app,
        ["cycle", "rotation.waiting", "--save-run", "waiting-cycle", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["cycle_status"] == "waiting"
    assert payload["first_wait"]["step"] == 3

    replayed = runner.invoke(app, ["replay", "waiting-cycle", "--json"])
    assert replayed.exit_code == 0, replayed.output
    assert json.loads(replayed.stdout)["matches_recorded_result"] is True

    index = Workbench(workspace.root).bootstrap()["index"]
    assert any(item["value"] == "rotation.waiting" for item in index["cycles"])


def test_public_parser_rejects_v1(tmp_path: Path) -> None:
    root = initialize(tmp_path / "legacy")
    path = root / "entries" / "legacy.kirin"
    path.write_text(
        "@kirin 1\n@entry legacy\n\noutputs:\n  result: dimensionless = 1\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="@kirin 2"):
        Workspace.load(root)
