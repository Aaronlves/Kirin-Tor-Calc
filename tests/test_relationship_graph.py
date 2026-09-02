from pathlib import Path

from kirin_tor.workbench import Workbench
from kirin_tor.workspace import initialize


def test_relationship_graph_uses_formula_members_and_aggregates_documents(
    example_workspace: Path,
) -> None:
    graph = Workbench(example_workspace).execute("relationship_graph")

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["combo.total"]["label"] == "组合期望伤害"
    assert nodes["combo.total"]["kind"] == "output"
    assert nodes["combo.total"]["line"] is not None
    assert "完全虚构" not in nodes

    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("combo.crit", "combo.total") in edges
    assert ("skill_a.expected", "combo.total") in edges
    assert ("skill_b.expected", "combo.total") in edges

    document_edges = {
        (edge["source"], edge["target"]): edge["count"]
        for edge in graph["document_edges"]
    }
    assert document_edges[("skill_a", "combo")] == 1
    assert document_edges[("skill_b", "combo")] == 1

    documents = {document["id"]: document for document in graph["documents"]}
    assert documents["combo"]["label"] == "双技能组合（虚构）"
    assert documents["combo"]["has_chart"] is True


def test_relationship_graph_includes_process_scenario_and_analysis_dependencies(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "relationship-models")
    (root / "entries" / "bounded_models.kirin").write_text(
        """@kirin 2
@entry bounded_models

input proc_chance: probability = 1/4

output expected: dimensionless = expectation(proc_result)

distribution proc_result "触发结果": dimensionless:
  outcomes:
    - 0 @ 1 - proc_chance
    - 1 @ proc_chance

process proc_cycle "触发循环":
  state active: boolean = false
  event input step()
  on step():
    next active = true
  observe is_active: boolean = active

scenario one_step "一步场景":
  phases:
    - step
  use actor = proc_cycle:
  at 0 second phase step:
    send actor.step()
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1

analysis run_once "运行一次":
  using = one_step
  operation = run
""",
        encoding="utf-8",
    )

    graph = Workbench(root).execute("relationship_graph")
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["bounded_models.proc_result"]["kind"] == "distribution"
    assert nodes["bounded_models.proc_cycle"]["kind"] == "process"
    assert nodes["bounded_models.one_step"]["kind"] == "scenario"
    assert nodes["bounded_models.run_once"]["kind"] == "analysis"
    assert nodes["bounded_models.proc_result"]["line"] is not None

    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("bounded_models.proc_chance", "bounded_models.proc_result") in edges
    assert ("bounded_models.proc_result", "bounded_models.expected") in edges
    assert ("bounded_models.proc_cycle", "bounded_models.one_step") in edges
    assert ("bounded_models.one_step", "bounded_models.run_once") in edges
