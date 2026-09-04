"""Transactional local installation and activation for Workbench Plugins."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Tuple

from .errors import (
    PackageError,
    PermissionDeniedError,
    PluginDisabledError,
    PluginError,
    WorkspaceError,
)
from .package_manifest import atomic_write_text, current_feature_line
from .package_store import PackageResolution, locked_workspace_resolution
from .plugin_manifest import (
    PLUGIN_ALIAS_RE,
    PLUGIN_STORE,
    LockedPlugin,
    PluginLock,
    PluginManifest,
    PluginRequirement,
    PluginRequirements,
    SHA256_RE,
    canonical_plugin_sha256,
    load_plugin_lock,
    load_plugin_manifest,
    load_plugin_requirements,
    normalize_plugin_source,
    render_plugin_lock,
    render_plugin_requirements,
)
from .plugin_protocol import PLUGIN_API_VERSION, plugin_protocol_descriptor


APPROVAL_SCHEMA = 1
APPROVAL_FILE = "plugin-approvals.json"


def default_plugin_home() -> Path:
    configured = os.environ.get("KIRIN_PLUGIN_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".config" / "kirin-tor").resolve()


class PluginApprovals:
    """User-local executable approvals keyed by immutable content digest."""

    def __init__(self, home: Optional[Path] = None):
        self.home = (home or default_plugin_home()).expanduser().resolve()
        self.path = self.home / APPROVAL_FILE

    def load(self) -> set[str]:
        if not self.path.exists():
            return set()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"invalid local plugin approval registry: {exc}") from exc
        if not isinstance(raw, dict) or set(raw) != {"schema", "approved_content_sha256"}:
            raise PluginError("local plugin approval registry has unknown or missing fields")
        if raw.get("schema") != APPROVAL_SCHEMA:
            raise PluginError(f"local plugin approval schema must be {APPROVAL_SCHEMA}")
        values = raw.get("approved_content_sha256")
        if not isinstance(values, list) or any(
            not isinstance(item, str) or not SHA256_RE.fullmatch(item) for item in values
        ):
            raise PluginError("local plugin approval digests are invalid")
        return set(values)

    def approve(self, digest: str) -> None:
        approved = self.load()
        approved.add(digest)
        text = json.dumps(
            {
                "schema": APPROVAL_SCHEMA,
                "approved_content_sha256": sorted(approved),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
        atomic_write_text(self.path, text)

    def is_approved(self, digest: str) -> bool:
        return digest in self.load()


@dataclass(frozen=True)
class ResolvedPlugin:
    requirement: PluginRequirement
    locked: Optional[LockedPlugin]
    root: Optional[Path]
    manifest: Optional[PluginManifest]
    status: str
    approved: bool
    active: bool
    error: Optional[str] = None
    compatibility: Optional[dict] = None

    def as_dict(self) -> dict:
        locked = self.locked
        manifest = self.manifest
        return {
            "alias": self.requirement.alias,
            "source": self.requirement.source,
            "requested_version": self.requirement.version,
            "enabled": self.requirement.enabled,
            "id": manifest.id if manifest else locked.id if locked else None,
            "name": manifest.name if manifest else locked.name if locked else None,
            "version": manifest.version if manifest else locked.version if locked else None,
            "api": manifest.api if manifest else None,
            "description": manifest.description if manifest else None,
            "license": manifest.license if manifest else None,
            "requires": manifest.requires.as_dict() if manifest else None,
            "storage": manifest.storage.as_dict() if manifest and manifest.storage else None,
            "content_sha256": locked.content_sha256 if locked else None,
            "approved": self.approved,
            "active": self.active,
            "status": self.status,
            "error": self.error,
            "compatibility": self.compatibility,
        }


def _package_provider(package, interface) -> dict:
    return {
        "interface": {"id": interface.id, "revision": interface.revision},
        "package": package.manifest.name,
        "version": package.manifest.version,
        "source": package.source,
        "resolved": package.resolved,
        "content_sha256": package.content_sha256,
    }


def plugin_compatibility(
    manifest: PluginManifest,
    resolution: Optional[PackageResolution],
    package_error: Optional[str] = None,
) -> dict:
    """Resolve strict Plugin feature/interface requirements without activating code."""

    current_feature = current_feature_line()
    feature_status = (
        "satisfied"
        if manifest.requires.kirin_feature == current_feature
        else "kirin-incompatible"
    )
    interface_results = []
    for requirement in manifest.requires.interfaces:
        if package_error is not None:
            interface_results.append(
                {
                    **requirement.as_dict(),
                    "status": "invalid-provider",
                    "providers": [],
                    "error": package_error,
                }
            )
            continue
        candidates = [
            (package, interface)
            for package in (resolution.packages if resolution is not None else ())
            for interface in package.manifest.interfaces
            if interface.id == requirement.id
        ]
        exact = [
            (package, interface)
            for package, interface in candidates
            if interface.revision == requirement.revision
        ]
        if len(exact) > 1:
            status = "ambiguous"
        elif len(exact) == 1:
            status = "satisfied"
        elif candidates:
            status = "revision-mismatch"
        else:
            status = "missing"
        interface_results.append(
            {
                **requirement.as_dict(),
                "status": status,
                "providers": [
                    _package_provider(package, interface)
                    for package, interface in sorted(
                        candidates,
                        key=lambda item: (
                            item[1].revision,
                            item[0].source,
                        ),
                    )
                ],
                "error": None,
            }
        )
    compatible = feature_status == "satisfied" and all(
        item["status"] == "satisfied" for item in interface_results
    )
    return {
        "status": "satisfied" if compatible else "incompatible",
        "compatible": compatible,
        "kirin_feature": {
            "required": manifest.requires.kirin_feature,
            "current": current_feature,
            "status": feature_status,
        },
        "interfaces": interface_results,
    }


class PluginManager:
    """Resolve immutable plugin snapshots and expose only approved active contributions."""

    def __init__(
        self,
        root: Path,
        *,
        safe_mode: bool = False,
        approval_home: Optional[Path] = None,
    ):
        self.root = root.expanduser().resolve()
        self.safe_mode = safe_mode
        self.store = self.root / PLUGIN_STORE
        self.approvals = PluginApprovals(approval_home)

    def _require_workspace(self) -> None:
        if not (self.root / "kirin.workspace").is_file():
            raise WorkspaceError(f"{self.root} is not a Kirin Tor workspace")

    def _snapshot(self, source_root: Path) -> tuple[PluginManifest, str, Path]:
        source_root = source_root.expanduser().resolve()
        manifest = load_plugin_manifest(source_root)
        digest = canonical_plugin_sha256(source_root)
        self.store.parent.mkdir(parents=True, exist_ok=True)
        target = self.store / digest
        if target.exists():
            if target.is_symlink() or not target.is_dir():
                raise PluginError(f"plugin store target is not a real directory: {target}")
            if canonical_plugin_sha256(target) != digest:
                raise PluginError(f"cached plugin content failed its digest: {digest}")
            return manifest, digest, target
        stage_parent = Path(
            tempfile.mkdtemp(prefix=".plugin-stage-", dir=str(self.store.parent))
        )
        staged = stage_parent / "bundle"
        try:
            shutil.copytree(source_root, staged, copy_function=shutil.copy2)
            staged_manifest = load_plugin_manifest(staged)
            staged_digest = canonical_plugin_sha256(staged)
            if staged_manifest.id != manifest.id or staged_digest != digest:
                raise PluginError("plugin source changed while its immutable snapshot was staged")
            self.store.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(staged, target)
            except FileExistsError:
                if canonical_plugin_sha256(target) != digest:
                    raise PluginError(f"concurrent plugin snapshot failed its digest: {digest}")
        finally:
            shutil.rmtree(stage_parent, ignore_errors=True)
        return manifest, digest, target

    @staticmethod
    def _write_transaction(requirements: PluginRequirements, lock: PluginLock) -> None:
        requirement_path = requirements.path
        lock_path = lock.path
        previous_requirements = requirement_path.read_bytes() if requirement_path.exists() else None
        previous_lock = lock_path.read_bytes() if lock_path.exists() else None
        try:
            atomic_write_text(requirement_path, render_plugin_requirements(requirements))
            atomic_write_text(lock_path, render_plugin_lock(lock))
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

    def add_path(self, alias: str, source_root: Path) -> dict:
        self._require_workspace()
        if not PLUGIN_ALIAS_RE.fullmatch(alias):
            raise PluginError("plugin alias must match [a-z][a-z0-9_]*")
        requirements = load_plugin_requirements(self.root)
        lock = load_plugin_lock(self.root)
        if alias in requirements.by_alias():
            raise PluginError(f"plugin alias {alias!r} already exists")
        source_root = source_root.expanduser().resolve()
        source = normalize_plugin_source(f"path:{source_root}", relative_to=self.root)
        if any(item.source == source for item in requirements.plugins):
            raise PluginError(f"plugin source {source!r} is already requested")
        manifest, digest, _target = self._snapshot(source_root)
        if any(item.id == manifest.id for item in lock.plugins):
            raise PluginError(f"plugin id {manifest.id!r} is already installed")
        updated_requirements = PluginRequirements(
            self.root,
            tuple(
                sorted(
                    (
                        *requirements.plugins,
                        PluginRequirement(alias, source, manifest.version, True),
                    ),
                    key=lambda item: item.alias,
                )
            ),
        )
        updated_lock = PluginLock(
            self.root,
            tuple(
                sorted(
                    (
                        *lock.plugins,
                        LockedPlugin(
                            alias,
                            source,
                            manifest.id,
                            manifest.name,
                            manifest.version,
                            digest,
                        ),
                    ),
                    key=lambda item: item.alias,
                )
            ),
        )
        self.approvals.approve(digest)
        self._write_transaction(updated_requirements, updated_lock)
        return self.summary()

    def update_path(self, alias: str) -> dict:
        self._require_workspace()
        requirements = load_plugin_requirements(self.root)
        lock = load_plugin_lock(self.root, required=True)
        requirement = requirements.by_alias().get(alias)
        locked = lock.by_alias().get(alias)
        if requirement is None or locked is None:
            raise PluginError(f"unknown installed plugin alias {alias!r}")
        source_root = Path(requirement.source.removeprefix("path:"))
        manifest, digest, _target = self._snapshot(source_root)
        if manifest.id != locked.id:
            raise PluginError(
                f"plugin update changed id from {locked.id!r} to {manifest.id!r}"
            )
        updated_requirements = PluginRequirements(
            self.root,
            tuple(
                PluginRequirement(item.alias, item.source, manifest.version, item.enabled)
                if item.alias == alias
                else item
                for item in requirements.plugins
            ),
        )
        updated_lock = PluginLock(
            self.root,
            tuple(
                LockedPlugin(
                    item.alias,
                    item.source,
                    manifest.id,
                    manifest.name,
                    manifest.version,
                    digest,
                )
                if item.alias == alias
                else item
                for item in lock.plugins
            ),
        )
        self.approvals.approve(digest)
        self._write_transaction(updated_requirements, updated_lock)
        return self.summary()

    def set_enabled(self, alias: str, enabled: bool) -> dict:
        self._require_workspace()
        requirements = load_plugin_requirements(self.root)
        if alias not in requirements.by_alias():
            raise PluginError(f"unknown installed plugin alias {alias!r}")
        if enabled:
            current = next(
                (
                    item
                    for item in self.resolved(include_disabled_approvals=True)
                    if item.requirement.alias == alias
                ),
                None,
            )
            if current is None or current.manifest is None or current.locked is None:
                raise PluginError(f"plugin {alias!r} has no valid immutable snapshot")
            if not current.approved:
                raise PluginError(
                    f"plugin {alias!r} content is not approved by the current local user"
                )
        updated = PluginRequirements(
            self.root,
            tuple(
                PluginRequirement(item.alias, item.source, item.version, enabled)
                if item.alias == alias
                else item
                for item in requirements.plugins
            ),
        )
        self._write_transaction(updated, load_plugin_lock(self.root, required=True))
        return self.summary()

    def remove(self, alias: str) -> dict:
        self._require_workspace()
        requirements = load_plugin_requirements(self.root)
        lock = load_plugin_lock(self.root, required=True)
        if alias not in requirements.by_alias():
            raise PluginError(f"unknown installed plugin alias {alias!r}")
        self._write_transaction(
            PluginRequirements(
                self.root, tuple(item for item in requirements.plugins if item.alias != alias)
            ),
            PluginLock(self.root, tuple(item for item in lock.plugins if item.alias != alias)),
        )
        return self.summary()

    def resolved(
        self, *, include_disabled_approvals: bool = False
    ) -> Tuple[ResolvedPlugin, ...]:
        requirements = load_plugin_requirements(self.root)
        lock = load_plugin_lock(self.root)
        locked_by_alias = lock.by_alias()
        approved = (
            self.approvals.load()
            if not self.safe_mode
            and (
                include_disabled_approvals
                or any(item.enabled for item in requirements.plugins)
            )
            else set()
        )
        try:
            package_resolution = locked_workspace_resolution(self.root)
            package_error = None
        except PackageError as exc:
            package_resolution = None
            package_error = str(exc)
        result = []
        for requirement in requirements.plugins:
            locked = locked_by_alias.get(requirement.alias)
            if locked is None:
                result.append(
                    ResolvedPlugin(
                        requirement,
                        None,
                        None,
                        None,
                        "missing-lock",
                        False,
                        False,
                        "plugin has no locked immutable snapshot",
                    )
                )
                continue
            root = self.store / locked.content_sha256
            try:
                if not root.is_dir() or root.is_symlink():
                    raise PluginError("locked plugin snapshot is missing")
                actual_digest = canonical_plugin_sha256(root)
                if actual_digest != locked.content_sha256:
                    raise PluginError("locked plugin snapshot failed its content digest")
                manifest = load_plugin_manifest(root)
                if (
                    manifest.id != locked.id
                    or manifest.name != locked.name
                    or manifest.version != locked.version
                    or manifest.version != requirement.version
                    or requirement.source != locked.source
                ):
                    raise PluginError("plugin requirements, lock, and manifest identity disagree")
                is_approved = locked.content_sha256 in approved
                compatibility = plugin_compatibility(
                    manifest,
                    package_resolution,
                    package_error,
                )
                if not requirement.enabled:
                    status = "disabled"
                    active = False
                elif self.safe_mode:
                    status = "safe-mode"
                    active = False
                elif not is_approved:
                    status = "unapproved"
                    active = False
                elif not compatibility["compatible"]:
                    status = "incompatible"
                    active = False
                else:
                    status = "active"
                    active = True
                result.append(
                    ResolvedPlugin(
                        requirement,
                        locked,
                        root,
                        manifest,
                        status,
                        is_approved,
                        active,
                        compatibility=compatibility,
                    )
                )
            except PluginError as exc:
                result.append(
                    ResolvedPlugin(
                        requirement,
                        locked,
                        root,
                        None,
                        "invalid",
                        locked.content_sha256 in approved,
                        False,
                        str(exc),
                    )
                )
        unused_locks = sorted(set(locked_by_alias) - set(requirements.by_alias()))
        if unused_locks:
            raise PluginError(
                "plugin lock contains undeclared aliases: " + ", ".join(unused_locks)
            )
        return tuple(result)

    def verify(self) -> dict:
        result = self.resolved()
        invalid = [item for item in result if item.status in {"invalid", "missing-lock"}]
        if invalid:
            raise PluginError(
                "; ".join(
                    f"{item.requirement.alias}: {item.error or item.status}" for item in invalid
                )
            )
        return self.summary(resolved=result)

    def authorize_contribution(
        self,
        plugin_id: str,
        content_sha256: str,
        contribution_id: str,
        permission: str,
    ) -> PluginManifest:
        """Resolve one active immutable frame identity and enforce its permission."""

        if self.safe_mode:
            raise PluginDisabledError("Plugin capabilities are unavailable in Safe Mode")
        for item in self.resolved():
            if (
                not item.active
                or item.manifest is None
                or item.locked is None
                or item.manifest.id != plugin_id
                or item.locked.content_sha256 != content_sha256
            ):
                continue
            surfaces = (
                *item.manifest.contributes.renderers,
                *item.manifest.contributes.views,
                *item.manifest.contributes.tools,
            )
            contribution = next(
                (candidate for candidate in surfaces if candidate.id == contribution_id),
                None,
            )
            if contribution is None:
                raise PluginDisabledError(
                    "Plugin contribution is not active for this content snapshot"
                )
            if permission not in contribution.permissions:
                raise PermissionDeniedError(
                    f"Plugin contribution did not declare {permission}"
                )
            return item.manifest
        raise PluginDisabledError(
            "Plugin is disabled, unapproved, incompatible, or no longer current"
        )

    def summary(self, *, resolved: Optional[Tuple[ResolvedPlugin, ...]] = None) -> dict:
        contributions = {
            "renderers": [],
            "views": [],
            "tools": [],
            "commands": [],
            "profiles": [],
        }
        try:
            items = resolved if resolved is not None else self.resolved()
        except PluginError as exc:
            return {
                "safe_mode": self.safe_mode,
                "protocol": plugin_protocol_descriptor(),
                "plugins": [],
                "contributions": contributions,
                "error": str(exc),
            }
        active_ids = set()
        for item in items:
            if not item.active or item.manifest is None or item.locked is None:
                continue
            if item.manifest.id in active_ids:
                raise PluginError(f"duplicate active plugin id {item.manifest.id!r}")
            active_ids.add(item.manifest.id)
            plugin_meta = {
                "plugin_id": item.manifest.id,
                "plugin_name": item.manifest.name,
                "plugin_version": item.manifest.version,
                "content_sha256": item.locked.content_sha256,
                "api": PLUGIN_API_VERSION,
                "required_interfaces": [
                    item.as_dict() for item in item.manifest.requires.interfaces
                ],
                "storage_schema": (
                    item.manifest.storage.preferences.schema
                    if item.manifest.storage
                    and item.manifest.storage.preferences
                    else None
                ),
            }
            for key in contributions:
                group = getattr(item.manifest.contributes, key)
                for contribution in group:
                    value = {**contribution.as_dict(), **plugin_meta}
                    if key in {"renderers", "views", "tools"}:
                        value["entry_url"] = (
                            f"/plugins/{item.locked.content_sha256}/{contribution.entry}"
                        )
                    contributions[key].append(value)
        contributions["renderers"].sort(key=lambda item: (-item["priority"], item["id"]))
        for key in ("views", "tools", "commands", "profiles"):
            contributions[key].sort(key=lambda item: item["id"])
        return {
            "safe_mode": self.safe_mode,
            "protocol": plugin_protocol_descriptor(),
            "plugins": [item.as_dict() for item in items],
            "contributions": contributions,
            "error": None,
        }

    def asset(self, digest: str, relative: str) -> Path:
        active = {
            item.locked.content_sha256: item
            for item in self.resolved()
            if item.active and item.locked is not None
        }
        selected = active.get(digest)
        if selected is None or selected.root is None:
            raise PluginError("plugin asset is not available from an active approved plugin")
        if "\\" in relative:
            raise PluginError("plugin asset path must use forward slashes")
        pure = PurePosixPath(relative)
        if pure.is_absolute() or not pure.parts or ".." in pure.parts:
            raise PluginError("plugin asset path is invalid")
        path = selected.root.joinpath(*pure.parts)
        if path.is_symlink() or not path.is_file():
            raise PluginError("plugin asset was not found")
        try:
            path.resolve().relative_to(selected.root)
        except ValueError as exc:
            raise PluginError("plugin asset leaves its immutable root") from exc
        return path
