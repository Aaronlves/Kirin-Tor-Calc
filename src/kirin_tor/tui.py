"""Textual authoring workbench for Kirin source documents."""

from __future__ import annotations

import math
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.theme import Theme
from textual.timer import Timer
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.widgets.option_list import Option

from .application import (
    ComparisonVariant,
    WorkspaceIndex,
    artifact_path,
    build_workspace_index,
    compare_variants,
    parse_player_override_text,
    save_comparison_run,
    scan_variant_comparison,
)
from .authoring import (
    CompletionCandidate,
    build_completion_candidates,
    completion_prefix,
    highlight_kirin_source,
    prepare_completion_insertion,
)
from .diagnostics import extract_author_title, format_tui_diagnostic
from .engine import Engine
from .errors import KTError, ParameterError, ValidationErrors, WorkspaceError
from .operations import explain, scan_values, solve_equation
from .plotting import render_plot, write_scan_csv
from .records import load_run, replay as replay_run
from .schema import PlotConfig
from .tui_components import NewDocumentScreen, UnsavedChangesScreen, VariantRow
from .workspace import DocumentDraft, Workspace, build_document_draft


_PLOT_LOCK = threading.Lock()

KIRIN_THEME = Theme(
    name="kirin-tor",
    primary="#8f63ff",
    secondary="#66dcff",
    accent="#e6bf68",
    foreground="#f2edff",
    background="#090612",
    surface="#100a20",
    panel="#17102d",
    success="#73e7c0",
    warning="#e6bf68",
    error="#ff6f91",
    dark=True,
    variables={
        "footer-key-foreground": "#e6bf68",
        "input-selection-background": "#8f63ff 38%",
        "block-cursor-background": "#66dcff",
        "block-cursor-foreground": "#090612",
    },
)


class KirinTextArea(TextArea):
    """TextArea with lightweight Kirin highlighting independent of tree-sitter."""

    def _build_highlight_map(self) -> None:
        if hasattr(self, "_line_cache"):
            self._line_cache.clear()
        self._highlights.clear()
        for row, highlights in highlight_kirin_source(self.text).items():
            self._highlights[row].extend(highlights)


def _source_template(path: Path) -> str:
    parent = path.parent.name
    if parent == "scenarios":
        kind = "scenario"
    elif parent == "plots":
        kind = "plot"
    else:
        kind = "model"
    return build_document_draft(path.parents[1], kind, path.stem).source_text


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
    return artifact_path(root, value)


def _scan_plot(workspace: Workspace, config: PlotConfig) -> dict:
    return scan_values(
        Engine(workspace),
        config.x,
        f"{config.range_start}:{config.range_end}",
        config.points,
        config.y,
        config.scenario,
    )


def render_terminal_plot(
    scan: dict,
    config: PlotConfig,
    width: int,
    height: int,
    row_limit: Optional[int] = None,
) -> Text:
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

            rows = scan["rows"] if row_limit is None else scan["rows"][:row_limit]
            for row in rows:
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


def build_terminal_plot_frames(
    scan: dict,
    config: PlotConfig,
    width: int,
    height: int,
    frame_count: int = 8,
) -> list[Text]:
    """Build cached reveal frames from one already computed scan."""
    points = len(scan.get("rows", []))
    if points < 3 or frame_count < 2:
        return []
    limits = sorted(
        {
            max(2, min(points, round(points * step / frame_count)))
            for step in range(1, frame_count + 1)
        }
    )
    return [render_terminal_plot(scan, config, width, height, limit) for limit in limits]


class KirinTUI(App[None]):
    """Player-facing calculation, comparison, chart, and document workbench."""

    TITLE = "Kirin Tor 游戏计算工具"
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }

    #brand {
        height: 3;
        padding: 0 2;
        content-align: left middle;
        color: $text-accent;
        background: $panel;
        border-bottom: solid $accent-darken-2;
        text-style: bold;
    }

    #main-content {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    .view-toolbar {
        height: auto;
        min-height: 3;
        padding: 0 1;
        background: $surface;
    }

    .view-toolbar Select,
    .view-toolbar Input {
        width: 1fr;
        min-width: 18;
    }

    .view-toolbar Button {
        width: auto;
    }

    #calculate-view,
    #charts-view,
    #documents-view,
    #diagnostics-view,
    #runs-view {
        height: 1fr;
        width: 1fr;
    }

    #calculation-source-state,
    #calculation-input-help,
    #calculation-details,
    #solve-result,
    #chart-status,
    #run-details {
        height: auto;
        min-height: 1;
        padding: 0 1;
        color: $text-muted;
    }

    #variant-list {
        height: auto;
        max-height: 24;
        padding: 0 1;
        border-bottom: solid $primary-darken-2;
    }

    #comparison-results {
        height: 1fr;
        min-height: 8;
    }

    #chart-body {
        height: 1fr;
    }

    #scan-preview {
        width: 3fr;
        height: 1fr;
        padding: 0 1;
        border: solid $secondary-darken-2;
        overflow: auto;
    }

    #scan-table {
        width: 2fr;
        height: 1fr;
    }

    #document-toolbar {
        height: 3;
        padding: 0 1;
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
        border: solid $primary-darken-1;
    }

    #side {
        width: 2fr;
    }

    #preview {
        height: 2fr;
        border: solid $secondary-darken-2;
        padding: 0 1;
        overflow: auto;
    }

    #completions {
        display: none;
        height: 1fr;
        min-height: 6;
        border: solid $accent-darken-1;
    }

    #diagnostics {
        height: 1fr;
        min-height: 5;
        border: solid $warning-darken-2;
        padding: 0 1;
        overflow: auto;
    }

    #status {
        height: 1;
        padding: 0 1;
        background: $panel;
    }

    #diagnostics-body {
        height: 1fr;
    }

    #diagnostic-list-pane,
    #explain-output {
        width: 1fr;
        height: 1fr;
        padding: 1;
        overflow: auto;
        border: solid $primary-darken-2;
    }

    #workspace-diagnostics {
        height: auto;
        min-height: 2;
        color: $text-muted;
    }

    #diagnostic-list {
        height: 1fr;
    }

    #runs-table {
        height: 1fr;
    }

    .section-heading {
        height: 2;
        padding: 0 1;
        color: $text-accent;
        text-style: bold;
    }

    Screen.narrow #chart-body,
    Screen.narrow #body,
    Screen.narrow #diagnostics-body {
        layout: vertical;
    }

    Screen.narrow #scan-preview,
    Screen.narrow #scan-table,
    Screen.narrow #editor,
    Screen.narrow #side,
    Screen.narrow #diagnostic-list-pane,
    Screen.narrow #explain-output {
        width: 1fr;
    }

    Screen.narrow #scan-preview,
    Screen.narrow #editor {
        height: 2fr;
    }

    Screen.narrow #scan-table,
    Screen.narrow #side {
        height: 1fr;
    }
    """
    BINDINGS = [
        Binding("ctrl+1", "show_calculate", "计算"),
        Binding("ctrl+2", "show_charts", "图表"),
        Binding("ctrl+3", "show_documents", "文档"),
        Binding("ctrl+4", "show_diagnostics", "诊断"),
        Binding("ctrl+5", "show_runs", "记录"),
        Binding("ctrl+n", "new_document", "新建"),
        Binding("ctrl+space", "complete", "补全", priority=True),
        Binding("ctrl+s", "save", "保存"),
        Binding("ctrl+r", "validate", "校验"),
        Binding("ctrl+e", "export", "导出图表"),
        Binding("ctrl+p", "select_document", "文档"),
        Binding("ctrl+w", "close_document", "关闭文档"),
        Binding("ctrl+q", "request_quit", "退出"),
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
        self._workspace_index: Optional[WorkspaceIndex] = None
        self._last_comparison: Optional[dict] = None
        self._last_comparison_variants: list[ComparisonVariant] = []
        self._last_scan: Optional[dict] = None
        self._variant_counter = 2
        self._exit_after_save = False
        self._close_after_save: Optional[Path] = None
        self._selected_run_id: Optional[str] = None
        self._diagnostic_errors: list[KTError] = []
        self._plot_animation_timer: Optional[Timer] = None
        self._plot_animation_frames: list[Text] = []
        self._plot_animation_index = 0
        configured_motion = os.environ.get("KIRIN_TOR_MOTION", "full").lower()
        if configured_motion in {"none", "0"}:
            configured_motion = "off"
        if configured_motion not in {"full", "reduced", "off"}:
            configured_motion = "full"
        if "PYTEST_CURRENT_TEST" in os.environ:
            configured_motion = "off"
        self.motion_mode = configured_motion
        self.motion_enabled = self.motion_mode != "off"

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
            if not path.exists():
                state = ("  新建", "bold #e6bf68")
            elif path in self._buffers and source != self._saved_text(path):
                state = ("  已修改", "bold #ffcf70")
            else:
                state = ("", "")
            options.append(
                (
                    Text.assemble(
                        title,
                        ("  ·  ", "dim"),
                        (relative, "dim"),
                        state,
                    ),
                    relative,
                )
            )
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
        yield Static(
            Text.assemble(
                ("◉", "bold #b99cff"),
                ("  KIRIN TOR", "bold #e6bf68"),
                ("  游戏计算工具", "#aaa0c6"),
            ),
            id="brand",
        )
        with TabbedContent(initial="calculate-pane", id="main-content"):
            with TabPane("计算", id="calculate-pane"):
                with Vertical(id="calculate-view"):
                    with Horizontal(classes="view-toolbar"):
                        yield Select(
                            [],
                            prompt="等待有效的输出定义",
                            allow_blank=True,
                            id="target-select",
                        )
                        yield Button("添加方案", id="add-variant")
                        yield Button("计算", id="calculate", variant="primary")
                    yield Static("正在读取工作区…", id="calculation-source-state")
                    yield Static("选择结果后会显示可调整的输入。", id="calculation-input-help")
                    with Horizontal(classes="view-toolbar"):
                        yield Select(
                            [],
                            prompt="要反求的输入",
                            allow_blank=True,
                            id="solve-variable",
                        )
                        yield Input(
                            placeholder="目标结果，例如 3000 damage",
                            id="solve-equals",
                            compact=True,
                        )
                        yield Input(
                            placeholder="输入范围，例如 0:1",
                            id="solve-range",
                            compact=True,
                        )
                        yield Button("按基准方案反求", id="solve-target")
                    yield Static("可按第一个方案反求达到目标结果所需的输入。", id="solve-result")
                    yield Label("比较方案", classes="section-heading")
                    with VerticalScroll(id="variant-list"):
                        yield VariantRow(1, "基准")
                        yield VariantRow(2, "方案 B")
                    yield DataTable(
                        id="comparison-results",
                        show_row_labels=False,
                        zebra_stripes=True,
                        cursor_type="row",
                    )
                    yield Static("选择输出并计算。", id="calculation-details")

            with TabPane("图表", id="charts-pane"):
                with Vertical(id="charts-view"):
                    with Horizontal(classes="view-toolbar"):
                        yield Select([], prompt="横轴输入", allow_blank=True, id="scan-x-select")
                        yield Input("0:1", placeholder="范围，例如 0:1", id="scan-range", compact=True)
                        yield Input("41", placeholder="点数", id="scan-points", compact=True)
                        yield Select(
                            [("默认参数", "__defaults__")],
                            value="__defaults__",
                            allow_blank=False,
                            id="scan-scenario",
                        )
                    with Horizontal(classes="view-toolbar"):
                        yield Select([], prompt="结果输出", allow_blank=True, id="scan-y-select")
                        yield Input(
                            placeholder="临时参数：entry.input=value",
                            id="scan-overrides",
                            compact=True,
                        )
                        yield Button("生成图表", id="run-scan", variant="primary")
                        yield Button("比较计算页方案", id="run-variant-scan")
                        yield Input(placeholder="保存为图表文档 ID", id="scan-plot-id", compact=True)
                        yield Button("创建图表文档", id="create-plot-draft")
                        yield Select(
                            [("动画：完整", "full"), ("动画：精简", "reduced"), ("动画：关闭", "off")],
                            value=self.motion_mode,
                            allow_blank=False,
                            id="motion-select",
                            compact=True,
                        )
                    yield Static("选择横轴和结果输出。", id="chart-status")
                    with Horizontal(id="chart-body"):
                        yield Static("尚未生成图表。", id="scan-preview")
                        yield DataTable(
                            id="scan-table",
                            show_row_labels=False,
                            zebra_stripes=True,
                            cursor_type="row",
                        )

            with TabPane("文档", id="documents-pane"):
                with Vertical(id="documents-view"):
                    with Horizontal(id="document-toolbar"):
                        yield Button("新建", id="new-document")
                        yield Select(
                            self._source_options(),
                            value=relative,
                            allow_blank=False,
                            id="source-select",
                        )
                        yield Button("保存", id="save-documents", variant="primary")
                        yield Button("校验", id="validate-documents")
                        yield Button("导出图表", id="export-document")
                    with Horizontal(id="body"):
                        yield KirinTextArea.code_editor(
                            self._buffers[self.source_path], id="editor", soft_wrap=False
                        )
                        with Vertical(id="side"):
                            yield Static("当前文档无需图表预览。", id="preview")
                            yield OptionList(id="completions", markup=False)
                            yield Static("等待校验…", id="diagnostics")

            with TabPane("诊断", id="diagnostics-pane"):
                with Vertical(id="diagnostics-view"):
                    with Horizontal(classes="view-toolbar"):
                        yield Select([], prompt="选择结果输出", allow_blank=True, id="explain-target")
                        yield Button("查看公式与依赖", id="explain-target-button", variant="primary")
                    with Horizontal(id="diagnostics-body"):
                        with Vertical(id="diagnostic-list-pane"):
                            yield Static("正在校验工作区…", id="workspace-diagnostics")
                            yield OptionList(id="diagnostic-list", markup=False)
                        yield Static("选择结果输出以查看公式、输入、单位和依赖。", id="explain-output")

            with TabPane("记录", id="runs-pane"):
                with Vertical(id="runs-view"):
                    with Horizontal(classes="view-toolbar"):
                        yield Input(placeholder="记录 ID", id="run-id", compact=True)
                        yield Button("保存当前计算", id="save-run", variant="primary")
                        yield Button("刷新列表", id="refresh-runs")
                        yield Button("重放选中记录", id="replay-run")
                    yield DataTable(
                        id="runs-table",
                        show_row_labels=False,
                        zebra_stripes=True,
                        cursor_type="row",
                    )
                    yield Static("尚未选择运行记录。", id="run-details")
        yield Static("尚未校验", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(KIRIN_THEME)
        self.theme = "kirin-tor"
        self.screen.set_class(self.size.width < 90, "narrow")
        editor = self.query_one("#editor", TextArea)
        editor.indent_width = 2
        comparison = self.query_one("#comparison-results", DataTable)
        comparison.add_columns("方案", "场景", "结果", "差异", "变化", "状态")
        scan_table = self.query_one("#scan-table", DataTable)
        scan_table.add_columns("横轴", "结果", "状态")
        runs_table = self.query_one("#runs-table", DataTable)
        runs_table.add_columns("记录 ID", "操作", "创建时间", "状态")
        self._refresh_runs()
        self.query_one("#target-select", Select).focus()
        if self.motion_enabled:
            brand = self.query_one("#brand", Static)
            brand.styles.opacity = 0.45
            brand.styles.animate("opacity", 1.0, duration=0.45)
        self._queue_validation(delay=0.05)

    def on_resize(self, event: events.Resize) -> None:
        self.screen.set_class(event.size.width < 90, "narrow")

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "editor":
            return
        self._revision += 1
        self._buffers[self.source_path] = event.text_area.text
        dirty = self._dirty_count()
        status = self.query_one_optional("#status", Static)
        if status is None:
            return
        status.update(
            f"{dirty} 个草稿已修改 · 正在校验…" if dirty else "正在校验…"
        )
        self._queue_validation()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "motion-select" and isinstance(event.value, str):
            self.motion_mode = event.value
            self.motion_enabled = self.motion_mode != "off"
            if not self.motion_enabled and self._plot_animation_timer is not None:
                self._plot_animation_timer.stop()
                self._plot_animation_timer = None
            return
        if event.select.id == "target-select":
            if isinstance(event.value, str):
                self._update_calculation_inputs(event.value)
            return
        if event.select.id != "source-select" or self._switching_document or not isinstance(event.value, str):
            return
        target = (self.root / event.value).resolve()
        self._switch_source(target)

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
            workspace = Workspace.load_for_check_with_overlays(self.root, overlays)
            Engine(workspace).validate_all()
            document = next(
                (
                    item
                    for item in workspace.documents.values()
                    if item.path.resolve() == source_path.resolve()
                ),
                None,
            )
            if document is None:
                raise WorkspaceError(f"editor document did not load from {source_path}")
            index = build_workspace_index(workspace)
            preview: Optional[Text] = None
            if isinstance(document, PlotConfig):
                preview = render_terminal_plot(_scan_plot(workspace, document), document, width, height)
            self.call_from_thread(self._apply_validation, revision, None, preview, index, [])
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 校验过程意外失败。\n技术详情：{exc}"
            )
            diagnostic_errors = (
                list(exc.errors)
                if isinstance(exc, ValidationErrors)
                else [exc]
                if isinstance(exc, KTError)
                else []
            )
            self.call_from_thread(
                self._apply_validation,
                revision,
                message,
                None,
                None,
                diagnostic_errors,
            )

    def _refresh_source_selector(self) -> None:
        selector = self.query_one_optional("#source-select", Select)
        if selector is None:
            return
        self._switching_document = True
        try:
            selector.set_options(self._source_options())
            selector.value = str(self.source_path.relative_to(self.root))
        finally:
            self._switching_document = False

    @staticmethod
    def _set_select_options(select: Select, options, preferred=None) -> None:
        current = preferred if preferred is not None else select.value
        select.set_options(options)
        values = {value for _label, value in options}
        if current in values:
            select.value = current
        elif options:
            select.value = options[0][1]
        else:
            select.value = Select.NULL

    def _apply_workspace_index(self, index: WorkspaceIndex) -> None:
        self._workspace_index = index
        target_options = [
            (
                Text.assemble(
                    item.label,
                    ("  ·  ", "dim"),
                    (item.value, "dim"),
                    (f"  [{item.unit}]", "dim"),
                ),
                item.value,
            )
            for item in index.targets
        ]
        input_options = [
            (
                Text.assemble(
                    item.label,
                    ("  ·  ", "dim"),
                    (item.value, "dim"),
                    (f"  [{item.unit}]", "dim"),
                ),
                item.value,
            )
            for item in index.inputs
            if item.value_type == "number"
        ]
        scenario_options = [("默认参数", "__defaults__")] + [
            (
                item.label if item.label != item.value else item.value,
                item.value,
            )
            for item in index.scenarios
        ]
        for selector_id in ("#target-select", "#scan-y-select", "#explain-target"):
            self._set_select_options(self.query_one(selector_id, Select), target_options)
        self._set_select_options(self.query_one("#scan-x-select", Select), input_options)
        self._set_select_options(
            self.query_one("#scan-scenario", Select), scenario_options, "__defaults__"
        )
        for row in self.query(VariantRow):
            row.set_scenarios(index.scenarios)
        selected_target = self.query_one("#target-select", Select).value
        if isinstance(selected_target, str):
            self._update_calculation_inputs(selected_target)

    def _update_calculation_inputs(self, target: str) -> None:
        if self._workspace_index is None:
            return
        target_option = next(
            (item for item in self._workspace_index.targets if item.value == target),
            None,
        )
        if target_option is None:
            return
        relevant = set(target_option.inputs)
        inputs = [item for item in self._workspace_index.inputs if item.value in relevant]
        numeric_options = [
            (
                Text.assemble(
                    item.label,
                    ("  ·  ", "dim"),
                    (item.value, "dim"),
                    (f"  [{item.unit}]", "dim"),
                ),
                item.value,
            )
            for item in inputs
            if item.value_type == "number"
        ]
        self._set_select_options(self.query_one("#solve-variable", Select), numeric_options)
        if not inputs:
            self.query_one("#calculation-input-help", Static).update(
                "这个结果没有可临时调整的输入。"
            )
            return
        details = []
        for item in inputs[:8]:
            constraints = []
            if item.default is not None:
                constraints.append(f"默认 {item.default}")
            if item.minimum is not None or item.maximum is not None:
                constraints.append(f"范围 {item.minimum or '—'}..{item.maximum or '—'}")
            suffix = f"，{'，'.join(constraints)}" if constraints else ""
            details.append(f"{item.label}（{item.value}）{suffix}")
        if len(inputs) > 8:
            details.append(f"另有 {len(inputs) - 8} 项")
        self.query_one("#calculation-input-help", Static).update(
            "可临时调整：" + "；".join(details)
        )

    def _apply_validation(
        self,
        revision: int,
        error: Optional[str],
        preview: Optional[Text],
        index: Optional[WorkspaceIndex],
        diagnostic_errors: Sequence[KTError],
    ) -> None:
        if revision != self._revision:
            return
        editor = self.query_one("#editor", TextArea)
        self._buffers[self.source_path] = editor.text
        dirty = self._dirty_count()
        self._diagnostic_errors = list(diagnostic_errors)
        diagnostic_list = self.query_one("#diagnostic-list", OptionList)
        diagnostic_list.clear_options()
        if diagnostic_errors:
            options = []
            for number, diagnostic in enumerate(diagnostic_errors):
                location = diagnostic.location
                path_text = "工作区"
                if location and location.path:
                    try:
                        path_text = str(Path(location.path).resolve().relative_to(self.root))
                    except (OSError, ValueError):
                        path_text = location.path
                    if location.line is not None:
                        path_text += f":{location.line}"
                options.append(
                    Option(
                        Text.assemble(
                            (path_text, "bold"),
                            "  ",
                            (diagnostic.message, "dim"),
                        ),
                        id=str(number),
                    )
                )
            diagnostic_list.add_options(options)
        if error:
            self.query_one("#diagnostics", Static).update(Text(error, style="red"))
            self.query_one("#workspace-diagnostics", Static).update(Text(error, style="red"))
            self.query_one("#status", Static).update(
                f"{dirty} 个草稿已修改 · 校验失败" if dirty else "校验失败"
            )
            self.query_one("#calculation-source-state", Static).update(
                "当前文档存在错误；修正后才能生成新的计算结果。"
            )
            if self._last_comparison is not None:
                self.query_one("#calculation-details", Static).update(
                    "当前显示的是较早的结果，已经过期。"
                )
            self.query_one("#preview", Static).update("文档校验失败，暂时无法预览。")
            return
        if index is not None:
            self._apply_workspace_index(index)
        self.query_one("#diagnostics", Static).update(Text("校验通过", style="green"))
        document_count = len(index.document_ids) if index is not None else 0
        self.query_one("#workspace-diagnostics", Static).update(
            f"工作区校验通过\n\n{document_count} 个文档可用于计算。"
        )
        self.query_one("#status", Static).update(
            f"{dirty} 个草稿已修改 · 校验通过" if dirty else "已保存 · 校验通过"
        )
        self.query_one("#calculation-source-state", Static).update(
            f"使用 {dirty} 个未保存草稿进行计算。" if dirty else "使用已保存且校验通过的文档。"
        )
        self.query_one("#preview", Static).update(
            preview if preview is not None else "当前文档无需图表预览。"
        )

    def action_validate(self) -> None:
        self._revision += 1
        self.query_one("#status", Static).update("正在校验…")
        self._start_validation()

    def _show_pane(self, pane_id: str) -> None:
        self.query_one("#main-content", TabbedContent).active = pane_id

    def action_show_calculate(self) -> None:
        self._show_pane("calculate-pane")
        self.query_one("#target-select", Select).focus()

    def action_show_charts(self) -> None:
        self._show_pane("charts-pane")
        self.query_one("#scan-x-select", Select).focus()

    def action_show_documents(self) -> None:
        self._show_pane("documents-pane")
        self.query_one("#editor", TextArea).focus()

    def action_show_diagnostics(self) -> None:
        self._show_pane("diagnostics-pane")
        self.query_one("#explain-target", Select).focus()

    def action_show_runs(self) -> None:
        self._show_pane("runs-pane")
        self._refresh_runs()
        self.query_one("#runs-table", DataTable).focus()

    def _known_document_ids(self) -> set[str]:
        result = set(self._workspace_index.document_ids if self._workspace_index else ())
        pattern = re.compile(r"^@(?:entry|scenario|plot)\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", re.MULTILINE)
        for source in self._all_source_texts().values():
            match = pattern.search(source)
            if match:
                result.add(match.group(1))
        return result

    def action_new_document(self) -> None:
        self.push_screen(
            NewDocumentScreen(
                self.root,
                self._known_document_ids(),
                self._all_source_texts(),
            ),
            self._accept_new_document,
        )

    def _accept_new_document(self, draft: Optional[DocumentDraft]) -> None:
        if draft is None:
            return
        if draft.path in self._buffers or draft.path.exists():
            self.query_one("#status", Static).update("无法创建：文件已经存在")
            return
        self._buffers[draft.path] = draft.source_text
        self._saved_texts[draft.path] = ""
        self._switch_source(draft.path)
        self._refresh_source_selector()
        self.action_show_documents()
        self.query_one("#status", Static).update("已创建未保存草稿")

    def _switch_source(self, target: Path, *, preserve_current: bool = True) -> None:
        target = target.resolve()
        if target == self.source_path:
            return
        self._close_completion()
        editor = self.query_one_optional("#editor", TextArea)
        if editor is None:
            return
        if preserve_current:
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

    async def _add_variant(self) -> None:
        rows = list(self.query(VariantRow))
        if len(rows) >= 8:
            self.query_one("#calculation-details", Static).update("最多可以比较 8 个方案。")
            return
        self._variant_counter += 1
        scenarios = self._workspace_index.scenarios if self._workspace_index else ()
        row = VariantRow(self._variant_counter, f"方案 {self._variant_counter}", scenarios)
        await self.query_one("#variant-list", VerticalScroll).mount(row)
        row.query_one(".variant-name", Input).focus()

    async def _remove_variant(self, row: VariantRow) -> None:
        if len(list(self.query(VariantRow))) <= 1:
            self.query_one("#calculation-details", Static).update("至少保留一个计算方案。")
            return
        await row.remove()

    def action_calculate(self) -> None:
        target = self.query_one("#target-select", Select).value
        if not isinstance(target, str):
            self.query_one("#calculation-details", Static).update("请先选择一个结果输出。")
            return
        try:
            inputs = self._workspace_index.inputs if self._workspace_index else ()
            variants = [row.request(inputs) for row in self.query(VariantRow)]
        except KTError as exc:
            self.query_one("#calculation-details", Static).update(
                Text(format_tui_diagnostic(exc, self.root), style="red")
            )
            return
        editor = self.query_one("#editor", TextArea)
        overlays = dict(self._buffers)
        overlays[self.source_path] = editor.text
        self._last_comparison_variants = variants
        self.query_one("#calculation-details", Static).update("正在计算…")
        self._comparison_worker(overlays, target, variants, self._revision, self._dirty_count())

    @work(thread=True, exclusive=True, group="calculate")
    def _comparison_worker(
        self,
        overlays: Dict[Path, str],
        target: str,
        variants: Sequence[ComparisonVariant],
        revision: int,
        dirty_count: int,
    ) -> None:
        try:
            workspace = Workspace.load_with_overlays(self.root, overlays)
            Engine(workspace).validate_all()
            result = compare_variants(workspace, target, variants)
            self.call_from_thread(
                self._apply_comparison, revision, dirty_count, result, None
            )
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 计算过程意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(
                self._apply_comparison, revision, dirty_count, None, message
            )

    def _apply_comparison(
        self,
        revision: int,
        dirty_count: int,
        result: Optional[dict],
        error: Optional[str],
    ) -> None:
        if revision != self._revision:
            return
        table = self.query_one("#comparison-results", DataTable)
        table.clear()
        if error or result is None:
            self.query_one("#calculation-details", Static).update(
                Text(error or "计算失败。", style="red")
            )
            return
        self._last_comparison = result
        for row in result["variants"]:
            scenario = row.get("scenario") or "默认参数"
            if row["status"] == "ok":
                calculated = row["result"]
                exact = calculated["exact"]
                approximate = calculated["approximate"]
                rendered_result = exact if exact == approximate else f"{exact}\n≈ {approximate}"
                delta = row.get("delta_exact") or "—"
                percent = (
                    f"{row['delta_percent']}%" if row.get("delta_percent") is not None else "—"
                )
                status = Text("完成", style="green")
            else:
                rendered_result = "—"
                delta = "—"
                percent = "—"
                status = Text(
                    f"错误：{row['error'].get('message', row['error'].get('code', 'unknown'))}",
                    style="red",
                )
            table.add_row(
                row["name"],
                scenario,
                rendered_result,
                delta,
                percent,
                status,
                height=2,
            )
        source_note = "未保存草稿" if dirty_count else "已保存文档"
        dependencies = "、".join(result.get("dependency_ids", [])) or "无跨文档依赖"
        self.query_one("#calculation-details", Static).update(
            f"依据：{source_note} · 单位：{result['unit']} · 依赖：{dependencies}"
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if event.button.has_class("variant-remove") and isinstance(event.button.parent, VariantRow):
            await self._remove_variant(event.button.parent)
        elif button_id in {"new-document", "new-document-toolbar"}:
            self.action_new_document()
        elif button_id == "add-variant":
            await self._add_variant()
        elif button_id == "calculate":
            self.action_calculate()
        elif button_id == "solve-target":
            self.action_solve_target()
        elif button_id == "save-documents":
            self.action_save()
        elif button_id == "validate-documents":
            self.action_validate()
        elif button_id == "export-document":
            self.action_export()
        elif button_id == "run-scan":
            self.action_run_scan()
        elif button_id == "run-variant-scan":
            self.action_run_variant_scan()
        elif button_id == "create-plot-draft":
            self.action_create_plot_draft()
        elif button_id == "explain-target-button":
            self.action_explain_target()
        elif button_id == "refresh-runs":
            self._refresh_runs()
        elif button_id == "save-run":
            self.action_save_run()
        elif button_id == "replay-run":
            self.action_replay_run()

    def action_solve_target(self) -> None:
        target = self.query_one("#target-select", Select).value
        variable = self.query_one("#solve-variable", Select).value
        equals = self.query_one("#solve-equals", Input).value.strip()
        range_text = self.query_one("#solve-range", Input).value.strip()
        if not isinstance(target, str) or not isinstance(variable, str):
            self.query_one("#solve-result", Static).update("请选择结果输出和要反求的输入。")
            return
        if not equals:
            self.query_one("#solve-result", Static).update("请输入希望达到的目标结果。")
            return
        try:
            inputs = self._workspace_index.inputs if self._workspace_index else ()
            baseline = next(iter(self.query(VariantRow))).request(inputs)
        except (StopIteration, KTError) as exc:
            message = "至少需要一个计算方案。" if isinstance(exc, StopIteration) else str(exc)
            self.query_one("#solve-result", Static).update(Text(message, style="red"))
            return
        editor = self.query_one("#editor", TextArea)
        overlays = dict(self._buffers)
        overlays[self.source_path] = editor.text
        self.query_one("#solve-result", Static).update("正在反求输入…")
        self._solve_worker(
            overlays,
            target,
            variable,
            equals,
            range_text or None,
            baseline,
            self._revision,
        )

    @work(thread=True, exclusive=True, group="solve")
    def _solve_worker(
        self,
        overlays: Dict[Path, str],
        target: str,
        variable: str,
        equals: str,
        range_text: Optional[str],
        baseline: ComparisonVariant,
        revision: int,
    ) -> None:
        try:
            workspace = Workspace.load_with_overlays(self.root, overlays)
            Engine(workspace).validate_all()
            result = solve_equation(
                Engine(workspace),
                target,
                variable,
                equals,
                range_text,
                baseline.scenario,
                baseline.normalized_overrides(),
            )
            self.call_from_thread(self._apply_solve, revision, baseline.name, result, None)
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 反求输入意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(self._apply_solve, revision, baseline.name, None, message)

    def _apply_solve(
        self,
        revision: int,
        baseline_name: str,
        result: Optional[dict],
        error: Optional[str],
    ) -> None:
        if revision != self._revision:
            return
        output = self.query_one("#solve-result", Static)
        if error or result is None:
            output.update(Text(error or "反求失败。", style="red"))
            return
        kind = result.get("solution_kind")
        if kind in {"exact", "numeric_approximate"}:
            rendered = []
            for solution in result.get("solutions", []):
                exact = solution["exact"]
                approximate = solution.get("approximate")
                rendered.append(exact if not approximate or approximate == exact else f"{exact}（约 {approximate}）")
            message = "；".join(rendered) or "没有可用解"
            output.update(
                f"按方案“{baseline_name}”：{result['variable']} = {message} [{result['unit']}]"
            )
        elif kind == "no_solution_proven":
            output.update(f"按方案“{baseline_name}”：指定范围内没有满足目标的输入。")
        else:
            output.update(
                f"按方案“{baseline_name}”：只能得到未完成解集 {result.get('solution_set', '—')}。"
            )

    def action_run_scan(self) -> None:
        axis = self.query_one("#scan-x-select", Select).value
        target = self.query_one("#scan-y-select", Select).value
        scenario_value = self.query_one("#scan-scenario", Select).value
        if not isinstance(axis, str) or not isinstance(target, str):
            self.query_one("#chart-status", Static).update("请选择横轴输入和结果输出。")
            return
        try:
            points = int(self.query_one("#scan-points", Input).value.strip())
            range_text = self.query_one("#scan-range", Input).value.strip()
            inputs = self._workspace_index.inputs if self._workspace_index else ()
            overrides = parse_player_override_text(
                self.query_one("#scan-overrides", Input).value,
                inputs,
            )
        except (ValueError, KTError) as exc:
            message = "点数必须是整数。" if isinstance(exc, ValueError) else str(exc)
            self.query_one("#chart-status", Static).update(Text(message, style="red"))
            return
        scenario = None if scenario_value in {"__defaults__", Select.NULL} else str(scenario_value)
        editor = self.query_one("#editor", TextArea)
        overlays = dict(self._buffers)
        overlays[self.source_path] = editor.text
        preview = self.query_one("#scan-preview", Static)
        self.query_one("#chart-status", Static).update("正在生成图表…")
        self._scan_worker(
            overlays,
            axis,
            range_text,
            points,
            target,
            scenario,
            overrides,
            self._revision,
            max(preview.size.width - 2, 30),
            max(preview.size.height - 2, 10),
        )

    def action_run_variant_scan(self) -> None:
        """Plot the variants currently configured on the Calculate page."""
        axis = self.query_one("#scan-x-select", Select).value
        target = self.query_one("#scan-y-select", Select).value
        if not isinstance(axis, str) or not isinstance(target, str):
            self.query_one("#chart-status", Static).update("请选择横轴输入和结果输出。")
            return
        try:
            points = int(self.query_one("#scan-points", Input).value.strip())
            range_text = self.query_one("#scan-range", Input).value.strip()
            inputs = self._workspace_index.inputs if self._workspace_index else ()
            variants = [row.request(inputs) for row in self.query(VariantRow)]
        except (ValueError, KTError) as exc:
            message = "点数必须是整数。" if isinstance(exc, ValueError) else str(exc)
            self.query_one("#chart-status", Static).update(Text(message, style="red"))
            return
        editor = self.query_one("#editor", TextArea)
        overlays = dict(self._buffers)
        overlays[self.source_path] = editor.text
        preview = self.query_one("#scan-preview", Static)
        self.query_one("#chart-status", Static).update("正在比较计算页中的方案…")
        self._variant_scan_worker(
            overlays,
            axis,
            range_text,
            points,
            target,
            variants,
            self._revision,
            max(preview.size.width - 2, 30),
            max(preview.size.height - 2, 10),
        )

    @work(thread=True, exclusive=True, group="scan")
    def _scan_worker(
        self,
        overlays: Dict[Path, str],
        axis: str,
        range_text: str,
        points: int,
        target: str,
        scenario: Optional[str],
        overrides: Dict[str, str],
        revision: int,
        width: int,
        height: int,
    ) -> None:
        try:
            workspace = Workspace.load_with_overlays(self.root, overlays)
            Engine(workspace).validate_all()
            scan = scan_values(
                Engine(workspace),
                axis,
                range_text,
                points,
                [target],
                scenario,
                overrides,
            )
            start, end = range_text.split(":", 1)
            config = PlotConfig(
                id="interactive_preview",
                name="interactive_preview",
                type="plot",
                path=self.root / "plots" / "interactive_preview.kirin",
                raw={},
                raw_text="",
                sha256="",
                x=axis,
                range_start=start,
                range_end=end,
                points=points,
                y=[target],
                scenario=scenario,
                title="比较曲线",
            )
            rendered = render_terminal_plot(scan, config, width, height)
            frames = (
                build_terminal_plot_frames(
                    scan,
                    config,
                    width,
                    height,
                    frame_count=3 if self.motion_mode == "reduced" else 8,
                )
                if self.motion_enabled
                else []
            )
            self.call_from_thread(
                self._apply_scan, revision, scan, rendered, frames, None
            )
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 图表计算意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(self._apply_scan, revision, None, None, [], message)

    @work(thread=True, exclusive=True, group="scan")
    def _variant_scan_worker(
        self,
        overlays: Dict[Path, str],
        axis: str,
        range_text: str,
        points: int,
        target: str,
        variants: Sequence[ComparisonVariant],
        revision: int,
        width: int,
        height: int,
    ) -> None:
        try:
            workspace = Workspace.load_with_overlays(self.root, overlays)
            Engine(workspace).validate_all()
            scan = scan_variant_comparison(
                workspace,
                axis,
                range_text,
                points,
                target,
                variants,
            )
            start, end = range_text.split(":", 1)
            config = PlotConfig(
                id="interactive_comparison",
                name="interactive_comparison",
                type="plot",
                path=self.root / "plots" / "interactive_comparison.kirin",
                raw={},
                raw_text="",
                sha256="",
                x=axis,
                range_start=start,
                range_end=end,
                points=points,
                y=list(scan["targets"]),
                scenario=None,
                title="方案比较",
            )
            rendered = render_terminal_plot(scan, config, width, height)
            frames = (
                build_terminal_plot_frames(
                    scan,
                    config,
                    width,
                    height,
                    frame_count=3 if self.motion_mode == "reduced" else 8,
                )
                if self.motion_enabled
                else []
            )
            self.call_from_thread(
                self._apply_scan, revision, scan, rendered, frames, None
            )
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 方案图表计算意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(self._apply_scan, revision, None, None, [], message)

    def _apply_scan(
        self,
        revision: int,
        scan: Optional[dict],
        rendered: Optional[Text],
        frames: Sequence[Text],
        error: Optional[str],
    ) -> None:
        if revision != self._revision:
            return
        table = self.query_one("#scan-table", DataTable)
        table.clear(columns=True)
        if error or scan is None or rendered is None:
            table.add_columns("横轴", "结果", "状态")
            self.query_one("#chart-status", Static).update(Text(error or "图表失败。", style="red"))
            return
        self._last_scan = scan
        if frames:
            self._start_plot_animation(list(frames), rendered)
        else:
            self.query_one("#scan-preview", Static).update(rendered)
        targets = list(scan["targets"])
        labels = scan.get("labels", {})
        table.add_columns("横轴", *(labels.get(target, target) for target in targets), "状态")
        for row in scan["rows"]:
            rendered_values = []
            errors = []
            for target in targets:
                value = row["values"][target]
                if value["error"] is None:
                    rendered_values.append(value["exact"])
                else:
                    rendered_values.append("—")
                    errors.append(value["error"])
            status = (
                Text("有效", style="green")
                if not errors
                else Text(f"{len(errors)} 个错误", style="red")
            )
            table.add_row(row["x"], *rendered_values, status)
        warnings = "；".join(scan.get("warnings", []))
        valid_text = "，".join(
            f"{labels.get(target, target)} {scan['valid_points'][target]}/{scan['points']}"
            for target in targets
        )
        message = f"已计算 {scan['points']} 个点：{valid_text}。"
        if scan.get("operation") == "scan_compare":
            message += " 使用计算页中的方案设置；图表页的场景和临时参数未参与。"
        if warnings:
            message += f" {warnings}"
        self.query_one("#chart-status", Static).update(message)

    def _start_plot_animation(self, frames: list[Text], final_frame: Text) -> None:
        if self._plot_animation_timer is not None:
            self._plot_animation_timer.stop()
        self._plot_animation_frames = list(frames[:-1]) + [final_frame]
        self._plot_animation_index = 0
        self._advance_plot_animation()

    def _advance_plot_animation(self) -> None:
        if self._plot_animation_index >= len(self._plot_animation_frames):
            self._plot_animation_timer = None
            return
        preview = self.query_one_optional("#scan-preview", Static)
        if preview is None:
            self._plot_animation_timer = None
            return
        preview.update(self._plot_animation_frames[self._plot_animation_index])
        self._plot_animation_index += 1
        if self._plot_animation_index < len(self._plot_animation_frames):
            self._plot_animation_timer = self.set_timer(0.09, self._advance_plot_animation)
        else:
            self._plot_animation_timer = None

    def action_create_plot_draft(self) -> None:
        plot_id = self.query_one("#scan-plot-id", Input).value.strip()
        axis = self.query_one("#scan-x-select", Select).value
        target = self.query_one("#scan-y-select", Select).value
        scenario_value = self.query_one("#scan-scenario", Select).value
        try:
            if self._last_scan is not None and self._last_scan.get("operation") == "scan_compare":
                raise ParameterError(
                    "多方案比较图只能在工作台中查看；请先生成单方案图，再创建图表文档"
                )
            if not isinstance(axis, str) or not isinstance(target, str):
                raise ParameterError("请先选择横轴输入和结果输出")
            if not plot_id:
                raise ParameterError("请输入图表文档 ID")
            range_text = self.query_one("#scan-range", Input).value.strip()
            if range_text.count(":") != 1:
                raise ParameterError("范围必须使用 START:END")
            start, end = range_text.split(":", 1)
            points = int(self.query_one("#scan-points", Input).value.strip())
            scenario = (
                None
                if scenario_value in {"__defaults__", Select.NULL}
                else str(scenario_value)
            )
            draft = build_document_draft(
                self.root,
                "plot",
                plot_id,
                plot_x=axis,
                plot_targets=(target,),
                plot_range_start=start,
                plot_range_end=end,
                plot_points=points,
                plot_scenario=scenario,
            )
            if draft.document_id in self._known_document_ids():
                raise WorkspaceError(f"文档 ID 已存在：{draft.document_id}")
            if draft.path.exists() or draft.path in self._buffers:
                raise WorkspaceError(f"文件已经存在：{draft.path.relative_to(self.root)}")
        except (ValueError, KTError) as exc:
            message = "点数必须是整数。" if isinstance(exc, ValueError) else str(exc)
            self.query_one("#chart-status", Static).update(Text(message, style="red"))
            return
        self._accept_new_document(draft)

    def action_explain_target(self) -> None:
        target = self.query_one("#explain-target", Select).value
        if not isinstance(target, str):
            self.query_one("#explain-output", Static).update("请先选择一个结果输出。")
            return
        editor = self.query_one("#editor", TextArea)
        overlays = dict(self._buffers)
        overlays[self.source_path] = editor.text
        self.query_one("#explain-output", Static).update("正在读取公式和依赖…")
        self._explain_worker(overlays, target, self._revision)

    @work(thread=True, exclusive=True, group="explain")
    def _explain_worker(
        self, overlays: Dict[Path, str], target: str, revision: int
    ) -> None:
        try:
            workspace = Workspace.load_with_overlays(self.root, overlays)
            Engine(workspace).validate_all()
            result = explain(Engine(workspace), target)
            self.call_from_thread(self._apply_explain, revision, result, None)
        except Exception as exc:
            message = (
                format_tui_diagnostic(exc, self.root, overlays)
                if isinstance(exc, KTError)
                else f"[内部错误] 公式说明意外失败。\n技术详情：{exc}"
            )
            self.call_from_thread(self._apply_explain, revision, None, message)

    def _apply_explain(
        self, revision: int, result: Optional[dict], error: Optional[str]
    ) -> None:
        if revision != self._revision:
            return
        output = self.query_one("#explain-output", Static)
        if error or result is None:
            output.update(Text(error or "无法读取公式。", style="red"))
            return
        lines = [
            result.get("label") or result["target"],
            f"正式名称：{result['target']}",
            f"单位：{result['unit']}",
            "",
            "展开公式：",
            result["expression"],
            "",
            "输入：",
        ]
        if result["inputs"]:
            for name, spec in result["inputs"].items():
                details = [spec.get("label") or name, f"单位 {spec['unit']}"]
                if spec.get("default") is not None:
                    details.append(f"默认 {spec['default']}")
                if spec.get("min") is not None or spec.get("max") is not None:
                    details.append(f"范围 {spec.get('min', '—')}..{spec.get('max', '—')}")
                lines.append(f"- {name}：" + " · ".join(details))
        else:
            lines.append("- 无输入")
        lines.extend(
            [
                "",
                "条件：" + ("；".join(result["conditions"]) if result["conditions"] else "无"),
                "依赖文档："
                + ("、".join(result["dependency_ids"]) if result["dependency_ids"] else "无"),
            ]
        )
        output.update("\n".join(lines))

    def _refresh_runs(self) -> None:
        table = self.query_one_optional("#runs-table", DataTable)
        if table is None:
            return
        table.clear()
        self._selected_run_id = None
        runs_directory = self.root / "runs"
        for path in sorted(runs_directory.glob("*.json"), reverse=True):
            run_id = path.stem
            try:
                record = load_run(self.root, run_id)
                table.add_row(
                    run_id,
                    record.get("operation", "—"),
                    record.get("created_at", "—"),
                    record.get("status", "—"),
                    key=run_id,
                )
                if self._selected_run_id is None:
                    self._selected_run_id = run_id
            except KTError as exc:
                table.add_row(run_id, "—", "—", f"损坏：{exc.code}", key=run_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "runs-table":
            return
        self._selected_run_id = str(event.row_key.value)
        self.query_one("#run-details", Static).update(f"已选择：{self._selected_run_id}")

    def action_save_run(self) -> None:
        run_id = self.query_one("#run-id", Input).value.strip()
        if not run_id:
            self.query_one("#run-details", Static).update("请输入运行记录 ID。")
            return
        if self._dirty_count():
            self.query_one("#run-details", Static).update(
                "保存运行记录前必须先保存并校验所有文档。"
            )
            return
        if self._last_comparison is None or not self._last_comparison_variants:
            self.query_one("#run-details", Static).update("请先在计算页生成结果。")
            return
        self.query_one("#run-details", Static).update("正在保存运行记录…")
        self._save_run_worker(
            run_id,
            self._last_comparison["target"],
            list(self._last_comparison_variants),
        )

    @work(thread=True, exclusive=True, group="runs")
    def _save_run_worker(
        self, run_id: str, target: str, variants: Sequence[ComparisonVariant]
    ) -> None:
        try:
            workspace = Workspace.load(self.root)
            Engine(workspace).validate_all()
            result = save_comparison_run(workspace, run_id, target, variants)
            self.call_from_thread(self._apply_saved_run, run_id, result, None)
        except Exception as exc:
            message = str(exc) if isinstance(exc, KTError) else f"内部错误：{exc}"
            self.call_from_thread(self._apply_saved_run, run_id, None, message)

    def _apply_saved_run(
        self, run_id: str, result: Optional[dict], error: Optional[str]
    ) -> None:
        if error or result is None:
            self.query_one("#run-details", Static).update(Text(error or "保存失败。", style="red"))
            return
        self._refresh_runs()
        self._selected_run_id = run_id
        self.query_one("#run-details", Static).update(f"已保存运行记录：{run_id}")

    def action_replay_run(self) -> None:
        run_id = self._selected_run_id or self.query_one("#run-id", Input).value.strip()
        if not run_id:
            self.query_one("#run-details", Static).update("请选择一条运行记录。")
            return
        self.query_one("#run-details", Static).update(f"正在重放 {run_id}…")
        self._replay_worker(run_id)

    @work(thread=True, exclusive=True, group="runs")
    def _replay_worker(self, run_id: str) -> None:
        try:
            result = replay_run(self.root, run_id)
            self.call_from_thread(self._apply_replay, run_id, result, None)
        except Exception as exc:
            message = str(exc) if isinstance(exc, KTError) else f"内部错误：{exc}"
            self.call_from_thread(self._apply_replay, run_id, None, message)

    def _apply_replay(
        self, run_id: str, result: Optional[dict], error: Optional[str]
    ) -> None:
        if error or result is None:
            self.query_one("#run-details", Static).update(Text(error or "重放失败。", style="red"))
            return
        lines = [
            f"记录：{run_id}",
            f"操作：{result['original_operation']}",
            f"结果一致：{'是' if result['matches_recorded_result'] else '否'}",
            f"环境一致：{'是' if result['environment_match'] else '否'}",
        ]
        if result.get("version_drift"):
            lines.append("检测到依赖或实现版本变化。")
        self.query_one("#run-details", Static).update("\n".join(lines))

    def action_request_quit(self) -> None:
        dirty = self._dirty_count()
        if not dirty:
            self.exit()
            return
        self.push_screen(
            UnsavedChangesScreen(f"有 {dirty} 个未保存草稿。退出前如何处理？"),
            self._handle_quit_decision,
        )

    def _handle_quit_decision(self, decision: str) -> None:
        if decision == "discard":
            self.exit()
        elif decision == "save":
            self._exit_after_save = True
            self.action_save()

    def action_close_document(self) -> None:
        paths = {path.resolve() for path in self._all_source_texts()}
        if len(paths) <= 1:
            self.query_one("#status", Static).update("至少保留一个打开的文档。")
            return
        current = self.source_path
        if self._buffers.get(current, self._saved_text(current)) != self._saved_text(current):
            self.push_screen(
                UnsavedChangesScreen("当前文档有未保存修改。", allow_save=True),
                lambda decision: self._handle_close_decision(current, decision),
            )
        else:
            self._close_document_now(current)

    def _handle_close_decision(self, path: Path, decision: str) -> None:
        if decision == "discard":
            self._close_document_now(path)
        elif decision == "save":
            self._close_after_save = path
            self.action_save()

    def _close_document_now(self, path: Path) -> None:
        candidates = sorted(
            candidate
            for candidate in self._all_source_texts()
            if candidate.resolve() != path.resolve()
        )
        if not candidates:
            self.query_one("#status", Static).update("至少保留一个打开的文档。")
            return
        self._buffers.pop(path, None)
        self._saved_texts.pop(path, None)
        self._switch_source(candidates[0], preserve_current=False)
        self._refresh_source_selector()

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
        if event.option_list.id == "diagnostic-list":
            if 0 <= event.option_index < len(self._diagnostic_errors):
                self._open_diagnostic(self._diagnostic_errors[event.option_index])
            return
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

    def _open_diagnostic(self, diagnostic: KTError) -> None:
        location = diagnostic.location
        if location is None or location.path is None:
            return
        path = Path(location.path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return
        self._show_pane("documents-pane")
        self._switch_source(path)
        row = max((location.line or 1) - 1, 0)
        column = max((location.column or 1) - 1, 0)
        self.call_after_refresh(self._move_editor_cursor, row, column)

    def _move_editor_cursor(self, row: int, column: int) -> None:
        editor = self.query_one_optional("#editor", TextArea)
        if editor is None or not editor.document.lines:
            return
        row = min(row, editor.document.line_count - 1)
        column = min(column, len(editor.document[row]))
        editor.move_cursor((row, column))
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
            self._exit_after_save = False
            self._close_after_save = None
            return
        for path, saved_text in saved_buffers.items():
            self._saved_texts[path] = saved_text
        self._refresh_source_selector()
        if (
            source_path == self.source_path
            and revision == self._revision
            and self.query_one("#editor", TextArea).text == self._buffers[source_path]
        ):
            self.query_one("#status", Static).update("已保存 · 校验通过")
        else:
            self.query_one("#status", Static).update("已保存较早版本 · 当前草稿仍有修改")
        if self._exit_after_save and revision == self._revision and self._dirty_count() == 0:
            self._exit_after_save = False
            self.exit()
            return
        if self._exit_after_save:
            self._exit_after_save = False
            self.query_one("#status", Static).update("保存后又有新的修改，已取消退出")
        if self._close_after_save is not None:
            closing = self._close_after_save
            self._close_after_save = None
            if self._buffers.get(closing, self._saved_text(closing)) == self._saved_text(closing):
                self._close_document_now(closing)
                return
            self.query_one("#status", Static).update("保存后文档又有新的修改，已取消关闭")
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
        self._show_pane("documents-pane")
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
