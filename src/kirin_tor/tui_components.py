"""Reusable Textual components for the player-facing workbench."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from .application import (
    ComparisonVariant,
    InputOption,
    NamedOption,
    parse_player_override_text,
)
from .errors import KTError, WorkspaceError
from .workspace import DOCUMENT_DRAFT_KINDS, DocumentDraft, build_document_draft


DEFAULT_SCENARIO = "__defaults__"


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
    VariantRow .variant-scenario {
        width: 1fr;
        min-width: 16;
    }
    VariantRow .variant-overrides {
        width: 2fr;
        min-width: 24;
    }
    VariantRow .variant-remove {
        width: 8;
    }
    """

    def __init__(
        self,
        number: int,
        name: str,
        scenarios: Sequence[NamedOption] = (),
    ) -> None:
        super().__init__(id=f"variant-{number}", classes="variant-row")
        self.number = number
        self.initial_name = name
        self._scenarios = tuple(scenarios)

    def _scenario_options(self):
        return [("默认参数", DEFAULT_SCENARIO)] + [
            (item.label if item.label != item.value else item.value, item.value)
            for item in self._scenarios
        ]

    def compose(self) -> ComposeResult:
        yield Label(f"方案 {self.number}", classes="variant-index")
        yield Input(self.initial_name, placeholder="方案名称", classes="variant-name", compact=True)
        yield Select(
            self._scenario_options(),
            value=DEFAULT_SCENARIO,
            allow_blank=False,
            classes="variant-scenario",
            compact=True,
        )
        yield Input(
            placeholder="临时参数：暴击率=25%，用逗号分隔",
            classes="variant-overrides",
            compact=True,
        )
        yield Button("移除", classes="variant-remove", compact=True)

    def set_scenarios(self, scenarios: Sequence[NamedOption]) -> None:
        self._scenarios = tuple(scenarios)
        select = self.query_one(".variant-scenario", Select)
        current = select.value
        options = self._scenario_options()
        select.set_options(options)
        values = {value for _label, value in options}
        select.value = current if current in values else DEFAULT_SCENARIO

    def request(self, inputs: Sequence[InputOption] = ()) -> ComparisonVariant:
        name = self.query_one(".variant-name", Input).value.strip()
        scenario_value = self.query_one(".variant-scenario", Select).value
        scenario = (
            None
            if scenario_value in {DEFAULT_SCENARIO, Select.NULL}
            else str(scenario_value)
        )
        overrides = parse_player_override_text(
            self.query_one(".variant-overrides", Input).value,
            inputs,
        )
        return ComparisonVariant(name, scenario, overrides)


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
        "skill": "技能或数据",
        "model": "组合模型",
        "scenario": "参数方案",
        "plot": "图表配置",
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
                value="model",
                allow_blank=False,
                id="new-kind",
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
        document_id = self.query_one("#new-id", Input).value.strip()
        if not document_id or not isinstance(kind, str):
            return None
        return build_document_draft(self.root, kind, document_id)

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
        if event.select.id == "new-kind":
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
