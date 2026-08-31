"""CLI-independent mathematical operations with process-enforced deadlines."""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional, Sequence

import sympy as sp

from .engine import Engine, precision_value, render_conditions
from .errors import DomainError, ParameterError, UnitError, UnsupportedError
from .expression import parse_exact_number
from .limits import DEFAULT_TIMEOUT_SECONDS, MAX_SCAN_POINTS
from .timeout import run_with_timeout
from .workspace import Workspace


def exact_text(expr: sp.Expr) -> str:
    return sp.sstr(expr)


def _ensure_real_finite(expr: sp.Expr) -> None:
    if expr.has(sp.zoo, sp.oo, -sp.oo, sp.nan):
        raise DomainError(f"result is not finite: {sp.sstr(expr)}")
    if expr.is_real is False:
        raise DomainError(f"result is not real: {sp.sstr(expr)}")
    if expr.free_symbols:
        raise ParameterError(
            "result still has free variables: " + ", ".join(sorted(map(str, expr.free_symbols)))
        )


def _evaluate_core(
    workspace: Workspace,
    target: str,
    scenario: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
    display_digits: int,
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, scenario, overrides, require_numeric=True)
    exact = sp.simplify(prepared.expr)
    if prepared.value.is_boolean:
        if exact not in (sp.true, sp.false):
            raise DomainError(f"boolean result did not resolve to true or false: {sp.sstr(exact)}")
        rendered_approx = sp.sstr(exact)
    else:
        _ensure_real_finite(exact)
        rendered_approx = sp.sstr(sp.N(exact, precision).evalf(display_digits))
    return {
        "status": "ok",
        "operation": "eval",
        "target": target,
        "exact": exact_text(exact),
        "approximate": rendered_approx,
        "precision": precision,
        "display_digits": display_digits,
        "unit": workspace.units.render(prepared.value.dimension),
        "conditions": render_conditions(prepared.conditions),
        "parameters": {name: exact_text(value) for name, value in sorted(prepared.parameters.items())},
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def evaluate(
    engine: Engine,
    target: str,
    scenario: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    precision: int = 30,
    display_digits: int = 12,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    precision_value(precision)
    if isinstance(display_digits, bool) or not isinstance(display_digits, int) or display_digits < 1 or display_digits > precision:
        raise ParameterError("display digits must be between 1 and the numerical precision")
    return run_with_timeout(
        _evaluate_core,
        (engine.workspace, target, scenario, overrides, precision, display_digits),
        timeout_seconds,
    )


def _transform_core(
    workspace: Workspace,
    operation: str,
    target: str,
    scenario: Optional[str],
    overrides: Optional[Mapping[str, str]],
    keep: Optional[Iterable[str]],
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, scenario, overrides, keep=keep, require_numeric=False)
    if operation == "simplify":
        transformed = sp.simplify(prepared.expr)
    elif operation == "expand":
        transformed = sp.expand(prepared.expr)
    elif operation == "factor":
        transformed = sp.factor(prepared.expr)
    else:
        raise UnsupportedError(f"unsupported transform {operation!r}")
    return {
        "status": "ok",
        "operation": operation,
        "target": target,
        "expression": sp.sstr(transformed),
        "unit": workspace.units.render(prepared.value.dimension),
        "conditions": render_conditions(prepared.conditions),
        "parameters": {name: exact_text(value) for name, value in sorted(prepared.parameters.items())},
        "free_variables": sorted(map(str, transformed.free_symbols)),
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def transform(
    engine: Engine,
    operation: str,
    target: str,
    scenario: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    keep: Optional[Iterable[str]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    if operation not in {"simplify", "expand", "factor"}:
        raise UnsupportedError(f"unsupported transform {operation!r}")
    return run_with_timeout(
        _transform_core,
        (engine.workspace, operation, target, scenario, overrides, tuple(keep or ())),
        timeout_seconds,
    )


def _differentiate_core(
    workspace: Workspace,
    target: str,
    variable: str,
    scenario: Optional[str],
    overrides: Optional[Mapping[str, str]],
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, scenario, overrides, keep={variable}, require_numeric=False)
    if prepared.value.is_boolean:
        raise ParameterError("cannot differentiate a boolean expression")
    canonical = engine.resolve_input_key(variable, prepared.value.inputs)
    symbol = engine.input_symbol(canonical, prepared.value.inputs[canonical])
    expr = sp.diff(prepared.expr, symbol)
    dimension = prepared.value.dimension.divide(prepared.value.inputs[canonical].dimension)
    return {
        "status": "ok",
        "operation": "diff",
        "target": target,
        "variable": canonical,
        "expression": exact_text(expr),
        "unit": workspace.units.render(dimension),
        "conditions": render_conditions(prepared.conditions),
        "parameters": {name: exact_text(value) for name, value in sorted(prepared.parameters.items())},
        "free_variables": sorted(map(str, expr.free_symbols)),
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def differentiate(
    engine: Engine,
    target: str,
    variable: str,
    scenario: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    return run_with_timeout(
        _differentiate_core,
        (engine.workspace, target, variable, scenario, overrides),
        timeout_seconds,
    )


QUANTITY_RE = re.compile(r"^\s*(\S+?)(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$")


def parse_quantity(text: str, inherited_dimension, workspace: Workspace):
    match = QUANTITY_RE.fullmatch(text)
    if not match:
        raise ParameterError(f"invalid target quantity {text!r}")
    number = parse_exact_number(match.group(1))
    if match.group(2) is None:
        return number, inherited_dimension
    dimension = workspace.units.parse_unit(match.group(2))
    return number, dimension


def parse_range(
    text: str,
    inherited_dimension=None,
    workspace: Optional[Workspace] = None,
) -> tuple[sp.Rational, sp.Rational]:
    if text.count(":") != 1:
        raise ParameterError("range must use START:END")
    start_text, end_text = text.split(":", 1)
    if workspace is None:
        start, end = parse_exact_number(start_text), parse_exact_number(end_text)
    else:
        start, start_dimension = parse_quantity(start_text, inherited_dimension, workspace)
        end, end_dimension = parse_quantity(end_text, inherited_dimension, workspace)
        if start_dimension != inherited_dimension or end_dimension != inherited_dimension:
            raise UnitError("range endpoints must use the scan/solve variable unit")
    if start > end:
        raise ParameterError("range start must not exceed range end")
    return start, end


def _solve_core(
    workspace: Workspace,
    target: str,
    variable: str,
    equals: str,
    range_text: Optional[str],
    scenario: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, scenario, overrides, keep={variable}, require_numeric=False)
    if prepared.value.is_boolean:
        raise ParameterError("cannot solve a boolean-valued target as a numeric equation")
    canonical = engine.resolve_input_key(variable, prepared.value.inputs)
    other_missing = prepared.missing - {canonical}
    if other_missing:
        raise ParameterError(
            "single-variable solve has other unassigned inputs: " + ", ".join(sorted(other_missing))
        )
    target_number, target_dimension = parse_quantity(equals, prepared.value.dimension, workspace)
    if target_dimension != prepared.value.dimension:
        raise UnitError(
            "equation sides have incompatible units: "
            f"{workspace.units.render(prepared.value.dimension)} and {workspace.units.render(target_dimension)}"
        )
    variable_spec = prepared.value.inputs[canonical]
    symbol = engine.input_symbol(canonical, variable_spec)
    if range_text:
        start, end = parse_range(range_text, variable_spec.dimension, workspace)
        domain = sp.Interval(start, end)
    else:
        domain = sp.S.Reals
        start = end = None
    solutions = sp.solveset(prepared.expr - target_number, symbol, domain=domain)
    result = {
        "status": "ok",
        "operation": "solve",
        "target": target,
        "equals": exact_text(target_number),
        "target_unit": workspace.units.render(prepared.value.dimension),
        "unit": variable_spec.unit_name,
        "variable": canonical,
        "range": [exact_text(start), exact_text(end)] if range_text else None,
        "conditions": render_conditions(prepared.conditions),
        "parameters": {name: exact_text(value) for name, value in sorted(prepared.parameters.items())},
        "dependency_ids": sorted(prepared.value.dependencies),
    }
    if solutions is sp.S.EmptySet:
        result.update(solution_kind="no_solution_proven", solutions=[])
        return result
    if isinstance(solutions, sp.FiniteSet):
        accepted = []
        for solution in solutions:
            try:
                engine._check_constraint(variable_spec, solution)
                engine.check_conditions(condition.subs(symbol, solution) for condition in prepared.conditions)
            except (ParameterError, DomainError):
                continue
            accepted.append(solution)
        if not accepted:
            result.update(solution_kind="no_solution_proven", solutions=[])
            return result
        kind = "numeric_approximate" if any(item.has(sp.Float) for item in accepted) else "exact"
        result.update(
            solution_kind=kind,
            solutions=[
                {"exact": exact_text(item), "approximate": sp.sstr(sp.N(item, precision)), "conditions": []}
                for item in accepted
            ],
        )
        return result
    result.update(
        status="incomplete",
        solution_kind="incomplete",
        solution_set=sp.sstr(solutions),
        message="solver returned a conditional or non-finite set; this is not reported as a completed solve",
    )
    return result


def solve_equation(
    engine: Engine,
    target: str,
    variable: str,
    equals: str,
    range_text: Optional[str] = None,
    scenario: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    precision: int = 30,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    precision_value(precision)
    return run_with_timeout(
        _solve_core,
        (engine.workspace, target, variable, equals, range_text, scenario, overrides, precision),
        timeout_seconds,
    )


def _scan_core(
    workspace: Workspace,
    x: str,
    range_text: str,
    points: int,
    targets: Sequence[str],
    scenario: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
    display_digits: int,
) -> dict:
    engine = Engine(workspace)
    prepared_values = [
        engine.prepare(target, scenario, overrides, keep={x}, require_numeric=False) for target in targets
    ]
    specs = []
    canonical_axes = []
    for target, prepared in zip(targets, prepared_values):
        if prepared.value.is_boolean:
            raise ParameterError(f"scan target {target} is boolean; scan curves require numeric values")
        canonical = engine.resolve_input_key(x, prepared.value.inputs)
        canonical_axes.append(canonical)
        other_missing = prepared.missing - {canonical}
        if other_missing:
            raise ParameterError(
                f"{target} has unassigned non-axis inputs: " + ", ".join(sorted(other_missing))
            )
        spec = prepared.value.inputs[canonical]
        if spec.value_type == "boolean":
            raise ParameterError("scan axis must be a numeric input")
        specs.append(spec)
    if any(name != canonical_axes[0] for name in canonical_axes[1:]):
        raise ParameterError(
            "scan curves do not share one stable axis input: " + ", ".join(canonical_axes)
        )
    axis_name = canonical_axes[0]
    if any(spec.dimension != specs[0].dimension for spec in specs[1:]):
        raise UnitError("scan variable has conflicting units across curves")
    axis_symbol = engine.input_symbol(axis_name, specs[0])
    start, end = parse_range(range_text, specs[0].dimension, workspace)
    step = (end - start) / (points - 1)
    rows = []
    unexpected_errors = []
    for index in range(points):
        x_value = start + step * index
        row = {
            "x": exact_text(x_value),
            "x_approximate": sp.sstr(sp.N(x_value, precision).evalf(display_digits)),
            "values": {},
        }
        for target, prepared, spec in zip(targets, prepared_values, specs):
            try:
                engine._check_constraint(spec, x_value)
                conditions = [condition.subs(axis_symbol, x_value) for condition in prepared.conditions]
                engine.check_conditions(conditions)
                value = sp.simplify(prepared.expr.subs(axis_symbol, x_value))
                _ensure_real_finite(value)
                row["values"][target] = {
                    "exact": exact_text(value),
                    "approximate": sp.sstr(sp.N(value, precision).evalf(display_digits)),
                    "error": None,
                }
            except (DomainError, ParameterError) as exc:
                row["values"][target] = {
                    "exact": None,
                    "approximate": None,
                    "error": str(exc),
                }
            except Exception as exc:
                unexpected_errors.append(f"point {index}, target {target}: {type(exc).__name__}: {exc}")
        rows.append(row)
    if unexpected_errors:
        raise RuntimeError("unexpected scan failure: " + unexpected_errors[0])
    valid_points = {
        target: sum(row["values"][target]["error"] is None for row in rows) for target in targets
    }
    warnings = []
    y_units = {
        target: workspace.units.render(prepared.value.dimension)
        for target, prepared in zip(targets, prepared_values)
    }
    if len(set(y_units.values())) > 1:
        warnings.append("curves use different units; no implicit conversion was performed")
    if any(count == 0 for count in valid_points.values()):
        warnings.append("one or more curves have no valid sample points")
    return {
        "status": "ok",
        "operation": "scan",
        "x": axis_name,
        "x_unit": specs[0].unit_name,
        "x_domain": specs[0].domain_name,
        "range": [exact_text(start), exact_text(end)],
        "points": points,
        "targets": list(targets),
        "units": y_units,
        "parameters": {
            name: exact_text(value)
            for prepared in prepared_values
            for name, value in sorted(prepared.parameters.items())
        },
        "valid_points": valid_points,
        "warnings": warnings,
        "precision": precision,
        "display_digits": display_digits,
        "rows": rows,
        "dependency_ids": sorted(set().union(*(prepared.value.dependencies for prepared in prepared_values))),
    }


def scan_values(
    engine: Engine,
    x: str,
    range_text: str,
    points: int,
    targets: Sequence[str],
    scenario: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    precision: int = 30,
    display_digits: int = 12,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    precision_value(precision)
    if isinstance(display_digits, bool) or not isinstance(display_digits, int) or display_digits < 1 or display_digits > precision:
        raise ParameterError("display digits must be between 1 and the numerical precision")
    if isinstance(points, bool) or not isinstance(points, int) or points < 2 or points > MAX_SCAN_POINTS:
        raise ParameterError(f"scan points must be between 2 and {MAX_SCAN_POINTS}")
    if not targets:
        raise ParameterError("at least one --y target is required")
    return run_with_timeout(
        _scan_core,
        (
            engine.workspace,
            x,
            range_text,
            points,
            tuple(targets),
            scenario,
            overrides,
            precision,
            display_digits,
        ),
        timeout_seconds,
    )


def _explain_core(workspace: Workspace, target: str) -> dict:
    engine = Engine(workspace)
    value = engine.resolve_target(target)
    return {
        "status": "ok",
        "operation": "explain",
        "target": target,
        "expression": exact_text(value.expr),
        "unit": workspace.units.render(value.dimension),
        "is_boolean": value.is_boolean,
        "conditions": render_conditions(value.conditions),
        "inputs": {
            key: {
                "local_name": spec.name,
                "domain": spec.domain_name,
                "value_type": spec.value_type,
                "unit": spec.unit_name,
                "default": spec.default,
                "min": spec.minimum,
                "max": spec.maximum,
                "integer": spec.integer,
                "allowed_values": list(spec.allowed_values),
            }
            for key, spec in sorted(value.inputs.items())
        },
        "dependency_ids": sorted(value.dependencies),
    }


def explain(
    engine: Engine,
    target: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    return run_with_timeout(_explain_core, (engine.workspace, target), timeout_seconds)
