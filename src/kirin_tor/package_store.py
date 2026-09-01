"""Resolve local and GitHub package graphs into a bounded content-addressed store."""

from __future__ import annotations

import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Mapping, Optional, Set, Tuple

from .errors import PackageError, SourceLocation
from .limits import (
    MAX_PACKAGE_ARCHIVE_BYTES,
    MAX_PACKAGE_ARCHIVE_FILES,
    MAX_PACKAGE_EXTRACTED_BYTES,
    MAX_PACKAGE_GRAPH_DEPTH,
    MAX_PACKAGE_GRAPH_PACKAGES,
    PACKAGE_NETWORK_TIMEOUT_SECONDS,
)
from .package_manifest import (
    GITHUB_RE,
    PACKAGE_MANIFEST,
    PACKAGE_STORE,
    LockedPackage,
    PackageDependency,
    PackageLock,
    PackageManifest,
    WorkspaceRequirement,
    WorkspaceRequirements,
    canonical_content_sha256,
    load_package_lock,
    load_package_manifest,
    load_workspace_requirements,
    normalize_source,
    package_source_paths,
    package_template_paths,
    source_kind,
)


@dataclass(frozen=True)
class ResolvedPackage:
    source: str
    manifest: PackageManifest
    root: Path
    resolved: str
    content_sha256: str

    def locked(self) -> LockedPackage:
        return LockedPackage(
            source=self.source,
            name=self.manifest.name,
            version=self.manifest.version,
            namespace=self.manifest.namespace,
            resolved=self.resolved,
            content_sha256=self.content_sha256,
            dependencies=self.manifest.dependencies,
        )


@dataclass(frozen=True)
class PackageResolution:
    root: Path
    requirements: WorkspaceRequirements
    packages: Tuple[ResolvedPackage, ...]

    @property
    def lock(self) -> PackageLock:
        return PackageLock(
            self.root,
            direct=self.requirements.packages,
            packages=tuple(item.locked() for item in self.packages),
        )

    def by_source(self) -> Dict[str, ResolvedPackage]:
        return {item.source: item for item in self.packages}


class GitHubClient:
    """Small public-GitHub adapter with explicit host and response bounds."""

    api_host = "api.github.com"
    archive_hosts = {"codeload.github.com", "github.com"}

    def __init__(self, token: Optional[str] = None, timeout: float = PACKAGE_NETWORK_TIMEOUT_SECONDS):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self.timeout = timeout

    def _headers(self, *, json_response: bool = False) -> dict:
        headers = {
            "Accept": "application/vnd.github+json" if json_response else "application/octet-stream",
            "User-Agent": "kirin-tor-cli-package-resolver",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _open(self, request: urllib.request.Request, *, allowed_hosts: Set[str]):
        try:
            response = urllib.request.urlopen(request, timeout=self.timeout)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PackageError(f"GitHub request failed: {exc}") from exc
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != "https" or (final.hostname or "").lower() not in allowed_hosts:
            response.close()
            raise PackageError(f"GitHub request redirected to disallowed URL {response.geturl()!r}")
        return response

    def _json_get(self, url: str) -> Mapping[str, object]:
        request = urllib.request.Request(url, headers=self._headers(json_response=True))
        with self._open(request, allowed_hosts={self.api_host}) as response:
            content_length = response.headers.get("Content-Length")
            try:
                declared_length = int(content_length) if content_length else 0
            except ValueError as exc:
                raise PackageError("GitHub JSON response has an invalid Content-Length") from exc
            if declared_length > 1_000_000:
                raise PackageError("GitHub JSON response is unexpectedly large")
            payload = response.read(1_000_001)
            if len(payload) > 1_000_000:
                raise PackageError("GitHub JSON response is unexpectedly large")
        try:
            data = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"invalid GitHub JSON response: {exc}") from exc
        if not isinstance(data, dict):
            raise PackageError("GitHub JSON response must be an object")
        return data

    def resolve_release_commit(self, source: str, version: str) -> str:
        match = GITHUB_RE.fullmatch(source)
        if match is None:
            raise PackageError(f"cannot resolve non-GitHub source {source!r}")
        owner = urllib.parse.quote(match.group("owner"), safe="")
        repository = urllib.parse.quote(match.group("repo"), safe="")
        last_error = None
        for reference in (f"v{version}", version):
            encoded = urllib.parse.quote(reference, safe="")
            url = f"https://api.github.com/repos/{owner}/{repository}/git/ref/tags/{encoded}"
            try:
                data = self._json_get(url)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    last_error = exc
                    continue
                raise PackageError(f"GitHub rejected tag lookup with HTTP {exc.code}") from exc
            object_data = data.get("object")
            if not isinstance(object_data, dict):
                raise PackageError("GitHub tag response has no object")
            for _depth in range(5):
                object_type = object_data.get("type")
                object_sha = object_data.get("sha")
                if not isinstance(object_sha, str) or not re.fullmatch(
                    r"[0-9a-fA-F]{40}", object_sha
                ):
                    raise PackageError("GitHub tag response has no full object SHA")
                if object_type == "commit":
                    return object_sha.lower()
                if object_type != "tag":
                    raise PackageError(
                        f"GitHub release tag points to unsupported object type {object_type!r}"
                    )
                tag_url = (
                    f"https://api.github.com/repos/{owner}/{repository}/git/tags/"
                    + object_sha
                )
                try:
                    tag_data = self._json_get(tag_url)
                except urllib.error.HTTPError as exc:
                    raise PackageError(
                        f"GitHub rejected annotated tag lookup with HTTP {exc.code}"
                    ) from exc
                object_data = tag_data.get("object")
                if not isinstance(object_data, dict):
                    raise PackageError("annotated GitHub tag has no target object")
            raise PackageError("annotated GitHub tag indirection is too deep")
        raise PackageError(f"GitHub release tag v{version!s} or {version!s} was not found") from last_error

    def download_archive(self, source: str, commit: str, destination: Path) -> None:
        match = GITHUB_RE.fullmatch(source)
        if match is None:
            raise PackageError(f"cannot download non-GitHub source {source!r}")
        owner = urllib.parse.quote(match.group("owner"), safe="")
        repository = urllib.parse.quote(match.group("repo"), safe="")
        url = f"https://codeload.github.com/{owner}/{repository}/tar.gz/{commit}"
        request = urllib.request.Request(url, headers=self._headers())
        try:
            response = self._open(request, allowed_hosts=self.archive_hosts)
        except urllib.error.HTTPError as exc:
            raise PackageError(f"GitHub archive download failed with HTTP {exc.code}") from exc
        with response:
            content_length = response.headers.get("Content-Length")
            try:
                declared_length = int(content_length) if content_length else 0
            except ValueError as exc:
                raise PackageError("GitHub archive has an invalid Content-Length") from exc
            if declared_length > MAX_PACKAGE_ARCHIVE_BYTES:
                raise PackageError(
                    f"GitHub archive exceeds {MAX_PACKAGE_ARCHIVE_BYTES} bytes"
                )
            total = 0
            with destination.open("xb") as handle:
                while True:
                    chunk = response.read(min(1024 * 1024, MAX_PACKAGE_ARCHIVE_BYTES - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_PACKAGE_ARCHIVE_BYTES:
                        raise PackageError(
                            f"GitHub archive exceeds {MAX_PACKAGE_ARCHIVE_BYTES} bytes"
                        )
                    handle.write(chunk)


def _safe_archive_path(name: str) -> PurePosixPath:
    if "\\" in name or "\x00" in name:
        raise PackageError(f"unsafe package archive path {name!r}")
    candidate = PurePosixPath(name)
    if not name or candidate.is_absolute() or any(
        part in {"", ".", ".."} or ":" in part for part in candidate.parts
    ):
        raise PackageError(f"unsafe package archive path {name!r}")
    return candidate


def extract_github_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    count = 0
    top_levels = set()
    seen = set()
    try:
        handle = tarfile.open(archive, mode="r:gz")
    except (tarfile.TarError, OSError) as exc:
        raise PackageError(f"invalid GitHub package archive: {exc}") from exc
    with handle:
        for member in handle:
            count += 1
            if count > MAX_PACKAGE_ARCHIVE_FILES:
                raise PackageError(
                    f"package archive exceeds {MAX_PACKAGE_ARCHIVE_FILES} members"
                )
            relative = _safe_archive_path(member.name)
            top_levels.add(relative.parts[0])
            if len(top_levels) > 1:
                raise PackageError("GitHub archive must contain one repository root")
            normalized = relative.as_posix()
            collision_key = normalized.casefold()
            if collision_key in seen:
                raise PackageError(f"package archive repeats path {normalized!r}")
            seen.add(collision_key)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise PackageError(f"package archive contains unsupported link or device {normalized!r}")
            if not (member.isdir() or member.isfile()):
                raise PackageError(f"package archive contains unsupported member {normalized!r}")
            target = destination.joinpath(*relative.parts)
            try:
                target.resolve().relative_to(destination.resolve())
            except ValueError as exc:
                raise PackageError(f"package archive path leaves extraction root: {normalized!r}") from exc
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if member.size < 0:
                raise PackageError(f"package archive member has an invalid size: {normalized!r}")
            total += member.size
            if total > MAX_PACKAGE_EXTRACTED_BYTES:
                raise PackageError(
                    f"package archive expands beyond {MAX_PACKAGE_EXTRACTED_BYTES} bytes"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            source = handle.extractfile(member)
            if source is None:
                raise PackageError(f"cannot read package archive member {normalized!r}")
            remaining = member.size
            with source, target.open("xb") as output:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise PackageError(f"truncated package archive member {normalized!r}")
                    output.write(chunk)
                    remaining -= len(chunk)
    if len(top_levels) != 1:
        raise PackageError("GitHub archive is empty")
    root = destination / next(iter(top_levels))
    if not (root / PACKAGE_MANIFEST).is_file():
        raise PackageError("GitHub repository root has no kirin.package.toml")
    return root


class PackageStoreManager:
    def __init__(self, workspace_root: Path, github: Optional[GitHubClient] = None):
        self.workspace_root = workspace_root.expanduser().resolve()
        self.root = self.workspace_root / PACKAGE_STORE
        self.github = github or GitHubClient()

    def cached_root(self, digest: str) -> Path:
        return self.root / digest

    def _copy_authoritative_content(self, source_root: Path, digest: str) -> Path:
        source_root = source_root.resolve()
        target = self.cached_root(digest)
        if target.exists():
            if canonical_content_sha256(target) != digest:
                raise PackageError(f"cached package {digest} failed its content digest")
            return target
        self.root.mkdir(parents=True, exist_ok=True)
        cache_ignore = self.root.parent / ".gitignore"
        if not cache_ignore.exists():
            cache_ignore.write_text("*\n", encoding="utf-8")
        temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=self.root))
        try:
            shutil.copy2(source_root / PACKAGE_MANIFEST, temporary / PACKAGE_MANIFEST)
            for path in (*package_source_paths(source_root), *package_template_paths(source_root)):
                relative = path.relative_to(source_root)
                destination = temporary / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            if canonical_content_sha256(temporary) != digest:
                raise PackageError("copied package content changed during snapshot")
            try:
                os.replace(temporary, target)
            except OSError:
                if not target.exists():
                    raise
            if canonical_content_sha256(target) != digest:
                raise PackageError(f"cached package {digest} failed its content digest")
            return target
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def materialize(self, source: str, version: str) -> ResolvedPackage:
        source = normalize_source(source, relative_to=self.workspace_root)
        kind = source_kind(source)
        if kind == "path":
            source_root = Path(source[5:]).resolve()
            manifest = load_package_manifest(source_root)
            if manifest.version != version:
                raise PackageError(
                    f"requested {source} version {version}, manifest declares {manifest.version}"
                )
            digest = canonical_content_sha256(source_root)
            cached = self._copy_authoritative_content(source_root, digest)
            cached_manifest = load_package_manifest(cached)
            # Preserve normalized dependency paths from the authoring directory.
            cached_manifest = PackageManifest(
                root=cached,
                name=cached_manifest.name,
                version=cached_manifest.version,
                namespace=cached_manifest.namespace,
                description=cached_manifest.description,
                license=cached_manifest.license,
                requires_kirin=cached_manifest.requires_kirin,
                game=cached_manifest.game,
                game_version=cached_manifest.game_version,
                dependencies=manifest.dependencies,
            )
            return ResolvedPackage(source, cached_manifest, cached, str(source_root), digest)
        commit = self.github.resolve_release_commit(source, version)
        with tempfile.TemporaryDirectory(prefix="kirin-package-download-") as temporary_name:
            temporary = Path(temporary_name)
            archive = temporary / "package.tar.gz"
            extracted = temporary / "extracted"
            self.github.download_archive(source, commit, archive)
            repository_root = extract_github_archive(archive, extracted)
            manifest = load_package_manifest(repository_root)
            if manifest.version != version:
                raise PackageError(
                    f"requested {source} version {version}, manifest declares {manifest.version}"
                )
            if any(source_kind(item.source) != "github" for item in manifest.dependencies):
                raise PackageError("published GitHub packages may only depend on GitHub package sources")
            digest = canonical_content_sha256(repository_root)
            cached = self._copy_authoritative_content(repository_root, digest)
        cached_manifest = load_package_manifest(cached)
        return ResolvedPackage(source, cached_manifest, cached, commit, digest)

    def from_locked(self, package: LockedPackage) -> ResolvedPackage:
        root = self.cached_root(package.content_sha256)
        if not root.is_dir():
            raise PackageError(
                f"package cache is missing {package.name} {package.version}; run 'kt package restore'"
            )
        digest = canonical_content_sha256(root)
        if digest != package.content_sha256:
            raise PackageError(
                f"cached package {package.name} {package.version} failed its content digest"
            )
        manifest = load_package_manifest(root)
        if (
            manifest.name != package.name
            or manifest.version != package.version
            or manifest.namespace != package.namespace
        ):
            raise PackageError(
                f"cached package identity does not match lockfile for {package.source}"
            )
        cached_dependencies = {
            (item.alias, item.source, item.version) for item in manifest.dependencies
        }
        locked_dependencies = {
            (item.alias, item.source, item.version) for item in package.dependencies
        }
        if cached_dependencies != locked_dependencies:
            raise PackageError(
                f"cached package dependencies do not match lockfile for {package.source}"
            )
        # Lockfile sources are authoritative for normalized path dependencies because
        # a cached manifest no longer has the author's relative filesystem context.
        manifest = PackageManifest(
            root=root,
            name=manifest.name,
            version=manifest.version,
            namespace=manifest.namespace,
            description=manifest.description,
            license=manifest.license,
            requires_kirin=manifest.requires_kirin,
            game=manifest.game,
            game_version=manifest.game_version,
            dependencies=package.dependencies,
        )
        return ResolvedPackage(
            package.source,
            manifest,
            root,
            package.resolved,
            package.content_sha256,
        )

    def restore_locked(self, package: LockedPackage) -> ResolvedPackage:
        """Rebuild one missing cache entry from its immutable lock identity."""
        if self.cached_root(package.content_sha256).is_dir():
            return self.from_locked(package)
        kind = source_kind(package.source)
        if kind == "path":
            source_root = Path(package.resolved).expanduser().resolve()
            if not source_root.is_dir():
                raise PackageError(
                    f"locked local package source is unavailable: {source_root}"
                )
            manifest = load_package_manifest(source_root)
            digest = canonical_content_sha256(source_root)
            if digest != package.content_sha256:
                raise PackageError(
                    f"local source for {package.name} changed and cannot reconstruct locked content "
                    f"{package.content_sha256}"
                )
            if (
                manifest.name != package.name
                or manifest.version != package.version
                or manifest.namespace != package.namespace
            ):
                raise PackageError(f"local source identity changed for {package.source}")
            self._copy_authoritative_content(source_root, digest)
            return self.from_locked(package)

        if not re.fullmatch(r"[0-9a-f]{40}", package.resolved):
            raise PackageError(f"locked GitHub commit is invalid for {package.source}")
        with tempfile.TemporaryDirectory(prefix="kirin-package-restore-") as temporary_name:
            temporary = Path(temporary_name)
            archive = temporary / "package.tar.gz"
            extracted = temporary / "extracted"
            self.github.download_archive(package.source, package.resolved, archive)
            repository_root = extract_github_archive(archive, extracted)
            manifest = load_package_manifest(repository_root)
            digest = canonical_content_sha256(repository_root)
            if digest != package.content_sha256:
                raise PackageError(
                    f"GitHub commit content for {package.name} does not match locked digest"
                )
            if (
                manifest.name != package.name
                or manifest.version != package.version
                or manifest.namespace != package.namespace
            ):
                raise PackageError(f"GitHub commit identity does not match lockfile for {package.source}")
            self._copy_authoritative_content(repository_root, digest)
        return self.from_locked(package)


class PackageResolver:
    def __init__(self, store: PackageStoreManager):
        self.store = store

    def resolve(self, requirements: WorkspaceRequirements) -> PackageResolution:
        requested: Dict[str, str] = {}
        instances: Dict[str, ResolvedPackage] = {}
        visiting: Set[str] = set()
        complete: Set[str] = set()
        namespaces: Dict[str, str] = {}

        def visit(source: str, version: str, chain: Tuple[str, ...]) -> None:
            if len(chain) >= MAX_PACKAGE_GRAPH_DEPTH:
                raise PackageError(
                    f"package dependency graph exceeds depth {MAX_PACKAGE_GRAPH_DEPTH}"
                )
            existing_version = requested.get(source)
            if existing_version is not None and existing_version != version:
                raise PackageError(
                    f"package version conflict for {source}: {existing_version} and {version}"
                )
            requested[source] = version
            if source in complete:
                return
            if source in visiting:
                cycle_start = chain.index(source) if source in chain else 0
                cycle = (*chain[cycle_start:], source)
                raise PackageError("package dependency cycle: " + " -> ".join(cycle))
            visiting.add(source)
            instance = instances.get(source)
            if instance is None:
                if len(instances) >= MAX_PACKAGE_GRAPH_PACKAGES:
                    raise PackageError(
                        f"package dependency graph exceeds {MAX_PACKAGE_GRAPH_PACKAGES} packages"
                    )
                instance = self.store.materialize(source, version)
                instances[source] = instance
            owner = namespaces.get(instance.manifest.namespace)
            if owner is not None and owner != source:
                raise PackageError(
                    f"package namespace {instance.manifest.namespace!r} is claimed by both {owner} and {source}"
                )
            namespaces[instance.manifest.namespace] = source
            for dependency in instance.manifest.dependencies:
                visit(dependency.source, dependency.version, (*chain, source))
            visiting.remove(source)
            complete.add(source)

        for requirement in requirements.packages:
            visit(requirement.source, requirement.version, ())
        return PackageResolution(
            requirements.root,
            requirements,
            tuple(instances[source] for source in sorted(instances)),
        )

    def resolve_workspace(self) -> PackageResolution:
        requirements = load_workspace_requirements(self.store.workspace_root)
        return self.resolve(requirements)

    def load_locked_workspace(self) -> PackageResolution:
        requirements = load_workspace_requirements(self.store.workspace_root)
        if not requirements.packages:
            lock = load_package_lock(self.store.workspace_root)
            if lock.packages or lock.direct:
                raise PackageError(
                    f"{lock.path.name} exists without declared packages in {requirements.path.name}"
                )
            return PackageResolution(self.store.workspace_root, requirements, ())
        lock = load_package_lock(self.store.workspace_root, required=True)
        expected = {(item.alias, item.source, item.version) for item in requirements.packages}
        locked = {(item.alias, item.source, item.version) for item in lock.direct}
        if expected != locked:
            raise PackageError(
                f"{lock.path.name} does not match {requirements.path.name}; run 'kt package restore'"
            )
        packages = tuple(self.store.from_locked(item) for item in lock.packages)
        resolution = PackageResolution(self.store.workspace_root, requirements, packages)
        resolved_lock = resolution.lock
        if resolved_lock.as_dict()["packages"] != lock.as_dict()["packages"]:
            raise PackageError(f"{lock.path.name} does not match cached package metadata")
        self._validate_graph(resolution)
        return resolution

    def restore_locked_workspace(self) -> PackageResolution:
        requirements = load_workspace_requirements(self.store.workspace_root)
        if not requirements.packages:
            lock = load_package_lock(self.store.workspace_root)
            if lock.packages or lock.direct:
                raise PackageError(
                    f"{lock.path.name} exists without declared packages in {requirements.path.name}"
                )
            return PackageResolution(self.store.workspace_root, requirements, ())
        lock = load_package_lock(self.store.workspace_root, required=True)
        expected = {(item.alias, item.source, item.version) for item in requirements.packages}
        locked = {(item.alias, item.source, item.version) for item in lock.direct}
        if expected != locked:
            raise PackageError(
                f"{lock.path.name} does not match {requirements.path.name}; use package update to resolve changes"
            )
        packages = tuple(self.store.restore_locked(item) for item in lock.packages)
        resolution = PackageResolution(self.store.workspace_root, requirements, packages)
        self._validate_graph(resolution)
        return resolution

    @staticmethod
    def _validate_graph(resolution: PackageResolution) -> None:
        by_source = resolution.by_source()
        namespaces: Dict[str, str] = {}
        for instance in resolution.packages:
            owner = namespaces.get(instance.manifest.namespace)
            if owner is not None and owner != instance.source:
                raise PackageError(
                    f"package namespace {instance.manifest.namespace!r} is claimed by both {owner} and {instance.source}"
                )
            namespaces[instance.manifest.namespace] = instance.source
            for dependency in instance.manifest.dependencies:
                target = by_source.get(dependency.source)
                if target is None or target.manifest.version != dependency.version:
                    raise PackageError(
                        f"locked dependency {instance.manifest.name}:{dependency.alias} is unavailable"
                    )
        visiting: Set[str] = set()
        complete: Set[str] = set()

        def visit(source: str, chain: Tuple[str, ...]) -> None:
            if len(chain) >= MAX_PACKAGE_GRAPH_DEPTH:
                raise PackageError(
                    f"locked package dependency graph exceeds depth {MAX_PACKAGE_GRAPH_DEPTH}"
                )
            if source in complete:
                return
            if source in visiting:
                start = chain.index(source) if source in chain else 0
                raise PackageError(
                    "locked package dependency cycle: "
                    + " -> ".join((*chain[start:], source))
                )
            visiting.add(source)
            package = by_source[source]
            for dependency in package.manifest.dependencies:
                visit(dependency.source, (*chain, source))
            visiting.remove(source)
            complete.add(source)

        for source in sorted(by_source):
            visit(source, ())


def locked_workspace_resolution(root: Path) -> PackageResolution:
    return PackageResolver(PackageStoreManager(root)).load_locked_workspace()


def resolve_workspace_requirements(root: Path) -> PackageResolution:
    return PackageResolver(PackageStoreManager(root)).resolve_workspace()
