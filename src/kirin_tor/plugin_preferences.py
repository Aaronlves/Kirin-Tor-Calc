"""Bounded user-local preferences for sandboxed Workbench Plugins."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping, Optional

from .errors import InvalidRequestError, LimitExceededError, PluginError
from .limits import (
    MAX_PLUGIN_PREFERENCE_BYTES,
    MAX_PLUGIN_PREFERENCE_DEPTH,
    MAX_PLUGIN_PREFERENCE_KEY_CHARS,
    MAX_PLUGIN_PREFERENCE_KEYS,
    MAX_PLUGIN_PREFERENCE_VALUE_BYTES,
    MAX_PLUGIN_IDENTITY_CHARS,
)
from .package_manifest import atomic_write_text
from .plugin_manifest import PLUGIN_ID_RE
from .plugin_store import default_plugin_home


PREFERENCE_STORE_SCHEMA = 1
PREFERENCE_DIRECTORY = "plugin-preferences-v1"
PREFERENCE_KEY_RE = re.compile(
    rf"^[A-Za-z][A-Za-z0-9._-]{{0,{MAX_PLUGIN_PREFERENCE_KEY_CHARS - 1}}}$"
)


def _bounded_key(value: object, label: str = "preference key") -> str:
    if not isinstance(value, str) or not PREFERENCE_KEY_RE.fullmatch(value):
        raise InvalidRequestError(
            f"{label} must begin with a letter and contain only letters, digits, '.', '_' or '-'"
        )
    return value


def _json_value(value: object, *, depth: int = 0) -> Any:
    if depth > MAX_PLUGIN_PREFERENCE_DEPTH:
        raise LimitExceededError(
            f"preference value exceeds nesting depth {MAX_PLUGIN_PREFERENCE_DEPTH}"
        )
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidRequestError("preference numbers must be finite")
        return value
    if isinstance(value, list):
        if len(value) > MAX_PLUGIN_PREFERENCE_KEYS:
            raise LimitExceededError("preference array has too many items")
        return [_json_value(item, depth=depth + 1) for item in value]
    if isinstance(value, Mapping):
        if len(value) > MAX_PLUGIN_PREFERENCE_KEYS:
            raise LimitExceededError("preference object has too many fields")
        result = {}
        for key, item in value.items():
            result[_bounded_key(key, "preference object key")] = _json_value(
                item, depth=depth + 1
            )
        return result
    raise InvalidRequestError("preference value must be JSON-safe data")


def _encoded(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class PluginPreferences:
    """Store one workspace/Plugin namespace outside editable source authority."""

    def __init__(self, workspace: Path, home: Optional[Path] = None):
        workspace_id = hashlib.sha256(
            str(workspace.expanduser().resolve()).encode("utf-8")
        ).hexdigest()
        self.root = (home or default_plugin_home()).expanduser().resolve()
        self.directory = self.root / PREFERENCE_DIRECTORY / workspace_id

    def _path(self, plugin_id: str) -> Path:
        if (
            not isinstance(plugin_id, str)
            or len(plugin_id) > MAX_PLUGIN_IDENTITY_CHARS
            or not PLUGIN_ID_RE.fullmatch(plugin_id)
        ):
            raise InvalidRequestError("Plugin ID is invalid")
        return self.directory / f"{plugin_id}.json"

    def _load(self, plugin_id: str, preference_schema: int) -> dict[str, Any]:
        path = self._path(plugin_id)
        if not path.exists():
            return {}
        try:
            if path.stat().st_size > MAX_PLUGIN_PREFERENCE_BYTES + 4_096:
                raise PluginError("local Plugin preferences exceed their storage envelope")
            raw = json.loads(path.read_text(encoding="utf-8"))
        except PluginError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"cannot read local Plugin preferences: {exc}") from exc
        if not isinstance(raw, dict) or set(raw) != {
            "schema",
            "plugin_id",
            "preference_schema",
            "values",
        }:
            raise PluginError("local Plugin preferences have unknown or missing fields")
        if raw.get("schema") != PREFERENCE_STORE_SCHEMA or raw.get("plugin_id") != plugin_id:
            raise PluginError("local Plugin preference identity is invalid")
        stored_schema = raw.get("preference_schema")
        if not isinstance(stored_schema, int) or isinstance(stored_schema, bool):
            raise PluginError("local Plugin preference schema is invalid")
        if stored_schema != preference_schema:
            self._write(plugin_id, preference_schema, {})
            return {}
        values = raw.get("values")
        if not isinstance(values, dict) or len(values) > MAX_PLUGIN_PREFERENCE_KEYS:
            raise PluginError("local Plugin preference values are invalid")
        normalized = {
            _bounded_key(key): _json_value(value)
            for key, value in values.items()
        }
        if len(_encoded(normalized)) > MAX_PLUGIN_PREFERENCE_BYTES:
            raise PluginError("local Plugin preferences exceed their storage quota")
        return normalized

    def _write(
        self,
        plugin_id: str,
        preference_schema: int,
        values: Mapping[str, object],
    ) -> None:
        normalized = dict(values)
        if len(_encoded(normalized)) > MAX_PLUGIN_PREFERENCE_BYTES:
            raise LimitExceededError(
                f"Plugin preferences exceed {MAX_PLUGIN_PREFERENCE_BYTES} bytes"
            )
        text = json.dumps(
            {
                "schema": PREFERENCE_STORE_SCHEMA,
                "plugin_id": plugin_id,
                "preference_schema": preference_schema,
                "values": normalized,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ) + "\n"
        atomic_write_text(self._path(plugin_id), text)

    def get(self, plugin_id: str, preference_schema: int, key: object) -> dict:
        name = _bounded_key(key)
        values = self._load(plugin_id, preference_schema)
        return {
            "status": "ok",
            "key": name,
            "found": name in values,
            **({"value": values[name]} if name in values else {}),
        }

    def set(
        self,
        plugin_id: str,
        preference_schema: int,
        key: object,
        value: object,
    ) -> dict:
        name = _bounded_key(key)
        normalized = _json_value(value)
        if len(_encoded(normalized)) > MAX_PLUGIN_PREFERENCE_VALUE_BYTES:
            raise LimitExceededError(
                f"preference value exceeds {MAX_PLUGIN_PREFERENCE_VALUE_BYTES} bytes"
            )
        values = self._load(plugin_id, preference_schema)
        if name not in values and len(values) >= MAX_PLUGIN_PREFERENCE_KEYS:
            raise LimitExceededError(
                f"Plugin preferences exceed {MAX_PLUGIN_PREFERENCE_KEYS} keys"
            )
        values[name] = normalized
        self._write(plugin_id, preference_schema, values)
        return {
            "status": "ok",
            "key": name,
            "bytes": len(_encoded(values)),
        }

    def delete(self, plugin_id: str, preference_schema: int, key: object) -> dict:
        name = _bounded_key(key)
        values = self._load(plugin_id, preference_schema)
        removed = name in values
        values.pop(name, None)
        self._write(plugin_id, preference_schema, values)
        return {"status": "ok", "key": name, "removed": removed}

    def clear(self, plugin_id: str) -> bool:
        path = self._path(plugin_id)
        if not path.exists():
            return False
        path.unlink()
        return True
