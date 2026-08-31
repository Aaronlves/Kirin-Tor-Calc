"""Textual authoring workbench for Kirin source documents."""

from __future__ import annotations

import math
import os
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Footer, OptionList, Select, Static, TextArea
from textual.widgets.option_list import Option

from .authoring import (
    CompletionCandidate,
    build_completion_candidates,
    completion_prefix,
    highlight_kirin_source,
    prepare_completion_insertion,
)
from .diagnostics import extract_author_title, format_tui_diagnostic
from .engine import Engine
from .errors import KTError, ParameterError, WorkspaceError
from .operations import scan_values
from .plotting import render_plot, write_scan_csv
from .schema import PlotConfig
from .workspace import Workspace


_PLOT_LOCK = threading.Lock()


class KirinTextArea(TextArea):
    """TextArea with lightweight Kirin highlighting independent of tree-sitter."""

    def _build_highlight_map(self) -> None:
        if hasattr(self, "_line_cache"):
            self._line_cache.clear()
        self._highlights.clear()
        for row, highlights in highlight_kirin_source(self.text).items():
            self._highlights[row].extend(highlights)


def _source_template(path: Path) -> str:
    document_id = path.stem
    parent = path.parent.name
    if parent == "scenarios":
        return f"""@kirin 1
@scenario {document_id}

// {document_id}

values:
"""
    if parent == "plots":
        return f"""@kirin 1
@plot {document_id}

// {document_id}

x: entry.input
range: 0..1
points: 101

y:
  entry.output
"""
    return f"""@kirin 1
@entry {document_id}
@template model

// {document_id}

inputs:
  x: number[dimensionless] = 0

outputs:
  result: dimensionless = x
"""


def resolve_source_path(root: Path, requested: Optional[Path]) -> Path:
    """Resolve a TUI source path without allowing it to leave the workspace."""
    root = root.resolve()
    if requested is None:
        candidates = []
        for folder in ("entries", "scenarios", "plots"):
            candidates.extend((root / folder).rglob("*.kirin"))
        if candidates:
            return sorted(path.resolve() for path in candidates)[0]
        return (root / "entries" / "workbench.kirin").resolve()
    path = requested if requested.is_absolute() else root / requested
    path = path.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError(f"TUI source must stay inside the workspace: {path}") from exc
    if path.suffix.lower() != ".kirin" or not relative.parts or relative.parts[0] not in {
        "entries", "scenarios", "plots"
    }:
        raise WorkspaceError("TUI source must be a .kirin file inside entries, scenarios, or plots")
    return path


def _atomic_write_many(buffers: Dict[Path, str]) -> None:
    """Validate first, then stage every buffer before replacing any source."""
    staged: Dict[Path, Path] = {}
    try:
        for path, text in buffers.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            staged[path] = temporary
        for path, temporary in staged.items():
            os.replace(temporary, path)
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def _artifact_path(root: Path, value: str) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ParameterError(f"export path leaves the workspace: {resolved}") from exc
    return resolved


def _scan_plot(workspace: Workspace, config: PlotConfig) -> dict:
    return scan_values(
        Engine(workspace),
        config.x,
        f"{config.range_start}:{config.range_end}",
        config.points,
        config.y,
        config.scenario,
    )


def render_terminal_plot(scan: dict, config: PlotConfig, width: int, height: int) -> Text:
    """Render scan data as a Plotext terminal figure without an intermediate file."""
    import plotext

    width = max(30, min(width, 120))
    height = max(10, min(height, 40))
    with _PLOT_LOCK:
        figure = plotext.figure
        figure.clear()
        figure.plot_size(width, height)
        figure.theme("dark")
        if config.title:
            figure.title(config.title)
        axis_name = scan.get("x_display_label") or scan["x"]
        figure.label(config.x_label or f"{axis_name} [{scan['x_unit']}]", axis="x")
        if config.y_label:
            figure.label(config.y_label, axis="y")
        elif len(scan["targets"]) == 1:
            target = scan["targets"][0]
            label = config.curve_labels.get(target, scan.get("labels", {}).get(target, target))
            figure.label(f"{label} [{scan['units'][target]}]", axis="y")

        plotted = False
        for target in scan["targets"]:
            label = config.curve_labels.get(target, scan.get("labels", {}).get(target, target))
            segment_x = []
            segment_y = []
            labelled = False

            def flush() -> None:
                nonlocal plotted, labelled, segment_x, segment_y
                if not segment_x:
                    return
                signal = figure.signal(segment_x, segment_y).lines()
                if not labelled:
                    signal.label(label)
                    labelled = True
                plotted = True
                segment_x = []
                segment_y = []

            for row in scan["rows"]:
                value = row["values"][target]
                if value["error"] is not None:
                    flush()
                    continue
                x_value = float(row["x_approximate"])
                y_value = float(value["approximate"])
                if not math.isfinite(x_value) or not math.isfinite(y_value):
                    flush()
                    continue
                segment_x.append(x_value)
                segment_y.append(y_value)
            flush()
        if not plotted:
            raise ParameterError("plot has no valid finite points to preview")
        return Text.from_ansi(str(figure.build()))


class KirinTUI(App[None]):
    """A single-editor Kirin authoring workbench."""

    TITLE = "Kirin Tor 作者工作台"
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #source-select {
        height: 3;
        width: 1fr;
    }

    #body {
        height: 1fr;
    }

    #editor {
        width: 3fr;
        border: solid $primary;
    }

    #side {
        width: 2fr;
    }

    #preview {
        height: 2fr;
        border: solid $secondary;
        padding: 0 1;
        overflow: auto;
    }

    #completions {
        display: none;
        height: 1fr;
        min-height: 6;
        border: solid $accent;
    }

    #diagnostics {
        height: 1fr;
        min-height: 5;
        border: solid $warning;
        padding: 0 1;
        overflow: auto;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    """
    BINDINGS = [
        Binding("ctrl+space", "complete", "补全"),
        Binding("ctrl+s", "save", "保存"),
        Binding("ctrl+r", "validate", "校验"),
        Binding("ctrl+e", "export", "导出图表"),
        Binding("ctrl+p", "select_document", "文档"),
        Binding("ctrl+q", "quit", "退出"),
        Binding("escape", "close_completion", show=False, priority=True),
    ]

    def __init__(self, root: Path, source_path: Path):
        super().__init__()
        self.root = root.resolve()
        self.source_path = source_path.resolve()
        initial_text = (
            self.source_path.read_text(encoding="utf-8")
            if self.source_path.exists()
            else _source_template(self.source_path)
        )
        self._buffers: Dict[Path, str] = {self.source_path: initial_text}
        self._saved_texts: Dict[Path, str] = {
            self.source_path: initial_text if self.source_path.exists() else ""
        }
        self._switching_document = False
        self._revision = 0
        self._validation_timer: Optional[Timer] = None
        self._completion_candidates: list[CompletionCandidate] = []
        self._completion_range: Optional[Tuple[Tuple[int, int], Tuple[int, int]]] = None

    def _source_options(self) -> list[tuple[Text, str]]:
        paths = set(self._buffers)
        for folder in ("entries", "scenarios", "plots"):
            paths.update(path.resolve() for path in (self.root / folder).rglob("*.kirin"))
        options = []
        for path in sorted(paths):
            relative = str(path.relative_to(self.root))
            source = self._buffers.get(path)
            if source is None:
                try:
                    source = path.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    source = ""
            title = extract_author_title(source, path.stem)
            options.append((Text.assemble(title, ("  ·  ", "dim"), (relative, "dim")), relative))
        return options

    def _saved_text(self, path: Optional[Path] = None) -> str:
        return self._saved_texts.get(path or self.source_path, "")

    def _dirty_count(self) -> int:
        return sum(text != self._saved_text(path) for path, text in self._buffers.items())

    def _all_source_texts(self) -> Dict[Path, str]:
        sources = dict(self._buffers)
        for folder in ("entries", "scenarios", "plots"):
            for path in (self.root / folder).rglob("*.kirin"):
                resolved = path.resolve()
                if resolved in sources:
                    continue
                try:
                    sources[resolved] = resolved.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    continue
        return sources

    def compose(self) -> ComposeResult:
        relative = str(self.source_path.relative_to(self.root))
        yield Select(self._source_options(), value=relative, allow_blank=False, id="source-select")
        with Horizontal(id="body"):
            yield KirinTextArea.code_editor(
                self._buffers[self.source_path], id="editor", soft_wrap=False
            )
            with Vertical(id="side"):
                yield Static("当前文档无需图表预览。", id="preview")
                yield OptionList(id="completions", markup=False)
                yield Static("等待校验…", id="diagnostics")
        yield Static("尚未校验", id="status")
        yield Footer()

    def on_mount(self) -> None:
        editor = self.query_one("#editor", TextArea)
        editor.indent_width = 2
        editor.focus()
        self._queue_validation(delay=0.05)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "editor":
            return
        self._revision += 1
        self._buffers[self.source_path] = event.text_area.text
        dirty = self._dirty_count()
        self.query_one("#status", Static).update(
            f"{dirty} 个草稿已修改 · 正在校验…" if dirty else "正在校验…"
        )
        self._queue_validation()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "source-select" or self._switching_document or not isinstance(event.value, str):
            return
        target = (self.root / event.value).resolve()
        if target == self.source_path:
            return
        self._close_completion()
        editor = self.query_one("#editor", TextArea)
        self._buffers[self.source_path] = editor.text
        if target not in self._buffers:
            text = target.read_text(encoding="utf-8") if target.exists() else _source_template(target)
            self._buffers[target] = text
            self._saved_texts[target] = text if target.exists() else ""
        self.source_path = target
        self._revision += 1
        self._switching_document = True
        try:
            editor.load_text(self._buffers[target])
        finally:
            self._switching_document = False
        self.query_one("#status", Static).update("正在校验…")
        self._queue_validation(delay=0.05)

    def _queue_validation(self, delay: float = 0.4) -> None:
        if self._validation_timer is not None:
            self._validation_timer.stop()
        self._validation_timer = self.set_timer(delay, self._start_validation)

    def _start_validation(self) -> None:
        editor = self.query_one("#editor", TextArea)
        preview = self.query_one("#preview", Static)
        overlays = dict(self._buffers)
        overlays[self.source_path] = editor.text
        self._validate_worker(
            overlays,
            self.source_path,
            self._revision,
            max(preview.size.width - 2, 30),
            max(preview.size.height - 2, 10),
        )

    def _load_validated(
        self, overlays: Dict[Path, str], source_path: Path
    ) -> Tuple[Workspace, object]:
        source_path = source_path.resolve()
        workspace = Workspace.load_with_overlays(self.root, overlays)
        Engine(workspace).validate_all()
        document = next(
            (item for item in workspace.documents.values() if item.path.resolve() == source_path),
            None,
        )
        if document is None:
            raise WorkspaceError(f"editor document did not load from {source_path}")
        return workspace, document

    @work(thread=True, exclusive=True, group="validate")
    def _validate_worker(
        self,
        overlays: Dict[Path, str],
        source_path: Path,
        revision: int,
        width: int,
        height: int,
    ) -> None:
        try:
            workspace, document = self._load_validated(overlays, source_path)
            preview: Optional[Text] = None
            if isinstance(document, PlotConfig):
                preview = render_terminal_plot(_scan_plot(workspace, document), document, width, height)
            self.call_from_thread(self._apply_validation, revision, None, preview)
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 校验过程意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(self._apply_validation, revision, message, None)

    def _apply_validation(self, revision: int, error: Optional[str], preview: Optional[Text]) -> None:
        if revision != self._revision:
            return
        editor = self.query_one("#editor", TextArea)
        self._buffers[self.source_path] = editor.text
        dirty = self._dirty_count()
        if error:
            self.query_one("#diagnostics", Static).update(Text(error, style="red"))
            self.query_one("#status", Static).update(
                f"{dirty} 个草稿已修改 · 校验失败" if dirty else "校验失败"
            )
            self.query_one("#preview", Static).update("文档校验失败，暂时无法预览。")
            return
        self.query_one("#diagnostics", Static).update(Text("校验通过", style="green"))
        self.query_one("#status", Static).update(
            f"{dirty} 个草稿已修改 · 校验通过" if dirty else "已保存 · 校验通过"
        )
        self.query_one("#preview", Static).update(
            preview if preview is not None else "当前文档无需图表预览。"
        )

    def action_validate(self) -> None:
        self._revision += 1
        self.query_one("#status", Static).update("正在校验…")
        self._start_validation()

    def action_complete(self) -> None:
        editor = self.query_one("#editor", TextArea)
        row, column = editor.cursor_location
        line = editor.document[row]
        prefix, start_column = completion_prefix(line, column)
        sources = self._all_source_texts()
        sources[self.source_path] = editor.text
        candidates = build_completion_candidates(sources, self.source_path, prefix)
        if not candidates:
            self.query_one("#diagnostics", Static).update("没有匹配的补全候选。")
            self._close_completion()
            return
        self._completion_candidates = candidates
        self._completion_range = ((row, start_column), (row, column))
        option_list = self.query_one("#completions", OptionList)
        option_list.clear_options()
        option_list.add_options(
            [
                Option(
                    Text.assemble((candidate.label, "bold"), "  ", (candidate.detail, "dim")),
                    id=str(index),
                )
                for index, candidate in enumerate(candidates)
            ]
        )
        option_list.styles.display = "block"
        option_list.highlighted = 0
        option_list.focus()

    def _close_completion(self, *, focus_editor: bool = True) -> None:
        option_list = self.query_one_optional("#completions", OptionList)
        if option_list is not None:
            option_list.styles.display = "none"
            option_list.clear_options()
        self._completion_candidates = []
        self._completion_range = None
        if focus_editor:
            editor = self.query_one_optional("#editor", TextArea)
            if editor is not None:
                editor.focus()

    def action_close_completion(self) -> None:
        self._close_completion()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "completions" or self._completion_range is None:
            return
        if event.option_index < 0 or event.option_index >= len(self._completion_candidates):
            return
        candidate = self._completion_candidates[event.option_index]
        start, end = self._completion_range
        editor = self.query_one("#editor", TextArea)
        line = editor.document[start[0]]
        indent = line[: len(line) - len(line.lstrip(" "))]
        inserted, cursor_offset = prepare_completion_insertion(candidate.insert_text, indent)
        self._close_completion(focus_editor=False)
        editor.replace(inserted, start, end)
        before_cursor = inserted[:cursor_offset]
        if "\n" in before_cursor:
            cursor = (
                start[0] + before_cursor.count("\n"),
                len(before_cursor.rsplit("\n", 1)[1]),
            )
        else:
            cursor = (start[0], start[1] + len(before_cursor))
        editor.move_cursor(cursor)
        editor.focus()

    def action_save(self) -> None:
        text = self.query_one("#editor", TextArea).text
        source_path = self.source_path
        overlays = dict(self._buffers)
        overlays[source_path] = text
        dirty = {path: value for path, value in overlays.items() if value != self._saved_text(path)}
        revision = self._revision
        self.query_one("#status", Static).update("保存前正在校验整个工作区…")
        self._save_worker(overlays, dirty, source_path, revision)

    @work(thread=True, exclusive=True, group="write")
    def _save_worker(
        self,
        overlays: Dict[Path, str],
        dirty: Dict[Path, str],
        source_path: Path,
        revision: int,
    ) -> None:
        try:
            self._load_validated(overlays, source_path)
            _atomic_write_many(dirty)
            self.call_from_thread(self._apply_save, source_path, revision, dirty, None)
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 保存过程意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(self._apply_save, source_path, revision, dirty, message)

    def _apply_save(
        self,
        source_path: Path,
        revision: int,
        saved_buffers: Dict[Path, str],
        error: Optional[str],
    ) -> None:
        if error:
            self.query_one("#diagnostics", Static).update(Text(error, style="red"))
            self.query_one("#status", Static).update("保存被拒绝")
            return
        for path, saved_text in saved_buffers.items():
            self._saved_texts[path] = saved_text
        if (
            source_path == self.source_path
            and revision == self._revision
            and self.query_one("#editor", TextArea).text == self._buffers[source_path]
        ):
            self.query_one("#status", Static).update("已保存 · 校验通过")
        else:
            self.query_one("#status", Static).update("已保存较早版本 · 当前草稿仍有修改")
        self._queue_validation(delay=0.05)

    def action_export(self) -> None:
        text = self.query_one("#editor", TextArea).text
        source_path = self.source_path
        overlays = dict(self._buffers)
        overlays[source_path] = text
        dirty = {path: value for path, value in overlays.items() if value != self._saved_text(path)}
        revision = self._revision
        self.query_one("#status", Static).update("正在校验、保存并导出…")
        self._export_worker(overlays, dirty, source_path, revision)

    @work(thread=True, exclusive=True, group="write")
    def _export_worker(
        self,
        overlays: Dict[Path, str],
        dirty: Dict[Path, str],
        source_path: Path,
        revision: int,
    ) -> None:
        sources_saved = False
        exported: list[str] = []
        try:
            workspace, document = self._load_validated(overlays, source_path)
            if not isinstance(document, PlotConfig):
                raise ParameterError("only a plot document can be exported")
            if not document.out and not document.data_out:
                raise ParameterError("plot has no export-svg or export-csv path")
            _atomic_write_many(dirty)
            sources_saved = True
            scan = _scan_plot(workspace, document)
            if document.out:
                exported.append(
                    str(
                        render_plot(
                            scan,
                            _artifact_path(self.root, document.out),
                            overwrite=True,
                            title=document.title,
                            x_label=document.x_label,
                            y_label=document.y_label,
                            curve_labels=document.curve_labels,
                        )
                    )
                )
            if document.data_out:
                exported.append(
                    str(write_scan_csv(scan, _artifact_path(self.root, document.data_out), overwrite=True))
                )
            self.call_from_thread(
                self._apply_export, source_path, revision, dirty, True, None, exported
            )
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 导出过程意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(
                self._apply_export,
                source_path,
                revision,
                dirty,
                sources_saved,
                message,
                exported,
            )

    def _apply_export(
        self,
        source_path: Path,
        revision: int,
        saved_buffers: Dict[Path, str],
        sources_saved: bool,
        error: Optional[str],
        exported: list[str],
    ) -> None:
        if sources_saved:
            for path, saved_text in saved_buffers.items():
                self._saved_texts[path] = saved_text
        if error:
            details = error
            if exported:
                details += "\n失败前已完成：\n" + "\n".join(exported)
            self.query_one("#diagnostics", Static).update(Text(details, style="red"))
            self.query_one("#status", Static).update(
                "源文件已保存 · 导出失败" if sources_saved else "导出失败"
            )
            return
        if source_path != self.source_path or revision != self._revision:
            return
        message = "已导出：\n" + "\n".join(exported)
        self.query_one("#diagnostics", Static).update(Text(message, style="green"))
        self.query_one("#status", Static).update("已保存 · 已导出")

    def action_select_document(self) -> None:
        selector = self.query_one("#source-select", Select)
        self._switching_document = True
        try:
            selector.set_options(self._source_options())
            selector.value = str(self.source_path.relative_to(self.root))
        finally:
            self._switching_document = False
        selector.focus()
        selector.action_show_overlay()


def run_tui(root: Path, requested_source: Optional[Path] = None) -> None:
    source_path = resolve_source_path(root, requested_source)
    KirinTUI(root, source_path).run()
