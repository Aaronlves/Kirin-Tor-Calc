"""Immutable run records with embedded definitions and environment-aware replay."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Union

from . import __version__
from .engine import Engine
from .errors import KTError, SchemaError, UnsupportedError, WorkspaceError
from .kirin_syntax import parse_kirin_source
from .limits import MAX_RUN_RECORD_BYTES
from .operations import (
    differentiate,
    evaluate,
    scan_grid,
    scan_values,
    solve_equation,
    solve_system,
    transform,
)
from .plotting import render_plot, write_grid_csv, write_scan_csv
from .timeout import run_with_timeout
from .workspace import Workspace


RUN_FORMAT_VERSION = 2


def run_record_path(workspace_or_root: Union[Workspace, Path], run_id: str) -> Path:
    if not run_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in run_id
    ):
        raise WorkspaceError("run id may contain only ASCII letters, digits, '_' and '-'")
    root = _root_path(workspace_or_root)
    path = (root / "runs" / f"{run_id}.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("runs directory resolves outside the workspace") from exc
    return path


def _canonical_hash(content: dict) -> str:
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def software_versions() -> dict:
    package_root = Path(__file__).resolve().parent
    implementation = hashlib.sha256()
    implementation_files = sorted(package_root.glob("*.py"))
    for path in implementation_files:
        implementation.update(str(path.relative_to(package_root)).encode("utf-8"))
        implementation.update(b"\0")
        implementation.update(path.read_bytes())
        implementation.update(b"\0")
    result = {
        "kirin_tor_cli": __version__,
        "kirin_tor_implementation_sha256": implementation.hexdigest(),
        "python": platform.python_version(),
        "platform": sys.platform,
    }
    for distribution in ("sympy", "typer", "matplotlib"):
        try:
            result[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            result[distribution] = "not-installed"
    return result


def _artifact_metadata(result: dict) -> dict:
    artifacts = {}
    for key in ("out", "data_out"):
        value = result.get(key)
        if value:
            path = Path(value)
            if path.is_file():
                artifacts[key] = {
                    "filename": path.name,
                    "suffix": path.suffix.lower(),
                    "sha256": _file_hash(path),
                    "size": path.stat().st_size,
                }
    return artifacts


def save_run(
    workspace: Workspace,
    run_id: str,
    operation: str,
    request: dict,
    result: dict,
    document_ids: Iterable[str],
) -> Path:
    path = run_record_path(workspace, run_id)
    if path.exists():
        raise WorkspaceError(f"run record already exists and will not be overwritten: {path}")
    semantic_ids = {entry.id for entry in workspace.entries.values() if entry.semantics}
    snapshots = []
    for document_id in sorted(set(document_ids) | semantic_ids):
        if document_id not in workspace.documents:
            raise WorkspaceError(f"cannot snapshot missing document {document_id!r}")
        document = workspace.documents[document_id]
        snapshot = {
            "id": document.id,
            "source_sha256": document.sha256,
            "content_sha256": _canonical_hash(document.raw),
            "source_text": document.raw_text,
            "content": document.raw,
        }
        if document.package_origin is not None:
            snapshot["package"] = {
                "source": document.package_origin.source,
                "name": document.package_origin.name,
                "version": document.package_origin.version,
                "namespace": document.package_origin.namespace,
                "resolved": document.package_origin.resolved,
                "content_sha256": document.package_origin.content_sha256,
            }
        snapshots.append(snapshot)
    record = {
        "run_format_version": RUN_FORMAT_VERSION,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "request": request,
        "definitions": snapshots,
        "software": software_versions(),
        "domain": result.get("conditions", []),
        "assumptions": {
            "symbols": "real unless declared boolean",
            "input_constraints": "embedded in schema-v1 definition snapshots",
        },
        "units": result.get("units", result.get("unit")),
        "precision": request.get("precision"),
        "artifacts": _artifact_metadata(result),
        "result": result,
        "status": result.get("status", "unknown"),
    }
    encoded_record = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if len(encoded_record.encode("utf-8")) > MAX_RUN_RECORD_BYTES:
        raise WorkspaceError(
            f"run record exceeds {MAX_RUN_RECORD_BYTES} bytes; reduce the recorded dependency closure"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(encoded_record, encoding="utf-8")
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise WorkspaceError(f"run record already exists and will not be overwritten: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _root_path(workspace_or_root: Union[Workspace, Path]) -> Path:
    return workspace_or_root.root if isinstance(workspace_or_root, Workspace) else Path(workspace_or_root).resolve()


def load_run(workspace_or_root: Union[Workspace, Path], run_id: str) -> dict:
    path = run_record_path(workspace_or_root, run_id)
    if not path.is_file():
        raise WorkspaceError(f"run record not found: {path}")
    if path.stat().st_size > MAX_RUN_RECORD_BYTES:
        raise WorkspaceError(f"run record exceeds {MAX_RUN_RECORD_BYTES} bytes: {path}")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkspaceError(f"invalid run record {path}: {exc}") from exc
    if record.get("run_format_version") != RUN_FORMAT_VERSION:
        raise UnsupportedError(
            f"run format {record.get('run_format_version')!r} is incompatible with supported format {RUN_FORMAT_VERSION}"
        )
    definitions = record.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        raise SchemaError("run record has no recoverable definition snapshots")
    for snapshot in definitions:
        if _canonical_hash(snapshot.get("content")) != snapshot.get("content_sha256"):
            raise SchemaError(f"embedded definition snapshot {snapshot.get('id')!r} failed its content hash")
        source_text = snapshot.get("source_text")
        if not isinstance(source_text, str):
            raise SchemaError(f"embedded definition snapshot {snapshot.get('id')!r} has no source text")
        if hashlib.sha256(source_text.encode("utf-8")).hexdigest() != snapshot.get("source_sha256"):
            raise SchemaError(f"embedded definition snapshot {snapshot.get('id')!r} failed its source hash")
        try:
            parsed_source, _positions = parse_kirin_source(
                source_text, Path(f"{snapshot.get('id', 'unknown')}.kirin")
            )
        except SchemaError as exc:
            raise SchemaError(
                f"embedded definition snapshot {snapshot.get('id')!r} has invalid source text"
            ) from exc
        if parsed_source != snapshot.get("content"):
            raise SchemaError(
                f"embedded definition snapshot {snapshot.get('id')!r} source and structured content disagree"
            )
        if snapshot.get("id") != snapshot.get("content", {}).get("id"):
            raise SchemaError(
                f"embedded definition snapshot {snapshot.get('id')!r} has an inconsistent id"
            )
    return record


def _execute_record(record: dict, workspace: Workspace) -> dict:
    engine = Engine(workspace)
    request = record["request"]
    operation = record["operation"]
    has_effective = "effective_parameters" in request
    parameters = request.get("effective_parameters", request.get("overrides", {}))
    preset = None if has_effective else request.get("preset")
    if operation == "eval":
        return evaluate(
            engine,
            request["target"],
            preset=preset,
            overrides=parameters,
            precision=request["precision"],
            display_digits=request["display_digits"],
            timeout_seconds=request["timeout_seconds"],
        )
    if operation == "compare":
        from .application import ComparisonVariant, compare_variants

        variants = [
            ComparisonVariant(
                item["name"],
                item.get("preset"),
                item.get("overrides", {}),
            )
            for item in request["variants"]
        ]
        return compare_variants(
            workspace,
            request["target"],
            variants,
            precision=request["precision"],
            display_digits=request["display_digits"],
            timeout_seconds=request["timeout_seconds"],
        )
    if operation in {"simplify", "expand", "factor"}:
        return transform(
            engine,
            operation,
            request["target"],
            preset=preset,
            overrides=parameters,
            keep=request.get("keep", []),
            timeout_seconds=request["timeout_seconds"],
        )
    if operation == "diff":
        return differentiate(
            engine,
            request["target"],
            request["variable"],
            preset=preset,
            overrides=parameters,
            timeout_seconds=request["timeout_seconds"],
        )
    if operation == "solve":
        return solve_equation(
            engine,
            request["target"],
            request["variable"],
            request["equals"],
            request.get("range"),
            preset=preset,
            overrides=parameters,
            precision=request["precision"],
            timeout_seconds=request["timeout_seconds"],
        )
    if operation == "solve_system":
        return solve_system(
            engine,
            [
                (item["target"], item["equals"])
                for item in request["equations"]
            ],
            request["variables"],
            preset=preset,
            overrides=parameters,
            precision=request["precision"],
            timeout_seconds=request["timeout_seconds"],
        )
    if operation == "grid":
        return scan_grid(
            engine,
            request["x"],
            request["x_range"],
            request["x_points"],
            request["y"],
            request["y_range"],
            request["y_points"],
            request["target"],
            preset=preset,
            overrides=parameters,
            precision=request["precision"],
            display_digits=request["display_digits"],
            timeout_seconds=request["timeout_seconds"],
        )
    if operation in {"scan", "plot"}:
        replayed = scan_values(
            engine,
            request["x"],
            request["range"],
            request["points"],
            request["targets"],
            preset=preset,
            overrides=parameters,
            precision=request["precision"],
            display_digits=request["display_digits"],
            timeout_seconds=request["timeout_seconds"],
        )
        if operation == "plot":
            replayed["operation"] = "plot"
        return replayed
    raise UnsupportedError(f"replay does not support recorded operation {operation!r}")


def _comparable(result: dict) -> dict:
    comparable = dict(result)
    for transient in ("out", "data_out", "run_record"):
        comparable.pop(transient, None)
    if comparable.get("status") == "error":
        comparable.pop("location", None)
    return comparable


def replay(
    workspace_or_root: Union[Workspace, Path],
    run_id: str,
    regenerate_artifacts: bool = False,
    out: Optional[Path] = None,
    data_out: Optional[Path] = None,
    force: bool = False,
) -> dict:
    root = _root_path(workspace_or_root)
    Workspace._validate_marker(root)
    record = load_run(root, run_id)
    snapshot_workspace = Workspace.from_snapshots(record["definitions"])
    try:
        replayed = _execute_record(record, snapshot_workspace)
    except KTError as exc:
        replayed = exc.as_dict()
    except Exception as exc:
        replayed = {"status": "error", "code": "internal_operation_error", "message": str(exc)}

    regenerated = {}
    if regenerate_artifacts:
        if record["operation"] == "grid" and replayed.get("status") == "ok":
            csv_path = out or data_out or (root / "results" / f"replay-{run_id}.csv")
            regenerated["out"] = str(
                write_grid_csv(replayed, Path(csv_path), overwrite=force)
            )
            regenerated["hashes"] = _artifact_metadata(regenerated)
        elif record["operation"] != "plot" or replayed.get("status") != "ok":
            raise UnsupportedError(
                "artifact regeneration requires a successful recorded plot or grid operation"
            )
        else:
            suffix = record.get("artifacts", {}).get("out", {}).get("suffix", ".svg")
            plot_path = out or (root / "results" / f"replay-{run_id}{suffix}")
            request = record["request"]
            regenerated["out"] = str(
                run_with_timeout(
                    render_plot,
                    (
                        replayed,
                        Path(plot_path),
                        force,
                        request.get("title"),
                        request.get("x_label"),
                        request.get("y_label"),
                        request.get("curve_labels", {}),
                    ),
                    request["timeout_seconds"],
                )
            )
            if data_out is not None or "data_out" in record.get("artifacts", {}):
                csv_path = data_out or (root / "results" / f"replay-{run_id}.csv")
                regenerated["data_out"] = str(
                    write_scan_csv(replayed, Path(csv_path), overwrite=force)
                )
            regenerated["hashes"] = _artifact_metadata(regenerated)

    current_software = software_versions()
    recorded_software = record.get("software", {})
    drift = {
        name: {"recorded": recorded_software.get(name), "current": current_software.get(name)}
        for name in sorted(set(recorded_software) | set(current_software))
        if recorded_software.get(name) != current_software.get(name)
    }
    matches = _comparable(replayed) == _comparable(record["result"])
    return {
        "status": "ok",
        "operation": "replay",
        "run_id": run_id,
        "original_operation": record["operation"],
        "used_embedded_definitions": True,
        "definition_ids": [snapshot["id"] for snapshot in record["definitions"]],
        "environment_match": not drift,
        "version_drift": drift,
        "reproducibility": "exact_environment" if not drift else "version_drift_result_compared",
        "matches_recorded_result": matches,
        "recorded_result": record["result"],
        "replayed_result": replayed,
        "regenerated_artifacts": regenerated,
    }
