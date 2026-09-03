"""Strict schema-v1 validation and game-neutral document types."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Tuple

from .errors import SchemaError, SourceLocation
from .limits import (
    MAX_ABS_DIMENSION_EXPONENT,
    MAX_DECIMAL_EXPONENT,
    MAX_DISTRIBUTION_OUTCOMES,
    MAX_DOMAIN_VALUES,
    MAX_ENTRY_ALIASES,
    MAX_MODEL_INPUTS,
    MAX_NUMERIC_LITERAL_LENGTH,
    MAX_STATIC_CHARTS_PER_ENTRY,
    MAX_STRUCTURE_FIELDS,
    MAX_STRUCTURE_DEPTH,
    MAX_STRUCTURE_TYPES,
    MAX_STRUCTURED_OBJECTS,
)
from .units import Dimension, DomainSpec, UnitRegistry

if TYPE_CHECKING:
    from .process_ast import ProcessAst
    from .process_ir import ProcessIR
    from .scenario_ast import AnalysisAst, ScenarioAst
    from .scenario_ir import AnalysisIR, ScenarioIR


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PARAMETER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")
QUALIFIED_MEMBER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
MEMBER_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$"
)
REFERENCE_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$"
)
NUMBER_TEXT_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|\d+/\d+)$")
DOCUMENT_TYPES = {"entry"}
DISPLAY_FORMATS = {"number", "integer", "percent", "coefficient_percent"}
EXPRESSION_RESERVED_NAMES = {
    "abs", "ceil", "condition", "expectation", "floor", "if_else",
    "independent_sum", "interpolate", "lookup", "map", "max", "min",
    "piecewise", "probability", "product", "repeat_sum", "sqrt", "sum",
    "variance",
}


def require_identifier(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value):
        raise SchemaError(f"{label} must match [A-Za-z_][A-Za-z0-9_]*", location)
    if value.startswith("__"):
        raise SchemaError(f"{label} may not start with '__'", location)
    return value


def require_parameter_name(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str) or not PARAMETER_RE.fullmatch(value):
        raise SchemaError(f"{label} must be NAME or ENTRY_ID.NAME", location)
    if any(part.startswith("__") for part in value.split(".")):
        raise SchemaError(f"{label} components may not start with '__'", location)
    return value


def require_alias_identifier(value: Any, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str) or not value.isidentifier():
        raise SchemaError("alias must be one Unicode identifier without spaces or punctuation", location)
    if value.startswith("__"):
        raise SchemaError("alias may not start with '__'", location)
    if value in EXPRESSION_RESERVED_NAMES:
        raise SchemaError(f"alias {value!r} is reserved by the expression language", location)
    return value


def require_qualified_member(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str) or not QUALIFIED_MEMBER_RE.fullmatch(value):
        raise SchemaError(f"{label} must be ENTRY_ID.MEMBER", location)
    if any(part.startswith("__") for part in value.split(".")):
        raise SchemaError(f"{label} components may not start with '__'", location)
    return value


def require_member_path(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str) or not MEMBER_PATH_RE.fullmatch(value):
        raise SchemaError(f"{label} must be a dotted member path", location)
    if any(part.startswith("__") for part in value.split(".")):
        raise SchemaError(f"{label} may not contain private path segments", location)
    return value


def require_reference_path(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str) or not REFERENCE_PATH_RE.fullmatch(value):
        raise SchemaError(f"{label} must be an identifier path", location)
    if any(part.startswith("__") for part in value.split(".")):
        raise SchemaError(f"{label} may not contain private path segments", location)
    if len(value.split(".")) > MAX_STRUCTURE_DEPTH + 2:
        raise SchemaError(
            f"{label} exceeds the maximum path depth {MAX_STRUCTURE_DEPTH + 2}",
            location,
        )
    return value


def require_display_label(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    value = require_text(value, label, location)
    if not value.strip():
        raise SchemaError(f"{label} may not be empty", location)
    return value


def require_mapping(value: Any, label: str, location: Optional[SourceLocation]) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SchemaError(f"{label} must be a mapping", location)
    if any(not isinstance(key, str) for key in value):
        raise SchemaError(f"{label} keys must be text", location)
    return value


def require_text(value: Any, label: str, location: Optional[SourceLocation]) -> str:
    if not isinstance(value, str):
        raise SchemaError(f"{label} must be text", location)
    return value


def number_text(value: Any, label: str, location: Optional[SourceLocation] = None) -> str:
    if isinstance(value, bool) or isinstance(value, float):
        raise SchemaError(
            f"{label} must be an integer or exact numeric text; binary floating-point values are rejected",
            location,
        )
    if isinstance(value, int):
        result = str(value)
        if len(result.lstrip("-")) > MAX_NUMERIC_LITERAL_LENGTH:
            raise SchemaError(
                f"{label} exceeds {MAX_NUMERIC_LITERAL_LENGTH} characters", location
            )
        return result
    if isinstance(value, str) and value.strip():
        result = value.strip()
        if len(result) > MAX_NUMERIC_LITERAL_LENGTH:
            raise SchemaError(
                f"{label} exceeds {MAX_NUMERIC_LITERAL_LENGTH} characters", location
            )
        if not NUMBER_TEXT_RE.fullmatch(result):
            raise SchemaError(f"{label} has invalid numeric syntax", location)
        if "e" in result.lower():
            exponent = int(result.lower().split("e", 1)[1])
            if abs(exponent) > MAX_DECIMAL_EXPONENT:
                raise SchemaError(
                    f"{label} exponent magnitude may not exceed {MAX_DECIMAL_EXPONENT}", location
                )
        return result
    raise SchemaError(f"{label} must be numeric text", location)


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], label: str, location) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise SchemaError(f"unknown {label} key(s): {', '.join(unknown)}", location)


@dataclass(frozen=True)
class InputSpec:
    name: str
    qualified_name: Optional[str]
    value_type: str
    domain_name: Optional[str]
    unit_name: str
    dimension: Dimension
    default: Optional[Any]
    minimum: Optional[str]
    maximum: Optional[str]
    integer: bool = False
    allowed_values: Tuple[Any, ...] = ()
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def key(self) -> str:
        return self.qualified_name or self.name


@dataclass(frozen=True)
class PackageOrigin:
    source: str
    name: str
    version: str
    namespace: str
    resolved: str
    content_sha256: str


@dataclass
class Document:
    id: str
    name: str
    type: str
    path: Path
    raw: Dict[str, Any]
    raw_text: str
    sha256: str
    positions: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    package_origin: Optional[PackageOrigin] = None

    @property
    def authority_id(self) -> str:
        if self.package_origin is None:
            return self.id
        return f"{self.package_origin.source}::{self.id}"

    @property
    def read_only(self) -> bool:
        return self.package_origin is not None

    def location(self, field_name: Optional[str] = None) -> SourceLocation:
        line = column = None
        if field_name:
            candidate = field_name
            while candidate:
                if candidate in self.positions:
                    line, column = self.positions[candidate]
                    break
                candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
        if line is None and "id" in self.positions:
            line, column = self.positions["id"]
        return SourceLocation(str(self.path), self.id, field_name, line, column)


@dataclass(frozen=True)
class StaticChart:
    id: str
    owner_id: str
    label: str
    x: str
    range_start: str
    range_end: str
    points: int
    y: Tuple[str, ...]
    preset: Optional[str] = None
    out: Optional[str] = None
    data_out: Optional[str] = None
    title: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    curve_labels: Dict[str, str] = field(default_factory=dict)
    path: Path = field(default=Path("."), compare=False)
    positions: Dict[str, Tuple[int, int]] = field(default_factory=dict, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"

    def location(self, field_name: Optional[str] = None) -> SourceLocation:
        candidate = f"charts.{self.id}"
        if field_name:
            candidate = f"{candidate}.{field_name}"
        line = column = None
        while candidate:
            if candidate in self.positions:
                line, column = self.positions[candidate]
                break
            candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
        return SourceLocation(str(self.path), self.owner_id, field_name, line, column)


@dataclass
class Entry(Document):
    game_version: Optional[str] = None
    validation_status: Optional[str] = None
    sources: List[Dict[str, Any]] = field(default_factory=list)
    semantics: Dict[str, Any] = field(default_factory=dict)
    aliases: Dict[str, str] = field(default_factory=dict)
    inputs: Dict[str, InputSpec] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    fields: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    functions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    tables: Dict[str, "LookupTable"] = field(default_factory=dict)
    distributions: Dict[str, "DistributionSpec"] = field(default_factory=dict)
    outputs: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    groups: Dict[str, "OutputGroup"] = field(default_factory=dict)
    presets: Dict[str, "Preset"] = field(default_factory=dict)
    structure_types: Dict[str, "StructureTypeSpec"] = field(default_factory=dict)
    objects: Dict[str, "StructuredObjectSpec"] = field(default_factory=dict)
    process_asts: Tuple["ProcessAst", ...] = ()
    processes: Dict[str, "ProcessIR"] = field(default_factory=dict)
    scenario_asts: Tuple["ScenarioAst", ...] = ()
    scenarios: Dict[str, "ScenarioIR"] = field(default_factory=dict)
    analysis_asts: Tuple["AnalysisAst", ...] = ()
    analyses: Dict[str, "AnalysisIR"] = field(default_factory=dict)
    charts: Dict[str, StaticChart] = field(default_factory=dict)
    # The first chart remains projected through these fields for compatibility
    # with callers that treated the Entry itself as its sole chart config.
    x: Optional[str] = None
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    points: Optional[int] = None
    y: List[str] = field(default_factory=list)
    preset: Optional[str] = None
    out: Optional[str] = None
    data_out: Optional[str] = None
    title: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    curve_labels: Dict[str, str] = field(default_factory=dict)

    @property
    def has_chart(self) -> bool:
        return bool(self.charts) or self.x is not None


@dataclass(frozen=True)
class OutputGroup:
    id: str
    owner_id: str
    label: str
    outputs: Tuple[str, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class Preset:
    id: str
    owner_id: str
    label: str
    values: Dict[str, Any]
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class LookupTable:
    id: str
    owner_id: str
    label: str
    input_unit: str
    input_dimension: Dimension
    output_unit: str
    output_dimension: Dimension
    points: Tuple[Tuple[str, str], ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class DistributionOutcomeSpec:
    value: str
    probability: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class DistributionSpec:
    id: str
    owner_id: str
    label: str
    unit_name: str
    dimension: Dimension
    outcomes: Tuple[DistributionOutcomeSpec, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class StructureFieldSpec:
    id: str
    type_name: str
    optional: bool = False
    default: Optional[Any] = None
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class StructureTypeSpec:
    id: str
    owner_id: str
    label: str
    fields: Dict[str, StructureFieldSpec]
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class StructuredObjectSpec:
    id: str
    owner_id: str
    type_name: str
    label: str
    values: Dict[str, Any]
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


def _location(path: Path, entry_id: Optional[str], positions, field_name: Optional[str] = None):
    line = column = None
    if field_name:
        candidate = field_name
        while candidate:
            if candidate in positions:
                line, column = positions[candidate]
                break
            candidate = candidate.rsplit(".", 1)[0] if "." in candidate else ""
    return SourceLocation(str(path), entry_id, field_name, line, column)


def build_semantic_registry(raw_documents: List[tuple[Dict[str, Any], str, str, Path, dict]]) -> UnitRegistry:
    registry = UnitRegistry()
    declarations = []
    for raw, _text, _digest, path, positions in raw_documents:
        if raw.get("type") != "entry" or "semantics" not in raw:
            continue
        entry_id = raw.get("id") if isinstance(raw.get("id"), str) else None
        location = _location(path, entry_id, positions, "semantics")
        semantics = require_mapping(raw["semantics"], "semantics", location)
        _reject_unknown(semantics, {"dimensions", "units", "domains"}, "semantics", location)
        declarations.append((entry_id, path, positions, semantics))

    for entry_id, path, positions, semantics in declarations:
        dimensions = require_mapping(
            semantics.get("dimensions", {}), "semantics.dimensions", _location(path, entry_id, positions, "semantics.dimensions")
        )
        for name, metadata in dimensions.items():
            loc = _location(path, entry_id, positions, f"semantics.dimensions.{name}")
            require_identifier(name, "dimension name", loc)
            metadata = {} if metadata is None else require_mapping(metadata, f"dimension {name}", loc)
            _reject_unknown(metadata, {"name", "description"}, "dimension", loc)
            for key in ("name", "description"):
                if key in metadata:
                    require_text(metadata[key], key, loc)
            registry.add_dimension(name, metadata, loc)

    for entry_id, path, positions, semantics in declarations:
        units = require_mapping(
            semantics.get("units", {}), "semantics.units", _location(path, entry_id, positions, "semantics.units")
        )
        for name, raw_spec in units.items():
            loc = _location(path, entry_id, positions, f"semantics.units.{name}")
            require_identifier(name, "unit name", loc)
            spec = require_mapping(raw_spec, f"unit {name}", loc)
            _reject_unknown(spec, {"dimensions", "scale", "description"}, "unit", loc)
            powers_raw = require_mapping(spec.get("dimensions"), "unit dimensions", loc)
            powers = {}
            for dimension_name, exponent in powers_raw.items():
                require_identifier(dimension_name, "dimension name", loc)
                text = number_text(exponent, "dimension exponent", loc)
                try:
                    powers[dimension_name] = Fraction(text)
                except (ValueError, ZeroDivisionError) as exc:
                    raise SchemaError("dimension exponents must be exact rational numbers", loc) from exc
                if abs(powers[dimension_name]) > MAX_ABS_DIMENSION_EXPONENT:
                    raise SchemaError(
                        f"absolute dimension exponent may not exceed {MAX_ABS_DIMENSION_EXPONENT}", loc
                    )
            scale_text = number_text(spec.get("scale", "1"), "unit scale", loc)
            try:
                scale = Fraction(scale_text)
            except (ValueError, ZeroDivisionError) as exc:
                raise SchemaError("unit scale must be an exact positive number", loc) from exc
            registry.add_unit(name, powers, scale, loc)

    for entry_id, path, positions, semantics in declarations:
        domains = require_mapping(
            semantics.get("domains", {}), "semantics.domains", _location(path, entry_id, positions, "semantics.domains")
        )
        for name, raw_spec in domains.items():
            loc = _location(path, entry_id, positions, f"semantics.domains.{name}")
            require_identifier(name, "domain name", loc)
            spec = require_mapping(raw_spec, f"domain {name}", loc)
            _reject_unknown(
                spec,
                {
                    "value_type", "unit", "min", "max", "integer",
                    "allowed_values", "description", "label", "value_labels",
                },
                "domain",
                loc,
            )
            value_type = spec.get("value_type", "number")
            if value_type not in {"number", "boolean", "symbolic"}:
                raise SchemaError(
                    "domain value_type must be number, boolean, or symbolic", loc
                )
            if "label" in spec:
                require_display_label(spec["label"], "domain label", loc)
            unit_name = spec.get("unit", "dimensionless")
            require_identifier(unit_name, "domain unit", loc)
            minimum = number_text(spec["min"], "domain min", loc) if "min" in spec else None
            maximum = number_text(spec["max"], "domain max", loc) if "max" in spec else None
            integer = spec.get("integer", False)
            if not isinstance(integer, bool):
                raise SchemaError("domain integer must be true or false", loc)
            allowed_raw = spec.get("allowed_values", [])
            if not isinstance(allowed_raw, list):
                raise SchemaError("domain allowed_values must be a list", loc)
            if len(allowed_raw) > MAX_DOMAIN_VALUES:
                raise SchemaError(
                    f"domain allowed_values exceeds {MAX_DOMAIN_VALUES} items", loc
                )
            if value_type == "symbolic":
                allowed = tuple(
                    require_identifier(item, "symbolic domain value", loc)
                    for item in allowed_raw
                )
            else:
                allowed = tuple(
                    item
                    if isinstance(item, bool)
                    else number_text(item, "allowed value", loc)
                    for item in allowed_raw
                )
            if value_type == "boolean" and (unit_name != "dimensionless" or minimum or maximum or integer):
                raise SchemaError("boolean domains cannot define units, numeric bounds, or integer", loc)
            if value_type == "boolean" and any(not isinstance(item, bool) for item in allowed):
                raise SchemaError("boolean domain allowed_values must contain only booleans", loc)
            if value_type == "number":
                try:
                    minimum_value = Fraction(minimum) if minimum is not None else None
                    maximum_value = Fraction(maximum) if maximum is not None else None
                    allowed_numbers = [Fraction(str(item)) for item in allowed]
                except (ValueError, ZeroDivisionError) as exc:
                    raise SchemaError("domain numeric constraints must be finite exact numbers", loc) from exc
                if minimum_value is not None and maximum_value is not None and minimum_value > maximum_value:
                    raise SchemaError("domain min must not exceed max", loc)
                for item in allowed_numbers:
                    if integer and item.denominator != 1:
                        raise SchemaError("integer domain allowed_values must be integers", loc)
                    if minimum_value is not None and item < minimum_value:
                        raise SchemaError("domain allowed_values contains a value below min", loc)
                    if maximum_value is not None and item > maximum_value:
                        raise SchemaError("domain allowed_values contains a value above max", loc)
            if value_type == "symbolic":
                if unit_name != "dimensionless" or minimum or maximum or integer:
                    raise SchemaError(
                        "symbolic domains cannot define units, numeric bounds, or integer",
                        loc,
                    )
                if not allowed:
                    raise SchemaError(
                        "symbolic domains require at least one allowed value", loc
                    )
                if len(set(allowed)) != len(allowed):
                    raise SchemaError(
                        "symbolic domain values must be unique", loc
                    )
                labels = require_mapping(
                    spec.get("value_labels", {}), "symbolic domain labels", loc
                )
                unknown_labels = sorted(set(labels) - set(allowed))
                if unknown_labels:
                    raise SchemaError(
                        "symbolic domain labels reference unknown value(s): "
                        + ", ".join(unknown_labels),
                        loc,
                    )
                for label in labels.values():
                    require_display_label(label, "symbolic domain value label", loc)
            elif "value_labels" in spec:
                raise SchemaError(
                    "value_labels is only valid for symbolic domains", loc
                )
            registry.add_domain(
                DomainSpec(name, value_type, unit_name, minimum, maximum, integer, allowed), loc
            )
    return registry


INPUT_KEYS = {
    "value_type", "domain", "unit", "default", "min", "max", "integer", "allowed_values",
    "description", "label",
}


def _parse_input(
    name: str,
    raw: Any,
    location: SourceLocation,
    registry: UnitRegistry,
    owner_id: Optional[str] = None,
) -> InputSpec:
    require_identifier(name, "input name", location)
    data = require_mapping(raw, f"input {name}", location)
    _reject_unknown(data, INPUT_KEYS, "input", location)
    display_label = None
    if "label" in data:
        display_label = require_display_label(data["label"], "input label", location)
    domain_name = data.get("domain")
    domain_shorthand = False
    if domain_name is None and data.get("unit") in registry.domains:
        domain_name = data.get("unit")
        domain_shorthand = True
    domain = None
    if domain_name is not None:
        require_identifier(domain_name, "domain", location)
        domain = registry.domains.get(domain_name)
        if domain is None:
            raise SchemaError(f"unknown domain {domain_name!r}", location)
    value_type = data.get("value_type", domain.value_type if domain else "number")
    if value_type not in {"number", "boolean"}:
        raise SchemaError("input value_type must be number or boolean", location)
    if domain and value_type != domain.value_type:
        raise SchemaError("input value_type conflicts with its domain", location)
    unit_name = (
        domain.unit_name
        if domain_shorthand
        else data.get("unit", domain.unit_name if domain else "dimensionless")
    )
    require_identifier(unit_name, "input unit", location)
    if domain and unit_name != domain.unit_name:
        raise SchemaError("input unit conflicts with its domain", location)
    dimension = registry.parse_unit(unit_name, location)
    minimum = domain.minimum if domain else None
    maximum = domain.maximum if domain else None
    integer = domain.integer if domain else False
    allowed = domain.allowed_values if domain else ()
    if "min" in data:
        requested_minimum = number_text(data["min"], "min", location)
        if domain and domain.minimum is not None and Fraction(requested_minimum) < Fraction(domain.minimum):
            raise SchemaError("input min may narrow but not widen its domain", location)
        minimum = requested_minimum
    if "max" in data:
        requested_maximum = number_text(data["max"], "max", location)
        if domain and domain.maximum is not None and Fraction(requested_maximum) > Fraction(domain.maximum):
            raise SchemaError("input max may narrow but not widen its domain", location)
        maximum = requested_maximum
    if "integer" in data:
        if not isinstance(data["integer"], bool):
            raise SchemaError("input integer must be true or false", location)
        if domain and domain.integer and not data["integer"]:
            raise SchemaError("input integer may not relax its domain", location)
        integer = data["integer"]
    if "allowed_values" in data:
        if not isinstance(data["allowed_values"], list):
            raise SchemaError("input allowed_values must be a list", location)
        if len(data["allowed_values"]) > MAX_DOMAIN_VALUES:
            raise SchemaError(
                f"input allowed_values exceeds {MAX_DOMAIN_VALUES} items", location
            )
        requested_allowed = tuple(
            item if isinstance(item, bool) else number_text(item, "allowed value", location)
            for item in data["allowed_values"]
        )
        if domain and domain.allowed_values:
            def semantic_value(item):
                return item if isinstance(item, bool) else Fraction(str(item))

            domain_values = {semantic_value(item) for item in domain.allowed_values}
            if any(semantic_value(item) not in domain_values for item in requested_allowed):
                raise SchemaError("input allowed_values may narrow but not widen its domain", location)
        allowed = requested_allowed
    default = data.get("default")
    if value_type == "boolean":
        if unit_name != "dimensionless" or minimum is not None or maximum is not None or integer:
            raise SchemaError("boolean inputs cannot define units, numeric bounds, or integer", location)
        if default is not None and not isinstance(default, bool):
            raise SchemaError("boolean input defaults must be true or false", location)
        if any(not isinstance(item, bool) for item in allowed):
            raise SchemaError("boolean allowed_values must contain only booleans", location)
    else:
        default = number_text(default, "default", location) if default is not None else None
        if any(isinstance(item, bool) for item in allowed):
            raise SchemaError("numeric allowed_values cannot contain booleans", location)
        try:
            minimum_value = Fraction(minimum) if minimum is not None else None
            maximum_value = Fraction(maximum) if maximum is not None else None
            allowed_numbers = [Fraction(str(item)) for item in allowed]
        except (ValueError, ZeroDivisionError) as exc:
            raise SchemaError("numeric constraints must be finite exact numbers", location) from exc
        if minimum_value is not None and maximum_value is not None and minimum_value > maximum_value:
            raise SchemaError("input min must not exceed max", location)
        for item in allowed_numbers:
            if integer and item.denominator != 1:
                raise SchemaError("integer input allowed_values must be integers", location)
            if minimum_value is not None and item < minimum_value:
                raise SchemaError("input allowed_values contains a value below min", location)
            if maximum_value is not None and item > maximum_value:
                raise SchemaError("input allowed_values contains a value above max", location)
    return InputSpec(
        name=name,
        qualified_name=f"{owner_id}.{name}" if owner_id else None,
        value_type=value_type,
        domain_name=domain_name,
        unit_name=unit_name,
        dimension=dimension,
        default=default,
        minimum=minimum,
        maximum=maximum,
        integer=integer,
        allowed_values=allowed,
        label=display_label,
        location=location,
    )


TOP_KEYS = {
    "schema_version", "source_version", "id", "name", "type", "description", "sources", "game_version",
    "validation_status", "semantics", "aliases", "inputs", "constraints", "fields", "functions", "tables",
    "distributions", "outputs",
    "groups", "presets", "x", "range", "points", "y", "preset", "out", "data_out",
    "title", "x_label", "y_label", "curve_labels", "charts", "types", "objects",
}


def parse_document(
    raw: Dict[str, Any],
    text: str,
    sha256: str,
    path: Path,
    registry: Optional[UnitRegistry] = None,
    positions: Optional[Dict[str, Tuple[int, int]]] = None,
    package_origin: Optional[PackageOrigin] = None,
    process_asts: Optional[Tuple["ProcessAst", ...]] = None,
    scenario_asts: Optional[Tuple["ScenarioAst", ...]] = None,
    analysis_asts: Optional[Tuple["AnalysisAst", ...]] = None,
) -> Document:
    registry = registry or UnitRegistry()
    positions = positions or {}
    root_location = _location(path, None, positions)
    require_mapping(raw, "document root", root_location)
    if raw.get("schema_version") != 1:
        raise SchemaError("schema_version must be 1", _location(path, None, positions, "schema_version"))
    doc_id = require_identifier(raw.get("id"), "id", _location(path, None, positions, "id"))
    name = require_text(raw.get("name"), "name", _location(path, doc_id, positions, "name"))
    doc_type = raw.get("type")
    if doc_type not in DOCUMENT_TYPES:
        raise SchemaError(
            f"type must be one of: {', '.join(sorted(DOCUMENT_TYPES))}",
            _location(path, doc_id, positions, "type"),
        )
    base = dict(
        id=doc_id,
        name=name,
        type=doc_type,
        path=path,
        raw=raw,
        raw_text=text,
        sha256=sha256,
        positions=positions,
        package_origin=package_origin,
    )

    if doc_type == "entry":
        _reject_unknown(raw, TOP_KEYS, "entry", root_location)
        for key in ("description", "game_version", "validation_status"):
            if key in raw:
                require_text(raw[key], key, _location(path, doc_id, positions, key))
        sources_raw = raw.get("sources", [])
        if not isinstance(sources_raw, list):
            raise SchemaError("sources must be a list", _location(path, doc_id, positions, "sources"))
        sources = []
        for index, source in enumerate(sources_raw):
            source_location = _location(path, doc_id, positions, f"sources.{index}")
            if isinstance(source, str):
                raise SchemaError(
                    "source must be a structured object with kind and citation",
                    source_location,
                )
            source = require_mapping(source, "source", source_location)
            _reject_unknown(
                source,
                {"kind", "citation", "location", "verified_at", "digest", "game_version"},
                "source",
                source_location,
            )
            kind = require_identifier(source.get("kind"), "source kind", source_location)
            citation = require_text(source.get("citation"), "source citation", source_location)
            if not citation.strip():
                raise SchemaError("source citation may not be empty", source_location)
            normalized_source = {"kind": kind, "citation": citation}
            for key in ("location", "verified_at", "digest", "game_version"):
                if key in source:
                    normalized_source[key] = require_text(
                        source[key], f"source {key}", source_location
                    )
            if "verified_at" in normalized_source and not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", normalized_source["verified_at"]
            ):
                raise SchemaError("source verified_at must use YYYY-MM-DD", source_location)
            if "digest" in normalized_source and not re.fullmatch(
                r"sha256:[0-9a-f]{64}", normalized_source["digest"]
            ):
                raise SchemaError(
                    "source digest must use sha256:<64 lowercase hex digits>",
                    source_location,
                )
            if (
                raw.get("game_version")
                and normalized_source.get("game_version")
                and normalized_source["game_version"] != raw["game_version"]
            ):
                raise SchemaError(
                    "source game_version must match the owning entry game version",
                    source_location,
                )
            sources.append(normalized_source)
        input_data = require_mapping(raw.get("inputs", {}), "inputs", _location(path, doc_id, positions, "inputs"))
        if len(input_data) > MAX_MODEL_INPUTS:
            raise SchemaError(f"an entry may define at most {MAX_MODEL_INPUTS} inputs", root_location)
        inputs = {
            key: _parse_input(
                key, value, _location(path, doc_id, positions, f"inputs.{key}"), registry, owner_id=doc_id
            )
            for key, value in input_data.items()
        }
        aliases_raw = require_mapping(
            raw.get("aliases", {}), "aliases", _location(path, doc_id, positions, "aliases")
        )
        if len(aliases_raw) > MAX_ENTRY_ALIASES:
            raise SchemaError(
                f"an entry may define at most {MAX_ENTRY_ALIASES} aliases",
                _location(path, doc_id, positions, "aliases"),
            )
        aliases = {}
        for alias, target in aliases_raw.items():
            alias_location = _location(path, doc_id, positions, f"aliases.{alias}")
            require_alias_identifier(alias, alias_location)
            aliases[alias] = require_member_path(target, "alias target", alias_location)

        types_raw = require_mapping(
            raw.get("types", {}), "types", _location(path, doc_id, positions, "types")
        )
        structure_types: Dict[str, StructureTypeSpec] = {}
        if len(types_raw) > MAX_STRUCTURE_TYPES:
            raise SchemaError(
                f"an entry may define at most {MAX_STRUCTURE_TYPES} structure types",
                _location(path, doc_id, positions, "types"),
            )
        for type_id, type_raw in types_raw.items():
            type_location = _location(path, doc_id, positions, f"types.{type_id}")
            require_identifier(type_id, "type id", type_location)
            type_raw = require_mapping(type_raw, f"types.{type_id}", type_location)
            _reject_unknown(type_raw, {"label", "fields"}, "type", type_location)
            fields_raw = require_mapping(
                type_raw.get("fields", {}), f"types.{type_id}.fields", type_location
            )
            if not fields_raw:
                raise SchemaError("type must declare at least one field", type_location)
            if len(fields_raw) > MAX_STRUCTURE_FIELDS:
                raise SchemaError(
                    f"type exceeds {MAX_STRUCTURE_FIELDS} fields", type_location
                )
            type_fields: Dict[str, StructureFieldSpec] = {}
            for field_id, field_raw in fields_raw.items():
                field_location = _location(
                    path, doc_id, positions, f"types.{type_id}.fields.{field_id}"
                )
                require_identifier(field_id, "type field id", field_location)
                field_raw = require_mapping(
                    field_raw, f"types.{type_id}.fields.{field_id}", field_location
                )
                _reject_unknown(
                    field_raw,
                    {"type", "optional", "default", "label"},
                    "type field",
                    field_location,
                )
                field_type = require_reference_path(
                    field_raw.get("type"), "type field type", field_location
                )
                optional = field_raw.get("optional", False)
                if not isinstance(optional, bool):
                    raise SchemaError("type field optional must be boolean", field_location)
                label = field_raw.get("label")
                if label is not None:
                    label = require_display_label(label, "type field label", field_location)
                type_fields[field_id] = StructureFieldSpec(
                    field_id,
                    field_type,
                    optional,
                    field_raw.get("default"),
                    label,
                    field_location,
                )
            structure_types[type_id] = StructureTypeSpec(
                type_id,
                doc_id,
                require_display_label(type_raw.get("label", type_id), "type label", type_location),
                type_fields,
                type_location,
            )

        objects_raw = require_mapping(
            raw.get("objects", {}), "objects", _location(path, doc_id, positions, "objects")
        )
        objects: Dict[str, StructuredObjectSpec] = {}
        if len(objects_raw) > MAX_STRUCTURED_OBJECTS:
            raise SchemaError(
                f"an entry may define at most {MAX_STRUCTURED_OBJECTS} structured objects",
                _location(path, doc_id, positions, "objects"),
            )
        for object_id, object_raw in objects_raw.items():
            object_location = _location(path, doc_id, positions, f"objects.{object_id}")
            require_identifier(object_id, "object id", object_location)
            object_raw = require_mapping(object_raw, f"objects.{object_id}", object_location)
            _reject_unknown(object_raw, {"type", "label", "values"}, "object", object_location)
            values = dict(
                require_mapping(
                    object_raw.get("values", {}),
                    f"objects.{object_id}.values",
                    object_location,
                )
            )

            def validate_object_values(candidate: Mapping[str, Any], prefix: str) -> None:
                for member, value in candidate.items():
                    require_identifier(member, "object field id", object_location)
                    if isinstance(value, Mapping):
                        validate_object_values(value, f"{prefix}.{member}")
                    elif not isinstance(value, (str, bool, int)) or isinstance(value, float):
                        raise SchemaError(
                            "object values must be exact expressions, booleans, or nested objects",
                            _location(path, doc_id, positions, f"{prefix}.{member}"),
                        )

            validate_object_values(values, f"objects.{object_id}.values")
            objects[object_id] = StructuredObjectSpec(
                object_id,
                doc_id,
                require_reference_path(object_raw.get("type"), "object type", object_location),
                require_display_label(
                    object_raw.get("label", object_id), "object label", object_location
                ),
                values,
                object_location,
            )

        fields = dict(require_mapping(raw.get("fields", {}), "fields", root_location))
        constraints_raw = raw.get("constraints", [])
        if not isinstance(constraints_raw, list) or not all(isinstance(item, str) for item in constraints_raw):
            raise SchemaError("constraints must be a list of boolean expressions", root_location)
        functions = dict(require_mapping(raw.get("functions", {}), "functions", root_location))
        tables_raw = require_mapping(raw.get("tables", {}), "tables", root_location)
        tables = {}
        for table_id, table_raw in tables_raw.items():
            table_location = _location(path, doc_id, positions, f"tables.{table_id}")
            require_identifier(table_id, "table id", table_location)
            table_raw = require_mapping(table_raw, f"tables.{table_id}", table_location)
            _reject_unknown(
                table_raw,
                {"label", "input_unit", "unit", "points"},
                "table",
                table_location,
            )
            label = require_display_label(
                table_raw.get("label", table_id), "table label", table_location
            )
            input_unit = require_identifier(
                table_raw.get("input_unit", "dimensionless"),
                "table input unit",
                table_location,
            )
            output_unit = require_identifier(
                table_raw.get("unit", "dimensionless"),
                "table output unit",
                table_location,
            )
            input_dimension = registry.parse_unit(input_unit, table_location)
            output_dimension = registry.parse_unit(output_unit, table_location)
            points_raw = table_raw.get("points", [])
            if (
                not isinstance(points_raw, list)
                or not points_raw
                or any(not isinstance(point, list) or len(point) != 2 for point in points_raw)
            ):
                raise SchemaError("table points must be a non-empty list of [x, y] pairs", table_location)
            points = []
            seen_x = set()
            previous_x = None
            for index, point in enumerate(points_raw):
                x = number_text(point[0], "table x", table_location)
                y = number_text(point[1], "table y", table_location)
                x_value = Fraction(x)
                if x_value in seen_x:
                    raise SchemaError("table x values must be unique", table_location)
                if previous_x is not None and x_value <= previous_x:
                    raise SchemaError("table x values must be strictly increasing", table_location)
                seen_x.add(x_value)
                previous_x = x_value
                points.append((x, y))
            tables[table_id] = LookupTable(
                table_id,
                doc_id,
                label,
                input_unit,
                input_dimension,
                output_unit,
                output_dimension,
                tuple(points),
                table_location,
            )
        outputs = dict(require_mapping(raw.get("outputs", {}), "outputs", root_location))
        occupied = set(inputs)
        for object_id in objects:
            if object_id in occupied:
                raise SchemaError(
                    f"duplicate member name {object_id!r}",
                    _location(path, doc_id, positions, f"objects.{object_id}"),
                )
            occupied.add(object_id)
        for table_id in tables:
            if table_id in occupied:
                raise SchemaError(
                    f"duplicate member name {table_id!r}",
                    _location(path, doc_id, positions, f"tables.{table_id}"),
                )
            occupied.add(table_id)
        distributions_raw = require_mapping(
            raw.get("distributions", {}),
            "distributions",
            _location(path, doc_id, positions, "distributions"),
        )
        distributions = {}
        for distribution_id, distribution_raw in distributions_raw.items():
            distribution_location = _location(
                path, doc_id, positions, f"distributions.{distribution_id}"
            )
            require_identifier(distribution_id, "distribution id", distribution_location)
            if distribution_id in occupied:
                raise SchemaError(
                    f"duplicate member name {distribution_id!r}", distribution_location
                )
            distribution_raw = require_mapping(
                distribution_raw,
                f"distributions.{distribution_id}",
                distribution_location,
            )
            _reject_unknown(
                distribution_raw,
                {"label", "unit", "outcomes"},
                "distribution",
                distribution_location,
            )
            label = require_display_label(
                distribution_raw.get("label", distribution_id),
                "distribution label",
                distribution_location,
            )
            unit_name = require_identifier(
                distribution_raw.get("unit", "dimensionless"),
                "distribution unit",
                distribution_location,
            )
            dimension = registry.parse_unit(unit_name, distribution_location)
            outcomes_raw = distribution_raw.get("outcomes", [])
            if not isinstance(outcomes_raw, list) or not outcomes_raw:
                raise SchemaError(
                    "distribution outcomes must be a non-empty list",
                    distribution_location,
                )
            if len(outcomes_raw) > MAX_DISTRIBUTION_OUTCOMES:
                raise SchemaError(
                    f"distribution exceeds {MAX_DISTRIBUTION_OUTCOMES} outcomes",
                    distribution_location,
                )
            outcomes = []
            for index, outcome_raw in enumerate(outcomes_raw):
                outcome_location = _location(
                    path,
                    doc_id,
                    positions,
                    f"distributions.{distribution_id}.outcomes.{index}",
                )
                outcome_raw = require_mapping(
                    outcome_raw, "distribution outcome", outcome_location
                )
                _reject_unknown(
                    outcome_raw,
                    {"value", "probability"},
                    "distribution outcome",
                    outcome_location,
                )
                value = require_text(
                    outcome_raw.get("value"), "distribution outcome value", outcome_location
                )
                probability = require_text(
                    outcome_raw.get("probability"),
                    "distribution outcome probability",
                    outcome_location,
                )
                if not value.strip() or not probability.strip():
                    raise SchemaError(
                        "distribution outcome value and probability may not be empty",
                        outcome_location,
                    )
                outcomes.append(
                    DistributionOutcomeSpec(value, probability, outcome_location)
                )
            distributions[distribution_id] = DistributionSpec(
                distribution_id,
                doc_id,
                label,
                unit_name,
                dimension,
                tuple(outcomes),
                distribution_location,
            )
            occupied.add(distribution_id)
        for section_name, section in (("fields", fields), ("functions", functions), ("outputs", outputs)):
            for member, value in section.items():
                member_location = _location(path, doc_id, positions, f"{section_name}.{member}")
                require_identifier(member, f"{section_name} name", member_location)
                if member in occupied:
                    raise SchemaError(f"duplicate member name {member!r}", member_location)
                occupied.add(member)
                data = require_mapping(value, f"{section_name}.{member}", member_location)
                if section_name == "fields":
                    kind = data.get("kind")
                    if kind not in {"value", "expression"}:
                        raise SchemaError("field kind must be value or expression", member_location)
                    if kind == "value":
                        _reject_unknown(data, {"kind", "value", "value_type", "unit", "description", "label"}, "value field", member_location)
                        if "value" not in data or "expression" in data:
                            raise SchemaError("value field requires value and may not define expression", member_location)
                        value_type = data.get("value_type", "number")
                        if value_type not in {"number", "boolean"}:
                            raise SchemaError("value field value_type must be number or boolean", member_location)
                        if value_type == "boolean":
                            if not isinstance(data["value"], bool):
                                raise SchemaError("boolean value fields require true or false", member_location)
                            if data.get("unit", "dimensionless") != "dimensionless":
                                raise SchemaError("boolean value fields must be dimensionless", member_location)
                        else:
                            number_text(data["value"], "field value", member_location)
                    elif kind == "expression":
                        _reject_unknown(data, {"kind", "expression", "unit", "description", "label"}, "expression field", member_location)
                        if "expression" not in data or "value" in data:
                            raise SchemaError("expression field requires expression and may not define value", member_location)
                        require_text(data["expression"], "expression", member_location)
                    if "label" in data:
                        require_display_label(data["label"], "field label", member_location)
                    unit_name = data.get("unit", "dimensionless")
                    require_identifier(unit_name, "unit", member_location)
                    registry.parse_unit(unit_name, member_location)
                elif section_name == "functions":
                    _reject_unknown(data, {"parameters", "expression", "unit", "description", "label"}, "function", member_location)
                    if "label" in data:
                        require_display_label(data["label"], "function label", member_location)
                    require_text(data.get("expression"), "function expression", member_location)
                    params = require_mapping(data.get("parameters", {}), "function parameters", member_location)
                    if len(params) > MAX_MODEL_INPUTS:
                        raise SchemaError(
                            f"a function may define at most {MAX_MODEL_INPUTS} parameters",
                            member_location,
                        )
                    for param, spec in params.items():
                        parsed = _parse_input(
                            param, spec, _location(path, doc_id, positions, f"functions.{member}.parameters.{param}"), registry
                        )
                        if parsed.default is not None:
                            raise SchemaError("explicit function parameters may not define defaults", parsed.location)
                    registry.parse_unit(data.get("unit", "dimensionless"), member_location)
                else:
                    _reject_unknown(
                        data,
                        {"expression", "unit", "description", "label", "display", "digits"},
                        "output",
                        member_location,
                    )
                    if "label" in data:
                        require_display_label(data["label"], "output label", member_location)
                    require_text(data.get("expression"), "output expression", member_location)
                    registry.parse_unit(data.get("unit", "dimensionless"), member_location)
                    display = data.get("display", "number")
                    if display not in DISPLAY_FORMATS:
                        raise SchemaError(
                            "output display must be one of: "
                            + ", ".join(sorted(DISPLAY_FORMATS)),
                            member_location,
                        )
                    digits = data.get("digits")
                    if digits is not None and (
                        isinstance(digits, bool) or not isinstance(digits, int) or digits < 0 or digits > 15
                    ):
                        raise SchemaError("output digits must be an integer from 0 to 15", member_location)
        for alias in aliases:
            if alias in occupied:
                raise SchemaError(
                    f"alias {alias!r} conflicts with a declared member",
                    _location(path, doc_id, positions, f"aliases.{alias}"),
                )
        groups_raw = require_mapping(raw.get("groups", {}), "groups", root_location)
        if len(groups_raw) > MAX_ENTRY_ALIASES:
            raise SchemaError(
                f"an entry may define at most {MAX_ENTRY_ALIASES} output groups",
                _location(path, doc_id, positions, "groups"),
            )
        groups = {}
        grouped_outputs = set()
        for group_id, group_raw in groups_raw.items():
            group_location = _location(path, doc_id, positions, f"groups.{group_id}")
            require_identifier(group_id, "group id", group_location)
            group_raw = require_mapping(group_raw, f"groups.{group_id}", group_location)
            _reject_unknown(group_raw, {"label", "outputs"}, "group", group_location)
            label = require_display_label(
                group_raw.get("label", group_id), "group label", group_location
            )
            members = group_raw.get("outputs", [])
            if not isinstance(members, list) or not members or not all(isinstance(item, str) for item in members):
                raise SchemaError("group outputs must be a non-empty list", group_location)
            normalized_members = []
            for member in members:
                require_identifier(member, "group output", group_location)
                if member not in outputs:
                    raise SchemaError(
                        f"group {group_id!r} references unknown local output {member!r}",
                        group_location,
                    )
                if member in grouped_outputs:
                    raise SchemaError(
                        f"output {member!r} appears in more than one group",
                        group_location,
                    )
                grouped_outputs.add(member)
                normalized_members.append(member)
            groups[group_id] = OutputGroup(
                group_id,
                doc_id,
                label,
                tuple(normalized_members),
                group_location,
            )

        presets_raw = require_mapping(raw.get("presets", {}), "presets", root_location)
        if len(presets_raw) > MAX_ENTRY_ALIASES:
            raise SchemaError(
                f"an entry may define at most {MAX_ENTRY_ALIASES} presets",
                _location(path, doc_id, positions, "presets"),
            )
        presets = {}
        for preset_id, preset_raw in presets_raw.items():
            preset_location = _location(path, doc_id, positions, f"presets.{preset_id}")
            require_identifier(preset_id, "preset id", preset_location)
            preset_raw = require_mapping(preset_raw, f"presets.{preset_id}", preset_location)
            _reject_unknown(preset_raw, {"label", "values"}, "preset", preset_location)
            label = require_display_label(
                preset_raw.get("label", preset_id), "preset label", preset_location
            )
            values_raw = require_mapping(
                preset_raw.get("values", {}), f"presets.{preset_id}.values", preset_location
            )
            values = {}
            for key, value in values_raw.items():
                parameter = require_parameter_name(
                    key,
                    "preset parameter name",
                    _location(path, doc_id, positions, f"presets.{preset_id}.values.{key}"),
                )
                values[parameter] = value if isinstance(value, bool) else number_text(
                    value, f"preset value {key}", preset_location
                )
            presets[preset_id] = Preset(
                preset_id,
                doc_id,
                label,
                values,
                preset_location,
            )

        chart_keys = {
            "x", "range", "points", "y", "preset", "out", "data_out", "title",
            "x_label", "y_label", "curve_labels",
        }
        legacy_chart_present = bool(chart_keys.intersection(raw))
        declared_charts = raw.get("charts", {})
        if legacy_chart_present and declared_charts:
            raise SchemaError(
                "entry cannot mix legacy chart fields with named charts",
                root_location,
            )
        charts_raw = require_mapping(declared_charts, "charts", root_location)
        if len(charts_raw) > MAX_STATIC_CHARTS_PER_ENTRY:
            raise SchemaError(
                f"entry exceeds {MAX_STATIC_CHARTS_PER_ENTRY} static charts",
                root_location,
            )
        if legacy_chart_present:
            charts_raw = {"preview": {key: raw[key] for key in chart_keys if key in raw}}

        static_charts: Dict[str, StaticChart] = {}
        for chart_id, raw_chart_value in charts_raw.items():
            chart_prefix = f"charts.{chart_id}" if not legacy_chart_present else ""
            chart_location = _location(path, doc_id, positions, chart_prefix or "x")
            require_identifier(chart_id, "chart id", chart_location)
            raw_chart = require_mapping(raw_chart_value, f"chart {chart_id}", chart_location)
            _reject_unknown(raw_chart, chart_keys, "chart", chart_location)
            missing = sorted({"x", "range", "points", "y"} - set(raw_chart))
            if missing:
                raise SchemaError(
                    "chart configuration is missing required key(s): " + ", ".join(missing),
                    chart_location,
                )

            def chart_field(name: str) -> str:
                return f"{chart_prefix}.{name}" if chart_prefix else name

            chart_x = require_parameter_name(
                raw_chart.get("x"),
                "chart x",
                _location(path, doc_id, positions, chart_field("x")),
            )
            range_value = raw_chart.get("range")
            if not isinstance(range_value, list) or len(range_value) != 2:
                raise SchemaError(
                    "chart range must be a two-item list",
                    _location(path, doc_id, positions, chart_field("range")),
                )
            range_start = number_text(range_value[0], "chart range start", chart_location)
            range_end = number_text(range_value[1], "chart range end", chart_location)
            points = raw_chart.get("points")
            if not isinstance(points, int) or isinstance(points, bool):
                raise SchemaError(
                    "chart points must be an integer",
                    _location(path, doc_id, positions, chart_field("points")),
                )
            y = raw_chart.get("y")
            if not isinstance(y, list) or not y or not all(isinstance(item, str) for item in y):
                raise SchemaError(
                    "chart y must be a non-empty list of targets",
                    _location(path, doc_id, positions, chart_field("y")),
                )
            chart_preset = raw_chart.get("preset")
            if chart_preset is not None:
                chart_preset = require_parameter_name(
                    chart_preset,
                    "chart preset",
                    _location(path, doc_id, positions, chart_field("preset")),
                )
            text_values: Dict[str, Optional[str]] = {}
            for key in ("out", "data_out", "title", "x_label", "y_label"):
                value = raw_chart.get(key)
                text_values[key] = (
                    require_text(
                        value,
                        f"chart {key}",
                        _location(path, doc_id, positions, chart_field(key)),
                    )
                    if value is not None
                    else None
                )
            labels_raw = require_mapping(
                raw_chart.get("curve_labels", {}),
                "curve_labels",
                chart_location,
            )
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in labels_raw.items()
            ):
                raise SchemaError(
                    "curve_labels must map target text to label text",
                    chart_location,
                )
            static_charts[chart_id] = StaticChart(
                id=chart_id,
                owner_id=doc_id,
                label=text_values["title"] or chart_id,
                x=chart_x,
                range_start=range_start,
                range_end=range_end,
                points=points,
                y=tuple(y),
                preset=chart_preset,
                out=text_values["out"],
                data_out=text_values["data_out"],
                title=text_values["title"],
                x_label=text_values["x_label"],
                y_label=text_values["y_label"],
                curve_labels=dict(labels_raw),
                path=path,
                positions=positions,
            )

        first_chart = next(iter(static_charts.values()), None)
        chart = {
            "x": None,
            "range_start": None,
            "range_end": None,
            "points": None,
            "y": [],
            "preset": None,
            "out": None,
            "data_out": None,
            "title": None,
            "x_label": None,
            "y_label": None,
            "curve_labels": {},
        }
        if first_chart is not None:
            chart.update({
                "x": first_chart.x,
                "range_start": first_chart.range_start,
                "range_end": first_chart.range_end,
                "points": first_chart.points,
                "y": list(first_chart.y),
                "preset": first_chart.preset,
                "out": first_chart.out,
                "data_out": first_chart.data_out,
                "title": first_chart.title,
                "x_label": first_chart.x_label,
                "y_label": first_chart.y_label,
                "curve_labels": dict(first_chart.curve_labels),
            })

        if process_asts is None:
            from .process_parser import parse_process_asts

            process_asts = parse_process_asts(text, path)
        for process_ast in process_asts:
            if process_ast.id in occupied:
                raise SchemaError(
                    f"duplicate member name {process_ast.id!r}",
                    process_ast.location,
                )
            occupied.add(process_ast.id)

        from .process_ir import SymbolicTypeIR, SymbolRefIR
        from .process_lowering import lower_process_asts
        from .process_model import ExpressionSymbolKind

        static_symbols = {}
        symbolic_candidates = {}
        for domain_id, domain in registry.domains.items():
            if domain.value_type != "symbolic":
                continue
            value_type = SymbolicTypeIR(domain_id)
            for value in domain.allowed_values:
                assert isinstance(value, str)
                reference = SymbolRefIR(
                    f"@domain.{domain_id}",
                    value,
                    ExpressionSymbolKind.STATIC_MEMBER,
                    value_type,
                )
                static_symbols[f"{domain_id}.{value}"] = reference
                symbolic_candidates.setdefault(value, []).append(reference)
        for value, candidates in symbolic_candidates.items():
            if len(candidates) == 1:
                static_symbols[value] = candidates[0]
        object_type_ids = {
            name
            for item in structure_types.values()
            for name in (item.id, item.qualified_id)
        }
        lowered_processes = lower_process_asts(
            process_asts,
            registry,
            object_types=object_type_ids,
            static_symbols=static_symbols,
        )
        processes = {process.id: process for process in lowered_processes}

        if scenario_asts is None or analysis_asts is None:
            from .scenario_parser import parse_analysis_asts, parse_scenario_asts

            if scenario_asts is None:
                scenario_asts = parse_scenario_asts(text, path)
            if analysis_asts is None:
                analysis_asts = parse_analysis_asts(text, path)
        for declaration, kind in (
            *((item, "scenario") for item in scenario_asts),
            *((item, "analysis") for item in analysis_asts),
        ):
            if declaration.id in occupied:
                raise SchemaError(
                    f"duplicate member name {declaration.id!r}", declaration.location
                )
            occupied.add(declaration.id)

        semantics = dict(require_mapping(raw.get("semantics", {}), "semantics", root_location))
        return Entry(
            **base,
            game_version=raw.get("game_version"),
            validation_status=raw.get("validation_status"),
            sources=sources,
            semantics=semantics,
            aliases=aliases,
            inputs=inputs,
            constraints=list(constraints_raw),
            fields=fields,
            functions=functions,
            tables=tables,
            distributions=distributions,
            outputs=outputs,
            groups=groups,
            presets=presets,
            structure_types=structure_types,
            objects=objects,
            process_asts=process_asts,
            processes=processes,
            scenario_asts=scenario_asts,
            analysis_asts=analysis_asts,
            charts=static_charts,
            **chart,
        )

    raise SchemaError("unsupported document type", root_location)


def load_document(path: Path, registry: Optional[UnitRegistry] = None) -> Document:
    from .kirin_syntax import load_kirin_document

    loaded = load_kirin_document(path)
    return parse_document(
        loaded.raw,
        loaded.text,
        loaded.sha256,
        path,
        registry,
        loaded.positions,
        process_asts=loaded.process_asts,
        scenario_asts=loaded.scenario_asts,
        analysis_asts=loaded.analysis_asts,
    )
