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
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

import { authoringTargetAt, codePointColumn, utf16OffsetForColumn, type AuthoringTarget } from "../authoring";
import type { AuthoringIndex, AuthoringLocation, CompletionItem, DiagnosticItem } from "../types";
import { openSyntaxReference, syntaxTopicForDiagnostic, syntaxTopicForKind, syntaxTopicForLine } from "../syntaxHelp";

interface KirinParserState {
  section: string | null;
}

const editorSessions = new Map<string, unknown>();
const punctuationReplacements: Record<string, string> = {
  "：": ":",
  "，": ",",
  "（": "(",
  "）": ")",
  "＝": "=",
  "％": "%",
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

const topLevelSections = new Set([
  "aliases",
  "dimensions",
  "units",
  "domains",
  "inputs",
  "constraints",
  "fields",
  "functions",
  "tables",
  "distributions",
  "recurrences",
  "state_models",
  "outputs",
  "sources",
  "groups",
  "presets",
  "display",
  "y",
]);

const nestedSections = new Set(["states", "transitions", "rewards"]);

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

function targetAtPosition(state: EditorState, authoring: AuthoringIndex, documentKey: string, position: number): AuthoringTarget | null {
  const line = state.doc.lineAt(position);
  const column = codePointColumn(line.text, position - line.from);
  return authoringTargetAt(authoring, documentKey, line.number, column);
}

function callContext(state: EditorState, authoring: AuthoringIndex, documentKey: string, position: number) {
  const line = state.doc.lineAt(position);
  const before = line.text.slice(0, position - line.from);
  const match = before.match(/([A-Za-z_\u0080-\uFFFF][\w.\u0080-\uFFFF]*)\(([^()]*)$/u);
  if (!match || match.index === undefined) return { symbolId: null, activeParameter: null };
  const nameOffset = match.index;
  const column = codePointColumn(line.text, nameOffset);
  const target = authoringTargetAt(authoring, documentKey, line.number, column);
  return {
    symbolId: target?.id ?? null,
    activeParameter: match[2].split(",").length,
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
  const replacements = Array.from(line.text)
    .map((character, index) => ({ character, index, replacement: punctuationReplacements[character] }))
    .filter((item) => item.replacement);
  if (!replacements.length) return [];
  return [{
    name: "替换这一行的全角语法符号",
    apply: (currentView: EditorView) => {
      const currentLine = currentView.state.doc.line(Math.min(lineNumber, currentView.state.doc.lines));
      const currentReplacements = Array.from(currentLine.text)
        .map((character, index) => ({ character, index, replacement: punctuationReplacements[character] }))
        .filter((item) => item.replacement);
      const changes = currentReplacements.map((item) => ({
        from: currentLine.from + utf16OffsetForColumn(currentLine.text, item.index + 1),
        to: currentLine.from + utf16OffsetForColumn(currentLine.text, item.index + 2),
        insert: item.replacement,
      }));
      currentView.dispatch({ changes });
    },
  }];
}

const kirinLanguage = StreamLanguage.define<KirinParserState>({
  startState: () => ({ section: null }),
  token(stream, state) {
    if (stream.eatSpace()) return null;
    if (stream.match("//")) {
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
    if (stream.match(/^@(kirin|entry|game-version|status)\b/)) return "keyword";
    const section = stream.match(/^([A-Za-z_][A-Za-z0-9_]*):/, false);
    if (section && typeof section !== "boolean" && (topLevelSections.has(section[1]) || nestedSections.has(section[1]))) {
      stream.match(/^([A-Za-z_][A-Za-z0-9_]*):/);
      if (stream.indentation() === 0 && topLevelSections.has(section[1])) state.section = section[1];
      return "heading";
    }
    if (stream.match(/^(x|range|points|preset|title|x-label|y-label|export-svg|export-csv)\s*:/)) return "heading";
    if (stream.match(/^(true|false)\b/)) return "bool";
    if (stream.match(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?/)) return "number";
    if (stream.match(/^(number|probability|boolean|integer|dimensionless|nonnegative_integer|positive_integer|count|time|second|millisecond)\b/)) return "typeName";
    if (stream.match(/^(in|if|else|and|or|not|one-of|as)\b/)) return "keyword";
    if (stream.match(/^[A-Za-z_\u0080-\uFFFF][\w\u0080-\uFFFF]*(?:\.[A-Za-z_\u0080-\uFFFF][\w\u0080-\uFFFF]*)*/u)) {
      return state.section === "outputs" || state.section === "fields" ? "variableName" : "propertyName";
    }
    if (stream.match(/^(?:->|==|!=|<=|>=|\+|-|\*|\/|\^|=|@|:|\.\.)/)) return "operator";
    stream.next();
    return null;
  },
} satisfies StreamParser<KirinParserState>);

const kirinHighlight = HighlightStyle.define([
  { tag: tags.keyword, color: "#d97757", fontWeight: "600" },
  { tag: tags.heading, color: "#e8b86d", fontWeight: "600" },
  { tag: tags.string, color: "#b7c98b" },
  { tag: tags.number, color: "#8fb9d4" },
  { tag: tags.bool, color: "#c5a0d8" },
  { tag: tags.typeName, color: "#a9a3d5" },
  { tag: tags.variableName, color: "#e5e1d8" },
  { tag: tags.propertyName, color: "#c9c4b9" },
  { tag: tags.operator, color: "#8f8b82" },
  { tag: tags.comment, color: "#8b9188", fontStyle: "italic" },
]);

const editorTheme = EditorView.theme({
  "&": {
    height: "100%",
    color: "#eeeae1",
    backgroundColor: "#11110f",
    fontSize: "13px",
  },
  ".cm-content": {
    caretColor: "#d97757",
    fontFamily: "var(--mantine-font-family-monospace)",
    lineHeight: "1.72",
    padding: "18px 0 64px",
  },
  ".cm-line": { padding: "0 22px" },
  ".cm-cursor, .cm-dropCursor": {
    borderLeft: "2px solid #f08b66",
    marginLeft: "-1px",
  },
  ".cm-selectionBackground": { backgroundColor: "#3f352f !important" },
  "&.cm-focused .cm-selectionBackground": { backgroundColor: "#704536 !important" },
  ".cm-content ::selection": { backgroundColor: "#704536 !important" },
  ".cm-activeLine": { backgroundColor: "#171714" },
  "&.cm-focused .cm-activeLine": {
    backgroundColor: "#1b1916",
    boxShadow: "inset 2px 0 #8f543f",
  },
  ".cm-gutters": {
    backgroundColor: "#11110f",
    color: "#8b9188",
    border: "0",
    borderRight: "1px solid #262521",
    fontFamily: "var(--mantine-font-family-monospace)",
  },
  ".cm-activeLineGutter": { backgroundColor: "#1b1a17", color: "#9c998f" },
  ".cm-tooltip": {
    border: "1px solid #3a3832",
    borderRadius: "0",
    backgroundColor: "#1a1916",
    boxShadow: "0 14px 36px rgba(0, 0, 0, .35)",
  },
  ".cm-tooltip-autocomplete > ul > li": { padding: "6px 10px" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "#3a2923", color: "#f5f1e9" },
  ".cm-completionLabel": { fontFamily: "var(--mantine-font-family-monospace)" },
  ".cm-completionDetail": { color: "#8f8b82", fontStyle: "normal" },
  ".cm-diagnostic": { borderRadius: "0" },
  ".cm-panels": { backgroundColor: "#171714", color: "#eeeae1" },
  ".cm-searchMatch": { backgroundColor: "#4b4025", outline: "1px solid #8d7441" },
  "&.cm-focused": { outline: "2px solid #cf7455", outlineOffset: "-2px" },
});

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
  onChange(value: string): void;
  onComplete(prefix: string): Promise<CompletionItem[]>;
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
      const word = context.matchBefore(/[\w.\u0080-\uFFFF]*/u);
      if (!word || (!context.explicit && word.from === word.to)) return null;
      const items = await completionRef.current(word.text);
      const line = context.state.doc.lineAt(word.from);
      const indent = line.text.match(/^\s*/)?.[0] ?? "";
      return {
        from: word.from,
        filter: false,
        options: items.map((item): Completion => {
          const insertion = prepareCompletionInsertion(item.insert_text, indent);
          const topic = syntaxTopicForKind(item.kind) ?? syntaxTopicForLine(item.insert_text);
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
              detail.textContent = item.detail || "Kirin 写作项";
              const help = document.createElement("button");
              help.type = "button";
              help.textContent = "查看相关语法";
              help.addEventListener("mousedown", (event) => event.preventDefault());
              help.addEventListener("click", () => openSyntaxReference(topic));
              dom.append(detail, help);
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
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        closeBrackets(),
        bracketMatching(),
        foldService.of(kirinFoldRange),
        search({ top: true }),
        kirinLanguage,
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
              const topic = syntaxTopicForKind(item.kind);
              if (topic) {
                const help = document.createElement("button");
                help.type = "button";
                help.textContent = "查看相关语法";
                help.addEventListener("mousedown", (event) => event.preventDefault());
                help.addEventListener("click", () => openSyntaxReference(topic));
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
          "aria-description": "Kirin 源码编辑器。Control 加空格补全；F12 转到定义；Shift F12 查看引用；F2 重命名。",
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
  }, [ariaLabel, documentKey, readOnly]);

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
      const from = Math.min(line.to, line.from + utf16OffsetForColumn(line.text, item.location?.column ?? 1));
      const topic = syntaxTopicForDiagnostic(item, line.text);
      return {
        from,
        to: Math.min(view.state.doc.length, Math.max(from + 1, line.to)),
        severity: "error",
        message: item.author_message || item.message || "文档校验失败",
        source: item.code || "Kirin",
        actions: [
          ...quickFixes(view, requestedLine),
          { name: "查看相关语法", apply: () => openSyntaxReference(topic) },
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
