"""Typer command-line adapter for the Kirin Tor math kernel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

import typer
import yaml

from . import __version__
from .engine import Engine
from .errors import KTError, ParameterError
from .limits import DEFAULT_TIMEOUT_SECONDS
from .operations import differentiate, evaluate, explain, scan_values, solve_equation, transform
from .plotting import render_plot, write_scan_csv
from .records import replay as replay_run
from .records import run_record_path, save_run
from .schema import require_identifier, require_parameter_name
from .timeout import run_with_timeout
from .workspace import (
    AVAILABLE_PACKAGES,
    Workspace,
    create_entry_template,
    create_plot_template,
    create_scenario_template,
    initialize,
)


app = typer.Typer(
    name="kt",
    help="Kirin Tor: game-neutral, file-driven structured mathematics for theorycrafting.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
new_app = typer.Typer(help="Create an entry from a minimal schema-v1 template.")
app.add_typer(new_app, name="new")


def _emit(result: dict, json_output: bool, human: Optional[str] = None) -> None:
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(human if human is not None else yaml.safe_dump(result, allow_unicode=True, sort_keys=False).rstrip())


def _execute(action: Callable[[], None], json_output: bool = False) -> None:
    try:
        action()
    except KTError as exc:
        if json_output:
            typer.echo(json.dumps(exc.as_dict(), ensure_ascii=False, sort_keys=True))
        typer.echo(f"Error [{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=1)
    except typer.Exit:
        raise
    except Exception as exc:
        payload = {"status": "error", "code": "internal_operation_error", "message": str(exc)}
        if json_output:
            typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        typer.echo(f"Error [internal_operation_error]: {exc}", err=True)
        raise typer.Exit(code=1)


def _parse_sets(values: List[str]) -> Dict[str, str]:
    result = {}
    for value in values:
        if value.count("=") != 1:
            raise ParameterError("--set must use NAME=VALUE")
        name, number = value.split("=", 1)
        require_parameter_name(name, "parameter name", None)
        if name in result:
            raise ParameterError(f"parameter {name!r} was overridden more than once")
        result[name] = number
    return result


def _artifact_path(workspace: Union[Workspace, Path], text: str, allow_outside: bool = False) -> Path:
    root = workspace.root if isinstance(workspace, Workspace) else Path(workspace).resolve()
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


def _preflight_artifacts(paths: List[Path], force: bool) -> None:
    if len(set(paths)) != len(paths):
        raise ParameterError("plot and data outputs must use different paths")
    if not force:
        existing = [path for path in paths if path.exists()]
        if existing:
            raise ParameterError(
                "output file already exists; use --force to replace it: " + ", ".join(map(str, existing))
            )


def _validate_workspace(workspace: Workspace) -> dict:
    return Engine(workspace).validate_all()


def _recorded_compute(
    workspace: Workspace,
    save_run_id: Optional[str],
    operation: str,
    request: dict,
    compute: Callable[[], dict],
    extra_document_ids=(),
) -> dict:
    if save_run_id:
        candidate = run_record_path(workspace, save_run_id)
        if candidate.exists():
            from .errors import WorkspaceError

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
            failure = {"status": "error", "code": "internal_operation_error", "message": str(exc)}
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
        document_ids = set(result.get("dependency_ids", [])) | set(extra_document_ids)
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


@app.command("version")
def version_command() -> None:
    """Print the installed Kirin Tor CLI version."""
    typer.echo(__version__)


@app.command("init")
def init_command(
    directory: Path,
    package_name: str = typer.Option(
        "none", "--package", help=f"Data-only starter package: {', '.join(sorted(AVAILABLE_PACKAGES))}."
    ),
) -> None:
    """Create a new workspace directory."""
    def action():
        root = initialize(directory, package_name)
        typer.echo(f"Initialized Kirin Tor workspace: {root} (package={package_name})")

    _execute(action)


def _new_entry(entry_type: str, entry_id: str) -> None:
    def action():
        workspace = Workspace.discover()
        path = create_entry_template(workspace, entry_type, entry_id)
        typer.echo(str(path))

    _execute(action)


@new_app.command("skill")
def new_skill(entry_id: str) -> None:
    """Create a skill/data entry template."""
    _new_entry("skill", entry_id)


@new_app.command("model")
def new_model(entry_id: str) -> None:
    """Create a combination model template."""
    _new_entry("model", entry_id)


@new_app.command("entry")
def new_entry(entry_id: str) -> None:
    """Create a game-neutral entry template."""
    _new_entry("entry", entry_id)


@new_app.command("scenario")
def new_scenario(scenario_id: str) -> None:
    """Create a parameter scenario template."""
    def action():
        typer.echo(str(create_scenario_template(Workspace.discover(), scenario_id)))

    _execute(action)


@new_app.command("plot")
def new_plot(plot_id: str) -> None:
    """Create a saved plot configuration template."""
    def action():
        typer.echo(str(create_plot_template(Workspace.discover(), plot_id)))

    _execute(action)


@app.command("list")
def list_command(json_output: bool = typer.Option(False, "--json", help="Write JSON to stdout.")) -> None:
    """List loaded documents by stable id."""
    def action():
        workspace = Workspace.discover()
        items = [
            {
                "id": document.id,
                "name": document.name,
                "type": document.type,
                "template": getattr(document, "template", None),
                "path": str(document.path.relative_to(workspace.root)),
            }
            for document in sorted(workspace.documents.values(), key=lambda item: item.id)
        ]
        _emit(
            {"status": "ok", "documents": items},
            json_output,
            "\n".join(
                f"{item['id']:<20} {item['type']:<10} {(item['template'] or '-'):<12} {item['name']}"
                for item in items
            ),
        )

    _execute(action, json_output)


@app.command("show")
def show_command(entry_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
    """Show a document by stable id."""
    def action():
        workspace = Workspace.discover()
        if entry_id not in workspace.documents:
            from .errors import ReferenceError
            raise ReferenceError(f"unknown document id {entry_id!r}")
        raw = workspace.documents[entry_id].raw
        _emit({"status": "ok", "document": raw}, json_output, yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).rstrip())

    _execute(action, json_output)


@app.command("explain")
def explain_command(
    target: str,
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show a target's expanded expression, inputs, conditions, units, and dependencies."""
    def action():
        result = explain(Engine(Workspace.discover()), target, timeout)
        _emit(result, json_output)

    _execute(action, json_output)


@app.command("check")
def check_command(
    json_output: bool = typer.Option(False, "--json", help="Write JSON to stdout."),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
) -> None:
    """Validate every document, reference, unit, expression, and dependency."""
    def action():
        workspace = Workspace.load_for_check(Workspace.find_root())
        result = run_with_timeout(_validate_workspace, (workspace,), timeout)
        _emit(result, json_output, f"OK: {result['documents']} documents; {len(result['checked'])} mathematical definitions checked")

    _execute(action, json_output)


@app.command("eval")
def eval_command(
    target: str,
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set", help="Override NAME=VALUE; repeatable."),
    precision: int = typer.Option(30, "--precision"),
    display_digits: int = typer.Option(12, "--display-digits"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Evaluate an output numerically using defaults < scenario < --set."""
    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        request = {
            "target": target,
            "scenario": scenario,
            "overrides": overrides,
            "precision": precision,
            "display_digits": display_digits,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            "eval",
            request,
            lambda: evaluate(Engine(workspace), target, scenario, overrides, precision, display_digits, timeout),
            [scenario] if scenario else [],
        )
        _emit(result, json_output, f"{result['exact']} {result['unit']} (≈ {result['approximate']})")

    _execute(action, json_output)


def _transform_command(
    operation: str,
    target: str,
    scenario: Optional[str],
    set_values: List[str],
    keep: List[str],
    timeout: float,
    save_run_id: Optional[str],
    json_output: bool,
) -> None:
    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        request = {
            "target": target,
            "scenario": scenario,
            "overrides": overrides,
            "keep": keep,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            operation,
            request,
            lambda: transform(Engine(workspace), operation, target, scenario, overrides, keep, timeout),
            [scenario] if scenario else [],
        )
        _emit(result, json_output, f"{result['expression']} [{result['unit']}]")

    _execute(action, json_output)


@app.command("simplify")
def simplify_command(
    target: str,
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    keep: List[str] = typer.Option([], "--keep", help="Retain this declared variable; repeatable."),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Simplify an output or ad-hoc expression."""
    _transform_command("simplify", target, scenario, set_values, keep, timeout, save_run_id, json_output)


@app.command("expand")
def expand_command(
    target: str,
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    keep: List[str] = typer.Option([], "--keep"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Expand an output or ad-hoc expression."""
    _transform_command("expand", target, scenario, set_values, keep, timeout, save_run_id, json_output)


@app.command("factor")
def factor_command(
    target: str,
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    keep: List[str] = typer.Option([], "--keep"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Factor an output or ad-hoc expression."""
    _transform_command("factor", target, scenario, set_values, keep, timeout, save_run_id, json_output)


@app.command("diff")
def diff_command(
    target: str,
    variable: str = typer.Option(..., "--var"),
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Differentiate with respect to a declared variable."""
    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        request = {
            "target": target,
            "variable": variable,
            "scenario": scenario,
            "overrides": overrides,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            "diff",
            request,
            lambda: differentiate(Engine(workspace), target, variable, scenario, overrides, timeout),
            [scenario] if scenario else [],
        )
        _emit(result, json_output, f"{result['expression']} [{result['unit']}]")

    _execute(action, json_output)


@app.command("solve")
def solve_command(
    target: str,
    variable: str = typer.Option(..., "--var"),
    equals: str = typer.Option(..., "--equals", help="Target value, optionally followed by a unit."),
    range_text: Optional[str] = typer.Option(None, "--range"),
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    precision: int = typer.Option(30, "--precision"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Solve one real-variable equation, optionally inside a closed range."""
    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        request = {
            "target": target,
            "variable": variable,
            "equals": equals,
            "range": range_text,
            "scenario": scenario,
            "overrides": overrides,
            "precision": precision,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            "solve",
            request,
            lambda: solve_equation(Engine(workspace), target, variable, equals, range_text, scenario, overrides, precision, timeout),
            [scenario] if scenario else [],
        )
        if result["solution_kind"] in {"exact", "numeric_approximate"}:
            human = ", ".join(solution["exact"] for solution in result["solutions"])
        elif result["solution_kind"] == "no_solution_proven":
            human = "No real solution in the requested domain (proven by the symbolic solver)."
        else:
            human = f"Incomplete solve: {result.get('solution_set')}"
        _emit(result, json_output, human)
        if result["status"] == "incomplete":
            typer.echo("Solver did not produce a completed solution.", err=True)
            raise typer.Exit(code=1)

    _execute(action, json_output)


@app.command("scan")
def scan_command(
    x: str = typer.Option(..., "--x"),
    range_text: str = typer.Option(..., "--range"),
    points: int = typer.Option(..., "--points"),
    targets: List[str] = typer.Option(..., "--y"),
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    out: Optional[str] = typer.Option(None, "--out", help="CSV output path."),
    precision: int = typer.Option(30, "--precision"),
    display_digits: int = typer.Option(12, "--display-digits"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    force: bool = typer.Option(False, "--force", help="Replace an existing output file."),
    allow_outside: bool = typer.Option(False, "--allow-outside-workspace"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Sample one axis for one or more outputs; invalid points retain error reasons."""
    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        request = {
            "x": x,
            "range": range_text,
            "points": points,
            "targets": targets,
            "scenario": scenario,
            "overrides": overrides,
            "precision": precision,
            "display_digits": display_digits,
            "timeout_seconds": timeout,
            "out": out,
        }
        output_path = _artifact_path(workspace, out, allow_outside) if out else None
        if output_path:
            _preflight_artifacts([output_path], force)

        def compute_scan() -> dict:
            computed = scan_values(
                Engine(workspace), x, range_text, points, targets, scenario, overrides,
                precision, display_digits, timeout
            )
            if output_path:
                computed["out"] = str(write_scan_csv(computed, output_path, overwrite=force))
            return computed

        result = _recorded_compute(
            workspace,
            save_run_id,
            "scan",
            request,
            compute_scan,
            [scenario] if scenario else [],
        )
        human_lines = ["x\t" + "\t".join(targets)]
        for row in result["rows"]:
            values = [row["values"][target]["exact"] or f"ERROR: {row['values'][target]['error']}" for target in targets]
            human_lines.append(row["x"] + "\t" + "\t".join(values))
        if out:
            human_lines.append(f"CSV: {result['out']}")
        for warning in result.get("warnings", []):
            typer.echo(f"Warning: {warning}", err=True)
        _emit(result, json_output, "\n".join(human_lines))

    _execute(action, json_output)


@app.command("plot")
def plot_command(
    x: Optional[str] = typer.Option(None, "--x"),
    range_text: Optional[str] = typer.Option(None, "--range"),
    points: Optional[int] = typer.Option(None, "--points"),
    targets: List[str] = typer.Option([], "--y"),
    scenario: Optional[str] = typer.Option(None, "--scenario"),
    set_values: List[str] = typer.Option([], "--set"),
    out: Optional[str] = typer.Option(None, "--out"),
    data_out: Optional[str] = typer.Option(None, "--data-out"),
    config: Optional[str] = typer.Option(None, "--config", help="Saved plot config id."),
    precision: int = typer.Option(30, "--precision"),
    display_digits: int = typer.Option(12, "--display-digits"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    force: bool = typer.Option(False, "--force", help="Replace existing plot/CSV files."),
    allow_outside: bool = typer.Option(False, "--allow-outside-workspace"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Generate SVG/PNG from the exact same scan/evaluation pipeline."""
    def action():
        workspace = Workspace.discover()
        chosen_x, chosen_range, chosen_points = x, range_text, points
        chosen_targets, chosen_scenario = list(targets), scenario
        chosen_out, chosen_data_out = out, data_out
        title = x_label = y_label = None
        curve_labels = {}
        if config:
            saved = workspace.get_plot(config)
            chosen_x = chosen_x or saved.x
            chosen_range = chosen_range or f"{saved.range_start}:{saved.range_end}"
            chosen_points = chosen_points or saved.points
            chosen_targets = chosen_targets or saved.y
            chosen_scenario = chosen_scenario or saved.scenario
            chosen_out = chosen_out or saved.out
            chosen_data_out = chosen_data_out or saved.data_out
            title, x_label, y_label = saved.title, saved.x_label, saved.y_label
            curve_labels = saved.curve_labels
        if chosen_x is None or chosen_range is None or chosen_points is None or not chosen_targets or chosen_out is None:
            raise ParameterError("plot requires --x, --range, --points, at least one --y, and --out (directly or via --config)")
        overrides = _parse_sets(set_values)
        request = {
            "x": chosen_x,
            "range": chosen_range,
            "points": chosen_points,
            "targets": chosen_targets,
            "scenario": chosen_scenario,
            "overrides": overrides,
            "precision": precision,
            "display_digits": display_digits,
            "timeout_seconds": timeout,
            "config": config,
            "out": chosen_out,
            "data_out": chosen_data_out,
            "title": title,
            "x_label": x_label,
            "y_label": y_label,
            "curve_labels": curve_labels,
        }
        extra_ids = [item for item in (chosen_scenario, config) if item]
        plot_path = _artifact_path(workspace, chosen_out, allow_outside)
        data_path = (
            _artifact_path(workspace, chosen_data_out, allow_outside) if chosen_data_out else None
        )
        _preflight_artifacts([path for path in (plot_path, data_path) if path is not None], force)

        def compute_plot() -> dict:
            computed = scan_values(
                Engine(workspace),
                chosen_x,
                chosen_range,
                chosen_points,
                chosen_targets,
                chosen_scenario,
                overrides,
                precision,
                display_digits,
                timeout,
            )
            computed["operation"] = "plot"
            computed["out"] = str(
                run_with_timeout(
                    render_plot,
                    (computed, plot_path, force, title, x_label, y_label, curve_labels),
                    timeout,
                )
            )
            if chosen_data_out:
                computed["data_out"] = str(
                    write_scan_csv(
                        computed,
                        data_path,
                        overwrite=force,
                    )
                )
            return computed

        result = _recorded_compute(
            workspace,
            save_run_id,
            "plot",
            request,
            compute_plot,
            extra_ids,
        )
        for warning in result.get("warnings", []):
            typer.echo(f"Warning: {warning}", err=True)
        human = f"Plot: {result['out']}" + (f"\nCSV: {result['data_out']}" if "data_out" in result else "")
        _emit(result, json_output, human)

    _execute(action, json_output)


@app.command("replay")
def replay_command(
    run_id: str,
    regenerate_artifacts: bool = typer.Option(False, "--regenerate-artifacts"),
    out: Optional[str] = typer.Option(None, "--out"),
    data_out: Optional[str] = typer.Option(None, "--data-out"),
    force: bool = typer.Option(False, "--force"),
    allow_outside: bool = typer.Option(False, "--allow-outside-workspace"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Replay a saved run using only its embedded definition snapshots."""
    def action():
        root = Workspace.find_root()
        out_path = _artifact_path(root, out, allow_outside) if out else None
        data_path = _artifact_path(root, data_out, allow_outside) if data_out else None
        result = replay_run(
            root,
            run_id,
            regenerate_artifacts=regenerate_artifacts,
            out=out_path,
            data_out=data_path,
            force=force,
        )
        human = (
            f"Replayed {result['original_operation']} with embedded definitions; "
            f"match={result['matches_recorded_result']}; environment_match={result['environment_match']}"
        )
        if result["version_drift"]:
            typer.echo("Warning: dependency version drift was detected; see --json for details.", err=True)
        _emit(result, json_output, human)

    _execute(action, json_output)


if __name__ == "__main__":
    app()
