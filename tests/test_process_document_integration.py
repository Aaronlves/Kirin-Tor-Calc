from __future__ import annotations

from pathlib import Path

from kirin_tor.engine import Engine
from kirin_tor.kirin_syntax import load_kirin_document, render_kirin_document
from kirin_tor.process_ir import SymbolicTypeIR
from kirin_tor.workspace import Workspace, initialize


SOURCE = """@kirin 2
@entry process_entry "过程文档"

dimension vitality

unit health = vitality

unit damage = vitality

domain dot_mode "周期模式":
  - snapshot "快照"
  - dynamic "动态"

process periodic_damage "周期伤害":
  input selected_mode: dot_mode = snapshot
  state mode: dot_mode = selected_mode
  state health: health = 100 health in 0 health..100 health
  event input hit(amount: damage reduce sum)

  on hit(amount):
    next health = max(0 health, health - amount)

  observe alive: boolean = health > 0 health
"""


def test_workspace_loads_typed_processes_and_symbolic_domains(tmp_path: Path) -> None:
    root = initialize(tmp_path / "process-workspace")
    path = root / "entries" / "process_entry.kirin"
    path.write_text(SOURCE, encoding="utf-8")

    workspace = Workspace.load(root)
    entry = workspace.get_entry("process_entry")

    assert Engine(workspace).validate_all()["status"] == "ok"
    assert "processes" not in entry.raw
    assert [process.id for process in entry.process_asts] == ["periodic_damage"]
    assert list(entry.processes) == ["periodic_damage"]
    assert list(workspace.processes) == ["process_entry.periodic_damage"]
    process = entry.processes["periodic_damage"]
    assert isinstance(process.inputs[0].value_type, SymbolicTypeIR)
    assert process.inputs[0].default is not None
    assert process.inputs[0].default.references[0].id == "snapshot"
    assert workspace.units.domains["dot_mode"].allowed_values == (
        "snapshot",
        "dynamic",
    )


def test_typed_document_renderer_round_trips_process_and_domain_labels(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "process-round-trip")
    path = root / "entries" / "process_entry.kirin"
    path.write_text(SOURCE, encoding="utf-8")
    entry = Workspace.load(root).get_entry("process_entry")

    rendered = render_kirin_document(entry)
    assert 'domain dot_mode "周期模式":' in rendered
    assert '  - snapshot "快照"' in rendered
    assert 'process periodic_damage "周期伤害":' in rendered

    overlay = Workspace.load_with_overlay(root, path, rendered)
    rendered_entry = overlay.get_entry("process_entry")
    assert rendered_entry.process_asts == entry.process_asts
    assert rendered_entry.processes == entry.processes

    loaded = load_kirin_document(path, rendered)
    assert render_kirin_document(loaded) == rendered


def test_symbolic_values_are_domain_scoped_and_support_qualified_disambiguation(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "symbolic-domains")
    path = root / "entries" / "symbols.kirin"
    path.write_text(
        """@kirin 2
@entry symbols

domain first_mode:
  - none
  - active

domain second_mode:
  - none
  - ready

process choices:
  input first: first_mode = none
  input second: second_mode = second_mode.none
  state selected: first_mode = first
  observe current: first_mode = selected
""",
        encoding="utf-8",
    )

    process = Workspace.load(root).get_entry("symbols").processes["choices"]
    assert process.inputs[0].default is not None
    assert process.inputs[0].default.references[0].owner_id == "@domain.first_mode"
    assert process.inputs[1].default is not None
    assert process.inputs[1].default.references[0].owner_id == "@domain.second_mode"
