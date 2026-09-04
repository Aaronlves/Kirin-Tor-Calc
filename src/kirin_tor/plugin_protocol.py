"""Single-source public capability contract for Workbench Plugin protocol v2."""

from __future__ import annotations

from copy import deepcopy
from typing import Final

from .limits import (
    DEFAULT_MODEL_QUERY_LIMIT,
    MAX_CATALOG_SUMMARY_INTERFACES,
    MAX_COMPARISON_VARIANTS,
    MAX_EXPRESSION_LENGTH,
    MAX_MODEL_CURSOR_CHARS,
    MAX_MODEL_DEPENDENCY_DEPTH,
    MAX_MODEL_QUERY_LIMIT,
    MAX_PLUGIN_ACTION_ID_CHARS,
    MAX_PLUGIN_DESCRIPTION_CHARS,
    MAX_PLUGIN_PENDING_PROPOSALS,
    MAX_PLUGIN_DRAFT_SOURCE_BYTES,
    MAX_PLUGIN_IDENTITY_CHARS,
    MAX_PLUGIN_INTERFACE_REQUIREMENTS,
    MAX_PLUGIN_JOBS_PER_CONTRIBUTION,
    MAX_PLUGIN_MESSAGE_CHARS,
    MAX_PLUGIN_MODEL_CHARS_PER_GROUP,
    MAX_PLUGIN_MODEL_ITEMS_PER_GROUP,
    MAX_PLUGIN_OPERATION_TARGETS,
    MAX_PLUGIN_PATH_CHARS,
    MAX_PLUGIN_PREFERENCE_BYTES,
    MAX_PLUGIN_PREFERENCE_DEPTH,
    MAX_PLUGIN_PREFERENCE_KEY_CHARS,
    MAX_PLUGIN_PREFERENCE_KEYS,
    MAX_PLUGIN_PREFERENCE_VALUE_BYTES,
    MAX_PLUGIN_PROPOSAL_BYTES,
    MAX_PLUGIN_PROPOSAL_CHANGES,
    MAX_PLUGIN_TARGET_INPUTS,
    MAX_PLUGIN_TEMPLATE_BINDINGS,
    MAX_PLUGIN_TITLE_CHARS,
    MAX_PLUGIN_VARIANT_NAME_CHARS,
    MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS,
    MAX_SCAN_POINTS,
    MAX_WORKBENCH_OPERATION_JOBS,
    PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS,
)


PLUGIN_API_VERSION: Final = "2"
PLUGIN_PROTOCOL_NAME: Final = "kirin-workbench-plugin"

PLUGIN_ERROR_CODES: Final = {
    "permission_denied": "the contribution did not declare the required permission",
    "unsupported_capability": "the current host does not provide the requested capability",
    "invalid_request": "the request does not satisfy the public action schema",
    "unknown_identity": "a requested canonical identity does not exist",
    "interface_unavailable": "a required model interface is unavailable",
    "stale_revision": "the request targets an obsolete workspace revision",
    "limit_exceeded": "the request exceeds a published hard limit",
    "result_too_large": "the response cannot fit the plugin message envelope",
    "workspace_invalid": "the current workspace overlay cannot be calculated",
    "proposal_invalid": "a proposed workspace candidate is invalid",
    "proposal_stale": "a proposal baseline changed before acceptance",
    "job_cancelled": "the operation job was explicitly cancelled",
    "operation_failed": "the mathematical service returned a structured failure",
    "plugin_disabled": "the plugin is no longer active or approved",
}

PLUGIN_CONTEXT_PERMISSIONS: Final = frozenset(
    {
        "workspace.summary",
        "model.read",
        "document.read",
        "draft.read",
        "template.read",
    }
)


def _object(properties: dict, required: tuple[str, ...] = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_REVISION = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_IDENTITY = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_PLUGIN_IDENTITY_CHARS,
}
_EXPRESSION = {
    "type": "string",
    "minLength": 1,
    "maxLength": MAX_EXPRESSION_LENGTH,
}
_OPTIONAL_IDENTITY = {"oneOf": [_IDENTITY, {"type": "null"}]}
_OVERRIDES = {
    "type": "object",
    "maxProperties": MAX_PLUGIN_TARGET_INPUTS,
    "additionalProperties": _EXPRESSION,
}
_TARGETS = {
    "type": "array",
    "minItems": 1,
    "maxItems": MAX_PLUGIN_OPERATION_TARGETS,
    "uniqueItems": True,
    "items": _IDENTITY,
}
_VARIANT = _object(
    {
        "name": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_PLUGIN_VARIANT_NAME_CHARS,
        },
        "preset": _OPTIONAL_IDENTITY,
        "overrides": _OVERRIDES,
    },
    ("name",),
)
_PROPOSAL_CHANGE = {
    "oneOf": [
        _object(
            {
                "kind": {"const": "create-from-template"},
                "template": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_PATH_CHARS,
                },
                "document_id": _IDENTITY,
                "bindings": {
                    "type": "object",
                    "maxProperties": MAX_PLUGIN_TEMPLATE_BINDINGS,
                    "additionalProperties": _EXPRESSION,
                },
            },
            ("kind", "template", "document_id"),
        ),
        _object(
            {
                "kind": {"const": "create-document"},
                "document_id": _IDENTITY,
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_DRAFT_SOURCE_BYTES,
                },
            },
            ("kind", "document_id", "text"),
        ),
        _object(
            {
                "kind": {"const": "replace-document"},
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_PATH_CHARS,
                },
                "base_sha256": _SHA256,
                "text": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_DRAFT_SOURCE_BYTES,
                },
            },
            ("kind", "key", "base_sha256", "text"),
        ),
    ]
}
_RESULT = {"$ref": "protocol.schema.json#/$defs/actionResult"}
_OPERATION_RESULT = {"$ref": "protocol.schema.json#/$defs/operationEnvelope"}
_JOB_RESULT = {"$ref": "protocol.schema.json#/$defs/job"}


def _capability(
    permission: str,
    handler: str,
    request_schema: dict,
    *,
    operation: str | None = None,
    execution: str = "sync",
    timeout_class: str = "none",
    hard_limits: dict | None = None,
    allow_unsaved_overlays: bool = False,
    allow_durable_run: bool = False,
    allow_artifacts: bool = False,
    unload_policy: str = "none",
) -> dict:
    result = {
        "permission": permission,
        "handler": handler,
        "execution": execution,
        "timeout_class": timeout_class,
        "request_schema": request_schema,
        "result_schema": (
            _JOB_RESULT
            if handler == "job" or (handler == "operation" and execution == "job")
            else _OPERATION_RESULT
            if handler == "operation"
            else _RESULT
        ),
        "hard_limits": hard_limits or {},
        "allow_unsaved_overlays": allow_unsaved_overlays,
        "allow_durable_run": allow_durable_run,
        "allow_artifacts": allow_artifacts,
        "unload_policy": unload_policy,
    }
    if operation is not None:
        result["operation"] = operation
    return result


_OPERATION_COMMON = {
    "revision": _REVISION,
    "preset": _OPTIONAL_IDENTITY,
    "overrides": _OVERRIDES,
}

PLUGIN_ACTIONS: Final = {
    "navigate-source": _capability(
        "source.navigate",
        "host",
        _object(
            {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_PATH_CHARS,
                },
                "line": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            },
            ("key",),
        ),
    ),
    "proposal.submit": _capability(
        "proposal.submit",
        "proposal",
        _object(
            {
                "revision": _REVISION,
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_TITLE_CHARS,
                },
                "description": {
                    "type": "string",
                    "maxLength": MAX_PLUGIN_DESCRIPTION_CHARS,
                },
                "changes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_PLUGIN_PROPOSAL_CHANGES,
                    "items": _PROPOSAL_CHANGE,
                },
            },
            ("revision", "title", "changes"),
        ),
        hard_limits={
            "changes": MAX_PLUGIN_PROPOSAL_CHANGES,
            "bytes": MAX_PLUGIN_PROPOSAL_BYTES,
            "bindings": MAX_PLUGIN_TEMPLATE_BINDINGS,
        },
        allow_unsaved_overlays=True,
    ),
    "result.present": _capability(
        "result.present",
        "result",
        _object(
            {
                "handle": _IDENTITY,
                "title": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_TITLE_CHARS,
                },
                "order": {"type": "integer", "minimum": -100, "maximum": 100},
            },
            ("handle",),
        ),
    ),
    "storage.get": _capability(
        "storage.preferences",
        "storage",
        _object(
            {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_PREFERENCE_KEY_CHARS,
                    "pattern": "^[A-Za-z][A-Za-z0-9._-]*$",
                }
            },
            ("key",),
        ),
    ),
    "storage.set": _capability(
        "storage.preferences",
        "storage",
        _object(
            {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_PREFERENCE_KEY_CHARS,
                    "pattern": "^[A-Za-z][A-Za-z0-9._-]*$",
                },
                "value": {},
            },
            ("key", "value"),
        ),
        hard_limits={"value_bytes": MAX_PLUGIN_PREFERENCE_VALUE_BYTES},
    ),
    "storage.delete": _capability(
        "storage.preferences",
        "storage",
        _object(
            {
                "key": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_PLUGIN_PREFERENCE_KEY_CHARS,
                    "pattern": "^[A-Za-z][A-Za-z0-9._-]*$",
                }
            },
            ("key",),
        ),
    ),
    "evaluate": _capability(
        "operation.evaluate",
        "operation",
        _object(
            {**_OPERATION_COMMON, "target": _IDENTITY},
            ("revision", "target"),
        ),
        operation="eval",
        timeout_class="standard",
        allow_unsaved_overlays=True,
    ),
    "evaluate-many": _capability(
        "operation.evaluate",
        "operation",
        _object(
            {**_OPERATION_COMMON, "targets": _TARGETS},
            ("revision", "targets"),
        ),
        operation="evaluate_many",
        timeout_class="standard",
        hard_limits={"targets": MAX_PLUGIN_OPERATION_TARGETS},
        allow_unsaved_overlays=True,
    ),
    "explain": _capability(
        "operation.explain",
        "operation",
        _object(
            {"revision": _REVISION, "target": _IDENTITY},
            ("revision", "target"),
        ),
        operation="explain",
        timeout_class="standard",
        allow_unsaved_overlays=True,
    ),
    "compare": _capability(
        "operation.compare",
        "operation",
        _object(
            {
                "revision": _REVISION,
                "target": _IDENTITY,
                "variants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": MAX_COMPARISON_VARIANTS,
                    "items": _VARIANT,
                },
            },
            ("revision", "target", "variants"),
        ),
        operation="compare",
        timeout_class="standard",
        hard_limits={"variants": MAX_COMPARISON_VARIANTS},
        allow_unsaved_overlays=True,
    ),
    "scan": _capability(
        "operation.scan",
        "operation",
        _object(
            {
                **_OPERATION_COMMON,
                "targets": _TARGETS,
                "x": _IDENTITY,
                "range": _EXPRESSION,
                "points": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": MAX_SCAN_POINTS,
                },
            },
            ("revision", "targets", "x", "range"),
        ),
        operation="scan",
        timeout_class="standard",
        hard_limits={
            "targets": MAX_PLUGIN_OPERATION_TARGETS,
            "points": MAX_SCAN_POINTS,
        },
        allow_unsaved_overlays=True,
    ),
    "grid": _capability(
        "operation.scan",
        "operation",
        _object(
            {
                **_OPERATION_COMMON,
                "target": _IDENTITY,
                "x": _IDENTITY,
                "x_range": _EXPRESSION,
                "x_points": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": MAX_SCAN_POINTS,
                },
                "y": _IDENTITY,
                "y_range": _EXPRESSION,
                "y_points": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": MAX_SCAN_POINTS,
                },
            },
            ("revision", "target", "x", "x_range", "y", "y_range"),
        ),
        operation="grid",
        timeout_class="standard",
        hard_limits={"total_points": MAX_SCAN_POINTS},
        allow_unsaved_overlays=True,
    ),
    "solve": _capability(
        "operation.solve",
        "operation",
        _object(
            {
                **_OPERATION_COMMON,
                "target": _IDENTITY,
                "variable": _IDENTITY,
                "equals": _EXPRESSION,
                "range": {"oneOf": [_EXPRESSION, {"type": "null"}]},
            },
            ("revision", "target", "variable", "equals"),
        ),
        operation="solve",
        timeout_class="standard",
        allow_unsaved_overlays=True,
    ),
    "analyze": _capability(
        "operation.analyze",
        "operation",
        _object(
            {
                "revision": _REVISION,
                "target": _IDENTITY,
                "include_trace": {"type": "boolean"},
            },
            ("revision", "target"),
        ),
        operation="process_analysis",
        execution="job",
        timeout_class="analysis",
        allow_unsaved_overlays=True,
        unload_policy="cancel",
    ),
    "job.status": _capability(
        "operation.job",
        "job",
        _object({"job_id": _IDENTITY}, ("job_id",)),
    ),
    "job.cancel": _capability(
        "operation.job",
        "job",
        _object({"job_id": _IDENTITY}, ("job_id",)),
    ),
    "model.query": _capability(
        "model.read",
        "catalog",
        {"$ref": "model-catalog.schema.json#/$defs/query"},
    ),
    "model.get": _capability(
        "model.read",
        "catalog",
        {"$ref": "model-catalog.schema.json#/$defs/get"},
    ),
    "model.dependencies": _capability(
        "model.read",
        "catalog",
        {"$ref": "model-catalog.schema.json#/$defs/dependencies"},
    ),
    "model.document": _capability(
        "model.read",
        "catalog",
        {"$ref": "model-catalog.schema.json#/$defs/document"},
    ),
    "model.capabilities": _capability(
        "model.read",
        "catalog",
        {"$ref": "model-catalog.schema.json#/$defs/capabilities"},
    ),
}

PLUGIN_PERMISSIONS: Final = frozenset(
    PLUGIN_CONTEXT_PERMISSIONS
    | {item["permission"] for item in PLUGIN_ACTIONS.values()}
)

PLUGIN_LIMITS: Final = {
    "max_message_chars": MAX_PLUGIN_MESSAGE_CHARS,
    "max_model_items_per_group": MAX_PLUGIN_MODEL_ITEMS_PER_GROUP,
    "max_model_chars_per_group": MAX_PLUGIN_MODEL_CHARS_PER_GROUP,
    "max_target_inputs": MAX_PLUGIN_TARGET_INPUTS,
    "max_operation_targets": MAX_PLUGIN_OPERATION_TARGETS,
    "max_comparison_variants": MAX_COMPARISON_VARIANTS,
    "max_scan_points": MAX_SCAN_POINTS,
    "max_plugin_jobs_per_contribution": MAX_PLUGIN_JOBS_PER_CONTRIBUTION,
    "max_concurrent_operation_jobs": MAX_WORKBENCH_OPERATION_JOBS,
    "max_expression_chars": MAX_EXPRESSION_LENGTH,
    "max_draft_source_bytes": MAX_PLUGIN_DRAFT_SOURCE_BYTES,
    "max_pending_proposals": MAX_PLUGIN_PENDING_PROPOSALS,
    "max_proposal_changes": MAX_PLUGIN_PROPOSAL_CHANGES,
    "max_proposal_bytes": MAX_PLUGIN_PROPOSAL_BYTES,
    "max_template_bindings": MAX_PLUGIN_TEMPLATE_BINDINGS,
    "max_preference_bytes": MAX_PLUGIN_PREFERENCE_BYTES,
    "max_preference_value_bytes": MAX_PLUGIN_PREFERENCE_VALUE_BYTES,
    "max_preference_keys": MAX_PLUGIN_PREFERENCE_KEYS,
    "max_preference_key_chars": MAX_PLUGIN_PREFERENCE_KEY_CHARS,
    "max_preference_depth": MAX_PLUGIN_PREFERENCE_DEPTH,
    "max_action_id_chars": MAX_PLUGIN_ACTION_ID_CHARS,
    "max_identity_chars": MAX_PLUGIN_IDENTITY_CHARS,
    "max_path_chars": MAX_PLUGIN_PATH_CHARS,
    "max_title_chars": MAX_PLUGIN_TITLE_CHARS,
    "max_description_chars": MAX_PLUGIN_DESCRIPTION_CHARS,
    "max_variant_name_chars": MAX_PLUGIN_VARIANT_NAME_CHARS,
    "max_interface_requirements": MAX_PLUGIN_INTERFACE_REQUIREMENTS,
    "standard_operation_timeout_seconds": PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS,
    "analysis_timeout_seconds": MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS,
    "default_model_query_limit": DEFAULT_MODEL_QUERY_LIMIT,
    "max_model_query_limit": MAX_MODEL_QUERY_LIMIT,
    "max_model_cursor_chars": MAX_MODEL_CURSOR_CHARS,
    "max_model_dependency_depth": MAX_MODEL_DEPENDENCY_DEPTH,
    "max_catalog_summary_interfaces": MAX_CATALOG_SUMMARY_INTERFACES,
}


def plugin_protocol_descriptor() -> dict:
    """Return an isolated JSON-safe descriptor for adapters, SDKs, and frames."""

    return {
        "protocol": PLUGIN_PROTOCOL_NAME,
        "api": PLUGIN_API_VERSION,
        "permissions": sorted(PLUGIN_PERMISSIONS),
        "actions": {
            name: deepcopy(capability)
            for name, capability in sorted(PLUGIN_ACTIONS.items())
        },
        "events": {
            "job-update": {
                "schema": {"$ref": "protocol.schema.json#/$defs/jobUpdate"}
            }
        },
        "limits": dict(PLUGIN_LIMITS),
        "errors": dict(sorted(PLUGIN_ERROR_CODES.items())),
    }
