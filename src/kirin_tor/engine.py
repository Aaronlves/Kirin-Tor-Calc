"""Entry resolution, parameter precedence, domain checks, and exact evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Mapping, Optional, Sequence, Set

import sympy as sp

from .errors import (
    DependencyCycleError,
    DomainError,
    ExpressionError,
    ParameterError,
    ReferenceError,
    SchemaError,
    SourceLocation,
    UnitError,
    ValidationErrors,
    KTError,
)
from .expression import (
    DistributionOutcome,
    FiniteDistribution,
    MathValue,
    RestrictedCompiler,
    merge_inputs,
    parse_exact_number,
)
from .limits import (
    MAX_DEPENDENCY_DEPTH,
    MAX_DEPENDENCY_DOCUMENTS,
    MAX_EXPANDED_NODES,
    MAX_NUMERIC_PRECISION,
    MAX_SCAN_POINTS,
    MAX_STRUCTURE_DEPTH,
)
from .schema import (
    Document,
    Entry,
    InputSpec,
    Preset,
    StructureTypeSpec,
    StructuredObjectSpec,
    _parse_input,
)
from .units import DIMENSIONLESS, Dimension
from .workspace import Workspace


TARGET_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
NUMBER_LITERAL_RE = re.compile(
    r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+)$"
)


@dataclass
class PreparedValue:
    value: MathValue
    expr: sp.Expr
    conditions: list
    parameters: Dict[str, sp.Basic]
    missing: Set[str]


class Engine:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self._symbols: Dict[str, sp.Symbol] = {}
        self._symbol_specs: Dict[str, InputSpec] = {}
        self._member_cache: Dict[tuple[str, str], MathValue] = {}
        self._object_member_cache: Dict[tuple[str, str, tuple[str, ...]], MathValue] = {}
        self._distribution_cache: Dict[tuple[str, str], FiniteDistribution] = {}
        self._stack: list[str] = []
        self._constraint_entries: Set[str] = set()

    def unit_scale_expr(self, unit_name: str) -> sp.Rational:
        scale = self.workspace.units.scale(unit_name)
        return sp.Rational(scale.numerator, scale.denominator)

    def target_unit_name(self, target: str, fallback_dimension: Dimension) -> str:
        """Return the unit explicitly chosen for a declared target when available."""
        normalized = target.strip()
        if TARGET_RE.fullmatch(normalized):
            parts = normalized.split(".")
            entry = self.workspace.entries.get(parts[0])
            if entry is not None:
                member = parts[1]
                if member in entry.inputs:
                    return entry.inputs[member].unit_name
                if member in entry.fields:
                    return entry.fields[member].get("unit", "dimensionless")
                if member in entry.outputs:
                    return entry.outputs[member].get("unit", "dimensionless")
                if member in entry.objects and len(parts) > 2:
                    return self._object_member_unit(entry, entry.objects[member], tuple(parts[2:]))
        return self.workspace.units.render(fallback_dimension)

    def input_symbol(self, name: str, spec: InputSpec) -> sp.Symbol:
        key = spec.key
        if key in self._symbol_specs and self._symbol_specs[key] != spec:
            raise ExpressionError(f"input {key!r} has conflicting declarations")
        self._symbol_specs[key] = spec
        if key not in self._symbols:
            self._symbols[key] = (
                sp.Symbol(key, boolean=True)
                if spec.value_type == "boolean"
                else sp.Symbol(key, real=True)
            )
        return self._symbols[key]

    def global_input(self, name: str) -> Optional[InputSpec]:
        if "." in name:
            entry_id, local_name = name.split(".", 1)
            entry = self.workspace.entries.get(entry_id)
            return entry.inputs.get(local_name) if entry else None
        found = []
        for entry in self.workspace.entries.values():
            if name in entry.inputs:
                found.append(entry.inputs[name])
        if len(found) > 1:
            choices = ", ".join(sorted(spec.key for spec in found))
            raise ExpressionError(f"input {name!r} is ambiguous; use one of: {choices}")
        return found[0] if found else None

    def resolve_input_key(
        self, name: str, candidates: Optional[Mapping[str, InputSpec]] = None
    ) -> str:
        pool = dict(candidates) if candidates is not None else {
            spec.key: spec for entry in self.workspace.entries.values() for spec in entry.inputs.values()
        }
        if name in pool:
            return name
        matches = [key for key, spec in pool.items() if spec.name == name]
        if not matches:
            raise ParameterError(f"undeclared parameter {name!r}")
        if len(matches) > 1:
            raise ParameterError(
                f"parameter {name!r} is ambiguous; use one of: " + ", ".join(sorted(matches))
            )
        return matches[0]

    def input_conditions(self, spec: InputSpec, expr: sp.Basic) -> list:
        conditions = []
        scale = self.unit_scale_expr(spec.unit_name)
        if spec.minimum is not None:
            conditions.append(
                sp.Ge(expr, parse_exact_number(spec.minimum) * scale, evaluate=False)
            )
        if spec.maximum is not None:
            conditions.append(
                sp.Le(expr, parse_exact_number(spec.maximum) * scale, evaluate=False)
            )
        if spec.integer:
            conditions.append(sp.Contains(expr / scale, sp.S.Integers, evaluate=False))
        if spec.allowed_values:
            values = [
                sp.true
                if value is True
                else sp.false
                if value is False
                else parse_exact_number(str(value)) * scale
                for value in spec.allowed_values
            ]
            conditions.append(sp.Or(*(sp.Eq(expr, value, evaluate=False) for value in values)))
        return conditions

    def resolve_target(self, target_or_expression: str) -> MathValue:
        normalized = target_or_expression.strip()
        if TARGET_RE.fullmatch(normalized) and normalized.split(".", 1)[0] in self.workspace.entries:
            value = self.resolve_path(tuple(normalized.split(".")))
        else:
            value = RestrictedCompiler(self, None, location=SourceLocation(field="expression")).compile(
                target_or_expression
            )
        self._check_expanded_size(value.expr)
        self._check_dependency_count(value)
        return value

    def display_label(self, target: str) -> Optional[str]:
        """Return non-authoritative presentation text for a canonical member target."""
        normalized = target.strip()
        if not TARGET_RE.fullmatch(normalized):
            return None
        parts = normalized.split(".")
        entry = self.workspace.entries.get(parts[0])
        if entry is None:
            return None
        member = parts[1]
        if member in entry.objects:
            if len(parts) == 2:
                return entry.objects[member].label
            type_spec = self.resolve_structure_type(entry, entry.objects[member].type_name)
            type_owner = self.workspace.get_entry(type_spec.owner_id)
            for index, segment in enumerate(parts[2:], start=2):
                field_spec = type_spec.fields.get(segment)
                if field_spec is None:
                    return None
                if index == len(parts) - 1:
                    return field_spec.label
                type_spec = self.resolve_structure_type(type_owner, field_spec.type_name)
                type_owner = self.workspace.get_entry(type_spec.owner_id)
        if member in entry.inputs:
            return entry.inputs[member].label
        if member in entry.distributions:
            return entry.distributions[member].label
        for collection in (entry.fields, entry.functions, entry.outputs):
            if member in collection:
                label = collection[member].get("label")
                return label if isinstance(label, str) else None
        return None

    def resolve_structure_type(self, owner: Entry, type_name: str) -> StructureTypeSpec:
        parts = type_name.split(".")
        if len(parts) == 2:
            entry = self.workspace.entries.get(parts[0])
            if entry is None or parts[1] not in entry.structure_types:
                raise ReferenceError(f"unknown structure type {type_name!r}")
            return entry.structure_types[parts[1]]
        if len(parts) != 1:
            raise ReferenceError(f"structure type path {type_name!r} must use TYPE or ENTRY.TYPE")
        if type_name in owner.structure_types:
            return owner.structure_types[type_name]
        matches = [
            entry.structure_types[type_name]
            for entry in self.workspace.entries.values()
            if type_name in entry.structure_types
        ]
        if not matches:
            raise ReferenceError(f"unknown structure type {type_name!r}")
        if len(matches) > 1:
            choices = ", ".join(sorted(item.qualified_id for item in matches))
            raise ReferenceError(
                f"structure type {type_name!r} is ambiguous; use one of: {choices}"
            )
        return matches[0]

    def resolve_object_reference(
        self, reference: str, owner: Entry
    ) -> tuple[Entry, StructuredObjectSpec]:
        parts = reference.split(".")
        if len(parts) == 1:
            if parts[0] not in owner.objects:
                raise ReferenceError(
                    f"entry {owner.id!r} has no structured object {parts[0]!r}"
                )
            return owner, owner.objects[parts[0]]
        if len(parts) == 2:
            entry = self.workspace.entries.get(parts[0])
            if entry is None or parts[1] not in entry.objects:
                raise ReferenceError(f"unknown structured object {reference!r}")
            return entry, entry.objects[parts[1]]
        raise ReferenceError(
            f"structured object reference {reference!r} must use OBJECT or ENTRY.OBJECT"
        )

    def _scalar_type(self, owner: Entry, type_name: str) -> tuple[str, str, Dimension]:
        if type_name == "boolean":
            return "boolean", "dimensionless", DIMENSIONLESS
        if type_name.startswith("number[") and type_name.endswith("]"):
            unit_name = type_name[7:-1]
            return "number", unit_name, self.workspace.units.parse_unit(unit_name)
        domain = self.workspace.units.domains.get(type_name)
        if domain is not None:
            return domain.value_type, domain.unit_name, self.workspace.units.parse_unit(domain.unit_name)
        if type_name in self.workspace.units.units:
            return "number", type_name, self.workspace.units.parse_unit(type_name)
        raise ReferenceError(f"type {type_name!r} is not a scalar type")

    def _is_scalar_type(self, type_name: str) -> bool:
        return (
            type_name == "boolean"
            or (type_name.startswith("number[") and type_name.endswith("]"))
            or type_name in self.workspace.units.units
            or type_name in self.workspace.units.domains
        )

    def _object_member_spec(
        self,
        owner: Entry,
        obj: StructuredObjectSpec,
        path: tuple[str, ...],
    ) -> tuple[Entry, Any, Any, set[str]]:
        if not path:
            raise ReferenceError(f"structured object {obj.qualified_id!r} requires a field path")
        type_owner = owner
        type_spec = self.resolve_structure_type(owner, obj.type_name)
        type_owner = self.workspace.get_entry(type_spec.owner_id)
        type_dependencies = {type_owner.id}
        values: Mapping[str, object] = obj.values
        for index, segment in enumerate(path):
            field_spec = type_spec.fields.get(segment)
            if field_spec is None:
                choices = ", ".join(sorted(type_spec.fields))
                raise ReferenceError(
                    f"type {type_spec.qualified_id!r} has no field {segment!r}; available: {choices}"
                )
            raw_value = values.get(segment, field_spec.default)
            if raw_value is None and not field_spec.optional:
                raise SchemaError(
                    f"object {obj.qualified_id!r} is missing required field {'.'.join(path[: index + 1])!r}",
                    obj.location,
                )
            final = index == len(path) - 1
            if self._is_scalar_type(field_spec.type_name):
                if not final:
                    raise ReferenceError(
                        f"scalar field {segment!r} has no nested member {path[index + 1]!r}"
                    )
                return type_owner, field_spec, raw_value, type_dependencies
            if final:
                raise ReferenceError(
                    f"structured field {segment!r} must be followed by a declared leaf field"
                )
            if not isinstance(raw_value, Mapping):
                raise SchemaError(
                    f"object field {segment!r} must contain a nested {field_spec.type_name} object",
                    obj.location,
                )
            type_spec = self.resolve_structure_type(type_owner, field_spec.type_name)
            type_owner = self.workspace.get_entry(type_spec.owner_id)
            type_dependencies.add(type_owner.id)
            values = raw_value
        raise AssertionError("unreachable")

    def _object_member_unit(
        self, owner: Entry, obj: StructuredObjectSpec, path: tuple[str, ...]
    ) -> str:
        type_owner, field_spec, _raw_value, _type_dependencies = self._object_member_spec(
            owner, obj, path
        )
        _value_type, unit_name, _dimension = self._scalar_type(type_owner, field_spec.type_name)
        return unit_name

    def resolve_object_member(
        self, owner: Entry, obj: StructuredObjectSpec, path: tuple[str, ...]
    ) -> MathValue:
        key = (owner.id, obj.id, path)
        if key in self._object_member_cache:
            cached = self._object_member_cache[key]
            return MathValue(
                cached.expr,
                cached.dimension,
                list(cached.conditions),
                dict(cached.inputs),
                set(cached.dependencies),
                cached.is_boolean,
            )
        type_owner, field_spec, raw_value, type_dependencies = self._object_member_spec(
            owner, obj, path
        )
        if raw_value is None and field_spec.optional:
            raise ReferenceError(
                f"optional field {obj.qualified_id}.{'.'.join(path)} has no value"
            )
        value_type, unit_name, dimension = self._scalar_type(type_owner, field_spec.type_name)
        stack_key = f"{obj.qualified_id}.{'.'.join(path)}"
        if stack_key in self._stack:
            start = self._stack.index(stack_key)
            raise DependencyCycleError(
                "dependency cycle: " + " -> ".join(self._stack[start:] + [stack_key])
            )
        self._stack.append(stack_key)
        try:
            if value_type == "boolean" and isinstance(raw_value, bool):
                value = MathValue(
                    sp.true if raw_value else sp.false,
                    DIMENSIONLESS,
                    dependencies={owner.id, *type_dependencies},
                    is_boolean=True,
                )
            elif value_type != "boolean" and isinstance(raw_value, (str, int)) and NUMBER_LITERAL_RE.fullmatch(str(raw_value)):
                value = MathValue(
                    parse_exact_number(str(raw_value)) * self.unit_scale_expr(unit_name),
                    dimension,
                    dependencies={owner.id, *type_dependencies},
                )
            else:
                value = self._compile_entry_expression(
                    owner,
                    str(raw_value).lower() if isinstance(raw_value, bool) else str(raw_value),
                    f"objects.{obj.id}.values.{'.'.join(path)}",
                    apply_constraints=True,
                )
                self._require_declared_dimension(
                    value.dimension,
                    dimension,
                    owner,
                    f"objects.{obj.id}.values.{'.'.join(path)}",
                    value.expr,
                )
                if value.expr == 0:
                    value.dimension = dimension
                value.dependencies.update({owner.id, *type_dependencies})
            domain = self.workspace.units.domains.get(field_spec.type_name)
            if domain is not None and not value.is_boolean:
                scale = self.unit_scale_expr(unit_name)
                if domain.minimum is not None:
                    value.conditions.append(
                        sp.Ge(value.expr, parse_exact_number(domain.minimum) * scale, evaluate=False)
                    )
                if domain.maximum is not None:
                    value.conditions.append(
                        sp.Le(value.expr, parse_exact_number(domain.maximum) * scale, evaluate=False)
                    )
                if domain.integer:
                    value.conditions.append(
                        sp.Contains(value.expr / scale, sp.S.Integers, evaluate=False)
                    )
            self._check_expanded_size(value.expr)
            self._check_dependency_count(value)
            self._check_package_dependency_scope(
                owner, value, owner.location(f"objects.{obj.id}.values.{'.'.join(path)}")
            )
            self._object_member_cache[key] = value
            return MathValue(
                value.expr,
                value.dimension,
                list(value.conditions),
                dict(value.inputs),
                set(value.dependencies),
                value.is_boolean,
            )
        finally:
            self._stack.pop()

    def resolve_path(
        self, path: Sequence[str], current_entry: Optional[Entry] = None
    ) -> MathValue:
        parts = tuple(path)
        if not parts:
            raise ReferenceError("member path may not be empty")
        if any(part.startswith("__") for part in parts):
            raise ReferenceError("private member path segments are not allowed")
        if current_entry is not None and parts[0] in current_entry.objects:
            return self.resolve_object_member(
                current_entry, current_entry.objects[parts[0]], parts[1:]
            )
        if parts[0] in self.workspace.entries:
            entry = self.workspace.get_entry(parts[0])
            if len(parts) >= 2 and parts[1] in entry.objects:
                return self.resolve_object_member(entry, entry.objects[parts[1]], parts[2:])
            if len(parts) == 2:
                return self.resolve_member(parts[0], parts[1])
            raise ReferenceError(f"unknown structured member path {'.'.join(parts)!r}")
        if current_entry is not None and len(parts) == 1:
            return self.resolve_member(current_entry.id, parts[0])
        raise ReferenceError(f"missing reference: unknown member path {'.'.join(parts)!r}")

    def resolve_member(self, entry_id: str, member: str) -> MathValue:
        key = (entry_id, member)
        if key in self._member_cache:
            cached = self._member_cache[key]
            return MathValue(
                cached.expr,
                cached.dimension,
                list(cached.conditions),
                dict(cached.inputs),
                set(cached.dependencies),
                cached.is_boolean,
            )
        entry = self.workspace.get_entry(entry_id)
        stack_key = f"{entry_id}.{member}"
        if stack_key in self._stack:
            start = self._stack.index(stack_key)
            path = self._stack[start:] + [stack_key]
            raise DependencyCycleError("dependency cycle: " + " -> ".join(path))
        if len(self._stack) >= MAX_DEPENDENCY_DEPTH:
            raise ExpressionError(
                f"dependency expansion exceeds depth {MAX_DEPENDENCY_DEPTH}: "
                + " -> ".join([*self._stack, stack_key])
            )
        self._stack.append(stack_key)
        try:
            if member in entry.fields:
                data = entry.fields[member]
                kind = data["kind"]
                dimension = self.workspace.units.parse_unit(data.get("unit", "dimensionless"))
                if kind == "value":
                    if data.get("value_type", "number") == "boolean":
                        value = MathValue(
                            sp.true if data["value"] else sp.false,
                            DIMENSIONLESS,
                            dependencies={entry_id},
                            is_boolean=True,
                        )
                    else:
                        value = MathValue(
                            parse_exact_number(str(data["value"]))
                            * self.unit_scale_expr(data.get("unit", "dimensionless")),
                            dimension,
                            dependencies={entry_id},
                        )
                else:
                    value = self._compile_entry_expression(
                        entry,
                        data["expression"],
                        f"fields.{member}.expression",
                        apply_constraints=True,
                    )
                    self._require_declared_dimension(
                        value.dimension, dimension, entry, f"fields.{member}.unit", value.expr
                    )
                    if value.expr == 0:
                        value.dimension = dimension
                    value.dependencies.add(entry_id)
            elif member in entry.outputs:
                data = entry.outputs[member]
                dimension = self.workspace.units.parse_unit(data.get("unit", "dimensionless"))
                value = self._compile_entry_expression(
                    entry,
                    data["expression"],
                    f"outputs.{member}.expression",
                    apply_constraints=True,
                )
                self._require_declared_dimension(
                    value.dimension, dimension, entry, f"outputs.{member}.unit", value.expr
                )
                if value.expr == 0:
                    value.dimension = dimension
                value.dependencies.add(entry_id)
            elif member in entry.functions:
                raise ReferenceError(f"function {entry_id}.{member} must be called with parentheses")
            elif member in entry.distributions:
                raise ReferenceError(
                    f"distribution {entry_id}.{member} must be observed with expectation, variance, or probability"
                )
            elif member in entry.inputs:
                spec = entry.inputs[member]
                symbol = self.input_symbol(member, spec)
                value = MathValue(
                    symbol,
                    spec.dimension,
                    self.input_conditions(spec, symbol),
                    {spec.key: spec},
                    {entry.id},
                    spec.value_type == "boolean",
                )
                value = self._apply_entry_constraints(
                    entry,
                    value,
                    RestrictedCompiler(
                        self, entry, location=entry.location(f"inputs.{member}")
                    ),
                )
            else:
                raise ReferenceError(f"entry {entry_id!r} has no mathematical field or output {member!r}")
            self._check_expanded_size(value.expr)
            self._check_dependency_count(value)
            self._check_package_dependency_scope(entry, value, entry.location(member))
            self._member_cache[key] = value
            return MathValue(
                value.expr,
                value.dimension,
                list(value.conditions),
                dict(value.inputs),
                set(value.dependencies),
                value.is_boolean,
            )
        finally:
            self._stack.pop()

    def bounded_nonnegative_integer_values(
        self, value: MathValue, context: str, maximum_allowed: int
    ) -> list[int]:
        """Resolve a finite integer domain shared by bounded static operators."""

        if value.is_boolean or not value.dimension.is_dimensionless:
            raise ExpressionError(f"{context} must be a dimensionless integer")
        if not value.expr.free_symbols:
            if not value.expr.is_Integer:
                raise ExpressionError(f"{context} must be an integer")
            candidates = [int(value.expr)]
        else:
            if not isinstance(value.expr, sp.Symbol):
                raise ExpressionError(
                    f"{context} must be a constant or direct bounded integer input"
                )
            spec = next(
                (
                    spec
                    for key, spec in value.inputs.items()
                    if self.input_symbol(key, spec) == value.expr
                ),
                None,
            )
            if spec is None:
                raise ExpressionError(
                    f"{context} must resolve to one declared bounded integer input"
                )
            if spec.allowed_values:
                parsed = [parse_exact_number(str(item)) for item in spec.allowed_values]
                if any(not item.is_Integer for item in parsed):
                    raise ExpressionError(
                        f"{context} allowed values must all be integers"
                    )
                candidates = sorted({int(item) for item in parsed})
            else:
                if not spec.integer or spec.minimum is None or spec.maximum is None:
                    raise ExpressionError(
                        f"{context} requires finite integer bounds or finite allowed values"
                    )
                minimum = parse_exact_number(spec.minimum)
                maximum = parse_exact_number(spec.maximum)
                if not minimum.is_Integer or not maximum.is_Integer:
                    raise ExpressionError(f"{context} bounds must be integers")
                if int(maximum) - int(minimum) > maximum_allowed:
                    raise ExpressionError(
                        f"{context} domain exceeds {maximum_allowed} values"
                    )
                candidates = list(range(int(minimum), int(maximum) + 1))
        if not candidates or min(candidates) < 0 or max(candidates) > maximum_allowed:
            raise ExpressionError(
                f"{context} must be between 0 and {maximum_allowed}"
            )
        return candidates

    def resolve_distribution(
        self, entry_id: str, distribution_name: str
    ) -> FiniteDistribution:
        key = (entry_id, distribution_name)
        if key in self._distribution_cache:
            return self._distribution_cache[key].copy()
        entry = self.workspace.get_entry(entry_id)
        distribution = entry.distributions.get(distribution_name)
        if distribution is None:
            raise ReferenceError(
                f"entry {entry_id!r} has no distribution {distribution_name!r}"
            )
        stack_key = f"{entry_id}.{distribution_name}<distribution>"
        if stack_key in self._stack:
            start = self._stack.index(stack_key)
            path = self._stack[start:] + [stack_key]
            raise DependencyCycleError("dependency cycle: " + " -> ".join(path))
        if len(self._stack) >= MAX_DEPENDENCY_DEPTH:
            raise ExpressionError(
                f"dependency expansion exceeds depth {MAX_DEPENDENCY_DEPTH}: "
                + " -> ".join([*self._stack, stack_key])
            )
        self._stack.append(stack_key)
        try:
            outcomes = []
            conditions = []
            inputs: Dict[str, InputSpec] = {}
            dependencies: Set[str] = {entry.id}
            probabilities = []
            for index, outcome_spec in enumerate(distribution.outcomes):
                value = self._compile_entry_expression(
                    entry,
                    outcome_spec.value,
                    f"distributions.{distribution_name}.outcomes.{index}.value",
                    apply_constraints=True,
                )
                probability = self._compile_entry_expression(
                    entry,
                    outcome_spec.probability,
                    f"distributions.{distribution_name}.outcomes.{index}.probability",
                    apply_constraints=True,
                )
                if value.is_boolean:
                    raise ExpressionError(
                        "distribution outcomes must be numeric", outcome_spec.location
                    )
                if probability.is_boolean:
                    raise ExpressionError(
                        "distribution probabilities must be numeric", outcome_spec.location
                    )
                if not probability.dimension.is_dimensionless:
                    raise UnitError(
                        "distribution probabilities must be dimensionless",
                        outcome_spec.location,
                    )
                self._require_declared_dimension(
                    value.dimension,
                    distribution.dimension,
                    entry,
                    f"distributions.{distribution_name}.outcomes.{index}.value",
                    value.expr,
                )
                if value.expr == 0:
                    value.dimension = distribution.dimension
                conditions.extend(value.conditions)
                conditions.extend(probability.conditions)
                conditions.extend(
                    [
                        sp.Ge(probability.expr, 0, evaluate=False),
                        sp.Le(probability.expr, 1, evaluate=False),
                    ]
                )
                inputs = merge_inputs(inputs, value.inputs, probability.inputs)
                dependencies.update(value.dependencies)
                dependencies.update(probability.dependencies)
                probabilities.append(probability.expr)
                outcomes.append(DistributionOutcome(value, probability))
                self._check_expanded_size(value.expr)
                self._check_expanded_size(probability.expr)
            conditions.append(sp.Eq(sp.Add(*probabilities), 1, evaluate=False))
            resolved = FiniteDistribution(
                tuple(outcomes),
                distribution.dimension,
                conditions,
                inputs,
                dependencies,
            )
            self.check_conditions(conditions)
            self._check_package_dependency_scope(
                entry,
                MathValue(sp.Integer(0), dependencies=dependencies),
                distribution.location or entry.location(f"distributions.{distribution_name}"),
            )
            self._check_dependency_count(
                MathValue(sp.Integer(0), dependencies=dependencies)
            )
            self._distribution_cache[key] = resolved
            return resolved.copy()
        finally:
            self._stack.pop()

    def call_function(self, entry_id: str, function_name: str, args: Sequence[MathValue]) -> MathValue:
        entry = self.workspace.get_entry(entry_id)
        if function_name not in entry.functions:
            raise ReferenceError(f"entry {entry_id!r} has no function {function_name!r}")
        stack_key = f"{entry_id}.{function_name}()"
        if stack_key in self._stack:
            start = self._stack.index(stack_key)
            path = self._stack[start:] + [stack_key]
            raise DependencyCycleError("dependency cycle: " + " -> ".join(path))
        if len(self._stack) >= MAX_DEPENDENCY_DEPTH:
            raise ExpressionError(
                f"dependency expansion exceeds depth {MAX_DEPENDENCY_DEPTH}: "
                + " -> ".join([*self._stack, stack_key])
            )
        data = entry.functions[function_name]
        params_raw = data.get("parameters", {})
        names = list(params_raw)
        if len(args) != len(names):
            raise ExpressionError(
                f"function {entry_id}.{function_name} expects {len(names)} arguments, got {len(args)}"
            )
        local_values = {}
        argument_conditions = []
        argument_dependencies: Set[str] = set()
        location = entry.location(f"functions.{function_name}")
        for name, arg in zip(names, args):
            spec = _parse_input(name, params_raw[name], location, self.workspace.units)
            if arg.is_boolean != (spec.value_type == "boolean"):
                raise ExpressionError(
                    f"argument {name!r} of {entry_id}.{function_name} has the wrong value type",
                    location,
                )
            if arg.dimension != spec.dimension:
                raise UnitError(
                    f"argument {name!r} of {entry_id}.{function_name} expects {spec.unit_name}, got {arg.dimension.render()}",
                    location,
                )
            # A package function may transform values supplied by its caller without gaining
            # authority to read the caller's documents. Compile the function body with the
            # argument provenance removed, validate only dependencies introduced by that body,
            # and restore caller provenance on the returned value below. This keeps transitive
            # calculation records complete while preserving the package dependency boundary.
            argument_dependencies.update(arg.dependencies)
            local_values[name] = MathValue(
                arg.expr,
                arg.dimension,
                list(arg.conditions),
                dict(arg.inputs),
                dependencies=set(),
                is_boolean=arg.is_boolean,
            )
            argument_conditions.extend(self.input_conditions(spec, arg.expr))
        self._stack.append(stack_key)
        try:
            compiler = RestrictedCompiler(
                self,
                entry,
                local_values=local_values,
                location=entry.location(f"functions.{function_name}.expression"),
            )
            value = compiler.compile(data["expression"])
            value = self._apply_entry_constraints(entry, value, compiler)
            value.conditions = argument_conditions + value.conditions
            expected = self.workspace.units.parse_unit(data.get("unit", "dimensionless"))
            self._require_declared_dimension(
                value.dimension, expected, entry, f"functions.{function_name}.unit", value.expr
            )
            if value.expr == 0:
                value.dimension = expected
            value.dependencies.add(entry.id)
            self._check_expanded_size(value.expr)
            self._check_package_dependency_scope(entry, value, location)
            value.dependencies.update(argument_dependencies)
            self._check_dependency_count(value)
            return value
        finally:
            self._stack.pop()

    def lookup_table(
        self,
        entry_id: str,
        table_name: str,
        key: MathValue,
        *,
        interpolate: bool,
    ) -> MathValue:
        entry = self.workspace.get_entry(entry_id)
        table = entry.tables.get(table_name)
        if table is None:
            raise ReferenceError(f"entry {entry_id!r} has no table {table_name!r}")
        if key.is_boolean:
            raise ExpressionError("table keys must be numeric", table.location)
        if key.dimension != table.input_dimension:
            raise UnitError(
                f"table {table.qualified_id} expects {table.input_unit}, got {key.dimension.render()}",
                table.location,
            )
        input_scale = self.unit_scale_expr(table.input_unit)
        output_scale = self.unit_scale_expr(table.output_unit)
        points = [
            (parse_exact_number(x) * input_scale, parse_exact_number(y) * output_scale)
            for x, y in table.points
        ]
        conditions = list(key.conditions)
        if interpolate:
            if len(points) < 2:
                raise ExpressionError(
                    f"interpolate requires at least two points in {table.qualified_id}",
                    table.location,
                )
            branches = []
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                active = sp.And(
                    sp.Ge(key.expr, x1, evaluate=False),
                    sp.Le(key.expr, x2, evaluate=False),
                )
                value = y1 + (key.expr - x1) * (y2 - y1) / (x2 - x1)
                branches.append((value, active))
            expr = sp.Piecewise(*branches, (points[-1][1], True))
            conditions.extend(
                [
                    sp.Ge(key.expr, points[0][0], evaluate=False),
                    sp.Le(key.expr, points[-1][0], evaluate=False),
                ]
            )
        else:
            matches = [sp.Eq(key.expr, x, evaluate=False) for x, _y in points]
            expr = sp.Piecewise(
                *((y, match) for match, (_x, y) in zip(matches, points)),
                (points[-1][1], True),
            )
            conditions.append(sp.Or(*matches))
        return MathValue(
            expr,
            table.output_dimension,
            conditions,
            dict(key.inputs),
            set(key.dependencies) | {entry_id},
        )

    def _compile_entry_expression(
        self,
        entry: Entry,
        source: str,
        field: str,
        apply_constraints: bool,
    ) -> MathValue:
        compiler = RestrictedCompiler(
            self,
            entry,
            location=entry.location(field),
        )
        value = compiler.compile(source)
        return self._apply_entry_constraints(entry, value, compiler) if apply_constraints else value

    def _apply_entry_constraints(
        self, entry: Entry, value: MathValue, compiler: RestrictedCompiler
    ) -> MathValue:
        if entry.id in self._constraint_entries:
            return value
        self._constraint_entries.add(entry.id)
        try:
            for index, source in enumerate(entry.constraints):
                constraint_compiler = RestrictedCompiler(
                    self,
                    entry,
                    local_values=compiler.local_values,
                    location=entry.location(f"constraints.{index}"),
                )
                condition = constraint_compiler.compile(source)
                if not condition.is_boolean:
                    raise SchemaError(
                        "entry constraint must be a boolean expression",
                        entry.location(f"constraints.{index}"),
                    )
                value.conditions.extend(condition.conditions)
                value.conditions.append(condition.expr)
                value.inputs = merge_inputs(value.inputs, condition.inputs)
                value.dependencies.update(condition.dependencies)
        finally:
            self._constraint_entries.remove(entry.id)
        return value

    def _require_declared_dimension(
        self,
        actual: Dimension,
        expected: Dimension,
        entry: Entry,
        field: str,
        expr: Optional[sp.Basic] = None,
    ) -> None:
        # Exact zero is the additive identity in every dimension. Callers set
        # its declared result dimension after this compatibility check.
        if actual != expected and expr != 0:
            raise UnitError(
                f"declared unit {expected.render()} does not match expression unit {actual.render()}",
                entry.location(field),
            )

    def _check_expanded_size(self, expr: sp.Expr) -> None:
        count = 0
        for _ in sp.preorder_traversal(expr):
            count += 1
            if count > MAX_EXPANDED_NODES:
                raise ExpressionError(
                    f"expanded expression exceeds {MAX_EXPANDED_NODES} mathematical nodes"
                )

    def _check_dependency_count(self, value: MathValue) -> None:
        if len(value.dependencies) > MAX_DEPENDENCY_DOCUMENTS:
            raise ExpressionError(
                f"expanded dependency closure exceeds {MAX_DEPENDENCY_DOCUMENTS} entries"
            )

    def _check_package_dependency_scope(
        self, owner: Document, value: MathValue, location: SourceLocation
    ) -> None:
        origin = owner.package_origin
        if origin is None:
            return
        allowed = self.workspace.allowed_package_sources(origin.source)
        if allowed is None:
            return
        for dependency_id in value.dependencies:
            dependency = self.workspace.entries.get(dependency_id)
            if dependency is None or dependency.id == owner.id:
                continue
            dependency_origin = dependency.package_origin
            if dependency_origin is None:
                raise SchemaError(
                    f"package {origin.name!r} references workspace-local entry {dependency_id!r}",
                    location,
                )
            if dependency_origin.source not in allowed:
                raise SchemaError(
                    f"package {origin.name!r} references undeclared package source "
                    f"{dependency_origin.source!r} through {dependency_id!r}",
                    location,
                )

    def _check_dependency_versions(self, value: MathValue, location: SourceLocation) -> None:
        versions = {
            entry.game_version
            for dependency in value.dependencies
            for entry in [self.workspace.entries.get(dependency)]
            if entry is not None and entry.game_version
        }
        if len(versions) > 1:
            raise SchemaError(
                "calculation mixes incompatible game versions: " + ", ".join(sorted(versions)),
                location,
            )

    def _parse_parameters(
        self,
        value: MathValue,
        preset: Optional[Preset],
        overrides: Optional[Mapping[str, str]],
        keep: Set[str],
    ) -> Dict[str, sp.Basic]:
        available: Dict[str, object] = {}
        for name, spec in value.inputs.items():
            if spec.default is not None:
                available[name] = spec.default
        if preset is not None:
            all_inputs = {
                spec.key: spec for entry in self.workspace.entries.values() for spec in entry.inputs.values()
            }
            preset_seen = set()
            for raw_name, raw_value in preset.values.items():
                key = self.resolve_input_key(raw_name, all_inputs)
                if key in preset_seen:
                    raise ParameterError(
                        f"preset {preset.qualified_id!r} assigns {key!r} more than once"
                    )
                preset_seen.add(key)
                available[key] = raw_value
        if overrides:
            canonical_overrides = {}
            for raw_name, raw_value in overrides.items():
                key = self.resolve_input_key(raw_name, value.inputs)
                if key in canonical_overrides:
                    raise ParameterError(f"command-line override assigns {key!r} more than once")
                canonical_overrides[key] = raw_value
            available.update(canonical_overrides)
        parsed = {}
        for name, text in available.items():
            if name not in value.inputs or name in keep:
                continue
            parsed[name] = self._parse_parameter_value(value.inputs[name], text)
        for name, number in parsed.items():
            self._check_constraint(value.inputs[name], number)
        return parsed

    def _parse_parameter_value(self, spec: InputSpec, value) -> sp.Basic:
        if spec.value_type == "boolean":
            if isinstance(value, bool):
                return sp.true if value else sp.false
            if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
                return sp.true if value.strip().lower() == "true" else sp.false
            raise ParameterError(f"parameter {spec.key} requires true or false", spec.location)
        if isinstance(value, bool):
            raise ParameterError(
                f"parameter {spec.key} requires a number, not a boolean", spec.location
            )
        try:
            return parse_exact_number(str(value)) * self.unit_scale_expr(spec.unit_name)
        except ExpressionError as exc:
            if exc.location is None:
                exc.location = spec.location
            raise

    def _check_constraint(self, spec: InputSpec, value: sp.Basic) -> None:
        if spec.value_type == "boolean":
            if value not in (sp.true, sp.false):
                raise ParameterError(f"parameter {spec.key} requires true or false", spec.location)
            if spec.allowed_values:
                allowed = [sp.true if item is True else sp.false for item in spec.allowed_values]
                if value not in allowed:
                    rendered = ", ".join(map(str, allowed))
                    raise ParameterError(
                        f"parameter {spec.key}={value} is not one of: {rendered}", spec.location
                    )
            return
        scale = self.unit_scale_expr(spec.unit_name)
        raw_value = sp.simplify(value / scale)
        if spec.minimum is not None and raw_value < parse_exact_number(spec.minimum):
            raise ParameterError(
                f"parameter {spec.key}={value} is below minimum {spec.minimum}", spec.location
            )
        if spec.maximum is not None and raw_value > parse_exact_number(spec.maximum):
            raise ParameterError(
                f"parameter {spec.key}={value} is above maximum {spec.maximum}", spec.location
            )
        if spec.integer and raw_value not in sp.S.Integers:
            raise ParameterError(f"parameter {spec.key}={value} must be an integer", spec.location)
        if spec.allowed_values:
            allowed = [
                sp.true
                if item is True
                else sp.false
                if item is False
                else parse_exact_number(str(item)) * scale
                for item in spec.allowed_values
            ]
            if value not in allowed:
                rendered = ", ".join(map(str, allowed))
                raise ParameterError(
                    f"parameter {spec.key}={value} is not one of: {rendered}", spec.location
                )

    def prepare(
        self,
        target_or_expression: str,
        preset_id: Optional[str] = None,
        overrides: Optional[Mapping[str, str]] = None,
        keep: Optional[Iterable[str]] = None,
        require_numeric: bool = False,
    ) -> PreparedValue:
        value = self.resolve_target(target_or_expression)
        self._check_dependency_versions(
            value, SourceLocation(field=target_or_expression)
        )
        keep_set = {self.resolve_input_key(name, value.inputs) for name in (keep or ())}
        preset = self.workspace.get_preset(preset_id)
        parameters = self._parse_parameters(value, preset, overrides, keep_set)
        substitutions = {self.input_symbol(name, value.inputs[name]): number for name, number in parameters.items()}
        expr = value.expr.subs(substitutions)
        conditions = [condition.subs(substitutions) for condition in value.conditions]
        self.check_conditions(conditions)
        missing = {str(symbol) for symbol in expr.free_symbols}
        for condition in conditions:
            missing.update(str(symbol) for symbol in getattr(condition, "free_symbols", set()))
        if require_numeric and missing:
            raise ParameterError("missing parameter value(s): " + ", ".join(sorted(missing)))
        return PreparedValue(value, expr, conditions, parameters, missing)

    def check_conditions(self, conditions: Iterable) -> None:
        for condition in conditions:
            if getattr(condition, "free_symbols", set()):
                continue
            verdict = sp.simplify(condition)
            if verdict is sp.false or verdict == False:
                raise DomainError(f"domain condition failed: {sp.sstr(condition)}")
            if verdict not in (sp.true, True):
                raise DomainError(f"could not establish domain condition: {sp.sstr(condition)}")

    def _validate_entry_constraint_values(
        self, entry: Entry, preset: Optional[Preset] = None
    ) -> None:
        for index, source in enumerate(entry.constraints):
            condition = RestrictedCompiler(
                self, entry, location=entry.location(f"constraints.{index}")
            ).compile(source)
            if not condition.is_boolean:
                raise SchemaError(
                    "entry constraint must be a boolean expression",
                    entry.location(f"constraints.{index}"),
                )
            available = {
                key: spec.default for key, spec in condition.inputs.items() if spec.default is not None
            }
            if preset is not None:
                all_inputs = {
                    spec.key: spec
                    for item in self.workspace.entries.values()
                    for spec in item.inputs.values()
                }
                for raw_name, raw_value in preset.values.items():
                    key = self.resolve_input_key(raw_name, all_inputs)
                    if key in condition.inputs:
                        available[key] = raw_value
            if set(condition.inputs) <= set(available):
                substitutions = {
                    self.input_symbol(key, spec): self._parse_parameter_value(spec, available[key])
                    for key, spec in condition.inputs.items()
                }
                try:
                    self.check_conditions(
                        [item.subs(substitutions) for item in condition.conditions]
                        + [condition.expr.subs(substitutions)]
                    )
                except DomainError as exc:
                    if exc.location is None:
                        exc.location = entry.location(f"constraints.{index}")
                    raise

    def _validate_distribution_values(
        self, distribution: FiniteDistribution, preset: Optional[Preset] = None
    ) -> None:
        available = {
            key: spec.default
            for key, spec in distribution.inputs.items()
            if spec.default is not None
        }
        if preset is not None:
            all_inputs = {
                spec.key: spec
                for entry in self.workspace.entries.values()
                for spec in entry.inputs.values()
            }
            for raw_name, raw_value in preset.values.items():
                key = self.resolve_input_key(raw_name, all_inputs)
                if key in distribution.inputs:
                    available[key] = raw_value
        if set(distribution.inputs) <= set(available):
            substitutions = {
                self.input_symbol(key, spec): self._parse_parameter_value(spec, available[key])
                for key, spec in distribution.inputs.items()
            }
            self.check_conditions(
                [condition.subs(substitutions) for condition in distribution.conditions]
            )

    def _validate_math_value_defaults(self, value: MathValue) -> None:
        available = {
            key: spec.default
            for key, spec in value.inputs.items()
            if spec.default is not None
        }
        if not set(value.inputs) <= set(available):
            return
        substitutions = {
            self.input_symbol(key, spec): self._parse_parameter_value(spec, available[key])
            for key, spec in value.inputs.items()
        }
        self.check_conditions(
            [condition.subs(substitutions) for condition in value.conditions]
        )

    def _validate_structured_object(
        self, owner: Entry, obj: StructuredObjectSpec
    ) -> None:
        def visit(
            type_owner: Entry,
            type_spec: StructureTypeSpec,
            values: Mapping[str, object],
            prefix: tuple[str, ...],
            depth: int,
        ) -> None:
            if depth > MAX_STRUCTURE_DEPTH:
                raise SchemaError(
                    f"structured object exceeds depth {MAX_STRUCTURE_DEPTH}", obj.location
                )
            unknown = sorted(set(values) - set(type_spec.fields))
            if unknown:
                raise SchemaError(
                    f"object {obj.qualified_id!r} has unknown field(s): "
                    + ", ".join(unknown),
                    obj.location,
                )
            for field_name, field_spec in type_spec.fields.items():
                raw_value = values.get(field_name, field_spec.default)
                field_path = (*prefix, field_name)
                if raw_value is None:
                    if not field_spec.optional:
                        raise SchemaError(
                            f"object {obj.qualified_id!r} is missing required field {'.'.join(field_path)!r}",
                            obj.location,
                        )
                    continue
                if self._is_scalar_type(field_spec.type_name):
                    value = self.resolve_object_member(owner, obj, field_path)
                    self._validate_math_value_defaults(value)
                    continue
                if not isinstance(raw_value, Mapping):
                    raise SchemaError(
                        f"object field {'.'.join(field_path)!r} must contain a nested object",
                        obj.location,
                    )
                nested_type = self.resolve_structure_type(
                    type_owner, field_spec.type_name
                )
                nested_owner = self.workspace.get_entry(nested_type.owner_id)
                visit(
                    nested_owner,
                    nested_type,
                    raw_value,
                    field_path,
                    depth + 1,
                )

        type_spec = self.resolve_structure_type(owner, obj.type_name)
        type_owner = self.workspace.get_entry(type_spec.owner_id)
        visit(type_owner, type_spec, obj.values, (), 1)

    def validate_all(self) -> dict:
        checked = []
        errors = []

        def capture(label: str, action, *, count: bool = True) -> None:
            try:
                action()
                if count:
                    checked.append(label)
            except KTError as exc:
                errors.append(exc)

        for entry in self.workspace.entries.values():
            if entry.semantics:
                checked.append(f"{entry.id}.semantics")
            for alias, target in entry.aliases.items():
                def validate_alias(entry=entry, alias=alias, target=target):
                    target_parts = target.split(".")
                    target_entry_id = target_parts[0]
                    target_member = target_parts[1] if len(target_parts) == 2 else ""
                    target_entry = self.workspace.get_entry(target_entry_id)
                    if target_member in target_entry.functions:
                        self._check_package_dependency_scope(
                            entry,
                            MathValue(sp.Integer(0), dependencies={target_entry_id}),
                            entry.location(f"aliases.{alias}"),
                        )
                        return
                    if target_member in target_entry.distributions:
                        distribution = self.resolve_distribution(
                            target_entry_id, target_member
                        )
                        self._check_package_dependency_scope(
                            entry,
                            MathValue(
                                sp.Integer(0),
                                dependencies=set(distribution.dependencies),
                            ),
                            entry.location(f"aliases.{alias}"),
                        )
                        return
                    value = self.resolve_path(tuple(target_parts), entry)
                    self._check_package_dependency_scope(
                        entry, value, entry.location(f"aliases.{alias}")
                    )

                capture(f"{entry.id}.aliases.{alias}", validate_alias, count=False)
            for spec in entry.inputs.values():
                def validate_spec(spec=spec, entry=entry):
                    if spec.minimum is not None and spec.maximum is not None:
                        if parse_exact_number(spec.minimum) > parse_exact_number(spec.maximum):
                            raise SchemaError(
                                f"input {spec.name!r} has min greater than max",
                                entry.location(f"inputs.{spec.name}"),
                            )
                    if spec.default is not None:
                        self._check_constraint(spec, self._parse_parameter_value(spec, spec.default))

                capture(spec.key, validate_spec)
            for object_name, obj in entry.objects.items():
                capture(
                    f"{entry.id}.{object_name}<object>",
                    lambda entry=entry, obj=obj: self._validate_structured_object(entry, obj),
                )
            for member in entry.fields:
                capture(f"{entry.id}.{member}", lambda e=entry.id, m=member: self.resolve_member(e, m))
            for distribution_name in entry.distributions:
                def validate_distribution(
                    entry=entry, distribution_name=distribution_name
                ):
                    distribution = self.resolve_distribution(entry.id, distribution_name)
                    self._validate_distribution_values(distribution)

                capture(
                    f"{entry.id}.{distribution_name}<distribution>",
                    validate_distribution,
                )
            for member in entry.outputs:
                def validate_output(entry=entry, member=member):
                    value = self.resolve_member(entry.id, member)
                    self._check_dependency_versions(
                        value, entry.location(f"outputs.{member}")
                    )

                capture(f"{entry.id}.{member}", validate_output)
            for function_name, data in entry.functions.items():
                def validate_function(entry=entry, function_name=function_name, data=data):
                    args = []
                    for param_name, raw in data.get("parameters", {}).items():
                        spec = _parse_input(
                            param_name,
                            raw,
                            entry.location(f"functions.{function_name}.parameters.{param_name}"),
                            self.workspace.units,
                        )
                        symbol = sp.Symbol(
                            f"_kt_param_{entry.id}_{function_name}_{param_name}",
                            **({"boolean": True} if spec.value_type == "boolean" else {"real": True}),
                        )
                        args.append(
                            MathValue(
                                symbol,
                                spec.dimension,
                                self.input_conditions(spec, symbol),
                                is_boolean=spec.value_type == "boolean",
                            )
                        )
                    self.call_function(entry.id, function_name, args)

                capture(f"{entry.id}.{function_name}()", validate_function)
            if entry.constraints:
                try:
                    self._validate_entry_constraint_values(entry)
                    checked.extend(
                        f"{entry.id}.constraints.{index}" for index in range(len(entry.constraints))
                    )
                except KTError as exc:
                    errors.append(exc)
        all_inputs = {
            spec.key: spec for entry in self.workspace.entries.values() for spec in entry.inputs.values()
        }
        for preset_reference, preset in self.workspace.presets.items():
            def validate_preset(preset=preset):
                seen = set()
                referenced_entries = set()
                for name, text in preset.values.items():
                    key = self.resolve_input_key(name, all_inputs)
                    if key in seen:
                        raise ParameterError(
                            f"preset {preset.qualified_id!r} assigns {key!r} more than once"
                        )
                    seen.add(key)
                    referenced_entries.add(key.rsplit(".", 1)[0])
                    spec = all_inputs[key]
                    self._check_constraint(spec, self._parse_parameter_value(spec, text))
                for entry in self.workspace.entries.values():
                    self._validate_entry_constraint_values(entry, preset)
                    for distribution_name in entry.distributions:
                        self._validate_distribution_values(
                            self.resolve_distribution(entry.id, distribution_name),
                            preset,
                        )
                owner = self.workspace.get_entry(preset.owner_id)
                self._check_package_dependency_scope(
                    owner,
                    MathValue(sp.Integer(0), dependencies=referenced_entries | {owner.id}),
                    preset.location or owner.location(f"presets.{preset.id}"),
                )

            capture(preset_reference, validate_preset)
        for chart in self.workspace.charts.values():
            def validate_chart(chart=chart):
                if chart.points < 2 or chart.points > MAX_SCAN_POINTS:
                    raise SchemaError(
                        f"chart points must be between 2 and {MAX_SCAN_POINTS}", chart.location("points")
                    )
                start = parse_exact_number(chart.range_start)
                end = parse_exact_number(chart.range_end)
                if start > end:
                    raise SchemaError("chart range start exceeds its end", chart.location("range"))
                self.workspace.get_preset(chart.preset)
                canonical = None
                chart_dependencies = set()
                for target in chart.y:
                    prepared = self.prepare(target, chart.preset, keep={chart.x})
                    chart_dependencies.update(prepared.value.dependencies)
                    target_axis = self.resolve_input_key(chart.x, prepared.value.inputs)
                    if canonical is None:
                        canonical = target_axis
                    elif canonical != target_axis:
                        raise ParameterError("chart curves do not share one stable axis input")
                self._check_dependency_versions(
                    MathValue(sp.Integer(0), dependencies=chart_dependencies),
                    chart.location("y"),
                )
                self._check_package_dependency_scope(
                    chart,
                    MathValue(sp.Integer(0), dependencies=chart_dependencies),
                    chart.location("y"),
                )

            capture(chart.id, validate_chart)
        if errors:
            unique = []
            seen = set()
            for error in errors:
                key = (error.code, str(error))
                if key not in seen:
                    seen.add(key)
                    unique.append(error)
            if len(unique) == 1:
                raise unique[0]
            raise ValidationErrors(unique)
        return {"status": "ok", "documents": len(self.workspace.documents), "checked": checked}


def render_conditions(conditions: Iterable) -> list[str]:
    seen = set()
    result = []
    for condition in conditions:
        if condition in (sp.true, True):
            continue
        text = sp.sstr(condition)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def precision_value(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 2 or value > MAX_NUMERIC_PRECISION:
        raise ParameterError(f"precision must be between 2 and {MAX_NUMERIC_PRECISION}")
    return value
