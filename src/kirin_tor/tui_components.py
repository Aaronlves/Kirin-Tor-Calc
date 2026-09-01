"""Reusable Textual components for the player-facing workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from .application import (
    ComparisonVariant,
    InputOption,
    NamedOption,
    parse_player_override_text,
)
from .errors import KTError, WorkspaceError
from .workspace import (
    DOCUMENT_DRAFT_KINDS,
    ENTRY_TEMPLATE_KINDS,
    DocumentDraft,
    build_document_draft,
)


DEFAULT_PRESET = "__defaults__"


class VariantRow(Horizontal):
    """Editable controls for one named calculation variant."""

    DEFAULT_CSS = """
    VariantRow {
        height: 3;
        width: 1fr;
    }
    VariantRow .variant-index {
        width: 8;
        height: 3;
        content-align: left middle;
        color: $text-muted;
    }
    VariantRow .variant-name {
        width: 1fr;
        min-width: 12;
    }
    VariantRow .variant-preset {
        width: 1fr;
        min-width: 16;
    }
    VariantRow .variant-overrides {
        width: 2fr;
        min-width: 24;
    }
    VariantRow .variant-form {
        width: 12;
    }
    VariantRow .variant-remove {
        width: 8;
    }
    """

    def __init__(
        self,
        number: int,
        name: str,
        presets: Sequence[NamedOption] = (),
    ) -> None:
        super().__init__(id=f"variant-{number}", classes="variant-row")
        self.number = number
        self.initial_name = name
        self._presets = tuple(presets)
        self.form_overrides: dict[str, str] = {}

    def _preset_options(self):
        return [("默认参数", DEFAULT_PRESET)] + [
            (item.label if item.label != item.value else item.value, item.value)
            for item in self._presets
        ]

    def compose(self) -> ComposeResult:
        yield Label(f"方案 {self.number}", classes="variant-index")
        yield Input(self.initial_name, placeholder="方案名称", classes="variant-name", compact=True)
        yield Select(
            self._preset_options(),
            value=DEFAULT_PRESET,
            allow_blank=False,
            classes="variant-preset",
            compact=True,
        )
        yield Input(
            placeholder="高级输入：暴击率=25%，用逗号分隔",
            classes="variant-overrides",
            compact=True,
        )
        yield Button("参数表单", classes="variant-form", compact=True)
        yield Button("移除", classes="variant-remove", compact=True)

    def set_presets(self, presets: Sequence[NamedOption]) -> None:
        self._presets = tuple(presets)
        select = self.query_one(".variant-preset", Select)
        current = select.value
        options = self._preset_options()
        select.set_options(options)
        values = {value for _label, value in options}
        select.value = current if current in values else DEFAULT_PRESET

    def request(self, inputs: Sequence[InputOption] = ()) -> ComparisonVariant:
        name = self.query_one(".variant-name", Input).value.strip()
        preset_value = self.query_one(".variant-preset", Select).value
        preset = (
            None
            if preset_value in {DEFAULT_PRESET, Select.NULL}
            else str(preset_value)
        )
        overrides = parse_player_override_text(
            self.query_one(".variant-overrides", Input).value,
            inputs,
        )
        duplicates = set(overrides) & set(self.form_overrides)
        if duplicates:
            raise WorkspaceError(
                "参数同时出现在表单和高级输入中：" + "、".join(sorted(duplicates))
            )
        overrides.update(self.form_overrides)
        return ComparisonVariant(name, preset, overrides)

    def set_form_overrides(self, values: Optional[dict[str, str]]) -> None:
        if values is None:
            return
        self.form_overrides = dict(values)
        button = self.query_one(".variant-form", Button)
        button.label = f"参数表单 {len(values)}" if values else "参数表单"


class OverrideFormScreen(ModalScreen[Optional[dict[str, str]]]):
    """Edit relevant inputs with type-aware controls instead of assignment syntax."""

    DEFAULT_CSS = """
    OverrideFormScreen {
        align: center middle;
        background: $background 70%;
    }
    OverrideFormScreen #override-dialog {
        width: 76;
        height: 80%;
        padding: 1 2;
        background: $panel;
        border: tall $primary;
    }
    OverrideFormScreen #override-fields {
        height: 1fr;
    }
    OverrideFormScreen .override-label {
        height: auto;
        margin-top: 1;
        color: $text-muted;
    }
    OverrideFormScreen .dialog-actions {
        height: 3;
        align-horizontal: right;
    }
    """

    def __init__(self, inputs: Sequence[InputOption], current: dict[str, str]) -> None:
        super().__init__()
        self.inputs = tuple(inputs)
        self.current = dict(current)

    def compose(self) -> ComposeResult:
        with Vertical(id="override-dialog"):
            yield Label("临时参数表单", classes="dialog-title")
            yield Static("留空表示使用所选参数方案或条目默认值。")
            with VerticalScroll(id="override-fields"):
                for index, item in enumerate(self.inputs):
                    details = [item.value, f"单位 {item.unit}"]
                    if item.default is not None:
                        details.append(f"默认 {item.default}")
                    if item.minimum is not None or item.maximum is not None:
                        details.append(f"范围 {item.minimum or '—'}..{item.maximum or '—'}")
                    yield Label(
                        f"{item.label} · " + " · ".join(details),
                        classes="override-label",
                    )
                    current = self.current.get(item.value, "")
                    if item.value_type == "boolean":
                        yield Select(
                            [("使用默认值", "__default__"), ("开启", "true"), ("关闭", "false")],
                            value=current.lower() if current.lower() in {"true", "false"} else "__default__",
                            allow_blank=False,
                            id=f"override-{index}",
                        )
                    else:
                        yield Input(
                            current,
                            placeholder="留空使用默认值；百分比可写 25%",
                            id=f"override-{index}",
                        )
            yield Static("", id="override-error")
            with Horizontal(classes="dialog-actions"):
                yield Button("清空", id="override-clear")
                yield Button("取消", id="override-cancel")
                yield Button("应用", id="override-apply", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "override-cancel":
            self.dismiss(None)
            return
        if event.button.id == "override-clear":
            self.dismiss({})
            return
        if event.button.id != "override-apply":
            return
        assignments = []
        for index, item in enumerate(self.inputs):
            widget = self.query_one(f"#override-{index}")
            if isinstance(widget, Select):
                value = widget.value
                if value in {"__default__", Select.NULL}:
                    continue
                assignments.append(f"{item.value}={value}")
            elif isinstance(widget, Input):
                value = widget.value.strip()
                if value:
                    assignments.append(f"{item.value}={value}")
        try:
            parsed = parse_player_override_text(",".join(assignments), self.inputs)
        except KTError as exc:
            self.query_one("#override-error", Static).update(str(exc))
            return
        self.dismiss(parsed)


class NewDocumentScreen(ModalScreen[Optional[DocumentDraft]]):
    """Create an in-memory source draft with no immediate file write."""

    DEFAULT_CSS = """
    NewDocumentScreen {
        align: center middle;
        background: $background 70%;
    }
    NewDocumentScreen #new-document-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: tall $primary;
    }
    NewDocumentScreen .dialog-title {
        height: 2;
        color: $text-primary;
        text-style: bold;
    }
    NewDocumentScreen .field-label {
        height: 1;
        color: $text-muted;
    }
    NewDocumentScreen #new-path,
    NewDocumentScreen #new-error {
        min-height: 1;
        margin: 1 0;
    }
    NewDocumentScreen #new-error {
        color: $text-error;
    }
    NewDocumentScreen .dialog-actions {
        height: 3;
        align-horizontal: right;
    }
    """

    KIND_LABELS = {
        "entry": "通用条目",
        "plot": "图表配置",
    }

    TEMPLATE_LABELS = {
        "blank": "空白",
        "data": "数据与技能",
        "model": "组合计算",
        "semantics": "数学语义",
    }

    def __init__(
        self,
        root: Path,
        existing_ids: Iterable[str],
        existing_paths: Iterable[Path],
    ) -> None:
        super().__init__()
        self.root = root.resolve()
        self.existing_ids = set(existing_ids)
        self.existing_paths = {path.resolve() for path in existing_paths}

    def compose(self) -> ComposeResult:
        with Vertical(id="new-document-dialog"):
            yield Label("新建文档", classes="dialog-title")
            yield Label("类型", classes="field-label")
            yield Select(
                [(self.KIND_LABELS[kind], kind) for kind in DOCUMENT_DRAFT_KINDS],
                value="entry",
                allow_blank=False,
                id="new-kind",
            )
            yield Label("起始模板（仅用于条目）", classes="field-label")
            yield Select(
                [(self.TEMPLATE_LABELS[kind], kind) for kind in ENTRY_TEMPLATE_KINDS],
                value="model",
                allow_blank=False,
                id="new-template",
            )
            yield Label("文档 ID", classes="field-label")
            yield Input(placeholder="例如：arcane_missiles", id="new-id")
            yield Static("输入 ID 后显示文件路径", id="new-path")
            yield Static("", id="new-error")
            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="new-cancel")
                yield Button("创建草稿", id="new-create", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#new-id", Input).focus()

    def _candidate(self) -> Optional[DocumentDraft]:
        kind = self.query_one("#new-kind", Select).value
        template = self.query_one("#new-template", Select).value
        document_id = self.query_one("#new-id", Input).value.strip()
        if not document_id or not isinstance(kind, str) or not isinstance(template, str):
            return None
        return build_document_draft(
            self.root,
            kind,
            document_id,
            entry_template=template,
        )

    def _refresh_preview(self) -> None:
        error = self.query_one("#new-error", Static)
        try:
            candidate = self._candidate()
        except KTError as exc:
            self.query_one("#new-path", Static).update("路径尚未确定")
            error.update(str(exc))
            return
        error.update("")
        if candidate is None:
            self.query_one("#new-path", Static).update("输入 ID 后显示文件路径")
            return
        relative = candidate.path.relative_to(self.root)
        self.query_one("#new-path", Static).update(f"将创建草稿：{relative}")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "new-id":
            self._refresh_preview()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in {"new-kind", "new-template"}:
            self._refresh_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-cancel":
            self.dismiss(None)
            return
        if event.button.id != "new-create":
            return
        error = self.query_one("#new-error", Static)
        try:
            candidate = self._candidate()
            if candidate is None:
                raise WorkspaceError("请输入文档 ID")
            if candidate.document_id in self.existing_ids:
                raise WorkspaceError(f"文档 ID 已存在：{candidate.document_id}")
            if candidate.path in self.existing_paths or candidate.path.exists():
                raise WorkspaceError(
                    f"文件已经存在：{candidate.path.relative_to(self.root)}"
                )
        except KTError as exc:
            error.update(str(exc))
            return
        self.dismiss(candidate)


class UnsavedChangesScreen(ModalScreen[str]):
    """Ask for an explicit decision before discarding in-memory authority drafts."""

    DEFAULT_CSS = """
    UnsavedChangesScreen {
        align: center middle;
        background: $background 70%;
    }
    UnsavedChangesScreen #unsaved-dialog {
        width: 62;
        height: auto;
        padding: 1 2;
        background: $panel;
        border: tall $warning;
    }
    UnsavedChangesScreen #unsaved-message {
        min-height: 3;
    }
    UnsavedChangesScreen .dialog-actions {
        height: 3;
        align-horizontal: right;
    }
    """

    def __init__(self, message: str, allow_save: bool = True) -> None:
        super().__init__()
        self.message = message
        self.allow_save = allow_save

    def compose(self) -> ComposeResult:
        with Vertical(id="unsaved-dialog"):
            yield Label("未保存的修改", classes="dialog-title")
            yield Static(self.message, id="unsaved-message")
            with Horizontal(classes="dialog-actions"):
                yield Button("取消", id="decision-cancel")
                yield Button("丢弃", id="decision-discard", variant="warning")
                if self.allow_save:
                    yield Button("保存", id="decision-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        decision = {
            "decision-cancel": "cancel",
            "decision-discard": "discard",
            "decision-save": "save",
        }.get(event.button.id)
        if decision:
            self.dismiss(decision)
