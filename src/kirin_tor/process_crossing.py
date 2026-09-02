"""Proof checks and exact roots for affine continuous decision conditions."""

from __future__ import annotations

from fractions import Fraction
from typing import Mapping, Optional, Sequence

from .process_expression import ProcessValue, evaluate_process_expression
from .process_ir import (
    BinaryExpressionIR,
    CallExpressionIR,
    ComparisonExpressionIR,
    LiteralExpressionIR,
    ReferenceExpressionIR,
    SymbolRefIR,
    TypedExpressionIR,
    UnaryExpressionIR,
)
from .process_model import ExpressionSymbolKind
from .scenario_ir import ProcessInstanceIR
from .units import UnitRegistry


def _degree(node, variable) -> Optional[int]:
    if isinstance(node, LiteralExpressionIR):
        return 0
    if isinstance(node, ReferenceExpressionIR):
        return 1 if variable(node.reference) else 0
    if isinstance(node, UnaryExpressionIR) and node.operator in {"+", "-"}:
        return _degree(node.operand, variable)
    if isinstance(node, BinaryExpressionIR):
        left = _degree(node.left, variable)
        right = _degree(node.right, variable)
        if left is None or right is None:
            return None
        if node.operator in {"+", "-"}:
            return max(left, right)
        if node.operator == "*":
            return left + right
        if node.operator == "/" and right == 0:
            return left
        if (
            node.operator == "**"
            and isinstance(node.right, LiteralExpressionIR)
            and node.right.value in {0, 1}
        ):
            return 0 if node.right.value == 0 else left
        return None
    if isinstance(node, CallExpressionIR):
        return None
    return None


def supports_exact_affine_crossing(
    condition: TypedExpressionIR,
    instances: Sequence[ProcessInstanceIR],
) -> bool:
    """Prove that one non-strict comparison is affine between event batches."""

    node = condition.node
    if not isinstance(node, ComparisonExpressionIR) or len(node.operators) != 1:
        return False
    if node.operators[0] not in {">=", "<="}:
        return False
    observation_degrees = {}
    for instance in instances:
        process = instance.process
        flows = {flow.state.member_id: flow for flow in process.flows}
        for observation in process.observations:
            scenario_name = f"{instance.id}.{observation.ref.member_id}"
            referenced_flow_ids = {
                reference.id
                for reference in observation.value.references
                if reference.kind is ExpressionSymbolKind.STATE
                and reference.id in flows
            }
            valid_flows = all(
                flow.value.node is not None
                and _degree(
                    flow.value.node,
                    lambda reference, elapsed=flow.elapsed_symbol: reference
                    == elapsed,
                )
                in {0, 1}
                for state_id, flow in flows.items()
                if state_id in referenced_flow_ids
            )
            if not valid_flows or observation.value.node is None:
                observation_degrees[scenario_name] = None
                continue
            observation_degrees[scenario_name] = _degree(
                observation.value.node,
                lambda reference, flowing=frozenset(flows): (
                    reference.kind is ExpressionSymbolKind.STATE
                    and reference.id in flowing
                ),
            )

    def scenario_variable(reference: SymbolRefIR) -> bool:
        if reference.kind is ExpressionSymbolKind.RUNTIME:
            return reference.id == "elapsed"
        if reference.kind is ExpressionSymbolKind.OBSERVATION:
            return observation_degrees.get(reference.id) == 1
        return False

    for operand in node.operands:
        if _degree(operand, scenario_variable) not in {0, 1}:
            return False
        for reference in condition.references:
            if (
                reference.kind is ExpressionSymbolKind.OBSERVATION
                and observation_degrees.get(reference.id) is None
            ):
                return False
    return True


def affine_condition_gap(
    condition: TypedExpressionIR,
    values: Mapping[SymbolRefIR, ProcessValue],
    registry: UnitRegistry,
) -> Fraction:
    """Return a gap whose nonnegative region is the declared condition."""

    node = condition.node
    if not isinstance(node, ComparisonExpressionIR) or len(node.operators) != 1:
        raise ValueError("condition is not a simple comparison")
    left, right = node.operands

    def evaluate(operand) -> Fraction:
        value = evaluate_process_expression(
            TypedExpressionIR(
                condition.source,
                operand.value_type,
                condition.references,
                condition.location,
                operand,
            ),
            values,
            registry,
        )
        assert isinstance(value, Fraction)
        return value

    left_value = evaluate(left)
    right_value = evaluate(right)
    return (
        left_value - right_value
        if node.operators[0] == ">="
        else right_value - left_value
    )
