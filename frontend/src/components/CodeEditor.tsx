import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
  type Completion,
  type CompletionContext,
} from "@codemirror/autocomplete";
import {
  defaultKeymap,
  history,
  historyField,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  bracketMatching,
  foldGutter,
  foldKeymap,
  foldService,
  HighlightStyle,
  indentService,
  indentUnit,
  StreamLanguage,
  syntaxHighlighting,
  type StreamParser,
} from "@codemirror/language";
import { lintGutter, lintKeymap, type Diagnostic, setDiagnostics } from "@codemirror/lint";
import { gotoLine, search, searchKeymap } from "@codemirror/search";
import { EditorState, Transaction } from "@codemirror/state";
import {
  crosshairCursor,
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  hoverTooltip,
  keymap,
  lineNumbers,
  rectangularSelection,
  tooltips,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

import { authoringTargetAt, codePointColumn, utf16OffsetForColumn, type AuthoringTarget } from "../authoring";
import type { AuthoringContract, AuthoringIndex, AuthoringLocation, CompletionItem, CompletionRequest, DiagnosticItem } from "../types";
import { openSyntaxReference, syntaxSymbolForDiagnostic, syntaxSymbolForKind, syntaxTopicForDiagnostic, syntaxTopicForKind, syntaxTopicForLine } from "../syntaxHelp";
import { fullWidthSyntaxReplacements } from "../editorSupport";

interface KirinParserState {
  section: string | null;
  proseFence: string | null;
}

const editorSessions = new Map<string, unknown>();
const kirinEditorPhrases: Record<string, string> = {
  Find: "查找",
  Replace: "替换为",
  next: "下一个",
  previous: "上一个",
  all: "选择全部匹配",
  "match case": "区分大小写",
  regexp: "正则表达式",
  "by word": "全词匹配",
  replace: "替换",
  "replace all": "全部替换",
  close: "关闭",
  "current match": "当前匹配",
  "on line": "所在行",
  "replaced match on line $": "已替换第 $ 行的匹配项",
  "replaced $ matches": "已替换 $ 个匹配项",
  "Go to line": "转到行",
  go: "转到",
};

export interface EditorCursorContext {
  symbolId: string | null;
  containerSymbolId: string | null;
  callSymbolId: string | null;
  activeParameter: number | null;
  line: number;
  column: number;
  selectionCharacters: number;
  selectionLines: number;
  selectionRanges: number;
}

const identifierPattern = /^[A-Za-z_\u0080-\uFFFF][\w\u0080-\uFFFF]*(?:\.[A-Za-z_\u0080-\uFFFF][\w\u0080-\uFFFF]*)*/u;

function escapedOperator(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function prepareCompletionInsertion(text: string, indent: string): { text: string; cursor: number } {
  const indented = text.replace(/\n/g, `\n${indent}`);
  const cursor = indented.indexOf("$0");
  if (cursor < 0) return { text: indented, cursor: indented.length };
  return { text: indented.replace("$0", ""), cursor };
}

function locationRange(state: EditorState, location: AuthoringLocation): { from: number; to: number } | null {
  if (location.line < 1 || location.line > state.doc.lines) return null;
  const line = state.doc.line(location.line);
  const from = line.from + utf16OffsetForColumn(line.text, location.column);
  const to = line.from + utf16OffsetForColumn(line.text, location.end_column);
  return { from: Math.min(line.to, from), to: Math.min(line.to, Math.max(from, to)) };
}

function diagnosticTokenRange(state: EditorState, lineNumber: number, column: number): { from: number; to: number } {
  const line = state.doc.line(Math.min(Math.max(1, lineNumber), state.doc.lines));
  const requested = Math.min(line.text.length, utf16OffsetForColumn(line.text, Math.max(1, column)));
  const tail = line.text.slice(requested);
  const leading = tail.match(/^\s*/)?.[0].length ?? 0;
  const start = Math.min(line.text.length, requested + leading);
  const token = line.text.slice(start).match(/^(?:[A-Za-z_\u0080-\uFFFF][\w.\u0080-\uFFFF]*|@[A-Za-z_-]+|\d+(?:\.\d+)?|\S)/u)?.[0] ?? "";
  const from = line.from + start;
  return { from, to: Math.min(line.to, from + Math.max(1, token.length)) };
}

function targetAtPosition(state: EditorState, authoring: AuthoringIndex, documentKey: string, position: number): AuthoringTarget | null {
  const line = state.doc.lineAt(position);
  const column = codePointColumn(line.text, position - line.from);
  return authoringTargetAt(authoring, documentKey, line.number, column);
}

function callContext(state: EditorState, authoring: AuthoringIndex, documentKey: string, position: number) {
  const source = state.sliceDoc(0, position);
  const openings: number[] = [];
  let quoted = false;
  let escaped = false;
  let comment = false;
  let proseFence: string | null = null;
  let lineStart = 0;
  for (let offset = 0; offset < source.length; offset += 1) {
    const character = source[offset];
    if (character === "\n") {
      if (!quoted) {
        const lineText = source.slice(lineStart, offset);
        if (/^-{3,}$/.test(lineText)) {
          proseFence = proseFence === null ? lineText : proseFence === lineText ? null : proseFence;
        }
      }
      comment = false;
      lineStart = offset + 1;
      continue;
    }
    if (comment || proseFence !== null) continue;
    if (quoted) {
      if (character === '"' && !escaped) quoted = false;
      escaped = character === "\\" && !escaped;
      if (character !== "\\") escaped = false;
      continue;
    }
    if (character === "/" && source[offset + 1] === "/") {
      comment = true;
      offset += 1;
      continue;
    }
    if (character === '"') {
      quoted = true;
      continue;
    }
    if (character === "(") openings.push(offset);
    else if (character === ")") openings.pop();
  }
  const opening = openings.at(-1);
  if (opening === undefined) return { symbolId: null, activeParameter: null };
  const nameMatch = source.slice(0, opening).match(/([A-Za-z_\u0080-\uFFFF][\w.\u0080-\uFFFF]*)\s*$/u);
  if (!nameMatch || nameMatch.index === undefined) return { symbolId: null, activeParameter: null };
  const nameOffset = nameMatch.index;
  const name = nameMatch[1];
  const line = state.doc.lineAt(nameOffset);
  const column = codePointColumn(line.text, nameOffset - line.from);
  const target = authoringTargetAt(authoring, documentKey, line.number, column);
  let nested = 0;
  let commas = 0;
  quoted = false;
  escaped = false;
  comment = false;
  proseFence = null;
  lineStart = opening + 1;
  for (let offset = opening + 1; offset < source.length; offset += 1) {
    const character = source[offset];
    if (character === "\n") {
      if (!quoted) {
        const lineText = source.slice(lineStart, offset);
        if (/^-{3,}$/.test(lineText)) {
          proseFence = proseFence === null ? lineText : proseFence === lineText ? null : proseFence;
        }
      }
      comment = false;
      lineStart = offset + 1;
      continue;
    }
    if (comment || proseFence !== null) continue;
    if (quoted) {
      if (character === '"' && !escaped) quoted = false;
      escaped = character === "\\" && !escaped;
      if (character !== "\\") escaped = false;
      continue;
    }
    if (character === "/" && source[offset + 1] === "/") {
      comment = true;
      offset += 1;
    } else if (character === '"') quoted = true;
    else if (character === "(" || character === "[" || character === "{") nested += 1;
    else if (character === ")" || character === "]" || character === "}") nested = Math.max(0, nested - 1);
    else if (character === "," && nested === 0) commas += 1;
  }
  const topDeclaration = source.slice(0, opening).split("\n").reverse().find((lineText) => (
    lineText.length > 0 && !/^\s/.test(lineText)
  )) ?? "";
  const preferredScopes = /^process\b/.test(topDeclaration)
    ? ["process"]
    : /^(scenario|analysis)\b/.test(topDeclaration)
      ? ["measure", "process"]
      : ["static"];
  const builtin = preferredScopes
    .map((scope) => authoring.builtins.find((item) => item.name === name && item.scope === scope))
    .find(Boolean);
  return {
    symbolId: target?.id ?? builtin?.id ?? null,
    activeParameter: commas + 1,
  };
}

function selectionMetrics(state: EditorState) {
  const ranges = state.selection.ranges.filter((range) => !range.empty);
  return {
    characters: ranges.reduce((total, range) => total + Array.from(state.sliceDoc(range.from, range.to)).length, 0),
    lines: ranges.reduce((total, range) => total + state.doc.lineAt(range.to).number - state.doc.lineAt(range.from).number + 1, 0),
    ranges: ranges.length,
  };
}

function kirinFoldRange(state: EditorState, lineStart: number) {
  const line = state.doc.lineAt(lineStart);
  const trimmed = line.text.trim();
  if (/^-{3,}$/.test(trimmed)) {
    for (let number = line.number + 1; number <= state.doc.lines; number += 1) {
      const candidate = state.doc.line(number);
      if (candidate.text.trim() === trimmed) return { from: line.to, to: candidate.from };
    }
    return null;
  }
  if (!trimmed.endsWith(":")) return null;
  const indent = line.text.length - line.text.trimStart().length;
  let last = line;
  for (let number = line.number + 1; number <= state.doc.lines; number += 1) {
    const candidate = state.doc.line(number);
    if (!candidate.text.trim()) {
      last = candidate;
      continue;
    }
    const candidateIndent = candidate.text.length - candidate.text.trimStart().length;
    if (candidateIndent <= indent) break;
    last = candidate;
  }
  return last.number > line.number ? { from: line.to, to: last.to } : null;
}

function quickFixes(view: EditorView, lineNumber: number) {
  if (lineNumber < 1 || lineNumber > view.state.doc.lines) return [];
  const line = view.state.doc.line(lineNumber);
  const replacements = fullWidthSyntaxReplacements(line.text);
  if (!replacements.length) return [];
  return [{
    name: "替换这一行字符串与注释之外的全角语法符号",
    apply: (currentView: EditorView) => {
      const currentLine = currentView.state.doc.line(Math.min(lineNumber, currentView.state.doc.lines));
      const currentReplacements = fullWidthSyntaxReplacements(currentLine.text);
      const changes = currentReplacements.map((item) => ({
        from: currentLine.from + item.from,
        to: currentLine.from + item.to,
        insert: item.insert,
      }));
      currentView.dispatch({ changes });
    },
  }];
}

function createKirinLanguage(contract: AuthoringContract) {
  const declarationKeywords = new Set(contract.tokens.top_level_declarations);
  const nestedSections = new Set(contract.tokens.nested_sections);
  const syntaxKeywords = new Set(contract.tokens.keywords);
  const typeKeywords = new Set(contract.tokens.types);
  const literalKeywords = new Set(contract.tokens.literals);
  const directivePattern = new RegExp(`^@(?:${contract.tokens.directives.map(escapedOperator).join("|")})\\b`);
  const compoundKeywordPattern = new RegExp(`^(?:${contract.tokens.compound_keywords.map(escapedOperator).join("|")})\\b`);
  const proseFencePattern = new RegExp(contract.prose_fence_pattern);
  const operatorPattern = new RegExp(`^(?:${[...contract.tokens.operators]
    .sort((left, right) => right.length - left.length)
    .map(escapedOperator)
    .join("|")})`);
  return StreamLanguage.define<KirinParserState>({
  languageData: {
    commentTokens: { line: contract.line_comment },
    closeBrackets: { brackets: contract.close_brackets },
  },
  startState: () => ({ section: null, proseFence: null }),
  token(stream, state) {
    if (stream.sol()) {
      const fence = stream.match(proseFencePattern);
      if (fence && typeof fence !== "boolean") {
        if (state.proseFence === null) {
          state.proseFence = fence[0];
          return "meta";
        }
        if (state.proseFence === fence[0]) {
          state.proseFence = null;
          return "meta";
        }
        return "comment";
      }
    }
    if (state.proseFence !== null) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.eatSpace()) return null;
    if (stream.match(contract.line_comment)) {
      stream.skipToEnd();
      return "comment";
    }
    if (stream.peek() === '"') {
      stream.next();
      let escaped = false;
      while (!stream.eol()) {
        const character = stream.next();
        if (character === '"' && !escaped) break;
        escaped = character === "\\" && !escaped;
        if (character !== "\\") escaped = false;
      }
      return "string";
    }
    if (stream.match(directivePattern)) return "keyword";
    const declaration = stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/, false);
    if (declaration && typeof declaration !== "boolean" && stream.indentation() === 0 && declarationKeywords.has(declaration[1])) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/);
      state.section = declaration[1];
      return "heading";
    }
    const section = stream.match(/^([A-Za-z_][A-Za-z0-9_]*):/, false);
    if (section && typeof section !== "boolean" && nestedSections.has(section[1])) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*):/);
      return "heading";
    }
    const literal = stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/, false);
    if (literal && typeof literal !== "boolean" && literalKeywords.has(literal[1])) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/);
      return "bool";
    }
    if (stream.match(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?/)) return "number";
    const word = stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/, false);
    if (
      word && typeof word !== "boolean" && word[1] === "probability"
      && state.section === "process" && stream.string.trimStart().startsWith("probability ")
    ) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/);
      return "keyword";
    }
    const collectionType = word && typeof word !== "boolean" && ["list", "map"].includes(word[1]);
    const followedByTypeArguments = word && typeof word !== "boolean"
      ? stream.string.slice(stream.pos + word[1].length).trimStart().startsWith("[")
      : false;
    if (word && typeof word !== "boolean" && typeKeywords.has(word[1]) && (!collectionType || followedByTypeArguments)) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/);
      return "typeName";
    }
    if (word && typeof word !== "boolean" && syntaxKeywords.has(word[1])) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*)\b/);
      return "keyword";
    }
    if (stream.match(compoundKeywordPattern)) return "keyword";
    const identifier = stream.match(identifierPattern, false);
    const followedByCall = identifier && typeof identifier !== "boolean"
      ? stream.string.slice(stream.pos + identifier[0].length).trimStart().startsWith("(")
      : false;
    if (identifier) {
      stream.match(identifierPattern);
      if (followedByCall) return "variableName.function";
      return state.section === "output" || state.section === "field" ? "variableName" : "propertyName";
    }
    if (stream.match(operatorPattern)) return "operator";
    stream.next();
    return null;
  },
  } satisfies StreamParser<KirinParserState>);
}

function kirinIndentation(contract: AuthoringContract) {
  const proseFencePattern = new RegExp(contract.prose_fence_pattern);
  return indentService.of((context, position) => {
    const current = context.state.doc.lineAt(position);
    const beforeCursor = current.text.slice(0, Math.max(0, position - current.from));
    let previous = /\S/.test(beforeCursor)
      ? current
      : current.number > 1
        ? context.state.doc.line(current.number - 1)
        : current;
    while (previous.number > 1 && !previous.text.trim()) previous = context.state.doc.line(previous.number - 1);
    const previousIndent = previous.text.length - previous.text.trimStart().length;
    const previousTrimmed = previous.text.trim();
    const currentTrimmed = current.text.trim();
    if (/^-{3,}$/.test(previousTrimmed) || /^-{3,}$/.test(currentTrimmed)) return 0;
    let proseFence: string | null = null;
    for (let number = 1; number < current.number; number += 1) {
      const line = context.state.doc.line(number);
      if (line.text.length !== line.text.trimStart().length) continue;
      const fence = line.text.match(proseFencePattern)?.[0];
      if (!fence) continue;
      if (proseFence === null) proseFence = fence;
      else if (proseFence === fence) proseFence = null;
    }
    if (proseFence !== null || previousTrimmed.startsWith(contract.line_comment)) {
      return previousIndent;
    }
    return previousIndent + (previousTrimmed.endsWith(":") ? contract.indent_width : 0);
  });
}

const kirinHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--kt-c-syn-keyword)", fontWeight: "var(--kt-t-w-medium)" },
  { tag: tags.heading, color: "var(--kt-c-syn-heading)", fontWeight: "var(--kt-t-w-medium)" },
  { tag: tags.string, color: "var(--kt-c-syn-string)" },
  { tag: tags.number, color: "var(--kt-c-syn-number)" },
  { tag: tags.bool, color: "var(--kt-c-syn-boolean)" },
  { tag: tags.typeName, color: "var(--kt-c-syn-type)" },
  { tag: tags.function(tags.variableName), color: "var(--kt-c-syn-heading)" },
  { tag: tags.variableName, color: "var(--kt-c-syn-variable)" },
  { tag: tags.propertyName, color: "var(--kt-c-syn-property)" },
  { tag: tags.operator, color: "var(--kt-c-syn-operator)" },
  { tag: tags.comment, color: "var(--kt-c-syn-comment)", fontStyle: "italic" },
  { tag: tags.meta, color: "var(--kt-c-syn-comment)", fontWeight: "var(--kt-t-w-medium)" },
]);

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    isolation: "isolate",
    color: "var(--kt-c-t-strong)",
    backgroundColor: "var(--kt-c-s-editor)",
    fontSize: "var(--kt-t-s-code)",
  },
  ".cm-content": {
    caretColor: "var(--kt-c-a-chart)",
    fontFamily: "var(--kt-t-f-mono)",
    lineHeight: "var(--kt-t-lh-editor)",
    padding: "var(--kt-sz-editor-content-top) var(--kt-sp-0) var(--kt-sp-8)",
  },
  ".cm-line": { padding: "var(--kt-sp-0) var(--kt-sz-editor-content-inline)" },
  ".cm-cursor, .cm-dropCursor": {
    borderLeft: "var(--kt-shp-border-emphasis) solid var(--kt-c-a-strong)",
    marginLeft: "calc(-1 * var(--kt-sp-hairline))",
  },
  ".cm-selectionBackground": { backgroundColor: "var(--kt-c-a-selection-muted) !important" },
  ".cm-selectionLayer": { zIndex: "var(--kt-z-selection) !important", pointerEvents: "none" },
  "&.cm-focused .cm-selectionBackground": { backgroundColor: "var(--kt-c-a-selection) !important" },
  ".cm-content ::selection": { backgroundColor: "var(--kt-c-a-selection) !important" },
  ".cm-activeLine": { backgroundColor: "var(--kt-c-s-floating)" },
  "&.cm-focused .cm-activeLine": {
    backgroundColor: "var(--kt-c-syn-active-line)",
    boxShadow: "var(--kt-sh-active)",
  },
  ".cm-gutters": {
    backgroundColor: "var(--kt-c-s-editor)",
    color: "var(--kt-c-syn-comment)",
    border: "0",
    borderRight: "var(--kt-shp-border) solid var(--kt-c-b-editor)",
    fontFamily: "var(--kt-t-f-mono)",
  },
  ".cm-activeLineGutter": { backgroundColor: "var(--kt-c-s-overlay)", color: "var(--kt-c-ch-text)" },
  ".cm-tooltip": {
    zIndex: "var(--kt-z-editor-tooltip)",
    maxWidth: "var(--kt-sz-420)",
    overflow: "hidden",
    border: "var(--kt-shp-border) solid var(--kt-c-b-floating)",
    borderRadius: "var(--kt-shp-radius)",
    backgroundColor: "var(--kt-c-s-floating)",
    color: "var(--kt-c-t-primary)",
    boxShadow: "var(--kt-sh-popover)",
    fontFamily: "var(--kt-t-f-sans)",
    overflowWrap: "anywhere",
  },
  ".cm-tooltip-autocomplete > ul > li": { padding: "var(--kt-sp-compact) var(--kt-sp-dense)" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "var(--kt-c-syn-selected-item)", color: "var(--kt-c-t-strong)" },
  ".cm-completionLabel": { fontFamily: "var(--kt-t-f-mono)" },
  ".cm-completionDetail": { color: "var(--kt-c-syn-operator)", fontStyle: "normal" },
  ".cm-diagnostic": { borderRadius: "var(--kt-shp-radius)" },
  ".cm-panels": {
    borderColor: "var(--kt-c-b-editor)",
    backgroundColor: "var(--kt-c-s-floating)",
    color: "var(--kt-c-t-strong)",
    fontFamily: "var(--kt-t-f-sans)",
  },
  ".cm-panel.cm-search": {
    display: "grid",
    gridTemplateColumns: "minmax(var(--kt-sz-150), var(--kt-sz-214)) max-content max-content max-content max-content max-content",
    alignItems: "center",
    gap: "var(--kt-sp-compact)",
    padding: "var(--kt-sp-2) calc(var(--kt-sz-control) + var(--kt-sp-2)) var(--kt-sp-2) var(--kt-sp-3)",
    borderBottom: "var(--kt-shp-border) solid var(--kt-c-b-editor)",
  },
  ".cm-panel.cm-search > br": { display: "none" },
  ".cm-panel.cm-search [name=search]": { gridColumn: "1", gridRow: "1" },
  ".cm-panel.cm-search [name=next]": { gridColumn: "2", gridRow: "1" },
  ".cm-panel.cm-search [name=prev]": { gridColumn: "3", gridRow: "1" },
  ".cm-panel.cm-search [name=select]": { gridColumn: "4", gridRow: "1" },
  ".cm-panel.cm-search input[name=replace]": { gridColumn: "1", gridRow: "2" },
  ".cm-panel.cm-search button[name=replace]": { gridColumn: "2", gridRow: "2" },
  ".cm-panel.cm-search [name=replaceAll]": { gridColumn: "3", gridRow: "2" },
  ".cm-panel.cm-search > label:nth-of-type(1)": { gridColumn: "4", gridRow: "2" },
  ".cm-panel.cm-search > label:nth-of-type(2)": { gridColumn: "5", gridRow: "2" },
  ".cm-panel.cm-search > label:nth-of-type(3)": { gridColumn: "6", gridRow: "2" },
  ".cm-panel.cm-search input, .cm-panel.cm-search button, .cm-panel.cm-search label": {
    margin: "var(--kt-sp-0) !important",
  },
  ".cm-panel.cm-search .cm-textfield": {
    width: "100%",
    minWidth: "var(--kt-sp-0)",
    height: "var(--kt-sz-control-compact)",
    padding: "var(--kt-sp-compact) var(--kt-sp-2)",
    border: "var(--kt-shp-border) solid var(--kt-c-b-default)",
    borderRadius: "var(--kt-shp-radius)",
    outline: "none",
    backgroundColor: "var(--kt-c-s-navigation)",
    color: "var(--kt-c-t-primary)",
    fontFamily: "var(--kt-t-f-mono)",
    fontSize: "var(--kt-t-s-body)",
  },
  ".cm-panel.cm-search .cm-textfield::placeholder": { color: "var(--kt-c-t-quiet)" },
  ".cm-panel.cm-search .cm-textfield:hover": { borderColor: "var(--kt-c-b-strong)" },
  ".cm-panel.cm-search .cm-textfield:focus": {
    borderColor: "var(--kt-c-a-base)",
    boxShadow: "var(--kt-sh-focus)",
  },
  ".cm-panel.cm-search .cm-button": {
    height: "var(--kt-sz-control-compact)",
    minHeight: "var(--kt-sz-control-compact)",
    padding: "var(--kt-sp-0) var(--kt-sp-dense)",
    border: "var(--kt-shp-border) solid var(--kt-c-b-strong)",
    borderRadius: "var(--kt-shp-radius)",
    backgroundColor: "var(--kt-c-s-raised)",
    backgroundImage: "none",
    color: "var(--kt-c-t-subtle)",
    fontFamily: "var(--kt-t-f-sans)",
    fontSize: "var(--kt-t-s-meta)",
    fontWeight: "var(--kt-t-w-semibold)",
    cursor: "pointer",
    transition: "border-color var(--kt-mo-d-fast) var(--kt-mo-e-standard), background-color var(--kt-mo-d-fast) var(--kt-mo-e-standard), color var(--kt-mo-d-fast) var(--kt-mo-e-standard)",
  },
  ".cm-panel.cm-search .cm-button:hover": {
    borderColor: "var(--kt-c-b-hover)",
    backgroundColor: "var(--kt-c-s-hover)",
    color: "var(--kt-c-t-primary)",
  },
  ".cm-panel.cm-search .cm-button:active": { backgroundColor: "var(--kt-c-s-selected)" },
  ".cm-panel.cm-search label": {
    display: "inline-flex",
    height: "var(--kt-sz-control-compact)",
    alignItems: "center",
    gap: "var(--kt-sp-1)",
    padding: "var(--kt-sp-0) var(--kt-sp-compact)",
    border: "var(--kt-shp-border) solid transparent",
    color: "var(--kt-c-t-muted)",
    fontSize: "var(--kt-t-s-meta)",
    cursor: "pointer",
    transition: "border-color var(--kt-mo-d-fast) var(--kt-mo-e-standard), background-color var(--kt-mo-d-fast) var(--kt-mo-e-standard), color var(--kt-mo-d-fast) var(--kt-mo-e-standard)",
  },
  ".cm-panel.cm-search label:hover": { backgroundColor: "var(--kt-c-s-hover)", color: "var(--kt-c-t-primary)" },
  ".cm-panel.cm-search label:has(input:checked)": {
    borderColor: "var(--kt-c-a-border)",
    backgroundColor: "var(--kt-c-a-surface)",
    color: "var(--kt-c-a-text)",
  },
  ".cm-panel.cm-search input[type=checkbox]": {
    appearance: "none",
    width: "var(--kt-sz-14)",
    height: "var(--kt-sz-14)",
    border: "var(--kt-shp-border) solid var(--kt-c-b-hover)",
    borderRadius: "var(--kt-shp-radius)",
    backgroundColor: "var(--kt-c-s-navigation)",
    cursor: "pointer",
  },
  ".cm-panel.cm-search input[type=checkbox]:checked": {
    borderColor: "var(--kt-c-a-base)",
    backgroundColor: "var(--kt-c-a-base)",
    boxShadow: "inset 0 0 0 var(--kt-sz-3) var(--kt-c-s-floating)",
  },
  ".cm-panel.cm-search .cm-button:focus-visible, .cm-panel.cm-search input[type=checkbox]:focus-visible, .cm-panel.cm-search [name=close]:focus-visible": {
    position: "relative",
    zIndex: "var(--kt-z-focus)",
    outline: "var(--kt-shp-border-emphasis) solid var(--kt-c-a-base)",
    outlineOffset: "var(--kt-shp-focus-offset)",
  },
  ".cm-panel.cm-search [name=close]": {
    top: "var(--kt-sp-2)",
    right: "var(--kt-sp-2)",
    width: "var(--kt-sz-control-compact)",
    height: "var(--kt-sz-control-compact)",
    padding: "var(--kt-sp-0)",
    border: "var(--kt-shp-border) solid transparent",
    borderRadius: "var(--kt-shp-radius)",
    backgroundColor: "transparent",
    color: "var(--kt-c-t-muted)",
    fontFamily: "var(--kt-t-f-sans)",
    fontSize: "var(--kt-t-s-label)",
    cursor: "pointer",
  },
  ".cm-panel.cm-search [name=close]:hover": {
    borderColor: "var(--kt-c-b-default)",
    backgroundColor: "var(--kt-c-s-hover)",
    color: "var(--kt-c-t-primary)",
  },
  ".cm-searchMatch": { backgroundColor: "var(--kt-c-syn-search)", outline: "var(--kt-shp-border) solid var(--kt-c-syn-search-border)" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "var(--kt-c-a-selection)" },
  "&.cm-focused": { outline: "none" },
  "&.cm-focused::after": {
    content: "''",
    position: "absolute",
    inset: "var(--kt-sp-0)",
    zIndex: "var(--kt-z-editor-focus)",
    boxSizing: "border-box",
    border: "var(--kt-shp-border-emphasis) solid var(--kt-c-a-base)",
    pointerEvents: "none",
  },
});

function editorTooltipSpace(view: EditorView) {
  const bounds = view.dom.getBoundingClientRect();
  const inset = Number.parseFloat(getComputedStyle(view.dom).getPropertyValue("--kt-sp-2")) || 0;
  return {
    top: bounds.top + inset,
    right: bounds.right - inset,
    bottom: bounds.bottom - inset,
    left: bounds.left + inset,
  };
}

export interface CodeEditorHandle {
  focusAt(line?: number, column?: number): void;
}

interface CodeEditorProps {
  documentKey: string;
  value: string;
  ariaLabel: string;
  readOnly?: boolean;
  diagnostics?: DiagnosticItem[];
  authoring: AuthoringIndex;
  authoringContract: AuthoringContract;
  onChange(value: string): void;
  onComplete(request: CompletionRequest, signal?: AbortSignal): Promise<CompletionItem[]>;
  onSave(): void;
  onNavigate(location: AuthoringLocation): void;
  onShowReferences(target: AuthoringTarget): void;
  onRename(target: AuthoringTarget): void;
  onCursorContext(context: EditorCursorContext): void;
  onFormat(): void;
  onOpenOutline(): void;
}

export const CodeEditor = forwardRef<CodeEditorHandle, CodeEditorProps>(function CodeEditor(
  {
    documentKey,
    value,
    ariaLabel,
    readOnly = false,
    diagnostics = [],
    authoring,
    authoringContract,
    onChange,
    onComplete,
    onSave,
    onNavigate,
    onShowReferences,
    onRename,
    onCursorContext,
    onFormat,
    onOpenOutline,
  },
  forwardedRef,
) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const changeRef = useRef(onChange);
  const completionRef = useRef(onComplete);
  const saveRef = useRef(onSave);
  const authoringRef = useRef(authoring);
  const navigateRef = useRef(onNavigate);
  const referencesRef = useRef(onShowReferences);
  const renameRef = useRef(onRename);
  const cursorContextRef = useRef(onCursorContext);
  const formatRef = useRef(onFormat);
  const outlineRef = useRef(onOpenOutline);

  changeRef.current = onChange;
  completionRef.current = onComplete;
  saveRef.current = onSave;
  authoringRef.current = authoring;
  navigateRef.current = onNavigate;
  referencesRef.current = onShowReferences;
  renameRef.current = onRename;
  cursorContextRef.current = onCursorContext;
  formatRef.current = onFormat;
  outlineRef.current = onOpenOutline;

  useEffect(() => {
    if (!hostRef.current) return;

    async function complete(context: CompletionContext) {
      const word = context.matchBefore(/[\w.\-\u0080-\uFFFF]*/u);
      if (!word || (!context.explicit && word.from === word.to)) return null;
      const completionFrom = word.from > 0 && context.state.sliceDoc(word.from - 1, word.from) === "@"
        ? word.from - 1
        : word.from;
      const cursorLine = context.state.doc.lineAt(context.pos);
      const abort = new AbortController();
      context.addEventListener("abort", () => abort.abort());
      const request: CompletionRequest = {
        prefix: word.text,
        line: cursorLine.number,
        column: codePointColumn(cursorLine.text, context.pos - cursorLine.from),
        explicit: context.explicit,
      };
      let items: CompletionItem[];
      try {
        items = await completionRef.current(request, abort.signal);
      } catch (error) {
        if (abort.signal.aborted) return null;
        throw error;
      }
      const line = context.state.doc.lineAt(completionFrom);
      const indent = line.text.match(/^\s*/)?.[0] ?? "";
      return {
        from: completionFrom,
        filter: false,
        options: items.map((item): Completion => {
          const insertion = prepareCompletionInsertion(item.insert_text, indent);
          const topic = item.reference_topic ?? syntaxTopicForLine(item.insert_text) ?? syntaxTopicForKind(authoringContract, item.kind);
          return {
            label: item.label,
            detail: item.detail,
            type: item.kind || "variable",
            apply: (view, _completion, from, to) => {
              view.dispatch({
                changes: { from, to, insert: insertion.text },
                selection: { anchor: from + insertion.cursor },
              });
            },
            info: topic ? () => {
              const dom = document.createElement("div");
              dom.className = "kirin-completion-info";
              const detail = document.createElement("span");
              detail.textContent = item.detail || "Kirin Tor 写作项";
              const signature = item.signature ? document.createElement("code") : null;
              if (signature) signature.textContent = item.signature ?? "";
              const help = document.createElement("button");
              help.type = "button";
              help.textContent = "查看相关语法";
              help.addEventListener("mousedown", (event) => event.preventDefault());
              help.addEventListener("click", () => openSyntaxReference(topic, item.reference_symbol ?? undefined));
              dom.append(detail);
              if (signature) dom.append(signature);
              dom.append(help);
              return dom;
            } : undefined,
          };
        }),
      };
    }

    const currentTarget = (view: EditorView) => {
      const selection = view.state.selection.main;
      const positions = [selection.head, selection.from, Math.max(0, selection.head - 1)];
      for (const position of positions) {
        const target = targetAtPosition(view.state, authoringRef.current, documentKey, position);
        if (target) return target;
      }
      return null;
    };
    const goToDefinition = (view: EditorView) => {
      const target = currentTarget(view);
      if (!target?.definition) return false;
      navigateRef.current(target.definition);
      return true;
    };
    const showReferences = (view: EditorView) => {
      const target = currentTarget(view);
      if (!target || target.builtin) return false;
      referencesRef.current(target);
      return true;
    };
    const renameTarget = (view: EditorView) => {
      const target = currentTarget(view);
      if (!target?.symbol?.renameable) return false;
      renameRef.current(target);
      return true;
    };
    const reportCursor = (view: EditorView) => {
      const selection = view.state.selection.main;
      const position = selection.head;
      const line = view.state.doc.lineAt(position);
      const target = targetAtPosition(view.state, authoringRef.current, documentKey, position);
      const container = authoringRef.current.symbols.find((item) => (
        item.definition.key === documentKey
        && item.definition.line === line.number
        && item.outline_level === 2
        && item.kind !== "alias"
      ));
      const call = callContext(view.state, authoringRef.current, documentKey, position);
      const selected = selectionMetrics(view.state);
      cursorContextRef.current({
        symbolId: target?.id ?? null,
        containerSymbolId: container?.id ?? null,
        callSymbolId: call.symbolId,
        activeParameter: call.activeParameter,
        line: line.number,
        column: codePointColumn(line.text, position - line.from),
        selectionCharacters: selected.characters,
        selectionLines: selected.lines,
        selectionRanges: selected.ranges,
      });
    };

    const config = {
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        foldGutter(),
        lintGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        dropCursor(),
        EditorState.allowMultipleSelections.of(true),
        EditorState.phrases.of(kirinEditorPhrases),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        closeBrackets(),
        bracketMatching(),
        foldService.of(kirinFoldRange),
        tooltips({ tooltipSpace: editorTooltipSpace }),
        search({ top: true }),
        createKirinLanguage(authoringContract),
        kirinIndentation(authoringContract),
        indentUnit.of(" ".repeat(authoringContract.indent_width)),
        syntaxHighlighting(kirinHighlight),
        autocompletion({ override: [complete], activateOnTyping: true }),
        hoverTooltip((view, position) => {
          const target = targetAtPosition(view.state, authoringRef.current, documentKey, position);
          if (!target) return null;
          const location = target.reference?.location ?? target.symbol?.definition;
          const range = location ? locationRange(view.state, location) : null;
          const item = target.symbol ?? target.builtin;
          if (!item) return null;
          return {
            pos: range?.from ?? position,
            end: range?.to,
            above: true,
            create: () => {
              const dom = document.createElement("div");
              dom.className = "kirin-hover-card";
              const title = document.createElement("strong");
              title.textContent = item.label;
              const detail = document.createElement("small");
              detail.textContent = item.detail;
              dom.append(title, detail);
              if (item.signature) {
                const signature = document.createElement("code");
                signature.textContent = item.signature;
                dom.append(signature);
              }
              if (target.definition) {
                const action = document.createElement("button");
                action.type = "button";
                action.textContent = "转到定义 · F12";
                action.addEventListener("mousedown", (event) => event.preventDefault());
                action.addEventListener("click", () => navigateRef.current(target.definition!));
                dom.append(action);
              }
              const topic = ("reference_topic" in item ? item.reference_topic : null) ?? syntaxTopicForKind(authoringContract, item.kind);
              if (topic) {
                const help = document.createElement("button");
                help.type = "button";
                help.textContent = "查看相关语法";
                help.addEventListener("mousedown", (event) => event.preventDefault());
                const referenceSymbol = ("reference_symbol" in item ? item.reference_symbol : null) ?? syntaxSymbolForKind(authoringContract, item.kind);
                help.addEventListener("click", () => openSyntaxReference(topic, referenceSymbol ?? undefined));
                dom.append(help);
              }
              return { dom };
            },
          };
        }),
        EditorView.domEventHandlers({
          mousedown(event, view) {
            if (!(event.metaKey || event.ctrlKey) || event.button !== 0) return false;
            const position = view.posAtCoords({ x: event.clientX, y: event.clientY });
            if (position === null) return false;
            const target = targetAtPosition(view.state, authoringRef.current, documentKey, position);
            if (!target?.definition) return false;
            event.preventDefault();
            navigateRef.current(target.definition);
            return true;
          },
        }),
        keymap.of([
          { key: "Mod-s", run: () => { saveRef.current(); return true; } },
          { key: "Mod-g", run: gotoLine },
          { key: "Mod-Shift-o", run: () => { outlineRef.current(); return true; } },
          { key: "Mod-Shift-f", run: () => { formatRef.current(); return true; } },
          { key: "F12", run: goToDefinition },
          { key: "Shift-F12", run: showReferences },
          { key: "F2", run: renameTarget },
          indentWithTab,
          ...searchKeymap,
          ...foldKeymap,
          ...lintKeymap,
          ...closeBracketsKeymap,
          ...completionKeymap,
          ...historyKeymap,
          ...defaultKeymap,
        ]),
        EditorState.readOnly.of(readOnly),
        EditorView.contentAttributes.of({
          "aria-label": ariaLabel,
          "aria-description": "Kirin Tor 源码编辑器。Control 加空格补全；F12 转到定义；Shift F12 查看引用；F2 重命名。",
        }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) changeRef.current(update.state.doc.toString());
          if (update.docChanged || update.selectionSet) reportCursor(update.view);
        }),
        editorTheme,
      ],
    };
    let state = EditorState.create(config);
    const saved = editorSessions.get(documentKey);
    if (saved) {
      try {
        const restored = EditorState.fromJSON(saved, config, { history: historyField });
        if (restored.doc.toString() === value) state = restored;
      } catch {
        editorSessions.delete(documentKey);
      }
    }
    const view = new EditorView({ state, parent: hostRef.current });
    view.scrollDOM.tabIndex = 0;
    view.scrollDOM.setAttribute("aria-label", "源码滚动区域");
    viewRef.current = view;
    reportCursor(view);
    return () => {
      editorSessions.set(documentKey, view.state.toJSON({ history: historyField }));
      view.destroy();
      viewRef.current = null;
    };
  }, [ariaLabel, authoringContract, documentKey, readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || view.state.doc.toString() === value) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: value },
      annotations: Transaction.addToHistory.of(false),
    });
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const position = view.state.selection.main.head;
    const line = view.state.doc.lineAt(position);
    const target = targetAtPosition(view.state, authoring, documentKey, position);
    const container = authoring.symbols.find((item) => item.definition.key === documentKey && item.definition.line === line.number && item.outline_level === 2);
    const call = callContext(view.state, authoring, documentKey, position);
    const selected = selectionMetrics(view.state);
    cursorContextRef.current({
      symbolId: target?.id ?? null,
      containerSymbolId: container?.id ?? null,
      callSymbolId: call.symbolId,
      activeParameter: call.activeParameter,
      line: line.number,
      column: codePointColumn(line.text, position - line.from),
      selectionCharacters: selected.characters,
      selectionLines: selected.lines,
      selectionRanges: selected.ranges,
    });
  }, [authoring, documentKey]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const mapped: Diagnostic[] = diagnostics.map((item) => {
      const requestedLine = Math.max(1, item.location?.line ?? 1);
      const line = view.state.doc.line(Math.min(requestedLine, view.state.doc.lines));
      const range = diagnosticTokenRange(view.state, requestedLine, item.location?.column ?? 1);
      const topic = syntaxTopicForDiagnostic(item, line.text);
      return {
        from: range.from,
        to: range.to,
        severity: "error",
        message: item.author_message || item.message || "文档校验失败",
        source: item.code || "Kirin Tor",
        actions: [
          ...quickFixes(view, requestedLine),
          { name: "查看相关语法", apply: () => openSyntaxReference(topic, syntaxSymbolForDiagnostic(item, line.text) ?? undefined) },
        ],
      };
    });
    view.dispatch(setDiagnostics(view.state, mapped));
  }, [diagnostics, value]);

  useImperativeHandle(forwardedRef, () => ({
    focusAt(line = 1, column = 1) {
      const view = viewRef.current;
      if (!view) return;
      const targetLine = view.state.doc.line(Math.min(Math.max(line, 1), view.state.doc.lines));
      const offset = Math.min(targetLine.to, targetLine.from + utf16OffsetForColumn(targetLine.text, column));
      view.dispatch({
        selection: { anchor: offset },
        effects: EditorView.scrollIntoView(offset, { y: "center" }),
      });
      view.focus();
    },
  }), []);

  return <div className="code-editor" ref={hostRef} />;
});
