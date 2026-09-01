"""CLI-independent mathematical operations with process-enforced deadlines."""

from __future__ import annotations

import math
import re
from typing import Iterable, Mapping, Optional, Sequence

import sympy as sp

from .engine import Engine, TARGET_RE, precision_value, render_conditions
from .errors import DomainError, ParameterError, UnitError, UnsupportedError
from .expression import parse_exact_number
from .limits import DEFAULT_TIMEOUT_SECONDS, MAX_SCAN_POINTS
from .timeout import run_with_timeout
from .workspace import Workspace


def exact_text(expr: sp.Expr) -> str:
    return sp.sstr(expr)


def parameter_text(engine: Engine, *prepared_values) -> dict[str, str]:
    """Render effective inputs in each input's declared unit for records and UI."""
    rendered: dict[str, str] = {}
    for prepared in prepared_values:
        for name, value in sorted(prepared.parameters.items()):
            spec = prepared.value.inputs[name]
            displayed = (
                value
                if spec.value_type == "boolean"
                else sp.simplify(value / engine.unit_scale_expr(spec.unit_name))
            )
            rendered[name] = exact_text(displayed)
    return rendered


def player_format(
    expr: sp.Expr,
    display: str = "number",
    digits: Optional[int] = None,
    *,
    fallback: Optional[str] = None,
) -> str:
    """Render a finite numeric result for ordinary player-facing tables."""
    chosen_digits = 2 if digits is None else digits
    try:
        numeric = float(sp.N(expr, max(chosen_digits + 6, 12)))
    except (TypeError, ValueError, OverflowError):
        return fallback or sp.sstr(expr)
    if not math.isfinite(numeric):
        return fallback or sp.sstr(expr)
    if display == "percent":
        return f"{numeric * 100:,.{chosen_digits}f}%"
    if display == "coefficient_percent":
        return f"{numeric:,.{chosen_digits}f}% AP"
    if display == "integer":
        return f"{numeric:,.0f}"
    return f"{numeric:,.{chosen_digits}f}"


def display_options(
    workspace: Workspace, target: str, default_digits: int
) -> tuple[str, int]:
    display = "number"
    digits = min(default_digits, 6)
    match = TARGET_RE.fullmatch(target.strip())
    if match and match.group(1) in workspace.entries:
        output = workspace.entries[match.group(1)].outputs.get(match.group(2), {})
        display = output.get("display", display)
        digits = output.get("digits", digits)
    return display, digits


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
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
    display_digits: int,
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, preset, overrides, require_numeric=True)
    internal_exact = sp.simplify(prepared.expr)
    unit_name = engine.target_unit_name(target, prepared.value.dimension)
    unit_scale = engine.unit_scale_expr(unit_name)
    exact = (
        internal_exact
        if prepared.value.is_boolean
        else sp.simplify(internal_exact / unit_scale)
    )
    if prepared.value.is_boolean:
        if exact not in (sp.true, sp.false):
            raise DomainError(f"boolean result did not resolve to true or false: {sp.sstr(exact)}")
        rendered_approx = sp.sstr(exact)
    else:
        _ensure_real_finite(exact)
        rendered_approx = sp.sstr(sp.N(exact, precision).evalf(display_digits))
    display, digits = display_options(workspace, target, display_digits)
    return {
        "status": "ok",
        "operation": "eval",
        "target": target,
        "exact": exact_text(exact),
        "approximate": rendered_approx,
        "formatted": (
            sp.sstr(exact)
            if prepared.value.is_boolean
            else player_format(exact, display, digits, fallback=rendered_approx)
        ),
        "display_format": display,
        "display_digits_player": digits,
        "precision": precision,
        "display_digits": display_digits,
        "unit": unit_name,
        "conditions": render_conditions(prepared.conditions),
        "parameters": parameter_text(engine, prepared),
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def evaluate(
    engine: Engine,
    target: str,
    preset: Optional[str] = None,
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
        (engine.workspace, target, preset, overrides, precision, display_digits),
        timeout_seconds,
    )


def _transform_core(
    workspace: Workspace,
    operation: str,
    target: str,
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
    keep: Optional[Iterable[str]],
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, preset, overrides, keep=keep, require_numeric=False)
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
        "parameters": parameter_text(engine, prepared),
        "free_variables": sorted(map(str, transformed.free_symbols)),
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def transform(
    engine: Engine,
    operation: str,
    target: str,
    preset: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    keep: Optional[Iterable[str]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    if operation not in {"simplify", "expand", "factor"}:
        raise UnsupportedError(f"unsupported transform {operation!r}")
    return run_with_timeout(
        _transform_core,
        (engine.workspace, operation, target, preset, overrides, tuple(keep or ())),
        timeout_seconds,
    )


def _differentiate_core(
    workspace: Workspace,
    target: str,
    variable: str,
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, preset, overrides, keep={variable}, require_numeric=False)
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
        "parameters": parameter_text(engine, prepared),
        "free_variables": sorted(map(str, expr.free_symbols)),
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def differentiate(
    engine: Engine,
    target: str,
    variable: str,
    preset: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    return run_with_timeout(
        _differentiate_core,
        (engine.workspace, target, variable, preset, overrides),
        timeout_seconds,
    )


QUANTITY_RE = re.compile(r"^\s*(\S+?)(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$")


def parse_quantity(
    text: str,
    inherited_dimension,
    workspace: Workspace,
    inherited_unit: Optional[str] = None,
):
    match = QUANTITY_RE.fullmatch(text)
    if not match:
        raise ParameterError(f"invalid target quantity {text!r}")
    number = parse_exact_number(match.group(1))
    if match.group(2) is None:
        if inherited_unit is None:
            return number, inherited_dimension
        scale = workspace.units.scale(inherited_unit)
        return number * sp.Rational(scale.numerator, scale.denominator), inherited_dimension
    unit_name = match.group(2)
    dimension = workspace.units.parse_unit(unit_name)
    scale = workspace.units.scale(unit_name)
    return number * sp.Rational(scale.numerator, scale.denominator), dimension


def parse_range(
    text: str,
    inherited_dimension=None,
    workspace: Optional[Workspace] = None,
    inherited_unit: Optional[str] = None,
) -> tuple[sp.Rational, sp.Rational]:
    if text.count(":") != 1:
        raise ParameterError("range must use START:END")
    start_text, end_text = text.split(":", 1)
    if workspace is None:
        start, end = parse_exact_number(start_text), parse_exact_number(end_text)
    else:
        start, start_dimension = parse_quantity(
            start_text, inherited_dimension, workspace, inherited_unit
        )
        end, end_dimension = parse_quantity(
            end_text, inherited_dimension, workspace, inherited_unit
        )
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
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(target, preset, overrides, keep={variable}, require_numeric=False)
    if prepared.value.is_boolean:
        raise ParameterError("cannot solve a boolean-valued target as a numeric equation")
    canonical = engine.resolve_input_key(variable, prepared.value.inputs)
    other_missing = prepared.missing - {canonical}
    if other_missing:
        raise ParameterError(
            "single-variable solve has other unassigned inputs: " + ", ".join(sorted(other_missing))
        )
    target_unit_name = engine.target_unit_name(target, prepared.value.dimension)
    target_number, target_dimension = parse_quantity(
        equals, prepared.value.dimension, workspace, target_unit_name
    )
    if target_dimension != prepared.value.dimension:
        raise UnitError(
            "equation sides have incompatible units: "
            f"{workspace.units.render(prepared.value.dimension)} and {workspace.units.render(target_dimension)}"
        )
    variable_spec = prepared.value.inputs[canonical]
    symbol = engine.input_symbol(canonical, variable_spec)
    if range_text:
        start, end = parse_range(
            range_text, variable_spec.dimension, workspace, variable_spec.unit_name
        )
        domain = sp.Interval(start, end)
    else:
        domain = sp.S.Reals
        start = end = None
    solutions = sp.solveset(prepared.expr - target_number, symbol, domain=domain)
    result = {
        "status": "ok",
        "operation": "solve",
        "target": target,
        "equals": exact_text(target_number / engine.unit_scale_expr(target_unit_name)),
        "target_unit": target_unit_name,
        "unit": variable_spec.unit_name,
        "variable": canonical,
        "range": (
            [
                exact_text(start / engine.unit_scale_expr(variable_spec.unit_name)),
                exact_text(end / engine.unit_scale_expr(variable_spec.unit_name)),
            ]
            if range_text
            else None
        ),
        "conditions": render_conditions(prepared.conditions),
        "parameters": parameter_text(engine, prepared),
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
        scale = engine.unit_scale_expr(variable_spec.unit_name)
        displayed = [sp.simplify(item / scale) for item in accepted]
        kind = "numeric_approximate" if any(item.has(sp.Float) for item in displayed) else "exact"
        result.update(
            solution_kind=kind,
            solutions=[
                {"exact": exact_text(item), "approximate": sp.sstr(sp.N(item, precision)), "conditions": []}
                for item in displayed
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
    preset: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    precision: int = 30,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    precision_value(precision)
    return run_with_timeout(
        _solve_core,
        (engine.workspace, target, variable, equals, range_text, preset, overrides, precision),
        timeout_seconds,
    )


def _solve_system_core(
    workspace: Workspace,
    equations: Sequence[tuple[str, str]],
    variables: Sequence[str],
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
) -> dict:
    engine = Engine(workspace)
    values = [engine.resolve_target(target) for target, _equals in equations]
    all_inputs = {
        name: spec for value in values for name, spec in value.inputs.items()
    }
    canonical_variables = [engine.resolve_input_key(name, all_inputs) for name in variables]
    if len(set(canonical_variables)) != len(canonical_variables):
        raise ParameterError("system variables must be unique")

    prepared_values = []
    expressions = []
    equation_rows = []
    for (target, equals), value in zip(equations, values):
        keep = [name for name in canonical_variables if name in value.inputs]
        prepared = engine.prepare(target, preset, overrides, keep=keep, require_numeric=False)
        other_missing = prepared.missing - set(canonical_variables)
        if other_missing:
            raise ParameterError(
                f"{target} has unassigned non-system inputs: "
                + ", ".join(sorted(other_missing))
            )
        unit_name = engine.target_unit_name(target, prepared.value.dimension)
        target_number, target_dimension = parse_quantity(
            equals, prepared.value.dimension, workspace, unit_name
        )
        if target_dimension != prepared.value.dimension:
            raise UnitError(
                f"equation for {target} has incompatible units: "
                f"{unit_name} and {workspace.units.render(target_dimension)}"
            )
        prepared_values.append(prepared)
        expressions.append(prepared.expr - target_number)
        equation_rows.append(
            {
                "target": target,
                "equals": exact_text(
                    sp.simplify(target_number / engine.unit_scale_expr(unit_name))
                ),
                "unit": unit_name,
            }
        )

    specs = [all_inputs[name] for name in canonical_variables]
    symbols = [engine.input_symbol(name, spec) for name, spec in zip(canonical_variables, specs)]
    raw_solutions = sp.solve(expressions, symbols, dict=True)
    if raw_solutions is None:
        raw_solutions = []
    if not isinstance(raw_solutions, list):
        raw_solutions = list(raw_solutions)

    accepted = []
    incomplete = False
    for raw_solution in raw_solutions:
        if any(symbol not in raw_solution for symbol in symbols):
            incomplete = True
            continue
        if any(raw_solution[symbol].free_symbols for symbol in symbols):
            incomplete = True
            continue
        try:
            for spec, symbol in zip(specs, symbols):
                value = sp.simplify(raw_solution[symbol])
                _ensure_real_finite(value)
                engine._check_constraint(spec, value)
            substitutions = {symbol: raw_solution[symbol] for symbol in symbols}
            for prepared in prepared_values:
                engine.check_conditions(
                    condition.subs(substitutions) for condition in prepared.conditions
                )
        except (DomainError, ParameterError):
            continue
        accepted.append(raw_solution)

    result = {
        "status": "ok",
        "operation": "solve_system",
        "equations": equation_rows,
        "variables": canonical_variables,
        "units": {name: spec.unit_name for name, spec in zip(canonical_variables, specs)},
        "parameters": parameter_text(engine, *prepared_values),
        "dependency_ids": sorted(
            set().union(*(prepared.value.dependencies for prepared in prepared_values))
        ),
    }
    if accepted:
        rendered_solutions = []
        for solution in accepted:
            values_row = {}
            for name, spec, symbol in zip(canonical_variables, specs, symbols):
                displayed = sp.simplify(
                    solution[symbol] / engine.unit_scale_expr(spec.unit_name)
                )
                values_row[name] = {
                    "exact": exact_text(displayed),
                    "approximate": sp.sstr(sp.N(displayed, precision)),
                    "unit": spec.unit_name,
                }
            rendered_solutions.append({"values": values_row, "conditions": []})
        result.update(solution_kind="exact", solutions=rendered_solutions)
    elif incomplete:
        result.update(
            status="incomplete",
            solution_kind="incomplete",
            solutions=[],
            solution_set=sp.sstr(raw_solutions),
            message="solver returned a parametric or incomplete system solution",
        )
    else:
        result.update(solution_kind="no_solution_proven", solutions=[])
    return result


def solve_system(
    engine: Engine,
    equations: Sequence[tuple[str, str]],
    variables: Sequence[str],
    preset: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    precision: int = 30,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    precision_value(precision)
    if not equations or len(equations) > 8:
        raise ParameterError("system solve requires between 1 and 8 equations")
    if not variables or len(variables) > 8:
        raise ParameterError("system solve requires between 1 and 8 variables")
    if len(set(variables)) != len(variables):
        raise ParameterError("system variables must be unique")
    return run_with_timeout(
        _solve_system_core,
        (
            engine.workspace,
            tuple(equations),
            tuple(variables),
            preset,
            overrides,
            precision,
        ),
        timeout_seconds,
    )


def _scan_core(
    workspace: Workspace,
    x: str,
    range_text: str,
    points: int,
    targets: Sequence[str],
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
    display_digits: int,
) -> dict:
    engine = Engine(workspace)
    prepared_values = [
        engine.prepare(target, preset, overrides, keep={x}, require_numeric=False) for target in targets
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
    start, end = parse_range(
        range_text, specs[0].dimension, workspace, specs[0].unit_name
    )
    axis_scale = engine.unit_scale_expr(specs[0].unit_name)
    target_units = [
        engine.target_unit_name(target, prepared.value.dimension)
        for target, prepared in zip(targets, prepared_values)
    ]
    target_scales = [engine.unit_scale_expr(unit_name) for unit_name in target_units]
    target_displays = [display_options(workspace, target, display_digits) for target in targets]
    step = (end - start) / (points - 1)
    rows = []
    unexpected_errors = []
    for index in range(points):
        x_value = start + step * index
        row = {
            "x": exact_text(sp.simplify(x_value / axis_scale)),
            "x_approximate": sp.sstr(
                sp.N(x_value / axis_scale, precision).evalf(display_digits)
            ),
            "values": {},
        }
        for target, prepared, spec, target_scale, display_option in zip(
            targets, prepared_values, specs, target_scales, target_displays
        ):
            try:
                engine._check_constraint(spec, x_value)
                conditions = [condition.subs(axis_symbol, x_value) for condition in prepared.conditions]
                engine.check_conditions(conditions)
                internal_value = sp.simplify(prepared.expr.subs(axis_symbol, x_value))
                _ensure_real_finite(internal_value)
                value = sp.simplify(internal_value / target_scale)
                row["values"][target] = {
                    "exact": exact_text(value),
                    "approximate": sp.sstr(sp.N(value, precision).evalf(display_digits)),
                    "formatted": player_format(
                        value, display_option[0], display_option[1]
                    ),
                    "error": None,
                }
            except (DomainError, ParameterError) as exc:
                row["values"][target] = {
                    "exact": None,
                    "approximate": None,
                    "formatted": None,
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
        target: unit_name for target, unit_name in zip(targets, target_units)
    }
    if len(set(y_units.values())) > 1:
        warnings.append("curves use different units; no implicit conversion was performed")
    if any(count == 0 for count in valid_points.values()):
        warnings.append("one or more curves have no valid sample points")
    return {
        "status": "ok",
        "operation": "scan",
        "x": axis_name,
        "x_display_label": specs[0].label,
        "x_unit": specs[0].unit_name,
        "x_domain": specs[0].domain_name,
        "range": [
            exact_text(sp.simplify(start / axis_scale)),
            exact_text(sp.simplify(end / axis_scale)),
        ],
        "points": points,
        "targets": list(targets),
        "labels": {
            target: (engine.display_label(target) or target) for target in targets
        },
        "units": y_units,
        "parameters": parameter_text(engine, *prepared_values),
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
    preset: Optional[str] = None,
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
            preset,
            overrides,
            precision,
            display_digits,
        ),
        timeout_seconds,
    )


def _scan_grid_core(
    workspace: Workspace,
    x: str,
    x_range: str,
    x_points: int,
    y: str,
    y_range: str,
    y_points: int,
    target: str,
    preset: Optional[str],
    overrides: Optional[Mapping[str, str]],
    precision: int,
    display_digits: int,
) -> dict:
    engine = Engine(workspace)
    prepared = engine.prepare(
        target, preset, overrides, keep={x, y}, require_numeric=False
    )
    if prepared.value.is_boolean:
        raise ParameterError("grid target must be numeric")
    x_name = engine.resolve_input_key(x, prepared.value.inputs)
    y_name = engine.resolve_input_key(y, prepared.value.inputs)
    if x_name == y_name:
        raise ParameterError("grid axes must use two different inputs")
    other_missing = prepared.missing - {x_name, y_name}
    if other_missing:
        raise ParameterError(
            f"{target} has unassigned non-axis inputs: " + ", ".join(sorted(other_missing))
        )
    x_spec = prepared.value.inputs[x_name]
    y_spec = prepared.value.inputs[y_name]
    if x_spec.value_type == "boolean" or y_spec.value_type == "boolean":
        raise ParameterError("grid axes must be numeric inputs")
    x_start, x_end = parse_range(
        x_range, x_spec.dimension, workspace, x_spec.unit_name
    )
    y_start, y_end = parse_range(
        y_range, y_spec.dimension, workspace, y_spec.unit_name
    )
    x_step = (x_end - x_start) / (x_points - 1)
    y_step = (y_end - y_start) / (y_points - 1)
    x_symbol = engine.input_symbol(x_name, x_spec)
    y_symbol = engine.input_symbol(y_name, y_spec)
    x_scale = engine.unit_scale_expr(x_spec.unit_name)
    y_scale = engine.unit_scale_expr(y_spec.unit_name)
    target_unit = engine.target_unit_name(target, prepared.value.dimension)
    target_scale = engine.unit_scale_expr(target_unit)
    target_display = display_options(workspace, target, display_digits)
    rows = []
    valid_points = 0
    for y_index in range(y_points):
        y_value = y_start + y_step * y_index
        for x_index in range(x_points):
            x_value = x_start + x_step * x_index
            row = {
                "x": exact_text(sp.simplify(x_value / x_scale)),
                "x_approximate": sp.sstr(
                    sp.N(x_value / x_scale, precision).evalf(display_digits)
                ),
                "y": exact_text(sp.simplify(y_value / y_scale)),
                "y_approximate": sp.sstr(
                    sp.N(y_value / y_scale, precision).evalf(display_digits)
                ),
            }
            try:
                engine._check_constraint(x_spec, x_value)
                engine._check_constraint(y_spec, y_value)
                substitutions = {x_symbol: x_value, y_symbol: y_value}
                engine.check_conditions(
                    condition.subs(substitutions) for condition in prepared.conditions
                )
                internal = sp.simplify(prepared.expr.subs(substitutions))
                _ensure_real_finite(internal)
                value = sp.simplify(internal / target_scale)
                row["value"] = {
                    "exact": exact_text(value),
                    "approximate": sp.sstr(
                        sp.N(value, precision).evalf(display_digits)
                    ),
                    "formatted": player_format(
                        value, target_display[0], target_display[1]
                    ),
                    "error": None,
                }
                valid_points += 1
            except (DomainError, ParameterError) as exc:
                row["value"] = {
                    "exact": None,
                    "approximate": None,
                    "formatted": None,
                    "error": str(exc),
                }
            rows.append(row)
    return {
        "status": "ok",
        "operation": "grid",
        "x": x_name,
        "x_display_label": x_spec.label,
        "x_unit": x_spec.unit_name,
        "x_range": [
            exact_text(sp.simplify(x_start / x_scale)),
            exact_text(sp.simplify(x_end / x_scale)),
        ],
        "x_points": x_points,
        "y": y_name,
        "y_display_label": y_spec.label,
        "y_unit": y_spec.unit_name,
        "y_range": [
            exact_text(sp.simplify(y_start / y_scale)),
            exact_text(sp.simplify(y_end / y_scale)),
        ],
        "y_points": y_points,
        "target": target,
        "target_label": engine.display_label(target) or target,
        "unit": target_unit,
        "points": x_points * y_points,
        "valid_points": valid_points,
        "parameters": parameter_text(engine, prepared),
        "precision": precision,
        "display_digits": display_digits,
        "rows": rows,
        "dependency_ids": sorted(prepared.value.dependencies),
    }


def scan_grid(
    engine: Engine,
    x: str,
    x_range: str,
    x_points: int,
    y: str,
    y_range: str,
    y_points: int,
    target: str,
    preset: Optional[str] = None,
    overrides: Optional[Mapping[str, str]] = None,
    precision: int = 30,
    display_digits: int = 12,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    precision_value(precision)
    if (
        isinstance(display_digits, bool)
        or not isinstance(display_digits, int)
        or display_digits < 1
        or display_digits > precision
    ):
        raise ParameterError("display digits must be between 1 and the numerical precision")
    for label, points in (("x", x_points), ("y", y_points)):
        if isinstance(points, bool) or not isinstance(points, int) or points < 2:
            raise ParameterError(f"grid {label} points must be at least 2")
    if x_points * y_points > MAX_SCAN_POINTS:
        raise ParameterError(
            f"grid may contain at most {MAX_SCAN_POINTS} total points"
        )
    return run_with_timeout(
        _scan_grid_core,
        (
            engine.workspace,
            x,
            x_range,
            x_points,
            y,
            y_range,
            y_points,
            target,
            preset,
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
        "label": engine.display_label(target),
        "expression": exact_text(value.expr),
        "unit": workspace.units.render(value.dimension),
        "is_boolean": value.is_boolean,
        "conditions": render_conditions(value.conditions),
        "inputs": {
            key: {
                "local_name": spec.name,
                "label": spec.label,
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
        "provenance": [
            {
                "entry": entry.id,
                "game_version": entry.game_version,
                "status": entry.validation_status,
                "sources": list(entry.sources),
                "package": (
                    {
                        "source": entry.package_origin.source,
                        "name": entry.package_origin.name,
                        "version": entry.package_origin.version,
                        "resolved": entry.package_origin.resolved,
                        "content_sha256": entry.package_origin.content_sha256,
                    }
                    if entry.package_origin is not None
                    else None
                ),
            }
            for entry in (
                workspace.entries[entry_id]
                for entry_id in sorted(value.dependencies)
                if entry_id in workspace.entries
            )
        ],
    }


def explain(
    engine: Engine,
    target: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    return run_with_timeout(_explain_core, (engine.workspace, target), timeout_seconds)
