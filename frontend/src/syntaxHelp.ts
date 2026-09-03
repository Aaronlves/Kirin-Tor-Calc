import type { AuthoringContract, DiagnosticItem } from "./types";

const sectionTopics: Record<string, string> = {
  phases: "process",
  objectives: "process",
  variants: "process",
  search: "process",
  series: "process",
  markers: "process",
  bounds: "process",
  sequence: "process",
  y: "charts",
};

export function syntaxTopicForKind(contract: AuthoringContract, kind?: string): string | null {
  if (!kind) return null;
  return contract.reference_identities[kind]?.topic ?? null;
}

export function syntaxSymbolForKind(contract: AuthoringContract, kind?: string): string | null {
  if (!kind) return null;
  return contract.reference_identities[kind]?.symbol ?? null;
}

export function syntaxTopicForLine(line: string): string | null {
  const trimmed = line.trim();
  const section = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*):/)?.[1];
  if (sectionTopics[section ?? ""]) return sectionTopics[section ?? ""];
  if (/^@(kirin|entry|game-version|status)\b/.test(trimmed)) return "document";
  if (/^type\b/.test(trimmed)) return "structures";
  if (/^(process|scenario|analysis|state|key|phase|event|action|flow|on|observe|let|next|emit|schedule|replace|cancel|when|branch|probability|use|variant|connect|at|every|send|policy|choose|otherwise|decide|measure|objective|maximize|minimize|then|stop|target|operation)\b/.test(trimmed)) return "process";
  if (/^(horizon|maximum_events|maximum_decisions|maximum_branches|maximum_entities|method|time_tolerance|maximum_evaluations)\b/.test(trimmed)) return "process";
  for (const [pattern, topic] of [[/^(alias|source)\b/, "aliases"], [/^(input|field|function|output|require)\b/, "members"], [/^preset\b|^group\b|^display\b/, "presets"], [/^table\b/, "tables"], [/^distribution\b/, "distributions"], [/^(dimension|unit|domain)\b/, "semantics"], [/^chart\b/, "charts"]] as Array<[RegExp, string]>) {
    if (pattern.test(trimmed)) return topic;
  }
  if (/\b(true|false|one-of|boolean|integer|probability|dimensionless|nonnegative_integer|positive_integer)\b/.test(line)) return "semantics";
  return null;
}

export function syntaxSymbolForLine(line: string): string | null {
  const trimmed = line.trim();
  if (/^@(kirin|entry)\b/.test(trimmed)) return "document-header";
  if (/^@(game-version|status)\b/.test(trimmed)) return "metadata-directives";
  if (/^-{3,}$/.test(trimmed) || trimmed.startsWith("//")) return "comments-and-prose";
  for (const [pattern, symbol] of [
    [/^input\b/, "input"], [/^field\b/, "field"], [/^function\b/, "function"],
    [/^output\b/, "output"], [/^require\b/, "require"], [/^alias\b/, "alias"],
    [/^source\b/, "source"], [/^display\b/, "display"], [/^group\b/, "group"],
    [/^preset\b/, "preset"], [/^table\b/, "table"], [/^distribution\b/, "distribution"],
    [/^dimension\b/, "dimension"], [/^unit\b/, "unit"], [/^domain\b/, "numeric-domain"],
    [/^type\b/, "type"],
    [/^(let|next|emit|schedule|replace|cancel|when|branch|probability)\b/, "process-effects"],
    [/^(process|state|key|phase|event|flow|on|observe)\b/, "process-declarations"],
    [/^(policy|choose|otherwise|decide|sequence)\b/, "scenario-policies-decisions"],
    [/^(measure|objective|maximize|minimize|then)\b/, "scenario-measures-objectives"],
    [/^(scenario|phases|use|variant|connect|at|every|send|stop|bounds)\b/, "scenario"],
    [/^(analysis|using|operation|policies|objectives|variants|target|search|method|time_tolerance|maximum_evaluations)\b/, "analysis"],
    [/^chart\b/, "static-chart"],
  ] as Array<[RegExp, string]>) {
    if (pattern.test(trimmed)) return symbol;
  }
  if (/\b(size|contains|empty|get|put|remove|filter|argmin|argmax|elapsed|event_count|decision_count|horizon)\b/.test(trimmed)) return "process-expressions";
  if (/\b(if_else|piecewise|abs|min|max|sqrt|floor|ceil|sum|product)\b/.test(trimmed)) return "scalar-expression";
  return null;
}

function syntaxLocationForDiagnostic(item: DiagnosticItem): { topic: string; symbol: string } | null {
  const field = item.location?.field?.toLocaleLowerCase() ?? "";
  if (/^processes(?:\.|$)/.test(field)) {
    return { topic: "process", symbol: field.includes(".effects") ? "process-effects" : "process-declarations" };
  }
  if (/^scenarios(?:\.|$)/.test(field)) {
    if (field.includes(".policies") || field.includes(".decisions")) {
      return { topic: "process", symbol: "scenario-policies-decisions" };
    }
    if (field.includes(".measures") || field.includes(".objectives")) {
      return { topic: "process", symbol: "scenario-measures-objectives" };
    }
    return { topic: "process", symbol: "scenario" };
  }
  if (/^analyses(?:\.|$)/.test(field)) {
    return { topic: "process", symbol: field.includes(".charts") ? "analysis-chart" : "analysis" };
  }
  if (/^charts(?:\.|$)/.test(field)) return { topic: "charts", symbol: "static-chart" };
  if (/^types(?:\.|$)/.test(field)) return { topic: "structures", symbol: "type" };
  if (/^objects(?:\.|$)/.test(field)) return { topic: "structures", symbol: "object" };
  return null;
}

export function syntaxTopicForDiagnostic(item: DiagnosticItem, line = ""): string {
  const located = syntaxLocationForDiagnostic(item);
  if (located) return located.topic;
  const direct = syntaxTopicForLine(line);
  if (direct) return direct;
  const message = `${item.code ?? ""} ${item.author_message ?? ""} ${item.message ?? ""}`.toLocaleLowerCase();
  for (const [needle, topic] of [
    ["alias", "aliases"], ["别名", "aliases"], ["table", "tables"], ["查表", "tables"],
    ["distribution", "distributions"], ["分布", "distributions"], ["preset", "presets"], ["参数方案", "presets"],
    ["cycle", "process"], ["sequence", "process"], ["循环", "process"], ["等待", "process"],
    ["process", "process"], ["scenario", "process"], ["analysis", "process"], ["measure", "process"], ["过程", "process"],
    ["unit", "semantics"], ["dimension", "semantics"], ["domain", "semantics"], ["单位", "semantics"], ["量纲", "semantics"],
    ["chart", "charts"], ["图表", "charts"],
  ] as Array<[string, string]>) {
    if (message.includes(needle)) return topic;
  }
  return "document";
}

export function syntaxSymbolForDiagnostic(item: DiagnosticItem, line = ""): string | null {
  const located = syntaxLocationForDiagnostic(item);
  if (located) return located.symbol;
  const direct = syntaxSymbolForLine(line);
  if (direct) return direct;
  const message = `${item.author_message ?? ""} ${item.message ?? ""}`.toLocaleLowerCase();
  if (message.includes("analysis chart")) return "analysis-chart";
  if (message.includes("process effect")) return "process-effects";
  if (message.includes("process")) return "process-declarations";
  if (message.includes("scenario")) return "scenario";
  if (message.includes("expression") || message.includes("公式")) return "scalar-expression";
  return null;
}

export function openSyntaxReference(topic: string, symbol?: string): void {
  window.dispatchEvent(new CustomEvent("kirin:open-syntax-reference", { detail: { topic, symbol } }));
}
