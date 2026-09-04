"""Deterministic schemas, TypeScript declarations, and SDK for Plugin API 2."""

from __future__ import annotations

import json
from typing import Mapping

from .limits import MAX_PLUGIN_CONTRIBUTIONS
from .model_catalog import MODEL_DESCRIPTOR_KINDS
from .plugin_protocol import (
    PLUGIN_ACTIONS,
    PLUGIN_API_VERSION,
    PLUGIN_ERROR_CODES,
    PLUGIN_LIMITS,
    PLUGIN_PERMISSIONS,
    PLUGIN_PROTOCOL_NAME,
    plugin_protocol_descriptor,
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def plugin_manifest_schema() -> dict:
    def text_list(*, minimum: int = 0) -> dict:
        return {
            "type": "array",
            "minItems": minimum,
            "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
            "uniqueItems": True,
            "items": {"type": "string", "minLength": 1},
        }

    def surface(renderer: bool) -> dict:
        properties = {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "entry": {"type": "string", "pattern": "^web/.+\\.html$"},
            "permissions": {
                "type": "array",
                "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
                "uniqueItems": True,
                "items": {"enum": sorted(PLUGIN_PERMISSIONS)},
            },
        }
        required = ["id", "title", "entry"]
        if renderer:
            properties["priority"] = {
                "type": "integer",
                "minimum": -1000,
                "maximum": 1000,
            }
            properties["match"] = {
                "type": "object",
                "properties": {
                    "document_ids": text_list(),
                    "document_id_prefixes": text_list(),
                    "package_names": text_list(),
                },
                "anyOf": [
                    {
                        "required": [name],
                        "properties": {name: text_list(minimum=1)},
                    }
                    for name in (
                        "document_ids",
                        "document_id_prefixes",
                        "package_names",
                    )
                ],
                "additionalProperties": False,
            }
            required.append("match")
        return {
            "type": "object",
            "required": required,
            "properties": properties,
            "additionalProperties": False,
        }
    command = {
        "type": "object",
        "required": ["id", "title", "description", "action", "target"],
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "action": {"enum": ["open-view", "open-tool", "activate-profile"]},
            "target": {"type": "string"},
        },
        "additionalProperties": False,
    }
    profile = {
        "type": "object",
        "required": [
            "id", "title", "description", "views", "default_view",
            "document_focus_mode",
        ],
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "views": text_list(minimum=1),
            "tools": text_list(),
            "default_view": {"type": "string"},
            "document_focus_mode": {"enum": ["editor", "split", "preview"]},
        },
        "additionalProperties": False,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://kirin-tor.invalid/schemas/plugin-v2/plugin-manifest.schema.json",
        "title": "Kirin Tor Workbench Plugin manifest v2",
        "type": "object",
        "required": [
            "schema", "id", "name", "version", "api", "description", "license",
            "requires", "contributes",
        ],
        "properties": {
            "schema": {"const": 2},
            "id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*(?:\\.[a-z][a-z0-9-]*)+$"},
            "name": {"type": "string", "minLength": 1},
            "version": {"type": "string", "pattern": "^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)$"},
            "api": {"const": PLUGIN_API_VERSION},
            "description": {"type": "string", "minLength": 1},
            "license": {"type": "string", "minLength": 1},
            "storage": {
                "type": "object",
                "required": ["preferences"],
                "properties": {
                    "preferences": {
                        "type": "object",
                        "required": ["schema"],
                        "properties": {
                            "schema": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 2_147_483_647,
                            }
                        },
                        "additionalProperties": False,
                    }
                },
                "additionalProperties": False,
            },
            "requires": {
                "type": "object",
                "required": ["kirin_feature"],
                "properties": {
                    "kirin_feature": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+$"},
                    "interfaces": {
                        "type": "array",
                        "maxItems": PLUGIN_LIMITS["max_interface_requirements"],
                        "uniqueItems": True,
                        "items": {
                            "type": "object",
                            "required": ["id", "revision"],
                            "properties": {
                                "id": {"type": "string"},
                                "revision": {"type": "integer", "minimum": 1},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            "contributes": {
                "type": "object",
                "properties": {
                    "renderers": {
                        "type": "array",
                        "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
                        "items": surface(True),
                    },
                    "views": {
                        "type": "array",
                        "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
                        "items": surface(False),
                    },
                    "tools": {
                        "type": "array",
                        "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
                        "items": surface(False),
                    },
                    "commands": {
                        "type": "array",
                        "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
                        "items": command,
                    },
                    "profiles": {
                        "type": "array",
                        "maxItems": MAX_PLUGIN_CONTRIBUTIONS,
                        "items": profile,
                    },
                },
                "anyOf": [
                    {
                        "required": [name],
                        "properties": {name: {"minItems": 1}},
                    }
                    for name in (
                        "renderers",
                        "views",
                        "tools",
                        "commands",
                        "profiles",
                    )
                ],
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def model_catalog_schema() -> dict:
    revision = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    identity = {"type": "string", "minLength": 1, "maxLength": PLUGIN_LIMITS["max_identity_chars"]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://kirin-tor.invalid/schemas/plugin-v2/model-catalog.schema.json",
        "$defs": {
            "descriptor": {
                "type": "object",
                "required": [
                    "id", "kind", "owner_id", "label", "contract", "dependencies",
                    "interfaces", "origin", "source_location", "payload",
                ],
                "properties": {
                    "id": identity,
                    "kind": {"enum": list(MODEL_DESCRIPTOR_KINDS)},
                    "owner_id": {"type": ["string", "null"]},
                    "label": {"type": "string"},
                    "contract": {"type": "object"},
                    "dependencies": {"type": "array", "items": identity},
                    "interfaces": {"type": "array", "items": {"type": "object"}},
                    "origin": {"type": "object"},
                    "source_location": {"type": "object"},
                    "payload": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "query": {
                "type": "object",
                "required": ["revision"],
                "properties": {
                    "revision": revision,
                    "kind": {
                        "oneOf": [
                            {"enum": list(MODEL_DESCRIPTOR_KINDS)},
                            {"type": "array", "minItems": 1, "items": {"enum": list(MODEL_DESCRIPTOR_KINDS)}},
                        ]
                    },
                    "interface": identity,
                    "interface_revision": {"type": "integer", "minimum": 1},
                    "owner": identity,
                    "prefix": identity,
                    "cursor": {"type": ["string", "null"], "maxLength": PLUGIN_LIMITS["max_model_cursor_chars"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": PLUGIN_LIMITS["max_model_query_limit"]},
                },
                "additionalProperties": False,
            },
            "get": {
                "type": "object",
                "required": ["revision", "id"],
                "properties": {"revision": revision, "id": identity, "kind": {"enum": list(MODEL_DESCRIPTOR_KINDS)}},
                "additionalProperties": False,
            },
            "dependencies": {
                "type": "object",
                "required": ["revision", "id"],
                "properties": {
                    "revision": revision,
                    "id": identity,
                    "kind": {"enum": list(MODEL_DESCRIPTOR_KINDS)},
                    "depth": {"type": "integer", "minimum": 1, "maximum": PLUGIN_LIMITS["max_model_dependency_depth"]},
                },
                "additionalProperties": False,
            },
            "document": {
                "type": "object",
                "required": ["revision", "id"],
                "properties": {"revision": revision, "id": identity},
                "additionalProperties": False,
            },
            "capabilities": {
                "type": "object",
                "required": ["revision"],
                "properties": {"revision": revision},
                "additionalProperties": False,
            },
        },
    }


def protocol_schema() -> dict:
    requests = []
    for action, capability in sorted(PLUGIN_ACTIONS.items()):
        requests.append(
            {
                "type": "object",
                "required": ["protocol", "api", "type", "id", "action", "payload"],
                "properties": {
                    "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                    "api": {"const": PLUGIN_API_VERSION},
                    "type": {"const": "action"},
                    "id": {"type": "string", "minLength": 1, "maxLength": PLUGIN_LIMITS["max_action_id_chars"]},
                    "action": {"const": action},
                    "payload": capability["request_schema"],
                },
                "additionalProperties": False,
            }
        )
    contribution = {
        "type": "object",
        "required": [
            "id", "kind", "title", "plugin_id", "plugin_name", "plugin_version",
            "permissions", "required_interfaces",
            "storage_schema",
        ],
        "properties": {
            "id": {"type": "string"},
            "kind": {"enum": ["renderer", "view", "tool"]},
            "title": {"type": "string"},
            "plugin_id": {"type": "string"},
            "plugin_name": {"type": "string"},
            "plugin_version": {"type": "string"},
            "permissions": {
                "type": "array",
                "uniqueItems": True,
                "items": {"enum": sorted(PLUGIN_PERMISSIONS)},
            },
            "required_interfaces": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["id", "revision"],
                    "properties": {
                        "id": {"type": "string"},
                        "revision": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
            },
            "storage_schema": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "null"},
                ]
            },
        },
        "additionalProperties": False,
    }
    context = {
        "type": "object",
        "properties": {
            "workspace": {"type": "object"},
            "document": {"type": "object"},
            "members": {"type": "array"},
            "relationships": {"type": "array"},
            "draft": {"type": "object"},
            "catalog": {"type": "object"},
            "templates": {"type": "array"},
        },
        "additionalProperties": False,
    }
    host_context_messages = [
        {
            "type": "object",
            "required": [
                "protocol", "api", "type", "contribution", "capabilities", "context",
            ],
            "properties": {
                "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                "api": {"const": PLUGIN_API_VERSION},
                "type": {"const": message_type},
                "contribution": {"$ref": "#/$defs/contribution"},
                "capabilities": {"$ref": "#/$defs/capabilityDescriptor"},
                "context": {"$ref": "#/$defs/context"},
            },
            "additionalProperties": False,
        }
        for message_type in ("activate", "context")
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://kirin-tor.invalid/schemas/plugin-v2/protocol.schema.json",
        "oneOf": [
            {"$ref": "#/$defs/pluginToHostMessage"},
            {"$ref": "#/$defs/hostToPluginMessage"},
        ],
        "$defs": {
            "ready": {
                "type": "object",
                "required": ["protocol", "api", "type"],
                "properties": {
                    "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                    "api": {"const": PLUGIN_API_VERSION},
                    "type": {"const": "ready"},
                },
                "additionalProperties": False,
            },
            "actionRequest": {"oneOf": requests},
            "actionResult": {
                "type": "object",
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
            "operationEnvelope": {
                "type": "object",
                "required": [
                    "status", "operation_id", "operation", "revision", "targets",
                    "applied", "provenance", "warnings", "result",
                ],
                "properties": {
                    "status": {"const": "ok"},
                    "operation_id": {"type": "string"},
                    "operation": {"type": "string"},
                    "revision": {"type": "string"},
                    "targets": {"type": "array", "items": {"type": "string"}},
                    "applied": {"type": "object"},
                    "provenance": {"type": "object"},
                    "warnings": {"type": "array"},
                    "result": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "job": {
                "type": "object",
                "required": ["status", "job_id", "operation", "state", "stage", "cancellable"],
                "properties": {
                    "status": {"enum": ["ok", "accepted"]},
                    "job_id": {"type": "string"},
                    "operation": {"type": "string"},
                    "state": {"enum": ["queued", "running", "completed", "failed", "cancelled"]},
                    "stage": {"enum": ["queued", "executing", "completed", "failed", "cancelled"]},
                    "cancellable": {"type": "boolean"},
                    "result": {"type": "object"},
                    "error": {"type": "object"},
                },
            },
            "jobUpdate": {
                "type": "object",
                "required": ["protocol", "api", "type", "job"],
                "properties": {
                    "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                    "api": {"const": PLUGIN_API_VERSION},
                    "type": {"const": "job-update"},
                    "job": {"$ref": "#/$defs/job"},
                },
                "additionalProperties": False,
            },
            "contribution": contribution,
            "context": context,
            "capabilityDescriptor": {
                "type": "object",
                "required": [
                    "protocol", "api", "permissions", "actions", "events", "limits", "errors",
                ],
                "properties": {
                    "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                    "api": {"const": PLUGIN_API_VERSION},
                    "permissions": {"type": "array", "items": {"type": "string"}},
                    "actions": {"type": "object"},
                    "events": {"type": "object"},
                    "limits": {"type": "object"},
                    "errors": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "activation": {"oneOf": host_context_messages},
            "actionResultMessage": {
                "type": "object",
                "required": ["protocol", "api", "type", "id", "result"],
                "properties": {
                    "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                    "api": {"const": PLUGIN_API_VERSION},
                    "type": {"const": "action-result"},
                    "id": {"type": "string", "minLength": 1},
                    "result": {"type": "object"},
                },
                "additionalProperties": False,
            },
            "actionErrorMessage": {
                "type": "object",
                "required": ["protocol", "api", "type", "id", "error"],
                "properties": {
                    "protocol": {"const": PLUGIN_PROTOCOL_NAME},
                    "api": {"const": PLUGIN_API_VERSION},
                    "type": {"const": "action-error"},
                    "id": {"type": "string", "minLength": 1},
                    "error": {
                        "type": "object",
                        "required": ["code", "message"],
                        "properties": {
                            "code": {"enum": sorted(PLUGIN_ERROR_CODES)},
                            "message": {"type": "string"},
                        },
                    },
                },
                "additionalProperties": False,
            },
            "pluginToHostMessage": {
                "oneOf": [
                    {"$ref": "#/$defs/ready"},
                    {"$ref": "#/$defs/actionRequest"},
                ],
            },
            "hostToPluginMessage": {
                "oneOf": [
                    {"$ref": "#/$defs/activation"},
                    {"$ref": "#/$defs/actionResultMessage"},
                    {"$ref": "#/$defs/actionErrorMessage"},
                    {"$ref": "#/$defs/jobUpdate"},
                ],
            },
        },
    }


def render_generated_typescript() -> str:
    permissions = " | ".join(json.dumps(item) for item in sorted(PLUGIN_PERMISSIONS))
    actions = " | ".join(json.dumps(item) for item in sorted(PLUGIN_ACTIONS))
    descriptor = json.dumps(plugin_protocol_descriptor(), ensure_ascii=False, indent=2, sort_keys=True)
    empty_limits = json.dumps(
        {name: 0 for name in sorted(PLUGIN_LIMITS)},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    limit_fields = "\n".join(
        f"  {name}: number;" for name in sorted(PLUGIN_LIMITS)
    )
    return f'''// Generated by scripts/generate_plugin_protocol.py. Do not edit.
export type GeneratedPluginPermission = {permissions};
export type GeneratedPluginAction = {actions};

export interface GeneratedPluginProtocolLimits {{
{limit_fields}
}}

export interface GeneratedPluginActionCapability {{
  permission: GeneratedPluginPermission;
  handler: "host" | "operation" | "catalog" | "job" | "proposal" | "result" | "storage";
  operation?: string;
  execution: "sync" | "job";
  timeout_class: "none" | "standard" | "analysis";
  request_schema: Record<string, unknown>;
  result_schema: Record<string, unknown>;
  hard_limits: Record<string, number>;
  allow_unsaved_overlays: boolean;
  allow_durable_run: boolean;
  allow_artifacts: boolean;
  unload_policy: "none" | "cancel";
}}

export interface GeneratedPluginProtocolDescriptor {{
  protocol: "{PLUGIN_PROTOCOL_NAME}";
  api: "{PLUGIN_API_VERSION}";
  permissions: GeneratedPluginPermission[];
  actions: Record<string, GeneratedPluginActionCapability>;
  events: Record<string, {{ schema: Record<string, unknown> }}>;
  limits: GeneratedPluginProtocolLimits;
  errors: Record<string, string>;
}}

export const GENERATED_PLUGIN_PROTOCOL = {descriptor} as const;

export const EMPTY_GENERATED_PLUGIN_PROTOCOL: GeneratedPluginProtocolDescriptor = {{
  protocol: "{PLUGIN_PROTOCOL_NAME}",
  api: "{PLUGIN_API_VERSION}",
  permissions: [],
  actions: {{}},
  events: {{}},
  limits: {empty_limits},
  errors: {{}},
}};
'''


def render_sdk_mjs() -> str:
    descriptor = json.dumps(plugin_protocol_descriptor(), ensure_ascii=False, separators=(",", ":"))
    catalog_schemas = json.dumps(
        model_catalog_schema()["$defs"], ensure_ascii=False, separators=(",", ":")
    )
    return r'''// Generated Kirin Tor Plugin SDK v2. No runtime dependencies.
const DESCRIPTOR = __DESCRIPTOR__;
const CATALOG_SCHEMAS = __CATALOG_SCHEMAS__;
const PROTOCOL = DESCRIPTOR.protocol;

export class KirinPluginError extends Error {
  constructor(code, message, details = null) {
    super(message || code);
    this.name = "KirinPluginError";
    this.code = code;
    this.details = details;
  }
}

function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function schemaError(path, message, limit = false) {
  throw new KirinPluginError(limit ? "limit_exceeded" : "invalid_request", `${path} ${message}`);
}

function resolveSchema(schema) {
  if (!schema?.$ref) return schema;
  const match = schema.$ref.match(/^model-catalog\.schema\.json#\/\$defs\/(.+)$/);
  if (match && CATALOG_SCHEMAS[match[1]]) return CATALOG_SCHEMAS[match[1]];
  return schema;
}

function validate(value, unresolved, path = "payload") {
  const schema = resolveSchema(unresolved);
  if (!schema || schema.$ref) return;
  if (schema.oneOf) {
    let matches = 0;
    for (const choice of schema.oneOf) {
      try { validate(value, choice, path); matches += 1; } catch { /* try the next branch */ }
    }
    if (matches !== 1) schemaError(path, "does not match exactly one allowed shape");
    return;
  }
  if (Object.prototype.hasOwnProperty.call(schema, "const") && value !== schema.const) schemaError(path, "has the wrong constant value");
  if (schema.enum && !schema.enum.includes(value)) schemaError(path, "is not an allowed value");
  const types = Array.isArray(schema.type) ? schema.type : schema.type ? [schema.type] : [];
  if (types.length) {
    const matches = types.some((type) => (
      (type === "null" && value === null)
      || (type === "object" && record(value))
      || (type === "array" && Array.isArray(value))
      || (type === "string" && typeof value === "string")
      || (type === "integer" && Number.isInteger(value))
      || (type === "number" && typeof value === "number" && Number.isFinite(value))
      || (type === "boolean" && typeof value === "boolean")
    ));
    if (!matches) schemaError(path, `must be ${types.join(" or ")}`);
  }
  if (typeof value === "string") {
    if (schema.minLength !== undefined && value.length < schema.minLength) schemaError(path, "is too short");
    if (schema.maxLength !== undefined && value.length > schema.maxLength) schemaError(path, "is too long", true);
    if (schema.pattern && !(new RegExp(schema.pattern)).test(value)) schemaError(path, "has an invalid format");
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) schemaError(path, "is below its minimum");
    if (schema.maximum !== undefined && value > schema.maximum) schemaError(path, "exceeds its maximum", true);
  }
  if (Array.isArray(value)) {
    if (schema.minItems !== undefined && value.length < schema.minItems) schemaError(path, "has too few items");
    if (schema.maxItems !== undefined && value.length > schema.maxItems) schemaError(path, "has too many items", true);
    if (schema.uniqueItems && new Set(value.map((item) => JSON.stringify(item))).size !== value.length) schemaError(path, "contains duplicate items");
    if (schema.items) value.forEach((item, index) => validate(item, schema.items, `${path}[${index}]`));
  }
  if (record(value)) {
    for (const key of schema.required || []) {
      if (!Object.prototype.hasOwnProperty.call(value, key)) schemaError(path, `is missing ${key}`);
    }
    if (schema.maxProperties !== undefined && Object.keys(value).length > schema.maxProperties) schemaError(path, "has too many fields", true);
    for (const [key, item] of Object.entries(value)) {
      if (schema.properties?.[key]) validate(item, schema.properties[key], `${path}.${key}`);
      else if (schema.additionalProperties === false) schemaError(path, `contains unknown field ${key}`);
      else if (record(schema.additionalProperties)) validate(item, schema.additionalProperties, `${path}.${key}`);
    }
  }
}

export function createKirinPlugin(options = {}) {
  const api = String(options.api ?? "2");
  if (api !== DESCRIPTOR.api) throw new KirinPluginError("unsupported_capability", `SDK API ${api} is unavailable`);
  let contribution = null;
  let context = {};
  let disposed = false;
  let started = false;
  let sequence = 0;
  let resolveActivation;
  let rejectActivation;
  const pending = new Map();
  const contextListeners = new Set();
  const jobListeners = new Set();
  const liveJobs = new Set();
  const activation = new Promise((resolve, reject) => {
    resolveActivation = resolve;
    rejectActivation = reject;
  });

  function size(value) {
    try { return JSON.stringify(value).length; } catch { return Infinity; }
  }

  function post(message) {
    if (disposed) throw new KirinPluginError("plugin_disabled", "Plugin SDK is disposed");
    const complete = { protocol: PROTOCOL, api, ...message };
    if (size(complete) > DESCRIPTOR.limits.max_message_chars) {
      throw new KirinPluginError("limit_exceeded", "Plugin message exceeds the host limit");
    }
    parent.postMessage(complete, "*");
  }

  function revisionPayload(action, payload) {
    const capability = DESCRIPTOR.actions[action];
    if (!capability) throw new KirinPluginError("unsupported_capability", `Unsupported action: ${action}`);
    if (!record(payload)) throw new KirinPluginError("invalid_request", "Action payload must be an object");
    if ((capability.handler === "operation" || capability.handler === "catalog" || capability.handler === "proposal") && !payload.revision) {
      const revision = context?.catalog?.revision;
      if (!revision) throw new KirinPluginError("stale_revision", "No current workspace revision is available");
      return { ...payload, revision };
    }
    return payload;
  }

  function request(action, payload = {}) {
    if (!contribution) return ready().then(() => request(action, payload));
    const capability = DESCRIPTOR.actions[action];
    if (!capability) return Promise.reject(new KirinPluginError("unsupported_capability", `Unsupported action: ${action}`));
    if (!contribution.permissions.includes(capability.permission)) {
      return Promise.reject(new KirinPluginError("permission_denied", `${capability.permission} was not granted`));
    }
    const id = `sdk-${++sequence}`;
    const normalized = revisionPayload(action, payload);
    validate(normalized, capability.request_schema);
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      try { post({ type: "action", id, action, payload: normalized }); }
      catch (error) { pending.delete(id); reject(error); }
    });
  }

  function receive(event) {
    if (event.source !== parent || !record(event.data)) return;
    const message = event.data;
    if (message.protocol !== PROTOCOL || String(message.api) !== api) return;
    if (message.type === "activate" || message.type === "context") {
      contribution = message.contribution;
      context = message.context || {};
      if (message.type === "activate") resolveActivation({ contribution, context, capabilities: message.capabilities });
      for (const listener of contextListeners) listener(context, contribution);
      return;
    }
    if (message.type === "job-update" && record(message.job)) {
      const job = message.job;
      if (["completed", "failed", "cancelled"].includes(job.state)) liveJobs.delete(job.job_id);
      for (const listener of jobListeners) listener(job);
      return;
    }
    if (message.type !== "action-result" && message.type !== "action-error") return;
    const waiting = pending.get(message.id);
    if (!waiting) return;
    pending.delete(message.id);
    if (message.type === "action-result" && record(message.result)) {
      if (message.result?.job_id && ["queued", "running"].includes(message.result.state)) liveJobs.add(message.result.job_id);
      waiting.resolve(message.result);
    } else if (message.type === "action-result") {
      waiting.reject(new KirinPluginError("operation_failed", "Host returned an invalid action result", message.result));
    } else {
      waiting.reject(new KirinPluginError(message.error?.code || "operation_failed", message.error?.message, message.error));
    }
  }

  addEventListener("message", receive);

  function ready() {
    if (!started) {
      started = true;
      post({ type: "ready" });
    }
    return activation;
  }

  async function waitJob(handle, options = {}) {
    const interval = options.interval ?? 250;
    let job = typeof handle === "string" ? await request("job.status", { job_id: handle }) : handle;
    while (job && ["queued", "running"].includes(job.state)) {
      await new Promise((resolve) => setTimeout(resolve, interval));
      job = await request("job.status", { job_id: job.job_id });
    }
    if (job?.state === "completed") return job.result;
    throw new KirinPluginError(job?.error?.code || "operation_failed", job?.error?.message || "Job failed", job);
  }

  async function* pages(query = {}) {
    let cursor = query.cursor ?? null;
    do {
      const page = await request("model.query", { ...query, cursor });
      yield page;
      cursor = page.next_cursor;
    } while (cursor);
  }

  async function all(query = {}) {
    const items = [];
    for await (const page of pages(query)) items.push(...page.items);
    return items;
  }

  function dispose() {
    if (disposed) return;
    for (const jobId of liveJobs) request("job.cancel", { job_id: jobId }).catch(() => undefined);
    disposed = true;
    removeEventListener("message", receive);
    const error = new KirinPluginError("plugin_disabled", "Plugin SDK was disposed");
    rejectActivation(error);
    for (const waiting of pending.values()) waiting.reject(error);
    pending.clear();
    contextListeners.clear();
    jobListeners.clear();
  }

  return Object.freeze({
    descriptor: DESCRIPTOR,
    ready,
    request,
    dispose,
    get context() { return context; },
    get contribution() { return contribution; },
    onContext(listener) { contextListeners.add(listener); return () => contextListeners.delete(listener); },
    model: Object.freeze({
      query: (payload) => request("model.query", payload),
      pages,
      all,
      get: (payload) => request("model.get", payload),
      dependencies: (payload) => request("model.dependencies", payload),
      document: (payload) => request("model.document", payload),
      capabilities: (payload = {}) => request("model.capabilities", payload),
    }),
    operations: Object.freeze({
      evaluate: (payload) => request("evaluate", payload),
      evaluateMany: (payload) => request("evaluate-many", payload),
      explain: (payload) => request("explain", payload),
      compare: (payload) => request("compare", payload),
      scan: (payload) => request("scan", payload),
      grid: (payload) => request("grid", payload),
      solve: (payload) => request("solve", payload),
      analyze: (payload) => request("analyze", payload),
    }),
    results: Object.freeze({
      present: (handle, options = {}) => request("result.present", { handle, ...options }),
    }),
    storage: Object.freeze({
      get: (key) => request("storage.get", { key }),
      set: (key, value) => request("storage.set", { key, value }),
      delete: (key) => request("storage.delete", { key }),
    }),
    proposals: Object.freeze({
      submit: (payload) => request("proposal.submit", payload),
    }),
    jobs: Object.freeze({
      status: (jobId) => request("job.status", { job_id: jobId }),
      cancel: (jobId) => request("job.cancel", { job_id: jobId }),
      wait: waitJob,
      onUpdate(listener) { jobListeners.add(listener); return () => jobListeners.delete(listener); },
    }),
  });
}
'''.replace("__DESCRIPTOR__", descriptor).replace("__CATALOG_SCHEMAS__", catalog_schemas)


def _typescript_type(schema: Mapping[str, object], *, sdk_payload: bool = False) -> str:
    """Render the bounded request-schema subset used by the public SDK."""

    if "$ref" in schema:
        reference = schema["$ref"]
        prefix = "model-catalog.schema.json#/$defs/"
        if isinstance(reference, str) and reference.startswith(prefix):
            definition = model_catalog_schema()["$defs"].get(
                reference.removeprefix(prefix)
            )
            if isinstance(definition, Mapping):
                return _typescript_type(definition, sdk_payload=sdk_payload)
        return "Record<string, unknown>"
    if "oneOf" in schema:
        return " | ".join(
            _typescript_type(choice) for choice in schema["oneOf"]  # type: ignore[index]
        )
    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)
    if "enum" in schema:
        return " | ".join(
            json.dumps(item, ensure_ascii=False) for item in schema["enum"]  # type: ignore[index]
        )
    raw_type = schema.get("type")
    if isinstance(raw_type, list):
        return " | ".join(
            _typescript_type({"type": item}) for item in raw_type
        )
    if raw_type == "string":
        return "string"
    if raw_type in {"integer", "number"}:
        return "number"
    if raw_type == "boolean":
        return "boolean"
    if raw_type == "null":
        return "null"
    if raw_type == "array":
        item = schema.get("items")
        rendered = (
            _typescript_type(item)
            if isinstance(item, Mapping)
            else "unknown"
        )
        return f"Array<{rendered}>"
    if raw_type == "object":
        properties = schema.get("properties")
        if isinstance(properties, Mapping) and properties:
            required = {
                item for item in schema.get("required", []) if isinstance(item, str)
            }
            if sdk_payload:
                required.discard("revision")
            fields = []
            for name, value in properties.items():
                if not isinstance(name, str) or not isinstance(value, Mapping):
                    continue
                optional = "" if name in required else "?"
                fields.append(
                    f"{json.dumps(name, ensure_ascii=False)}{optional}: "
                    f"{_typescript_type(value)};"
                )
            return "{ " + " ".join(fields) + " }"
        additional = schema.get("additionalProperties")
        if isinstance(additional, Mapping):
            return f"Record<string, {_typescript_type(additional)}>"
        return "Record<string, unknown>"
    return "unknown"


def _sdk_result_type(action: str, capability: Mapping[str, object]) -> str:
    explicit = {
        "proposal.submit": "KirinProposalResult",
        "result.present": "KirinResultPresentation",
        "storage.get": "KirinStorageGetResult",
        "storage.set": "KirinStorageSetResult",
        "storage.delete": "KirinStorageDeleteResult",
    }
    if action in explicit:
        return explicit[action]
    if capability["handler"] == "job" or capability["execution"] == "job":
        return "KirinJob"
    if capability["handler"] == "operation":
        return "KirinOperationEnvelope"
    if capability["handler"] == "catalog":
        return "KirinCatalogResult"
    return "KirinActionResult"


def render_sdk_types() -> str:
    actions = " | ".join(json.dumps(item) for item in sorted(PLUGIN_ACTIONS))
    payloads = "\n".join(
        f"  {json.dumps(action)}: "
        f"{_typescript_type(capability['request_schema'], sdk_payload=True)};"
        for action, capability in sorted(PLUGIN_ACTIONS.items())
    )
    results = "\n".join(
        f"  {json.dumps(action)}: {_sdk_result_type(action, capability)};"
        for action, capability in sorted(PLUGIN_ACTIONS.items())
    )
    return f'''// Generated Kirin Tor Plugin SDK declarations v2. Do not edit.
export type KirinAction = {actions};
export type KirinActionResult = {{ status: string }} & Record<string, unknown>;
export type KirinCatalogResult = KirinActionResult;
export interface KirinProposalResult {{ status: "queued" | "rejected"; proposal_id?: string; reason?: string; errors?: unknown[]; }}
export interface KirinResultPresentation {{ status: "ok"; handle: string; }}
export interface KirinStorageGetResult {{ status: "ok"; key: string; found: boolean; value?: unknown; }}
export interface KirinStorageSetResult {{ status: "ok"; key: string; bytes: number; }}
export interface KirinStorageDeleteResult {{ status: "ok"; key: string; removed: boolean; }}
export interface KirinOperationEnvelope {{ status: "ok"; operation_id: string; operation: string; revision: string; targets: string[]; applied: {{ preset: string | null; overrides: Record<string, string> }}; provenance: Record<string, unknown>; warnings: unknown[]; result: Record<string, any>; }}
export interface KirinJob {{ status: "ok" | "accepted"; job_id: string; operation: string; state: "queued" | "running" | "completed" | "failed" | "cancelled"; stage: "queued" | "executing" | "completed" | "failed" | "cancelled"; cancellable: boolean; result?: KirinOperationEnvelope; error?: {{ code?: string; message?: string; [key: string]: unknown }}; }}
export interface KirinActionPayloads {{
{payloads}
}}
export interface KirinActionResults {{
{results}
}}
export interface KirinActivation {{ contribution: Record<string, unknown>; context: Record<string, any>; capabilities: Record<string, unknown>; }}
export declare class KirinPluginError extends Error {{ code: string; details: unknown; }}
export interface KirinPlugin {{
  readonly descriptor: Record<string, unknown>;
  readonly context: Record<string, any>;
  readonly contribution: Record<string, unknown> | null;
  ready(): Promise<KirinActivation>;
  request<A extends KirinAction>(action: A, payload: KirinActionPayloads[A]): Promise<KirinActionResults[A]>;
  dispose(): void;
  onContext(listener: (context: Record<string, any>, contribution: Record<string, unknown>) => void): () => void;
  model: {{ query(payload?: KirinActionPayloads["model.query"]): Promise<KirinCatalogResult>; pages(query?: KirinActionPayloads["model.query"]): AsyncGenerator<KirinCatalogResult>; all(query?: KirinActionPayloads["model.query"]): Promise<Record<string, unknown>[]>; get(payload: KirinActionPayloads["model.get"]): Promise<KirinCatalogResult>; dependencies(payload: KirinActionPayloads["model.dependencies"]): Promise<KirinCatalogResult>; document(payload: KirinActionPayloads["model.document"]): Promise<KirinCatalogResult>; capabilities(payload?: KirinActionPayloads["model.capabilities"]): Promise<KirinCatalogResult>; }};
  operations: {{ evaluate(payload: KirinActionPayloads["evaluate"]): Promise<KirinOperationEnvelope>; evaluateMany(payload: KirinActionPayloads["evaluate-many"]): Promise<KirinOperationEnvelope>; explain(payload: KirinActionPayloads["explain"]): Promise<KirinOperationEnvelope>; compare(payload: KirinActionPayloads["compare"]): Promise<KirinOperationEnvelope>; scan(payload: KirinActionPayloads["scan"]): Promise<KirinOperationEnvelope>; grid(payload: KirinActionPayloads["grid"]): Promise<KirinOperationEnvelope>; solve(payload: KirinActionPayloads["solve"]): Promise<KirinOperationEnvelope>; analyze(payload: KirinActionPayloads["analyze"]): Promise<KirinJob>; }};
  results: {{ present(handle: string, options?: Omit<KirinActionPayloads["result.present"], "handle">): Promise<KirinResultPresentation>; }};
  storage: {{ get(key: string): Promise<KirinStorageGetResult>; set(key: string, value: unknown): Promise<KirinStorageSetResult>; delete(key: string): Promise<KirinStorageDeleteResult>; }};
  proposals: {{ submit(payload: KirinActionPayloads["proposal.submit"]): Promise<KirinProposalResult>; }};
  jobs: {{ status(jobId: string): Promise<KirinJob>; cancel(jobId: string): Promise<KirinJob>; wait(handle: string | KirinJob, options?: {{ interval?: number }}): Promise<KirinOperationEnvelope>; onUpdate(listener: (job: KirinJob) => void): () => void; }};
}}
export declare function createKirinPlugin(options?: {{ api?: 2 | "2" }}): KirinPlugin;
'''


def protocol_artifacts() -> Mapping[str, str]:
    """Return every versioned artifact from the current Python contract source."""

    descriptor = plugin_protocol_descriptor()
    schemas = {
        "plugin-manifest.schema.json": _json(plugin_manifest_schema()),
        "protocol.schema.json": _json(protocol_schema()),
        "model-catalog.schema.json": _json(model_catalog_schema()),
        "operations.json": _json(descriptor["actions"]),
        "limits.json": _json(descriptor["limits"]),
        "errors.json": _json(PLUGIN_ERROR_CODES),
    }
    artifacts = {
        **{
            f"schemas/plugin-v2/{name}": content
            for name, content in schemas.items()
        },
        **{
            f"src/kirin_tor/protocol_assets/{name}": content
            for name, content in schemas.items()
        },
        "frontend/src/generated/pluginProtocol.ts": render_generated_typescript(),
        "sdk/plugin/kirin-plugin-sdk.mjs": render_sdk_mjs(),
        "sdk/plugin/kirin-plugin-sdk.d.mts": render_sdk_types(),
        "src/kirin_tor/protocol_assets/kirin-plugin-sdk.mjs": render_sdk_mjs(),
        "src/kirin_tor/protocol_assets/kirin-plugin-sdk.d.mts": render_sdk_types(),
        "examples/plugins/fictional-talent-tree/web/kirin-plugin-sdk.mjs": render_sdk_mjs(),
    }
    return artifacts
