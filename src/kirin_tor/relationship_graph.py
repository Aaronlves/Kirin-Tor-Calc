"""Deterministic dependency projections derived from validated Kirin Tor expressions."""

from __future__ import annotations

import ast
from collections import Counter
from typing import Iterable, Optional

from .diagnostics import extract_author_title
from .kirin_v2 import normalize_expression
from .schema import Entry
from .workspace import Workspace


_BUILTINS = {
    "abs", "ceil", "condition", "expectation", "floor", "if_else",
    "independent_sum", "interpolate", "lookup", "map", "max", "min",
    "piecewise", "probability", "product", "repeat_sum", "sqrt", "sum",
    "true", "false", "variance",
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
    if name in entry.outputs:
        return "output"
    if name in entry.objects:
        return "object"
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
    normalized = normalize_expression(
        " ".join(line.strip() for line in expression.splitlines()),
        workspace.units.units,
    )
    tree = ast.parse(normalized, mode="eval")
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

    attribute_bases = {
        id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }

    def attribute_segments(node: ast.Attribute) -> tuple[str, ...]:
        segments: list[str] = []
        candidate: ast.AST = node
        while isinstance(candidate, ast.Attribute):
            segments.append(candidate.attr)
            candidate = candidate.value
        if not isinstance(candidate, ast.Name):
            return ()
        segments.append(candidate.id)
        return tuple(reversed(segments))

    def canonical_path(parts: tuple[str, ...]) -> Optional[str]:
        if not parts:
            return None
        if parts[0] in workspace.entries:
            owner = workspace.entries[parts[0]]
            if len(parts) >= 2 and parts[1] in owner.objects:
                return f"{owner.id}.{parts[1]}"
            if len(parts) == 2 and _member_kind(owner, parts[1]):
                return ".".join(parts)
            return None
        if parts[0] in entry.objects:
            return f"{entry.id}.{parts[0]}"
        if len(parts) == 1:
            return _qualified_reference(workspace, entry, parts[0])
        return None
    result: set[str] = set()
    for node in ast.walk(tree):
        reference: Optional[str] = None
        if isinstance(node, ast.Attribute) and id(node) not in attribute_bases:
            reference = canonical_path(attribute_segments(node))
        elif (
            isinstance(node, ast.Name)
            and id(node) not in attribute_bases
            and id(node) not in ignored_name_nodes
        ):
            if node.id in bound or node.id in _BUILTINS or node.id in workspace.units.units:
                continue
            reference = canonical_path((node.id,))
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
    elif kind == "object":
        expression = "; ".join(
            f"{key} = {value}" for key, value in metadata.values.items()
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
            ("object", entry.objects),
            ("output", entry.outputs),
            ("process", entry.processes),
            ("scenario", entry.scenarios),
            ("analysis", entry.analyses),
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
        for name, obj in entry.objects.items():
            def object_expressions(values):
                for value in values.values():
                    if isinstance(value, dict):
                        yield from object_expressions(value)
                    elif isinstance(value, str):
                        yield value

            formulae.extend(
                (f"{entry.id}.{name}", expression, ())
                for expression in object_expressions(obj.values)
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
        for scenario in entry.scenarios.values():
            for instance in scenario.instances:
                edges.append(
                    {
                        "id": f"{instance.process.qualified_id}->{scenario.qualified_id}",
                        "source": instance.process.qualified_id,
                        "target": scenario.qualified_id,
                        "kind": "uses",
                    }
                )
        for analysis in entry.analyses.values():
            edges.append(
                {
                    "id": f"{analysis.scenario_id}->{analysis.qualified_id}",
                    "source": analysis.scenario_id,
                    "target": analysis.qualified_id,
                    "kind": "analyzes",
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
