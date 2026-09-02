from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from fractions import Fraction

import pytest

from kirin_tor.process_ast import (
    BranchEffectAst,
    EventArgumentAst,
    EventAst,
    EventCallAst,
    EventParameterAst,
    ExpressionAst,
    HandlerAst,
    KeyAst,
    NextEffectAst,
    PhaseAst,
    ProbabilityCaseAst,
    ProcessAst,
    ScheduleEffectAst,
    StateAst,
    TypeAst,
    WhenEffectAst,
)
from kirin_tor.process_ir import (
    BooleanTypeIR,
    BoundIR,
    EventArgumentIR,
    EventCallIR,
    EventIdTypeIR,
    EventIR,
    EventParameterIR,
    HandlerIR,
    InputIR,
    MapTypeIR,
    NextEffectIR,
    NumberTypeIR,
    ProcessIR,
    ProcessMemberRefIR,
    StateIR,
    SymbolRefIR,
    TypedExpressionIR,
)
from kirin_tor.process_model import (
    BranchMode,
    EventDirection,
    ExpressionSymbolKind,
    ProcessMemberKind,
    Reducer,
    ScheduleOperation,
)
from kirin_tor.units import DIMENSIONLESS, Dimension


def test_process_source_ast_represents_nested_generic_effects_without_raw_mapping() -> None:
    damage = TypeAst("damage")
    process = ProcessAst(
        owner_id="combat",
        id="delayed_damage",
        states=(
            StateAst("pool", damage, ExpressionAst("0")),
        ),
        keys=(KeyAst("pool_tick"),),
        phases=(PhaseAst("tick"),),
        events=(
            EventAst(
                "incoming_damage",
                EventDirection.INPUT,
                (EventParameterAst("amount", damage, Reducer.SUM),),
            ),
        ),
        handlers=(
            HandlerAst(
                "incoming_damage",
                ("amount",),
                effects=(
                    NextEffectAst("pool", ExpressionAst("pool + amount * conversion")),
                    WhenEffectAst(
                        ExpressionAst("pool > 0 damage"),
                        (
                            ScheduleEffectAst(
                                ScheduleOperation.REPLACE,
                                EventCallAst(
                                    "pool_tick",
                                    (EventArgumentAst("source", ExpressionAst("event.id")),),
                                ),
                                ExpressionAst("1/2 second"),
                                "tick",
                                ExpressionAst("event.id"),
                            ),
                        ),
                    ),
                    BranchEffectAst(
                        "example_roll",
                        BranchMode.INDEPENDENT,
                        (
                            ProbabilityCaseAst(
                                ExpressionAst("proc_chance"),
                                (NextEffectAst("pool", ExpressionAst("pool + bonus")),),
                            ),
                            ProbabilityCaseAst(ExpressionAst("1 - proc_chance"), ()),
                        ),
                    ),
                ),
            ),
        ),
    )

    assert process.qualified_id == "combat.delayed_damage"
    assert process.keys[0].id == "pool_tick"
    assert process.phases[0].id == "tick"
    assert process.events[0].parameters[0].reducer is Reducer.SUM
    assert isinstance(process.handlers[0].effects[1], WhenEffectAst)
    assert isinstance(process.handlers[0].effects[2], BranchEffectAst)
    assert "raw" not in {item.name for item in fields(ProcessAst)}


def test_process_ir_carries_resolved_types_references_and_simultaneous_next_effects() -> None:
    vitality = Dimension.from_mapping({"vitality": Fraction(1)})
    health_type = NumberTypeIR("health", vitality)
    damage_type = NumberTypeIR("damage", vitality)
    probability_type = NumberTypeIR(
        "dimensionless", DIMENSIONLESS, domain_id="probability"
    )
    process_id = "combat.delayed_damage"

    def member(member_id: str, kind: ProcessMemberKind) -> ProcessMemberRefIR:
        return ProcessMemberRefIR(process_id, member_id, kind)

    health_symbol = SymbolRefIR(process_id, "health", ExpressionSymbolKind.STATE, health_type)
    pool_symbol = SymbolRefIR(process_id, "pool", ExpressionSymbolKind.STATE, damage_type)
    amount_symbol = SymbolRefIR(
        process_id, "amount", ExpressionSymbolKind.EVENT_PARAMETER, damage_type
    )
    conversion_symbol = SymbolRefIR(
        process_id, "conversion", ExpressionSymbolKind.INPUT, probability_type
    )
    incoming = member("incoming_damage", ProcessMemberKind.EVENT)

    process = ProcessIR(
        owner_id="combat",
        id="delayed_damage",
        inputs=(
            InputIR(member("conversion", ProcessMemberKind.INPUT), probability_type),
        ),
        states=(
            StateIR(
                member("health", ProcessMemberKind.STATE),
                health_type,
                TypedExpressionIR("maximum_health", health_type),
                bound=BoundIR(minimum=TypedExpressionIR("0 health", health_type)),
            ),
            StateIR(
                member("pool", ProcessMemberKind.STATE),
                damage_type,
                TypedExpressionIR("0 damage", damage_type),
            ),
        ),
        events=(
            EventIR(
                incoming,
                EventDirection.INPUT,
                (EventParameterIR("amount", damage_type, Reducer.SUM),),
            ),
        ),
        handlers=(
            HandlerIR(
                incoming,
                (amount_symbol,),
                effects=(
                    NextEffectIR(
                        member("health", ProcessMemberKind.STATE),
                        TypedExpressionIR(
                            "max(0 health, health - amount * (1 - conversion))",
                            health_type,
                            (health_symbol, amount_symbol, conversion_symbol),
                        ),
                    ),
                    NextEffectIR(
                        member("pool", ProcessMemberKind.STATE),
                        TypedExpressionIR(
                            "pool + amount * conversion",
                            damage_type,
                            (pool_symbol, amount_symbol, conversion_symbol),
                        ),
                    ),
                ),
            ),
        ),
    )

    assert process.qualified_id == process_id
    assert process.events[0].parameters[0].value_type == damage_type
    assert process.handlers[0].parameter_symbols == (amount_symbol,)
    assert [effect.state.member_id for effect in process.handlers[0].effects] == [
        "health",
        "pool",
    ]
    assert process.handlers[0].effects[1].value.result_type == damage_type

    with pytest.raises(FrozenInstanceError):
        process.id = "mutated"


def test_process_ir_supports_bounded_event_id_maps_and_typed_event_calls() -> None:
    process_id = "combat.independent_stacks"
    time = Dimension.from_mapping({"time": Fraction(1)})
    expiries_type = MapTypeIR(
        key_type=EventIdTypeIR(),
        value_type=NumberTypeIR("second", time),
        capacity=100,
    )
    event_ref = ProcessMemberRefIR(
        process_id, "expire_stack", ProcessMemberKind.EVENT
    )
    stack_symbol = SymbolRefIR(
        process_id,
        "stack",
        ExpressionSymbolKind.EVENT_PARAMETER,
        expiries_type.key_type,
    )
    call = EventCallIR(
        event_ref,
        (EventArgumentIR("stack", TypedExpressionIR("event.id", expiries_type.key_type)),),
    )

    assert expiries_type.capacity == 100
    assert isinstance(expiries_type.key_type, EventIdTypeIR)
    assert call.arguments[0].value.result_type == expiries_type.key_type
    assert stack_symbol.value_type == expiries_type.key_type
    assert BooleanTypeIR() == BooleanTypeIR()
