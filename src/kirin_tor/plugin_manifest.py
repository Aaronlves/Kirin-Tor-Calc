"""Strict manifests and workspace records for sandboxed Workbench Plugins."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.9 CI job
    import tomli as tomllib  # type: ignore

from . import __version__
from .errors import PluginError, SourceLocation
from .limits import (
    MAX_PLUGIN_CONTRIBUTIONS,
    MAX_PLUGIN_EXTRACTED_BYTES,
    MAX_PLUGIN_FILES,
    MAX_PLUGIN_MANIFEST_BYTES,
    MAX_WORKSPACE_PLUGINS,
)
from .package_manifest import VERSION_RE


PLUGIN_MANIFEST = "kirin.plugin.json"
WORKSPACE_PLUGIN_REQUIREMENTS = "kirin.plugins.toml"
WORKSPACE_PLUGIN_LOCK = "kirin.plugins.lock"
PLUGIN_STORE = Path(".kirin") / "plugins"
PLUGIN_SCHEMA_VERSION = 1
PLUGIN_API_VERSION = "1"
PLUGIN_LOCK_VERSION = 1

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+$")
PLUGIN_ALIAS_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PLUGIN_PERMISSIONS = {
    "workspace.summary",
    "document.read",
    "source.navigate",
    "operation.evaluate",
}
COMMAND_ACTIONS = {"open-view", "open-tool", "activate-profile"}
FOCUS_MODES = {"editor", "split", "preview"}
BUILTIN_VIEW_IDS = {"documents", "graph"}
BUILTIN_TOOL_IDS = {"runs", "packages", "plugins", "syntax", "search", "changes"}


def _location(path: Path, field_name: Optional[str] = None) -> SourceLocation:
    return SourceLocation(path=str(path), field=field_name)


def _mapping(value: Any, label: str, path: Path) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PluginError(f"{label} must be an object", _location(path, label))
    return value


def _list(value: Any, label: str, path: Path) -> list:
    if not isinstance(value, list):
        raise PluginError(f"{label} must be an array", _location(path, label))
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: Iterable[str], label: str, path: Path
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise PluginError(
            f"unknown {label} field(s): {', '.join(unknown)}", _location(path, label)
        )


def _text(value: Any, label: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PluginError(f"{label} must be non-empty text", _location(path, label))
    return value.strip()


def _optional_text(value: Any, label: str, path: Path) -> Optional[str]:
    if value is None:
        return None
    return _text(value, label, path)


def _text_tuple(value: Any, label: str, path: Path) -> Tuple[str, ...]:
    raw = _list(value, label, path)
    if len(raw) > MAX_PLUGIN_CONTRIBUTIONS:
        raise PluginError(
            f"{label} exceeds {MAX_PLUGIN_CONTRIBUTIONS} items", _location(path, label)
        )
    result = tuple(_text(item, f"{label}.{index}", path) for index, item in enumerate(raw))
    if len(result) != len(set(result)):
        raise PluginError(f"{label} contains duplicate values", _location(path, label))
    return result


def _contribution_id(value: Any, plugin_id: str, label: str, path: Path) -> str:
    identifier = _text(value, label, path)
    if not PLUGIN_ID_RE.fullmatch(identifier) or not identifier.startswith(plugin_id + "."):
        raise PluginError(
            f"{label} must be a dotted id beginning with {plugin_id!r}",
            _location(path, label),
        )
    return identifier


def _entry_path(
    value: Any,
    label: str,
    root: Path,
    path: Path,
    *,
    check_exists: bool = True,
) -> str:
    entry = _text(value, label, path)
    if "\\" in entry:
        raise PluginError(f"{label} must use forward slashes", _location(path, label))
    pure = PurePosixPath(entry)
    if pure.is_absolute() or not pure.parts or pure.parts[0] != "web" or ".." in pure.parts:
        raise PluginError(f"{label} must stay under web/", _location(path, label))
    if pure.suffix.lower() != ".html":
        raise PluginError(f"{label} must identify an .html file", _location(path, label))
    if check_exists:
        candidate = root.joinpath(*pure.parts)
        if candidate.is_symlink() or not candidate.is_file():
            raise PluginError(f"{label} does not identify a regular file: {entry}", _location(path, label))
        try:
            candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise PluginError(f"{label} leaves the plugin root", _location(path, label)) from exc
    return pure.as_posix()


def _permissions(value: Any, label: str, path: Path) -> Tuple[str, ...]:
    result = _text_tuple(value, label, path)
    unknown = sorted(set(result) - PLUGIN_PERMISSIONS)
    if unknown:
        raise PluginError(
            f"unknown plugin permission(s): {', '.join(unknown)}", _location(path, label)
        )
    return result


@dataclass(frozen=True)
class RendererMatch:
    document_ids: Tuple[str, ...] = ()
    document_id_prefixes: Tuple[str, ...] = ()
    package_names: Tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {
            "document_ids": list(self.document_ids),
            "document_id_prefixes": list(self.document_id_prefixes),
            "package_names": list(self.package_names),
        }


@dataclass(frozen=True)
class SurfaceContribution:
    kind: str
    id: str
    title: str
    entry: str
    permissions: Tuple[str, ...] = ()
    priority: int = 0
    match: Optional[RendererMatch] = None
    description: Optional[str] = None

    def as_dict(self) -> dict:
        result = {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "entry": self.entry,
            "permissions": list(self.permissions),
        }
        if self.description is not None:
            result["description"] = self.description
        if self.kind == "renderer":
            result["priority"] = self.priority
            result["match"] = self.match.as_dict() if self.match else {}
        return result


@dataclass(frozen=True)
class CommandContribution:
    id: str
    title: str
    description: str
    action: str
    target: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "action": self.action,
            "target": self.target,
        }


@dataclass(frozen=True)
class ProfileContribution:
    id: str
    title: str
    description: str
    views: Tuple[str, ...]
    tools: Tuple[str, ...]
    default_view: str
    document_focus_mode: str

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "views": list(self.views),
            "tools": list(self.tools),
            "default_view": self.default_view,
            "document_focus_mode": self.document_focus_mode,
        }


@dataclass(frozen=True)
class PluginContributions:
    renderers: Tuple[SurfaceContribution, ...] = ()
    views: Tuple[SurfaceContribution, ...] = ()
    tools: Tuple[SurfaceContribution, ...] = ()
    commands: Tuple[CommandContribution, ...] = ()
    profiles: Tuple[ProfileContribution, ...] = ()

    def all_ids(self) -> Tuple[str, ...]:
        return tuple(
            item.id
            for group in (self.renderers, self.views, self.tools, self.commands, self.profiles)
            for item in group
        )

    def as_dict(self) -> dict:
        return {
            "renderers": [item.as_dict() for item in self.renderers],
            "views": [item.as_dict() for item in self.views],
            "tools": [item.as_dict() for item in self.tools],
            "commands": [item.as_dict() for item in self.commands],
            "profiles": [item.as_dict() for item in self.profiles],
        }


@dataclass(frozen=True)
class PluginManifest:
    root: Path = field(compare=False)
    id: str
    name: str
    version: str
    api: str
    description: str
    license: str
    contributes: PluginContributions

    @property
    def path(self) -> Path:
        return self.root / PLUGIN_MANIFEST

    def as_dict(self) -> dict:
        return {
            "schema": PLUGIN_SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "api": self.api,
            "description": self.description,
            "license": self.license,
            "contributes": self.contributes.as_dict(),
        }


def _surface(
    raw: Any,
    *,
    kind: str,
    plugin_id: str,
    root: Path,
    path: Path,
    index: int,
    check_entries: bool,
) -> SurfaceContribution:
    label = f"contributes.{kind}s.{index}"
    data = _mapping(raw, label, path)
    allowed = {"id", "title", "description", "entry", "permissions"}
    if kind == "renderer":
        allowed |= {"priority", "match"}
    _reject_unknown(data, allowed, label, path)
    identifier = _contribution_id(data.get("id"), plugin_id, f"{label}.id", path)
    title = _text(data.get("title"), f"{label}.title", path)
    description = _optional_text(data.get("description"), f"{label}.description", path)
    entry = _entry_path(
        data.get("entry"),
        f"{label}.entry",
        root,
        path,
        check_exists=check_entries,
    )
    permissions = _permissions(data.get("permissions", []), f"{label}.permissions", path)
    if kind != "renderer":
        return SurfaceContribution(kind, identifier, title, entry, permissions, description=description)
    priority = data.get("priority", 0)
    if not isinstance(priority, int) or isinstance(priority, bool) or priority < -1000 or priority > 1000:
        raise PluginError(f"{label}.priority must be an integer from -1000 to 1000", _location(path, label))
    match_data = _mapping(data.get("match"), f"{label}.match", path)
    _reject_unknown(
        match_data,
        {"document_ids", "document_id_prefixes", "package_names"},
        f"{label}.match",
        path,
    )
    match = RendererMatch(
        _text_tuple(match_data.get("document_ids", []), f"{label}.match.document_ids", path),
        _text_tuple(
            match_data.get("document_id_prefixes", []),
            f"{label}.match.document_id_prefixes",
            path,
        ),
        _text_tuple(match_data.get("package_names", []), f"{label}.match.package_names", path),
    )
    if not (match.document_ids or match.document_id_prefixes or match.package_names):
        raise PluginError(f"{label}.match must declare at least one selector", _location(path, label))
    return SurfaceContribution(
        kind, identifier, title, entry, permissions, priority, match, description
    )


def _command(raw: Any, plugin_id: str, path: Path, index: int) -> CommandContribution:
    label = f"contributes.commands.{index}"
    data = _mapping(raw, label, path)
    _reject_unknown(data, {"id", "title", "description", "action", "target"}, label, path)
    action = _text(data.get("action"), f"{label}.action", path)
    if action not in COMMAND_ACTIONS:
        raise PluginError(f"{label}.action is not supported: {action}", _location(path, label))
    target = _text(data.get("target"), f"{label}.target", path)
    return CommandContribution(
        _contribution_id(data.get("id"), plugin_id, f"{label}.id", path),
        _text(data.get("title"), f"{label}.title", path),
        _text(data.get("description"), f"{label}.description", path),
        action,
        target,
    )


def _profile(raw: Any, plugin_id: str, path: Path, index: int) -> ProfileContribution:
    label = f"contributes.profiles.{index}"
    data = _mapping(raw, label, path)
    _reject_unknown(
        data,
        {
            "id",
            "title",
            "description",
            "views",
            "tools",
            "default_view",
            "document_focus_mode",
        },
        label,
        path,
    )
    views = _text_tuple(data.get("views"), f"{label}.views", path)
    tools = _text_tuple(data.get("tools", []), f"{label}.tools", path)
    if not views:
        raise PluginError(f"{label}.views must not be empty", _location(path, label))
    default_view = _text(data.get("default_view"), f"{label}.default_view", path)
    if default_view not in views:
        raise PluginError(f"{label}.default_view must appear in views", _location(path, label))
    focus = _text(data.get("document_focus_mode"), f"{label}.document_focus_mode", path)
    if focus not in FOCUS_MODES:
        raise PluginError(f"{label}.document_focus_mode is invalid", _location(path, label))
    return ProfileContribution(
        _contribution_id(data.get("id"), plugin_id, f"{label}.id", path),
        _text(data.get("title"), f"{label}.title", path),
        _text(data.get("description"), f"{label}.description", path),
        views,
        tools,
        default_view,
        focus,
    )


def load_plugin_manifest(root: Path, *, check_entries: bool = True) -> PluginManifest:
    root = root.expanduser().resolve()
    path = root / PLUGIN_MANIFEST
    if path.is_symlink() or not path.is_file():
        raise PluginError(f"plugin manifest not found: {path}", _location(path))
    if path.stat().st_size > MAX_PLUGIN_MANIFEST_BYTES:
        raise PluginError(f"plugin manifest exceeds {MAX_PLUGIN_MANIFEST_BYTES} bytes", _location(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginError(f"invalid {PLUGIN_MANIFEST}: {exc}", _location(path)) from exc
    data = _mapping(raw, "plugin manifest", path)
    _reject_unknown(
        data,
        {"schema", "id", "name", "version", "api", "description", "license", "contributes"},
        "plugin manifest",
        path,
    )
    if data.get("schema") != PLUGIN_SCHEMA_VERSION:
        raise PluginError(f"plugin schema must be {PLUGIN_SCHEMA_VERSION}", _location(path, "schema"))
    plugin_id = _text(data.get("id"), "id", path)
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        raise PluginError("plugin id must be a dotted lower-case id", _location(path, "id"))
    version = _text(data.get("version"), "version", path)
    if not VERSION_RE.fullmatch(version):
        raise PluginError("plugin version must use exact MAJOR.MINOR.PATCH", _location(path, "version"))
    api = _text(data.get("api"), "api", path)
    if api != PLUGIN_API_VERSION:
        raise PluginError(f"plugin api must be {PLUGIN_API_VERSION!r}", _location(path, "api"))
    contribution_data = _mapping(data.get("contributes"), "contributes", path)
    _reject_unknown(
        contribution_data,
        {"renderers", "views", "tools", "commands", "profiles"},
        "contributes",
        path,
    )
    raw_groups = {
        key: _list(contribution_data.get(key, []), f"contributes.{key}", path)
        for key in ("renderers", "views", "tools", "commands", "profiles")
    }
    total = sum(len(group) for group in raw_groups.values())
    if total == 0:
        raise PluginError("plugin must contribute at least one surface or command", _location(path))
    if total > MAX_PLUGIN_CONTRIBUTIONS:
        raise PluginError(f"plugin exceeds {MAX_PLUGIN_CONTRIBUTIONS} contributions", _location(path))
    contributions = PluginContributions(
        renderers=tuple(
            _surface(
                item,
                kind="renderer",
                plugin_id=plugin_id,
                root=root,
                path=path,
                index=index,
                check_entries=check_entries,
            )
            for index, item in enumerate(raw_groups["renderers"])
        ),
        views=tuple(
            _surface(
                item,
                kind="view",
                plugin_id=plugin_id,
                root=root,
                path=path,
                index=index,
                check_entries=check_entries,
            )
            for index, item in enumerate(raw_groups["views"])
        ),
        tools=tuple(
            _surface(
                item,
                kind="tool",
                plugin_id=plugin_id,
                root=root,
                path=path,
                index=index,
                check_entries=check_entries,
            )
            for index, item in enumerate(raw_groups["tools"])
        ),
        commands=tuple(
            _command(item, plugin_id, path, index)
            for index, item in enumerate(raw_groups["commands"])
        ),
        profiles=tuple(
            _profile(item, plugin_id, path, index)
            for index, item in enumerate(raw_groups["profiles"])
        ),
    )
    identifiers = contributions.all_ids()
    if len(identifiers) != len(set(identifiers)):
        raise PluginError("plugin contribution ids must be unique", _location(path))
    known_views = BUILTIN_VIEW_IDS | {item.id for item in contributions.views}
    known_tools = BUILTIN_TOOL_IDS | {item.id for item in contributions.tools}
    known_profiles = {item.id for item in contributions.profiles}
    for command in contributions.commands:
        known = {
            "open-view": known_views,
            "open-tool": known_tools,
            "activate-profile": known_profiles,
        }[command.action]
        if command.target not in known:
            raise PluginError(
                f"command {command.id!r} targets unknown {command.action} id {command.target!r}",
                _location(path, command.id),
            )
    for profile in contributions.profiles:
        unknown_views = sorted(set(profile.views) - known_views)
        unknown_tools = sorted(set(profile.tools) - known_tools)
        if unknown_views or unknown_tools:
            detail = ", ".join((*unknown_views, *unknown_tools))
            raise PluginError(f"profile {profile.id!r} references unknown ids: {detail}", _location(path, profile.id))
    return PluginManifest(
        root,
        plugin_id,
        _text(data.get("name"), "name", path),
        version,
        api,
        _text(data.get("description"), "description", path),
        _text(data.get("license"), "license", path),
        contributions,
    )


def plugin_content_paths(root: Path) -> Tuple[Path, ...]:
    root = root.expanduser().resolve()
    if root.is_symlink() or not root.is_dir():
        raise PluginError(f"plugin root must be a real directory: {root}", _location(root))
    result = []
    total_bytes = 0
    for current, directory_names, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory_name in list(directory_names):
            candidate = current_path / directory_name
            if candidate.is_symlink():
                raise PluginError("plugin directories may not be symbolic links", _location(candidate))
        for filename in filenames:
            path = current_path / filename
            if path.is_symlink() or not path.is_file():
                raise PluginError("plugin content must use regular files", _location(path))
            try:
                stat = path.stat()
                path.resolve().relative_to(root)
            except (OSError, ValueError) as exc:
                raise PluginError("plugin content leaves its root", _location(path)) from exc
            if stat.st_nlink != 1:
                raise PluginError("plugin content must not use hard links", _location(path))
            total_bytes += stat.st_size
            if total_bytes > MAX_PLUGIN_EXTRACTED_BYTES:
                raise PluginError(
                    f"plugin content exceeds {MAX_PLUGIN_EXTRACTED_BYTES} bytes", _location(root)
                )
            result.append(path)
            if len(result) > MAX_PLUGIN_FILES:
                raise PluginError(f"plugin exceeds {MAX_PLUGIN_FILES} files", _location(root))
    manifest = root / PLUGIN_MANIFEST
    if manifest not in result:
        raise PluginError(f"plugin manifest not found: {manifest}", _location(manifest))
    return tuple(sorted(result, key=lambda item: item.relative_to(root).as_posix()))


def canonical_plugin_sha256(root: Path) -> str:
    root = root.expanduser().resolve()
    load_plugin_manifest(root)
    digest = hashlib.sha256()
    for path in plugin_content_paths(root):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def normalize_plugin_source(source: str, *, relative_to: Path) -> str:
    source = source.strip()
    if not source.startswith("path:"):
        raise PluginError("plugin source must use path:PATH in protocol v1")
    raw_path = source[5:]
    if not raw_path:
        raise PluginError("plugin path source may not be empty")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = relative_to / candidate
    return "path:" + str(candidate.resolve())


@dataclass(frozen=True)
class PluginRequirement:
    alias: str
    source: str
    version: str
    enabled: bool = True

    def as_dict(self) -> dict:
        return {"source": self.source, "version": self.version, "enabled": self.enabled}


@dataclass(frozen=True)
class PluginRequirements:
    root: Path = field(compare=False)
    plugins: Tuple[PluginRequirement, ...] = ()

    @property
    def path(self) -> Path:
        return self.root / WORKSPACE_PLUGIN_REQUIREMENTS

    def by_alias(self) -> Dict[str, PluginRequirement]:
        return {item.alias: item for item in self.plugins}


@dataclass(frozen=True)
class LockedPlugin:
    alias: str
    source: str
    id: str
    name: str
    version: str
    content_sha256: str

    def as_dict(self) -> dict:
        return {
            "alias": self.alias,
            "source": self.source,
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class PluginLock:
    root: Path = field(compare=False)
    plugins: Tuple[LockedPlugin, ...] = ()

    @property
    def path(self) -> Path:
        return self.root / WORKSPACE_PLUGIN_LOCK

    def by_alias(self) -> Dict[str, LockedPlugin]:
        return {item.alias: item for item in self.plugins}

    def as_dict(self) -> dict:
        return {
            "lock_version": PLUGIN_LOCK_VERSION,
            "generated_by": f"kirin-tor-cli {__version__}",
            "plugins": [item.as_dict() for item in sorted(self.plugins, key=lambda item: item.alias)],
        }


def _read_toml(path: Path) -> Mapping[str, Any]:
    if path.stat().st_size > MAX_PLUGIN_MANIFEST_BYTES:
        raise PluginError(f"{path.name} is too large", _location(path))
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise PluginError(f"invalid {path.name}: {exc}", _location(path)) from exc
    return _mapping(raw, path.name, path)


def load_plugin_requirements(root: Path) -> PluginRequirements:
    root = root.expanduser().resolve()
    path = root / WORKSPACE_PLUGIN_REQUIREMENTS
    if not path.exists():
        return PluginRequirements(root)
    raw = _read_toml(path)
    _reject_unknown(raw, {"schema", "plugins"}, "plugin requirements", path)
    if raw.get("schema") != PLUGIN_SCHEMA_VERSION:
        raise PluginError(f"plugin requirements schema must be {PLUGIN_SCHEMA_VERSION}", _location(path))
    table = _mapping(raw.get("plugins", {}), "plugins", path)
    if len(table) > MAX_WORKSPACE_PLUGINS:
        raise PluginError(f"workspace exceeds {MAX_WORKSPACE_PLUGINS} plugins", _location(path))
    plugins = []
    for alias, untyped in sorted(table.items()):
        if not PLUGIN_ALIAS_RE.fullmatch(alias):
            raise PluginError(f"plugin alias {alias!r} must match [a-z][a-z0-9_]*", _location(path))
        data = _mapping(untyped, f"plugins.{alias}", path)
        _reject_unknown(data, {"source", "version", "enabled"}, f"plugins.{alias}", path)
        source = normalize_plugin_source(_text(data.get("source"), "source", path), relative_to=root)
        version = _text(data.get("version"), "version", path)
        if not VERSION_RE.fullmatch(version):
            raise PluginError("plugin version must use exact MAJOR.MINOR.PATCH", _location(path))
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            raise PluginError("plugin enabled state must be boolean", _location(path))
        plugins.append(PluginRequirement(alias, source, version, enabled))
    sources = [item.source for item in plugins]
    if len(sources) != len(set(sources)):
        raise PluginError("one plugin source may not be requested under multiple aliases", _location(path))
    return PluginRequirements(root, tuple(plugins))


def load_plugin_lock(root: Path, *, required: bool = False) -> PluginLock:
    root = root.expanduser().resolve()
    path = root / WORKSPACE_PLUGIN_LOCK
    if not path.exists():
        if required:
            raise PluginError(f"{WORKSPACE_PLUGIN_LOCK} is missing; reinstall the requested plugins", _location(path))
        return PluginLock(root)
    if path.stat().st_size > MAX_PLUGIN_MANIFEST_BYTES * 4:
        raise PluginError(f"{WORKSPACE_PLUGIN_LOCK} is too large", _location(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginError(f"invalid {WORKSPACE_PLUGIN_LOCK}: {exc}", _location(path)) from exc
    data = _mapping(raw, WORKSPACE_PLUGIN_LOCK, path)
    _reject_unknown(data, {"lock_version", "generated_by", "plugins"}, "plugin lock", path)
    if data.get("lock_version") != PLUGIN_LOCK_VERSION:
        raise PluginError(f"plugin lock_version must be {PLUGIN_LOCK_VERSION}", _location(path))
    if not isinstance(data.get("generated_by"), str):
        raise PluginError("plugin lock generated_by must be text", _location(path))
    raw_plugins = _list(data.get("plugins"), "plugins", path)
    if len(raw_plugins) > MAX_WORKSPACE_PLUGINS:
        raise PluginError(f"plugin lock exceeds {MAX_WORKSPACE_PLUGINS} plugins", _location(path))
    plugins = []
    for index, untyped in enumerate(raw_plugins):
        item = _mapping(untyped, f"plugins.{index}", path)
        _reject_unknown(
            item,
            {"alias", "source", "id", "name", "version", "content_sha256"},
            f"plugins.{index}",
            path,
        )
        alias = _text(item.get("alias"), "alias", path)
        plugin_id = _text(item.get("id"), "id", path)
        version = _text(item.get("version"), "version", path)
        digest = _text(item.get("content_sha256"), "content_sha256", path)
        if not PLUGIN_ALIAS_RE.fullmatch(alias) or not PLUGIN_ID_RE.fullmatch(plugin_id):
            raise PluginError(f"invalid plugin identity at lock index {index}", _location(path))
        if not VERSION_RE.fullmatch(version) or not SHA256_RE.fullmatch(digest):
            raise PluginError(f"invalid plugin version or digest at lock index {index}", _location(path))
        plugins.append(
            LockedPlugin(
                alias,
                normalize_plugin_source(_text(item.get("source"), "source", path), relative_to=root),
                plugin_id,
                _text(item.get("name"), "name", path),
                version,
                digest,
            )
        )
    aliases = [item.alias for item in plugins]
    ids = [item.id for item in plugins]
    if len(aliases) != len(set(aliases)) or len(ids) != len(set(ids)):
        raise PluginError("plugin lock contains duplicate aliases or plugin ids", _location(path))
    return PluginLock(root, tuple(plugins))


def render_plugin_requirements(requirements: PluginRequirements) -> str:
    lines = [f"schema = {PLUGIN_SCHEMA_VERSION}"]
    for item in sorted(requirements.plugins, key=lambda plugin: plugin.alias):
        lines.extend(
            [
                "",
                f"[plugins.{item.alias}]",
                f"source = {json.dumps(item.source, ensure_ascii=False)}",
                f"version = {json.dumps(item.version, ensure_ascii=False)}",
                f"enabled = {'true' if item.enabled else 'false'}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_plugin_lock(lock: PluginLock) -> str:
    return json.dumps(lock.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
