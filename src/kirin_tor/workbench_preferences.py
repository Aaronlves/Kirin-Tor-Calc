"""User-local launch preferences for the browser workbench."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .errors import WorkspaceError


PREFERENCES_SCHEMA = 1
PREFERENCES_FILE = "workbench-preferences.json"
MAX_PREFERENCES_BYTES = 64 * 1024


def default_workbench_home() -> Path:
    configured = os.environ.get("KIRIN_WORKBENCH_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".config" / "kirin-tor").resolve()


def _preferences_path(home: Optional[Path] = None) -> Path:
    return (home or default_workbench_home()) / PREFERENCES_FILE


def load_default_workspace(home: Optional[Path] = None) -> Optional[Path]:
    """Load the last explicitly selected workbench root, if one exists."""
    path = _preferences_path(home)
    if not path.exists():
        return None
    try:
        if path.stat().st_size > MAX_PREFERENCES_BYTES:
            raise WorkspaceError(f"local workbench preferences are too large: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except WorkspaceError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkspaceError(
            f"cannot read local workbench preferences at {path}: {exc}"
        ) from exc
    if not isinstance(raw, dict) or set(raw) != {"schema", "default_workspace"}:
        raise WorkspaceError(f"invalid local workbench preferences at {path}")
    if raw.get("schema") != PREFERENCES_SCHEMA:
        raise WorkspaceError(
            f"local workbench preference schema must be {PREFERENCES_SCHEMA}: {path}"
        )
    workspace = raw.get("default_workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise WorkspaceError(f"invalid default workspace in local preferences at {path}")
    return Path(workspace).expanduser().resolve()


def save_default_workspace(root: Path, home: Optional[Path] = None) -> Path:
    """Atomically remember one resolved workspace root outside source authority."""
    path = _preferences_path(home)
    text = json.dumps(
        {
            "schema": PREFERENCES_SCHEMA,
            "default_workspace": str(root.expanduser().resolve()),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    temporary: Optional[Path] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise WorkspaceError(
            f"cannot save local workbench preferences at {path}: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
