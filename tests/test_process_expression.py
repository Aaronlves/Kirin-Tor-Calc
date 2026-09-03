from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

from kirin_tor.errors import DomainError, ExpressionError, SchemaError, SourceLocation, UnitError
from kirin_tor.process_ast import ExpressionAst
from kirin_tor.process_expression import (
    FrozenMapValue,
    ProcessEventId,
    compile_process_expression,
    evaluate_process_expression,
)
from kirin_tor.process_ir import (
    BooleanTypeIR,
    EventIdTypeIR,
    MapTypeIR,
    NumberTypeIR,
    SymbolRefIR,
)
from kirin_tor.process_lowering import lower_process_asts
from kirin_tor.process_model import ExpressionSymbolKind
from kirin_tor.process_parser import parse_process_asts
from kirin_tor.units import DIMENSIONLESS, UnitRegistry


def _registry() -> UnitRegistry:
    registry = UnitRegistry()
    location = SourceLocation(path="types.kirin")
    registry.add_dimension("vitality", {}, location)
    registry.add_unit("health", {"vitality": Fraction(1)}, Fraction(1), location)
    registry.add_unit("damage", {"vitality": Fraction(1)}, Fraction(1), location)
    return registry


def test_typed_expression_ir_evaluates_exact_units_and_lazy_conditionals() -> None:
    registry = _registry()
    health = NumberTypeIR("health", registry.parse_unit("health"))
    current = SymbolRefIR("test", "current", ExpressionSymbolKind.STATE, health)
    expression = compile_process_expression(
        ExpressionAst(
            "if_else(current > 0 health, current / 2, 1 health / 0)",
            SourceLocation(path="test.kirin", line=1),
        ),
        health,
        {"current": current},
        registry,
    )

    assert expression.node is not None
    assert evaluate_process_expression(
        expression, {current: Fraction(9)}, registry
    ) == Fraction(9, 2)
    assert [reference.id for reference in expression.references] == ["health", "current"]


def test_process_expression_rejects_wrong_result_types_and_units() -> None:
    registry = _registry()
    health = NumberTypeIR("health", registry.parse_unit("health"))
    time = NumberTypeIR("second", registry.parse_unit("second"))
    value = SymbolRefIR("test", "value", ExpressionSymbolKind.STATE, health)

    with pytest.raises(ExpressionError, match="requires boolean"):
        compile_process_expression(
            ExpressionAst("value"), BooleanTypeIR(), {"value": value}, registry
        )
    with pytest.raises(UnitError, match="requires time"):
        compile_process_expression(
            ExpressionAst("value"), time, {"value": value}, registry
        )


def test_process_expression_continuations_allow_nested_argument_indentation() -> None:
    source = """@kirin 2
@entry nested_process

process counter:
  state value: count = 0
  event input add(amount: count)
  on add(amount):
    next value = max(
      value,
        min(
          amount,
          10
        )
    )
  observe current: count = value
"""
    process = parse_process_asts(source, Path("nested-process.kirin"))[0]
    effect = process.handlers[0].effects[0]
    assert effect.value.text == "max( value, min( amount, 10 ) )"
    assert lower_process_asts((process,), _registry())[0].id == "counter"


def test_bounded_map_operations_are_persistent_canonical_and_capacity_checked() -> None:
    registry = _registry()
    map_type = MapTypeIR(
        EventIdTypeIR(),
        NumberTypeIR("second", registry.parse_unit("second")),
        1,
    )
    mapping = SymbolRefIR("test", "mapping", ExpressionSymbolKind.STATE, map_type)
    event_id = SymbolRefIR("test", "event.id", ExpressionSymbolKind.EVENT_CONTEXT, EventIdTypeIR())
    expression = compile_process_expression(
        ExpressionAst("put(mapping, event.id, 3 second)"),
        map_type,
        {"mapping": mapping, "event.id": event_id},
        registry,
    )
    first = evaluate_process_expression(
        expression,
        {mapping: FrozenMapValue(), event_id: ProcessEventId("e1")},
        registry,
    )
    assert first == FrozenMapValue(((ProcessEventId("e1"), Fraction(3)),))
    assert evaluate_process_expression(
        expression,
        {mapping: first, event_id: ProcessEventId("e1")},
        registry,
    ) == first
    with pytest.raises(DomainError, match="capacity"):
        evaluate_process_expression(
            expression,
            {mapping: first, event_id: ProcessEventId("e2")},
            registry,
        )


def test_lowering_rejects_possible_same_transition_writes_but_allows_branch_cases() -> None:
    conflicting = """@kirin 2
@entry conflicts

process bad:
  state count: count = 0
  event input tick()
  on tick():
    next count = count + 1
    when count == 0:
      next count = 2
"""
    with pytest.raises(SchemaError, match="define next state 'count' more than once"):
        lower_process_asts(
            parse_process_asts(conflicting, Path("conflicting.kirin")), _registry()
        )

    exclusive = conflicting.replace(
        "    next count = count + 1\n    when count == 0:\n      next count = 2",
        "    branch result joint:\n      probability 1/2:\n        next count = count + 1\n      probability 1/2:\n        next count = 2",
    ).replace("process bad:", "process valid:")
    process = lower_process_asts(
        parse_process_asts(exclusive, Path("exclusive.kirin")), _registry()
    )[0]
    assert process.id == "valid"
