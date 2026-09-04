// Generated Kirin Tor Plugin SDK v2. No runtime dependencies.
const DESCRIPTOR = {"protocol":"kirin-workbench-plugin","api":"2","permissions":["document.read","draft.read","model.read","operation.analyze","operation.compare","operation.evaluate","operation.explain","operation.job","operation.scan","operation.solve","proposal.submit","result.present","source.navigate","storage.preferences","template.read","workspace.summary"],"actions":{"analyze":{"permission":"operation.analyze","handler":"operation","execution":"job","timeout_class":"analysis","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"target":{"type":"string","minLength":1,"maxLength":240},"include_trace":{"type":"boolean"}},"required":["revision","target"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/job"},"hard_limits":{},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"cancel","operation":"process_analysis"},"compare":{"permission":"operation.compare","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"target":{"type":"string","minLength":1,"maxLength":240},"variants":{"type":"array","minItems":1,"maxItems":8,"items":{"type":"object","properties":{"name":{"type":"string","minLength":1,"maxLength":80},"preset":{"oneOf":[{"type":"string","minLength":1,"maxLength":240},{"type":"null"}]},"overrides":{"type":"object","maxProperties":128,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}}},"required":["name"],"additionalProperties":false}}},"required":["revision","target","variants"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{"variants":8},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"compare"},"evaluate":{"permission":"operation.evaluate","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"preset":{"oneOf":[{"type":"string","minLength":1,"maxLength":240},{"type":"null"}]},"overrides":{"type":"object","maxProperties":128,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}},"target":{"type":"string","minLength":1,"maxLength":240}},"required":["revision","target"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"eval"},"evaluate-many":{"permission":"operation.evaluate","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"preset":{"oneOf":[{"type":"string","minLength":1,"maxLength":240},{"type":"null"}]},"overrides":{"type":"object","maxProperties":128,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}},"targets":{"type":"array","minItems":1,"maxItems":64,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":240}}},"required":["revision","targets"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{"targets":64},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"evaluate_many"},"explain":{"permission":"operation.explain","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"target":{"type":"string","minLength":1,"maxLength":240}},"required":["revision","target"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"explain"},"grid":{"permission":"operation.scan","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"preset":{"oneOf":[{"type":"string","minLength":1,"maxLength":240},{"type":"null"}]},"overrides":{"type":"object","maxProperties":128,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}},"target":{"type":"string","minLength":1,"maxLength":240},"x":{"type":"string","minLength":1,"maxLength":240},"x_range":{"type":"string","minLength":1,"maxLength":2000},"x_points":{"type":"integer","minimum":2,"maximum":10000},"y":{"type":"string","minLength":1,"maxLength":240},"y_range":{"type":"string","minLength":1,"maxLength":2000},"y_points":{"type":"integer","minimum":2,"maximum":10000}},"required":["revision","target","x","x_range","y","y_range"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{"total_points":10000},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"grid"},"job.cancel":{"permission":"operation.job","handler":"job","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"job_id":{"type":"string","minLength":1,"maxLength":240}},"required":["job_id"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/job"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"job.status":{"permission":"operation.job","handler":"job","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"job_id":{"type":"string","minLength":1,"maxLength":240}},"required":["job_id"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/job"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"model.capabilities":{"permission":"model.read","handler":"catalog","execution":"sync","timeout_class":"none","request_schema":{"$ref":"model-catalog.schema.json#/$defs/capabilities"},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"model.dependencies":{"permission":"model.read","handler":"catalog","execution":"sync","timeout_class":"none","request_schema":{"$ref":"model-catalog.schema.json#/$defs/dependencies"},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"model.document":{"permission":"model.read","handler":"catalog","execution":"sync","timeout_class":"none","request_schema":{"$ref":"model-catalog.schema.json#/$defs/document"},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"model.get":{"permission":"model.read","handler":"catalog","execution":"sync","timeout_class":"none","request_schema":{"$ref":"model-catalog.schema.json#/$defs/get"},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"model.query":{"permission":"model.read","handler":"catalog","execution":"sync","timeout_class":"none","request_schema":{"$ref":"model-catalog.schema.json#/$defs/query"},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"navigate-source":{"permission":"source.navigate","handler":"host","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"key":{"type":"string","minLength":1,"maxLength":500},"line":{"type":"integer","minimum":1},"column":{"type":"integer","minimum":1}},"required":["key"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"proposal.submit":{"permission":"proposal.submit","handler":"proposal","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"title":{"type":"string","minLength":1,"maxLength":120},"description":{"type":"string","maxLength":500},"changes":{"type":"array","minItems":1,"maxItems":16,"items":{"oneOf":[{"type":"object","properties":{"kind":{"const":"create-from-template"},"template":{"type":"string","minLength":1,"maxLength":500},"document_id":{"type":"string","minLength":1,"maxLength":240},"bindings":{"type":"object","maxProperties":64,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}}},"required":["kind","template","document_id"],"additionalProperties":false},{"type":"object","properties":{"kind":{"const":"create-document"},"document_id":{"type":"string","minLength":1,"maxLength":240},"text":{"type":"string","minLength":1,"maxLength":400000}},"required":["kind","document_id","text"],"additionalProperties":false},{"type":"object","properties":{"kind":{"const":"replace-document"},"key":{"type":"string","minLength":1,"maxLength":500},"base_sha256":{"type":"string","pattern":"^[0-9a-f]{64}$"},"text":{"type":"string","minLength":1,"maxLength":400000}},"required":["kind","key","base_sha256","text"],"additionalProperties":false}]}}},"required":["revision","title","changes"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{"changes":16,"bytes":800000,"bindings":64},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"result.present":{"permission":"result.present","handler":"result","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"handle":{"type":"string","minLength":1,"maxLength":240},"title":{"type":"string","minLength":1,"maxLength":120},"order":{"type":"integer","minimum":-100,"maximum":100}},"required":["handle"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"scan":{"permission":"operation.scan","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"preset":{"oneOf":[{"type":"string","minLength":1,"maxLength":240},{"type":"null"}]},"overrides":{"type":"object","maxProperties":128,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}},"targets":{"type":"array","minItems":1,"maxItems":64,"uniqueItems":true,"items":{"type":"string","minLength":1,"maxLength":240}},"x":{"type":"string","minLength":1,"maxLength":240},"range":{"type":"string","minLength":1,"maxLength":2000},"points":{"type":"integer","minimum":2,"maximum":10000}},"required":["revision","targets","x","range"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{"targets":64,"points":10000},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"scan"},"solve":{"permission":"operation.solve","handler":"operation","execution":"sync","timeout_class":"standard","request_schema":{"type":"object","properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"preset":{"oneOf":[{"type":"string","minLength":1,"maxLength":240},{"type":"null"}]},"overrides":{"type":"object","maxProperties":128,"additionalProperties":{"type":"string","minLength":1,"maxLength":2000}},"target":{"type":"string","minLength":1,"maxLength":240},"variable":{"type":"string","minLength":1,"maxLength":240},"equals":{"type":"string","minLength":1,"maxLength":2000},"range":{"oneOf":[{"type":"string","minLength":1,"maxLength":2000},{"type":"null"}]}},"required":["revision","target","variable","equals"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/operationEnvelope"},"hard_limits":{},"allow_unsaved_overlays":true,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none","operation":"solve"},"storage.delete":{"permission":"storage.preferences","handler":"storage","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"key":{"type":"string","minLength":1,"maxLength":80,"pattern":"^[A-Za-z][A-Za-z0-9._-]*$"}},"required":["key"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"storage.get":{"permission":"storage.preferences","handler":"storage","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"key":{"type":"string","minLength":1,"maxLength":80,"pattern":"^[A-Za-z][A-Za-z0-9._-]*$"}},"required":["key"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"},"storage.set":{"permission":"storage.preferences","handler":"storage","execution":"sync","timeout_class":"none","request_schema":{"type":"object","properties":{"key":{"type":"string","minLength":1,"maxLength":80,"pattern":"^[A-Za-z][A-Za-z0-9._-]*$"},"value":{}},"required":["key","value"],"additionalProperties":false},"result_schema":{"$ref":"protocol.schema.json#/$defs/actionResult"},"hard_limits":{"value_bytes":16384},"allow_unsaved_overlays":false,"allow_durable_run":false,"allow_artifacts":false,"unload_policy":"none"}},"events":{"job-update":{"schema":{"$ref":"protocol.schema.json#/$defs/jobUpdate"}}},"limits":{"max_message_chars":1000000,"max_model_items_per_group":240,"max_model_chars_per_group":120000,"max_target_inputs":128,"max_operation_targets":64,"max_comparison_variants":8,"max_scan_points":10000,"max_plugin_jobs_per_contribution":4,"max_concurrent_operation_jobs":8,"max_expression_chars":2000,"max_draft_source_bytes":400000,"max_pending_proposals":16,"max_proposal_changes":16,"max_proposal_bytes":800000,"max_template_bindings":64,"max_preference_bytes":65536,"max_preference_value_bytes":16384,"max_preference_keys":128,"max_preference_key_chars":80,"max_preference_depth":8,"max_action_id_chars":80,"max_identity_chars":240,"max_path_chars":500,"max_title_chars":120,"max_description_chars":500,"max_variant_name_chars":80,"max_interface_requirements":64,"standard_operation_timeout_seconds":30.0,"analysis_timeout_seconds":3600.0,"default_model_query_limit":50,"max_model_query_limit":100,"max_model_cursor_chars":4096,"max_model_dependency_depth":8,"max_catalog_summary_interfaces":256},"errors":{"interface_unavailable":"a required model interface is unavailable","invalid_request":"the request does not satisfy the public action schema","job_cancelled":"the operation job was explicitly cancelled","limit_exceeded":"the request exceeds a published hard limit","operation_failed":"the mathematical service returned a structured failure","permission_denied":"the contribution did not declare the required permission","plugin_disabled":"the plugin is no longer active or approved","proposal_invalid":"a proposed workspace candidate is invalid","proposal_stale":"a proposal baseline changed before acceptance","result_too_large":"the response cannot fit the plugin message envelope","stale_revision":"the request targets an obsolete workspace revision","unknown_identity":"a requested canonical identity does not exist","unsupported_capability":"the current host does not provide the requested capability","workspace_invalid":"the current workspace overlay cannot be calculated"}};
const CATALOG_SCHEMAS = {"descriptor":{"type":"object","required":["id","kind","owner_id","label","contract","dependencies","interfaces","origin","source_location","payload"],"properties":{"id":{"type":"string","minLength":1,"maxLength":240},"kind":{"enum":["analysis","analysis_chart","dimension","distribution","domain","entry","field","function","group","input","object","object_field","output","preset","process","process_action","process_event","process_input","process_observe","process_state","scenario","scenario_decision","scenario_instance","scenario_measure","scenario_objective","scenario_policy","scenario_variant","source","static_chart","table","type","type_field","unit"]},"owner_id":{"type":["string","null"]},"label":{"type":"string"},"contract":{"type":"object"},"dependencies":{"type":"array","items":{"type":"string","minLength":1,"maxLength":240}},"interfaces":{"type":"array","items":{"type":"object"}},"origin":{"type":"object"},"source_location":{"type":"object"},"payload":{"type":"object"}},"additionalProperties":false},"query":{"type":"object","required":["revision"],"properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"kind":{"oneOf":[{"enum":["analysis","analysis_chart","dimension","distribution","domain","entry","field","function","group","input","object","object_field","output","preset","process","process_action","process_event","process_input","process_observe","process_state","scenario","scenario_decision","scenario_instance","scenario_measure","scenario_objective","scenario_policy","scenario_variant","source","static_chart","table","type","type_field","unit"]},{"type":"array","minItems":1,"items":{"enum":["analysis","analysis_chart","dimension","distribution","domain","entry","field","function","group","input","object","object_field","output","preset","process","process_action","process_event","process_input","process_observe","process_state","scenario","scenario_decision","scenario_instance","scenario_measure","scenario_objective","scenario_policy","scenario_variant","source","static_chart","table","type","type_field","unit"]}}]},"interface":{"type":"string","minLength":1,"maxLength":240},"interface_revision":{"type":"integer","minimum":1},"owner":{"type":"string","minLength":1,"maxLength":240},"prefix":{"type":"string","minLength":1,"maxLength":240},"cursor":{"type":["string","null"],"maxLength":4096},"limit":{"type":"integer","minimum":1,"maximum":100}},"additionalProperties":false},"get":{"type":"object","required":["revision","id"],"properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"id":{"type":"string","minLength":1,"maxLength":240},"kind":{"enum":["analysis","analysis_chart","dimension","distribution","domain","entry","field","function","group","input","object","object_field","output","preset","process","process_action","process_event","process_input","process_observe","process_state","scenario","scenario_decision","scenario_instance","scenario_measure","scenario_objective","scenario_policy","scenario_variant","source","static_chart","table","type","type_field","unit"]}},"additionalProperties":false},"dependencies":{"type":"object","required":["revision","id"],"properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"id":{"type":"string","minLength":1,"maxLength":240},"kind":{"enum":["analysis","analysis_chart","dimension","distribution","domain","entry","field","function","group","input","object","object_field","output","preset","process","process_action","process_event","process_input","process_observe","process_state","scenario","scenario_decision","scenario_instance","scenario_measure","scenario_objective","scenario_policy","scenario_variant","source","static_chart","table","type","type_field","unit"]},"depth":{"type":"integer","minimum":1,"maximum":8}},"additionalProperties":false},"document":{"type":"object","required":["revision","id"],"properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"},"id":{"type":"string","minLength":1,"maxLength":240}},"additionalProperties":false},"capabilities":{"type":"object","required":["revision"],"properties":{"revision":{"type":"string","pattern":"^[0-9a-f]{64}$"}},"additionalProperties":false}};
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
