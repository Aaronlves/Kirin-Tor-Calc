"""Workspace discovery, safe document loading, and file creation."""

from __future__ import annotations

import hashlib
import importlib.resources
from pathlib import Path
from typing import Dict, Iterable, Optional

from .errors import KTError, ReferenceError, SchemaError, SourceLocation, ValidationErrors, WorkspaceError
from .kirin_syntax import load_kirin_document, parse_kirin_source, render_kirin_document
from .schema import (
    Document,
    Entry,
    PlotConfig,
    Scenario,
    build_semantic_registry,
    parse_document,
)
from .limits import MAX_SOURCE_BYTES, MAX_WORKSPACE_DOCUMENTS, MAX_WORKSPACE_SOURCE_BYTES
from .units import UnitRegistry


MARKER = "kirin.workspace"


class Workspace:
    def __init__(self, root: Path, documents: Iterable[Document], units: Optional[UnitRegistry] = None):
        self.root = root.resolve()
        self.units = units or UnitRegistry()
        self.documents: Dict[str, Document] = {}
        for document in documents:
            if document.id in self.documents:
                previous = self.documents[document.id]
                raise SchemaError(
                    f"duplicate id {document.id!r}; first defined at {previous.path}",
                    SourceLocation(path=str(document.path), entry_id=document.id),
                )
            self.documents[document.id] = document

    @property
    def entries(self) -> Dict[str, Entry]:
        return {key: value for key, value in self.documents.items() if isinstance(value, Entry)}

    @property
    def scenarios(self) -> Dict[str, Scenario]:
        return {key: value for key, value in self.documents.items() if isinstance(value, Scenario)}

    @property
    def plots(self) -> Dict[str, PlotConfig]:
        return {key: value for key, value in self.documents.items() if isinstance(value, PlotConfig)}

    @classmethod
    def find_root(cls, start: Optional[Path] = None) -> Path:
        current = (start or Path.cwd()).resolve()
        for candidate in (current, *current.parents):
            if (candidate / MARKER).is_file():
                return candidate
        raise WorkspaceError(f"no Kirin Tor workspace found from {current}; run 'kt init <directory>'")

    @classmethod
    def discover(cls, start: Optional[Path] = None) -> "Workspace":
        return cls.load(cls.find_root(start))

    @classmethod
    def load(cls, root: Path) -> "Workspace":
        root = root.resolve()
        if not (root / MARKER).is_file():
            raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
        cls._validate_marker(root)
        paths = cls._document_paths(root)
        raw_documents = []
        for path in paths:
            raw, text, digest, positions = cls._load_source_document(path)
            raw_documents.append((raw, text, digest, path, positions))
        registry = build_semantic_registry(raw_documents)
        documents = [
            parse_document(raw, text, digest, path, registry, positions)
            for raw, text, digest, path, positions in raw_documents
        ]
        return cls(root, documents, registry)

    @classmethod
    def load_with_overlay(cls, root: Path, source_path: Path, source_text: str) -> "Workspace":
        """Load a workspace with one unsaved Kirin editor buffer overlaid."""
        return cls.load_with_overlays(root, {source_path: source_text})

    @classmethod
    def load_with_overlays(cls, root: Path, overlays: Dict[Path, str]) -> "Workspace":
        """Load a workspace with unsaved Kirin editor buffers overlaid."""
        root = root.resolve()
        if not (root / MARKER).is_file():
            raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
        cls._validate_marker(root)
        resolved_overlays: Dict[Path, str] = {}
        for source_path, source_text in overlays.items():
            source_path = source_path.resolve()
            try:
                relative = source_path.relative_to(root)
            except ValueError as exc:
                raise WorkspaceError(f"editor source must stay inside the workspace: {source_path}") from exc
            if source_path.suffix.lower() != ".kirin" or not relative.parts or relative.parts[0] not in {
                "entries", "scenarios", "plots"
            }:
                raise WorkspaceError("editor source must be a .kirin file inside entries, scenarios, or plots")
            resolved_overlays[source_path] = source_text
        paths = cls._document_paths(root)
        for source_path in resolved_overlays:
            if source_path not in paths:
                paths.append(source_path)
        paths.sort()
        if len(paths) > MAX_WORKSPACE_DOCUMENTS:
            raise WorkspaceError(
                f"workspace exceeds {MAX_WORKSPACE_DOCUMENTS} source documents"
            )
        total_bytes = sum(
            len(resolved_overlays[path].encode("utf-8")) if path in resolved_overlays else path.stat().st_size
            for path in paths
        )
        if total_bytes > MAX_WORKSPACE_SOURCE_BYTES:
            raise WorkspaceError(
                f"workspace sources exceed {MAX_WORKSPACE_SOURCE_BYTES} total bytes"
            )
        raw_documents = []
        for path in paths:
            raw, text, digest, positions = cls._load_source_document(
                path, resolved_overlays.get(path)
            )
            raw_documents.append((raw, text, digest, path, positions))
        registry = build_semantic_registry(raw_documents)
        documents = [
            parse_document(raw, text, digest, path, registry, positions)
            for raw, text, digest, path, positions in raw_documents
        ]
        return cls(root, documents, registry)

    @staticmethod
    def _load_source_document(path: Path, text_override: Optional[str] = None):
        if path.suffix.lower() != ".kirin":
            raise WorkspaceError(f"workspace source must use the .kirin extension: {path}")
        return load_kirin_document(path, text_override)

    @staticmethod
    def _document_paths(root: Path) -> list[Path]:
        paths = []
        for folder in ("entries", "scenarios", "plots"):
            directory = root / folder
            if directory.exists():
                paths.extend(path for path in directory.rglob("*.kirin") if path.is_file())
        result = sorted(set(paths))
        if len(result) > MAX_WORKSPACE_DOCUMENTS:
            raise WorkspaceError(
                f"workspace exceeds {MAX_WORKSPACE_DOCUMENTS} source documents"
            )
        total_bytes = sum(path.stat().st_size for path in result)
        if total_bytes > MAX_WORKSPACE_SOURCE_BYTES:
            raise WorkspaceError(
                f"workspace sources exceed {MAX_WORKSPACE_SOURCE_BYTES} total bytes"
            )
        return result

    @staticmethod
    def _validate_marker(root: Path) -> None:
        marker = root / MARKER
        raw_bytes = marker.read_bytes()
        if len(raw_bytes) > MAX_SOURCE_BYTES:
            raise SchemaError("workspace marker is too large", SourceLocation(path=str(marker)))
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SchemaError("workspace marker must be UTF-8", SourceLocation(path=str(marker))) from exc
        lines = [
            (number, line.strip())
            for number, line in enumerate(text.splitlines(), 1)
            if line.strip() and not line.lstrip().startswith("//")
        ]
        if not lines or lines[0][1] != "@kirin-workspace 1":
            raise SchemaError(
                "workspace marker must start with '@kirin-workspace 1'",
                SourceLocation(path=str(marker), line=lines[0][0] if lines else 1, column=1),
            )
        seen = set()
        for number, line in lines[1:]:
            if ":" not in line:
                raise SchemaError(
                    "workspace setting must use KEY: VALUE",
                    SourceLocation(path=str(marker), line=number, column=1),
                )
            key, value = (part.strip() for part in line.split(":", 1))
            if key != "initial-package":
                raise SchemaError(
                    f"unknown workspace setting {key!r}",
                    SourceLocation(path=str(marker), line=number, column=1),
                )
            if key in seen or not value:
                raise SchemaError(
                    "workspace initial-package must appear once with a value",
                    SourceLocation(path=str(marker), line=number, column=1),
                )
            if value not in AVAILABLE_PACKAGES:
                raise SchemaError(
                    "workspace initial-package must be one of: "
                    + ", ".join(sorted(AVAILABLE_PACKAGES)),
                    SourceLocation(path=str(marker), line=number, column=1),
                )
            seen.add(key)
        if "initial-package" not in seen:
            raise SchemaError(
                "workspace marker requires initial-package",
                SourceLocation(path=str(marker), line=1, column=1),
            )

    @classmethod
    def load_for_check(cls, root: Path) -> "Workspace":
        """Load as many documents as possible and report independent schema failures together."""
        root = root.resolve()
        if not (root / MARKER).is_file():
            raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
        cls._validate_marker(root)
        raw_documents = []
        errors = []
        for path in cls._document_paths(root):
            try:
                raw, text, digest, positions = cls._load_source_document(path)
                raw_documents.append((raw, text, digest, path, positions))
            except KTError as exc:
                errors.append(exc)
        try:
            registry = build_semantic_registry(raw_documents)
        except KTError as exc:
            errors.append(exc)
            if errors:
                raise ValidationErrors(errors)
            raise
        documents = []
        for raw, text, digest, path, positions in raw_documents:
            try:
                documents.append(parse_document(raw, text, digest, path, registry, positions))
            except KTError as exc:
                errors.append(exc)
        try:
            workspace = cls(root, documents, registry)
        except KTError as exc:
            errors.append(exc)
            workspace = cls(root, [], registry)
        if errors:
            raise ValidationErrors(errors)
        return workspace

    @classmethod
    def from_snapshots(cls, snapshots: Iterable[dict]) -> "Workspace":
        documents = []
        virtual_root = Path("/snapshot")
        raw_documents = []
        for index, snapshot in enumerate(snapshots):
            raw = snapshot.get("content")
            if not isinstance(raw, dict):
                raise SchemaError("run snapshot content is invalid")
            text = snapshot.get("source_text")
            if not isinstance(text, str):
                text = render_kirin_document(raw)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            path = virtual_root / f"{index:04d}-{raw.get('id', 'unknown')}.kirin"
            _parsed, positions = parse_kirin_source(text, path)
            raw_documents.append((raw, text, digest, path, positions))
        registry = build_semantic_registry(raw_documents)
        for raw, text, digest, path, positions in raw_documents:
            documents.append(parse_document(raw, text, digest, path, registry, positions))
        return cls(virtual_root, documents, registry)

    def get_entry(self, entry_id: str) -> Entry:
        document = self.documents.get(entry_id)
        if document is None:
            raise ReferenceError(f"missing reference to entry {entry_id!r}")
        if not isinstance(document, Entry):
            raise ReferenceError(f"{entry_id!r} is a {document.type}, not a data entry")
        return document

    def get_scenario(self, scenario_id: Optional[str]) -> Optional[Scenario]:
        if scenario_id is None:
            return None
        document = self.documents.get(scenario_id)
        if document is None:
            raise ReferenceError(f"missing scenario {scenario_id!r}")
        if not isinstance(document, Scenario):
            raise ReferenceError(f"{scenario_id!r} is not a scenario")
        return document

    def get_plot(self, plot_id: str) -> PlotConfig:
        document = self.documents.get(plot_id)
        if document is None:
            raise ReferenceError(f"missing plot config {plot_id!r}")
        if not isinstance(document, PlotConfig):
            raise ReferenceError(f"{plot_id!r} is not a plot config")
        return document


AVAILABLE_PACKAGES = {"none", "wow"}


def initialize(root: Path, package_name: str = "none") -> Path:
    root = root.resolve()
    if package_name not in AVAILABLE_PACKAGES:
        raise WorkspaceError(
            f"unknown package {package_name!r}; available packages: {', '.join(sorted(AVAILABLE_PACKAGES))}"
        )
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if marker.exists():
        raise WorkspaceError(f"workspace already exists at {root}")
    package_path = root / "entries" / f"{package_name}_semantics.kirin"
    if package_name != "none" and package_path.exists():
        raise WorkspaceError(f"initialization would overwrite an existing file: {package_path}")
    for folder in ("entries", "scenarios", "plots", "runs", "results"):
        (root / folder).mkdir(exist_ok=True)
    with marker.open("x", encoding="utf-8") as handle:
        handle.write(f"@kirin-workspace 1\ninitial-package: {package_name}\n")
    if package_name != "none":
        resource = importlib.resources.files("kirin_tor.packages").joinpath(f"{package_name}.kirin")
        content = resource.read_text(encoding="utf-8")
        with package_path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    return root


def create_entry_template(workspace: Workspace, entry_type: str, entry_id: str) -> Path:
    from .schema import require_identifier

    require_identifier(entry_id, "id", SourceLocation(entry_id=entry_id))
    if entry_type not in {"entry", "skill", "model"}:
        raise SchemaError("new entry template must be entry, skill, or model")
    if entry_id in workspace.documents:
        raise WorkspaceError(f"document id already exists: {entry_id}")
    path = workspace.root / "entries" / f"{entry_id}.kirin"
    if path.exists():
        raise WorkspaceError(f"file already exists: {path}")
    if entry_type in {"entry", "skill"}:
        content = f"""@kirin 1
@entry {entry_id}
@template {entry_type}

// {entry_id}

---
Edit this fictional template.
---

fields:
  base_value: dimensionless = 0
"""
    else:
        content = f"""@kirin 1
@entry {entry_id}
@template model

// {entry_id}

inputs:
  x: number[dimensionless] = 0

outputs:
  result: dimensionless = x
"""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    return path


def create_scenario_template(workspace: Workspace, scenario_id: str) -> Path:
    from .schema import require_identifier

    require_identifier(scenario_id, "id", SourceLocation(entry_id=scenario_id))
    if scenario_id in workspace.documents:
        raise WorkspaceError(f"document id already exists: {scenario_id}")
    path = workspace.root / "scenarios" / f"{scenario_id}.kirin"
    if path.exists():
        raise WorkspaceError(f"file already exists: {path}")
    content = f"""@kirin 1
@scenario {scenario_id}

// {scenario_id}

values:
"""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    return path


def create_plot_template(workspace: Workspace, plot_id: str) -> Path:
    from .schema import require_identifier

    require_identifier(plot_id, "id", SourceLocation(entry_id=plot_id))
    if plot_id in workspace.documents:
        raise WorkspaceError(f"document id already exists: {plot_id}")
    path = workspace.root / "plots" / f"{plot_id}.kirin"
    if path.exists():
        raise WorkspaceError(f"file already exists: {path}")
    content = f"""@kirin 1
@plot {plot_id}

// {plot_id}

x: entry.input
range: 0..1
points: 101

y:
  entry.output

export-svg: \"results/{plot_id}.svg\"
export-csv: \"results/{plot_id}.csv\"
"""
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    return path
