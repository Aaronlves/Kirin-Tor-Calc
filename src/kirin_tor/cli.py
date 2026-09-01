"""Typer command-line adapter for the Kirin Tor math kernel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional

import typer

from . import __version__
from .application import (
    artifact_path as _artifact_path,
    parse_override_assignments as _parse_sets,
    preflight_artifacts as _preflight_artifacts,
    record_operation as _recorded_compute,
)
from .engine import Engine
from .errors import KTError, ParameterError, UnsupportedError
from .limits import DEFAULT_TIMEOUT_SECONDS
from .operations import (
    differentiate,
    evaluate,
    explain,
    scan_grid,
    scan_values,
    solve_equation,
    solve_system,
    transform,
)
from .plotting import render_plot, write_grid_csv, write_scan_csv
from .records import replay as replay_run
from .timeout import run_with_timeout
from .workspace import (
    AVAILABLE_PACKAGES,
    Workspace,
    create_entry_template,
    create_plot_template,
    initialize,
)


app = typer.Typer(
    name="kt",
    help="Kirin Tor: game-neutral, file-driven structured mathematics for theorycrafting.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
new_app = typer.Typer(help="Create an entry or plot from a minimal Kirin v1 template.")
app.add_typer(new_app, name="new")


def _emit(result: dict, json_output: bool, human: Optional[str] = None) -> None:
    if json_output:
        typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(human if human is not None else json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


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


def _validate_workspace(workspace: Workspace) -> dict:
    return Engine(workspace).validate_all()


@app.command("version")
def version_command() -> None:
    """Print the installed Kirin Tor CLI version."""
    typer.echo(__version__)


@app.command("tui")
def tui_command(
    source: Optional[Path] = typer.Argument(
        None,
        help="Workspace directory or Kirin source path; defaults to the current workspace.",
    ),
) -> None:
    """Open the player calculation, chart, document, diagnostics, and runs workbench."""
    def action():
        requested = source
        if requested is not None and requested.expanduser().is_dir():
            root = requested.expanduser().resolve()
            requested = None
        elif requested is not None and requested.expanduser().is_absolute():
            requested = requested.expanduser().resolve()
            root = Workspace.find_root(requested.parent)
        else:
            root = Workspace.find_root()
        try:
            from .tui import run_tui
        except ModuleNotFoundError as exc:
            raise UnsupportedError(
                "TUI dependencies are not installed; install 'kirin-tor-cli[tui]'"
            ) from exc
        run_tui(root, requested)

    _execute(action)


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


@new_app.command("entry")
def new_entry(
    entry_id: str,
    template: str = typer.Option(
        "model", "--template", help="Starting template: blank, data, model, or semantics."
    ),
) -> None:
    """Create a game-neutral entry template."""
    _new_entry(template, entry_id)


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
        document = workspace.documents[entry_id]
        _emit({"status": "ok", "document": document.raw}, json_output, document.raw_text.rstrip())

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
    preset: Optional[str] = typer.Option(None, "--preset"),
    set_values: List[str] = typer.Option([], "--set", help="Override NAME=VALUE; repeatable."),
    precision: int = typer.Option(30, "--precision"),
    display_digits: int = typer.Option(12, "--display-digits"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Evaluate an output numerically using defaults < preset < --set."""
    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        request = {
            "target": target,
            "preset": preset,
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
            lambda: evaluate(Engine(workspace), target, preset, overrides, precision, display_digits, timeout),
            [preset] if preset else [],
        )
        _emit(
            result,
            json_output,
            f"{result.get('formatted', result['approximate'])} [{result['unit']}]"
            f"\nexact: {result['exact']}",
        )

    _execute(action, json_output)


def _transform_command(
    operation: str,
    target: str,
    preset: Optional[str],
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
            "preset": preset,
            "overrides": overrides,
            "keep": keep,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            operation,
            request,
            lambda: transform(Engine(workspace), operation, target, preset, overrides, keep, timeout),
            [preset] if preset else [],
        )
        _emit(result, json_output, f"{result['expression']} [{result['unit']}]")

    _execute(action, json_output)


@app.command("simplify")
def simplify_command(
    target: str,
    preset: Optional[str] = typer.Option(None, "--preset"),
    set_values: List[str] = typer.Option([], "--set"),
    keep: List[str] = typer.Option([], "--keep", help="Retain this declared variable; repeatable."),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Simplify an output or ad-hoc expression."""
    _transform_command("simplify", target, preset, set_values, keep, timeout, save_run_id, json_output)


@app.command("expand")
def expand_command(
    target: str,
    preset: Optional[str] = typer.Option(None, "--preset"),
    set_values: List[str] = typer.Option([], "--set"),
    keep: List[str] = typer.Option([], "--keep"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Expand an output or ad-hoc expression."""
    _transform_command("expand", target, preset, set_values, keep, timeout, save_run_id, json_output)


@app.command("factor")
def factor_command(
    target: str,
    preset: Optional[str] = typer.Option(None, "--preset"),
    set_values: List[str] = typer.Option([], "--set"),
    keep: List[str] = typer.Option([], "--keep"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Factor an output or ad-hoc expression."""
    _transform_command("factor", target, preset, set_values, keep, timeout, save_run_id, json_output)


@app.command("diff")
def diff_command(
    target: str,
    variable: str = typer.Option(..., "--var"),
    preset: Optional[str] = typer.Option(None, "--preset"),
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
            "preset": preset,
            "overrides": overrides,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            "diff",
            request,
            lambda: differentiate(Engine(workspace), target, variable, preset, overrides, timeout),
            [preset] if preset else [],
        )
        _emit(result, json_output, f"{result['expression']} [{result['unit']}]")

    _execute(action, json_output)


@app.command("solve")
def solve_command(
    target: str,
    variable: str = typer.Option(..., "--var"),
    equals: str = typer.Option(..., "--equals", help="Target value, optionally followed by a unit."),
    range_text: Optional[str] = typer.Option(None, "--range"),
    preset: Optional[str] = typer.Option(None, "--preset"),
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
            "preset": preset,
            "overrides": overrides,
            "precision": precision,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            "solve",
            request,
            lambda: solve_equation(Engine(workspace), target, variable, equals, range_text, preset, overrides, precision, timeout),
            [preset] if preset else [],
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


@app.command("solve-system")
def solve_system_command(
    equations: List[str] = typer.Option(
        ..., "--equation", help="Repeat TARGET=VALUE, with an optional unit after VALUE."
    ),
    variables: List[str] = typer.Option(..., "--var"),
    preset: Optional[str] = typer.Option(None, "--preset"),
    set_values: List[str] = typer.Option([], "--set"),
    precision: int = typer.Option(30, "--precision"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Solve up to eight linked equations for up to eight player inputs."""

    def action():
        workspace = Workspace.discover()
        parsed_equations = []
        for equation in equations:
            if equation.count("=") != 1:
                raise ParameterError("system equation must use TARGET=VALUE")
            target, equals = (part.strip() for part in equation.split("=", 1))
            if not target or not equals:
                raise ParameterError("system equation requires both TARGET and VALUE")
            parsed_equations.append((target, equals))
        overrides = _parse_sets(set_values)
        request = {
            "equations": [
                {"target": target, "equals": equals}
                for target, equals in parsed_equations
            ],
            "variables": variables,
            "preset": preset,
            "overrides": overrides,
            "precision": precision,
            "timeout_seconds": timeout,
        }
        result = _recorded_compute(
            workspace,
            save_run_id,
            "solve_system",
            request,
            lambda: solve_system(
                Engine(workspace),
                parsed_equations,
                variables,
                preset,
                overrides,
                precision,
                timeout,
            ),
            [preset] if preset else [],
        )
        if result["solution_kind"] == "exact":
            lines = []
            for solution in result["solutions"]:
                lines.append(
                    ", ".join(
                        f"{name}={value['exact']} {value['unit']}"
                        for name, value in solution["values"].items()
                    )
                )
            human = "\n".join(lines)
        elif result["solution_kind"] == "no_solution_proven":
            human = "No solution satisfies the declared input domains."
        else:
            human = f"Incomplete system solve: {result.get('solution_set')}"
        _emit(result, json_output, human)
        if result["status"] == "incomplete":
            raise typer.Exit(code=1)

    _execute(action, json_output)


@app.command("scan")
def scan_command(
    x: str = typer.Option(..., "--x"),
    range_text: str = typer.Option(..., "--range"),
    points: int = typer.Option(..., "--points"),
    targets: List[str] = typer.Option(..., "--y"),
    preset: Optional[str] = typer.Option(None, "--preset"),
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
            "preset": preset,
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
                Engine(workspace), x, range_text, points, targets, preset, overrides,
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
            [preset] if preset else [],
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


@app.command("grid")
def grid_command(
    x: str = typer.Option(..., "--x"),
    x_range: str = typer.Option(..., "--x-range"),
    x_points: int = typer.Option(..., "--x-points"),
    y: str = typer.Option(..., "--y"),
    y_range: str = typer.Option(..., "--y-range"),
    y_points: int = typer.Option(..., "--y-points"),
    target: str = typer.Option(..., "--result"),
    preset: Optional[str] = typer.Option(None, "--preset"),
    set_values: List[str] = typer.Option([], "--set"),
    out: Optional[str] = typer.Option(None, "--out", help="CSV output path."),
    precision: int = typer.Option(30, "--precision"),
    display_digits: int = typer.Option(12, "--display-digits"),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    force: bool = typer.Option(False, "--force"),
    allow_outside: bool = typer.Option(False, "--allow-outside-workspace"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Scan two inputs and produce heatmap-ready rows."""

    def action():
        workspace = Workspace.discover()
        overrides = _parse_sets(set_values)
        output_path = _artifact_path(workspace, out, allow_outside) if out else None
        if output_path:
            _preflight_artifacts([output_path], force)
        request = {
            "x": x,
            "x_range": x_range,
            "x_points": x_points,
            "y": y,
            "y_range": y_range,
            "y_points": y_points,
            "target": target,
            "preset": preset,
            "overrides": overrides,
            "precision": precision,
            "display_digits": display_digits,
            "timeout_seconds": timeout,
            "out": out,
        }

        def compute_grid() -> dict:
            result = scan_grid(
                Engine(workspace),
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
                timeout,
            )
            if output_path:
                result["out"] = str(write_grid_csv(result, output_path, overwrite=force))
            return result

        result = _recorded_compute(
            workspace,
            save_run_id,
            "grid",
            request,
            compute_grid,
            [preset] if preset else [],
        )
        human = (
            f"Grid: {result['valid_points']}/{result['points']} valid points"
            + (f"\nCSV: {result['out']}" if "out" in result else "")
        )
        _emit(result, json_output, human)

    _execute(action, json_output)


@app.command("plot")
def plot_command(
    x: Optional[str] = typer.Option(None, "--x"),
    range_text: Optional[str] = typer.Option(None, "--range"),
    points: Optional[int] = typer.Option(None, "--points"),
    targets: List[str] = typer.Option([], "--y"),
    preset: Optional[str] = typer.Option(None, "--preset"),
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
        chosen_targets, chosen_preset = list(targets), preset
        chosen_out, chosen_data_out = out, data_out
        title = x_label = y_label = None
        curve_labels = {}
        if config:
            saved = workspace.get_plot(config)
            chosen_x = chosen_x or saved.x
            chosen_range = chosen_range or f"{saved.range_start}:{saved.range_end}"
            chosen_points = chosen_points or saved.points
            chosen_targets = chosen_targets or saved.y
            chosen_preset = chosen_preset or saved.preset
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
            "preset": chosen_preset,
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
        extra_ids = [item for item in (chosen_preset, config) if item]
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
                chosen_preset,
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
