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
from .expression import MathValue, RestrictedCompiler, merge_inputs, parse_exact_number
from .limits import (
    MAX_DEPENDENCY_DEPTH,
    MAX_DEPENDENCY_DOCUMENTS,
    MAX_EXPANDED_NODES,
    MAX_NUMERIC_PRECISION,
    MAX_SCAN_POINTS,
)
from .schema import Document, Entry, InputSpec, PlotConfig, Preset, _parse_input
from .units import DIMENSIONLESS, Dimension
from .workspace import Workspace


TARGET_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)$")


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
        self._stack: list[str] = []
        self._constraint_entries: Set[str] = set()

    def unit_scale_expr(self, unit_name: str) -> sp.Rational:
        scale = self.workspace.units.scale(unit_name)
        return sp.Rational(scale.numerator, scale.denominator)

    def target_unit_name(self, target: str, fallback_dimension: Dimension) -> str:
        """Return the unit explicitly chosen for a declared target when available."""
        match = TARGET_RE.fullmatch(target.strip())
        if match:
            entry = self.workspace.entries.get(match.group(1))
            if entry is not None:
                member = match.group(2)
                if member in entry.inputs:
                    return entry.inputs[member].unit_name
                if member in entry.fields and entry.fields[member].get("kind") != "info":
                    return entry.fields[member].get("unit", "dimensionless")
                if member in entry.outputs:
                    return entry.outputs[member].get("unit", "dimensionless")
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
        match = TARGET_RE.fullmatch(target_or_expression.strip())
        if match and match.group(1) in self.workspace.entries:
            value = self.resolve_member(match.group(1), match.group(2))
        else:
            value = RestrictedCompiler(self, None, location=SourceLocation(field="expression")).compile(
                target_or_expression
            )
        self._check_expanded_size(value.expr)
        self._check_dependency_count(value)
        return value

    def display_label(self, target: str) -> Optional[str]:
        """Return non-authoritative presentation text for a canonical member target."""
        match = TARGET_RE.fullmatch(target.strip())
        if not match:
            return None
        entry = self.workspace.entries.get(match.group(1))
        if entry is None:
            return None
        member = match.group(2)
        if member in entry.inputs:
            return entry.inputs[member].label
        for collection in (entry.fields, entry.functions, entry.outputs):
            if member in collection:
                label = collection[member].get("label")
                return label if isinstance(label, str) else None
        return None

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
                if kind == "info":
                    raise ReferenceError(
                        f"field {entry_id}.{member} is informational and cannot be used in mathematics"
                    )
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
                    target_entry_id, target_member = target.split(".", 1)
                    target_entry = self.workspace.get_entry(target_entry_id)
                    if target_member in target_entry.functions:
                        self._check_package_dependency_scope(
                            entry,
                            MathValue(sp.Integer(0), dependencies={target_entry_id}),
                            entry.location(f"aliases.{alias}"),
                        )
                        return
                    value = self.resolve_member(target_entry_id, target_member)
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
            for member, data in entry.fields.items():
                if data["kind"] != "info":
                    capture(f"{entry.id}.{member}", lambda e=entry.id, m=member: self.resolve_member(e, m))
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
                owner = self.workspace.get_entry(preset.owner_id)
                self._check_package_dependency_scope(
                    owner,
                    MathValue(sp.Integer(0), dependencies=referenced_entries | {owner.id}),
                    preset.location or owner.location(f"presets.{preset.id}"),
                )

            capture(preset_reference, validate_preset)
        for plot in self.workspace.plots.values():
            def validate_plot(plot=plot):
                if plot.points < 2 or plot.points > MAX_SCAN_POINTS:
                    raise SchemaError(
                        f"plot points must be between 2 and {MAX_SCAN_POINTS}", plot.location("points")
                    )
                start = parse_exact_number(plot.range_start)
                end = parse_exact_number(plot.range_end)
                if start > end:
                    raise SchemaError("plot range start exceeds its end", plot.location("range"))
                self.workspace.get_preset(plot.preset)
                canonical = None
                plot_dependencies = set()
                for target in plot.y:
                    prepared = self.prepare(target, plot.preset, keep={plot.x})
                    plot_dependencies.update(prepared.value.dependencies)
                    target_axis = self.resolve_input_key(plot.x, prepared.value.inputs)
                    if canonical is None:
                        canonical = target_axis
                    elif canonical != target_axis:
                        raise ParameterError("plot curves do not share one stable axis input")
                self._check_dependency_versions(
                    MathValue(sp.Integer(0), dependencies=plot_dependencies),
                    plot.location("y"),
                )
                self._check_package_dependency_scope(
                    plot,
                    MathValue(sp.Integer(0), dependencies=plot_dependencies),
                    plot.location("y"),
                )

            capture(plot.id, validate_plot)
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
