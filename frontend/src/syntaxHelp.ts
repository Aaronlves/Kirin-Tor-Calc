import type { DiagnosticItem } from "./types";

const sectionTopics: Record<string, string> = {
  aliases: "aliases",
  inputs: "members",
  fields: "members",
  functions: "members",
  outputs: "members",
  presets: "presets",
  tables: "tables",
  distributions: "distributions",
  recurrences: "recurrences",
  state_models: "state-models",
  dimensions: "semantics",
  units: "semantics",
  domains: "semantics",
  display: "charts",
  y: "charts",
};

const kindTopics: Record<string, string> = {
  entry: "document",
  alias: "aliases",
  input: "members",
  field: "members",
  function: "members",
  output: "members",
  preset: "presets",
  table: "tables",
  distribution: "distributions",
  recurrence: "recurrences",
  state_model: "state-models",
  dimension: "semantics",
  unit: "semantics",
  domain: "semantics",
  chart: "charts",
};

export function syntaxTopicForKind(kind?: string): string | null {
  if (!kind) return null;
  return kindTopics[kind] ?? (kind === "keyword" ? "document" : null);
}

export function syntaxTopicForLine(line: string): string | null {
  const section = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*):/)?.[1];
  if (sectionTopics[section ?? ""]) return sectionTopics[section ?? ""];
  if (/^@(kirin|entry|game-version|status)\b/.test(line.trim())) return "document";
  if (/\b(one-of|boolean|integer|probability|dimensionless|nonnegative_integer|positive_integer)\b/.test(line)) return "semantics";
  return null;
}

export function syntaxTopicForDiagnostic(item: DiagnosticItem, line = ""): string {
  const direct = syntaxTopicForLine(line);
  if (direct) return direct;
  const message = `${item.code ?? ""} ${item.author_message ?? ""} ${item.message ?? ""}`.toLocaleLowerCase();
  for (const [needle, topic] of [
    ["alias", "aliases"], ["别名", "aliases"], ["table", "tables"], ["查表", "tables"],
    ["distribution", "distributions"], ["分布", "distributions"], ["recurrence", "recurrences"], ["递推", "recurrences"],
    ["state", "state-models"], ["状态", "state-models"], ["preset", "presets"], ["参数方案", "presets"],
    ["unit", "semantics"], ["dimension", "semantics"], ["domain", "semantics"], ["单位", "semantics"], ["量纲", "semantics"],
    ["chart", "charts"], ["图表", "charts"],
  ] as Array<[string, string]>) {
    if (message.includes(needle)) return topic;
  }
  return "document";
}

export function openSyntaxReference(topic: string): void {
  window.dispatchEvent(new CustomEvent("kirin:open-syntax-reference", { detail: { topic } }));
}
