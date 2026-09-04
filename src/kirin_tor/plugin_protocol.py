"""Single-source public capability descriptor for Workbench Plugin protocol v2."""

from __future__ import annotations

from typing import Final

from .limits import (
    DEFAULT_MODEL_QUERY_LIMIT,
    MAX_CATALOG_SUMMARY_INTERFACES,
    MAX_COMPARISON_VARIANTS,
    MAX_EXPRESSION_LENGTH,
    MAX_PLUGIN_ACTION_ID_CHARS,
    MAX_PLUGIN_DESCRIPTION_CHARS,
    MAX_PLUGIN_DRAFT_PROPOSALS,
    MAX_PLUGIN_DRAFT_SOURCE_BYTES,
    MAX_PLUGIN_IDENTITY_CHARS,
    MAX_PLUGIN_MESSAGE_CHARS,
    MAX_PLUGIN_MODEL_CHARS_PER_GROUP,
    MAX_PLUGIN_MODEL_ITEMS_PER_GROUP,
    MAX_PLUGIN_OPERATION_TARGETS,
    MAX_PLUGIN_PATH_CHARS,
    MAX_PLUGIN_TARGET_INPUTS,
    MAX_PLUGIN_TITLE_CHARS,
    MAX_PLUGIN_VARIANT_NAME_CHARS,
    MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS,
    MAX_MODEL_CURSOR_CHARS,
    MAX_MODEL_DEPENDENCY_DEPTH,
    MAX_MODEL_QUERY_LIMIT,
    MAX_SCAN_POINTS,
    PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS,
)


PLUGIN_API_VERSION: Final = "2"

PLUGIN_CONTEXT_PERMISSIONS: Final = frozenset(
    {
        "workspace.summary",
        "model.read",
        "document.read",
        "draft.read",
    }
)

# ``operation`` is the exact Workbench backend operation when the host forwards
# a validated request. Host-only actions deliberately have no operation name.
PLUGIN_ACTIONS: Final = {
    "navigate-source": {"permission": "source.navigate", "handler": "host"},
    "propose-draft": {"permission": "draft.propose", "handler": "host"},
    "evaluate": {
        "permission": "operation.evaluate",
        "handler": "operation",
        "operation": "eval",
    },
    "explain": {
        "permission": "operation.explain",
        "handler": "operation",
        "operation": "explain",
    },
    "compare": {
        "permission": "operation.compare",
        "handler": "operation",
        "operation": "compare",
    },
    "scan": {
        "permission": "operation.scan",
        "handler": "operation",
        "operation": "scan",
    },
    "grid": {
        "permission": "operation.scan",
        "handler": "operation",
        "operation": "grid",
    },
    "solve": {
        "permission": "operation.solve",
        "handler": "operation",
        "operation": "solve",
    },
    "analyze": {
        "permission": "operation.analyze",
        "handler": "operation",
        "operation": "process_analysis",
    },
    "model.query": {"permission": "model.read", "handler": "catalog"},
    "model.get": {"permission": "model.read", "handler": "catalog"},
    "model.dependencies": {"permission": "model.read", "handler": "catalog"},
    "model.document": {"permission": "model.read", "handler": "catalog"},
    "model.capabilities": {"permission": "model.read", "handler": "catalog"},
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
    "max_expression_chars": MAX_EXPRESSION_LENGTH,
    "max_draft_source_bytes": MAX_PLUGIN_DRAFT_SOURCE_BYTES,
    "max_draft_proposals": MAX_PLUGIN_DRAFT_PROPOSALS,
    "max_action_id_chars": MAX_PLUGIN_ACTION_ID_CHARS,
    "max_identity_chars": MAX_PLUGIN_IDENTITY_CHARS,
    "max_path_chars": MAX_PLUGIN_PATH_CHARS,
    "max_title_chars": MAX_PLUGIN_TITLE_CHARS,
    "max_description_chars": MAX_PLUGIN_DESCRIPTION_CHARS,
    "max_variant_name_chars": MAX_PLUGIN_VARIANT_NAME_CHARS,
    "standard_operation_timeout_seconds": PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS,
    "analysis_timeout_seconds": MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS,
    "default_model_query_limit": DEFAULT_MODEL_QUERY_LIMIT,
    "max_model_query_limit": MAX_MODEL_QUERY_LIMIT,
    "max_model_cursor_chars": MAX_MODEL_CURSOR_CHARS,
    "max_model_dependency_depth": MAX_MODEL_DEPENDENCY_DEPTH,
    "max_catalog_summary_interfaces": MAX_CATALOG_SUMMARY_INTERFACES,
}


def plugin_protocol_descriptor() -> dict:
    """Return a fresh JSON-safe descriptor for adapters and Plugin frames."""

    return {
        "api": PLUGIN_API_VERSION,
        "permissions": sorted(PLUGIN_PERMISSIONS),
        "actions": {
            name: dict(capability)
            for name, capability in sorted(PLUGIN_ACTIONS.items())
        },
        "limits": dict(PLUGIN_LIMITS),
    }
