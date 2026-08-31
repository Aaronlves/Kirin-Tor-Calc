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
            if name in self.entry.fields or name in self.entry.outputs:
                return self.engine.resolve_member(self.entry.id, name)
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
        if name == "sum":
            return self._finite_sum(node)
        if name in {"if_else", "piecewise"}:
            args = [self._build(arg) for arg in node.args]
            return self._piecewise(name, args)
        args = [self._build(arg) for arg in node.args]
        return self._builtin(name, args)

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

    def _finite_sum(self, node: ast.Call) -> MathValue:
        if len(node.args) != 4:
            raise ExpressionError("sum expects sum(expression, index, lower, upper)", self.location)
        index_node = node.args[1]
        if not isinstance(index_node, ast.Name):
            raise ExpressionError("sum index must be a plain identifier", self.location)
        index_name = index_node.id
        entry_names = set()
        if self.entry is not None:
            entry_names = (
                set(self.entry.inputs)
                | set(self.entry.fields)
                | set(self.entry.functions)
                | set(self.entry.outputs)
            )
        if index_name in self.local_values or index_name in entry_names:
            raise ExpressionError(f"sum index {index_name!r} shadows a declared name", self.location)
        lower = self._build(node.args[2])
        upper = self._build(node.args[3])
        self._require_numeric(lower, "sum lower bound")
        self._require_numeric(upper, "sum upper bound")
        require_same([lower.dimension, DIMENSIONLESS], "sum lower bound")
        require_same([upper.dimension, DIMENSIONLESS], "sum upper bound")
        if lower.expr.free_symbols or upper.expr.free_symbols or not lower.expr.is_Integer or not upper.expr.is_Integer:
            raise ExpressionError("sum bounds must be constant integers", self.location)
        start, end = int(lower.expr), int(upper.expr)
        terms = max(0, end - start + 1)
        if terms > MAX_SUM_TERMS:
            raise ExpressionError(f"finite sum exceeds {MAX_SUM_TERMS} terms", self.location)
        symbol = sp.Symbol(index_name, integer=True)
        nested = RestrictedCompiler(
            self.engine,
            self.entry,
            {**self.local_values, index_name: MathValue(symbol)},
            self.location,
        )
        nested.source = self.source
        summand = nested._build(node.args[0])
        self._require_numeric(summand, "sum")
        expr = sp.Add(*(summand.expr.subs(symbol, value) for value in range(start, end + 1)))
        conditions = [condition.subs(symbol, value) for value in range(start, end + 1) for condition in summand.conditions]
        conditions.extend(lower.conditions)
        conditions.extend(upper.conditions)
        return MathValue(
            expr,
            summand.dimension,
            conditions,
            merge_inputs(summand.inputs, lower.inputs, upper.inputs),
            set(summand.dependencies) | set(lower.dependencies) | set(upper.dependencies),
        )
