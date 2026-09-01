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


def test_relationship_graph_includes_bounded_model_members_and_dependencies(
    tmp_path: Path,
) -> None:
    root = initialize(tmp_path / "relationship-models")
    (root / "entries" / "bounded_models.kirin").write_text(
        """@kirin 1
@entry bounded_models

inputs:
  proc_chance: probability = 1/4
  failures: nonnegative_integer = 2 in 0..5

distributions:
  proc_result "触发结果": dimensionless:
    0 @ 1 - proc_chance
    1 @ proc_chance

recurrences:
  protected_chance "失败保护": dimensionless:
    initial = proc_chance
    steps = failures
    next(current, index) = min(current + proc_chance, 1)

state_models:
  proc_cycle "触发循环":
    states:
      ready
      cooldown
    transitions:
      ready -> ready @ 1 - proc_chance
      ready -> cooldown @ proc_chance
      cooldown -> ready @ 1
    rewards:
      active "激活收益": dimensionless:
        ready = proc_chance
        cooldown = 0

outputs:
  combined: dimensionless = expectation(proc_result) + protected_chance + steady_reward(proc_cycle, active)
""",
        encoding="utf-8",
    )

    graph = Workbench(root).execute("relationship_graph")
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["bounded_models.proc_result"]["kind"] == "distribution"
    assert nodes["bounded_models.protected_chance"]["kind"] == "recurrence"
    assert nodes["bounded_models.proc_cycle"]["kind"] == "state_model"
    assert nodes["bounded_models.proc_result"]["line"] is not None

    edges = {(edge["source"], edge["target"]) for edge in graph["edges"]}
    assert ("bounded_models.proc_chance", "bounded_models.proc_result") in edges
    assert ("bounded_models.proc_chance", "bounded_models.protected_chance") in edges
    assert ("bounded_models.failures", "bounded_models.protected_chance") in edges
    assert ("bounded_models.proc_chance", "bounded_models.proc_cycle") in edges
    assert ("bounded_models.proc_result", "bounded_models.combined") in edges
    assert ("bounded_models.protected_chance", "bounded_models.combined") in edges
    assert ("bounded_models.proc_cycle", "bounded_models.combined") in edges
