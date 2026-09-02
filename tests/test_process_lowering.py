from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import re

import pytest

from kirin_tor.errors import ExpressionError, SchemaError, SourceLocation
from kirin_tor.kirin_syntax import parse_kirin_source
from kirin_tor.process_ir import (
    EventIdScheduleKeyIR,
    LetEffectIR,
    NextEffectIR,
    NumberTypeIR,
    ScheduleEffectIR,
    SymbolicTypeIR,
    SymbolRefIR,
)
from kirin_tor.process_lowering import lower_process_asts
from kirin_tor.process_model import EventDirection, ExpressionSymbolKind, Reducer
from kirin_tor.process_parser import parse_process_asts
from kirin_tor.units import DomainSpec, UnitRegistry


PROCESS_SOURCE = """@kirin 2
@entry combat

process delayed_damage "伤害延迟池":
  input maximum_health: health
  input conversion: probability = 80%
  state health: health = maximum_health in 0..maximum_health
  state pool: damage = 0 damage in 0..30000
  key pool_tick
  phase periodic_tick
  event input incoming_damage(amount: damage reduce sum)
  event internal stagger_tick()
  action purify() when pool > 0 damage

  on incoming_damage(amount):
    let delayed: damage = amount * conversion
    next health = max(0 health, health - (amount - delayed))
    next pool = pool + delayed
    replace stagger_tick() after 1/2 second phase periodic_tick key event.id

  on purify():
    let cleared: damage = pool * 50%
    next pool = pool - cleared

  observe alive: boolean = health > 0 health
"""


def _registry() -> UnitRegistry:
    registry = UnitRegistry()
    location = SourceLocation(path="semantics.kirin")
    registry.add_dimension("vitality", {}, location)
    registry.add_unit(
        "health", {"vitality": Fraction(1)}, Fraction(1), location
    )
    registry.add_unit(
        "damage", {"vitality": Fraction(1)}, Fraction(1), location
    )
    return registry


def test_process_block_parser_and_lowerer_build_typed_ir() -> None:
    path = Path("combat.kirin")
    processes = parse_process_asts(PROCESS_SOURCE, path)

    assert len(processes) == 1
    source = processes[0]
    assert source.qualified_id == "combat.delayed_damage"
    assert source.location is not None
    assert source.location.line == 4
    assert source.events[0].direction is EventDirection.INPUT
    assert source.events[0].parameters[0].reducer is Reducer.SUM
    assert source.states[0].bound is not None
    assert source.states[0].bound.maximum.text == "maximum_health"

    process = lower_process_asts(processes, _registry())[0]
    assert process.qualified_id == "combat.delayed_damage"
    assert isinstance(process.states[0].value_type, NumberTypeIR)
    assert process.states[0].value_type.unit_name == "health"
    assert process.events[0].parameters[0].reducer is Reducer.SUM
    assert process.inputs[1].default.source == "(80 / 100)"
    incoming = process.handlers[0]
    assert incoming.parameter_symbols[0].id == "amount"
    assert [type(effect) for effect in incoming.effects] == [
        LetEffectIR,
        NextEffectIR,
        NextEffectIR,
        ScheduleEffectIR,
    ]
    scheduled = incoming.effects[-1]
    assert isinstance(scheduled, ScheduleEffectIR)
    assert isinstance(scheduled.key, EventIdScheduleKeyIR)
    assert scheduled.phase.member_id == "periodic_tick"
    assert scheduled.delay.source == "(1/2 * second)"
    assert scheduled.delay.references[0].id == "second"


def test_public_raw_parser_still_rejects_process_until_renderer_can_preserve_it() -> None:
    with pytest.raises(SchemaError, match="unknown v2 declaration"):
        parse_kirin_source(PROCESS_SOURCE, Path("combat.kirin"))


@pytest.mark.parametrize(
    ("replacement", "error", "message"),
    [
        (
            "state pool: damage = 0 damage in 0..30000",
            "state conversion: damage = 0 damage",
            "duplicate process value",
        ),
        (
            "event input incoming_damage(amount: damage reduce sum)",
            "event input incoming_damage(amount: boolean reduce sum)",
            "requires a numeric parameter",
        ),
        (
            "replace stagger_tick() after 1/2 second phase periodic_tick key event.id",
            "replace stagger_tick() after 1/2 second phase missing key event.id",
            "unknown phase",
        ),
    ],
)
def test_process_lowering_rejects_invalid_members_reducers_and_phases(
    replacement: str, error: str, message: str
) -> None:
    source = PROCESS_SOURCE.replace(replacement, error)
    processes = parse_process_asts(source, Path("invalid.kirin"))
    with pytest.raises(SchemaError, match=message):
        lower_process_asts(processes, _registry())


def test_process_lowering_rejects_undeclared_expression_values() -> None:
    source = PROCESS_SOURCE.replace("pool + delayed", "pool + missing_value")
    processes = parse_process_asts(source, Path("invalid.kirin"))
    with pytest.raises(ExpressionError, match="undeclared process value 'missing_value'"):
        lower_process_asts(processes, _registry())


def test_process_parser_rejects_unbounded_or_malformed_collection_types() -> None:
    source = PROCESS_SOURCE.replace(
        "state pool: damage = 0 damage in 0..30000",
        "state pool: map[event_id,time,unbounded] = empty",
    )
    with pytest.raises(SchemaError, match="map capacity must be an integer literal"):
        parse_process_asts(source, Path("invalid.kirin"))


def test_all_documented_paper_processes_parse_with_the_frozen_surface_grammar() -> None:
    project_root = Path(__file__).resolve().parents[1]
    document = (project_root / "docs" / "bounded-process-paper-models.md").read_text(
        encoding="utf-8"
    )
    parsed_processes = []
    for index, block in enumerate(re.findall(r"```text\n(.*?)```", document, re.DOTALL)):
        if not re.search(r"(?m)^process [a-z_][A-Za-z0-9_]*(?:\s|:)", block):
            continue
        source = f"@kirin 2\n@entry paper_{index}\n\n{block}"
        parsed_processes.extend(
            parse_process_asts(source, Path(f"paper-model-{index}.kirin"))
        )

    assert [process.id for process in parsed_processes] == [
        "combat_resources",
        "delayed_damage",
        "sequential_charges",
        "periodic_damage",
        "priority_shields",
        "proportional_shields",
        "independent_stacks",
        "refreshing_stacks",
        "proc_combat",
    ]
    periodic = next(
        process for process in parsed_processes if process.id == "periodic_damage"
    )
    target_health = next(state for state in periodic.states if state.id == "target_health")
    assert target_health.bound is not None
    assert target_health.bound.maximum.text == "1000 health"
    stacks = next(
        process for process in parsed_processes if process.id == "independent_stacks"
    )
    assert stacks.states[0].value_type.name == "map"
    assert stacks.states[0].value_type.capacity == 100

    registry = _registry()
    location = SourceLocation(path="paper-semantics.kirin")
    registry.add_dimension("mana", {}, location)
    registry.add_dimension("rage", {}, location)
    registry.add_unit("mana", {"mana": Fraction(1)}, Fraction(1), location)
    registry.add_unit("rage", {"rage": Fraction(1)}, Fraction(1), location)
    registry.add_unit(
        "mana_per_time",
        {"mana": Fraction(1), "time": Fraction(-1)},
        Fraction(1),
        location,
    )
    registry.domains["dot_mode"] = DomainSpec(
        "dot_mode", value_type="symbolic", allowed_values=("snapshot", "dynamic")
    )
    dot_mode = SymbolicTypeIR("dot_mode")
    static_symbols = {
        value: SymbolRefIR(
            "@domain.dot_mode",
            value,
            ExpressionSymbolKind.STATIC_MEMBER,
            dot_mode,
        )
        for value in ("snapshot", "dynamic")
    }
    lowered = lower_process_asts(
        parsed_processes, registry, static_symbols=static_symbols
    )
    assert [process.id for process in lowered] == [
        process.id for process in parsed_processes
    ]
