"""Shared player-facing application services for the CLI and TUI adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence, Tuple, Union

import sympy as sp

from .engine import Engine
from .errors import KTError, ParameterError, WorkspaceError
from .expression import parse_exact_number
from .operations import evaluate, exact_text, scan_values
from .records import run_record_path, save_run
from .schema import require_parameter_name
from .workspace import Workspace


@dataclass(frozen=True)
class TargetOption:
    value: str
    label: str
    unit: str
    is_boolean: bool
    inputs: Tuple[str, ...] = ()
    group: Optional[str] = None
    group_label: Optional[str] = None
    display: str = "number"
    digits: Optional[int] = None
    package_name: Optional[str] = None
    package_version: Optional[str] = None
    package_source: Optional[str] = None


@dataclass(frozen=True)
class InputOption:
    value: str
    label: str
    unit: str
    value_type: str
    default: Optional[object]
    minimum: Optional[str]
    maximum: Optional[str]
    allowed_values: Tuple[object, ...]


@dataclass(frozen=True)
class NamedOption:
    value: str
    label: str


@dataclass(frozen=True)
class WorkspaceIndex:
    targets: Tuple[TargetOption, ...]
    inputs: Tuple[InputOption, ...]
    presets: Tuple[NamedOption, ...]
    plots: Tuple[NamedOption, ...]
    document_ids: Tuple[str, ...]

@dataclass(frozen=True)
class ComparisonVariant:
    name: str
    preset: Optional[str] = None
    overrides: Mapping[str, str] = None

    def normalized_overrides(self) -> Mapping[str, str]:
        return dict(self.overrides or {})

def parse_override_assignments(values: Iterable[str]) -> dict[str, str]:
    """Parse repeatable NAME=VALUE input with stable duplicate handling."""
    result: dict[str, str] = {}
    for value in values:
        if value.count("=") != 1:
            raise ParameterError("temporary input must use NAME=VALUE")
        name, number = (part.strip() for part in value.split("=", 1))
        require_parameter_name(name, "parameter name", None)
        if not number:
            raise ParameterError(f"temporary input {name!r} has no value")
        if name in result:
            raise ParameterError(f"parameter {name!r} was overridden more than once")
        result[name] = number
    return result


def parse_override_text(text: str) -> dict[str, str]:
    """Parse a player-facing comma/newline separated override field."""
    values = [item.strip() for line in text.splitlines() for item in line.split(",") if item.strip()]
    return parse_override_assignments(values)


def _normalize_player_value(value: str) -> str:
    value = value.strip()
    if value.endswith("%"):
        number = parse_exact_number(value[:-1].strip())
        return exact_text(sp.simplify(number / 100))
    return value


def parse_player_override_text(
    text: str, inputs: Sequence[InputOption]
) -> dict[str, str]:
    """Resolve canonical, local, or display input names and accept exact percentages."""
    assignments = [
        item.strip()
        for line in text.splitlines()
        for item in line.split(",")
        if item.strip()
    ]
    result: dict[str, str] = {}
    for assignment in assignments:
        if assignment.count("=") != 1:
            raise ParameterError("temporary input must use NAME=VALUE")
        supplied_name, supplied_value = (part.strip() for part in assignment.split("=", 1))
        if not supplied_name or not supplied_value:
            raise ParameterError("temporary input requires both a name and a value")
        matches = [
            item
            for item in inputs
            if supplied_name
            in {
                item.value,
                item.value.rsplit(".", 1)[-1],
                item.label,
            }
        ]
        if len(matches) > 1:
            raise ParameterError(
                f"temporary input {supplied_name!r} is ambiguous; use its full entry.input name"
            )
        if matches:
            canonical = matches[0].value
        else:
            require_parameter_name(supplied_name, "parameter name", None)
            canonical = supplied_name
        if canonical in result:
            raise ParameterError(f"parameter {canonical!r} was overridden more than once")
        result[canonical] = _normalize_player_value(supplied_value)
    return result


def build_workspace_index(workspace: Workspace) -> WorkspaceIndex:
    """Build immutable selectors from one already validated workspace revision."""
    engine = Engine(workspace)
    targets = []
    inputs = []
    for entry in sorted(workspace.entries.values(), key=lambda item: item.id):
        for name in sorted(entry.inputs):
            spec = entry.inputs[name]
            qualified = f"{entry.id}.{name}"
            inputs.append(
                InputOption(
                    qualified,
                    spec.label or qualified,
                    spec.unit_name,
                    spec.value_type,
                    spec.default,
                    spec.minimum,
                    spec.maximum,
                    tuple(spec.allowed_values),
                )
            )
        group_by_output = {
            output: group
            for group in entry.groups.values()
            for output in group.outputs
        }
        grouped_order = [
            output
            for group in entry.groups.values()
            for output in group.outputs
        ]
        output_order = grouped_order + [
            name for name in sorted(entry.outputs) if name not in group_by_output
        ]
        for name in output_order:
            qualified = f"{entry.id}.{name}"
            resolved = engine.resolve_target(qualified)
            group = group_by_output.get(name)
            targets.append(
                TargetOption(
                    qualified,
                    engine.display_label(qualified) or qualified,
                    workspace.units.render(resolved.dimension),
                    resolved.is_boolean,
                    tuple(sorted(resolved.inputs)),
                    group.qualified_id if group else None,
                    group.label if group else None,
                    entry.outputs[name].get("display", "number"),
                    entry.outputs[name].get("digits"),
                    entry.package_origin.name if entry.package_origin else None,
                    entry.package_origin.version if entry.package_origin else None,
                    entry.package_origin.source if entry.package_origin else None,
                )
            )
    presets = tuple(
        NamedOption(reference, preset.label)
        for reference, preset in sorted(workspace.presets.items())
    )
    plots = tuple(
        NamedOption(document.id, document.name)
        for document in sorted(workspace.plots.values(), key=lambda item: item.id)
    )
    return WorkspaceIndex(
        tuple(targets),
        tuple(inputs),
        presets,
        plots,
        tuple(sorted(workspace.documents)),
    )


def _render_number(expr: sp.Expr, precision: int, display_digits: int) -> str:
    return sp.sstr(sp.N(expr, precision).evalf(display_digits))


def compare_variants(
    workspace: Workspace,
    target: str,
    variants: Sequence[ComparisonVariant],
    *,
    precision: int = 30,
    display_digits: int = 12,
    timeout_seconds: float = 10.0,
) -> dict:
    """Evaluate named variants against one workspace revision and one target."""
    if not variants:
        raise ParameterError("comparison requires at least one variant")
    if len(variants) > 8:
        raise ParameterError("comparison supports at most 8 variants")
    normalized_names = [variant.name.strip() for variant in variants]
    if any(not name for name in normalized_names):
        raise ParameterError("every comparison variant requires a name")
    if len(set(normalized_names)) != len(normalized_names):
        raise ParameterError("comparison variant names must be unique")

    index = build_workspace_index(workspace)
    target_option = next((item for item in index.targets if item.value == target), None)
    if target_option is None:
        raise ParameterError(f"comparison target must be a declared output: {target}")

    rows = []
    for name, variant in zip(normalized_names, variants):
        try:
            result = evaluate(
                Engine(workspace),
                target,
                preset=variant.preset,
                overrides=variant.normalized_overrides(),
                precision=precision,
                display_digits=display_digits,
                timeout_seconds=timeout_seconds,
            )
            rows.append(
                {
                    "name": name,
                    "preset": variant.preset,
                    "overrides": dict(variant.normalized_overrides()),
                    "status": "ok",
                    "result": result,
                    "delta_exact": None,
                    "delta_approximate": None,
                    "delta_percent": None,
                }
            )
        except KTError as exc:
            rows.append(
                {
                    "name": name,
                    "preset": variant.preset,
                    "overrides": dict(variant.normalized_overrides()),
                    "status": "error",
                    "error": exc.as_dict(),
                    "delta_exact": None,
                    "delta_approximate": None,
                    "delta_percent": None,
                }
            )

    baseline = rows[0]
    if baseline["status"] == "ok" and not target_option.is_boolean:
        baseline_expr = sp.sympify(baseline["result"]["exact"])
        for row in rows[1:]:
            if row["status"] != "ok":
                continue
            current_expr = sp.sympify(row["result"]["exact"])
            delta = sp.simplify(current_expr - baseline_expr)
            row["delta_exact"] = exact_text(delta)
            row["delta_approximate"] = _render_number(delta, precision, display_digits)
            if baseline_expr != 0:
                percentage = sp.simplify(delta * 100 / baseline_expr)
                row["delta_percent"] = _render_number(percentage, precision, display_digits)

    successful = [row for row in rows if row["status"] == "ok"]
    dependency_ids = sorted(
        {
            dependency
            for row in successful
            for dependency in row["result"].get("dependency_ids", [])
        }
    )
    return {
        "status": "ok" if len(successful) == len(rows) else "partial",
        "operation": "compare",
        "target": target,
        "label": target_option.label,
        "unit": target_option.unit,
        "is_boolean": target_option.is_boolean,
        "precision": precision,
        "display_digits": display_digits,
        "display_format": target_option.display,
        "display_digits_player": target_option.digits,
        "package_origin": (
            {
                "name": target_option.package_name,
                "version": target_option.package_version,
                "source": target_option.package_source,
            }
            if target_option.package_source is not None
            else None
        ),
        "variants": rows,
        "dependency_ids": dependency_ids,
    }


def save_comparison_run(
    workspace: Workspace,
    run_id: str,
    target: str,
    variants: Sequence[ComparisonVariant],
    *,
    precision: int = 30,
    display_digits: int = 12,
    timeout_seconds: float = 10.0,
) -> dict:
    """Recompute and save one comparison against saved, validated source authority."""
    request = {
        "target": target,
        "variants": [
            {
                "name": variant.name,
                "preset": variant.preset,
                "overrides": dict(variant.normalized_overrides()),
            }
            for variant in variants
        ],
        "precision": precision,
        "display_digits": display_digits,
        "timeout_seconds": timeout_seconds,
    }
    preset_document_ids = {
        workspace.get_preset(variant.preset).owner_id
        for variant in variants
        if variant.preset is not None
    }
    return record_operation(
        workspace,
        run_id,
        "compare",
        request,
        lambda: compare_variants(
            workspace,
            target,
            variants,
            precision=precision,
            display_digits=display_digits,
            timeout_seconds=timeout_seconds,
        ),
        preset_document_ids,
    )


def scan_variant_comparison(
    workspace: Workspace,
    x: str,
    range_text: str,
    points: int,
    target: str,
    variants: Sequence[ComparisonVariant],
    *,
    precision: int = 30,
    display_digits: int = 12,
    timeout_seconds: float = 10.0,
) -> dict:
    """Scan one output for several player variants on one shared axis."""
    if not variants:
        raise ParameterError("chart comparison requires at least one variant")
    if len(variants) > 8:
        raise ParameterError("chart comparison supports at most 8 variants")
    names = [variant.name.strip() for variant in variants]
    if any(not name for name in names) or len(set(names)) != len(names):
        raise ParameterError("chart comparison variants require unique non-empty names")

    scans = []
    scan_errors = []
    for variant in variants:
        try:
            scans.append(
                scan_values(
                    Engine(workspace),
                    x,
                    range_text,
                    points,
                    [target],
                    variant.preset,
                    variant.normalized_overrides(),
                    precision,
                    display_digits,
                    timeout_seconds,
                )
            )
            scan_errors.append(None)
        except KTError as exc:
            scans.append(None)
            scan_errors.append(str(exc))
    first = next((scan for scan in scans if scan is not None), None)
    if first is None:
        raise ParameterError(f"all chart variants failed; first error: {scan_errors[0]}")
    if any(
        scan is not None
        and (scan["x"] != first["x"] or scan["range"] != first["range"])
        for scan in scans
    ):
        raise ParameterError("chart variants did not resolve to one shared input axis")
    variant_targets = [f"variant_{index + 1}" for index in range(len(variants))]
    rows = []
    for row_index, first_row in enumerate(first["rows"]):
        row = {
            "x": first_row["x"],
            "x_approximate": first_row["x_approximate"],
            "values": {},
        }
        for key, scan, scan_error in zip(variant_targets, scans, scan_errors):
            row["values"][key] = (
                dict(scan["rows"][row_index]["values"][target])
                if scan is not None
                else {"exact": None, "approximate": None, "error": scan_error}
            )
        rows.append(row)
    unit = first["units"][target]
    return {
        "status": "partial" if any(scan_errors) else "ok",
        "operation": "scan_compare",
        "x": first["x"],
        "x_display_label": first.get("x_display_label"),
        "x_unit": first["x_unit"],
        "x_domain": first.get("x_domain"),
        "range": first["range"],
        "points": points,
        "targets": variant_targets,
        "labels": dict(zip(variant_targets, names)),
        "units": {key: unit for key in variant_targets},
        "parameters": {
            key: (
                scan.get("parameters", {})
                if scan is not None
                else dict(variant.normalized_overrides())
            )
            for key, scan, variant in zip(variant_targets, scans, variants)
        },
        "valid_points": {
            key: scan["valid_points"][target] if scan is not None else 0
            for key, scan in zip(variant_targets, scans)
        },
        "warnings": sorted(
            {
                warning
                for scan in scans
                if scan is not None
                for warning in scan.get("warnings", [])
            }
            | {
                f"方案 {name} 无法计算：{error}"
                for name, error in zip(names, scan_errors)
                if error is not None
            }
        ),
        "precision": precision,
        "display_digits": display_digits,
        "rows": rows,
        "variants": [
            {
                "key": key,
                "name": name,
                "preset": variant.preset,
                "overrides": dict(variant.normalized_overrides()),
                "status": "error" if error is not None else "ok",
                "error": error,
            }
            for key, name, variant, error in zip(variant_targets, names, variants, scan_errors)
        ],
        "dependency_ids": sorted(
            {
                dependency
                for scan in scans
                if scan is not None
                for dependency in scan.get("dependency_ids", [])
            }
        ),
    }


def artifact_path(
    workspace_or_root: Union[Workspace, Path], text: str, allow_outside: bool = False
) -> Path:
    """Resolve an artifact with the same default workspace boundary for every adapter."""
    root = (
        workspace_or_root.root
        if isinstance(workspace_or_root, Workspace)
        else Path(workspace_or_root).resolve()
    )
    path = Path(text)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not allow_outside:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ParameterError(
                f"output path leaves the workspace; pass --allow-outside-workspace explicitly: {resolved}"
            ) from exc
    return resolved


def preflight_artifacts(paths: Sequence[Path], force: bool) -> None:
    if len(set(paths)) != len(paths):
        raise ParameterError("plot and data outputs must use different paths")
    if not force:
        existing = [path for path in paths if path.exists()]
        if existing:
            raise ParameterError(
                "output file already exists; use --force to replace it: "
                + ", ".join(map(str, existing))
            )


def record_operation(
    workspace: Workspace,
    save_run_id: Optional[str],
    operation: str,
    request: dict,
    compute: Callable[[], dict],
    extra_document_ids: Iterable[str] = (),
) -> dict:
    """Execute and optionally record one operation, including stable failures."""
    if save_run_id:
        candidate = run_record_path(workspace, save_run_id)
        if candidate.exists():
            raise WorkspaceError(
                f"run record already exists and will not be overwritten: {candidate}"
            )
    try:
        result = compute()
    except KTError as exc:
        if save_run_id:
            save_run(
                workspace,
                save_run_id,
                operation,
                request,
                exc.as_dict(),
                workspace.documents.keys(),
            )
        raise
    except Exception as exc:
        if save_run_id:
            failure = {
                "status": "error",
                "code": "internal_operation_error",
                "message": str(exc),
            }
            save_run(
                workspace,
                save_run_id,
                operation,
                request,
                failure,
                workspace.documents.keys(),
            )
        raise
    if save_run_id:
        final_request = dict(request)
        final_request["effective_parameters"] = result.get("parameters", {})
        normalized_extra_ids = set()
        for reference in extra_document_ids:
            if reference in workspace.documents:
                normalized_extra_ids.add(reference)
                continue
            preset = workspace.get_preset(reference)
            if preset is not None:
                normalized_extra_ids.add(preset.owner_id)
        document_ids = set(result.get("dependency_ids", [])) | normalized_extra_ids
        path = save_run(
            workspace,
            save_run_id,
            operation,
            final_request,
            result,
            document_ids,
        )
        result["run_record"] = str(path)
    return result
