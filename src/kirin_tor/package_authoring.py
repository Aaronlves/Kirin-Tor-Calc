"""Transactional consumer and author workflows for community packages."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from .engine import Engine
from .errors import PackageError, WorkspaceError
from .package_manifest import (
    NAMESPACE_RE,
    PACKAGE_NAME_RE,
    VERSION_RE,
    WORKSPACE_LOCK,
    PackageManifest,
    WorkspaceRequirement,
    WorkspaceRequirements,
    atomic_write_text,
    current_feature_line,
    load_package_manifest,
    load_workspace_requirements,
    normalize_source,
    render_package_manifest,
    render_workspace_requirements,
)
from .package_store import PackageResolution, PackageResolver, PackageStoreManager
from .workspace import Workspace, initialize


def _validate_resolved_workspace(root: Path, resolution: PackageResolution) -> dict:
    workspace = Workspace.load(root, package_resolution=resolution)
    return Engine(workspace).validate_all()


def _write_transaction(requirements: WorkspaceRequirements, resolution: PackageResolution) -> None:
    requirement_path = requirements.path
    lock_path = resolution.lock.path
    previous_requirements = requirement_path.read_bytes() if requirement_path.exists() else None
    previous_lock = lock_path.read_bytes() if lock_path.exists() else None
    requirement_text = render_workspace_requirements(requirements)
    lock_text = json.dumps(
        resolution.lock.as_dict(), ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    try:
        atomic_write_text(requirement_path, requirement_text)
        atomic_write_text(lock_path, lock_text)
    except Exception:
        if previous_requirements is None:
            requirement_path.unlink(missing_ok=True)
        else:
            atomic_write_text(requirement_path, previous_requirements.decode("utf-8"))
        if previous_lock is None:
            lock_path.unlink(missing_ok=True)
        else:
            atomic_write_text(lock_path, previous_lock.decode("utf-8"))
        raise


def apply_workspace_requirements(requirements: WorkspaceRequirements) -> PackageResolution:
    root = requirements.root.resolve()
    if not (root / "kirin.workspace").is_file():
        raise WorkspaceError(f"{root} is not a Kirin Tor workspace")
    resolver = PackageResolver(PackageStoreManager(root))
    resolution = resolver.resolve(requirements)
    _validate_resolved_workspace(root, resolution)
    _write_transaction(requirements, resolution)
    return resolution


def add_package(root: Path, alias: str, source: str, version: str) -> PackageResolution:
    root = root.resolve()
    requirements = load_workspace_requirements(root)
    if not NAMESPACE_RE.fullmatch(alias):
        raise PackageError("package alias must match [a-z][a-z0-9_]*")
    normalized = normalize_source(source, relative_to=root)
    if not normalized.startswith("github:"):
        raise PackageError("package add requires github:OWNER/REPO; use package add-path for local sources")
    if not VERSION_RE.fullmatch(version):
        raise PackageError("package version must use exact MAJOR.MINOR.PATCH")
    by_alias = requirements.by_alias()
    if alias in by_alias:
        raise PackageError(f"package alias {alias!r} already exists; use package update or remove")
    if any(item.source == normalized for item in requirements.packages):
        raise PackageError(f"package source {normalized!r} is already a direct dependency")
    updated = WorkspaceRequirements(
        root,
        tuple(sorted((*requirements.packages, WorkspaceRequirement(alias, normalized, version)), key=lambda item: item.alias)),
    )
    return apply_workspace_requirements(updated)


def add_path_package(root: Path, alias: str, package_path: Path) -> PackageResolution:
    root = root.resolve()
    package_path = package_path.expanduser().resolve()
    manifest = load_package_manifest(package_path)
    requirements = load_workspace_requirements(root)
    if not NAMESPACE_RE.fullmatch(alias):
        raise PackageError("package alias must match [a-z][a-z0-9_]*")
    if alias in requirements.by_alias():
        raise PackageError(f"package alias {alias!r} already exists; use package remove first")
    source = normalize_source(f"path:{package_path}", relative_to=root)
    if any(item.source == source for item in requirements.packages):
        raise PackageError(f"package source {source!r} is already a direct dependency")
    updated = WorkspaceRequirements(
        root,
        tuple(
            sorted(
                (*requirements.packages, WorkspaceRequirement(alias, source, manifest.version)),
                key=lambda item: item.alias,
            )
        ),
    )
    return apply_workspace_requirements(updated)


def remove_package(root: Path, alias: str) -> PackageResolution:
    root = root.resolve()
    requirements = load_workspace_requirements(root)
    if alias not in requirements.by_alias():
        raise PackageError(f"unknown direct package alias {alias!r}")
    updated = WorkspaceRequirements(
        root, tuple(item for item in requirements.packages if item.alias != alias)
    )
    return apply_workspace_requirements(updated)


def update_package(root: Path, alias: str, version: Optional[str] = None) -> PackageResolution:
    root = root.resolve()
    requirements = load_workspace_requirements(root)
    current = requirements.by_alias().get(alias)
    if current is None:
        raise PackageError(f"unknown direct package alias {alias!r}")
    requested_version = version or current.version
    if not VERSION_RE.fullmatch(requested_version):
        raise PackageError("package version must use exact MAJOR.MINOR.PATCH")
    updated_items = tuple(
        WorkspaceRequirement(item.alias, item.source, requested_version)
        if item.alias == alias
        else item
        for item in requirements.packages
    )
    return apply_workspace_requirements(WorkspaceRequirements(root, updated_items))


def restore_packages(root: Path) -> PackageResolution:
    root = root.resolve()
    requirements = load_workspace_requirements(root)
    resolver = PackageResolver(PackageStoreManager(root))
    if (root / WORKSPACE_LOCK).is_file():
        resolution = resolver.restore_locked_workspace()
        _validate_resolved_workspace(root, resolution)
        return resolution
    resolution = resolver.resolve(requirements)
    _validate_resolved_workspace(root, resolution)
    _write_transaction(requirements, resolution)
    return resolution


def verify_packages(root: Path) -> Tuple[PackageResolution, dict]:
    root = root.resolve()
    resolver = PackageResolver(PackageStoreManager(root))
    resolution = resolver.load_locked_workspace()
    result = _validate_resolved_workspace(root, resolution)
    return resolution, result


def check_package(package_root: Path) -> Tuple[PackageResolution, dict]:
    package_root = package_root.expanduser().resolve()
    manifest = load_package_manifest(package_root)
    with tempfile.TemporaryDirectory(prefix="kirin-package-check-") as temporary_name:
        workspace_root = initialize(Path(temporary_name) / "workspace")
        requirement = WorkspaceRequirement(
            alias="subject",
            source=normalize_source(f"path:{package_root}", relative_to=workspace_root),
            version=manifest.version,
        )
        requirements = WorkspaceRequirements(workspace_root, (requirement,))
        resolution = PackageResolver(PackageStoreManager(workspace_root)).resolve(requirements)
        result = _validate_resolved_workspace(workspace_root, resolution)
        return resolution, result


MIT_LICENSE = """MIT License

Copyright (c) 2026 Package contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""


def _next_feature_line() -> str:
    major_text, minor_text = current_feature_line().split(".", 1)
    return f"{major_text}.{int(minor_text) + 1}"


def create_package_template(
    root: Path,
    *,
    name: str,
    namespace: str,
    version: str = "1.0.0",
) -> Path:
    root = root.expanduser().resolve()
    if not PACKAGE_NAME_RE.fullmatch(name):
        raise PackageError("package name must be a dotted lower-case name")
    if not NAMESPACE_RE.fullmatch(namespace):
        raise PackageError("package namespace must match [a-z][a-z0-9_]*")
    if not VERSION_RE.fullmatch(version):
        raise PackageError("package version must use exact MAJOR.MINOR.PATCH")
    if root.exists() and not root.is_dir():
        raise PackageError(f"package target is not a directory: {root}")
    if root.exists() and any(root.iterdir()):
        raise PackageError(f"package directory is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    manifest = PackageManifest(
        root=root,
        name=name,
        version=version,
        namespace=namespace,
        description="Describe the package's authoritative scope and exclusions.",
        license="MIT",
        requires_kirin=current_feature_line(),
    )
    (root / "kirin.package.toml").write_text(render_package_manifest(manifest), encoding="utf-8")
    entries = root / "entries"
    entries.mkdir()
    entry_id = f"{namespace}_example"
    (entries / "example.kirin").write_text(
        f'''@kirin 1
@entry {entry_id}
@status draft

// Replace this game-neutral example with sourced community data.

sources:
  {{"kind":"documentation","citation":"Replace with an authoritative source"}}

inputs:
  x "输入": number[dimensionless] = 1

outputs:
  result "结果": dimensionless = x
''',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f'''# {name}

Community-maintained Kirin package using namespace `{namespace}`.

```bash
python -m pip install "kirin-tor-cli>={current_feature_line()},<{_next_feature_line()}"
kt package check .
```

Document the package scope, excluded claims, game/ruleset versions, evidence policy, and
maintainer process here. Package sources are data only and must not require executable hooks.
''',
        encoding="utf-8",
    )
    (root / "LICENSE").write_text(MIT_LICENSE, encoding="utf-8")
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "validate.yml").write_text(
        f'''name: validate-kirin-package

on:
  push:
  pull_request:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: actions/setup-python@v6
        with:
          python-version: "3.12"
      - run: python -m pip install "kirin-tor-cli>={current_feature_line()},<{_next_feature_line()}"
      - run: kt package check .
''',
        encoding="utf-8",
    )
    load_package_manifest(root)
    return root
