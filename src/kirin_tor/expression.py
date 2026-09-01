"""Restricted expression parser that constructs SymPy objects without eval-like APIs."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Dict, Iterable, Mapping, Optional, Set, TYPE_CHECKING

import sympy as sp

from .errors import DomainError, ExpressionError, KTError, SourceLocation, UnitError
from .limits import (
    MAX_ABS_INTEGER_EXPONENT,
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    MAX_DIRECT_DEPENDENCIES,
    MAX_DISTRIBUTION_COMBINATION_PAIRS,
    MAX_DISTRIBUTION_OUTCOMES,
    MAX_DISTRIBUTION_REPETITIONS,
    MAX_DECIMAL_EXPONENT,
    MAX_EXPRESSION_LENGTH,
    MAX_NUMERIC_LITERAL_LENGTH,
    MAX_SUM_TERMS,
)
from .schema import Entry, InputSpec
from .units import DIMENSIONLESS, Dimension, require_same

if TYPE_CHECKING:
    from .engine import Engine


NUMBER_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+)$")


def parse_exact_number(text: str) -> sp.Rational:
    """Parse a deliberately small numeric grammar without string sympification."""
    value = text.strip()
    if len(value) > MAX_NUMERIC_LITERAL_LENGTH:
        raise ExpressionError(
            f"numeric literal exceeds {MAX_NUMERIC_LITERAL_LENGTH} characters"
        )
    if not NUMBER_RE.fullmatch(value):
        raise ExpressionError(f"invalid numeric literal {text!r}")
    if "/" in value:
        numerator_text, denominator_text = value.split("/", 1)
        denominator = int(denominator_text)
        if denominator == 0:
            raise DomainError("numeric literal has a zero denominator")
        return sp.Rational(int(numerator_text), denominator)
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ExpressionError(f"invalid numeric literal {text!r}") from exc
    if not decimal.is_finite():
        raise ExpressionError("NaN and infinity are not valid numeric literals")
    if decimal and abs(decimal.adjusted()) > MAX_DECIMAL_EXPONENT:
        raise ExpressionError(
            f"decimal exponent magnitude may not exceed {MAX_DECIMAL_EXPONENT}"
        )
    numerator, denominator = decimal.as_integer_ratio()
    return sp.Rational(numerator, denominator)


def merge_inputs(*groups: Mapping[str, InputSpec]) -> Dict[str, InputSpec]:
    result: Dict[str, InputSpec] = {}
    for group in groups:
        for name, spec in group.items():
            if name in result and result[name] != spec:
                raise ExpressionError(
                    f"input {name!r} has conflicting declarations across referenced entries"
                )
            result[name] = spec
    return result


def compatible_value_dimension(values: Iterable["MathValue"], context: str) -> Dimension:
    """Treat exact literal/derived zero as unit-polymorphic, never nonzero values."""
    values = list(values)
    substantive = [value.dimension for value in values if value.expr != 0]
    if not substantive:
        return DIMENSIONLESS
    return require_same(substantive, context)


@dataclass
class MathValue:
    expr: sp.Expr
    dimension: Dimension = DIMENSIONLESS
    conditions: list = field(default_factory=list)
    inputs: Dict[str, InputSpec] = field(default_factory=dict)
    dependencies: Set[str] = field(default_factory=set)
    is_boolean: bool = False

    def with_expr(self, expr: sp.Expr) -> "MathValue":
        return MathValue(
            expr,
            self.dimension,
            list(self.conditions),
            dict(self.inputs),
            set(self.dependencies),
            self.is_boolean,
        )


@dataclass(frozen=True)
class DistributionOutcome:
    value: MathValue
    probability: MathValue


@dataclass
class FiniteDistribution:
    outcomes: tuple[DistributionOutcome, ...]
    dimension: Dimension
    conditions: list = field(default_factory=list)
    inputs: Dict[str, InputSpec] = field(default_factory=dict)
    dependencies: Set[str] = field(default_factory=set)

    def copy(self) -> "FiniteDistribution":
        return FiniteDistribution(
            tuple(
                DistributionOutcome(
                    MathValue(
                        outcome.value.expr,
                        outcome.value.dimension,
                        list(outcome.value.conditions),
                        dict(outcome.value.inputs),
                        set(outcome.value.dependencies),
                        outcome.value.is_boolean,
                    ),
                    MathValue(
                        outcome.probability.expr,
                        outcome.probability.dimension,
                        list(outcome.probability.conditions),
                        dict(outcome.probability.inputs),
                        set(outcome.probability.dependencies),
                        outcome.probability.is_boolean,
                    ),
                )
                for outcome in self.outcomes
            ),
            self.dimension,
            list(self.conditions),
            dict(self.inputs),
            set(self.dependencies),
        )


@dataclass(frozen=True)
class StateRewardValue:
    id: str
    dimension: Dimension
    values: Mapping[str, MathValue]
    conditions: tuple
    inputs: Mapping[str, InputSpec]
    dependencies: frozenset[str]


@dataclass(frozen=True)
class FiniteStateModel:
    id: str
    owner_id: str
    states: tuple[str, ...]
    transitions: tuple[tuple[MathValue, ...], ...]
    rewards: Mapping[str, StateRewardValue]
    conditions: tuple
    inputs: Mapping[str, InputSpec]
    dependencies: frozenset[str]


ALLOWED_NODES = {
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.Compare,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Eq,
    ast.NotEq,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Constant,
}


class RestrictedCompiler:
    def __init__(
        self,
        engine: "Engine",
        entry: Optional[Entry],
        local_values: Optional[Mapping[str, MathValue]] = None,
        location: Optional[SourceLocation] = None,
    ):
        self.engine = engine
        self.entry = entry
        self.local_values = dict(local_values or {})
        self.location = location
        self.source = ""

    def compile(self, source: str) -> MathValue:
        if len(source) > MAX_EXPRESSION_LENGTH:
            raise ExpressionError(
                f"expression exceeds {MAX_EXPRESSION_LENGTH} characters", self.location
            )
        self.source = " ".join(line.strip() for line in source.splitlines() if line.strip())
        try:
            tree = ast.parse(self.source, mode="eval")
        except SyntaxError as exc:
            detail = f"invalid expression syntax at column {exc.offset}: {exc.msg}"
            raise ExpressionError(detail, self.location) from exc
        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_AST_NODES:
            raise ExpressionError(f"expression exceeds {MAX_AST_NODES} AST nodes", self.location)
        for node in nodes:
            if type(node) not in ALLOWED_NODES:
                if isinstance(node, ast.BitXor):
                    detail = "'^' is not supported; use '**' for exponentiation"
                else:
                    detail = f"expression syntax {type(node).__name__} is not allowed"
                raise ExpressionError(detail, self.location)
        if self._depth(tree) > MAX_AST_DEPTH:
            raise ExpressionError(f"expression exceeds AST depth {MAX_AST_DEPTH}", self.location)
        dependencies = self._direct_dependencies(tree)
        if len(dependencies) > MAX_DIRECT_DEPENDENCIES:
            raise ExpressionError(
                f"expression exceeds {MAX_DIRECT_DEPENDENCIES} direct dependencies", self.location
            )
        try:
            return self._build(tree.body)
        except KTError as exc:
            if getattr(exc, "location", None) is None:
                exc.location = self.location
            raise

    def _depth(self, node: ast.AST) -> int:
        children = list(ast.iter_child_nodes(node))
        return 1 if not children else 1 + max(self._depth(child) for child in children)

    def _direct_dependencies(self, tree: ast.AST) -> Set[str]:
        result: Set[str] = set()
        attribute_bases = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                result.add(f"{node.value.id}.{node.attr}")
            elif isinstance(node, ast.Name) and id(node) not in attribute_bases:
                result.add(node.id)
        return result

    def _constant(self, node: ast.Constant) -> MathValue:
        if isinstance(node.value, bool):
            return MathValue(sp.true if node.value else sp.false, is_boolean=True)
        if not isinstance(node.value, (int, float)):
            raise ExpressionError("only integer and decimal numeric literals are allowed", self.location)
        token = ast.get_source_segment(self.source, node)
        if token is None:
            raise ExpressionError("could not preserve numeric literal text", self.location)
        return MathValue(parse_exact_number(token))

    def _combine(self, left: MathValue, right: MathValue) -> tuple[list, Dict[str, InputSpec], Set[str]]:
        return (
            [*left.conditions, *right.conditions],
            merge_inputs(left.inputs, right.inputs),
            set(left.dependencies) | set(right.dependencies),
        )

    def _build(self, node: ast.AST) -> MathValue:
        if isinstance(node, ast.Constant):
            return self._constant(node)
        if isinstance(node, ast.Name):
            return self._name(node.id)
        if isinstance(node, ast.Attribute):
            return self._attribute(node)
        if isinstance(node, ast.UnaryOp):
            value = self._build(node.operand)
            if isinstance(node.op, ast.Not):
                self._require_boolean(value, "not")
                return value.with_expr(sp.Not(value.expr))
            self._require_numeric(value, "unary arithmetic")
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return value.with_expr(-value.expr)
            raise ExpressionError("unsupported unary operator", self.location)
        if isinstance(node, ast.BinOp):
            return self._binary(node)
        if isinstance(node, ast.Compare):
            return self._comparison(node)
        if isinstance(node, ast.BoolOp):
            return self._boolean_operation(node)
        if isinstance(node, ast.Call):
            return self._call(node)
        raise ExpressionError(f"unsupported expression node {type(node).__name__}", self.location)

    def _name(self, name: str) -> MathValue:
        if name.startswith("__"):
            raise ExpressionError("private names are not allowed", self.location)
        if name in self.local_values:
            value = self.local_values[name]
            return MathValue(
                value.expr,
                value.dimension,
                list(value.conditions),
                dict(value.inputs),
                set(value.dependencies),
                value.is_boolean,
            )
        if self.entry is not None:
            if name in self.entry.inputs:
                spec = self.entry.inputs[name]
                symbol = self.engine.input_symbol(name, spec)
                return MathValue(
                    symbol,
                    spec.dimension,
                    conditions=self.engine.input_conditions(spec, symbol),
                    inputs={spec.key: spec},
                    dependencies={self.entry.id},
                    is_boolean=spec.value_type == "boolean",
                )
            if name in self.entry.fields or name in self.entry.recurrences or name in self.entry.outputs:
                return self.engine.resolve_member(self.entry.id, name)
            if name in self.entry.distributions:
                raise ExpressionError(
                    f"distribution {name!r} must be observed with expectation, variance, or probability",
                    self.location,
                )
            if name in self.entry.state_models:
                raise ExpressionError(
                    f"state model {name!r} must be queried with a state-model analytical function",
                    self.location,
                )
            if name in self.entry.aliases:
                entry_id, member = self.entry.aliases[name].split(".", 1)
                return self.engine.resolve_member(entry_id, member)
        spec = self.engine.global_input(name)
        if spec is not None:
            symbol = self.engine.input_symbol(name, spec)
            return MathValue(
                symbol,
                spec.dimension,
                conditions=self.engine.input_conditions(spec, symbol),
                inputs={spec.key: spec},
                is_boolean=spec.value_type == "boolean",
            )
        if name in self.engine.workspace.units.units:
            return MathValue(
                self.engine.unit_scale_expr(name),
                self.engine.workspace.units.parse_unit(name),
            )
        raise ExpressionError(f"undeclared variable {name!r}", self.location)

    def _attribute(self, node: ast.Attribute) -> MathValue:
        if not isinstance(node.value, ast.Name):
            raise ExpressionError("nested attribute access is not allowed", self.location)
        if node.value.id.startswith("__") or node.attr.startswith("__"):
            raise ExpressionError("private attribute access is not allowed", self.location)
        return self.engine.resolve_member(node.value.id, node.attr)

    def _binary(self, node: ast.BinOp) -> MathValue:
        left = self._build(node.left)
        right = self._build(node.right)
        self._require_numeric(left, "arithmetic")
        self._require_numeric(right, "arithmetic")
        conditions, inputs, dependencies = self._combine(left, right)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            dimension = compatible_value_dimension([left, right], "addition/subtraction")
            expr = left.expr + right.expr if isinstance(node.op, ast.Add) else left.expr - right.expr
        elif isinstance(node.op, ast.Mult):
            dimension = left.dimension.multiply(right.dimension)
            expr = left.expr * right.expr
        elif isinstance(node.op, ast.Div):
            dimension = left.dimension.divide(right.dimension)
            conditions.append(sp.Ne(right.expr, 0, evaluate=False))
            expr = left.expr / right.expr
        elif isinstance(node.op, ast.Pow):
            if not right.dimension.is_dimensionless:
                raise UnitError("an exponent must be dimensionless", self.location)
            if right.expr.is_number:
                if not right.expr.is_Rational:
                    raise ExpressionError("exponent must be an exact rational number", self.location)
                exponent = Fraction(int(right.expr.p), int(right.expr.q))
                if abs(exponent) > MAX_ABS_INTEGER_EXPONENT:
                    raise ExpressionError(
                        f"absolute exponent may not exceed {MAX_ABS_INTEGER_EXPONENT}", self.location
                    )
                dimension = left.dimension.power(exponent)
                if exponent < 0:
                    conditions.append(sp.Ne(left.expr, 0, evaluate=False))
                if exponent == 0:
                    conditions.append(sp.Ne(left.expr, 0, evaluate=False))
                if exponent.denominator != 1:
                    conditions.append(sp.Ge(left.expr, 0, evaluate=False))
            else:
                if not left.dimension.is_dimensionless:
                    raise UnitError("a dimensioned base requires a constant rational exponent", self.location)
                dimension = DIMENSIONLESS
                conditions.append(sp.Gt(left.expr, 0, evaluate=False))
            expr = left.expr ** right.expr
        else:
            raise ExpressionError("unsupported binary operator", self.location)
        return MathValue(expr, dimension, conditions, inputs, dependencies)

    def _comparison(self, node: ast.Compare) -> MathValue:
        values = [self._build(node.left), *(self._build(item) for item in node.comparators)]
        for value in values:
            self._require_numeric(value, "comparison")
        relations = []
        conditions = []
        inputs = merge_inputs(*(value.inputs for value in values))
        dependencies = set().union(*(value.dependencies for value in values))
        relation_types = {
            ast.Lt: sp.Lt,
            ast.LtE: sp.Le,
            ast.Gt: sp.Gt,
            ast.GtE: sp.Ge,
            ast.Eq: sp.Eq,
            ast.NotEq: sp.Ne,
        }
        for left, operator, right in zip(values, node.ops, values[1:]):
            compatible_value_dimension([left, right], "comparison")
            constructor = relation_types.get(type(operator))
            if constructor is None:
                raise ExpressionError("unsupported comparison operator", self.location)
            if left.expr.free_symbols or right.expr.free_symbols:
                relations.append(constructor(left.expr, right.expr, evaluate=False))
            else:
                relations.append(constructor(left.expr, right.expr))
            conditions.extend(left.conditions)
        conditions.extend(values[-1].conditions)
        expr = relations[0] if len(relations) == 1 else sp.And(*relations)
        return MathValue(expr, DIMENSIONLESS, conditions, inputs, dependencies, True)

    def _boolean_operation(self, node: ast.BoolOp) -> MathValue:
        values = [self._build(item) for item in node.values]
        for value in values:
            self._require_boolean(value, "boolean operation")
        constructor = sp.And if isinstance(node.op, ast.And) else sp.Or
        return MathValue(
            constructor(*(value.expr for value in values)),
            DIMENSIONLESS,
            [condition for value in values for condition in value.conditions],
            merge_inputs(*(value.inputs for value in values)),
            set().union(*(value.dependencies for value in values)),
            True,
        )

    def _call(self, node: ast.Call) -> MathValue:
        if node.keywords:
            raise ExpressionError("keyword arguments are not allowed", self.location)
        if isinstance(node.func, ast.Attribute):
            if not isinstance(node.func.value, ast.Name):
                raise ExpressionError("nested function access is not allowed", self.location)
            args = [self._build(arg) for arg in node.args]
            return self.engine.call_function(node.func.value.id, node.func.attr, args)
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("only named functions are allowed", self.location)
        name = node.func.id
        if self.entry is not None and name in self.entry.functions:
            args = [self._build(arg) for arg in node.args]
            return self.engine.call_function(self.entry.id, name, args)
        if self.entry is not None and name in self.entry.aliases:
            entry_id, function_name = self.entry.aliases[name].split(".", 1)
            args = [self._build(arg) for arg in node.args]
            return self.engine.call_function(entry_id, function_name, args)
        if name in {"lookup", "interpolate"}:
            return self._table_call(node, interpolate=name == "interpolate")
        if name in {"expectation", "variance", "probability"}:
            return self._distribution_call(node, name)
        if name in {
            "steady_probability",
            "steady_reward",
            "hitting_probability",
            "expected_steps",
        }:
            return self._state_model_call(node, name)
        if name in {"sum", "product"}:
            return self._finite_aggregate(node, name)
        if name in {"if_else", "piecewise"}:
            args = [self._build(arg) for arg in node.args]
            return self._piecewise(name, args)
        args = [self._build(arg) for arg in node.args]
        return self._builtin(name, args)

    def _state_model_reference(self, node: ast.AST) -> FiniteStateModel:
        if isinstance(node, ast.Name):
            if self.entry is None:
                raise ExpressionError(
                    f"local state model {node.id!r} requires an entry context",
                    self.location,
                )
            if node.id in self.entry.aliases:
                entry_id, model_name = self.entry.aliases[node.id].split(".", 1)
            else:
                entry_id, model_name = self.entry.id, node.id
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            entry_id, model_name = node.value.id, node.attr
        else:
            raise ExpressionError(
                "state model must be a local name or ENTRY.STATE_MODEL", self.location
            )
        return self.engine.resolve_state_model(entry_id, model_name)

    def _state_model_identifier(
        self, node: ast.AST, label: str, allowed: Iterable[str]
    ) -> str:
        if not isinstance(node, ast.Name):
            raise ExpressionError(f"{label} must be a plain identifier", self.location)
        if node.id not in set(allowed):
            raise ExpressionError(f"unknown {label} {node.id!r}", self.location)
        return node.id

    def _state_model_call(self, node: ast.Call, operation: str) -> MathValue:
        if node.keywords:
            raise ExpressionError("keyword arguments are not allowed", self.location)
        expected = 2 if operation in {"steady_probability", "steady_reward"} else 3
        if len(node.args) != expected:
            signatures = {
                "steady_probability": "steady_probability(MODEL, STATE)",
                "steady_reward": "steady_reward(MODEL, REWARD)",
                "hitting_probability": "hitting_probability(MODEL, START, TARGET)",
                "expected_steps": "expected_steps(MODEL, START, TARGET)",
            }
            raise ExpressionError(
                f"{operation} expects {signatures[operation]}", self.location
            )
        model = self._state_model_reference(node.args[0])
        if operation == "steady_reward":
            reward = self._state_model_identifier(
                node.args[1], "state reward", model.rewards
            )
            return self.engine.state_model_steady_reward(model, reward)
        if operation == "steady_probability":
            state = self._state_model_identifier(node.args[1], "state", model.states)
            return self.engine.state_model_steady_probability(model, state)
        start = self._state_model_identifier(node.args[1], "state", model.states)
        target = self._state_model_identifier(node.args[2], "state", model.states)
        if operation == "hitting_probability":
            return self.engine.state_model_hitting_probability(model, start, target)
        return self.engine.state_model_expected_steps(model, start, target)

    def _distribution_reference(self, node: ast.AST) -> FiniteDistribution:
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ExpressionError(
                    "distribution transformations must use named functions",
                    self.location,
                )
            operations = {
                "map",
                "independent_sum",
                "repeat_sum",
                "condition",
            }
            if node.func.id not in operations:
                raise ExpressionError(
                    f"function {node.func.id!r} does not produce a distribution",
                    self.location,
                )
            return self._distribution_operation(node, node.func.id)
        if isinstance(node, ast.Name):
            if self.entry is None:
                raise ExpressionError(
                    f"local distribution {node.id!r} requires an entry context",
                    self.location,
                )
            if node.id in self.entry.aliases:
                entry_id, distribution_name = self.entry.aliases[node.id].split(".", 1)
            else:
                entry_id, distribution_name = self.entry.id, node.id
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            entry_id, distribution_name = node.value.id, node.attr
        else:
            raise ExpressionError(
                "distribution must be a local name or ENTRY.DISTRIBUTION",
                self.location,
            )
        return self.engine.resolve_distribution(entry_id, distribution_name)

    def _distribution_bound_expression(
        self,
        variable_node: ast.AST,
        expression_node: ast.AST,
        value: MathValue,
        operation: str,
    ) -> MathValue:
        if not isinstance(variable_node, ast.Name):
            raise ExpressionError(
                f"{operation} variable must be a plain identifier", self.location
            )
        variable = variable_node.id
        entry_names = set()
        if self.entry is not None:
            entry_names = (
                set(self.entry.inputs)
                | set(self.entry.fields)
                | set(self.entry.functions)
                | set(self.entry.tables)
                | set(self.entry.distributions)
                | set(self.entry.recurrences)
                | set(self.entry.state_models)
                | set(self.entry.outputs)
                | set(self.entry.aliases)
            )
        if variable in self.local_values or variable in entry_names:
            raise ExpressionError(
                f"{operation} variable {variable!r} shadows a declared name",
                self.location,
            )
        source = ast.get_source_segment(self.source, expression_node)
        if source is None:
            raise ExpressionError(
                f"could not preserve {operation} expression text", self.location
            )
        local_values = dict(self.local_values)
        local_values[variable] = value
        return RestrictedCompiler(
            self.engine,
            self.entry,
            local_values=local_values,
            location=self.location,
        ).compile(source)

    def _merged_distribution(
        self,
        outcomes: Iterable[DistributionOutcome],
        dimension: Dimension,
        conditions: list,
        inputs: Mapping[str, InputSpec],
        dependencies: Set[str],
        operation: str,
    ) -> FiniteDistribution:
        merged: Dict[str, DistributionOutcome] = {}
        for outcome in outcomes:
            simplified_value = sp.simplify(outcome.value.expr)
            key = sp.srepr(simplified_value)
            if key in merged:
                previous = merged[key]
                probability = MathValue(
                    sp.simplify(
                        previous.probability.expr + outcome.probability.expr
                    ),
                    DIMENSIONLESS,
                )
                merged[key] = DistributionOutcome(previous.value, probability)
            else:
                merged[key] = DistributionOutcome(
                    outcome.value.with_expr(simplified_value), outcome.probability
                )
            if len(merged) > MAX_DISTRIBUTION_OUTCOMES:
                raise ExpressionError(
                    f"{operation} exceeds {MAX_DISTRIBUTION_OUTCOMES} finite outcomes",
                    self.location,
                )
        return FiniteDistribution(
            tuple(merged.values()),
            dimension,
            conditions,
            dict(inputs),
            set(dependencies),
        )

    def _independent_sum(
        self, left: FiniteDistribution, right: FiniteDistribution
    ) -> FiniteDistribution:
        require_same(
            [left.dimension, right.dimension],
            "independent_sum distributions",
        )
        pair_count = len(left.outcomes) * len(right.outcomes)
        if pair_count > MAX_DISTRIBUTION_COMBINATION_PAIRS:
            raise ExpressionError(
                "independent_sum would combine "
                f"{pair_count} outcome pairs; limit is {MAX_DISTRIBUTION_COMBINATION_PAIRS}",
                self.location,
            )
        outcomes = []
        for left_outcome in left.outcomes:
            for right_outcome in right.outcomes:
                outcomes.append(
                    DistributionOutcome(
                        MathValue(
                            left_outcome.value.expr + right_outcome.value.expr,
                            left.dimension,
                        ),
                        MathValue(
                            left_outcome.probability.expr
                            * right_outcome.probability.expr,
                            DIMENSIONLESS,
                        ),
                    )
                )
        return self._merged_distribution(
            outcomes,
            left.dimension,
            [*left.conditions, *right.conditions],
            merge_inputs(left.inputs, right.inputs),
            set(left.dependencies) | set(right.dependencies),
            "independent_sum",
        )

    def _distribution_operation(
        self, node: ast.Call, operation: str
    ) -> FiniteDistribution:
        if node.keywords:
            raise ExpressionError("keyword arguments are not allowed", self.location)
        if operation == "independent_sum":
            if len(node.args) != 2:
                raise ExpressionError(
                    "independent_sum expects two distributions", self.location
                )
            return self._independent_sum(
                self._distribution_reference(node.args[0]),
                self._distribution_reference(node.args[1]),
            )
        if operation == "repeat_sum":
            if len(node.args) != 2:
                raise ExpressionError(
                    "repeat_sum expects a distribution and bounded count",
                    self.location,
                )
            base = self._distribution_reference(node.args[0])
            count = self._build(node.args[1])
            self._require_numeric(count, "repeat_sum count")
            require_same([count.dimension, DIMENSIONLESS], "repeat_sum count")
            candidates = self.engine.bounded_nonnegative_integer_values(
                count, "repeat_sum count", MAX_DISTRIBUTION_REPETITIONS
            )
            result = FiniteDistribution(
                (
                    DistributionOutcome(
                        MathValue(sp.Integer(0), base.dimension),
                        MathValue(sp.Integer(1)),
                    ),
                ),
                base.dimension,
                list(count.conditions),
                dict(count.inputs),
                set(count.dependencies),
            )
            results = {0: result}
            for repetition in range(1, max(candidates) + 1):
                result = self._independent_sum(result, base)
                if repetition in candidates:
                    results[repetition] = result
            if len(candidates) == 1 and not count.expr.free_symbols:
                return results[candidates[0]]
            conditions = [*count.conditions, *base.conditions]
            inputs = merge_inputs(count.inputs, base.inputs)
            dependencies = set(count.dependencies) | set(base.dependencies)
            selected_outcomes = []
            active_conditions = []
            selected_outcome_count = sum(
                len(results[candidate].outcomes) for candidate in candidates
            )
            if selected_outcome_count > MAX_DISTRIBUTION_COMBINATION_PAIRS:
                raise ExpressionError(
                    "repeat_sum bounded count would combine "
                    f"{selected_outcome_count} conditional outcomes; limit is "
                    f"{MAX_DISTRIBUTION_COMBINATION_PAIRS}",
                    self.location,
                )
            for candidate in candidates:
                active = sp.Eq(count.expr, candidate, evaluate=False)
                active_conditions.append(active)
                for outcome in results[candidate].outcomes:
                    selected_outcomes.append(
                        DistributionOutcome(
                            outcome.value,
                            MathValue(
                                outcome.probability.expr
                                * sp.Piecewise((1, active), (0, True)),
                                DIMENSIONLESS,
                            ),
                        )
                    )
            conditions.append(sp.Or(*active_conditions))
            return self._merged_distribution(
                selected_outcomes,
                base.dimension,
                conditions,
                inputs,
                dependencies,
                "repeat_sum",
            )
        if operation == "map":
            if len(node.args) != 3:
                raise ExpressionError(
                    "map expects map(DISTRIBUTION, VARIABLE, EXPRESSION)",
                    self.location,
                )
            base = self._distribution_reference(node.args[0])
            mapped = []
            mapped_values = []
            conditions = list(base.conditions)
            inputs = dict(base.inputs)
            dependencies = set(base.dependencies)
            for outcome in base.outcomes:
                value = self._distribution_bound_expression(
                    node.args[1], node.args[2], outcome.value, "map"
                )
                self._require_numeric(value, "map result")
                mapped_values.append(value)
                conditions.extend(value.conditions)
                inputs = merge_inputs(inputs, value.inputs)
                dependencies.update(value.dependencies)
                mapped.append(DistributionOutcome(value, outcome.probability))
            dimension = compatible_value_dimension(mapped_values, "map results")
            for outcome in mapped:
                if outcome.value.expr == 0:
                    outcome.value.dimension = dimension
            return self._merged_distribution(
                mapped,
                dimension,
                conditions,
                inputs,
                dependencies,
                "map",
            )
        if operation == "condition":
            if len(node.args) != 3:
                raise ExpressionError(
                    "condition expects condition(DISTRIBUTION, VARIABLE, PREDICATE)",
                    self.location,
                )
            base = self._distribution_reference(node.args[0])
            weighted = []
            active_probabilities = []
            conditions = list(base.conditions)
            inputs = dict(base.inputs)
            dependencies = set(base.dependencies)
            for outcome in base.outcomes:
                predicate = self._distribution_bound_expression(
                    node.args[1], node.args[2], outcome.value, "condition"
                )
                self._require_boolean(predicate, "condition predicate")
                conditions.extend(predicate.conditions)
                inputs = merge_inputs(inputs, predicate.inputs)
                dependencies.update(predicate.dependencies)
                active = sp.Piecewise((1, predicate.expr), (0, True))
                active_probability = outcome.probability.expr * active
                active_probabilities.append(active_probability)
                weighted.append((outcome, active_probability))
            normalization = sp.simplify(sp.Add(*active_probabilities))
            conditions.append(sp.Ne(normalization, 0, evaluate=False))
            outcomes = [
                DistributionOutcome(
                    outcome.value,
                    MathValue(
                        sp.simplify(active_probability / normalization),
                        DIMENSIONLESS,
                    ),
                )
                for outcome, active_probability in weighted
            ]
            return self._merged_distribution(
                outcomes,
                base.dimension,
                conditions,
                inputs,
                dependencies,
                "condition",
            )
        raise ExpressionError(
            f"unsupported distribution operation {operation!r}", self.location
        )

    def _distribution_call(self, node: ast.Call, name: str) -> MathValue:
        expected_arguments = 2 if name == "probability" else 1
        if len(node.args) != expected_arguments:
            signature = (
                "probability(DISTRIBUTION, VALUE)"
                if name == "probability"
                else f"{name}(DISTRIBUTION)"
            )
            raise ExpressionError(f"{name} expects {signature}", self.location)
        distribution = self._distribution_reference(node.args[0])
        conditions = list(distribution.conditions)
        inputs = dict(distribution.inputs)
        dependencies = set(distribution.dependencies)
        expectation_expr = sp.Add(
            *(
                outcome.value.expr * outcome.probability.expr
                for outcome in distribution.outcomes
            )
        )
        if name == "expectation":
            return MathValue(
                expectation_expr,
                distribution.dimension,
                conditions,
                inputs,
                dependencies,
            )
        if name == "variance":
            variance_expr = sp.Add(
                *(
                    (outcome.value.expr - expectation_expr) ** 2
                    * outcome.probability.expr
                    for outcome in distribution.outcomes
                )
            )
            return MathValue(
                variance_expr,
                distribution.dimension.power(Fraction(2)),
                conditions,
                inputs,
                dependencies,
            )

        target = self._build(node.args[1])
        self._require_numeric(target, "probability target")
        compatible_value_dimension(
            [MathValue(sp.Integer(1), distribution.dimension), target],
            "probability target",
        )
        conditions.extend(target.conditions)
        inputs = merge_inputs(inputs, target.inputs)
        dependencies.update(target.dependencies)
        matching_probability = sp.Add(
            *(
                outcome.probability.expr
                * sp.Piecewise(
                    (1, sp.Eq(outcome.value.expr, target.expr)),
                    (0, True),
                )
                for outcome in distribution.outcomes
            )
        )
        return MathValue(
            matching_probability,
            DIMENSIONLESS,
            conditions,
            inputs,
            dependencies,
        )

    def _table_call(self, node: ast.Call, *, interpolate: bool) -> MathValue:
        name = "interpolate" if interpolate else "lookup"
        if len(node.args) != 2:
            raise ExpressionError(f"{name} expects TABLE and KEY", self.location)
        reference = node.args[0]
        if isinstance(reference, ast.Name):
            if self.entry is None:
                raise ExpressionError(
                    f"local table {reference.id!r} requires an entry context", self.location
                )
            entry_id, table_name = self.entry.id, reference.id
        elif isinstance(reference, ast.Attribute) and isinstance(reference.value, ast.Name):
            entry_id, table_name = reference.value.id, reference.attr
        else:
            raise ExpressionError(
                f"{name} table must be a local name or ENTRY.TABLE", self.location
            )
        key = self._build(node.args[1])
        return self.engine.lookup_table(
            entry_id,
            table_name,
            key,
            interpolate=interpolate,
        )

    def _builtin(self, name: str, args: list[MathValue]) -> MathValue:
        allowed = {"abs", "min", "max", "sqrt", "floor", "ceil"}
        if name not in allowed:
            raise ExpressionError(f"function {name!r} is not allowed or declared", self.location)
        if name in {"abs", "sqrt", "floor", "ceil"} and len(args) != 1:
            raise ExpressionError(f"{name} expects exactly one argument", self.location)
        if name in {"min", "max"} and len(args) < 1:
            raise ExpressionError(f"{name} expects at least one argument", self.location)
        for arg in args:
            self._require_numeric(arg, name)
        conditions = [condition for arg in args for condition in arg.conditions]
        inputs = merge_inputs(*(arg.inputs for arg in args))
        dependencies = set().union(*(arg.dependencies for arg in args)) if args else set()
        if name == "abs":
            return MathValue(sp.Abs(args[0].expr), args[0].dimension, conditions, inputs, dependencies)
        if name in {"min", "max"}:
            dimension = compatible_value_dimension(args, name)
            function = sp.Min if name == "min" else sp.Max
            return MathValue(function(*(arg.expr for arg in args)), dimension, conditions, inputs, dependencies)
        if name == "sqrt":
            conditions.append(sp.Ge(args[0].expr, 0, evaluate=False))
            return MathValue(sp.sqrt(args[0].expr), args[0].dimension.power(Fraction(1, 2)), conditions, inputs, dependencies)
        function = sp.floor if name == "floor" else sp.ceiling
        return MathValue(function(args[0].expr), args[0].dimension, conditions, inputs, dependencies)

    def _piecewise(self, name: str, args: list[MathValue]) -> MathValue:
        if name == "if_else":
            if len(args) != 3:
                raise ExpressionError("if_else expects condition, when_true, when_false", self.location)
            pairs = [(args[0], args[1])]
            default = args[2]
        else:
            if len(args) < 3 or len(args) % 2 == 0:
                raise ExpressionError(
                    "piecewise expects condition, value pairs followed by one default value",
                    self.location,
                )
            pairs = [(args[index], args[index + 1]) for index in range(0, len(args) - 1, 2)]
            default = args[-1]
        for condition, _value in pairs:
            self._require_boolean(condition, name)
        branch_values = [value for _condition, value in pairs] + [default]
        if any(value.is_boolean != default.is_boolean for value in branch_values):
            raise ExpressionError("piecewise branches must all be numeric or all boolean", self.location)
        dimension = compatible_value_dimension(branch_values, "piecewise branches")
        inputs = merge_inputs(
            *(item.inputs for pair in pairs for item in pair), default.inputs
        )
        dependencies = set().union(
            *(item.dependencies for pair in pairs for item in pair), default.dependencies
        )
        conditions = [item for condition, _value in pairs for item in condition.conditions]
        prior_false = sp.true
        sympy_pairs = []
        for condition, value in pairs:
            active = sp.And(prior_false, condition.expr)
            sympy_pairs.append((value.expr, active))
            conditions.extend(sp.Implies(active, item) for item in value.conditions)
            prior_false = sp.And(prior_false, sp.Not(condition.expr))
        sympy_pairs.append((default.expr, True))
        conditions.extend(sp.Implies(prior_false, item) for item in default.conditions)
        return MathValue(
            sp.Piecewise(*sympy_pairs),
            dimension,
            conditions,
            inputs,
            dependencies,
            default.is_boolean,
        )

    def _require_numeric(self, value: MathValue, context: str) -> None:
        if value.is_boolean:
            raise ExpressionError(f"{context} requires numeric operands", self.location)

    def _require_boolean(self, value: MathValue, context: str) -> None:
        if not value.is_boolean:
            raise ExpressionError(f"{context} requires boolean operands", self.location)

    def _finite_aggregate(self, node: ast.Call, operation: str) -> MathValue:
        if len(node.args) != 4:
            raise ExpressionError(
                f"{operation} expects {operation}(expression, index, lower, upper)",
                self.location,
            )
        index_node = node.args[1]
        if not isinstance(index_node, ast.Name):
            raise ExpressionError(f"{operation} index must be a plain identifier", self.location)
        index_name = index_node.id
        entry_names = set()
        if self.entry is not None:
            entry_names = (
                set(self.entry.inputs)
                | set(self.entry.fields)
                | set(self.entry.functions)
                | set(self.entry.outputs)
                | set(self.entry.aliases)
            )
        if index_name in self.local_values or index_name in entry_names:
            raise ExpressionError(
                f"{operation} index {index_name!r} shadows a declared name", self.location
            )
        lower = self._build(node.args[2])
        upper = self._build(node.args[3])
        self._require_numeric(lower, f"{operation} lower bound")
        self._require_numeric(upper, f"{operation} upper bound")
        require_same([lower.dimension, DIMENSIONLESS], f"{operation} lower bound")
        require_same([upper.dimension, DIMENSIONLESS], f"{operation} upper bound")
        if lower.expr.free_symbols or upper.expr.free_symbols or not lower.expr.is_Integer or not upper.expr.is_Integer:
            raise ExpressionError(f"{operation} bounds must be constant integers", self.location)
        start, end = int(lower.expr), int(upper.expr)
        terms = max(0, end - start + 1)
        if terms > MAX_SUM_TERMS:
            raise ExpressionError(
                f"finite {operation} exceeds {MAX_SUM_TERMS} terms", self.location
            )
        symbol = sp.Symbol(index_name, integer=True)
        nested = RestrictedCompiler(
            self.engine,
            self.entry,
            {**self.local_values, index_name: MathValue(symbol)},
            self.location,
        )
        nested.source = self.source
        summand = nested._build(node.args[0])
        self._require_numeric(summand, operation)
        rendered_terms = [
            summand.expr.subs(symbol, value) for value in range(start, end + 1)
        ]
        expr = (
            sp.Add(*rendered_terms)
            if operation == "sum"
            else sp.Mul(*rendered_terms)
        )
        conditions = [condition.subs(symbol, value) for value in range(start, end + 1) for condition in summand.conditions]
        conditions.extend(lower.conditions)
        conditions.extend(upper.conditions)
        return MathValue(
            expr,
            (
                summand.dimension
                if operation == "sum"
                else summand.dimension.power(Fraction(terms))
            ),
            conditions,
            merge_inputs(summand.inputs, lower.inputs, upper.inputs),
            set(summand.dependencies) | set(lower.dependencies) | set(upper.dependencies),
        )
