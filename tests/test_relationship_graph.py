from pathlib import Path

from kirin_tor.workbench import Workbench


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
