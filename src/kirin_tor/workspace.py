"""Workspace discovery, safe document loading, and file creation."""

from __future__ import annotations

import hashlib
import importlib.resources
from pathlib import Path
from typing import Dict, Iterable, Optional

import yaml

from .errors import KTError, ReferenceError, SchemaError, SourceLocation, ValidationErrors, WorkspaceError
from .schema import (
    Document,
    Entry,
    PlotConfig,
    Scenario,
    build_semantic_registry,
    parse_document,
    safe_load_document,
)
from .limits import MAX_WORKSPACE_DOCUMENTS, MAX_WORKSPACE_YAML_BYTES
from .units import UnitRegistry


MARKER = ".kirin-tor.yaml"


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
            raw, text, digest, positions = safe_load_document(path)
            raw_documents.append((raw, text, digest, path, positions))
        registry = build_semantic_registry(raw_documents)
        documents = [
            parse_document(raw, text, digest, path, registry, positions)
            for raw, text, digest, path, positions in raw_documents
        ]
        return cls(root, documents, registry)

    @staticmethod
    def _document_paths(root: Path) -> list[Path]:
        paths = []
        for folder in ("entries", "scenarios", "plots"):
            directory = root / folder
            if directory.exists():
                paths.extend(path for path in directory.rglob("*.yaml") if path.is_file())
                paths.extend(path for path in directory.rglob("*.yml") if path.is_file())
        result = sorted(set(paths))
        if len(result) > MAX_WORKSPACE_DOCUMENTS:
            raise WorkspaceError(
                f"workspace exceeds {MAX_WORKSPACE_DOCUMENTS} YAML documents"
            )
        total_bytes = sum(path.stat().st_size for path in result)
        if total_bytes > MAX_WORKSPACE_YAML_BYTES:
            raise WorkspaceError(
                f"workspace YAML exceeds {MAX_WORKSPACE_YAML_BYTES} total bytes"
            )
        return result

    @staticmethod
    def _validate_marker(root: Path) -> None:
        marker = root / MARKER
        raw, _text, _digest, _positions = safe_load_document(marker)
        unknown = sorted(set(raw) - {"schema_version", "kind", "initial_package"})
        if unknown:
            raise SchemaError(
                "unknown workspace marker key(s): " + ", ".join(unknown),
                SourceLocation(path=str(marker)),
            )
        if raw.get("schema_version") != 1:
            raise SchemaError("workspace schema_version must be 1", SourceLocation(path=str(marker)))
        if raw.get("kind") != "kirin_tor_workspace":
            raise SchemaError(
                "workspace marker kind must be kirin_tor_workspace",
                SourceLocation(path=str(marker)),
            )
        if "initial_package" in raw and not isinstance(raw["initial_package"], str):
            raise SchemaError("workspace initial_package must be text", SourceLocation(path=str(marker)))

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
                raw, text, digest, positions = safe_load_document(path)
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
                text = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            path = virtual_root / f"{index:04d}-{raw.get('id', 'unknown')}.yaml"
            from .schema import _collect_positions

            raw_documents.append((raw, text, digest, path, _collect_positions(text)))
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
    package_path = root / "entries" / f"{package_name}_semantics.yaml"
    if package_name != "none" and package_path.exists():
        raise WorkspaceError(f"initialization would overwrite an existing file: {package_path}")
    for folder in ("entries", "scenarios", "plots", "runs", "results"):
        (root / folder).mkdir(exist_ok=True)
    with marker.open("x", encoding="utf-8") as handle:
        handle.write(f"schema_version: 1\nkind: kirin_tor_workspace\ninitial_package: {package_name}\n")
    if package_name != "none":
        resource = importlib.resources.files("kirin_tor.packages").joinpath(f"{package_name}.yaml")
        content = resource.read_text(encoding="utf-8")
        with package_path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    return root


def create_entry_template(workspace: Workspace, entry_type: str, entry_id: str) -> Path:
    from .schema import require_identifier

    require_identifier(entry_id, "id", SourceLocation(entry_id=entry_id))
    if entry_type not in {"entry", "skill", "model"}:
        raise SchemaError("new entry template must be entry, skill, or model")
    path = workspace.root / "entries" / f"{entry_id}.yaml"
    if path.exists():
        raise WorkspaceError(f"file already exists: {path}")
    if entry_type in {"entry", "skill"}:
        content = {
            "schema_version": 1,
            "id": entry_id,
            "name": entry_id,
            "type": "entry",
            "template": entry_type,
            "description": "Edit this fictional template.",
            "inputs": {},
            "fields": {
                "base_value": {"kind": "value", "value": "0", "unit": "dimensionless"}
            },
            "functions": {},
            "outputs": {},
        }
    else:
        content = {
            "schema_version": 1,
            "id": entry_id,
            "name": entry_id,
            "type": "entry",
            "template": "model",
            "inputs": {
                "x": {"unit": "dimensionless", "default": "0"}
            },
            "fields": {},
            "functions": {},
            "outputs": {
                "result": {"expression": "x", "unit": "dimensionless"}
            },
        }
    with path.open("x", encoding="utf-8") as handle:
        handle.write(yaml.safe_dump(content, allow_unicode=True, sort_keys=False))
    return path


def create_scenario_template(workspace: Workspace, scenario_id: str) -> Path:
    from .schema import require_identifier

    require_identifier(scenario_id, "id", SourceLocation(entry_id=scenario_id))
    path = workspace.root / "scenarios" / f"{scenario_id}.yaml"
    if path.exists():
        raise WorkspaceError(f"file already exists: {path}")
    content = {
        "schema_version": 1,
        "id": scenario_id,
        "name": scenario_id,
        "type": "scenario",
        "values": {},
    }
    with path.open("x", encoding="utf-8") as handle:
        handle.write(yaml.safe_dump(content, allow_unicode=True, sort_keys=False))
    return path


def create_plot_template(workspace: Workspace, plot_id: str) -> Path:
    from .schema import require_identifier

    require_identifier(plot_id, "id", SourceLocation(entry_id=plot_id))
    path = workspace.root / "plots" / f"{plot_id}.yaml"
    if path.exists():
        raise WorkspaceError(f"file already exists: {path}")
    content = {
        "schema_version": 1,
        "id": plot_id,
        "name": plot_id,
        "type": "plot",
        "x": "entry.input",
        "range": ["0", "1"],
        "points": 101,
        "y": ["entry.output"],
        "out": f"results/{plot_id}.svg",
        "data_out": f"results/{plot_id}.csv",
    }
    with path.open("x", encoding="utf-8") as handle:
        handle.write(yaml.safe_dump(content, allow_unicode=True, sort_keys=False))
    return path
