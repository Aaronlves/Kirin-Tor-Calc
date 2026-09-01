from __future__ import annotations

import io
import json
import shutil
import tarfile
from pathlib import Path
from typing import Optional

import pytest

from kirin_tor.application import build_workspace_index
from kirin_tor.engine import Engine
from kirin_tor.errors import PackageError, ReferenceError, SchemaError
from kirin_tor.operations import evaluate
from kirin_tor.package_authoring import add_path_package, remove_package
from kirin_tor.package_manifest import (
    PackageManifest,
    WorkspaceRequirement,
    WorkspaceRequirements,
    canonical_content_sha256,
    current_feature_line,
    load_package_lock,
    load_package_manifest,
    load_workspace_requirements,
    render_package_manifest,
    write_package_lock,
    write_workspace_requirements,
)
from kirin_tor.package_store import (
    GitHubClient,
    PackageResolver,
    PackageStoreManager,
    extract_github_archive,
)
from kirin_tor.tui import KirinTUI, resolve_source_path
from kirin_tor.workspace import Workspace, initialize
from textual.widgets import TextArea


def _package(
    root: Path,
    *,
    name: str = "community.example",
    version: str = "1.0.0",
    namespace: str = "community_example",
    expression: str = "1",
    dependencies: str = "",
    document_id: Optional[str] = None,
) -> Path:
    root.mkdir(parents=True)
    manifest = f'''schema = 1
name = "{name}"
version = "{version}"
namespace = "{namespace}"
description = "Test package"
license = "MIT"
requires_kirin = "{current_feature_line()}"
{dependencies}'''
    (root / "kirin.package.toml").write_text(manifest, encoding="utf-8")
    entries = root / "entries"
    entries.mkdir()
    entry_id = document_id or f"{namespace}_value"
    (entries / "value.kirin").write_text(
        f"@kirin 1\n@entry {entry_id}\n\noutputs:\n  result: dimensionless = {expression}\n",
        encoding="utf-8",
    )
    return root


def _resolve_and_lock(workspace: Path, requirements: WorkspaceRequirements):
    write_workspace_requirements(requirements)
    resolution = PackageResolver(PackageStoreManager(workspace)).resolve(requirements)
    write_package_lock(resolution.lock)
    return resolution


def test_manifest_is_strict_and_round_trips_template(tmp_path: Path) -> None:
    root = tmp_path / "package"
    _package(root)
    manifest = load_package_manifest(root)
    assert manifest.name == "community.example"
    assert manifest.namespace == "community_example"
    rendered = render_package_manifest(manifest)
    (root / "kirin.package.toml").write_text(rendered, encoding="utf-8")
    assert load_package_manifest(root) == manifest

    (root / "kirin.package.toml").write_text(rendered + "hook = \"run-me\"\n", encoding="utf-8")
    with pytest.raises(PackageError, match="unknown package manifest field"):
        load_package_manifest(root)


def test_content_digest_covers_only_authoritative_package_sources(tmp_path: Path) -> None:
    root = _package(tmp_path / "package")
    before = canonical_content_sha256(root)
    (root / "README.md").write_text("presentation only", encoding="utf-8")
    assert canonical_content_sha256(root) == before
    source = root / "entries" / "value.kirin"
    source.write_text(source.read_text(encoding="utf-8") + "// changed\n", encoding="utf-8")
    assert canonical_content_sha256(root) != before


def test_local_package_resolves_locks_and_loads_read_only(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package")
    requirement = WorkspaceRequirement("example", f"path:{package}", "1.0.0")
    requirements = WorkspaceRequirements(workspace, (requirement,))
    resolution = _resolve_and_lock(workspace, requirements)

    loaded_requirements = load_workspace_requirements(workspace)
    loaded_lock = load_package_lock(workspace, required=True)
    assert loaded_requirements.packages[0].alias == "example"
    assert loaded_lock.packages[0].content_sha256 == resolution.packages[0].content_sha256

    loaded = Workspace.load(workspace)
    document = loaded.get_entry("community_example_value")
    assert document.read_only is True
    assert document.package_origin is not None
    assert document.package_origin.source.startswith("path:")
    assert evaluate(Engine(loaded), "community_example_value.result")["exact"] == "1"
    target = build_workspace_index(loaded).targets[0]
    assert target.package_name == "community.example"
    assert target.package_version == "1.0.0"


@pytest.mark.asyncio
async def test_tui_opens_package_diagnostics_as_read_only(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package")
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("example", f"path:{package}", "1.0.0"),),
    )
    _resolve_and_lock(workspace, requirements)
    packaged_document = Workspace.load(workspace).get_entry("community_example_value")
    app = KirinTUI(workspace, resolve_source_path(workspace, None))
    async with app.run_test() as pilot:
        app._switch_source(packaged_document.path)
        await pilot.pause(1.0)
        assert app.query_one("#editor", TextArea).read_only is True
        assert packaged_document.path not in app._workspace_overlays()


def test_package_namespace_is_enforced(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package", document_id="unscoped")
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("example", f"path:{package}", "1.0.0"),),
    )
    _resolve_and_lock(workspace, requirements)
    with pytest.raises(SchemaError, match="namespace prefix"):
        Workspace.load(workspace)


def test_package_semantic_exports_require_the_same_namespace(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package")
    (package / "entries" / "value.kirin").write_text(
        """@kirin 1
@entry community_example_semantics

dimensions:
  damage

units:
  damage = damage
""",
        encoding="utf-8",
    )
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("example", f"path:{package}", "1.0.0"),),
    )
    _resolve_and_lock(workspace, requirements)
    with pytest.raises(SchemaError, match="namespace prefix"):
        Workspace.load(workspace)


def test_local_semantics_cannot_shadow_package_semantics(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package")
    semantic_source = """@kirin 1
@entry community_example_semantics

dimensions:
  community_example_damage

units:
  community_example_damage = community_example_damage
"""
    (package / "entries" / "value.kirin").write_text(semantic_source, encoding="utf-8")
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("example", f"path:{package}", "1.0.0"),),
    )
    _resolve_and_lock(workspace, requirements)
    (workspace / "entries" / "shadow.kirin").write_text(
        semantic_source.replace("@entry community_example_semantics", "@entry local_shadow"),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="authority boundaries"):
        Workspace.load(workspace)


def test_transitive_local_package_dependency_is_loaded(tmp_path: Path) -> None:
    base = _package(
        tmp_path / "base",
        name="community.base",
        namespace="community_base",
        expression="2",
    )
    dependency = f'''\n[dependencies.base]\nsource = "path:{base}"\nversion = "1.0.0"\n'''
    feature = _package(
        tmp_path / "feature",
        name="community.feature",
        namespace="community_feature",
        expression="community_base_value.result + 1",
        dependencies=dependency,
    )
    workspace = initialize(tmp_path / "workspace")
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("feature", f"path:{feature}", "1.0.0"),),
    )
    _resolve_and_lock(workspace, requirements)
    loaded = Workspace.load(workspace)
    assert set(loaded.entries) == {"community_base_value", "community_feature_value"}
    assert evaluate(Engine(loaded), "community_feature_value.result")["exact"] == "3"


def test_package_cannot_use_an_undeclared_sibling_package(tmp_path: Path) -> None:
    base = _package(
        tmp_path / "base",
        name="community.base",
        namespace="community_base",
        expression="2",
    )
    feature = _package(
        tmp_path / "feature",
        name="community.feature",
        namespace="community_feature",
        expression="community_base_value.result + 1",
    )
    workspace = initialize(tmp_path / "workspace")
    requirements = WorkspaceRequirements(
        workspace,
        (
            WorkspaceRequirement("base", f"path:{base}", "1.0.0"),
            WorkspaceRequirement("feature", f"path:{feature}", "1.0.0"),
        ),
    )
    _resolve_and_lock(workspace, requirements)
    with pytest.raises(SchemaError, match="undeclared package source"):
        Engine(Workspace.load(workspace)).validate_all()


def test_package_cannot_use_undeclared_sibling_semantics(tmp_path: Path) -> None:
    base = _package(
        tmp_path / "base",
        name="community.base",
        namespace="community_base",
        document_id="community_base_semantics",
    )
    (base / "entries" / "value.kirin").write_text(
        """@kirin 1
@entry community_base_semantics

dimensions:
  community_base_damage

units:
  community_base_damage = community_base_damage
""",
        encoding="utf-8",
    )
    feature = _package(
        tmp_path / "feature",
        name="community.feature",
        namespace="community_feature",
    )
    (feature / "entries" / "value.kirin").write_text(
        """@kirin 1
@entry community_feature_value

fields:
  amount: community_base_damage = 1

outputs:
  result: community_base_damage = amount
""",
        encoding="utf-8",
    )
    workspace = initialize(tmp_path / "workspace")
    requirements = WorkspaceRequirements(
        workspace,
        (
            WorkspaceRequirement("base", f"path:{base}", "1.0.0"),
            WorkspaceRequirement("feature", f"path:{feature}", "1.0.0"),
        ),
    )
    _resolve_and_lock(workspace, requirements)
    with pytest.raises(SchemaError, match="undeclared package source"):
        Workspace.load(workspace)


def test_lock_and_cache_drift_are_rejected_offline(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package")
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("example", f"path:{package}", "1.0.0"),),
    )
    resolution = _resolve_and_lock(workspace, requirements)
    cached_source = resolution.packages[0].root / "entries" / "value.kirin"
    cached_source.write_text("tampered", encoding="utf-8")
    with pytest.raises(PackageError, match="content digest"):
        Workspace.load(workspace)


def test_failed_package_mutation_preserves_previous_requirements_and_lock(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    valid = _package(tmp_path / "valid")
    add_path_package(workspace, "valid", valid)
    requirements_before = (workspace / "kirin.packages.toml").read_bytes()
    lock_before = (workspace / "kirin.lock").read_bytes()

    invalid = _package(
        tmp_path / "invalid",
        name="community.invalid",
        namespace="community_invalid",
        document_id="wrong_prefix",
    )
    with pytest.raises(SchemaError, match="namespace prefix"):
        add_path_package(workspace, "invalid", invalid)
    assert (workspace / "kirin.packages.toml").read_bytes() == requirements_before
    assert (workspace / "kirin.lock").read_bytes() == lock_before


def test_remove_refuses_to_break_workspace_dependencies(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    package = _package(tmp_path / "package")
    add_path_package(workspace, "example", package)
    (workspace / "entries" / "consumer.kirin").write_text(
        """@kirin 1
@entry consumer

outputs:
  result: dimensionless = community_example_value.result + 1
""",
        encoding="utf-8",
    )
    requirements_before = (workspace / "kirin.packages.toml").read_bytes()
    lock_before = (workspace / "kirin.lock").read_bytes()
    with pytest.raises(ReferenceError, match="missing reference|undeclared variable"):
        remove_package(workspace, "example")
    assert (workspace / "kirin.packages.toml").read_bytes() == requirements_before
    assert (workspace / "kirin.lock").read_bytes() == lock_before


def test_dependency_version_conflicts_are_rejected(tmp_path: Path) -> None:
    shared = _package(tmp_path / "shared", name="community.shared", namespace="community_shared")
    dependency_one = f'''\n[dependencies.shared]\nsource = "path:{shared}"\nversion = "1.0.0"\n'''
    left = _package(
        tmp_path / "left",
        name="community.left",
        namespace="community_left",
        dependencies=dependency_one,
    )
    dependency_two = f'''\n[dependencies.shared]\nsource = "path:{shared}"\nversion = "2.0.0"\n'''
    right = _package(
        tmp_path / "right",
        name="community.right",
        namespace="community_right",
        dependencies=dependency_two,
    )
    workspace = initialize(tmp_path / "workspace")
    requirements = WorkspaceRequirements(
        workspace,
        (
            WorkspaceRequirement("left", f"path:{left}", "1.0.0"),
            WorkspaceRequirement("right", f"path:{right}", "1.0.0"),
        ),
    )
    with pytest.raises(PackageError, match="version conflict"):
        PackageResolver(PackageStoreManager(workspace)).resolve(requirements)


def test_duplicate_package_namespaces_and_dependency_cycles_are_rejected(tmp_path: Path) -> None:
    first = _package(tmp_path / "first", name="community.first", namespace="shared_namespace")
    second = _package(tmp_path / "second", name="community.second", namespace="shared_namespace")
    workspace = initialize(tmp_path / "workspace")
    duplicate_requirements = WorkspaceRequirements(
        workspace,
        (
            WorkspaceRequirement("first", f"path:{first}", "1.0.0"),
            WorkspaceRequirement("second", f"path:{second}", "1.0.0"),
        ),
    )
    with pytest.raises(PackageError, match="namespace .* claimed by both"):
        PackageResolver(PackageStoreManager(workspace)).resolve(duplicate_requirements)

    left = _package(tmp_path / "left-cycle", name="community.left", namespace="cycle_left")
    right = _package(tmp_path / "right-cycle", name="community.right", namespace="cycle_right")
    left_manifest = (left / "kirin.package.toml").read_text(encoding="utf-8")
    right_manifest = (right / "kirin.package.toml").read_text(encoding="utf-8")
    (left / "kirin.package.toml").write_text(
        left_manifest
        + f'\n[dependencies.right]\nsource = "path:{right}"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    (right / "kirin.package.toml").write_text(
        right_manifest
        + f'\n[dependencies.left]\nsource = "path:{left}"\nversion = "1.0.0"\n',
        encoding="utf-8",
    )
    cycle_requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("left", f"path:{left}", "1.0.0"),),
    )
    with pytest.raises(PackageError, match="dependency cycle"):
        PackageResolver(PackageStoreManager(workspace)).resolve(cycle_requirements)


def test_archive_extraction_rejects_links_and_parent_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        manifest = b"schema = 1\n"
        info = tarfile.TarInfo("repo/kirin.package.toml")
        info.size = len(manifest)
        handle.addfile(info, io.BytesIO(manifest))
        link = tarfile.TarInfo("repo/entries/link.kirin")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        handle.addfile(link)
    with pytest.raises(PackageError, match="link or device"):
        extract_github_archive(archive, tmp_path / "extract")

    traversal = tmp_path / "traversal.tar.gz"
    with tarfile.open(traversal, "w:gz") as handle:
        payload = b"bad"
        info = tarfile.TarInfo("../outside")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    with pytest.raises(PackageError, match="unsafe package archive path"):
        extract_github_archive(traversal, tmp_path / "extract-two")

    windows_traversal = tmp_path / "windows-traversal.tar.gz"
    with tarfile.open(windows_traversal, "w:gz") as handle:
        payload = b"bad"
        info = tarfile.TarInfo("repo\\..\\outside")
        info.size = len(payload)
        handle.addfile(info, io.BytesIO(payload))
    with pytest.raises(PackageError, match="unsafe package archive path"):
        extract_github_archive(windows_traversal, tmp_path / "extract-three")


def test_github_release_is_resolved_by_commit_and_cached_by_content(tmp_path: Path) -> None:
    package = _package(tmp_path / "source")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(package, arcname="repo-commit")

    class FakeGitHub:
        def __init__(self):
            self.resolved = []
            self.downloaded = []

        def resolve_release_commit(self, source: str, version: str) -> str:
            self.resolved.append((source, version))
            return "a" * 40

        def download_archive(self, source: str, commit: str, destination: Path) -> None:
            self.downloaded.append((source, commit))
            shutil.copyfile(archive, destination)

    github = FakeGitHub()
    workspace = initialize(tmp_path / "workspace")
    store = PackageStoreManager(workspace, github=github)  # type: ignore[arg-type]
    resolved = store.materialize("github:Community/Example", "1.0.0")
    assert resolved.source == "github:community/example"
    assert resolved.resolved == "a" * 40
    assert resolved.root == workspace / ".kirin" / "packages" / resolved.content_sha256
    assert github.resolved == [("github:community/example", "1.0.0")]
    assert github.downloaded == [("github:community/example", "a" * 40)]
    assert load_package_manifest(resolved.root).name == "community.example"


def test_github_release_resolution_requires_and_dereferences_a_tag() -> None:
    annotated = "c" * 40
    commit = "d" * 40

    class FakeClient(GitHubClient):
        def __init__(self):
            super().__init__(token="test")
            self.urls = []

        def _json_get(self, url: str):
            self.urls.append(url)
            if "/git/ref/tags/v1.2.3" in url:
                return {"object": {"type": "tag", "sha": annotated}}
            if url.endswith("/git/tags/" + annotated):
                return {"object": {"type": "commit", "sha": commit}}
            raise AssertionError(url)

    client = FakeClient()
    assert client.resolve_release_commit("github:community/example", "1.2.3") == commit
    assert "/git/ref/tags/v1.2.3" in client.urls[0]
    assert client.urls[1].endswith("/git/tags/" + annotated)


def test_restore_uses_locked_github_commit_without_resolving_tag(tmp_path: Path) -> None:
    package = _package(tmp_path / "source")
    archive = tmp_path / "release.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        handle.add(package, arcname="repo-commit")

    class InitialGitHub:
        def resolve_release_commit(self, source: str, version: str) -> str:
            return "b" * 40

        def download_archive(self, source: str, commit: str, destination: Path) -> None:
            shutil.copyfile(archive, destination)

    workspace = initialize(tmp_path / "workspace")
    requirements = WorkspaceRequirements(
        workspace,
        (WorkspaceRequirement("example", "github:community/example", "1.0.0"),),
    )
    write_workspace_requirements(requirements)
    initial = PackageResolver(
        PackageStoreManager(workspace, github=InitialGitHub())  # type: ignore[arg-type]
    ).resolve(requirements)
    write_package_lock(initial.lock)
    shutil.rmtree(initial.packages[0].root)

    class RestoreGitHub:
        def __init__(self):
            self.downloads = []

        def resolve_release_commit(self, source: str, version: str) -> str:
            raise AssertionError("restore must not resolve a mutable tag")

        def download_archive(self, source: str, commit: str, destination: Path) -> None:
            self.downloads.append((source, commit))
            shutil.copyfile(archive, destination)

    github = RestoreGitHub()
    restored = PackageResolver(
        PackageStoreManager(workspace, github=github)  # type: ignore[arg-type]
    ).restore_locked_workspace()
    assert restored.packages[0].resolved == "b" * 40
    assert github.downloads == [("github:community/example", "b" * 40)]


def test_lockfile_rejects_unsatisfied_direct_entry(tmp_path: Path) -> None:
    workspace = initialize(tmp_path / "workspace")
    path = workspace / "kirin.lock"
    path.write_text(
        json.dumps(
            {
                "lock_version": 1,
                "generated_by": "test",
                "direct": {"missing": {"source": "github:a/b", "version": "1.0.0"}},
                "packages": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(PackageError, match="not satisfied"):
        load_package_lock(workspace, required=True)
