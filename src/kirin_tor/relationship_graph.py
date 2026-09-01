"""Deterministic dependency projections derived from validated Kirin expressions."""

from __future__ import annotations

import ast
from collections import Counter
from typing import Iterable, Optional

from .diagnostics import extract_author_title
from .schema import Entry
from .workspace import Workspace


_BUILTINS = {
    "abs", "ceil", "condition", "expectation", "expected_steps", "floor",
    "hitting_probability", "if_else", "independent_sum", "interpolate", "lookup",
    "map", "max", "min", "piecewise", "probability", "product", "repeat_sum",
    "sqrt", "steady_probability", "steady_reward", "sum", "true", "false", "variance",
}


def _member_kind(entry: Entry, name: str) -> Optional[str]:
    if name in entry.inputs:
        return "input"
    if name in entry.fields:
        return "field"
    if name in entry.functions:
        return "function"
    if name in entry.tables:
        return "table"
    if name in entry.distributions:
        return "distribution"
    if name in entry.recurrences:
        return "recurrence"
    if name in entry.state_models:
        return "state_model"
    if name in entry.outputs:
        return "output"
    return None


def _qualified_reference(workspace: Workspace, entry: Entry, name: str) -> Optional[str]:
    if _member_kind(entry, name):
        return f"{entry.id}.{name}"
    if name in entry.aliases:
        return entry.aliases[name]
    matches = [
        f"{candidate.id}.{name}"
        for candidate in workspace.entries.values()
        if name in candidate.inputs
    ]
    return matches[0] if len(matches) == 1 else None


def _expression_references(
    workspace: Workspace,
    entry: Entry,
    expression: str,
    *,
    local_names: Iterable[str] = (),
) -> set[str]:
    """Return direct semantic member references from one already validated expression."""
    tree = ast.parse(" ".join(line.strip() for line in expression.splitlines()), mode="eval")
    bound = set(local_names)
    ignored_name_nodes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if (
            node.func.id in {"sum", "product", "map", "condition"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Name)
        ):
            bound.add(node.args[1].id)
        if node.func.id in {
            "steady_probability", "steady_reward", "hitting_probability", "expected_steps"
        }:
            ignored_name_nodes.update(
                id(argument) for argument in node.args[1:] if isinstance(argument, ast.Name)
            )

    attribute_bases = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }
    result: set[str] = set()
    for node in ast.walk(tree):
        reference: Optional[str] = None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            reference = f"{node.value.id}.{node.attr}"
        elif (
            isinstance(node, ast.Name)
            and id(node) not in attribute_bases
            and id(node) not in ignored_name_nodes
        ):
            if node.id in bound or node.id in _BUILTINS or node.id in workspace.units.units:
                continue
            reference = _qualified_reference(workspace, entry, node.id)
        if reference is None or "." not in reference:
            continue
        owner_id, member = reference.split(".", 1)
        owner = workspace.entries.get(owner_id)
        if owner is not None and _member_kind(owner, member):
            result.add(reference)
    return result


def _node(entry: Entry, name: str, kind: str, metadata: object) -> dict:
    qualified = f"{entry.id}.{name}"
    position = entry.positions.get(f"{kind}s.{name}") or entry.positions.get(
        f"{kind}s.{name}.expression"
    )
    if kind == "table":
        position = entry.positions.get(f"tables.{name}")
    location = getattr(metadata, "location", None)
    if location is not None and location.line is not None:
        position = (location.line, location.column or 1)
    label = metadata.get("label") if isinstance(metadata, dict) else getattr(metadata, "label", None)
    unit = metadata.get("unit") if isinstance(metadata, dict) else getattr(metadata, "unit_name", None)
    expression = metadata.get("expression") if isinstance(metadata, dict) else None
    if kind == "input":
        spec = entry.inputs[name]
        label = spec.label
        unit = spec.unit_name
    elif kind == "distribution":
        expression = "; ".join(
            f"{outcome.value} @ {outcome.probability}" for outcome in metadata.outcomes
        )
    elif kind == "recurrence":
        expression = (
            f"initial = {metadata.initial}; steps = {metadata.steps}; "
            f"next({metadata.current_name}, {metadata.index_name}) = {metadata.next_expression}"
        )
    elif kind == "state_model":
        expression = "; ".join(
            f"{transition.source} -> {transition.target} @ {transition.probability}"
            for transition in metadata.transitions
        )
    return {
        "id": qualified,
        "label": label or name,
        "kind": kind,
        "document_id": entry.id,
        "path": str(entry.path),
        "line": position[0] if position else None,
        "column": position[1] if position else None,
        "unit": unit,
        "expression": expression,
        "read_only": entry.read_only,
    }


def build_relationship_graph(workspace: Workspace) -> dict:
    """Build member-level and document-level projections from validated authority."""
    nodes: list[dict] = []
    edges: list[dict] = []
    documents: list[dict] = []

    for entry in sorted(workspace.entries.values(), key=lambda item: item.id):
        documents.append(
            {
                "id": entry.id,
                "label": extract_author_title(entry.raw_text, entry.name),
                "path": str(entry.path),
                "read_only": entry.read_only,
                "has_chart": entry.has_chart,
                "package": (
                    {
                        "name": entry.package_origin.name,
                        "version": entry.package_origin.version,
                        "source": entry.package_origin.source,
                    }
                    if entry.package_origin
                    else None
                ),
            }
        )
        collections = (
            ("input", entry.inputs),
            ("field", entry.fields),
            ("function", entry.functions),
            ("table", entry.tables),
            ("distribution", entry.distributions),
            ("recurrence", entry.recurrences),
            ("state_model", entry.state_models),
            ("output", entry.outputs),
        )
        for kind, collection in collections:
            for name in sorted(collection):
                metadata = collection[name]
                nodes.append(_node(entry, name, kind, metadata))

        formulae = [
            (f"{entry.id}.{name}", data["expression"], ())
            for name, data in entry.fields.items()
            if data.get("kind") == "expression"
        ]
        formulae.extend(
            (f"{entry.id}.{name}", data["expression"], tuple(data.get("parameters", {})))
            for name, data in entry.functions.items()
        )
        formulae.extend(
            (f"{entry.id}.{name}", data["expression"], ())
            for name, data in entry.outputs.items()
        )
        for name, distribution in entry.distributions.items():
            formulae.extend(
                (f"{entry.id}.{name}", expression, ())
                for outcome in distribution.outcomes
                for expression in (outcome.value, outcome.probability)
            )
        formulae.extend(
            (
                f"{entry.id}.{name}",
                expression,
                (recurrence.current_name, recurrence.index_name),
            )
            for name, recurrence in entry.recurrences.items()
            for expression in (
                recurrence.initial,
                recurrence.steps,
                recurrence.next_expression,
            )
        )
        for name, model in entry.state_models.items():
            formulae.extend(
                (f"{entry.id}.{name}", transition.probability, ())
                for transition in model.transitions
            )
            formulae.extend(
                (f"{entry.id}.{name}", expression, ())
                for reward in model.rewards.values()
                for expression in reward.values.values()
            )
        for target, expression, local_names in formulae:
            for source in sorted(
                _expression_references(
                    workspace, entry, expression, local_names=local_names
                )
            ):
                edges.append(
                    {
                        "id": f"{source}->{target}",
                        "source": source,
                        "target": target,
                        "kind": "formula",
                    }
                )

    edges = [
        edge
        for (_source, _target), edge in sorted(
            {
                (edge["source"], edge["target"]): edge
                for edge in edges
                if edge["source"] != edge["target"]
            }.items()
        )
    ]

    document_counts: Counter[tuple[str, str]] = Counter()
    for edge in edges:
        source_document = edge["source"].split(".", 1)[0]
        target_document = edge["target"].split(".", 1)[0]
        if source_document != target_document:
            document_counts[(source_document, target_document)] += 1
    document_edges = [
        {
            "id": f"{source}->{target}",
            "source": source,
            "target": target,
            "kind": "formula",
            "count": count,
        }
        for (source, target), count in sorted(document_counts.items())
    ]
    return {
        "status": "ok",
        "operation": "relationship_graph",
        "nodes": nodes,
        "edges": edges,
        "documents": documents,
        "document_edges": document_edges,
    }
