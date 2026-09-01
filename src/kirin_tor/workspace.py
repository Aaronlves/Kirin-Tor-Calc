"""Workspace discovery, safe document loading, and file creation."""

from __future__ import annotations

import hashlib
import importlib.resources
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from .errors import KTError, ReferenceError, SchemaError, SourceLocation, ValidationErrors, WorkspaceError
from .kirin_syntax import load_kirin_document, parse_kirin_source, render_kirin_document
from .schema import (
    Document,
    Entry,
    PlotConfig,
    Preset,
    build_semantic_registry,
    parse_document,
    require_identifier,
)
from .limits import MAX_SOURCE_BYTES, MAX_WORKSPACE_DOCUMENTS, MAX_WORKSPACE_SOURCE_BYTES
from .units import UnitRegistry


MARKER = "kirin.workspace"
DOCUMENT_DRAFT_KINDS = ("entry", "plot")
ENTRY_TEMPLATE_KINDS = ("blank", "data", "model", "semantics")


@dataclass(frozen=True)
class DocumentDraft:
    """A validated source-template proposal which has not necessarily been written."""

    kind: str
    document_id: str
    path: Path
    source_text: str


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
    def presets(self) -> Dict[str, Preset]:
        result: Dict[str, Preset] = {}
        for entry in self.entries.values():
            for preset in entry.presets.values():
                result[preset.qualified_id] = preset
        return result

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
                "entries", "plots"
            }:
                raise WorkspaceError("editor source must be a .kirin file inside entries or plots")
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
        for folder in ("entries", "plots"):
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
    def load_for_check_with_overlays(
        cls, root: Path, overlays: Dict[Path, str]
    ) -> "Workspace":
        """Aggregate independent source failures while honoring unsaved editor overlays."""
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
                raise WorkspaceError(
                    f"editor source must stay inside the workspace: {source_path}"
                ) from exc
            if source_path.suffix.lower() != ".kirin" or not relative.parts or relative.parts[0] not in {
                "entries",
                "plots",
            }:
                raise WorkspaceError(
                    "editor source must be a .kirin file inside entries or plots"
                )
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
            len(resolved_overlays[path].encode("utf-8"))
            if path in resolved_overlays
            else path.stat().st_size
            for path in paths
        )
        if total_bytes > MAX_WORKSPACE_SOURCE_BYTES:
            raise WorkspaceError(
                f"workspace sources exceed {MAX_WORKSPACE_SOURCE_BYTES} total bytes"
            )

        raw_documents = []
        errors = []
        for path in paths:
            try:
                raw, text, digest, positions = cls._load_source_document(
                    path, resolved_overlays.get(path)
                )
                raw_documents.append((raw, text, digest, path, positions))
            except KTError as exc:
                errors.append(exc)
        try:
            registry = build_semantic_registry(raw_documents)
        except KTError as exc:
            errors.append(exc)
            raise ValidationErrors(errors)
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

    def get_preset(self, preset_id: Optional[str]) -> Optional[Preset]:
        if preset_id is None:
            return None
        presets = self.presets
        if preset_id in presets:
            return presets[preset_id]
        matches = [preset for preset in presets.values() if preset.id == preset_id]
        if not matches:
            raise ReferenceError(f"missing preset {preset_id!r}")
        if len(matches) > 1:
            choices = ", ".join(sorted(preset.qualified_id for preset in matches))
            raise ReferenceError(f"preset {preset_id!r} is ambiguous; use one of: {choices}")
        return matches[0]

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
    for folder in ("entries", "plots", "runs", "results"):
        (root / folder).mkdir(exist_ok=True)
    with marker.open("x", encoding="utf-8") as handle:
        handle.write(f"@kirin-workspace 1\ninitial-package: {package_name}\n")
    if package_name != "none":
        resource = importlib.resources.files("kirin_tor.packages").joinpath(f"{package_name}.kirin")
        content = resource.read_text(encoding="utf-8")
        with package_path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    return root


def build_document_draft(
    root: Path,
    document_kind: str,
    document_id: str,
    *,
    plot_x: str = "entry.input",
    plot_targets: Sequence[str] = ("entry.output",),
    plot_range_start: str = "0",
    plot_range_end: str = "1",
    plot_points: int = 101,
    plot_preset: Optional[str] = None,
    entry_template: str = "model",
) -> DocumentDraft:
    """Build the canonical CLI/TUI source template without writing it."""
    require_identifier(document_id, "id", SourceLocation(entry_id=document_id))
    if document_kind not in DOCUMENT_DRAFT_KINDS:
        raise SchemaError(
            "new document template must be one of: " + ", ".join(DOCUMENT_DRAFT_KINDS)
        )
    if document_kind == "entry" and entry_template not in ENTRY_TEMPLATE_KINDS:
        raise SchemaError(
            "entry template must be one of: " + ", ".join(ENTRY_TEMPLATE_KINDS)
        )
    root = root.resolve()
    if document_kind == "entry":
        path = root / "entries" / f"{document_id}.kirin"
    else:
        path = root / "plots" / f"{document_id}.kirin"

    if document_kind == "entry" and entry_template == "blank":
        source_text = f"""@kirin 1
@entry {document_id}
@template entry

// {document_id}

---
说明这个条目的数据、公式和适用范围。
---
"""
    elif document_kind == "entry" and entry_template == "data":
        source_text = f"""@kirin 1
@entry {document_id}
@template data

// {document_id}

fields:
  base_value: dimensionless = 0
"""
    elif document_kind == "entry" and entry_template == "model":
        source_text = f"""@kirin 1
@entry {document_id}
@template model

// {document_id}

inputs:
  x: number[dimensionless] = 0

outputs:
  result: dimensionless = x
"""
    elif document_kind == "entry":
        source_text = f"""@kirin 1
@entry {document_id}
@template semantics

// {document_id}

dimensions:
  value

units:
  value = value

domains:
  nonnegative: number[dimensionless] in 0..*
"""
    else:
        targets = tuple(plot_targets)
        if not targets:
            raise SchemaError("new plot template requires at least one output target")
        if isinstance(plot_points, bool) or not isinstance(plot_points, int) or plot_points < 2:
            raise SchemaError("new plot template points must be an integer of at least 2")
        preset_line = f"preset: {plot_preset}\n\n" if plot_preset else ""
        target_lines = "\n".join(f"  {target}" for target in targets)
        source_text = f"""@kirin 1
@plot {document_id}

// {document_id}

x: {plot_x}
range: {plot_range_start}..{plot_range_end}
points: {plot_points}

{preset_line}y:
{target_lines}

export-svg: \"results/{document_id}.svg\"
export-csv: \"results/{document_id}.csv\"
"""
    return DocumentDraft(document_kind, document_id, path.resolve(), source_text)


def create_document_template(workspace: Workspace, document_kind: str, document_id: str) -> Path:
    """Create one canonical source template without replacing existing authority."""
    draft = build_document_draft(workspace.root, document_kind, document_id)
    if document_id in workspace.documents:
        raise WorkspaceError(f"document id already exists: {document_id}")
    if draft.path.exists():
        raise WorkspaceError(f"file already exists: {draft.path}")
    draft.path.parent.mkdir(parents=True, exist_ok=True)
    with draft.path.open("x", encoding="utf-8") as handle:
        handle.write(draft.source_text)
    return draft.path


def create_entry_template(workspace: Workspace, entry_type: str, entry_id: str) -> Path:
    template = entry_type
    if template not in ENTRY_TEMPLATE_KINDS:
        raise SchemaError(
            "entry template must be one of: " + ", ".join(ENTRY_TEMPLATE_KINDS)
        )
    draft = build_document_draft(workspace.root, "entry", entry_id, entry_template=template)
    if entry_id in workspace.documents:
        raise WorkspaceError(f"document id already exists: {entry_id}")
    if draft.path.exists():
        raise WorkspaceError(f"file already exists: {draft.path}")
    draft.path.parent.mkdir(parents=True, exist_ok=True)
    with draft.path.open("x", encoding="utf-8") as handle:
        handle.write(draft.source_text)
    return draft.path


def create_plot_template(workspace: Workspace, plot_id: str) -> Path:
    return create_document_template(workspace, "plot", plot_id)
