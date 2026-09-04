// Generated Kirin Tor Plugin SDK declarations v2. Do not edit.
export type KirinAction = "analyze" | "compare" | "evaluate" | "evaluate-many" | "explain" | "grid" | "job.cancel" | "job.status" | "model.capabilities" | "model.dependencies" | "model.document" | "model.get" | "model.query" | "navigate-source" | "proposal.submit" | "result.present" | "scan" | "solve" | "storage.delete" | "storage.get" | "storage.set";
export type KirinActionResult = { status: string } & Record<string, unknown>;
export type KirinCatalogResult = KirinActionResult;
export interface KirinProposalResult { status: "queued" | "rejected"; proposal_id?: string; reason?: string; errors?: unknown[]; }
export interface KirinResultPresentation { status: "ok"; handle: string; }
export interface KirinStorageGetResult { status: "ok"; key: string; found: boolean; value?: unknown; }
export interface KirinStorageSetResult { status: "ok"; key: string; bytes: number; }
export interface KirinStorageDeleteResult { status: "ok"; key: string; removed: boolean; }
export interface KirinOperationEnvelope { status: "ok"; operation_id: string; operation: string; revision: string; targets: string[]; applied: { preset: string | null; overrides: Record<string, string> }; provenance: Record<string, unknown>; warnings: unknown[]; result: Record<string, any>; }
export interface KirinJob { status: "ok" | "accepted"; job_id: string; operation: string; state: "queued" | "running" | "completed" | "failed" | "cancelled"; stage: "queued" | "executing" | "completed" | "failed" | "cancelled"; cancellable: boolean; result?: KirinOperationEnvelope; error?: { code?: string; message?: string; [key: string]: unknown }; }
export interface KirinActionPayloads {
  "analyze": { "revision"?: string; "target": string; "include_trace"?: boolean; };
  "compare": { "revision"?: string; "target": string; "variants": Array<{ "name": string; "preset"?: string | null; "overrides"?: Record<string, string>; }>; };
  "evaluate": { "revision"?: string; "preset"?: string | null; "overrides"?: Record<string, string>; "target": string; };
  "evaluate-many": { "revision"?: string; "preset"?: string | null; "overrides"?: Record<string, string>; "targets": Array<string>; };
  "explain": { "revision"?: string; "target": string; };
  "grid": { "revision"?: string; "preset"?: string | null; "overrides"?: Record<string, string>; "target": string; "x": string; "x_range": string; "x_points"?: number; "y": string; "y_range": string; "y_points"?: number; };
  "job.cancel": { "job_id": string; };
  "job.status": { "job_id": string; };
  "model.capabilities": { "revision"?: string; };
  "model.dependencies": { "revision"?: string; "id": string; "kind"?: "analysis" | "analysis_chart" | "dimension" | "distribution" | "domain" | "entry" | "field" | "function" | "group" | "input" | "object" | "object_field" | "output" | "preset" | "process" | "process_action" | "process_event" | "process_input" | "process_observe" | "process_state" | "scenario" | "scenario_decision" | "scenario_instance" | "scenario_measure" | "scenario_objective" | "scenario_policy" | "scenario_variant" | "source" | "static_chart" | "table" | "type" | "type_field" | "unit"; "depth"?: number; };
  "model.document": { "revision"?: string; "id": string; };
  "model.get": { "revision"?: string; "id": string; "kind"?: "analysis" | "analysis_chart" | "dimension" | "distribution" | "domain" | "entry" | "field" | "function" | "group" | "input" | "object" | "object_field" | "output" | "preset" | "process" | "process_action" | "process_event" | "process_input" | "process_observe" | "process_state" | "scenario" | "scenario_decision" | "scenario_instance" | "scenario_measure" | "scenario_objective" | "scenario_policy" | "scenario_variant" | "source" | "static_chart" | "table" | "type" | "type_field" | "unit"; };
  "model.query": { "revision"?: string; "kind"?: "analysis" | "analysis_chart" | "dimension" | "distribution" | "domain" | "entry" | "field" | "function" | "group" | "input" | "object" | "object_field" | "output" | "preset" | "process" | "process_action" | "process_event" | "process_input" | "process_observe" | "process_state" | "scenario" | "scenario_decision" | "scenario_instance" | "scenario_measure" | "scenario_objective" | "scenario_policy" | "scenario_variant" | "source" | "static_chart" | "table" | "type" | "type_field" | "unit" | Array<"analysis" | "analysis_chart" | "dimension" | "distribution" | "domain" | "entry" | "field" | "function" | "group" | "input" | "object" | "object_field" | "output" | "preset" | "process" | "process_action" | "process_event" | "process_input" | "process_observe" | "process_state" | "scenario" | "scenario_decision" | "scenario_instance" | "scenario_measure" | "scenario_objective" | "scenario_policy" | "scenario_variant" | "source" | "static_chart" | "table" | "type" | "type_field" | "unit">; "interface"?: string; "interface_revision"?: number; "owner"?: string; "prefix"?: string; "cursor"?: string | null; "limit"?: number; };
  "navigate-source": { "key": string; "line"?: number; "column"?: number; };
  "proposal.submit": { "revision"?: string; "title": string; "description"?: string; "changes": Array<{ "kind": "create-from-template"; "template": string; "document_id": string; "bindings"?: Record<string, string>; } | { "kind": "create-document"; "document_id": string; "text": string; } | { "kind": "replace-document"; "key": string; "base_sha256": string; "text": string; }>; };
  "result.present": { "handle": string; "title"?: string; "order"?: number; };
  "scan": { "revision"?: string; "preset"?: string | null; "overrides"?: Record<string, string>; "targets": Array<string>; "x": string; "range": string; "points"?: number; };
  "solve": { "revision"?: string; "preset"?: string | null; "overrides"?: Record<string, string>; "target": string; "variable": string; "equals": string; "range"?: string | null; };
  "storage.delete": { "key": string; };
  "storage.get": { "key": string; };
  "storage.set": { "key": string; "value": unknown; };
}
export interface KirinActionResults {
  "analyze": KirinJob;
  "compare": KirinOperationEnvelope;
  "evaluate": KirinOperationEnvelope;
  "evaluate-many": KirinOperationEnvelope;
  "explain": KirinOperationEnvelope;
  "grid": KirinOperationEnvelope;
  "job.cancel": KirinJob;
  "job.status": KirinJob;
  "model.capabilities": KirinCatalogResult;
  "model.dependencies": KirinCatalogResult;
  "model.document": KirinCatalogResult;
  "model.get": KirinCatalogResult;
  "model.query": KirinCatalogResult;
  "navigate-source": KirinActionResult;
  "proposal.submit": KirinProposalResult;
  "result.present": KirinResultPresentation;
  "scan": KirinOperationEnvelope;
  "solve": KirinOperationEnvelope;
  "storage.delete": KirinStorageDeleteResult;
  "storage.get": KirinStorageGetResult;
  "storage.set": KirinStorageSetResult;
}
export interface KirinActivation { contribution: Record<string, unknown>; context: Record<string, any>; capabilities: Record<string, unknown>; }
export declare class KirinPluginError extends Error { code: string; details: unknown; }
export interface KirinPlugin {
  readonly descriptor: Record<string, unknown>;
  readonly context: Record<string, any>;
  readonly contribution: Record<string, unknown> | null;
  ready(): Promise<KirinActivation>;
  request<A extends KirinAction>(action: A, payload: KirinActionPayloads[A]): Promise<KirinActionResults[A]>;
  dispose(): void;
  onContext(listener: (context: Record<string, any>, contribution: Record<string, unknown>) => void): () => void;
  model: { query(payload?: KirinActionPayloads["model.query"]): Promise<KirinCatalogResult>; pages(query?: KirinActionPayloads["model.query"]): AsyncGenerator<KirinCatalogResult>; all(query?: KirinActionPayloads["model.query"]): Promise<Record<string, unknown>[]>; get(payload: KirinActionPayloads["model.get"]): Promise<KirinCatalogResult>; dependencies(payload: KirinActionPayloads["model.dependencies"]): Promise<KirinCatalogResult>; document(payload: KirinActionPayloads["model.document"]): Promise<KirinCatalogResult>; capabilities(payload?: KirinActionPayloads["model.capabilities"]): Promise<KirinCatalogResult>; };
  operations: { evaluate(payload: KirinActionPayloads["evaluate"]): Promise<KirinOperationEnvelope>; evaluateMany(payload: KirinActionPayloads["evaluate-many"]): Promise<KirinOperationEnvelope>; explain(payload: KirinActionPayloads["explain"]): Promise<KirinOperationEnvelope>; compare(payload: KirinActionPayloads["compare"]): Promise<KirinOperationEnvelope>; scan(payload: KirinActionPayloads["scan"]): Promise<KirinOperationEnvelope>; grid(payload: KirinActionPayloads["grid"]): Promise<KirinOperationEnvelope>; solve(payload: KirinActionPayloads["solve"]): Promise<KirinOperationEnvelope>; analyze(payload: KirinActionPayloads["analyze"]): Promise<KirinJob>; };
  results: { present(handle: string, options?: Omit<KirinActionPayloads["result.present"], "handle">): Promise<KirinResultPresentation>; };
  storage: { get(key: string): Promise<KirinStorageGetResult>; set(key: string, value: unknown): Promise<KirinStorageSetResult>; delete(key: string): Promise<KirinStorageDeleteResult>; };
  proposals: { submit(payload: KirinActionPayloads["proposal.submit"]): Promise<KirinProposalResult>; };
  jobs: { status(jobId: string): Promise<KirinJob>; cancel(jobId: string): Promise<KirinJob>; wait(handle: string | KirinJob, options?: { interval?: number }): Promise<KirinOperationEnvelope>; onUpdate(listener: (job: KirinJob) => void): () => void; };
}
export declare function createKirinPlugin(options?: { api?: 2 | "2" }): KirinPlugin;
