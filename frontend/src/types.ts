export type ViewId = "documents" | "graph";
export type WorkspaceTool = "runs" | "packages" | "syntax" | "search" | "changes";
export type DocumentFocusMode = "editor" | "split" | "preview";

export interface PackageReference {
  name: string;
  version: string;
  source: string;
  content_sha256: string;
}

export interface DocumentItem {
  key: string;
  path: string;
  title: string;
  kind: "entry" | string;
  read_only: boolean;
  source_sha256: string | null;
  package?: PackageReference;
}

export interface DocumentPayload extends DocumentItem {
  status: "ok";
  text: string;
}

export interface ExternalChangeConflict {
  key: string;
  path: string;
  base?: string | null;
  draft: string;
  disk: string;
  disk_sha256?: string | null;
}

export interface WorkspaceSearchMatch {
  key: string;
  path: string;
  line: number;
  column: number;
  preview: string;
  read_only: boolean;
}

export interface GitSummary {
  available: boolean;
  root?: string;
  commits: Array<{ sha: string; date: string; subject: string }>;
  working_tree: string[];
}

export interface CompletionItem {
  label: string;
  detail?: string;
  insert_text: string;
  kind?: string;
  priority?: number;
}

export interface AuthoringLocation {
  key: string;
  path: string;
  line: number;
  column: number;
  end_column: number;
  read_only: boolean;
}

export interface AuthoringSymbol {
  id: string;
  name: string;
  label: string;
  kind: string;
  entry_id?: string;
  detail: string;
  signature?: string;
  unit?: string | null;
  parameters?: string[];
  target?: string;
  definition: AuthoringLocation;
  renameable: boolean;
  outline: boolean;
  outline_level: number;
}

export interface AuthoringReference {
  symbol_id: string;
  text: string;
  location: AuthoringLocation;
  via_alias: boolean;
}

export interface AuthoringBuiltin {
  id: string;
  name: string;
  label: string;
  kind: string;
  detail: string;
  signature?: string;
}

export interface AuthoringIndex {
  symbols: AuthoringSymbol[];
  references: AuthoringReference[];
  builtins: AuthoringBuiltin[];
}

export interface AuthoringChange {
  key: string;
  path: string;
  before: string;
  text: string;
}

export interface RecoveryDraft {
  text: string;
  base_sha256: string | null;
  document: DocumentItem;
}

export interface RecoveryPayload {
  version: number;
  drafts: Record<string, RecoveryDraft>;
}

export interface DiagnosticLocation {
  path?: string;
  line?: number;
  column?: number;
}

export interface DiagnosticItem {
  code?: string;
  message?: string;
  author_message?: string;
  location?: DiagnosticLocation;
}

export interface TargetItem {
  value: string;
  label: string;
  group_label?: string;
  unit?: string;
  inputs?: string[];
  line?: number | null;
  column?: number | null;
  [key: string]: unknown;
}

export interface InputItem {
  value: string;
  label: string;
  unit?: string;
  value_type?: string;
  default?: unknown;
  minimum?: unknown;
  maximum?: unknown;
  [key: string]: unknown;
}

export interface PresetItem {
  value: string;
  label: string;
  [key: string]: unknown;
}

export interface ChartItem {
  value: string;
  label: string;
  line?: number | null;
  column?: number | null;
  [key: string]: unknown;
}

export interface WorkspaceIndex {
  targets: TargetItem[];
  inputs: InputItem[];
  presets: PresetItem[];
  charts: ChartItem[];
  document_ids?: string[];
}

export interface ValidationResult {
  status: "ok" | "error";
  documents?: number;
  errors?: DiagnosticItem[];
  index?: WorkspaceIndex;
  code?: string;
  message?: string;
  author_message?: string;
  authoring?: AuthoringIndex;
  [key: string]: unknown;
}

export interface TemplateItem {
  id: string;
  value: string;
  label: string;
  kind: string;
  origin: "builtin" | "workspace" | "package" | string;
  error?: string;
  package_name?: string;
  package_version?: string;
  [key: string]: unknown;
}

export interface RunItem {
  id: string;
  operation?: string;
  created_at?: string;
  status?: string;
  error?: DiagnosticItem;
}

export interface InstalledPackage {
  alias?: string;
  direct: boolean;
  source: string;
  name: string;
  version: string;
  namespace: string;
  description?: string;
  license?: string;
  game?: string;
  game_version?: string;
  resolved: string;
  content_sha256: string;
  dependencies?: Record<string, { source: string; version: string }>;
}

export interface BootstrapPayload {
  status: "ok";
  version: string;
  workspace: string;
  documents: DocumentItem[];
  templates: TemplateItem[];
  packages: InstalledPackage[];
  runs: RunItem[];
  validation: ValidationResult;
  index: WorkspaceIndex;
  authoring: AuthoringIndex;
  recovery: RecoveryPayload;
}

export interface Variant {
  id: string;
  name: string;
  preset: string;
  overrides: string;
}

export interface OperationResult {
  status?: string;
  operation?: string;
  [key: string]: unknown;
}

export interface OperationJobStatus {
  status: "ok";
  job_id: string;
  operation: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  stage: "queued" | "executing" | "completed" | "failed" | "cancelled";
  started_at: number;
  cancellable: boolean;
  result?: OperationResult;
  error?: Record<string, unknown>;
}

export type RelationshipNodeKind = "input" | "field" | "function" | "table" | "output" | string;

export interface RelationshipNode {
  id: string;
  label: string;
  kind: RelationshipNodeKind;
  document_id: string;
  path: string;
  line?: number | null;
  column?: number | null;
  unit?: string | null;
  expression?: string | null;
  read_only: boolean;
}

export interface RelationshipEdge {
  id: string;
  source: string;
  target: string;
  kind: string;
  count?: number;
}

export interface RelationshipDocument {
  id: string;
  label: string;
  path: string;
  read_only: boolean;
  has_chart: boolean;
  package?: { name: string; version: string; source: string } | null;
}

export interface RelationshipGraphResult extends OperationResult {
  operation: "relationship_graph";
  nodes: RelationshipNode[];
  edges: RelationshipEdge[];
  documents: RelationshipDocument[];
  document_edges: RelationshipEdge[];
}

export type AsyncState = "idle" | "connecting" | "validating" | "saving" | "running";
