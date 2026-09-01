"""Workspace discovery, safe document loading, and file creation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence

from .errors import KTError, ReferenceError, SchemaError, SourceLocation, ValidationErrors, WorkspaceError
from .kirin_syntax import load_kirin_document, parse_kirin_source, render_kirin_document
from .schema import (
    Document,
    Entry,
    PackageOrigin,
    Preset,
    build_semantic_registry,
    parse_document,
    require_identifier,
)
from .limits import MAX_SOURCE_BYTES, MAX_WORKSPACE_DOCUMENTS, MAX_WORKSPACE_SOURCE_BYTES
from .package_manifest import package_source_paths
from .package_store import PackageResolution, locked_workspace_resolution
from .units import UnitRegistry


MARKER = "kirin.workspace"
DOCUMENT_DRAFT_KINDS = ("entry",)
ENTRY_TEMPLATE_KINDS = ("blank", "data", "model", "semantics", "chart")


@dataclass(frozen=True)
class DocumentDraft:
    """A validated source-template proposal which has not necessarily been written."""

    kind: str
    document_id: str
    path: Path
    source_text: str


class Workspace:
    def __init__(
        self,
        root: Path,
        documents: Iterable[Document],
        units: Optional[UnitRegistry] = None,
        package_resolution: Optional[PackageResolution] = None,
    ):
        self.root = root.resolve()
        self.units = units or UnitRegistry()
        self.package_resolution = package_resolution
        self.documents: Dict[str, Document] = {}
        for document in documents:
            if document.id in self.documents:
                previous = self.documents[document.id]
                raise SchemaError(
                    f"duplicate id {document.id!r}; first defined at {previous.path}",
                    SourceLocation(path=str(document.path), entry_id=document.id),
                )
            self.documents[document.id] = document
        self._validate_package_semantic_scopes()

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
    def charts(self) -> Dict[str, Entry]:
        """Return documents that opt into a chart through x/y syntax."""
        return {key: value for key, value in self.entries.items() if value.has_chart}

    def allowed_package_sources(self, source: str) -> Optional[set[str]]:
        """Return one package's declared dependency closure, or None for snapshots."""
        if self.package_resolution is None:
            return None
        packages = self.package_resolution.by_source()
        if source not in packages:
            return {source}
        result: set[str] = set()
        pending = [source]
        while pending:
            candidate = pending.pop()
            if candidate in result:
                continue
            result.add(candidate)
            package = packages.get(candidate)
            if package is not None:
                pending.extend(item.source for item in package.manifest.dependencies)
        return result

    def _validate_package_semantic_scopes(self) -> None:
        if self.package_resolution is None:
            return
        owners: Dict[str, Dict[str, set[Optional[str]]]] = {
            "dimension": {},
            "unit": {},
            "domain": {},
        }
        section_kinds = {
            "dimensions": "dimension",
            "units": "unit",
            "domains": "domain",
        }
        for document in self.entries.values():
            origin_source = document.package_origin.source if document.package_origin else None
            for section, kind in section_kinds.items():
                declarations = document.semantics.get(section, {})
                if not isinstance(declarations, dict):
                    continue
                for name in declarations:
                    owners[kind].setdefault(name, set()).add(origin_source)

        for kind, declarations in owners.items():
            for name, declared_by in declarations.items():
                package_sources = {source for source in declared_by if source is not None}
                if package_sources and (None in declared_by or len(package_sources) > 1):
                    raise SchemaError(
                        f"package {kind} {name!r} collides across authority boundaries"
                    )

        def check(document: Entry, kind: str, name: Optional[str], field: str) -> None:
            if name is None or document.package_origin is None:
                return
            builtin = {
                "dimension": self.units.builtin_dimensions,
                "unit": self.units.builtin_units,
                "domain": self.units.builtin_domains,
            }[kind]
            if name in builtin:
                return
            declared_by = owners[kind].get(name, set())
            allowed = self.allowed_package_sources(document.package_origin.source) or {
                document.package_origin.source
            }
            if None in declared_by:
                raise SchemaError(
                    f"package {document.package_origin.name!r} uses workspace-local {kind} {name!r}",
                    document.location(field),
                )
            unavailable = sorted(
                source for source in declared_by if source is not None and source not in allowed
            )
            if unavailable:
                raise SchemaError(
                    f"package {document.package_origin.name!r} uses {kind} {name!r} from undeclared "
                    f"package source {unavailable[0]!r}",
                    document.location(field),
                )

        for document in self.entries.values():
            if document.package_origin is None:
                continue
            for name, spec in document.inputs.items():
                check(document, "domain", spec.domain_name, f"inputs.{name}")
                check(document, "unit", spec.unit_name, f"inputs.{name}")
            for name, data in document.fields.items():
                check(document, "unit", data.get("unit", "dimensionless"), f"fields.{name}")
            for name, data in document.functions.items():
                check(document, "unit", data.get("unit", "dimensionless"), f"functions.{name}")
                for parameter, raw in data.get("parameters", {}).items():
                    check(document, "domain", raw.get("domain"), f"functions.{name}.parameters.{parameter}")
                    parameter_unit = raw.get("unit", "dimensionless")
                    if parameter_unit in self.units.domains:
                        check(
                            document,
                            "domain",
                            parameter_unit,
                            f"functions.{name}.parameters.{parameter}",
                        )
                    else:
                        check(
                            document,
                            "unit",
                            parameter_unit,
                            f"functions.{name}.parameters.{parameter}",
                        )
            for name, table in document.tables.items():
                check(document, "unit", table.input_unit, f"tables.{name}")
                check(document, "unit", table.output_unit, f"tables.{name}")
            for name, distribution in document.distributions.items():
                check(
                    document,
                    "unit",
                    distribution.unit_name,
                    f"distributions.{name}",
                )
            for name, recurrence in document.recurrences.items():
                check(
                    document,
                    "unit",
                    recurrence.unit_name,
                    f"recurrences.{name}",
                )
            for model_name, model in document.state_models.items():
                for reward_name, reward in model.rewards.items():
                    check(
                        document,
                        "unit",
                        reward.unit_name,
                        f"state_models.{model_name}.rewards.{reward_name}",
                    )
            for name, data in document.outputs.items():
                check(document, "unit", data.get("unit", "dimensionless"), f"outputs.{name}")
            units = document.semantics.get("units", {})
            if isinstance(units, dict):
                for unit_name, raw in units.items():
                    if isinstance(raw, dict):
                        for dimension_name in raw.get("dimensions", {}):
                            check(
                                document,
                                "dimension",
                                dimension_name,
                                f"semantics.units.{unit_name}",
                            )
            domains = document.semantics.get("domains", {})
            if isinstance(domains, dict):
                for domain_name, raw in domains.items():
                    if isinstance(raw, dict):
                        check(
                            document,
                            "unit",
                            raw.get("unit", "dimensionless"),
                            f"semantics.domains.{domain_name}",
                        )

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
    def load(
        cls, root: Path, package_resolution: Optional[PackageResolution] = None
    ) -> "Workspace":
        root = root.resolve()
        if not (root / MARKER).is_file():
            raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
        cls._validate_marker(root)
        package_resolution = package_resolution or locked_workspace_resolution(root)
        paths = cls._document_paths(root, package_resolution)
        origins = cls._package_origins(package_resolution)
        raw_documents = []
        for path in paths:
            raw, text, digest, positions = cls._load_source_document(path)
            cls._validate_package_source(raw, path, origins.get(path))
            raw_documents.append((raw, text, digest, path, positions))
        registry = build_semantic_registry(raw_documents)
        documents = [
            parse_document(
                raw,
                text,
                digest,
                path,
                registry,
                positions,
                package_origin=origins.get(path),
            )
            for raw, text, digest, path, positions in raw_documents
        ]
        return cls(root, documents, registry, package_resolution)

    @classmethod
    def load_with_overlay(cls, root: Path, source_path: Path, source_text: str) -> "Workspace":
        """Load a workspace with one unsaved Kirin editor buffer overlaid."""
        return cls.load_with_overlays(root, {source_path: source_text})

    @classmethod
    def load_with_overlays(
        cls,
        root: Path,
        overlays: Dict[Path, str],
        *,
        package_resolution: Optional[PackageResolution] = None,
    ) -> "Workspace":
        """Load a workspace with unsaved Kirin editor buffers overlaid."""
        root = root.resolve()
        if not (root / MARKER).is_file():
            raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
        cls._validate_marker(root)
        package_resolution = package_resolution or locked_workspace_resolution(root)
        origins = cls._package_origins(package_resolution)
        resolved_overlays: Dict[Path, str] = {}
        for source_path, source_text in overlays.items():
            source_path = source_path.resolve()
            try:
                relative = source_path.relative_to(root)
            except ValueError as exc:
                raise WorkspaceError(f"editor source must stay inside the workspace: {source_path}") from exc
            if source_path.suffix.lower() != ".kirin" or not relative.parts or relative.parts[0] != "entries":
                raise WorkspaceError("editor source must be a .kirin file inside entries")
            resolved_overlays[source_path] = source_text
        paths = cls._document_paths(root, package_resolution)
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
            cls._validate_package_source(raw, path, origins.get(path))
            raw_documents.append((raw, text, digest, path, positions))
        registry = build_semantic_registry(raw_documents)
        documents = [
            parse_document(
                raw,
                text,
                digest,
                path,
                registry,
                positions,
                package_origin=origins.get(path),
            )
            for raw, text, digest, path, positions in raw_documents
        ]
        return cls(root, documents, registry, package_resolution)

    @staticmethod
    def _load_source_document(path: Path, text_override: Optional[str] = None):
        if path.suffix.lower() != ".kirin":
            raise WorkspaceError(f"workspace source must use the .kirin extension: {path}")
        return load_kirin_document(path, text_override)

    @staticmethod
    def _document_paths(
        root: Path, package_resolution: Optional[PackageResolution] = None
    ) -> list[Path]:
        paths = []
        for folder in ("entries",):
            directory = root / folder
            if directory.exists():
                paths.extend(path for path in directory.rglob("*.kirin") if path.is_file())
        if package_resolution is not None:
            for package in package_resolution.packages:
                paths.extend(package_source_paths(package.root))
        result = sorted(set(path.resolve() for path in paths))
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
    def _package_origins(package_resolution: PackageResolution) -> Dict[Path, PackageOrigin]:
        result: Dict[Path, PackageOrigin] = {}
        for package in package_resolution.packages:
            origin = PackageOrigin(
                source=package.source,
                name=package.manifest.name,
                version=package.manifest.version,
                namespace=package.manifest.namespace,
                resolved=package.resolved,
                content_sha256=package.content_sha256,
            )
            for path in package_source_paths(package.root):
                result[path.resolve()] = origin
        return result

    @staticmethod
    def _validate_package_source(
        raw: dict, path: Path, origin: Optional[PackageOrigin]
    ) -> None:
        if origin is None:
            return
        prefix = origin.namespace + "_"
        document_id = raw.get("id")
        if not isinstance(document_id, str) or not document_id.startswith(prefix):
            raise SchemaError(
                f"package document id must start with namespace prefix {prefix!r}",
                SourceLocation(path=str(path), entry_id=document_id if isinstance(document_id, str) else None),
            )
        semantics = raw.get("semantics", {})
        if isinstance(semantics, dict):
            for section in ("dimensions", "units", "domains"):
                declarations = semantics.get(section, {})
                if not isinstance(declarations, dict):
                    continue
                for name in declarations:
                    if not isinstance(name, str) or not name.startswith(prefix):
                        raise SchemaError(
                            f"package {section[:-1]} name must start with namespace prefix {prefix!r}",
                            SourceLocation(path=str(path), entry_id=document_id, field=f"semantics.{section}.{name}"),
                        )

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
            seen.add(key)

    @classmethod
    def load_for_check(cls, root: Path) -> "Workspace":
        """Load as many documents as possible and report independent schema failures together."""
        root = root.resolve()
        if not (root / MARKER).is_file():
            raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
        cls._validate_marker(root)
        package_resolution = locked_workspace_resolution(root)
        origins = cls._package_origins(package_resolution)
        raw_documents = []
        errors = []
        for path in cls._document_paths(root, package_resolution):
            try:
                raw, text, digest, positions = cls._load_source_document(path)
                cls._validate_package_source(raw, path, origins.get(path))
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
                documents.append(
                    parse_document(
                        raw,
                        text,
                        digest,
                        path,
                        registry,
                        positions,
                        package_origin=origins.get(path),
                    )
                )
            except KTError as exc:
                errors.append(exc)
        try:
            workspace = cls(root, documents, registry, package_resolution)
        except KTError as exc:
            errors.append(exc)
            workspace = cls(root, [], registry, package_resolution)
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
        package_resolution = locked_workspace_resolution(root)
        origins = cls._package_origins(package_resolution)
        resolved_overlays: Dict[Path, str] = {}
        for source_path, source_text in overlays.items():
            source_path = source_path.resolve()
            try:
                relative = source_path.relative_to(root)
            except ValueError as exc:
                raise WorkspaceError(
                    f"editor source must stay inside the workspace: {source_path}"
                ) from exc
            if source_path.suffix.lower() != ".kirin" or not relative.parts or relative.parts[0] != "entries":
                raise WorkspaceError(
                    "editor source must be a .kirin file inside entries"
                )
            resolved_overlays[source_path] = source_text
        paths = cls._document_paths(root, package_resolution)
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
                cls._validate_package_source(raw, path, origins.get(path))
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
                documents.append(
                    parse_document(
                        raw,
                        text,
                        digest,
                        path,
                        registry,
                        positions,
                        package_origin=origins.get(path),
                    )
                )
            except KTError as exc:
                errors.append(exc)
        try:
            workspace = cls(root, documents, registry, package_resolution)
        except KTError as exc:
            errors.append(exc)
            workspace = cls(root, [], registry, package_resolution)
        if errors:
            raise ValidationErrors(errors)
        return workspace

    @classmethod
    def from_snapshots(cls, snapshots: Iterable[dict]) -> "Workspace":
        documents = []
        virtual_root = Path("/snapshot")
        raw_documents = []
        origins: Dict[Path, PackageOrigin] = {}
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
            package = snapshot.get("package")
            if isinstance(package, dict):
                required = {
                    "source",
                    "name",
                    "version",
                    "namespace",
                    "resolved",
                    "content_sha256",
                }
                if set(package) != required or any(
                    not isinstance(package.get(key), str) or not package.get(key)
                    for key in required
                ):
                    raise SchemaError("run snapshot package origin is invalid")
                origins[path] = PackageOrigin(**package)
        registry = build_semantic_registry(raw_documents)
        for raw, text, digest, path, positions in raw_documents:
            documents.append(
                parse_document(
                    raw,
                    text,
                    digest,
                    path,
                    registry,
                    positions,
                    package_origin=origins.get(path),
                )
            )
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

    def get_chart(self, document_id: str) -> Entry:
        document = self.documents.get(document_id)
        if document is None:
            raise ReferenceError(f"missing chart document {document_id!r}")
        if not isinstance(document, Entry) or not document.has_chart:
            raise ReferenceError(f"{document_id!r} does not define x/y chart configuration")
        return document


def initialize(root: Path) -> Path:
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if marker.exists():
        raise WorkspaceError(f"workspace already exists at {root}")
    for folder in ("entries", "runs", "results"):
        (root / folder).mkdir(exist_ok=True)
    with marker.open("x", encoding="utf-8") as handle:
        handle.write("@kirin-workspace 1\n")
    return root


def build_document_draft(
    root: Path,
    document_kind: str,
    document_id: str,
    *,
    entry_template: str = "model",
) -> DocumentDraft:
    """Build a canonical one-shot source template without writing it."""
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
    path = root / "entries" / f"{document_id}.kirin"

    if document_kind == "entry" and entry_template == "blank":
        source_text = f"""@kirin 1
@entry {document_id}

// {document_id}

---
说明这个条目的数据、公式和适用范围。
---
"""
    elif document_kind == "entry" and entry_template == "data":
        source_text = f"""@kirin 1
@entry {document_id}

// {document_id}

fields:
  base_value: dimensionless = 0
"""
    elif document_kind == "entry" and entry_template == "model":
        source_text = f"""@kirin 1
@entry {document_id}

// {document_id}

inputs:
  x: number[dimensionless] = 0

outputs:
  result: dimensionless = x
"""
    elif entry_template == "semantics":
        source_text = f"""@kirin 1
@entry {document_id}

// {document_id}

dimensions:
  value

units:
  value = value

domains:
  nonnegative: number[dimensionless] in 0..*
"""
    else:
        source_text = f"""@kirin 1
@entry {document_id}

// {document_id}

inputs:
  x: number[dimensionless] = 0

outputs:
  result: dimensionless = x

x: {document_id}.x
range: 0..1
points: 101

y:
  {document_id}.result
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
