"""Strict, data-only manifests and lockfiles for community packages."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

try:  # Python 3.11+
    import tomllib  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.9 CI job
    import tomli as tomllib  # type: ignore

from . import __version__
from .errors import PackageError, SourceLocation
from .limits import (
    MAX_PACKAGE_EXTRACTED_BYTES,
    MAX_PACKAGE_DEPENDENCIES,
    MAX_PACKAGE_GRAPH_PACKAGES,
    MAX_PACKAGE_MANIFEST_BYTES,
    MAX_WORKSPACE_DOCUMENTS,
)


PACKAGE_MANIFEST = "kirin.package.toml"
WORKSPACE_REQUIREMENTS = "kirin.packages.toml"
WORKSPACE_LOCK = "kirin.lock"
PACKAGE_STORE = Path(".kirin") / "packages"
PACKAGE_SCHEMA_VERSION = 1
LOCK_VERSION = 1

PACKAGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)*$")
NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
FEATURE_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
GITHUB_RE = re.compile(
    r"^github:(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<repo>[A-Za-z0-9_.-]+)$"
)


def _location(path: Path, field_name: Optional[str] = None) -> SourceLocation:
    return SourceLocation(path=str(path), field=field_name)


def _require_mapping(value: Any, label: str, path: Path) -> Mapping[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PackageError(f"{label} must be a TOML table", _location(path, label))
    return value


def _reject_unknown(
    value: Mapping[str, Any], allowed: Iterable[str], label: str, path: Path
) -> None:
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise PackageError(
            f"unknown {label} field(s): {', '.join(unknown)}", _location(path, label)
        )


def _require_text(value: Any, label: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackageError(f"{label} must be non-empty text", _location(path, label))
    return value.strip()


def _read_toml(path: Path) -> Mapping[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PackageError(f"cannot read {path.name}: {exc}", _location(path)) from exc
    if size > MAX_PACKAGE_MANIFEST_BYTES:
        raise PackageError(
            f"{path.name} exceeds {MAX_PACKAGE_MANIFEST_BYTES} bytes", _location(path)
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PackageError(f"{path.name} must be readable UTF-8: {exc}", _location(path)) from exc
    try:
        value = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PackageError(f"invalid TOML: {exc}", _location(path)) from exc
    return _require_mapping(value, path.name, path)


def current_feature_line() -> str:
    match = re.match(r"^(\d+)\.(\d+)", __version__)
    if match is None:  # pragma: no cover - guarded by project version tests
        raise PackageError(f"installed Kirin version {__version__!r} has no feature line")
    return f"{match.group(1)}.{match.group(2)}"


def normalize_source(source: str, *, relative_to: Optional[Path] = None) -> str:
    source = source.strip()
    match = GITHUB_RE.fullmatch(source)
    if match:
        owner = match.group("owner").lower()
        repository = match.group("repo").removesuffix(".git").lower()
        if not repository:
            raise PackageError("GitHub repository name may not be empty")
        return f"github:{owner}/{repository}"
    if source.startswith("path:"):
        raw_path = source[5:]
        if not raw_path:
            raise PackageError("path package source may not be empty")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            if relative_to is None:
                raise PackageError("relative path package source requires a base directory")
            candidate = relative_to / candidate
        return "path:" + str(candidate.resolve())
    raise PackageError("package source must use github:OWNER/REPO or path:PATH")


def source_kind(source: str) -> str:
    if source.startswith("github:"):
        return "github"
    if source.startswith("path:"):
        return "path"
    raise PackageError(f"unsupported normalized package source {source!r}")


@dataclass(frozen=True)
class PackageDependency:
    alias: str
    source: str
    version: str

    def as_dict(self) -> dict:
        return {"source": self.source, "version": self.version}


@dataclass(frozen=True)
class PackageManifest:
    root: Path = field(compare=False)
    name: str
    version: str
    namespace: str
    description: str
    license: str
    requires_kirin: str
    game: Optional[str] = None
    game_version: Optional[str] = None
    dependencies: Tuple[PackageDependency, ...] = ()

    @property
    def path(self) -> Path:
        return self.root / PACKAGE_MANIFEST


@dataclass(frozen=True)
class WorkspaceRequirement:
    alias: str
    source: str
    version: str

    def as_dict(self) -> dict:
        return {"source": self.source, "version": self.version}


@dataclass(frozen=True)
class WorkspaceRequirements:
    root: Path = field(compare=False)
    packages: Tuple[WorkspaceRequirement, ...] = ()

    @property
    def path(self) -> Path:
        return self.root / WORKSPACE_REQUIREMENTS

    def by_alias(self) -> Dict[str, WorkspaceRequirement]:
        return {item.alias: item for item in self.packages}


@dataclass(frozen=True)
class LockedPackage:
    source: str
    name: str
    version: str
    namespace: str
    resolved: str
    content_sha256: str
    dependencies: Tuple[PackageDependency, ...] = ()

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "name": self.name,
            "version": self.version,
            "namespace": self.namespace,
            "resolved": self.resolved,
            "content_sha256": self.content_sha256,
            "dependencies": {
                item.alias: item.as_dict() for item in sorted(self.dependencies, key=lambda dep: dep.alias)
            },
        }


@dataclass(frozen=True)
class PackageLock:
    root: Path = field(compare=False)
    direct: Tuple[WorkspaceRequirement, ...] = ()
    packages: Tuple[LockedPackage, ...] = ()

    @property
    def path(self) -> Path:
        return self.root / WORKSPACE_LOCK

    def by_source(self) -> Dict[str, LockedPackage]:
        return {item.source: item for item in self.packages}

    def as_dict(self) -> dict:
        return {
            "lock_version": LOCK_VERSION,
            "generated_by": f"kirin-tor-cli {__version__}",
            "direct": {
                item.alias: item.as_dict() for item in sorted(self.direct, key=lambda req: req.alias)
            },
            "packages": [
                item.as_dict() for item in sorted(self.packages, key=lambda package: package.source)
            ],
        }


def _parse_dependency_table(
    raw: Any, path: Path, *, relative_to: Path
) -> Tuple[PackageDependency, ...]:
    table = _require_mapping(raw, "dependencies", path)
    if len(table) > MAX_PACKAGE_DEPENDENCIES:
        raise PackageError(
            f"package exceeds {MAX_PACKAGE_DEPENDENCIES} direct dependencies", _location(path)
        )
    result = []
    for alias, untyped in sorted(table.items()):
        if not NAMESPACE_RE.fullmatch(alias):
            raise PackageError(
                f"dependency alias {alias!r} must match [a-z][a-z0-9_]*",
                _location(path, f"dependencies.{alias}"),
            )
        data = _require_mapping(untyped, f"dependencies.{alias}", path)
        _reject_unknown(data, {"source", "version"}, f"dependencies.{alias}", path)
        source_text = _require_text(data.get("source"), f"dependencies.{alias}.source", path)
        if source_text.startswith("path:") and not Path(source_text[5:]).expanduser().is_absolute():
            raise PackageError(
                "package manifest path dependencies must use absolute development paths",
                _location(path, f"dependencies.{alias}.source"),
            )
        source = normalize_source(source_text, relative_to=relative_to)
        version = _require_text(data.get("version"), f"dependencies.{alias}.version", path)
        if not VERSION_RE.fullmatch(version):
            raise PackageError(
                f"dependency version {version!r} must use exact MAJOR.MINOR.PATCH",
                _location(path, f"dependencies.{alias}.version"),
            )
        result.append(PackageDependency(alias, source, version))
    sources = [item.source for item in result]
    if len(sources) != len(set(sources)):
        raise PackageError("one package source may not be imported under multiple dependency aliases", _location(path))
    return tuple(result)


def load_package_manifest(root: Path, *, check_compatibility: bool = True) -> PackageManifest:
    root = root.expanduser().resolve()
    path = root / PACKAGE_MANIFEST
    if not path.is_file():
        raise PackageError(f"package manifest not found: {path}", _location(path))
    raw = _read_toml(path)
    allowed = {
        "schema",
        "name",
        "version",
        "namespace",
        "description",
        "license",
        "requires_kirin",
        "game",
        "game_version",
        "dependencies",
    }
    _reject_unknown(raw, allowed, "package manifest", path)
    if raw.get("schema") != PACKAGE_SCHEMA_VERSION:
        raise PackageError(
            f"package schema must be {PACKAGE_SCHEMA_VERSION}", _location(path, "schema")
        )
    name = _require_text(raw.get("name"), "name", path)
    if not PACKAGE_NAME_RE.fullmatch(name):
        raise PackageError(
            "name must be a dotted lower-case package name", _location(path, "name")
        )
    version = _require_text(raw.get("version"), "version", path)
    if not VERSION_RE.fullmatch(version):
        raise PackageError(
            "version must use exact MAJOR.MINOR.PATCH", _location(path, "version")
        )
    namespace = _require_text(raw.get("namespace"), "namespace", path)
    if not NAMESPACE_RE.fullmatch(namespace):
        raise PackageError(
            "namespace must match [a-z][a-z0-9_]*", _location(path, "namespace")
        )
    description = _require_text(raw.get("description"), "description", path)
    license_name = _require_text(raw.get("license"), "license", path)
    requires_kirin = _require_text(raw.get("requires_kirin"), "requires_kirin", path)
    if not FEATURE_RE.fullmatch(requires_kirin):
        raise PackageError(
            "requires_kirin must use exact MAJOR.MINOR", _location(path, "requires_kirin")
        )
    if check_compatibility and requires_kirin != current_feature_line():
        raise PackageError(
            f"package requires Kirin {requires_kirin}, installed feature line is {current_feature_line()}",
            _location(path, "requires_kirin"),
        )
    game = raw.get("game")
    if game is not None:
        game = _require_text(game, "game", path)
    game_version = raw.get("game_version")
    if game_version is not None:
        game_version = _require_text(game_version, "game_version", path)
    dependencies = _parse_dependency_table(
        raw.get("dependencies", {}), path, relative_to=root
    )
    return PackageManifest(
        root=root,
        name=name,
        version=version,
        namespace=namespace,
        description=description,
        license=license_name,
        requires_kirin=requires_kirin,
        game=game,
        game_version=game_version,
        dependencies=dependencies,
    )


def load_workspace_requirements(root: Path) -> WorkspaceRequirements:
    root = root.expanduser().resolve()
    path = root / WORKSPACE_REQUIREMENTS
    if not path.exists():
        return WorkspaceRequirements(root)
    raw = _read_toml(path)
    _reject_unknown(raw, {"schema", "packages"}, "workspace package requirements", path)
    if raw.get("schema") != PACKAGE_SCHEMA_VERSION:
        raise PackageError(
            f"workspace package schema must be {PACKAGE_SCHEMA_VERSION}",
            _location(path, "schema"),
        )
    table = _require_mapping(raw.get("packages", {}), "packages", path)
    if len(table) > MAX_PACKAGE_DEPENDENCIES:
        raise PackageError(
            f"workspace exceeds {MAX_PACKAGE_DEPENDENCIES} direct packages", _location(path)
        )
    result = []
    for alias, untyped in sorted(table.items()):
        if not NAMESPACE_RE.fullmatch(alias):
            raise PackageError(
                f"package alias {alias!r} must match [a-z][a-z0-9_]*",
                _location(path, f"packages.{alias}"),
            )
        data = _require_mapping(untyped, f"packages.{alias}", path)
        _reject_unknown(data, {"source", "version"}, f"packages.{alias}", path)
        source = normalize_source(
            _require_text(data.get("source"), f"packages.{alias}.source", path),
            relative_to=root,
        )
        version = _require_text(data.get("version"), f"packages.{alias}.version", path)
        if not VERSION_RE.fullmatch(version):
            raise PackageError(
                "workspace package version must use exact MAJOR.MINOR.PATCH",
                _location(path, f"packages.{alias}.version"),
            )
        result.append(WorkspaceRequirement(alias, source, version))
    sources = [item.source for item in result]
    if len(sources) != len(set(sources)):
        raise PackageError("one package source may not be requested under multiple aliases", _location(path))
    return WorkspaceRequirements(root, tuple(result))


def _lock_dependency(alias: str, raw: Any, path: Path) -> PackageDependency:
    if not NAMESPACE_RE.fullmatch(alias):
        raise PackageError(f"invalid locked dependency alias {alias!r}", _location(path))
    data = _require_mapping(raw, f"dependencies.{alias}", path)
    _reject_unknown(data, {"source", "version"}, f"dependencies.{alias}", path)
    source = normalize_source(_require_text(data.get("source"), "source", path), relative_to=path.parent)
    version = _require_text(data.get("version"), "version", path)
    if not VERSION_RE.fullmatch(version):
        raise PackageError("locked dependency version is invalid", _location(path))
    return PackageDependency(alias, source, version)


def load_package_lock(root: Path, *, required: bool = False) -> PackageLock:
    root = root.expanduser().resolve()
    path = root / WORKSPACE_LOCK
    if not path.exists():
        if required:
            raise PackageError(
                f"{WORKSPACE_LOCK} is missing; run 'kt package restore'", _location(path)
            )
        return PackageLock(root)
    if path.stat().st_size > MAX_PACKAGE_MANIFEST_BYTES * 10:
        raise PackageError(f"{WORKSPACE_LOCK} is too large", _location(path))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError(f"invalid {WORKSPACE_LOCK}: {exc}", _location(path)) from exc
    raw = _require_mapping(raw, WORKSPACE_LOCK, path)
    _reject_unknown(raw, {"lock_version", "generated_by", "direct", "packages"}, "lockfile", path)
    if raw.get("lock_version") != LOCK_VERSION:
        raise PackageError(f"lock_version must be {LOCK_VERSION}", _location(path, "lock_version"))
    if not isinstance(raw.get("generated_by"), str):
        raise PackageError("lockfile generated_by must be text", _location(path, "generated_by"))
    direct_table = _require_mapping(raw.get("direct", {}), "direct", path)
    direct = []
    for alias, untyped in sorted(direct_table.items()):
        if not NAMESPACE_RE.fullmatch(alias):
            raise PackageError(f"invalid locked direct alias {alias!r}", _location(path))
        dep = _lock_dependency(alias, untyped, path)
        direct.append(WorkspaceRequirement(alias, dep.source, dep.version))
    packages_raw = raw.get("packages", [])
    if not isinstance(packages_raw, list):
        raise PackageError("lockfile packages must be a list", _location(path, "packages"))
    if len(packages_raw) > MAX_PACKAGE_GRAPH_PACKAGES:
        raise PackageError(
            f"lockfile exceeds {MAX_PACKAGE_GRAPH_PACKAGES} packages", _location(path, "packages")
        )
    packages = []
    for index, untyped in enumerate(packages_raw):
        data = _require_mapping(untyped, f"packages.{index}", path)
        _reject_unknown(
            data,
            {"source", "name", "version", "namespace", "resolved", "content_sha256", "dependencies"},
            f"packages.{index}",
            path,
        )
        source = normalize_source(_require_text(data.get("source"), "source", path), relative_to=root)
        name = _require_text(data.get("name"), "name", path)
        version = _require_text(data.get("version"), "version", path)
        namespace = _require_text(data.get("namespace"), "namespace", path)
        resolved = _require_text(data.get("resolved"), "resolved", path)
        digest = _require_text(data.get("content_sha256"), "content_sha256", path)
        if not PACKAGE_NAME_RE.fullmatch(name) or not VERSION_RE.fullmatch(version):
            raise PackageError(f"invalid package identity at lock index {index}", _location(path))
        if not NAMESPACE_RE.fullmatch(namespace):
            raise PackageError(f"invalid namespace at lock index {index}", _location(path))
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PackageError(f"invalid content SHA-256 at lock index {index}", _location(path))
        if source_kind(source) == "github" and not re.fullmatch(r"[0-9a-f]{40}", resolved):
            raise PackageError(f"invalid GitHub commit at lock index {index}", _location(path))
        if source_kind(source) == "path" and not Path(resolved).is_absolute():
            raise PackageError(f"locked local source path must be absolute at index {index}", _location(path))
        dependencies_table = _require_mapping(data.get("dependencies", {}), "dependencies", path)
        dependencies = tuple(
            _lock_dependency(alias, value, path)
            for alias, value in sorted(dependencies_table.items())
        )
        packages.append(
            LockedPackage(source, name, version, namespace, resolved, digest, dependencies)
        )
    package_sources = [item.source for item in packages]
    if len(package_sources) != len(set(package_sources)):
        raise PackageError("lockfile contains duplicate package sources", _location(path))
    namespaces = [item.namespace for item in packages]
    if len(namespaces) != len(set(namespaces)):
        raise PackageError("lockfile contains duplicate package namespaces", _location(path))
    direct_sources = [item.source for item in direct]
    if len(direct_sources) != len(set(direct_sources)):
        raise PackageError("lockfile contains duplicate direct package sources", _location(path))
    locked_by_source = {item.source: item for item in packages}
    for item in direct:
        target = locked_by_source.get(item.source)
        if target is None or target.version != item.version:
            raise PackageError(f"direct package {item.alias!r} is not satisfied by lockfile", _location(path))
    for package in packages:
        for dependency in package.dependencies:
            target = locked_by_source.get(dependency.source)
            if target is None or target.version != dependency.version:
                raise PackageError(
                    f"dependency {package.name}:{dependency.alias} is not satisfied by lockfile",
                    _location(path),
                )
    return PackageLock(root, tuple(direct), tuple(packages))


def package_source_paths(root: Path) -> Tuple[Path, ...]:
    root = root.resolve()
    result = []
    total_bytes = 0
    for folder_name in ("entries",):
        folder = root / folder_name
        if not folder.exists():
            continue
        if folder.is_symlink() or not folder.is_dir():
            raise PackageError(f"package {folder_name}/ must be a real directory", _location(folder))
        for current, directory_names, filenames in os.walk(folder, followlinks=False):
            current_path = Path(current)
            for directory_name in list(directory_names):
                candidate = current_path / directory_name
                if candidate.is_symlink():
                    raise PackageError("package source directories may not be symbolic links", _location(candidate))
            for filename in filenames:
                path = current_path / filename
                if path.suffix.lower() != ".kirin":
                    continue
                if path.is_symlink() or not path.is_file():
                    raise PackageError("package Kirin sources must be regular files", _location(path))
                try:
                    path.resolve().relative_to(root)
                except ValueError as exc:
                    raise PackageError("package source leaves its root", _location(path)) from exc
                total_bytes += path.stat().st_size
                if total_bytes > MAX_PACKAGE_EXTRACTED_BYTES:
                    raise PackageError(
                        f"package sources exceed {MAX_PACKAGE_EXTRACTED_BYTES} bytes", _location(root)
                    )
                result.append(path)
                if len(result) > MAX_WORKSPACE_DOCUMENTS:
                    raise PackageError(
                        f"package exceeds {MAX_WORKSPACE_DOCUMENTS} Kirin documents", _location(root)
                    )
    if not result:
        raise PackageError("package must contain at least one .kirin source under entries/", _location(root))
    return tuple(sorted(result, key=lambda path: path.relative_to(root).as_posix()))


def package_template_paths(root: Path) -> Tuple[Path, ...]:
    """Return static creation templates shipped as authoritative Package data."""
    root = root.resolve()
    result = []
    total_bytes = 0
    base = root / "templates"
    if not base.exists():
        return ()
    if base.is_symlink() or not base.is_dir():
        raise PackageError("package templates/ must be a real directory", _location(base))
    for folder_name in ("entries",):
        folder = base / folder_name
        if not folder.exists():
            continue
        if folder.is_symlink() or not folder.is_dir():
            raise PackageError(
                f"package templates/{folder_name}/ must be a real directory",
                _location(folder),
            )
        for current, directory_names, filenames in os.walk(folder, followlinks=False):
            current_path = Path(current)
            for directory_name in list(directory_names):
                candidate = current_path / directory_name
                if candidate.is_symlink():
                    raise PackageError(
                        "package template directories may not be symbolic links",
                        _location(candidate),
                    )
            for filename in filenames:
                path = current_path / filename
                if path.suffix.lower() != ".kirin":
                    continue
                if path.is_symlink() or not path.is_file():
                    raise PackageError(
                        "package templates must be regular files", _location(path)
                    )
                try:
                    path.resolve().relative_to(root)
                except ValueError as exc:
                    raise PackageError("package template leaves its root", _location(path)) from exc
                total_bytes += path.stat().st_size
                if total_bytes > MAX_PACKAGE_EXTRACTED_BYTES:
                    raise PackageError(
                        f"package templates exceed {MAX_PACKAGE_EXTRACTED_BYTES} bytes",
                        _location(root),
                    )
                result.append(path)
                if len(result) > MAX_WORKSPACE_DOCUMENTS:
                    raise PackageError(
                        f"package exceeds {MAX_WORKSPACE_DOCUMENTS} templates",
                        _location(root),
                    )
    return tuple(sorted(result, key=lambda path: path.relative_to(root).as_posix()))


def canonical_content_sha256(root: Path) -> str:
    root = root.expanduser().resolve()
    manifest = root / PACKAGE_MANIFEST
    if manifest.is_symlink() or not manifest.is_file():
        raise PackageError(f"package manifest not found: {manifest}", _location(manifest))
    paths = (manifest, *package_source_paths(root), *package_template_paths(root))
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_workspace_requirements(requirements: WorkspaceRequirements) -> str:
    lines = [f"schema = {PACKAGE_SCHEMA_VERSION}"]
    for item in sorted(requirements.packages, key=lambda req: req.alias):
        lines.extend(
            [
                "",
                f"[packages.{item.alias}]",
                f"source = {_toml_string(item.source)}",
                f"version = {_toml_string(item.version)}",
            ]
        )
    return "\n".join(lines) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_workspace_requirements(requirements: WorkspaceRequirements) -> Path:
    atomic_write_text(requirements.path, render_workspace_requirements(requirements))
    return requirements.path


def write_package_lock(lock: PackageLock) -> Path:
    text = json.dumps(lock.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    atomic_write_text(lock.path, text)
    return lock.path


def render_package_manifest(manifest: PackageManifest) -> str:
    lines = [
        f"schema = {PACKAGE_SCHEMA_VERSION}",
        f"name = {_toml_string(manifest.name)}",
        f"version = {_toml_string(manifest.version)}",
        f"namespace = {_toml_string(manifest.namespace)}",
        f"description = {_toml_string(manifest.description)}",
        f"license = {_toml_string(manifest.license)}",
        f"requires_kirin = {_toml_string(manifest.requires_kirin)}",
    ]
    if manifest.game is not None:
        lines.append(f"game = {_toml_string(manifest.game)}")
    if manifest.game_version is not None:
        lines.append(f"game_version = {_toml_string(manifest.game_version)}")
    for dependency in sorted(manifest.dependencies, key=lambda item: item.alias):
        lines.extend(
            [
                "",
                f"[dependencies.{dependency.alias}]",
                f"source = {_toml_string(dependency.source)}",
                f"version = {_toml_string(dependency.version)}",
            ]
        )
    return "\n".join(lines) + "\n"
