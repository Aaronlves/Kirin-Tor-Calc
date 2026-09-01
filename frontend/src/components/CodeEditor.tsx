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
  type CompletionContext,
} from "@codemirror/autocomplete";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  HighlightStyle,
  StreamLanguage,
  syntaxHighlighting,
  type StreamParser,
} from "@codemirror/language";
import { type Diagnostic, setDiagnostics } from "@codemirror/lint";
import { EditorState } from "@codemirror/state";
import {
  crosshairCursor,
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

import type { CompletionItem, DiagnosticItem } from "../types";

interface KirinParserState {
  section: string | null;
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
    if (stream.match(/^@(kirin|entry)\b/)) return "keyword";
    if (stream.match(/^(inputs|fields|outputs|functions|when|sources|preset|x|range|points|y|export-svg|export-png|export-csv)\s*:/)) {
      state.section = stream.current().split(":", 1)[0];
      return "heading";
    }
    if (stream.match(/^(true|false)\b/)) return "bool";
    if (stream.match(/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%?/)) return "number";
    if (stream.match(/^(number|probability|boolean|integer)\b/)) return "typeName";
    if (stream.match(/^(in|if|else|and|or|not)\b/)) return "keyword";
    if (stream.match(/^[A-Za-z_\u0080-\uFFFF][\w\u0080-\uFFFF]*(?:\.[A-Za-z_\u0080-\uFFFF][\w\u0080-\uFFFF]*)*/u)) {
      return state.section === "outputs" || state.section === "fields" ? "variableName" : "propertyName";
    }
    if (stream.match(/^(?:==|!=|<=|>=|\+|-|\*|\/|\^|=|:|\.\.)/)) return "operator";
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
  { tag: tags.comment, color: "#68665f", fontStyle: "italic" },
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
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "#d97757" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": { backgroundColor: "#49352d" },
  ".cm-activeLine": { backgroundColor: "#171714" },
  ".cm-gutters": {
    backgroundColor: "#11110f",
    color: "#53514c",
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
  "&.cm-focused": { outline: "none" },
});

export interface CodeEditorHandle {
  focusAt(line?: number, column?: number): void;
}

interface CodeEditorProps {
  value: string;
  readOnly?: boolean;
  diagnostics?: DiagnosticItem[];
  onChange(value: string): void;
  onComplete(prefix: string): Promise<CompletionItem[]>;
  onSave(): void;
}

export const CodeEditor = forwardRef<CodeEditorHandle, CodeEditorProps>(function CodeEditor(
  { value, readOnly = false, diagnostics = [], onChange, onComplete, onSave },
  forwardedRef,
) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const changeRef = useRef(onChange);
  const completionRef = useRef(onComplete);
  const saveRef = useRef(onSave);

  changeRef.current = onChange;
  completionRef.current = onComplete;
  saveRef.current = onSave;

  useEffect(() => {
    if (!hostRef.current) return;

    async function complete(context: CompletionContext) {
      const word = context.matchBefore(/[\w.\u0080-\uFFFF]*/u);
      if (!word || (!context.explicit && word.from === word.to)) return null;
      const items = await completionRef.current(word.text);
      return {
        from: word.from,
        options: items.map((item) => ({
          label: item.label,
          detail: item.detail,
          type: item.kind || "variable",
          apply: item.insert_text.replace("$0", ""),
        })),
      };
    }

    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        dropCursor(),
        EditorState.allowMultipleSelections.of(true),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        closeBrackets(),
        kirinLanguage,
        syntaxHighlighting(kirinHighlight),
        autocompletion({ override: [complete], activateOnTyping: true }),
        keymap.of([
          { key: "Mod-s", run: () => { saveRef.current(); return true; } },
          indentWithTab,
          ...closeBracketsKeymap,
          ...completionKeymap,
          ...historyKeymap,
          ...defaultKeymap,
        ]),
        EditorState.readOnly.of(readOnly),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) changeRef.current(update.state.doc.toString());
        }),
        editorTheme,
      ],
    });
    const view = new EditorView({ state, parent: hostRef.current });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [readOnly]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || view.state.doc.toString() === value) return;
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const mapped: Diagnostic[] = diagnostics.map((item) => {
      const requestedLine = Math.max(1, item.location?.line ?? 1);
      const line = view.state.doc.line(Math.min(requestedLine, view.state.doc.lines));
      const from = Math.min(line.to, line.from + Math.max(0, (item.location?.column ?? 1) - 1));
      return {
        from,
        to: Math.min(view.state.doc.length, Math.max(from + 1, line.to)),
        severity: "error",
        message: item.author_message || item.message || "文档校验失败",
        source: item.code || "Kirin",
      };
    });
    view.dispatch(setDiagnostics(view.state, mapped));
  }, [diagnostics, value]);

  useImperativeHandle(forwardedRef, () => ({
    focusAt(line = 1, column = 1) {
      const view = viewRef.current;
      if (!view) return;
      const targetLine = view.state.doc.line(Math.min(Math.max(line, 1), view.state.doc.lines));
      const offset = Math.min(targetLine.to, targetLine.from + Math.max(column - 1, 0));
      view.dispatch({
        selection: { anchor: offset },
        effects: EditorView.scrollIntoView(offset, { y: "center" }),
      });
      view.focus();
    },
  }), []);

  return <div className="code-editor" ref={hostRef} />;
});
