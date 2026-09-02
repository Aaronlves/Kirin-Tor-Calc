"""Shared workspace workbench services used by the browser adapter."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence

from . import __version__
from .application import (
    ComparisonVariant,
    artifact_path,
    atomic_write_sources,
    build_workspace_index,
    compare_variants,
    parse_player_override_text,
    preflight_artifacts,
    record_operation,
    scan_variant_comparison,
)
from .authoring import (
    AuthoringSource,
    build_authoring_index,
    build_completion_candidates,
    format_kirin_source,
    rename_authoring_symbol,
)
from .community_discovery import discover_community
from .diagnostics import author_error_payload, extract_author_title
from .engine import Engine
from .errors import KTError, ParameterError, ReferenceError, SourceLocation, ValidationErrors, WorkspaceError
from .limits import DEFAULT_TIMEOUT_SECONDS
from .operations import (
    analyze_cycle,
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
from .package_manifest import package_source_paths
from .package_store import PackageResolver, PackageStoreManager, locked_workspace_resolution
from .plotting import render_plot, write_grid_csv, write_scan_csv
from .plugin_store import PluginManager
from .records import load_run, replay as replay_run
from .relationship_graph import build_relationship_graph
from .templates import (
    build_from_template,
    list_templates,
    remove_workspace_template,
    save_workspace_template,
)
from .timeout import run_with_timeout
from .tutorials import list_tutorials
from .workspace import Workspace, initialize


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_workspace(workspace: Workspace) -> dict:
    return Engine(workspace).validate_all()


def _plain_replace(text: str, query: str, replacement: str, case_sensitive: bool) -> tuple[str, int]:
    if case_sensitive:
        return text.replace(query, replacement), text.count(query)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return pattern.subn(lambda _match: replacement, text)


def _source_offset(text: str, line: int, column: int) -> int:
    lines = text.splitlines(keepends=True)
    if line < 1 or line > len(lines):
        raise WorkspaceError("authoring location is outside the duplicated source")
    return sum(len(item) for item in lines[:line - 1]) + max(0, column - 1)


def _three_way_merge(base: str, draft: str, disk: str) -> dict:
    if draft == disk:
        return {"text": draft, "clean": True, "conflicts": 0}
    if draft == base:
        return {"text": disk, "clean": True, "conflicts": 0}
    if disk == base:
        return {"text": draft, "clean": True, "conflicts": 0}

    base_lines = base.splitlines(keepends=True)

    def edits(other: str) -> list[tuple[int, int, list[str]]]:
        other_lines = other.splitlines(keepends=True)
        matcher = difflib.SequenceMatcher(a=base_lines, b=other_lines, autojunk=False)
        return [
            (i1, i2, other_lines[j1:j2])
            for tag, i1, i2, j1, j2 in matcher.get_opcodes()
            if tag != "equal"
        ]

    draft_edits = edits(draft)
    disk_edits = edits(disk)

    def overlaps(left: tuple[int, int, list[str]], right: tuple[int, int, list[str]]) -> bool:
        left_start, left_end, _ = left
        right_start, right_end, _ = right
        if left_start == left_end and right_start == right_end:
            return left_start == right_start
        if left_start == left_end:
            return right_start <= left_start < right_end
        if right_start == right_end:
            return left_start <= right_start < left_end
        return max(left_start, right_start) < min(left_end, right_end)

    conflicts = 0
    for draft_edit in draft_edits:
        for disk_edit in disk_edits:
            if draft_edit == disk_edit:
                continue
            if overlaps(draft_edit, disk_edit):
                conflicts += 1
    if conflicts:
        merged = (
            "<<<<<<< WORKBENCH DRAFT\n"
            + draft.rstrip("\n")
            + "\n=======\n"
            + disk.rstrip("\n")
            + "\n>>>>>>> DISK VERSION\n"
        )
        return {"text": merged, "clean": False, "conflicts": conflicts}

    combined: list[tuple[int, int, list[str]]] = list(draft_edits)
    for edit in disk_edits:
        if edit not in combined:
            combined.append(edit)
    merged_lines = list(base_lines)
    for start, end, replacement in sorted(combined, key=lambda item: (item[0], item[1]), reverse=True):
        merged_lines[start:end] = replacement
    return {"text": "".join(merged_lines), "clean": True, "conflicts": 0}


def package_summary(resolution) -> dict:
    direct_aliases = {item.source: item.alias for item in resolution.requirements.packages}
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


def _split_values(value, separators: str = ",;\n") -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value)
    for separator in separators[1:]:
        text = text.replace(separator, separators[0])
    return [item.strip() for item in text.split(separators[0]) if item.strip()]


def _number(payload: Mapping[str, object], key: str, default, cast):
    value = payload.get(key, default)
    try:
        return cast(value)
    except (TypeError, ValueError) as exc:
        raise ParameterError(f"{key} must be a {cast.__name__}") from exc


class Workbench:
    """Stateful, serialized adapter for one local workspace."""

    def __init__(
        self,
        root: Path,
        *,
        safe_mode: bool = False,
        plugin_approval_home: Optional[Path] = None,
    ):
        self.root = root.expanduser().resolve()
        Workspace._validate_marker(self.root)
        self._lock = threading.RLock()
        self.plugins = PluginManager(
            self.root,
            safe_mode=safe_mode,
            approval_home=plugin_approval_home,
        )

    def _local_path(self, relative: str, *, new: bool = False) -> Path:
        path = (self.root / relative).resolve()
        try:
            rel = path.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("document path must stay inside the workspace") from exc
        if path.suffix.lower() != ".kirin" or not rel.parts or rel.parts[0] != "entries":
            raise WorkspaceError("document path must be a .kirin file inside entries/")
        if not new and not path.is_file():
            raise WorkspaceError(f"document not found: {relative}")
        return path

    def _overlays(self, raw: Optional[Mapping[str, object]]) -> Dict[Path, str]:
        result: Dict[Path, str] = {}
        for relative, value in (raw or {}).items():
            if not isinstance(relative, str) or not isinstance(value, str):
                raise ParameterError("overlays must map relative document paths to source text")
            result[self._local_path(relative, new=True)] = value
        return result

    def workspace(self, overlays: Optional[Mapping[str, object]] = None) -> Workspace:
        parsed = self._overlays(overlays)
        return Workspace.load_with_overlays(self.root, parsed) if parsed else Workspace.load(self.root)

    def _document_catalog(self) -> list[dict]:
        items = []
        for folder in ("entries",):
            for path in sorted((self.root / folder).rglob("*.kirin")):
                if not path.is_file():
                    continue
                source = path.read_text(encoding="utf-8")
                items.append(
                    {
                        "key": path.relative_to(self.root).as_posix(),
                        "path": path.relative_to(self.root).as_posix(),
                        "title": extract_author_title(source, path.stem),
                        "kind": "entry",
                        "read_only": False,
                        "source_sha256": _hash_text(source),
                    }
                )
        resolution = locked_workspace_resolution(self.root)
        for package in resolution.packages:
            for path in package_source_paths(package.root):
                relative = path.relative_to(package.root).as_posix()
                source = path.read_text(encoding="utf-8")
                items.append(
                    {
                        "key": f"package:{package.content_sha256}:{relative}",
                        "path": relative,
                        "title": extract_author_title(source, path.stem),
                        "kind": path.parts[-2][:-1] if len(path.parts) > 1 else "entry",
                        "read_only": True,
                        "source_sha256": _hash_text(source),
                        "package": {
                            "name": package.manifest.name,
                            "version": package.manifest.version,
                            "source": package.source,
                            "content_sha256": package.content_sha256,
                        },
                    }
                )
        return items

    @property
    def _recovery_path(self) -> Path:
        return self.root / ".kirin" / "workbench-recovery.json"

    def _read_recovery(self) -> dict:
        path = self._recovery_path
        if not path.is_file():
            return {"version": 1, "drafts": {}}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": 1, "drafts": {}}
        drafts = payload.get("drafts") if isinstance(payload, dict) else None
        if not isinstance(drafts, dict):
            return {"version": 1, "drafts": {}}
        normalized: dict[str, dict] = {}
        total_size = 0
        for key, raw in drafts.items():
            if not isinstance(key, str) or not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                continue
            try:
                self._local_path(key, new=True)
            except KTError:
                continue
            total_size += len(raw["text"].encode("utf-8"))
            if total_size > 5 * 1024 * 1024 or len(normalized) >= 100:
                break
            document = raw.get("document") if isinstance(raw.get("document"), dict) else {}
            normalized[key] = {
                "text": raw["text"],
                "base_sha256": raw.get("base_sha256") if isinstance(raw.get("base_sha256"), str) else None,
                "document": {
                    "key": key,
                    "path": key,
                    "title": str(document.get("title") or Path(key).stem),
                    "kind": str(document.get("kind") or "entry"),
                    "read_only": False,
                    "source_sha256": None,
                },
            }
        return {"version": 1, "drafts": normalized}

    def save_recovery(self, drafts: object) -> dict:
        with self._lock:
            return self._save_recovery(drafts)

    def _save_recovery(self, drafts: object) -> dict:
        if not isinstance(drafts, dict):
            raise ParameterError("recovery drafts must be an object")
        normalized: dict[str, dict] = {}
        total_size = 0
        for key, raw in drafts.items():
            if not isinstance(key, str) or not isinstance(raw, dict):
                raise ParameterError("invalid recovery draft")
            self._local_path(key, new=True)
            text = raw.get("text")
            if not isinstance(text, str):
                raise ParameterError("recovery draft text must be a string")
            total_size += len(text.encode("utf-8"))
            if total_size > 5 * 1024 * 1024 or len(normalized) >= 100:
                raise ParameterError("recovery drafts exceed the workbench safety limit")
            document = raw.get("document") if isinstance(raw.get("document"), dict) else {}
            normalized[key] = {
                "text": text,
                "base_sha256": raw.get("base_sha256") if isinstance(raw.get("base_sha256"), str) else None,
                "document": {
                    "key": key,
                    "path": key,
                    "title": str(document.get("title") or Path(key).stem),
                    "kind": str(document.get("kind") or "entry"),
                    "read_only": False,
                    "source_sha256": None,
                },
            }
        path = self._recovery_path
        if not normalized:
            path.unlink(missing_ok=True)
            return {"status": "ok", "drafts": 0}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump({"version": 1, "drafts": normalized}, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"status": "ok", "drafts": len(normalized)}

    def _authoring_sources(
        self,
        overlays: Optional[Mapping[Path, str]] = None,
    ) -> list[AuthoringSource]:
        parsed = dict(overlays or {})
        items: list[AuthoringSource] = []
        seen: set[Path] = set()
        for item in self._document_catalog():
            if item["read_only"]:
                digest = item["package"]["content_sha256"]
                actual = self.root / ".kirin" / "packages" / digest / item["path"]
            else:
                actual = self._local_path(item["path"])
            seen.add(actual.resolve())
            items.append(
                AuthoringSource(
                    key=item["key"],
                    path=item["path"],
                    text=parsed.get(actual.resolve(), actual.read_text(encoding="utf-8")),
                    read_only=bool(item["read_only"]),
                )
            )
        for actual, text in sorted(parsed.items()):
            if actual.resolve() in seen:
                continue
            relative = actual.relative_to(self.root).as_posix()
            items.append(AuthoringSource(relative, relative, text, False))
        return items

    def bootstrap(self, overlays: Optional[Mapping[str, object]] = None) -> dict:
        with self._lock:
            documents = self._document_catalog()
            validation = self.validate(overlays)
            index = validation.get(
                "index",
                {"targets": [], "inputs": [], "presets": [], "charts": [], "cycles": []},
            )
            return {
                "status": "ok",
                "version": __version__,
                "workspace": str(self.root),
                "documents": documents,
                "templates": [item.as_dict() for item in list_templates(self.root)],
                "tutorials": [item.as_dict() for item in list_tutorials()],
                "packages": package_summary(locked_workspace_resolution(self.root))["packages"],
                "plugins": self.plugins.summary(),
                "runs": self.list_runs(),
                "validation": validation,
                "index": index,
                "authoring": validation.get("authoring", {"symbols": [], "references": [], "builtins": []}),
                "recovery": self._read_recovery(),
            }

    def read_document(self, key: str) -> dict:
        with self._lock:
            item = next((item for item in self._document_catalog() if item["key"] == key), None)
            if item is None:
                raise WorkspaceError(f"unknown document: {key}")
            if item["read_only"]:
                digest = item["package"]["content_sha256"]
                path = self.root / ".kirin" / "packages" / digest / item["path"]
            else:
                path = self._local_path(item["path"])
            text = path.read_text(encoding="utf-8")
            return {**item, "status": "ok", "text": text, "source_sha256": _hash_text(text)}

    def document_projection(
        self,
        key: str,
        overlays: Optional[Mapping[str, object]] = None,
    ) -> dict:
        """Return one validated, JSON-safe document projection for the trusted UI host."""
        with self._lock:
            parsed = self._overlays(overlays)
            catalog = self._document_catalog()
            item = next((candidate for candidate in catalog if candidate["key"] == key), None)
            if item is None:
                candidate_path = self._local_path(key, new=True)
                if candidate_path not in parsed:
                    raise WorkspaceError(f"unknown document: {key}")
                item = {
                    "key": key,
                    "path": key,
                    "title": extract_author_title(parsed[candidate_path], candidate_path.stem),
                    "kind": "entry",
                    "read_only": False,
                    "source_sha256": _hash_text(parsed[candidate_path]),
                }
                catalog.append(item)
            workspace = (
                Workspace.load_with_overlays(self.root, parsed)
                if parsed
                else Workspace.load(self.root)
            )
            run_with_timeout(_validate_workspace, (workspace,), DEFAULT_TIMEOUT_SECONDS)
            if item["read_only"]:
                actual = (
                    self.root
                    / ".kirin"
                    / "packages"
                    / item["package"]["content_sha256"]
                    / item["path"]
                ).resolve()
            else:
                actual = self._local_path(item["path"], new=True).resolve()
            document = next(
                (candidate for candidate in workspace.documents.values() if candidate.path.resolve() == actual),
                None,
            )
            if document is None:
                raise WorkspaceError(f"validated document disappeared: {key}")
            graph = build_relationship_graph(workspace)
            member_ids = {
                node["id"] for node in graph["nodes"] if node["document_id"] == document.id
            }
            relationships = [
                edge
                for edge in graph["edges"]
                if edge["source"] in member_ids or edge["target"] in member_ids
            ]
            package = None
            if document.package_origin is not None:
                package = {
                    "source": document.package_origin.source,
                    "name": document.package_origin.name,
                    "version": document.package_origin.version,
                    "namespace": document.package_origin.namespace,
                    "resolved": document.package_origin.resolved,
                    "content_sha256": document.package_origin.content_sha256,
                }
            return {
                "status": "ok",
                "document": {
                    "key": key,
                    "id": document.id,
                    "name": document.name,
                    "kind": document.type,
                    "read_only": document.read_only,
                    "source_sha256": document.sha256,
                    "content": document.raw,
                    "positions": {
                        field: {"line": position[0], "column": position[1]}
                        for field, position in sorted(document.positions.items())
                    },
                    "package": package,
                },
                "members": [
                    {**node, "path": key}
                    for node in graph["nodes"]
                    if node["document_id"] == document.id
                ],
                "relationships": relationships,
                "workspace": {
                    "documents": [
                        {
                            "key": candidate["key"],
                            "title": candidate["title"],
                            "kind": candidate["kind"],
                            "read_only": candidate["read_only"],
                            "package": (
                                {
                                    "name": candidate["package"]["name"],
                                    "version": candidate["package"]["version"],
                                    "content_sha256": candidate["package"]["content_sha256"],
                                }
                                if candidate.get("package")
                                else None
                            ),
                        }
                        for candidate in catalog
                    ],
                    "packages": [
                        {
                            key: package.get(key)
                            for key in (
                                "alias",
                                "direct",
                                "name",
                                "version",
                                "namespace",
                                "game",
                                "game_version",
                                "content_sha256",
                            )
                            if package.get(key) is not None
                        }
                        for package in package_summary(
                            locked_workspace_resolution(self.root)
                        )["packages"]
                    ],
                },
            }

    @staticmethod
    def _index_dict(workspace: Workspace) -> dict:
        index = build_workspace_index(workspace)
        return {
            "targets": [item.__dict__ for item in index.targets],
            "inputs": [item.__dict__ for item in index.inputs],
            "presets": [item.__dict__ for item in index.presets],
            "charts": [item.__dict__ for item in index.charts],
            "cycles": [item.__dict__ for item in index.cycles],
            "document_ids": list(index.document_ids),
        }

    def validate(self, overlays: Optional[Mapping[str, object]] = None) -> dict:
        with self._lock:
            parsed = self._overlays(overlays)
            sources = {
                path: path.read_text(encoding="utf-8")
                for folder in ("entries",)
                for path in (self.root / folder).rglob("*.kirin")
                if path.is_file()
            }
            sources.update(parsed)
            authoring = build_authoring_index(self._authoring_sources(parsed))
            try:
                workspace = (
                    Workspace.load_for_check_with_overlays(self.root, parsed)
                    if parsed
                    else Workspace.load_for_check(self.root)
                )
                result = run_with_timeout(
                    _validate_workspace,
                    (workspace,),
                    DEFAULT_TIMEOUT_SECONDS,
                )
                return {**result, "status": "ok", "index": self._index_dict(workspace), "authoring": authoring}
            except ValidationErrors as exc:
                return {**author_error_payload(exc, self.root, sources), "authoring": authoring}
            except KTError as exc:
                return {**author_error_payload(exc, self.root, sources), "authoring": authoring}

    def save(self, overlays: Mapping[str, object], expected: Optional[Mapping[str, object]] = None) -> dict:
        with self._lock:
            parsed = self._overlays(overlays)
            if not parsed:
                return {"status": "ok", "saved": []}
            expected = expected or {}
            for path in parsed:
                relative = path.relative_to(self.root).as_posix()
                expected_hash = expected.get(relative)
                if path.exists():
                    current = _hash_text(path.read_text(encoding="utf-8"))
                    if expected_hash is not None and current != expected_hash:
                        raise WorkspaceError(
                            "document changed outside the workbench; compare or reload before saving",
                            SourceLocation(path=relative),
                        )
                elif expected_hash not in {None, ""}:
                    raise WorkspaceError(
                        "new document unexpectedly disappeared",
                        SourceLocation(path=relative),
                    )
            workspace = Workspace.load_with_overlays(self.root, parsed)
            run_with_timeout(
                _validate_workspace,
                (workspace,),
                DEFAULT_TIMEOUT_SECONDS,
            )
            for path in parsed:
                relative = path.relative_to(self.root).as_posix()
                expected_hash = expected.get(relative)
                if path.exists():
                    current = _hash_text(path.read_text(encoding="utf-8"))
                    if expected_hash is not None and current != expected_hash:
                        raise WorkspaceError(
                            "document changed outside the workbench; compare or reload before saving",
                            SourceLocation(path=relative),
                        )
                elif expected_hash not in {None, ""}:
                    raise WorkspaceError(
                        "new document unexpectedly disappeared",
                        SourceLocation(path=relative),
                    )
            atomic_write_sources(parsed)
            return {
                "status": "ok",
                "saved": [
                    {
                        "path": path.relative_to(self.root).as_posix(),
                        "source_sha256": _hash_text(text),
                    }
                    for path, text in sorted(parsed.items())
                ],
            }

    def create_document(self, template: str, document_id: str) -> dict:
        with self._lock:
            draft = build_from_template(self.root, template, document_id)
            if draft.path.exists():
                raise WorkspaceError(f"document already exists: {draft.path.relative_to(self.root)}")
            return {
                "status": "ok",
                "path": draft.path.relative_to(self.root).as_posix(),
                "kind": draft.kind,
                "id": draft.document_id,
                "title": extract_author_title(draft.source_text, draft.document_id),
                "text": draft.source_text,
            }

    def document_action(
        self,
        action: str,
        payload: Optional[Mapping[str, object]] = None,
        overlays: Optional[Mapping[str, object]] = None,
    ) -> dict:
        with self._lock:
            data = dict(payload or {})
            parsed = self._overlays(overlays)
            if parsed:
                raise WorkspaceError("save or discard all drafts before changing document files")
            key = str(data.get("key", ""))
            source_path = self._local_path(key)
            source_text = source_path.read_text(encoding="utf-8")
            expected = data.get("expected_sha256")
            if isinstance(expected, str) and expected and _hash_text(source_text) != expected:
                raise WorkspaceError(
                    "document changed outside the workbench; reload before changing its file",
                    SourceLocation(path=key),
                )

            if action == "move":
                destination_key = str(data.get("destination", ""))
                destination = self._local_path(destination_key, new=True)
                if destination.exists():
                    raise WorkspaceError(f"document already exists: {destination_key}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source_path, destination)
                return {
                    "status": "ok",
                    "action": action,
                    "path": destination.relative_to(self.root).as_posix(),
                    "source_sha256": _hash_text(source_text),
                }

            if action == "duplicate":
                document_id = str(data.get("document_id", ""))
                if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", document_id):
                    raise ParameterError("document_id must be an ASCII identifier")
                destination = self._local_path(f"entries/{document_id}.kirin", new=True)
                if destination.exists():
                    raise WorkspaceError(f"document already exists: entries/{document_id}.kirin")
                header = re.search(
                    r'^@entry\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+"(?:[^"\\]|\\.)*")?$',
                    source_text,
                    re.MULTILINE,
                )
                if header is None:
                    raise WorkspaceError(f"document has no @entry identity: {key}")
                old_id = header.group(1)
                duplicated = source_text[:header.start(1)] + document_id + source_text[header.end(1):]
                authoring = build_authoring_index(self._authoring_sources({destination.resolve(): duplicated}))
                edits = []
                destination_key = destination.relative_to(self.root).as_posix()
                for reference in authoring["references"]:
                    location = reference["location"]
                    text = reference["text"]
                    if location["key"] != destination_key or not text.startswith(f"{old_id}."):
                        continue
                    edits.append((
                        _source_offset(duplicated, location["line"], location["column"]),
                        _source_offset(duplicated, location["line"], location["end_column"]),
                        f"{document_id}.{text.split('.', 1)[1]}",
                    ))
                for start, end, replacement in sorted(edits, reverse=True):
                    duplicated = duplicated[:start] + replacement + duplicated[end:]
                candidate = {destination: duplicated}
                workspace = Workspace.load_with_overlays(self.root, candidate)
                run_with_timeout(_validate_workspace, (workspace,), DEFAULT_TIMEOUT_SECONDS)
                return {
                    "status": "ok",
                    "action": action,
                    "path": destination.relative_to(self.root).as_posix(),
                    "kind": "entry",
                    "id": document_id,
                    "text": duplicated,
                }

            if action == "remove":
                trash_root = self.root / ".kirin" / "trash" / "documents"
                trash_root.mkdir(parents=True, exist_ok=True)
                trash_path = trash_root / f"{uuid.uuid4().hex}-{source_path.name}"
                os.replace(source_path, trash_path)
                try:
                    workspace = Workspace.load(self.root)
                    run_with_timeout(_validate_workspace, (workspace,), DEFAULT_TIMEOUT_SECONDS)
                except Exception:
                    source_path.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(trash_path, source_path)
                    raise
                return {
                    "status": "ok",
                    "action": action,
                    "path": key,
                    "trash_path": trash_path.relative_to(self.root).as_posix(),
                }

            raise ParameterError(f"unknown document action: {action}")

    def completions(self, key: str, prefix: str, overlays: Optional[Mapping[str, object]] = None) -> dict:
        with self._lock:
            path = self._local_path(key, new=True)
            parsed = self._overlays(overlays)
            sources: dict[Path, str] = {}
            for item in self._document_catalog():
                if item["read_only"]:
                    digest = item["package"]["content_sha256"]
                    actual = self.root / ".kirin" / "packages" / digest / item["path"]
                else:
                    actual = self._local_path(item["path"])
                sources[actual] = parsed.get(actual.resolve(), actual.read_text(encoding="utf-8"))
            sources.update(parsed)
            return {
                "status": "ok",
                "items": [item.__dict__ for item in build_completion_candidates(sources, path, prefix)],
            }

    def authoring_action(
        self,
        action: str,
        payload: Optional[Mapping[str, object]] = None,
        overlays: Optional[Mapping[str, object]] = None,
    ) -> dict:
        with self._lock:
            data = dict(payload or {})
            parsed = self._overlays(overlays)
            sources = self._authoring_sources(parsed)
            if action == "index":
                return {"status": "ok", **build_authoring_index(sources)}
            if action == "format":
                key = str(data.get("key", ""))
                source = next((item for item in sources if item.key == key), None)
                if source is None:
                    raise WorkspaceError(f"unknown document: {key}")
                if source.read_only:
                    raise WorkspaceError(f"document is read-only: {key}")
                rendered = format_kirin_source(source.text)
                return {
                    "status": "ok",
                    "changes": [] if rendered == source.text else [{
                        "key": source.key,
                        "path": source.path,
                        "before": source.text,
                        "text": rendered,
                    }],
                }
            if action == "rename":
                result = rename_authoring_symbol(
                    sources,
                    str(data.get("symbol", "")),
                    str(data.get("new_name", "")),
                )
                candidate = dict(parsed)
                for change in result["changes"]:
                    candidate[self._local_path(change["key"], new=True)] = change["text"]
                workspace = Workspace.load_with_overlays(self.root, candidate)
                run_with_timeout(_validate_workspace, (workspace,), DEFAULT_TIMEOUT_SECONDS)
                return result
            if action == "search":
                query = str(data.get("query", ""))
                if not query:
                    raise ParameterError("search query must not be empty")
                case_sensitive = bool(data.get("case_sensitive"))
                needle = query if case_sensitive else query.casefold()
                matches = []
                for source in sources:
                    for line_number, line in enumerate(source.text.splitlines(), start=1):
                        haystack = line if case_sensitive else line.casefold()
                        start = 0
                        while len(matches) < 1000:
                            column = haystack.find(needle, start)
                            if column < 0:
                                break
                            matches.append({
                                "key": source.key,
                                "path": source.path,
                                "line": line_number,
                                "column": column + 1,
                                "preview": line.strip(),
                                "read_only": source.read_only,
                            })
                            start = column + max(1, len(needle))
                    if len(matches) >= 1000:
                        break
                return {"status": "ok", "matches": matches, "truncated": len(matches) >= 1000}
            if action == "replace":
                query = str(data.get("query", ""))
                replacement = str(data.get("replacement", ""))
                if not query:
                    raise ParameterError("replace query must not be empty")
                case_sensitive = bool(data.get("case_sensitive"))
                changes = []
                replacements = 0
                for source in sources:
                    if source.read_only:
                        continue
                    rendered, count = _plain_replace(source.text, query, replacement, case_sensitive)
                    if count:
                        replacements += count
                        if replacements > 5000:
                            raise ParameterError("workspace replacement exceeds 5,000 edits")
                        changes.append({
                            "key": source.key,
                            "path": source.path,
                            "before": source.text,
                            "text": rendered,
                            "edits": count,
                        })
                return {"status": "ok", "changes": changes, "edits": replacements}
            if action == "merge":
                base = data.get("base")
                draft = data.get("draft")
                disk = data.get("disk")
                if not all(isinstance(value, str) for value in (base, draft, disk)):
                    raise ParameterError("merge requires base, draft, and disk source text")
                return {"status": "ok", **_three_way_merge(base, draft, disk)}
            if action == "git_history":
                try:
                    top = subprocess.run(
                        ["git", "rev-parse", "--show-toplevel"],
                        cwd=self.root,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    ).stdout.strip()
                    log = subprocess.run(
                        ["git", "log", "-n", "20", "--date=iso-strict", "--pretty=format:%H%x09%ad%x09%s"],
                        cwd=self.root,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    ).stdout
                    status = subprocess.run(
                        ["git", "status", "--short", "--", "."],
                        cwd=self.root,
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=3,
                    ).stdout.splitlines()
                except (FileNotFoundError, subprocess.SubprocessError):
                    return {"status": "ok", "available": False, "commits": [], "working_tree": []}
                commits = []
                for line in log.splitlines():
                    parts = line.split("\t", 2)
                    if len(parts) == 3:
                        commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})
                return {
                    "status": "ok",
                    "available": True,
                    "root": top,
                    "commits": commits,
                    "working_tree": status,
                }
            raise ParameterError(f"unknown authoring action: {action}")

    def list_runs(self) -> list[dict]:
        result = []
        for path in sorted((self.root / "runs").glob("*.json"), reverse=True):
            try:
                record = load_run(self.root, path.stem)
                result.append(
                    {
                        "id": path.stem,
                        "operation": record.get("operation"),
                        "created_at": record.get("created_at"),
                        "status": record.get("status"),
                    }
                )
            except KTError as exc:
                result.append({"id": path.stem, "status": "error", "error": exc.as_dict()})
        return result

    def _player_overrides(self, workspace: Workspace, text) -> dict[str, str]:
        if isinstance(text, dict):
            return {str(key): str(value) for key, value in text.items()}
        return parse_player_override_text(str(text or ""), build_workspace_index(workspace).inputs)

    def execute(
        self,
        operation: str,
        payload: Optional[Mapping[str, object]] = None,
        overlays: Optional[Mapping[str, object]] = None,
    ) -> dict:
        with self._lock:
            payload = dict(payload or {})
            parsed_overlays = self._overlays(overlays)
            workspace = Workspace.load_with_overlays(self.root, parsed_overlays) if parsed_overlays else Workspace.load(self.root)
            engine = Engine(workspace)
            precision = _number(payload, "precision", 30, int)
            display_digits = _number(payload, "display_digits", 12, int)
            timeout = _number(payload, "timeout", DEFAULT_TIMEOUT_SECONDS, float)
            preset = str(payload["preset"]) if payload.get("preset") else None
            overrides = self._player_overrides(workspace, payload.get("overrides"))
            save_run_id = str(payload["save_run"]) if payload.get("save_run") else None
            if save_run_id and parsed_overlays:
                raise WorkspaceError("save all document drafts before creating a durable run record")

            if operation == "version":
                return {"status": "ok", "version": __version__}
            if operation == "list":
                return {"status": "ok", "documents": self._document_catalog()}
            if operation == "show":
                return self.read_document(str(payload.get("document", "")))
            if operation == "check":
                candidate = (
                    Workspace.load_for_check_with_overlays(self.root, parsed_overlays)
                    if parsed_overlays
                    else Workspace.load_for_check(self.root)
                )
                result = run_with_timeout(
                    _validate_workspace,
                    (candidate,),
                    timeout,
                )
                return {**result, "status": "ok"}
            if operation == "explain":
                return explain(engine, str(payload.get("target", "")), timeout)
            if operation == "relationship_graph":
                run_with_timeout(_validate_workspace, (workspace,), timeout)
                return build_relationship_graph(workspace)

            if operation == "preview_plot":
                config_id = str(payload.get("config", ""))
                config = workspace.get_chart(config_id)
                preview_overrides = self._player_overrides(workspace, payload.get("overrides"))
                result = scan_values(
                    engine,
                    config.x,
                    f"{config.range_start}:{config.range_end}",
                    config.points,
                    list(config.y),
                    str(payload["preset"]) if payload.get("preset") else config.preset,
                    preview_overrides,
                    precision,
                    display_digits,
                    timeout,
                )
                result["operation"] = "preview_plot"
                result["config"] = config_id
                return result

            if operation == "eval":
                request = {
                    "target": str(payload.get("target", "")), "preset": preset,
                    "overrides": overrides, "precision": precision,
                    "display_digits": display_digits, "timeout_seconds": timeout,
                }
                return record_operation(
                    workspace, save_run_id, "eval", request,
                    lambda: evaluate(engine, request["target"], preset, overrides, precision, display_digits, timeout),
                    [preset] if preset else [],
                )

            if operation == "cycle":
                request = {
                    "target": str(payload.get("target", "")),
                    "preset": preset,
                    "overrides": overrides,
                    "timeout_seconds": timeout,
                }
                return record_operation(
                    workspace,
                    save_run_id,
                    "cycle",
                    request,
                    lambda: analyze_cycle(
                        engine,
                        request["target"],
                        preset,
                        overrides,
                        timeout,
                    ),
                    [preset] if preset else [],
                )

            if operation == "compare":
                variants = []
                for raw in payload.get("variants", []):
                    if not isinstance(raw, Mapping):
                        raise ParameterError("comparison variants must be objects")
                    variants.append(
                        ComparisonVariant(
                            str(raw.get("name", "")),
                            str(raw["preset"]) if raw.get("preset") else None,
                            self._player_overrides(workspace, raw.get("overrides")),
                        )
                    )
                if save_run_id:
                    from .application import save_comparison_run
                    return save_comparison_run(workspace, save_run_id, str(payload.get("target", "")), variants, precision=precision, display_digits=display_digits, timeout_seconds=timeout)
                return compare_variants(workspace, str(payload.get("target", "")), variants, precision=precision, display_digits=display_digits, timeout_seconds=timeout)

            if operation == "scan_compare":
                variants = []
                for raw in payload.get("variants", []):
                    if not isinstance(raw, Mapping):
                        raise ParameterError("chart comparison variants must be objects")
                    variants.append(
                        ComparisonVariant(
                            str(raw.get("name", "")),
                            str(raw["preset"]) if raw.get("preset") else None,
                            self._player_overrides(workspace, raw.get("overrides")),
                        )
                    )
                request = {
                    "x": str(payload.get("x", "")),
                    "range": str(payload.get("range", "")),
                    "points": _number(payload, "points", 41, int),
                    "target": str(payload.get("target", "")),
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
                    "timeout_seconds": timeout,
                    "out": payload.get("out"),
                }
                output_path = artifact_path(
                    workspace,
                    str(payload["out"]),
                    bool(payload.get("allow_outside_workspace")),
                ) if payload.get("out") else None
                if output_path:
                    preflight_artifacts([output_path], bool(payload.get("force")))

                def compute_comparison_scan():
                    result = scan_variant_comparison(
                        workspace,
                        request["x"],
                        request["range"],
                        request["points"],
                        request["target"],
                        variants,
                        precision=precision,
                        display_digits=display_digits,
                        timeout_seconds=timeout,
                    )
                    if output_path:
                        result["out"] = str(
                            write_scan_csv(
                                result,
                                output_path,
                                overwrite=bool(payload.get("force")),
                            )
                        )
                    return result

                extras = [variant.preset for variant in variants if variant.preset]
                return record_operation(
                    workspace,
                    save_run_id,
                    "scan_compare",
                    request,
                    compute_comparison_scan,
                    extras,
                )

            if operation in {"simplify", "expand", "factor"}:
                keep = _split_values(payload.get("keep"))
                request = {
                    "target": str(payload.get("target", "")), "preset": preset,
                    "overrides": overrides, "keep": keep, "timeout_seconds": timeout,
                }
                return record_operation(
                    workspace, save_run_id, operation, request,
                    lambda: transform(engine, operation, request["target"], preset, overrides, keep, timeout),
                    [preset] if preset else [],
                )

            if operation == "diff":
                request = {
                    "target": str(payload.get("target", "")),
                    "variable": str(payload.get("variable", "")),
                    "preset": preset, "overrides": overrides, "timeout_seconds": timeout,
                }
                return record_operation(
                    workspace, save_run_id, "diff", request,
                    lambda: differentiate(engine, request["target"], request["variable"], preset, overrides, timeout),
                    [preset] if preset else [],
                )

            if operation == "solve":
                request = {
                    "target": str(payload.get("target", "")),
                    "variable": str(payload.get("variable", "")),
                    "equals": str(payload.get("equals", "")),
                    "range": str(payload["range"]) if payload.get("range") else None,
                    "preset": preset, "overrides": overrides,
                    "precision": precision, "timeout_seconds": timeout,
                }
                return record_operation(
                    workspace, save_run_id, "solve", request,
                    lambda: solve_equation(engine, request["target"], request["variable"], request["equals"], request["range"], preset, overrides, precision, timeout),
                    [preset] if preset else [],
                )

            if operation == "solve_system":
                equations = []
                for line in _split_values(payload.get("equations"), ";\n"):
                    if line.count("=") != 1:
                        raise ParameterError("system equation must use TARGET=VALUE")
                    equations.append(tuple(part.strip() for part in line.split("=", 1)))
                variables = _split_values(payload.get("variables"))
                request = {
                    "equations": [{"target": target, "equals": equals} for target, equals in equations],
                    "variables": variables, "preset": preset, "overrides": overrides,
                    "precision": precision, "timeout_seconds": timeout,
                }
                return record_operation(
                    workspace, save_run_id, "solve_system", request,
                    lambda: solve_system(engine, equations, variables, preset, overrides, precision, timeout),
                    [preset] if preset else [],
                )

            if operation == "scan":
                targets = _split_values(payload.get("targets"))
                request = {
                    "x": str(payload.get("x", "")), "range": str(payload.get("range", "")),
                    "points": _number(payload, "points", 41, int), "targets": targets,
                    "preset": preset, "overrides": overrides, "precision": precision,
                    "display_digits": display_digits, "timeout_seconds": timeout,
                    "out": payload.get("out"),
                }
                output_path = artifact_path(
                    workspace,
                    str(payload["out"]),
                    bool(payload.get("allow_outside_workspace")),
                ) if payload.get("out") else None
                if output_path:
                    preflight_artifacts([output_path], bool(payload.get("force")))
                def compute_scan():
                    result = scan_values(engine, request["x"], request["range"], request["points"], targets, preset, overrides, precision, display_digits, timeout)
                    if output_path:
                        result["out"] = str(write_scan_csv(result, output_path, overwrite=bool(payload.get("force"))))
                    return result
                return record_operation(workspace, save_run_id, "scan", request, compute_scan, [preset] if preset else [])

            if operation == "grid":
                request = {
                    "x": str(payload.get("x", "")), "x_range": str(payload.get("x_range", "")),
                    "x_points": _number(payload, "x_points", 21, int),
                    "y": str(payload.get("y", "")), "y_range": str(payload.get("y_range", "")),
                    "y_points": _number(payload, "y_points", 21, int),
                    "target": str(payload.get("target", "")), "preset": preset,
                    "overrides": overrides, "precision": precision,
                    "display_digits": display_digits, "timeout_seconds": timeout,
                    "out": payload.get("out"),
                }
                output_path = artifact_path(
                    workspace,
                    str(payload["out"]),
                    bool(payload.get("allow_outside_workspace")),
                ) if payload.get("out") else None
                if output_path:
                    preflight_artifacts([output_path], bool(payload.get("force")))
                def compute_grid():
                    result = scan_grid(engine, request["x"], request["x_range"], request["x_points"], request["y"], request["y_range"], request["y_points"], request["target"], preset, overrides, precision, display_digits, timeout)
                    if output_path:
                        result["out"] = str(write_grid_csv(result, output_path, overwrite=bool(payload.get("force"))))
                    return result
                return record_operation(workspace, save_run_id, "grid", request, compute_grid, [preset] if preset else [])

            if operation == "plot":
                config_id = str(payload["config"]) if payload.get("config") else None
                config = workspace.get_chart(config_id) if config_id else None
                chosen_x = str(payload.get("x") or (config.x if config else ""))
                chosen_range = str(payload.get("range") or (f"{config.range_start}:{config.range_end}" if config else ""))
                chosen_points = _number(payload, "points", config.points if config else 101, int)
                targets = _split_values(payload.get("targets")) or (list(config.y) if config else [])
                chosen_preset = preset or (config.preset if config else None)
                chosen_out = str(payload.get("out") or (config.out if config else ""))
                chosen_data = str(payload.get("data_out") or (config.data_out if config else "")) or None
                if not chosen_x or not chosen_range or not targets or not chosen_out:
                    raise ParameterError("plot requires x, range, points, targets, and an output path")
                allow_outside = bool(payload.get("allow_outside_workspace"))
                plot_path = artifact_path(workspace, chosen_out, allow_outside)
                data_path = artifact_path(workspace, chosen_data, allow_outside) if chosen_data else None
                preflight_artifacts([path for path in (plot_path, data_path) if path], bool(payload.get("force")))
                title = str(payload.get("title") or (config.title if config else "")) or None
                x_label = str(payload.get("x_label") or (config.x_label if config else "")) or None
                y_label = str(payload.get("y_label") or (config.y_label if config else "")) or None
                curve_labels = config.curve_labels if config else {}
                request = {
                    "x": chosen_x, "range": chosen_range, "points": chosen_points,
                    "targets": targets, "preset": chosen_preset, "overrides": overrides,
                    "precision": precision, "display_digits": display_digits,
                    "timeout_seconds": timeout, "config": config_id, "out": chosen_out,
                    "data_out": chosen_data, "title": title, "x_label": x_label,
                    "y_label": y_label, "curve_labels": curve_labels,
                }
                def compute_plot():
                    result = scan_values(engine, chosen_x, chosen_range, chosen_points, targets, chosen_preset, overrides, precision, display_digits, timeout)
                    result["operation"] = "plot"
                    result["out"] = str(run_with_timeout(render_plot, (result, plot_path, bool(payload.get("force")), title, x_label, y_label, curve_labels), timeout))
                    if data_path:
                        result["data_out"] = str(write_scan_csv(result, data_path, overwrite=bool(payload.get("force"))))
                    return result
                extras = [item for item in (chosen_preset, config_id) if item]
                return record_operation(workspace, save_run_id, "plot", request, compute_plot, extras)

            if operation == "replay":
                allow_outside = bool(payload.get("allow_outside_workspace"))
                out_path = artifact_path(self.root, str(payload["out"]), allow_outside) if payload.get("out") else None
                data_path = artifact_path(self.root, str(payload["data_out"]), allow_outside) if payload.get("data_out") else None
                return replay_run(
                    self.root, str(payload.get("run_id", "")),
                    regenerate_artifacts=bool(payload.get("regenerate_artifacts")),
                    out=out_path, data_out=data_path, force=bool(payload.get("force")),
                )
            raise ParameterError(f"unknown workbench operation: {operation}")

    def package_action(self, action: str, payload: Optional[Mapping[str, object]] = None) -> dict:
        payload = dict(payload or {})
        if action == "discover":
            return discover_community(
                "package",
                query=payload.get("query", ""),
                page=payload.get("page", 1),
            )
        with self._lock:
            if action == "list":
                return package_summary(PackageResolver(PackageStoreManager(self.root)).load_locked_workspace())
            if action == "add":
                return package_summary(add_package(self.root, str(payload.get("alias", "")), str(payload.get("source", "")), str(payload.get("version", ""))))
            if action == "add_path":
                return package_summary(add_path_package(self.root, str(payload.get("alias", "")), Path(str(payload.get("path", "")))))
            if action == "remove":
                return package_summary(remove_package(self.root, str(payload.get("alias", ""))))
            if action == "update":
                version = str(payload["version"]) if payload.get("version") else None
                return package_summary(update_package(self.root, str(payload.get("alias", "")), version))
            if action == "restore":
                return package_summary(restore_packages(self.root))
            if action == "verify":
                resolution, validation = verify_packages(self.root)
                return {**package_summary(resolution), "validation": validation}
            if action == "new":
                root = create_package_template(
                    Path(str(payload.get("directory", ""))),
                    name=str(payload.get("name", "")),
                    namespace=str(payload.get("namespace", "")),
                    version=str(payload.get("version", "1.0.0")),
                )
                return {"status": "ok", "path": str(root)}
            if action == "check":
                resolution, validation = check_package(Path(str(payload.get("directory", "."))))
                return {**package_summary(resolution), "validation": validation}
            raise ParameterError(f"unknown package action: {action}")

    def plugin_action(self, action: str, payload: Optional[Mapping[str, object]] = None) -> dict:
        payload = dict(payload or {})
        if action == "discover":
            return discover_community(
                "plugin",
                query=payload.get("query", ""),
                page=payload.get("page", 1),
            )
        with self._lock:
            if action == "list":
                return self.plugins.summary()
            if action == "add_path":
                return self.plugins.add_path(
                    str(payload.get("alias", "")), Path(str(payload.get("path", "")))
                )
            if action == "update_path":
                return self.plugins.update_path(str(payload.get("alias", "")))
            if action == "enable":
                return self.plugins.set_enabled(str(payload.get("alias", "")), True)
            if action == "disable":
                return self.plugins.set_enabled(str(payload.get("alias", "")), False)
            if action == "remove":
                return self.plugins.remove(str(payload.get("alias", "")))
            if action == "verify":
                return self.plugins.verify()
            raise ParameterError(f"unknown plugin action: {action}")

    def plugin_asset(self, digest: str, relative: str) -> Path:
        return self.plugins.asset(digest, relative)

    def template_action(self, action: str, payload: Optional[Mapping[str, object]] = None) -> dict:
        with self._lock:
            payload = dict(payload or {})
            if action == "list":
                return {"status": "ok", "templates": [item.as_dict() for item in list_templates(self.root)]}
            if action == "save":
                workspace = Workspace.load(self.root)
                path = save_workspace_template(workspace, str(payload.get("document_id", "")), str(payload.get("template_id", "")))
                return {"status": "ok", "path": path.relative_to(self.root).as_posix()}
            if action == "remove":
                path = remove_workspace_template(self.root, str(payload.get("template", "")))
                return {"status": "ok", "path": path.relative_to(self.root).as_posix()}
            raise ParameterError(f"unknown template action: {action}")

    @staticmethod
    def initialize_workspace(path: str) -> dict:
        root = initialize(Path(path))
        return {"status": "ok", "path": str(root)}

    def artifact(self, relative: str) -> tuple[Path, str]:
        path = artifact_path(self.root, relative)
        if not path.is_file():
            raise WorkspaceError(f"artifact not found: {relative}")
        media = {
            ".svg": "image/svg+xml", ".png": "image/png", ".csv": "text/csv; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(path.suffix.lower(), "application/octet-stream")
        return path, media
