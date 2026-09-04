"""Revision-bound, paginated public model catalog for sandboxed Plugins."""

from __future__ import annotations

import base64
import hashlib
import json
from collections import Counter, deque
from dataclasses import fields, is_dataclass
from enum import Enum
from fractions import Fraction
from typing import Any, Iterable, Mapping, Optional

from .errors import (
    InvalidRequestError,
    LimitExceededError,
    StaleRevisionError,
    UnknownIdentityError,
    UnsupportedCapabilityError,
)
from .limits import (
    DEFAULT_MODEL_QUERY_LIMIT,
    MAX_CATALOG_SUMMARY_INTERFACES,
    MAX_MODEL_CURSOR_CHARS,
    MAX_MODEL_DEPENDENCY_DEPTH,
    MAX_MODEL_QUERY_LIMIT,
    MAX_PLUGIN_IDENTITY_CHARS,
)
from .plugin_protocol import plugin_protocol_descriptor
from .process_ir import ProcessMemberRefIR, SymbolRefIR, TypedExpressionIR
from .relationship_graph import build_relationship_graph
from .schema import Document, Entry, InputSpec
from .workspace import Workspace


MODEL_DESCRIPTOR_KINDS = (
    "analysis", "analysis_chart", "dimension", "distribution", "domain", "entry",
    "field", "function", "group", "input", "object", "object_field", "output",
    "preset", "process", "process_action", "process_event", "process_input",
    "process_observe", "process_state", "scenario", "scenario_decision",
    "scenario_instance", "scenario_measure", "scenario_objective", "scenario_policy",
    "scenario_variant", "source", "static_chart", "table", "type", "type_field", "unit",
)


def model_revision(workspace: Workspace) -> str:
    identity = [
        {
            "id": document.id,
            "sha256": document.sha256,
            "scope": "package" if document.package_origin else "workspace",
            "package_content_sha256": (
                document.package_origin.content_sha256 if document.package_origin else None
            ),
        }
        for document in sorted(workspace.documents.values(), key=lambda item: item.id)
    ]
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, TypedExpressionIR):
        return value.source
    if isinstance(value, ProcessMemberRefIR):
        return f"{value.process_id}.{value.member_id}"
    if isinstance(value, SymbolRefIR):
        return f"{value.owner_id}.{value.id}"
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_json_value(item) for item in sorted(value, key=str)]
    if is_dataclass(value):
        return {
            definition.name: _json_value(getattr(value, definition.name))
            for definition in fields(value)
            if definition.name not in {"location", "node", "process"}
        }
    return str(value)


def _references(value: Any) -> set[str]:
    result: set[str] = set()

    def visit(candidate: Any) -> None:
        if isinstance(candidate, SymbolRefIR):
            result.add(f"{candidate.owner_id}.{candidate.id}")
        elif isinstance(candidate, ProcessMemberRefIR):
            result.add(f"{candidate.process_id}.{candidate.member_id}")
        elif isinstance(candidate, TypedExpressionIR):
            for reference in candidate.references:
                visit(reference)
        elif isinstance(candidate, Mapping):
            for item in candidate.values():
                visit(item)
        elif isinstance(candidate, (tuple, list)):
            for item in candidate:
                visit(item)
        elif is_dataclass(candidate):
            for definition in fields(candidate):
                if definition.name not in {"location", "node", "process"}:
                    visit(getattr(candidate, definition.name))

    visit(value)
    return result


def _input_contract(spec: InputSpec) -> dict:
    return {
        "value_type": spec.value_type,
        "unit": spec.unit_name,
        "domain": spec.domain_name,
        "integer": spec.integer,
    }


def _origin(document: Document) -> dict:
    package = document.package_origin
    if package is None:
        return {"scope": "workspace", "document_sha256": document.sha256}
    local_source = package.source.startswith("path:")
    return {
        "scope": "package",
        "package": package.name,
        "version": package.version,
        "source": "path:<redacted>" if local_source else package.source,
        "resolved": None if local_source else package.resolved,
        "content_sha256": package.content_sha256,
    }


class ModelCatalog:
    """Immutable public projection of one already validated Workspace revision."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.revision = model_revision(workspace)
        self.interfaces = self._interfaces()
        self.descriptors = tuple(self._build_descriptors())
        self._by_id: dict[str, list[dict]] = {}
        for descriptor in self.descriptors:
            self._by_id.setdefault(descriptor["id"], []).append(descriptor)

    def _interfaces(self) -> list[dict]:
        resolution = self.workspace.package_resolution
        if resolution is None:
            return []
        result = []
        for package in sorted(resolution.packages, key=lambda item: item.source):
            for interface in sorted(package.manifest.interfaces, key=lambda item: item.id):
                local_source = package.source.startswith("path:")
                result.append({
                    "id": interface.id,
                    "revision": interface.revision,
                    "documents": list(interface.documents),
                    "document_prefixes": list(interface.document_prefixes),
                    "provider": {
                        "package": package.manifest.name,
                        "version": package.manifest.version,
                        "source": "path:<redacted>" if local_source else package.source,
                        "resolved": None if local_source else package.resolved,
                        "content_sha256": package.content_sha256,
                    },
                })
        return result

    def _document_interfaces(self, document: Document) -> list[dict]:
        if document.package_origin is None:
            return []
        return [
            {"id": interface["id"], "revision": interface["revision"]}
            for interface in self.interfaces
            if interface["provider"]["content_sha256"] == document.package_origin.content_sha256
            and (
                document.id in interface["documents"]
                or any(document.id.startswith(prefix) for prefix in interface["document_prefixes"])
            )
        ]

    @staticmethod
    def _source_location(document: Document, location, field_name: Optional[str]) -> dict:
        candidate = location or document.location(field_name)
        return {
            "document": document.id,
            "line": candidate.line,
            "column": candidate.column,
        }

    def _build_descriptors(self) -> list[dict]:
        graph = build_relationship_graph(self.workspace)
        graph_dependencies: dict[str, set[str]] = {}
        for edge in graph["edges"]:
            graph_dependencies.setdefault(edge["target"], set()).add(edge["source"])
        result: list[dict] = []

        def add(
            document: Entry,
            descriptor_id: str,
            kind: str,
            *,
            owner_id: Optional[str] = None,
            label: Optional[str] = None,
            contract: Optional[dict] = None,
            payload: Optional[dict] = None,
            location=None,
            field_name: Optional[str] = None,
            extra_dependencies: Iterable[str] = (),
        ) -> None:
            result.append({
                "id": descriptor_id,
                "kind": kind,
                "owner_id": owner_id,
                "label": label or descriptor_id.rsplit(".", 1)[-1],
                "contract": contract or {},
                "dependencies": sorted(
                    graph_dependencies.get(descriptor_id, set()) | set(extra_dependencies)
                ),
                "interfaces": self._document_interfaces(document),
                "origin": _origin(document),
                "source_location": self._source_location(document, location, field_name),
                "payload": _json_value(payload or {}),
            })

        for entry in sorted(self.workspace.entries.values(), key=lambda item: item.id):
            add(
                entry,
                entry.id,
                "entry",
                label=entry.name,
                payload={
                    "name": entry.name,
                    "game_version": entry.game_version,
                    "validation_status": entry.validation_status,
                    "description": entry.raw.get("description"),
                },
                field_name="id",
            )
            semantics = entry.raw.get("semantics", {})
            for section, kind in {
                "dimensions": "dimension", "units": "unit", "domains": "domain"
            }.items():
                values = semantics.get(section, {}) if isinstance(semantics, dict) else {}
                for name, value in sorted(values.items()):
                    metadata = value if isinstance(value, dict) else {}
                    add(
                        entry,
                        name,
                        kind,
                        owner_id=entry.id,
                        label=metadata.get("label", metadata.get("name", name)),
                        payload=metadata,
                        field_name=f"semantics.{section}.{name}",
                    )
            for name, spec in sorted(entry.structure_types.items()):
                qualified = spec.qualified_id
                add(
                    entry, qualified, "type", owner_id=entry.id, label=spec.label,
                    payload={"fields": sorted(spec.fields)}, location=spec.location,
                )
                for field_id, field_spec in sorted(spec.fields.items()):
                    add(
                        entry,
                        f"{qualified}.{field_id}",
                        "type_field",
                        owner_id=qualified,
                        label=field_spec.label or field_id,
                        contract={"type": field_spec.type_name, "optional": field_spec.optional},
                        payload={"default": field_spec.default},
                        location=field_spec.location,
                    )
            for name, spec in sorted(entry.objects.items()):
                qualified = spec.qualified_id
                add(
                    entry, qualified, "object", owner_id=entry.id, label=spec.label,
                    contract={"type": spec.type_name}, payload={"fields": sorted(spec.values)},
                    location=spec.location,
                )

                def add_object_fields(values: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> None:
                    for field_id, value in sorted(values.items()):
                        path = (*prefix, field_id)
                        add(
                            entry,
                            f"{qualified}." + ".".join(path),
                            "object_field",
                            owner_id=qualified,
                            label=field_id,
                            payload={"field_path": list(path), "value": value},
                            location=spec.location,
                            extra_dependencies=_references(value),
                        )
                        if isinstance(value, Mapping):
                            add_object_fields(value, path)

                add_object_fields(spec.values)
            for name, spec in sorted(entry.inputs.items()):
                add(
                    entry,
                    f"{entry.id}.{name}",
                    "input",
                    owner_id=entry.id,
                    label=spec.label or name,
                    contract=_input_contract(spec),
                    payload={
                        "default": spec.default,
                        "minimum": spec.minimum,
                        "maximum": spec.maximum,
                        "allowed_values": spec.allowed_values,
                    },
                    location=spec.location,
                )
            for kind, collection in (
                ("field", entry.fields), ("function", entry.functions), ("output", entry.outputs)
            ):
                for name, value in sorted(collection.items()):
                    add(
                        entry,
                        f"{entry.id}.{name}",
                        kind,
                        owner_id=entry.id,
                        label=value.get("label", name),
                        contract={
                            key: value.get(key)
                            for key in ("value_type", "unit", "domain")
                            if value.get(key) is not None
                        },
                        payload={key: item for key, item in value.items() if key != "label"},
                        field_name=f"{kind}s.{name}",
                    )
            for name, table in sorted(entry.tables.items()):
                add(
                    entry, table.qualified_id, "table", owner_id=entry.id, label=table.label,
                    contract={"input_unit": table.input_unit, "output_unit": table.output_unit},
                    payload={"points": table.points}, location=table.location,
                )
            for name, distribution in sorted(entry.distributions.items()):
                add(
                    entry, distribution.qualified_id, "distribution", owner_id=entry.id,
                    label=distribution.label, contract={"unit": distribution.unit_name},
                    payload={"outcomes": distribution.outcomes}, location=distribution.location,
                )
            for name, group in sorted(entry.groups.items()):
                add(
                    entry, group.qualified_id, "group", owner_id=entry.id, label=group.label,
                    payload={"outputs": list(group.outputs)}, location=group.location,
                    extra_dependencies=(f"{entry.id}.{item}" for item in group.outputs),
                )
            for name, preset in sorted(entry.presets.items()):
                add(
                    entry, preset.qualified_id, "preset", owner_id=entry.id, label=preset.label,
                    payload={"values": preset.values}, location=preset.location,
                    extra_dependencies=preset.values,
                )
            for index, source in enumerate(entry.sources, start=1):
                add(
                    entry, f"{entry.id}.source.{index}", "source", owner_id=entry.id,
                    label=source.get("citation", f"Source {index}"), payload=source,
                    field_name=f"sources.{index - 1}",
                )
            for name, chart in sorted(entry.charts.items()):
                add(
                    entry, chart.qualified_id, "static_chart", owner_id=entry.id,
                    label=chart.label,
                    payload={
                        "x": chart.x, "range": [chart.range_start, chart.range_end],
                        "points": chart.points, "y": chart.y, "preset": chart.preset,
                    },
                    location=chart.location(), extra_dependencies=(chart.x, *chart.y),
                )
            for name, process in sorted(entry.processes.items()):
                add(
                    entry,
                    process.qualified_id,
                    "process",
                    owner_id=entry.id,
                    label=process.label or name,
                    payload={
                        "version": process.version,
                        "inputs": len(process.inputs),
                        "states": len(process.states),
                        "events": len(process.events),
                        "actions": len(process.actions),
                        "observations": len(process.observations),
                    },
                    location=process.location,
                    extra_dependencies=_references(process),
                )
                for kind, members in (
                    ("process_input", process.inputs),
                    ("process_state", process.states),
                    ("process_event", process.events),
                    ("process_action", process.actions),
                    ("process_observe", process.observations),
                ):
                    for member in members:
                        add(
                            entry,
                            f"{process.qualified_id}.{member.ref.member_id}",
                            kind,
                            owner_id=process.qualified_id,
                            label=getattr(member, "label", None) or member.ref.member_id,
                            payload=_json_value(member),
                            location=member.location,
                            extra_dependencies=_references(member),
                        )
            for name, scenario in sorted(entry.scenarios.items()):
                add(
                    entry,
                    scenario.qualified_id,
                    "scenario",
                    owner_id=entry.id,
                    label=scenario.label or name,
                    payload={
                        "version": scenario.version,
                        "bounds": scenario.bounds,
                        "phases": [phase.id for phase in scenario.phases],
                        "schedules": len(scenario.schedules),
                        "actions": len(scenario.actions),
                    },
                    location=scenario.location,
                    extra_dependencies=_references(scenario),
                )
                scenario_members = (
                    ("scenario_instance", "instance", scenario.instances),
                    ("scenario_variant", "variant", scenario.variants),
                    ("scenario_policy", "policy", scenario.policies),
                    (
                        "scenario_decision",
                        "decision",
                        (
                            *scenario.decisions,
                            *scenario.event_decisions,
                            *scenario.condition_decisions,
                            *scenario.continuous_decisions,
                        ),
                    ),
                    ("scenario_measure", "measure", scenario.measures),
                    ("scenario_objective", "objective", scenario.objectives),
                )
                for kind, segment, members in scenario_members:
                    for index, member in enumerate(members, start=1):
                        member_id = str(getattr(member, "id", None) or index)
                        extra = _references(member)
                        if kind == "scenario_instance":
                            extra.add(member.process.qualified_id)
                        add(
                            entry,
                            f"{scenario.qualified_id}.{segment}.{member_id}",
                            kind,
                            owner_id=scenario.qualified_id,
                            label=getattr(member, "label", None) or member_id,
                            payload=_json_value(member),
                            location=getattr(member, "location", None),
                            extra_dependencies=extra,
                        )
            for name, analysis in sorted(entry.analyses.items()):
                add(
                    entry,
                    analysis.qualified_id,
                    "analysis",
                    owner_id=entry.id,
                    label=analysis.label or name,
                    payload={
                        "scenario": analysis.scenario_id,
                        "operation": analysis.operation,
                        "policy_ids": analysis.policy_ids,
                        "objective_ids": analysis.objective_ids,
                        "variant_ids": analysis.variant_ids,
                        "search_method": analysis.search_method,
                    },
                    location=analysis.location,
                    extra_dependencies=(analysis.scenario_id,),
                )
                for chart in analysis.charts:
                    add(
                        entry,
                        f"{analysis.qualified_id}.{chart.id}",
                        "analysis_chart",
                        owner_id=analysis.qualified_id,
                        label=chart.label or chart.id,
                        payload=_json_value(chart),
                        location=chart.location,
                        extra_dependencies=_references(chart),
                    )
        return sorted(result, key=lambda item: (item["id"], item["kind"]))

    def summary(self) -> dict:
        counts = Counter(item["kind"] for item in self.descriptors)
        visible_interfaces = [
            {
                "id": item["id"],
                "revision": item["revision"],
                "provider": {
                    key: item["provider"][key]
                    for key in ("package", "version", "content_sha256")
                },
            }
            for item in self.interfaces[:MAX_CATALOG_SUMMARY_INTERFACES]
        ]
        return {
            "status": "ok",
            "revision": self.revision,
            "counts": {kind: counts.get(kind, 0) for kind in MODEL_DESCRIPTOR_KINDS},
            "descriptor_count": len(self.descriptors),
            "descriptor_kinds": list(MODEL_DESCRIPTOR_KINDS),
            "interfaces": visible_interfaces,
            "interface_count": len(self.interfaces),
            "interfaces_truncated": len(visible_interfaces) < len(self.interfaces),
        }

    def _require_revision(self, value: object) -> None:
        if not isinstance(value, str) or value != self.revision:
            raise StaleRevisionError(
                "model catalog revision changed; restart from the current context"
            )

    @staticmethod
    def _query_fingerprint(filters: dict) -> str:
        return hashlib.sha256(
            json.dumps(filters, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _encode_cursor(self, fingerprint: str, offset: int) -> str:
        raw = json.dumps(
            {"revision": self.revision, "query": fingerprint, "offset": offset},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def _decode_cursor(self, cursor: object, fingerprint: str) -> int:
        if not isinstance(cursor, str) or not cursor or len(cursor) > MAX_MODEL_CURSOR_CHARS:
            raise InvalidRequestError("model query cursor is invalid")
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise InvalidRequestError("model query cursor is invalid") from exc
        if (
            not isinstance(value, dict)
            or set(value) != {"revision", "query", "offset"}
            or value.get("revision") != self.revision
            or value.get("query") != fingerprint
            or not isinstance(value.get("offset"), int)
            or isinstance(value.get("offset"), bool)
            or value["offset"] < 0
        ):
            raise InvalidRequestError(
                "model query cursor does not match this revision and query"
            )
        return value["offset"]

    def query(self, payload: Mapping[str, object]) -> dict:
        self._require_revision(payload.get("revision"))
        raw_kinds = payload.get("kind", list(MODEL_DESCRIPTOR_KINDS))
        if isinstance(raw_kinds, str):
            raw_kinds = [raw_kinds]
        if (
            not isinstance(raw_kinds, list)
            or not raw_kinds
            or any(
                not isinstance(item, str) or item not in MODEL_DESCRIPTOR_KINDS
                for item in raw_kinds
            )
        ):
            raise InvalidRequestError(
                "model query kind must contain supported descriptor kinds"
            )
        kinds = sorted(set(raw_kinds))

        def optional_text(name: str) -> Optional[str]:
            value = payload.get(name)
            if value is None or value == "":
                return None
            if not isinstance(value, str) or len(value) > MAX_PLUGIN_IDENTITY_CHARS:
                raise InvalidRequestError(f"model query {name} is invalid")
            return value

        interface = optional_text("interface")
        interface_revision = payload.get("interface_revision")
        if interface_revision is not None and (
            not isinstance(interface_revision, int)
            or isinstance(interface_revision, bool)
            or interface_revision < 1
        ):
            raise InvalidRequestError(
                "model query interface_revision must be a positive integer"
            )
        owner = optional_text("owner")
        prefix = optional_text("prefix")
        limit = payload.get("limit", DEFAULT_MODEL_QUERY_LIMIT)
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > MAX_MODEL_QUERY_LIMIT
        ):
            raise LimitExceededError(
                f"model query limit must be from 1 to {MAX_MODEL_QUERY_LIMIT}"
            )
        filters = {
            "kind": kinds,
            "interface": interface,
            "interface_revision": interface_revision,
            "owner": owner,
            "prefix": prefix,
            "limit": limit,
        }
        fingerprint = self._query_fingerprint(filters)
        offset = (
            self._decode_cursor(payload["cursor"], fingerprint)
            if payload.get("cursor") is not None
            else 0
        )
        matches = [
            item
            for item in self.descriptors
            if item["kind"] in kinds
            and (owner is None or item["owner_id"] == owner)
            and (prefix is None or item["id"].startswith(prefix))
            and (
                interface is None
                or any(
                    candidate["id"] == interface
                    and (
                        interface_revision is None
                        or candidate["revision"] == interface_revision
                    )
                    for candidate in item["interfaces"]
                )
            )
        ]
        if offset > len(matches):
            raise InvalidRequestError("model query cursor offset is outside the result set")
        items = matches[offset : offset + limit]
        next_offset = offset + len(items)
        return {
            "status": "ok",
            "operation": "model.query",
            "revision": self.revision,
            "items": items,
            "count": len(items),
            "total": len(matches),
            "next_cursor": (
                self._encode_cursor(fingerprint, next_offset)
                if next_offset < len(matches)
                else None
            ),
        }

    def _select(self, payload: Mapping[str, object]) -> dict:
        self._require_revision(payload.get("revision"))
        descriptor_id = payload.get("id")
        kind = payload.get("kind")
        if not isinstance(descriptor_id, str) or not descriptor_id:
            raise InvalidRequestError("model descriptor id must be non-empty text")
        candidates = self._by_id.get(descriptor_id, [])
        if kind is not None:
            if not isinstance(kind, str) or kind not in MODEL_DESCRIPTOR_KINDS:
                raise InvalidRequestError("model descriptor kind is invalid")
            candidates = [item for item in candidates if item["kind"] == kind]
        if not candidates:
            raise UnknownIdentityError(f"unknown model descriptor: {descriptor_id}")
        if len(candidates) > 1:
            raise InvalidRequestError(
                f"model descriptor {descriptor_id!r} is ambiguous; supply kind"
            )
        return candidates[0]

    def get(self, payload: Mapping[str, object]) -> dict:
        return {
            "status": "ok",
            "operation": "model.get",
            "revision": self.revision,
            "descriptor": self._select(payload),
        }

    def dependencies(self, payload: Mapping[str, object]) -> dict:
        root = self._select(payload)
        depth = payload.get("depth", 1)
        if (
            not isinstance(depth, int)
            or isinstance(depth, bool)
            or depth < 1
            or depth > MAX_MODEL_DEPENDENCY_DEPTH
        ):
            raise LimitExceededError(
                f"model dependency depth must be from 1 to {MAX_MODEL_DEPENDENCY_DEPTH}"
            )
        nodes: dict[tuple[str, str], dict] = {(root["id"], root["kind"]): root}
        edges: set[tuple[str, str]] = set()
        pending = deque([(root, 0)])
        while pending:
            current, current_depth = pending.popleft()
            if current_depth >= depth:
                continue
            for dependency_id in current["dependencies"]:
                edges.add((dependency_id, current["id"]))
                for dependency in self._by_id.get(dependency_id, []):
                    key = (dependency["id"], dependency["kind"])
                    if key not in nodes:
                        nodes[key] = dependency
                        pending.append((dependency, current_depth + 1))
        return {
            "status": "ok",
            "operation": "model.dependencies",
            "revision": self.revision,
            "root": {"id": root["id"], "kind": root["kind"]},
            "depth": depth,
            "nodes": [nodes[key] for key in sorted(nodes)],
            "edges": [
                {"source": source, "target": target}
                for source, target in sorted(edges)
            ],
        }

    def document(self, payload: Mapping[str, object]) -> dict:
        self._require_revision(payload.get("revision"))
        document_id = payload.get("id")
        if not isinstance(document_id, str) or document_id not in self.workspace.documents:
            raise UnknownIdentityError(
                "model document id is not a validated canonical Entry"
            )
        items = [
            item
            for item in self.descriptors
            if item["source_location"]["document"] == document_id
        ]
        return {
            "status": "ok",
            "operation": "model.document",
            "revision": self.revision,
            "document": next(
                item
                for item in items
                if item["kind"] == "entry" and item["id"] == document_id
            ),
            "descriptors": items,
        }

    def capabilities(self, payload: Mapping[str, object]) -> dict:
        self._require_revision(payload.get("revision"))
        protocol = plugin_protocol_descriptor()
        return {
            "status": "ok",
            "operation": "model.capabilities",
            "revision": self.revision,
            "descriptor_kinds": list(MODEL_DESCRIPTOR_KINDS),
            "actions": protocol["actions"],
            "limits": protocol["limits"],
            "interfaces": self.summary()["interfaces"],
            "interface_count": len(self.interfaces),
            "interfaces_truncated": len(self.interfaces) > MAX_CATALOG_SUMMARY_INTERFACES,
        }

    def dispatch(self, action: str, payload: Optional[Mapping[str, object]]) -> dict:
        handler = {
            "model.query": self.query,
            "model.get": self.get,
            "model.dependencies": self.dependencies,
            "model.document": self.document,
            "model.capabilities": self.capabilities,
        }.get(action)
        if handler is None:
            raise UnsupportedCapabilityError(
                f"unknown model catalog action: {action}"
            )
        return handler(dict(payload or {}))
