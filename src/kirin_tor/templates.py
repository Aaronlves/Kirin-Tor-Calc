"""Static one-shot document templates from the core, workspace, and Packages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Optional, Tuple

from .diagnostics import extract_author_title
from .errors import SchemaError, WorkspaceError
from .kirin_v2 import parse_kirin_v2_source, render_kirin_v2_document
from .limits import MAX_EXPRESSION_LENGTH, MAX_PLUGIN_TEMPLATE_BINDINGS
from .package_store import PackageResolution, locked_workspace_resolution
from .schema import require_identifier
from .workspace import DocumentDraft, Workspace, build_document_draft


TEMPLATE_DIRECTORY = "templates"
_HEADER_RE = re.compile(
    r'^@(entry)\s+([A-Za-z_][A-Za-z0-9_]*)(\s+"(?:[^"\\]|\\.)*")?$',
    re.MULTILINE,
)
_BINDING_RE = re.compile(
    r"^\s*//\s*@template-bind\s+([A-Za-z_][A-Za-z0-9_]*)\s*$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class TemplateInfo:
    value: str
    template_id: str
    label: str
    kind: str
    origin: str
    source_path: Optional[Path] = None
    package_name: Optional[str] = None
    package_version: Optional[str] = None
    bindings: Tuple[str, ...] = ()
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "id": self.template_id,
            "label": self.label,
            "kind": self.kind,
            "origin": self.origin,
            "source_path": (
                str(self.source_path)
                if self.source_path and self.origin in {"workspace", "package"}
                else None
            ),
            "package_name": self.package_name,
            "package_version": self.package_version,
            "bindings": list(self.bindings),
            "error": self.error,
        }


_BUILTINS: Tuple[Tuple[str, str, str], ...] = (
    ("blank", "空白条目", "entry"),
    ("data", "数据与技能", "entry"),
    ("model", "组合计算", "entry"),
    ("semantics", "数学语义", "entry"),
    ("chart", "带图表的计算文档", "entry"),
)


def _template_files(root: Path) -> Iterable[Tuple[str, Path]]:
    base = root / TEMPLATE_DIRECTORY
    for kind, folder in (("entry", "entries"),):
        directory = base / folder
        if directory.is_dir():
            for path in sorted(directory.rglob("*.kirin")):
                if path.is_file():
                    yield kind, path.resolve()


def _file_info(
    path: Path,
    kind: str,
    *,
    value: str,
    origin: str,
    package_name: Optional[str] = None,
    package_version: Optional[str] = None,
) -> TemplateInfo:
    source = path.read_text(encoding="utf-8")
    bindings = tuple(_BINDING_RE.findall(source))
    binding_error = None
    if len(bindings) != len(set(bindings)):
        binding_error = "template contains duplicate @template-bind names"
    elif len(bindings) > MAX_PLUGIN_TEMPLATE_BINDINGS:
        binding_error = (
            f"template exceeds {MAX_PLUGIN_TEMPLATE_BINDINGS} bindings"
        )
    else:
        try:
            raw, _positions, _processes, _scenarios, _analyses = (
                parse_kirin_v2_source(source, path)
            )
            missing = sorted(set(bindings) - set(raw.get("inputs", {})))
            if missing:
                binding_error = (
                    "template bindings must name declared inputs: "
                    + ", ".join(missing)
                )
        except SchemaError as exc:
            binding_error = str(exc)
    match = _HEADER_RE.search(source)
    if match is None or match.group(1) != kind:
        return TemplateInfo(
            value=value,
            template_id=path.stem,
            label=path.stem,
            kind=kind,
            origin=origin,
            source_path=path,
            package_name=package_name,
            package_version=package_version,
            bindings=bindings,
            error=f"template must contain one @{kind} document header",
        )
    return TemplateInfo(
        value=value,
        template_id=path.stem,
        label=extract_author_title(source, path.stem),
        kind=kind,
        origin=origin,
        source_path=path,
        package_name=package_name,
        package_version=package_version,
        bindings=bindings,
        error=binding_error,
    )


def list_templates(
    root: Path,
    *,
    package_resolution: Optional[PackageResolution] = None,
    include_packages: bool = True,
) -> Tuple[TemplateInfo, ...]:
    """List built-in, workspace, and locked Package templates."""
    root = root.resolve()
    result = [
        TemplateInfo(f"builtin:{template_id}", template_id, label, kind, "builtin")
        for template_id, label, kind in _BUILTINS
    ]
    for kind, path in _template_files(root):
        relative = path.relative_to(root / TEMPLATE_DIRECTORY).as_posix()
        result.append(
            _file_info(
                path,
                kind,
                value=f"workspace:{relative}",
                origin="workspace",
            )
        )
    if include_packages:
        resolution = package_resolution or locked_workspace_resolution(root)
        for package in resolution.packages:
            for kind, path in _template_files(package.root):
                relative = path.relative_to(package.root / TEMPLATE_DIRECTORY).as_posix()
                result.append(
                    _file_info(
                        path,
                        kind,
                        value=f"package:{package.content_sha256}:{relative}",
                        origin="package",
                        package_name=package.manifest.name,
                        package_version=package.manifest.version,
                    )
                )
    return tuple(result)


def expand_template_source(source: str, kind: str, document_id: str) -> str:
    match = _HEADER_RE.search(source)
    if match is None or match.group(1) != kind:
        raise SchemaError(f"selected template does not create a {kind} document")
    old_id = match.group(2)
    header = f"@{kind} {document_id}{match.group(3) or ''}"
    expanded = source[: match.start()] + header + source[match.end() :]
    if old_id != document_id:
        expanded = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old_id)}\.", f"{document_id}.", expanded)
    return expanded if expanded.endswith("\n") else expanded + "\n"


def apply_template_bindings(
    source: str,
    bindings: Mapping[str, object],
    *,
    path: Path,
) -> str:
    """Apply declared input defaults, then render one canonical new document."""

    if not bindings:
        return source
    if len(bindings) > MAX_PLUGIN_TEMPLATE_BINDINGS:
        raise WorkspaceError(
            f"template binding count exceeds {MAX_PLUGIN_TEMPLATE_BINDINGS}"
        )
    declared = tuple(_BINDING_RE.findall(source))
    unknown = sorted(set(bindings) - set(declared))
    if unknown:
        raise WorkspaceError(
            "template does not declare binding(s): " + ", ".join(unknown)
        )
    raw, _positions, process_asts, scenario_asts, analysis_asts = (
        parse_kirin_v2_source(source, path)
    )
    for name, value in bindings.items():
        if not isinstance(value, str) or not value.strip():
            raise WorkspaceError(f"template binding {name!r} must be non-empty text")
        text = value.strip()
        if len(text) > MAX_EXPRESSION_LENGTH:
            raise WorkspaceError(
                f"template binding {name!r} exceeds {MAX_EXPRESSION_LENGTH} characters"
            )
        input_data = raw.get("inputs", {}).get(name)
        if input_data is None:
            raise WorkspaceError(f"template binding input does not exist: {name}")
        input_data["default"] = (
            True if text == "true" else False if text == "false" else text
        )
    return render_kirin_v2_document(
        raw,
        process_asts,
        scenario_asts,
        analysis_asts,
    )


def build_from_template(
    root: Path,
    template_value: str,
    document_id: str,
    *,
    package_resolution: Optional[PackageResolution] = None,
    include_packages: bool = True,
    bindings: Optional[Mapping[str, object]] = None,
) -> DocumentDraft:
    """Expand one static template into an independent in-memory document draft."""
    root = root.resolve()
    require_identifier(document_id, "id", None)
    templates = {
        item.value: item
        for item in list_templates(
            root,
            package_resolution=package_resolution,
            include_packages=include_packages,
        )
    }
    selected = templates.get(template_value)
    if selected is None:
        raise WorkspaceError(f"unknown document template: {template_value}")
    if selected.error:
        raise SchemaError(selected.error)
    if selected.origin == "builtin":
        if bindings:
            raise WorkspaceError("built-in template does not declare bindings")
        entry_template = selected.template_id
        return build_document_draft(
            root,
            selected.kind,
            document_id,
            entry_template=entry_template,
        )
    unknown_bindings = sorted(set(bindings or {}) - set(selected.bindings))
    if unknown_bindings:
        raise WorkspaceError(
            "template does not declare binding(s): " + ", ".join(unknown_bindings)
        )
    assert selected.source_path is not None
    source = selected.source_path.read_text(encoding="utf-8")
    expanded = expand_template_source(source, selected.kind, document_id)
    expanded = apply_template_bindings(
        expanded,
        bindings or {},
        path=selected.source_path,
    )
    return DocumentDraft(
        selected.kind,
        document_id,
        (root / "entries" / f"{document_id}.kirin").resolve(),
        expanded,
    )


def save_workspace_template(
    workspace: Workspace, document_id: str, template_id: str
) -> Path:
    """Copy one local authoritative document into the workspace template catalog."""
    require_identifier(template_id, "template id", None)
    document = workspace.documents.get(document_id)
    if document is None:
        raise WorkspaceError(f"unknown document id {document_id!r}")
    if document.read_only:
        raise WorkspaceError("Package documents cannot be copied as workspace templates")
    target = (workspace.root / TEMPLATE_DIRECTORY / "entries" / f"{template_id}.kirin").resolve()
    if target.exists():
        raise WorkspaceError(f"template already exists: {template_id}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document.raw_text, encoding="utf-8")
    return target


def remove_workspace_template(root: Path, template_value: str) -> Path:
    """Remove one workspace-owned template without touching generated documents."""
    templates = {item.value: item for item in list_templates(root) if item.origin == "workspace"}
    selected = templates.get(template_value)
    if selected is None or selected.source_path is None:
        raise WorkspaceError("only workspace templates may be removed")
    selected.source_path.unlink()
    return selected.source_path
