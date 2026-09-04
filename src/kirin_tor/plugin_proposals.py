"""Validation for volatile, all-or-nothing Plugin proposal transactions."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Mapping

from .diagnostics import extract_author_title
from .engine import Engine
from .errors import (
    InvalidRequestError,
    KTError,
    LimitExceededError,
    ProposalInvalidError,
    ProposalStaleError,
)
from .limits import (
    MAX_PLUGIN_DESCRIPTION_CHARS,
    MAX_PLUGIN_DRAFT_SOURCE_BYTES,
    MAX_PLUGIN_PROPOSAL_BYTES,
    MAX_PLUGIN_PROPOSAL_CHANGES,
    MAX_PLUGIN_TEMPLATE_BINDINGS,
    MAX_PLUGIN_TITLE_CHARS,
)
from .model_catalog import model_revision
from .schema import require_identifier
from .templates import build_from_template
from .workspace import Workspace


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ENTRY_HEADER_RE = re.compile(
    r'^@entry\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+"(?:[^"\\]|\\.)*")?$',
    re.MULTILINE,
)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise InvalidRequestError(f"{label} must be an object")
    return value


def _reject_unknown(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise InvalidRequestError(
            f"unknown {label} field(s): " + ", ".join(unknown)
        )


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvalidRequestError(f"{label} must be bounded non-empty text")
    return value.strip()


def _local_path(root: Path, relative: object, *, must_exist: bool) -> Path:
    key = _text(relative, "proposal document key", 500)
    path = (root / key).resolve()
    try:
        normalized = path.relative_to(root).as_posix()
    except ValueError as exc:
        raise ProposalInvalidError("proposal document leaves the workspace") from exc
    if (
        not normalized.startswith("entries/")
        or path.suffix.lower() != ".kirin"
        or normalized != key
    ):
        raise ProposalInvalidError(
            "proposal documents must be normalized .kirin paths under entries/"
        )
    if must_exist and not path.is_file():
        raise ProposalStaleError(f"proposal document no longer exists: {key}")
    return path


def _source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ProposalInvalidError("proposal candidate source must be non-empty text")
    if len(value.encode("utf-8")) > MAX_PLUGIN_DRAFT_SOURCE_BYTES:
        raise LimitExceededError(
            f"proposal document exceeds {MAX_PLUGIN_DRAFT_SOURCE_BYTES} bytes"
        )
    return value


def validate_plugin_proposal(
    workspace: Workspace,
    payload: object,
    overlays: Mapping[Path, str],
) -> dict:
    """Return a normalized transaction only after validating its full workspace."""

    request = _mapping(payload, "proposal")
    _reject_unknown(request, {"revision", "title", "description", "changes"}, "proposal")
    revision = request.get("revision")
    current_revision = model_revision(workspace)
    if not isinstance(revision, str) or revision != current_revision:
        raise ProposalStaleError("proposal targets an obsolete workspace revision")
    title = _text(request.get("title"), "proposal title", MAX_PLUGIN_TITLE_CHARS)
    description_value = request.get("description")
    description = (
        None
        if description_value is None or description_value == ""
        else _text(
            description_value,
            "proposal description",
            MAX_PLUGIN_DESCRIPTION_CHARS,
        )
    )
    raw_changes = request.get("changes")
    if not isinstance(raw_changes, list) or not raw_changes:
        raise InvalidRequestError("proposal changes must be a non-empty array")
    if len(raw_changes) > MAX_PLUGIN_PROPOSAL_CHANGES:
        raise LimitExceededError(
            f"proposal exceeds {MAX_PLUGIN_PROPOSAL_CHANGES} document changes"
        )

    root = workspace.root
    candidates = dict(overlays)
    normalized_changes = []
    targets: set[Path] = set()
    total_bytes = 0
    for index, raw_change in enumerate(raw_changes):
        change = _mapping(raw_change, f"proposal change {index + 1}")
        kind = change.get("kind")
        if kind == "create-from-template":
            _reject_unknown(
                change,
                {"kind", "template", "document_id", "bindings"},
                f"proposal change {index + 1}",
            )
            template = _text(change.get("template"), "template", 500)
            document_id = _text(change.get("document_id"), "document_id", 240)
            require_identifier(document_id, "document_id", None)
            raw_bindings = _mapping(change.get("bindings", {}), "template bindings")
            if len(raw_bindings) > MAX_PLUGIN_TEMPLATE_BINDINGS:
                raise LimitExceededError(
                    f"template bindings exceed {MAX_PLUGIN_TEMPLATE_BINDINGS} items"
                )
            bindings = {}
            for name, value in raw_bindings.items():
                require_identifier(name, "template binding", None)
                bindings[name] = _text(value, f"template binding {name}", 2_000)
            draft = build_from_template(
                root,
                template,
                document_id,
                package_resolution=workspace.package_resolution,
                bindings=bindings,
            )
            path = draft.path
            if path.exists() or path in overlays:
                raise ProposalStaleError(
                    f"proposal create target already exists: {path.relative_to(root)}"
                )
            text = draft.source_text
            base_text = ""
            base_sha256 = None
            extra = {"template": template, "bindings": bindings}
        elif kind == "create-document":
            _reject_unknown(
                change,
                {"kind", "document_id", "text"},
                f"proposal change {index + 1}",
            )
            document_id = _text(change.get("document_id"), "document_id", 240)
            require_identifier(document_id, "document_id", None)
            path = _local_path(
                root,
                f"entries/{document_id}.kirin",
                must_exist=False,
            )
            if path.exists() or path in overlays:
                raise ProposalStaleError(
                    f"proposal create target already exists: {path.relative_to(root)}"
                )
            text = _candidate_text(change.get("text"))
            header = _ENTRY_HEADER_RE.search(text)
            if header is None or header.group(1) != document_id:
                raise ProposalInvalidError(
                    "create-document source must declare the requested @entry ID"
                )
            base_text = ""
            base_sha256 = None
            extra = {}
        elif kind == "replace-document":
            _reject_unknown(
                change,
                {"kind", "key", "base_sha256", "text"},
                f"proposal change {index + 1}",
            )
            path = _local_path(root, change.get("key"), must_exist=True)
            base_text = (
                overlays[path]
                if path in overlays
                else path.read_text(encoding="utf-8")
            )
            expected = change.get("base_sha256")
            if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
                raise InvalidRequestError(
                    "replace-document base_sha256 must be a SHA-256 digest"
                )
            base_sha256 = _source_hash(base_text)
            if expected != base_sha256:
                raise ProposalStaleError(
                    f"proposal baseline changed: {path.relative_to(root)}"
                )
            text = _candidate_text(change.get("text"))
            header = _ENTRY_HEADER_RE.search(text)
            document_id = header.group(1) if header else path.stem
            extra = {}
        else:
            raise InvalidRequestError(
                f"unsupported proposal change kind: {kind}"
            )

        if path in targets:
            raise ProposalInvalidError(
                f"proposal changes the same document more than once: {path.relative_to(root)}"
            )
        targets.add(path)
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_PLUGIN_PROPOSAL_BYTES:
            raise LimitExceededError(
                f"proposal candidates exceed {MAX_PLUGIN_PROPOSAL_BYTES} bytes"
            )
        candidates[path] = text
        normalized_changes.append(
            {
                "kind": kind,
                "key": path.relative_to(root).as_posix(),
                "path": path.relative_to(root).as_posix(),
                "document_id": document_id,
                "title": extract_author_title(text, document_id),
                "base_sha256": base_sha256,
                "base_text": base_text,
                "text": text,
                **extra,
            }
        )

    try:
        candidate_workspace = Workspace.load_with_overlays(
            root,
            candidates,
            package_resolution=workspace.package_resolution,
        )
        Engine(candidate_workspace).validate_all()
    except (ProposalInvalidError, ProposalStaleError, InvalidRequestError, LimitExceededError):
        raise
    except KTError as exc:
        raise ProposalInvalidError(str(exc), exc.location) from exc
    return {
        "status": "ok",
        "revision": current_revision,
        "title": title,
        "description": description,
        "total_bytes": total_bytes,
        "changes": normalized_changes,
    }
