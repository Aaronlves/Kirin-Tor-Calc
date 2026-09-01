"""Static one-shot document templates from the core, workspace, and Packages."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .diagnostics import extract_author_title
from .errors import SchemaError, WorkspaceError
from .package_store import locked_workspace_resolution
from .schema import require_identifier
from .workspace import DocumentDraft, Workspace, build_document_draft


TEMPLATE_DIRECTORY = "templates"
_HEADER_RE = re.compile(r"^@(entry)\s+([A-Za-z_][A-Za-z0-9_]*)$", re.MULTILINE)


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
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "value": self.value,
            "id": self.template_id,
            "label": self.label,
            "kind": self.kind,
            "origin": self.origin,
            "source_path": str(self.source_path) if self.source_path else None,
            "package_name": self.package_name,
            "package_version": self.package_version,
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
    )


def list_templates(root: Path) -> Tuple[TemplateInfo, ...]:
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
    resolution = locked_workspace_resolution(root)
    for package in resolution.packages:
        for kind, path in _template_files(package.root):
            relative = path.relative_to(package.root / TEMPLATE_DIRECTORY).as_posix()
            result.append(
                _file_info(
                    path,
                    kind,
                    value=f"package:{package.source}:{relative}",
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
    header = f"@{kind} {document_id}"
    expanded = source[: match.start()] + header + source[match.end() :]
    if old_id != document_id:
        expanded = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old_id)}\.", f"{document_id}.", expanded)
    return expanded if expanded.endswith("\n") else expanded + "\n"


def build_from_template(
    root: Path, template_value: str, document_id: str
) -> DocumentDraft:
    """Expand one static template into an independent in-memory document draft."""
    root = root.resolve()
    require_identifier(document_id, "id", None)
    templates = {item.value: item for item in list_templates(root)}
    selected = templates.get(template_value)
    if selected is None:
        raise WorkspaceError(f"unknown document template: {template_value}")
    if selected.error:
        raise SchemaError(selected.error)
    if selected.origin == "builtin":
        entry_template = selected.template_id
        return build_document_draft(
            root,
            selected.kind,
            document_id,
            entry_template=entry_template,
        )
    assert selected.source_path is not None
    source = selected.source_path.read_text(encoding="utf-8")
    expanded = expand_template_source(source, selected.kind, document_id)
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
