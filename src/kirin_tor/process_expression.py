"""Typed compilation and exact evaluation for bounded Process expressions.

This module deliberately owns a much smaller language than Python.  Python's
``ast`` module is used only as a parser; accepted nodes are immediately lowered
to immutable :mod:`kirin_tor.process_ir` nodes and execution recursively
interprets those nodes.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from math import isqrt
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from .errors import DomainError, ExpressionError, SourceLocation, UnitError
from .expression import ALLOWED_NODES
from .kirin_v2 import normalize_expression
from .limits import (
    MAX_ABS_INTEGER_EXPONENT,
    MAX_AST_DEPTH,
    MAX_AST_NODES,
    MAX_DIRECT_DEPENDENCIES,
    MAX_EXPRESSION_LENGTH,
)
from .process_ast import ExpressionAst
from .process_ir import (
    BinaryExpressionIR,
    BooleanExpressionIR,
    BooleanTypeIR,
    CallExpressionIR,
    ComparisonExpressionIR,
    EventIdTypeIR,
    ExpressionNodeIR,
    ListTypeIR,
    LiteralExpressionIR,
    MapTypeIR,
    NumberTypeIR,
    ObjectTypeIR,
    ReferenceExpressionIR,
    SymbolicTypeIR,
    SymbolRefIR,
    TypedExpressionIR,
    UnaryExpressionIR,
    ValueTypeIR,
)
from .process_model import ExpressionSymbolKind
from .units import DIMENSIONLESS, Dimension, UnitRegistry


_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "argmax",
        "argmin",
        "ceil",
        "contains",
        "empty",
        "filter",
        "floor",
        "get",
        "if_else",
        "max",
        "min",
        "put",
        "remove",
        "size",
        "sqrt",
        "sum",
    }
)


@dataclass(frozen=True, order=True)
class ProcessEventId:
    """Unforgeable-by-source stable event identity used as a map/key value."""

    value: str


@dataclass(frozen=True)
class FrozenMapValue:
    """Persistent finite map with canonical, insertion-independent storage."""

    entries: Tuple[Tuple[object, object], ...] = ()

    def as_dict(self) -> Dict[object, object]:
        return dict(self.entries)


ProcessValue = object
FunctionResolver = Callable[[SymbolRefIR, Tuple[ProcessValue, ...]], ProcessValue]


def _depth(node: ast.AST) -> int:
    children = list(ast.iter_child_nodes(node))
    return 1 if not children else 1 + max(_depth(child) for child in children)


def _path(node: ast.AST, location: Optional[SourceLocation]) -> str:
    pieces = []
    candidate = node
    while isinstance(candidate, ast.Attribute):
        if candidate.attr.startswith("__"):
            raise ExpressionError("private expression paths are not allowed", location)
        pieces.append(candidate.attr)
        candidate = candidate.value
    if not isinstance(candidate, ast.Name) or candidate.id.startswith("__"):
        raise ExpressionError("expression paths must begin with a declared name", location)
    pieces.append(candidate.id)
    return ".".join(reversed(pieces))


def _type_name(value_type: ValueTypeIR) -> str:
    if isinstance(value_type, NumberTypeIR):
        suffix = f" domain {value_type.domain_id}" if value_type.domain_id else ""
        return f"number<{value_type.dimension.render()}>{suffix}"
    if isinstance(value_type, BooleanTypeIR):
        return "boolean"
    if isinstance(value_type, SymbolicTypeIR):
        return f"symbol<{value_type.domain_id}>"
    if isinstance(value_type, EventIdTypeIR):
        return "event_id"
    if isinstance(value_type, ListTypeIR):
        return f"list[{_type_name(value_type.item_type)}, {value_type.capacity}]"
    if isinstance(value_type, MapTypeIR):
        return (
            f"map[{_type_name(value_type.key_type)}, "
            f"{_type_name(value_type.value_type)}, {value_type.capacity}]"
        )
    if isinstance(value_type, ObjectTypeIR):
        return f"object<{value_type.type_id}>"
    return type(value_type).__name__


def _same_value_type(left: ValueTypeIR, right: ValueTypeIR) -> bool:
    if isinstance(left, NumberTypeIR) and isinstance(right, NumberTypeIR):
        return left.dimension == right.dimension
    if isinstance(left, BooleanTypeIR) and isinstance(right, BooleanTypeIR):
        return True
    return left == right


def _numeric_type(dimension: Dimension, *, integer: bool = False) -> NumberTypeIR:
    return NumberTypeIR(
        "dimensionless" if dimension.is_dimensionless else dimension.render(),
        dimension,
        integer=integer if dimension.is_dimensionless else False,
    )


def _is_zero(node: ExpressionNodeIR) -> bool:
    return isinstance(node, LiteralExpressionIR) and node.value == 0


class ProcessExpressionCompiler:
    """Lower one expression with full result-type inference and checking."""

    def __init__(
        self,
        registry: UnitRegistry,
        symbols: Mapping[str, SymbolRefIR],
    ) -> None:
        self.registry = registry
        self.symbols = dict(symbols)
        self.location: Optional[SourceLocation] = None
        self.source = ""
        self.references: Dict[Tuple[str, str, ExpressionSymbolKind], SymbolRefIR] = {}

    def compile(
        self, source: ExpressionAst, expected: Optional[ValueTypeIR]
    ) -> TypedExpressionIR:
        self.location = source.location
        self.source = normalize_expression(source.text, self.registry.units)
        if len(self.source) > MAX_EXPRESSION_LENGTH:
            raise ExpressionError(
                f"expression exceeds {MAX_EXPRESSION_LENGTH} characters", self.location
            )
        try:
            tree = ast.parse(self.source, mode="eval")
        except SyntaxError as exc:
            raise ExpressionError(
                f"invalid expression syntax at column {exc.offset}: {exc.msg}",
                self.location,
            ) from exc
        nodes = list(ast.walk(tree))
        if len(nodes) > MAX_AST_NODES:
            raise ExpressionError(
                f"expression exceeds {MAX_AST_NODES} AST nodes", self.location
            )
        for node in nodes:
            if type(node) not in ALLOWED_NODES:
                detail = (
                    "'^' is not supported; use '**' for exponentiation"
                    if isinstance(node, ast.BitXor)
                    else f"expression syntax {type(node).__name__} is not allowed"
                )
                raise ExpressionError(detail, self.location)
        if _depth(tree) > MAX_AST_DEPTH:
            raise ExpressionError(
                f"expression exceeds AST depth {MAX_AST_DEPTH}", self.location
            )
        self.references = {}
        expression = self._build(tree.body, expected)
        if expected is not None:
            self._require_assignable(expression, expected, "expression result")
        if len(self.references) > MAX_DIRECT_DEPENDENCIES:
            raise ExpressionError(
                f"expression exceeds {MAX_DIRECT_DEPENDENCIES} direct dependencies",
                self.location,
            )
        references = tuple(
            self.references[key]
            for key in sorted(
                self.references, key=lambda item: (item[0], item[1], item[2].value)
            )
        )
        return TypedExpressionIR(
            self.source, expected or expression.value_type, references, self.location, expression
        )

    def _include(self, reference: SymbolRefIR) -> ReferenceExpressionIR:
        key = (reference.owner_id, reference.id, reference.kind)
        self.references[key] = reference
        return ReferenceExpressionIR(reference, reference.value_type)

    def _number_literal(
        self, node: ast.Constant, expected: Optional[ValueTypeIR]
    ) -> LiteralExpressionIR:
        token = ast.get_source_segment(self.source, node)
        if token is None:
            raise ExpressionError("could not preserve numeric literal text", self.location)
        try:
            value = Fraction(Decimal(token))
        except (ValueError, ArithmeticError) as exc:
            raise ExpressionError(f"invalid numeric literal {token!r}", self.location) from exc
        value_type: ValueTypeIR = _numeric_type(
            DIMENSIONLESS, integer=value.denominator == 1
        )
        # A top-level scalar literal is expressed in the declared target unit.
        # This also gives exact zero its conventional unit-polymorphic meaning.
        if isinstance(expected, NumberTypeIR):
            value_type = expected
            value *= self.registry.scale(expected.unit_name, self.location)
        return LiteralExpressionIR(value, value_type)

    def _name(
        self, name: str, expected: Optional[ValueTypeIR]
    ) -> ExpressionNodeIR:
        if name == "true":
            return LiteralExpressionIR(True, BooleanTypeIR())
        if name == "false":
            return LiteralExpressionIR(False, BooleanTypeIR())
        if name == "empty":
            if not isinstance(expected, (ListTypeIR, MapTypeIR)):
                raise ExpressionError(
                    "empty requires a declared list or map result type", self.location
                )
            return CallExpressionIR("empty", (), expected)
        reference = self.symbols.get(name)
        if reference is None and isinstance(expected, SymbolicTypeIR):
            domain = self.registry.domains[expected.domain_id]
            if name in domain.allowed_values:
                reference = SymbolRefIR(
                    f"@domain.{expected.domain_id}",
                    name,
                    ExpressionSymbolKind.STATIC_MEMBER,
                    expected,
                )
        if reference is None and name in self.registry.units:
            reference = SymbolRefIR(
                "@units",
                name,
                ExpressionSymbolKind.UNIT,
                NumberTypeIR(name, self.registry.parse_unit(name, self.location)),
            )
        if reference is None:
            raise ExpressionError(f"undeclared process value {name!r}", self.location)
        return self._include(reference)

    def _build(
        self, node: ast.AST, expected: Optional[ValueTypeIR] = None
    ) -> ExpressionNodeIR:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return LiteralExpressionIR(node.value, BooleanTypeIR())
            if not isinstance(node.value, (int, float)):
                raise ExpressionError(
                    "only integer and decimal numeric literals are allowed", self.location
                )
            return self._number_literal(node, expected)
        if isinstance(node, ast.Name):
            return self._name(node.id, expected)
        if isinstance(node, ast.Attribute):
            return self._name(_path(node, self.location), expected)
        if isinstance(node, ast.UnaryOp):
            operand = self._build(
                node.operand, expected if isinstance(node.op, (ast.UAdd, ast.USub)) else None
            )
            if isinstance(node.op, ast.Not):
                self._require_boolean(operand, "not")
                return UnaryExpressionIR("not", operand, BooleanTypeIR())
            self._require_number(operand, "unary arithmetic")
            operator = "+" if isinstance(node.op, ast.UAdd) else "-"
            return UnaryExpressionIR(operator, operand, operand.value_type)
        if isinstance(node, ast.BinOp):
            return self._binary(node)
        if isinstance(node, ast.Compare):
            return self._comparison(node)
        if isinstance(node, ast.BoolOp):
            values = tuple(self._build(item, BooleanTypeIR()) for item in node.values)
            for value in values:
                self._require_boolean(value, "boolean operation")
            return BooleanExpressionIR(
                "and" if isinstance(node.op, ast.And) else "or",
                values,
                BooleanTypeIR(),
            )
        if isinstance(node, ast.Call):
            return self._call(node, expected)
        raise ExpressionError(
            f"unsupported expression node {type(node).__name__}", self.location
        )

    def _binary(self, node: ast.BinOp) -> ExpressionNodeIR:
        left = self._build(node.left)
        right = self._build(node.right)
        self._require_number(left, "arithmetic")
        self._require_number(right, "arithmetic")
        left_type = left.value_type
        right_type = right.value_type
        assert isinstance(left_type, NumberTypeIR)
        assert isinstance(right_type, NumberTypeIR)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if left_type.dimension != right_type.dimension:
                if _is_zero(left):
                    dimension = right_type.dimension
                elif _is_zero(right):
                    dimension = left_type.dimension
                else:
                    raise UnitError(
                        "incompatible units in addition/subtraction: "
                        f"{left_type.dimension.render()}, {right_type.dimension.render()}",
                        self.location,
                    )
            else:
                dimension = left_type.dimension
            integer = left_type.integer and right_type.integer
            operator = "+" if isinstance(node.op, ast.Add) else "-"
        elif isinstance(node.op, ast.Mult):
            dimension = left_type.dimension.multiply(right_type.dimension)
            integer = left_type.integer and right_type.integer
            operator = "*"
        elif isinstance(node.op, ast.Div):
            dimension = left_type.dimension.divide(right_type.dimension)
            integer = False
            operator = "/"
        elif isinstance(node.op, ast.Pow):
            if not right_type.dimension.is_dimensionless:
                raise UnitError("an exponent must be dimensionless", self.location)
            if not isinstance(right, LiteralExpressionIR) or not isinstance(
                right.value, Fraction
            ):
                if not left_type.dimension.is_dimensionless:
                    raise UnitError(
                        "a dimensioned base requires a constant rational exponent",
                        self.location,
                    )
                dimension = DIMENSIONLESS
            else:
                if abs(right.value) > MAX_ABS_INTEGER_EXPONENT:
                    raise ExpressionError(
                        f"absolute exponent may not exceed {MAX_ABS_INTEGER_EXPONENT}",
                        self.location,
                    )
                dimension = left_type.dimension.power(right.value)
            integer = (
                left_type.integer
                and isinstance(right, LiteralExpressionIR)
                and isinstance(right.value, Fraction)
                and right.value.denominator == 1
                and right.value >= 0
            )
            operator = "**"
        else:
            raise ExpressionError("unsupported binary operator", self.location)
        return BinaryExpressionIR(
            operator, left, right, _numeric_type(dimension, integer=integer)
        )

    def _comparison(self, node: ast.Compare) -> ExpressionNodeIR:
        operands = [self._build(node.left)]
        for comparator in node.comparators:
            operands.append(self._build(comparator, operands[-1].value_type))
        operators = []
        names = {
            ast.Lt: "<",
            ast.LtE: "<=",
            ast.Gt: ">",
            ast.GtE: ">=",
            ast.Eq: "==",
            ast.NotEq: "!=",
        }
        for left, operator, right in zip(operands, node.ops, operands[1:]):
            name = names.get(type(operator))
            if name is None:
                raise ExpressionError("unsupported comparison operator", self.location)
            if name in {"<", "<=", ">", ">="}:
                self._require_number(left, "ordered comparison")
                self._require_number(right, "ordered comparison")
            if not _same_value_type(left.value_type, right.value_type):
                if not (
                    isinstance(left.value_type, NumberTypeIR)
                    and isinstance(right.value_type, NumberTypeIR)
                    and (_is_zero(left) or _is_zero(right))
                ):
                    raise ExpressionError(
                        "comparison operands have incompatible types: "
                        f"{_type_name(left.value_type)} and {_type_name(right.value_type)}",
                        self.location,
                    )
            operators.append(name)
        return ComparisonExpressionIR(
            tuple(operators), tuple(operands), BooleanTypeIR()
        )

    def _call(
        self, node: ast.Call, expected: Optional[ValueTypeIR]
    ) -> ExpressionNodeIR:
        if node.keywords:
            raise ExpressionError("keyword arguments are not allowed", self.location)
        if isinstance(node.func, (ast.Name, ast.Attribute)):
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else _path(node.func, self.location)
            )
        else:
            raise ExpressionError("only declared named functions are allowed", self.location)
        if name not in _BUILTINS:
            reference = self.symbols.get(name)
            if reference is None or reference.kind is not ExpressionSymbolKind.FUNCTION:
                raise ExpressionError(
                    f"undeclared process function {name!r}", self.location
                )
            self._include(reference)
            arguments = tuple(self._build(argument) for argument in node.args)
            return CallExpressionIR(name, arguments, reference.value_type)
        return self._builtin(name, node.args, expected)

    def _builtin(
        self,
        name: str,
        source_arguments: Sequence[ast.AST],
        expected: Optional[ValueTypeIR],
    ) -> ExpressionNodeIR:
        def arity(*allowed: int) -> None:
            if len(source_arguments) not in allowed:
                rendered = " or ".join(str(item) for item in allowed)
                raise ExpressionError(
                    f"{name} expects {rendered} argument(s)", self.location
                )

        if name == "empty":
            arity(0)
            if not isinstance(expected, (ListTypeIR, MapTypeIR)):
                raise ExpressionError(
                    "empty requires a declared list or map result type", self.location
                )
            return CallExpressionIR(name, (), expected)
        if name == "if_else":
            arity(3)
            condition = self._build(source_arguments[0], BooleanTypeIR())
            self._require_boolean(condition, "if_else condition")
            left = self._build(source_arguments[1], expected)
            right = self._build(source_arguments[2], left.value_type)
            if not _same_value_type(left.value_type, right.value_type):
                raise ExpressionError(
                    "if_else branches have incompatible types: "
                    f"{_type_name(left.value_type)} and {_type_name(right.value_type)}",
                    self.location,
                )
            return CallExpressionIR(
                name, (condition, left, right), expected or left.value_type
            )
        if name in {"min", "max"}:
            if not source_arguments:
                raise ExpressionError(f"{name} expects at least one argument", self.location)
            arguments = [self._build(source_arguments[0], expected)]
            self._require_number(arguments[0], name)
            for source in source_arguments[1:]:
                value = self._build(source, arguments[0].value_type)
                self._require_number(value, name)
                if not _same_value_type(arguments[0].value_type, value.value_type):
                    raise UnitError(f"{name} arguments must use compatible units", self.location)
                arguments.append(value)
            return CallExpressionIR(
                name, tuple(arguments), expected or arguments[0].value_type
            )
        if name in {"abs", "ceil", "floor", "sqrt"}:
            arity(1)
            argument = self._build(source_arguments[0], expected)
            self._require_number(argument, name)
            value_type = argument.value_type
            assert isinstance(value_type, NumberTypeIR)
            if name == "sqrt":
                value_type = _numeric_type(value_type.dimension.power(Fraction(1, 2)))
            elif name in {"ceil", "floor"}:
                value_type = _numeric_type(value_type.dimension, integer=True)
            return CallExpressionIR(name, (argument,), value_type)
        if name == "size":
            arity(1)
            collection = self._build(source_arguments[0])
            self._require_collection(collection, name)
            return CallExpressionIR(
                name,
                (collection,),
                NumberTypeIR("dimensionless", DIMENSIONLESS, "count", True),
            )
        if name == "contains":
            arity(2)
            collection = self._build(source_arguments[0])
            self._require_collection(collection, name)
            collection_type = collection.value_type
            item_type = (
                collection_type.key_type
                if isinstance(collection_type, MapTypeIR)
                else collection_type.item_type
            )
            item = self._build(source_arguments[1], item_type)
            self._require_assignable(item, item_type, "contains argument")
            return CallExpressionIR(name, (collection, item), BooleanTypeIR())
        if name == "get":
            arity(2)
            collection = self._build(source_arguments[0])
            self._require_collection(collection, name)
            collection_type = collection.value_type
            if isinstance(collection_type, MapTypeIR):
                key_type = collection_type.key_type
                result_type = collection_type.value_type
            else:
                key_type = NumberTypeIR(
                    "dimensionless", DIMENSIONLESS, "nonnegative_integer", True
                )
                result_type = collection_type.item_type
            key = self._build(source_arguments[1], key_type)
            self._require_assignable(key, key_type, "get key")
            return CallExpressionIR(name, (collection, key), result_type)
        if name == "put":
            arity(3)
            collection = self._build(source_arguments[0], expected)
            if not isinstance(collection.value_type, MapTypeIR):
                raise ExpressionError("put requires a bounded map", self.location)
            key = self._build(source_arguments[1], collection.value_type.key_type)
            value = self._build(source_arguments[2], collection.value_type.value_type)
            self._require_assignable(key, collection.value_type.key_type, "put key")
            self._require_assignable(value, collection.value_type.value_type, "put value")
            return CallExpressionIR(name, (collection, key, value), collection.value_type)
        if name == "remove":
            arity(2)
            collection = self._build(source_arguments[0], expected)
            if not isinstance(collection.value_type, MapTypeIR):
                raise ExpressionError("remove requires a bounded map", self.location)
            key = self._build(source_arguments[1], collection.value_type.key_type)
            self._require_assignable(key, collection.value_type.key_type, "remove key")
            return CallExpressionIR(name, (collection, key), collection.value_type)
        if name in {"all", "any", "sum", "argmin", "argmax"}:
            arity(1)
            collection = self._build(source_arguments[0])
            self._require_collection(collection, name)
            collection_type = collection.value_type
            item_type = (
                collection_type.value_type
                if isinstance(collection_type, MapTypeIR)
                else collection_type.item_type
            )
            if name in {"all", "any"}:
                if not isinstance(item_type, BooleanTypeIR):
                    raise ExpressionError(f"{name} requires boolean items", self.location)
                result_type: ValueTypeIR = BooleanTypeIR()
            elif name == "sum":
                if not isinstance(item_type, NumberTypeIR):
                    raise ExpressionError("sum requires numeric items", self.location)
                result_type = item_type
            else:
                if not isinstance(item_type, NumberTypeIR):
                    raise ExpressionError(f"{name} requires numeric values", self.location)
                result_type = (
                    collection_type.key_type
                    if isinstance(collection_type, MapTypeIR)
                    else NumberTypeIR(
                        "dimensionless", DIMENSIONLESS, "nonnegative_integer", True
                    )
                )
            return CallExpressionIR(name, (collection,), result_type)
        if name == "filter":
            arity(2)
            collection = self._build(source_arguments[0], expected)
            self._require_collection(collection, name)
            collection_type = collection.value_type
            if isinstance(collection_type, ListTypeIR):
                mask_type: ValueTypeIR = ListTypeIR(
                    BooleanTypeIR(), collection_type.capacity
                )
            else:
                mask_type = MapTypeIR(
                    collection_type.key_type,
                    BooleanTypeIR(),
                    collection_type.capacity,
                )
            mask = self._build(source_arguments[1], mask_type)
            self._require_assignable(mask, mask_type, "filter mask")
            return CallExpressionIR(name, (collection, mask), collection_type)
        raise ExpressionError(f"unsupported process builtin {name!r}", self.location)

    def _require_number(self, node: ExpressionNodeIR, context: str) -> None:
        if not isinstance(node.value_type, NumberTypeIR):
            raise ExpressionError(f"{context} requires numeric values", self.location)

    def _require_boolean(self, node: ExpressionNodeIR, context: str) -> None:
        if not isinstance(node.value_type, BooleanTypeIR):
            raise ExpressionError(f"{context} requires boolean values", self.location)

    def _require_collection(self, node: ExpressionNodeIR, context: str) -> None:
        if not isinstance(node.value_type, (ListTypeIR, MapTypeIR)):
            raise ExpressionError(f"{context} requires a bounded collection", self.location)

    def _require_assignable(
        self, node: ExpressionNodeIR, expected: ValueTypeIR, context: str
    ) -> None:
        actual = node.value_type
        if isinstance(expected, NumberTypeIR) and isinstance(actual, NumberTypeIR):
            if expected.dimension != actual.dimension and not _is_zero(node):
                raise UnitError(
                    f"{context} requires {expected.dimension.render()}, got "
                    f"{actual.dimension.render()}",
                    self.location,
                )
            if expected.integer and not actual.integer:
                raise ExpressionError(f"{context} must be integer-valued", self.location)
            return
        if isinstance(expected, BooleanTypeIR) and isinstance(actual, BooleanTypeIR):
            return
        if actual != expected:
            raise ExpressionError(
                f"{context} requires {_type_name(expected)}, got {_type_name(actual)}",
                self.location,
            )


def compile_process_expression(
    source: ExpressionAst,
    expected: Optional[ValueTypeIR],
    symbols: Mapping[str, SymbolRefIR],
    registry: UnitRegistry,
) -> TypedExpressionIR:
    return ProcessExpressionCompiler(registry, symbols).compile(source, expected)


def _stable_key(value: object) -> Tuple[str, str]:
    if isinstance(value, ProcessEventId):
        return ("event_id", value.value)
    if isinstance(value, Fraction):
        return ("number", f"{value.numerator}/{value.denominator}")
    if isinstance(value, bool):
        return ("boolean", "1" if value else "0")
    if isinstance(value, str):
        return ("symbol", value)
    raise DomainError(f"value {value!r} cannot be used as a stable map key")


def _exact_power(base: Fraction, exponent: Fraction) -> Fraction:
    if exponent.denominator == 1:
        if base == 0 and exponent <= 0:
            raise DomainError("zero cannot be raised to a non-positive exponent")
        return base ** exponent.numerator
    if base < 0:
        raise DomainError("fractional powers require a nonnegative base")
    numerator_root = isqrt(base.numerator)
    denominator_root = isqrt(base.denominator)
    if exponent.denominator != 2 or (
        numerator_root * numerator_root != base.numerator
        or denominator_root * denominator_root != base.denominator
    ):
        raise DomainError("power result is not an exact rational value")
    root = Fraction(numerator_root, denominator_root)
    return root ** exponent.numerator


def evaluate_process_expression(
    expression: TypedExpressionIR,
    values: Mapping[SymbolRefIR, ProcessValue],
    registry: UnitRegistry,
    *,
    function_resolver: Optional[FunctionResolver] = None,
) -> ProcessValue:
    """Evaluate already-typed Process IR with exact, persistent values."""

    if expression.node is None:
        raise ExpressionError(
            "process expression has no executable IR", expression.location
        )

    def build(node: ExpressionNodeIR) -> ProcessValue:
        if isinstance(node, LiteralExpressionIR):
            return node.value
        if isinstance(node, ReferenceExpressionIR):
            reference = node.reference
            if reference in values:
                return values[reference]
            if reference.kind is ExpressionSymbolKind.UNIT:
                return registry.scale(reference.id, expression.location)
            if reference.kind is ExpressionSymbolKind.STATIC_MEMBER:
                return reference.id
            raise ExpressionError(
                f"no runtime value for {reference.owner_id}.{reference.id}",
                expression.location,
            )
        if isinstance(node, UnaryExpressionIR):
            value = build(node.operand)
            if node.operator == "not":
                return not _boolean(value, expression.location)
            number = _number(value, expression.location)
            return number if node.operator == "+" else -number
        if isinstance(node, BinaryExpressionIR):
            left = _number(build(node.left), expression.location)
            right = _number(build(node.right), expression.location)
            if node.operator == "+":
                return left + right
            if node.operator == "-":
                return left - right
            if node.operator == "*":
                return left * right
            if node.operator == "/":
                if right == 0:
                    raise DomainError("division by zero", expression.location)
                return left / right
            if node.operator == "**":
                return _exact_power(left, right)
            raise ExpressionError(f"unknown binary operator {node.operator!r}")
        if isinstance(node, ComparisonExpressionIR):
            operands = [build(item) for item in node.operands]
            for left, operator, right in zip(
                operands, node.operators, operands[1:]
            ):
                result = {
                    "<": lambda: left < right,
                    "<=": lambda: left <= right,
                    ">": lambda: left > right,
                    ">=": lambda: left >= right,
                    "==": lambda: left == right,
                    "!=": lambda: left != right,
                }[operator]()
                if not result:
                    return False
            return True
        if isinstance(node, BooleanExpressionIR):
            if node.operator == "and":
                return all(_boolean(build(item), expression.location) for item in node.operands)
            return any(_boolean(build(item), expression.location) for item in node.operands)
        if isinstance(node, CallExpressionIR):
            if node.function == "if_else":
                condition = _boolean(build(node.arguments[0]), expression.location)
                return build(node.arguments[1] if condition else node.arguments[2])
            if node.function == "empty":
                return FrozenMapValue() if isinstance(node.value_type, MapTypeIR) else ()
            arguments = tuple(build(item) for item in node.arguments)
            return _evaluate_call(
                node, arguments, expression.location, function_resolver
            )
        raise ExpressionError(f"unknown Process expression IR {type(node).__name__}")

    value = build(expression.node)
    validate_process_value(value, expression.result_type, registry, expression.location)
    return value


def _number(value: object, location: Optional[SourceLocation]) -> Fraction:
    if isinstance(value, bool) or not isinstance(value, Fraction):
        raise ExpressionError("runtime value is not numeric", location)
    return value


def _boolean(value: object, location: Optional[SourceLocation]) -> bool:
    if not isinstance(value, bool):
        raise ExpressionError("runtime value is not boolean", location)
    return value


def _evaluate_call(
    node: CallExpressionIR,
    arguments: Tuple[ProcessValue, ...],
    location: Optional[SourceLocation],
    function_resolver: Optional[FunctionResolver],
) -> ProcessValue:
    name = node.function
    if name == "min":
        return min(_number(item, location) for item in arguments)
    if name == "max":
        return max(_number(item, location) for item in arguments)
    if name == "abs":
        return abs(_number(arguments[0], location))
    if name == "ceil":
        value = _number(arguments[0], location)
        return Fraction(-(-value.numerator // value.denominator))
    if name == "floor":
        value = _number(arguments[0], location)
        return Fraction(value.numerator // value.denominator)
    if name == "sqrt":
        return _exact_power(_number(arguments[0], location), Fraction(1, 2))
    if name == "size":
        collection = arguments[0]
        return Fraction(len(collection.entries if isinstance(collection, FrozenMapValue) else collection))
    if name == "contains":
        collection, key = arguments
        return key in (collection.as_dict() if isinstance(collection, FrozenMapValue) else collection)
    if name == "get":
        collection, key = arguments
        if isinstance(collection, FrozenMapValue):
            mapping = collection.as_dict()
            if key not in mapping:
                raise DomainError("get key is absent from the bounded map", location)
            return mapping[key]
        index = _number(key, location)
        if index.denominator != 1 or not 0 <= index < len(collection):
            raise DomainError("list index is outside the bounded list", location)
        return collection[index.numerator]
    if name == "put":
        collection, key, value = arguments
        assert isinstance(collection, FrozenMapValue)
        mapping = collection.as_dict()
        if key not in mapping and len(mapping) >= node.value_type.capacity:
            raise DomainError("put would exceed bounded map capacity", location)
        mapping[key] = value
        return FrozenMapValue(
            tuple(sorted(mapping.items(), key=lambda item: _stable_key(item[0])))
        )
    if name == "remove":
        collection, key = arguments
        assert isinstance(collection, FrozenMapValue)
        mapping = collection.as_dict()
        mapping.pop(key, None)
        return FrozenMapValue(
            tuple(sorted(mapping.items(), key=lambda item: _stable_key(item[0])))
        )
    if name == "filter":
        collection, mask = arguments
        if isinstance(collection, FrozenMapValue):
            assert isinstance(mask, FrozenMapValue)
            source = collection.as_dict()
            flags = mask.as_dict()
            if set(source) != set(flags):
                raise DomainError("map filter mask must contain exactly the same keys", location)
            return FrozenMapValue(
                tuple(
                    (key, source[key])
                    for key in sorted(source, key=_stable_key)
                    if _boolean(flags[key], location)
                )
            )
        if not isinstance(mask, tuple) or len(collection) != len(mask):
            raise DomainError("list filter mask must have the same length", location)
        return tuple(
            item
            for item, keep in zip(collection, mask)
            if _boolean(keep, location)
        )
    if name in {"all", "any", "sum", "argmin", "argmax"}:
        collection = arguments[0]
        if isinstance(collection, FrozenMapValue):
            items = collection.entries
            values = tuple(value for _, value in items)
        else:
            items = tuple(enumerate(collection))
            values = tuple(collection)
        if name == "all":
            return all(_boolean(value, location) for value in values)
        if name == "any":
            return any(_boolean(value, location) for value in values)
        if name == "sum":
            return sum((_number(value, location) for value in values), Fraction(0))
        if not items:
            raise DomainError(f"{name} requires a non-empty collection", location)
        selector = min if name == "argmin" else max
        chosen = selector(items, key=lambda item: (_number(item[1], location), _stable_key(item[0])))
        return chosen[0] if isinstance(collection, FrozenMapValue) else Fraction(chosen[0])
    if function_resolver is not None:
        # Only a caller-owned, already-validated Kirin function resolver may be
        # supplied here; source can never inject a Python callable.
        return function_resolver(
            SymbolRefIR("", name, ExpressionSymbolKind.FUNCTION, node.value_type),
            arguments,
        )
    raise ExpressionError(f"no evaluator for declared process function {name!r}", location)


def validate_process_value(
    value: ProcessValue,
    value_type: ValueTypeIR,
    registry: UnitRegistry,
    location: Optional[SourceLocation] = None,
) -> None:
    """Enforce the closed runtime representation and declared domain."""

    if isinstance(value_type, BooleanTypeIR):
        if not isinstance(value, bool):
            raise DomainError("value is not boolean", location)
        return
    if isinstance(value_type, NumberTypeIR):
        number = _number(value, location)
        if value_type.integer and number.denominator != 1:
            raise DomainError("value must be an integer", location)
        if value_type.domain_id:
            domain = registry.domains[value_type.domain_id]
            scale = registry.scale(domain.unit_name, location)
            if domain.minimum is not None and number < Fraction(domain.minimum) * scale:
                raise DomainError(
                    f"value is below domain {value_type.domain_id!r} minimum", location
                )
            if domain.maximum is not None and number > Fraction(domain.maximum) * scale:
                raise DomainError(
                    f"value is above domain {value_type.domain_id!r} maximum", location
                )
        return
    if isinstance(value_type, SymbolicTypeIR):
        domain = registry.domains[value_type.domain_id]
        if not isinstance(value, str) or value not in domain.allowed_values:
            raise DomainError(
                f"value is not a member of symbolic domain {value_type.domain_id!r}",
                location,
            )
        return
    if isinstance(value_type, EventIdTypeIR):
        if not isinstance(value, ProcessEventId):
            raise DomainError("value is not an event_id", location)
        return
    if isinstance(value_type, ListTypeIR):
        if not isinstance(value, tuple) or len(value) > value_type.capacity:
            raise DomainError("value is not a valid bounded list", location)
        for item in value:
            validate_process_value(item, value_type.item_type, registry, location)
        return
    if isinstance(value_type, MapTypeIR):
        if not isinstance(value, FrozenMapValue) or len(value.entries) > value_type.capacity:
            raise DomainError("value is not a valid bounded map", location)
        seen = set()
        for key, item in value.entries:
            validate_process_value(key, value_type.key_type, registry, location)
            validate_process_value(item, value_type.value_type, registry, location)
            if key in seen:
                raise DomainError("bounded map contains a duplicate key", location)
            seen.add(key)
        return
    if isinstance(value_type, ObjectTypeIR):
        if not isinstance(value, tuple):
            raise DomainError("closed object runtime values must be immutable tuples", location)
        return
    raise DomainError(f"unsupported Process value type {_type_name(value_type)}", location)
