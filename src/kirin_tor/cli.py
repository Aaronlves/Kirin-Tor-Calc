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
from .errors import KTError, ParameterError, WorkspaceError
from .limits import DEFAULT_TIMEOUT_SECONDS
from .operations import (
    analyze_process,
    process_analysis_request,
    differentiate,
    evaluate,
    explain,
    scan_grid,
    scan_values,
    solve_equation,
    solve_system,
    transform,
)
from .package_authoring import (
    add_package,
    add_path_package,
    check_package,
    create_package_template,
    remove_package,
    restore_packages,
    update_package,
    verify_packages,
)
from .package_store import PackageResolver, PackageStoreManager
from .plotting import render_plot, write_grid_csv, write_scan_csv
from .process_chart import render_process_chart_svg, write_process_chart_csv
from .plugin_store import PluginManager
from .plugin_authoring import (
    bundle_plugin,
    check_plugin,
    create_plugin_template,
    test_plugin,
)
from .records import replay as replay_run
from .timeout import run_with_timeout
from .workbench_preferences import load_default_workspace, save_default_workspace
from .workspace import (
    Workspace,
    create_entry_template,
    initialize,
)


app = typer.Typer(
    name="kt",
    help="Kirin Tor: game-neutral, file-driven structured mathematics for theorycrafting.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
new_app = typer.Typer(help="Create a document from a minimal Kirin Tor v2 template.")
app.add_typer(new_app, name="new")
package_app = typer.Typer(help="Install, verify, and author data-only community packages.")
app.add_typer(package_app, name="package")
plugin_app = typer.Typer(help="Install and manage sandboxed Workbench Extension Plugins.")
app.add_typer(plugin_app, name="plugin")


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


def _remember_web_workspace(root: Path) -> None:
    try:
        save_default_workspace(root)
    except WorkspaceError as exc:
        typer.echo(f"Warning: {exc}", err=True)


def _saved_web_workspace() -> Optional[Path]:
    try:
        root = load_default_workspace()
    except WorkspaceError as exc:
        typer.echo(f"Warning: {exc}", err=True)
        return None
    if root is None:
        return None
    if root.is_dir() and (root / "kirin.workspace").is_file():
        return root
    typer.echo(f"Warning: saved Kirin Tor workspace is unavailable: {root}", err=True)
    return None


def _choose_web_workspace() -> Optional[Path]:
    try:
        selected = typer.prompt("Kirin Tor workspace folder", default=str(Path.cwd()))
    except typer.Abort:
        typer.echo("Workspace selection cancelled.")
        return None
    candidate = Path(selected).expanduser().resolve()
    if candidate.exists() and not candidate.is_dir():
        raise WorkspaceError(f"web workspace must be a directory: {candidate}")
    try:
        return Workspace.find_root(candidate)
    except WorkspaceError:
        pass
    try:
        should_initialize = typer.confirm(
            f"No Kirin Tor workspace found. Initialize one at {candidate}?",
            default=False,
        )
    except typer.Abort:
        should_initialize = False
    if not should_initialize:
        typer.echo("Workspace selection cancelled.")
        return None
    root = initialize(candidate)
    typer.echo(f"Initialized game-neutral Kirin Tor workspace: {root}")
    return root


@app.command("version")
def version_command() -> None:
    """Print the installed Kirin Tor CLI version."""
    typer.echo(__version__)


@app.command("mcp")
def mcp_command(
    workspace: Optional[Path] = typer.Argument(
        None,
        help="Workspace directory or path inside one; defaults to the current directory.",
    ),
) -> None:
    """Serve one Kirin Tor workspace as a thin MCP server over stdio."""

    def action():
        requested = (workspace or Path.cwd()).expanduser().resolve()
        if not requested.exists():
            raise WorkspaceError(f"MCP workspace path does not exist: {requested}")
        start = requested.parent if requested.is_file() else requested
        root = requested if (requested / "kirin.workspace").is_file() else Workspace.find_root(start)
        from .mcp_server import run_mcp_server

        run_mcp_server(root)

    _execute(action)


@app.command("web")
def web_command(
    source: Optional[Path] = typer.Argument(
        None,
        help=(
            "Workspace directory or Kirin Tor source path; otherwise uses the current "
            "or saved workspace."
        ),
    ),
    port: int = typer.Option(0, "--port", help="Loopback port; 0 selects an available port."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open the default browser."),
    choose: bool = typer.Option(
        False,
        "--choose",
        help="Choose and remember a workspace, ignoring the current and saved workspace.",
    ),
    safe_mode: bool = typer.Option(
        False,
        "--safe-mode",
        help="Start without activating or serving any third-party Workbench Plugins.",
    ),
) -> None:
    """Start the local browser workbench and open it in the default browser."""
    def action():
        if source is not None and choose:
            raise WorkspaceError("web SOURCE and --choose cannot be used together")
        requested = source.expanduser().resolve() if source is not None else None
        initial_document = None
        if requested is not None and requested.is_dir():
            root = (
                requested
                if (requested / "kirin.workspace").is_file()
                else Workspace.find_root(requested)
            )
        elif requested is not None:
            if not requested.is_file() or requested.suffix.lower() != ".kirin":
                raise WorkspaceError(f"web source must be an existing .kirin file: {requested}")
            root = Workspace.find_root(requested.parent)
            try:
                relative = requested.relative_to(root)
            except ValueError as exc:
                raise WorkspaceError("web source must stay inside its workspace") from exc
            if not relative.parts or relative.parts[0] != "entries":
                raise WorkspaceError("web source must be inside entries/")
            initial_document = requested
        elif choose:
            root = _choose_web_workspace()
            if root is None:
                return
        else:
            try:
                root = Workspace.find_root()
            except WorkspaceError:
                root = _saved_web_workspace()
                if root is None:
                    root = _choose_web_workspace()
                    if root is None:
                        return
        _remember_web_workspace(root)
        from .web import run_web
        run_web(
            root,
            port=port,
            open_browser=not no_open,
            initial_document=initial_document,
            safe_mode=safe_mode,
        )

    _execute(action)


@plugin_app.command("new")
def plugin_new_command(
    directory: Path,
    plugin_id: str = typer.Option(..., "--id", help="Stable dotted lower-case Plugin ID."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a minimal SDK-backed Plugin without running external tools."""

    def action():
        result = create_plugin_template(directory, plugin_id)
        _emit(result, json_output, f"Created Plugin {result['id']} at {result['root']}")

    _execute(action, json_output)


@plugin_app.command("check")
def plugin_check_command(
    directory: Path = typer.Argument(Path(".")),
    workspace: Optional[Path] = typer.Option(None, "--workspace"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Validate one Plugin, its static content, permissions, and optional interfaces."""

    def action():
        result = check_plugin(directory, workspace)
        _emit(
            result,
            json_output,
            f"OK: {result['id']}@{result['version']}; {result['files']} static files; {result['content_sha256']}",
        )

    _execute(action, json_output)


@plugin_app.command("test")
def plugin_test_command(
    directory: Path = typer.Argument(Path(".")),
    workspace: Path = typer.Option(..., "--workspace"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run offline protocol fixtures in a disposable copy of a workspace."""

    def action():
        result = test_plugin(directory, workspace)
        _emit(
            result,
            json_output,
            f"PASS: {len(result['tests'])} offline Plugin protocol fixtures",
        )

    _execute(action, json_output)


@plugin_app.command("bundle")
def plugin_bundle_command(
    directory: Path = typer.Argument(Path(".")),
    output: Optional[Path] = typer.Option(None, "--out"),
    force: bool = typer.Option(False, "--force"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Build a deterministic static Plugin archive without executing scripts."""

    def action():
        result = bundle_plugin(directory, output, force=force)
        _emit(
            result,
            json_output,
            f"Bundled {result['id']} to {result['bundle']} ({result['bundle_sha256']})",
        )

    _execute(action, json_output)


@plugin_app.command("add-path")
def plugin_add_path_command(
    alias: str,
    path: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Install, lock, approve, and enable one local plugin directory snapshot."""
    def action():
        result = PluginManager(Workspace.find_root()).add_path(alias, path)
        selected = next(item for item in result["plugins"] if item["alias"] == alias)
        _emit(
            result,
            json_output,
            f"Installed {alias}: {selected['id']}@{selected['version']} ({selected['status']})",
        )

    _execute(action, json_output)


@plugin_app.command("update-path")
def plugin_update_path_command(
    alias: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Accept, lock, and approve the current content of a local plugin source."""
    def action():
        result = PluginManager(Workspace.find_root()).update_path(alias)
        selected = next(item for item in result["plugins"] if item["alias"] == alias)
        _emit(
            result,
            json_output,
            f"Updated {alias}: {selected['id']}@{selected['version']} ({selected['status']})",
        )

    _execute(action, json_output)


@plugin_app.command("enable")
def plugin_enable_command(
    alias: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Enable one installed and locally approved plugin."""
    def action():
        result = PluginManager(Workspace.find_root()).set_enabled(alias, True)
        _emit(result, json_output, f"Enabled plugin {alias}")

    _execute(action, json_output)


@plugin_app.command("disable")
def plugin_disable_command(
    alias: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Disable one plugin without deleting its immutable cached snapshot."""
    def action():
        result = PluginManager(Workspace.find_root()).set_enabled(alias, False)
        _emit(result, json_output, f"Disabled plugin {alias}")

    _execute(action, json_output)


@plugin_app.command("remove")
def plugin_remove_command(
    alias: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove one workspace plugin request and lock entry."""
    def action():
        result = PluginManager(Workspace.find_root()).remove(alias)
        _emit(result, json_output, f"Removed plugin {alias}")

    _execute(action, json_output)


@plugin_app.command("verify")
def plugin_verify_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Verify plugin requirements, locks, manifests, and cached content offline."""
    def action():
        result = PluginManager(Workspace.find_root()).verify()
        _emit(result, json_output, f"Verified {len(result['plugins'])} plugin(s)")

    _execute(action, json_output)


@plugin_app.command("list")
def plugin_list_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List requested plugins and their independent activation states."""
    def action():
        result = PluginManager(Workspace.find_root()).summary()
        lines = [
            f"{item['alias']:<16} {item['id'] or 'unknown'}@{item['version'] or '?'}  {item['status']}"
            for item in result["plugins"]
        ]
        _emit(result, json_output, "\n".join(lines) if lines else "No Workbench Plugins installed")

    _execute(action, json_output)


@app.command("init")
def init_command(
    directory: Path,
) -> None:
    """Create a new game-neutral workspace directory."""
    def action():
        root = initialize(directory)
        typer.echo(f"Initialized game-neutral Kirin Tor workspace: {root}")

    _execute(action)


def _package_summary(resolution) -> dict:
    direct_aliases = {
        item.source: item.alias for item in resolution.requirements.packages
    }
    return {
        "status": "ok",
        "packages": [
            {
                "alias": direct_aliases.get(item.source),
                "direct": item.source in direct_aliases,
                "source": item.source,
                "name": item.manifest.name,
                "version": item.manifest.version,
                "namespace": item.manifest.namespace,
                "description": item.manifest.description,
                "license": item.manifest.license,
                "game": item.manifest.game,
                "game_version": item.manifest.game_version,
                "resolved": item.resolved,
                "content_sha256": item.content_sha256,
                "dependencies": {
                    dependency.alias: {
                        "source": dependency.source,
                        "version": dependency.version,
                    }
                    for dependency in item.manifest.dependencies
                },
            }
            for item in sorted(resolution.packages, key=lambda package: package.source)
        ],
    }


def _document_origin(document, workspace: Workspace) -> tuple[str, Optional[dict]]:
    origin = document.package_origin
    if origin is None:
        return str(document.path.relative_to(workspace.root)), None
    package_root = workspace.root / ".kirin" / "packages" / origin.content_sha256
    try:
        relative = document.path.relative_to(package_root)
    except ValueError:
        relative = Path(document.path.name)
    return (
        f"{origin.name}@{origin.version}/{relative.as_posix()}",
        {
            "source": origin.source,
            "name": origin.name,
            "version": origin.version,
            "namespace": origin.namespace,
            "resolved": origin.resolved,
            "content_sha256": origin.content_sha256,
        },
    )
@package_app.command("add")
def package_add_command(
    alias: str,
    source: str,
    version: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add one exact GitHub release as a direct workspace dependency."""
    def action():
        result = _package_summary(add_package(Workspace.find_root(), alias, source, version))
        _emit(result, json_output, f"Added {alias}: {source}@{version}")

    _execute(action, json_output)


@package_app.command("add-path")
def package_add_path_command(
    alias: str,
    path: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Add an immutable snapshot of a local package development directory."""
    def action():
        resolution = add_path_package(Workspace.find_root(), alias, path)
        source = resolution.requirements.by_alias()[alias].source
        item = resolution.by_source()[source]
        result = _package_summary(resolution)
        _emit(result, json_output, f"Added {alias}: {item.manifest.name}@{item.manifest.version}")

    _execute(action, json_output)


@package_app.command("remove")
def package_remove_command(
    alias: str,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Remove one direct dependency and unreachable transitive packages."""
    def action():
        result = _package_summary(remove_package(Workspace.find_root(), alias))
        _emit(result, json_output, f"Removed package {alias}")

    _execute(action, json_output)


@package_app.command("update")
def package_update_command(
    alias: str,
    version: Optional[str] = typer.Argument(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Re-resolve one direct package, optionally at a new exact version."""
    def action():
        resolution = update_package(Workspace.find_root(), alias, version)
        result = _package_summary(resolution)
        selected = resolution.requirements.by_alias()[alias]
        _emit(result, json_output, f"Updated {alias} to {selected.version}")

    _execute(action, json_output)


@package_app.command("restore")
def package_restore_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Resolve declared releases, rebuild missing cache content, and replace the lockfile."""
    def action():
        resolution = restore_packages(Workspace.find_root())
        result = _package_summary(resolution)
        _emit(result, json_output, f"Restored {len(resolution.packages)} package(s)")

    _execute(action, json_output)


@package_app.command("verify")
def package_verify_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Verify the locked graph and cached content without network access."""
    def action():
        resolution, validation = verify_packages(Workspace.find_root())
        result = _package_summary(resolution)
        result["validation"] = validation
        _emit(result, json_output, f"Verified {len(resolution.packages)} package(s)")

    _execute(action, json_output)


@package_app.command("list")
def package_list_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List direct and transitive packages from the verified offline lock."""
    def action():
        root = Workspace.find_root()
        resolution = PackageResolver(PackageStoreManager(root)).load_locked_workspace()
        result = _package_summary(resolution)
        lines = []
        for item in result["packages"]:
            role = item["alias"] if item["direct"] else "transitive"
            lines.append(
                f"{role:<16} {item['name']}@{item['version']}  {item['source']}"
            )
        _emit(result, json_output, "\n".join(lines) if lines else "No community packages installed")

    _execute(action, json_output)


@package_app.command("new")
def package_new_command(
    directory: Path,
    name: str = typer.Option(..., "--name"),
    namespace: str = typer.Option(..., "--namespace"),
    version: str = typer.Option("1.0.0", "--version"),
) -> None:
    """Create a data-only community package repository template."""
    def action():
        root = create_package_template(
            directory, name=name, namespace=namespace, version=version
        )
        typer.echo(f"Created Kirin Tor community package: {root}")

    _execute(action)


@package_app.command("check")
def package_check_command(
    directory: Path = typer.Argument(Path(".")),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Validate a package manifest, dependencies, namespace, and all Kirin Tor mathematics."""
    def action():
        resolution, validation = check_package(directory)
        subject = next(
            item for item in resolution.packages if item.source == resolution.requirements.packages[0].source
        )
        result = _package_summary(resolution)
        result["validation"] = validation
        _emit(
            result,
            json_output,
            f"OK: {subject.manifest.name}@{subject.manifest.version}; "
            f"{validation['documents']} document(s)",
        )

    _execute(action, json_output)


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


@app.command("list")
def list_command(json_output: bool = typer.Option(False, "--json", help="Write JSON to stdout.")) -> None:
    """List loaded documents by stable id."""
    def action():
        workspace = Workspace.discover()
        items = []
        for document in sorted(workspace.documents.values(), key=lambda item: item.id):
            path, origin = _document_origin(document, workspace)
            items.append({
                "id": document.id,
                "authority_id": document.authority_id,
                "name": document.name,
                "type": document.type,
                "path": path,
                "read_only": document.read_only,
                "package_origin": origin,
            })
        _emit(
            {"status": "ok", "documents": items},
            json_output,
            "\n".join(
                f"{item['id']:<20} {item['type']:<10} {item['name']}"
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
        _path, origin = _document_origin(document, workspace)
        _emit(
            {
                "status": "ok",
                "document": document.raw,
                "authority_id": document.authority_id,
                "read_only": document.read_only,
                "package_origin": origin,
            },
            json_output,
            document.raw_text.rstrip(),
        )

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


@app.command("analyze")
def process_analysis_command(
    target: str,
    case_id: Optional[str] = typer.Option(None, "--case", help="Replay one declared sweep case with its trajectory."),
    no_trace: bool = typer.Option(False, "--no-trace", help="Omit event trace details."),
    timeout: float = typer.Option(DEFAULT_TIMEOUT_SECONDS, "--timeout"),
    save_run_id: Optional[str] = typer.Option(None, "--save-run"),
    export_charts: bool = typer.Option(
        False, "--export-charts", help="Export every configured Process chart."
    ),
    force: bool = typer.Option(False, "--force"),
    allow_outside: bool = typer.Option(False, "--allow-outside-workspace"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Execute a source-declared Process analysis as ENTRY.ANALYSIS."""

    def action():
        workspace = Workspace.discover()
        request = process_analysis_request(
            workspace,
            target,
            include_trace=not no_trace,
            timeout_seconds=timeout,
            case_id=case_id,
        )
        result = _recorded_compute(
            workspace,
            save_run_id,
            "process_analysis",
            request,
            lambda: analyze_process(
                workspace,
                target,
                include_trace=not no_trace,
                timeout_seconds=timeout,
                case_id=case_id,
            ),
        )
        if export_charts:
            charts = result.get("charts", [])
            configured = [
                (chart, chart.get("export_svg"), chart.get("export_csv"))
                for chart in charts
                if chart.get("export_svg") or chart.get("export_csv")
            ]
            if not configured:
                raise ParameterError(
                    "analysis has no chart export_svg or export_csv paths"
                )
            paths = [
                _artifact_path(workspace, value, allow_outside)
                for _chart, svg, csv_path in configured
                for value in (svg, csv_path)
                if value is not None
            ]
            _preflight_artifacts(paths, force)
            for chart, svg, csv_path in configured:
                artifacts = {}
                if svg is not None:
                    artifacts["svg"] = str(
                        render_process_chart_svg(
                            chart,
                            _artifact_path(workspace, svg, allow_outside),
                            overwrite=force,
                        )
                    )
                if csv_path is not None:
                    artifacts["csv"] = str(
                        write_process_chart_csv(
                            chart,
                            _artifact_path(workspace, csv_path, allow_outside),
                            overwrite=force,
                        )
                    )
                chart["artifacts"] = artifacts
        operation = result["analysis_operation"]
        if operation == "optimize":
            variants = result["variants"]
            proof_levels = sorted(
                {
                    objective["proof"]["level"]
                    for variant in variants
                    for objective in variant["objectives"]
                }
            )
            summary = (
                f"已分别优化 {len(variants)} 个方案；"
                f"证明等级 {','.join(proof_levels)}；"
                f"搜索分支 {result['explored_branches']}"
            )
        elif operation == "reach":
            summary = f"可达概率：{result['probability']}"
        elif operation == "steady":
            summary = f"稳态：{len(result['states'])} 个有限状态"
        elif operation == "cycle":
            summary = (
                f"周期已证明：前段 {result['preperiod']}，周期 {result['period']}"
            )
        elif operation == "compare":
            summary = f"已比较 {len(result['policies'])} 个策略"
        elif operation == "sweep":
            summary = (f"已计算 {result['completed_cases']}/{result['planned_cases']} 个声明候选；"
                       f"失败 {result['failed_cases']}；排名仅覆盖声明的策略与网格")
        else:
            outcome_states = len(result["outcomes"])
            source_paths = result.get("source_path_count", outcome_states)
            summary = f"运行完成：{outcome_states} 个精确结果状态"
            if source_paths != outcome_states:
                summary += f"（由 {source_paths} 条原始路径精确合并）"
        _emit(result, json_output, summary)

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
    config: Optional[str] = typer.Option(None, "--config", help="Saved plot config ID (ENTRY.CHART)."),
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
            saved = workspace.get_chart(config)
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
        extra_ids = [item for item in (chosen_preset, saved.owner_id if config else None) if item]
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
