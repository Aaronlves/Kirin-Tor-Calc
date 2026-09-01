"""Game-neutral dimensions, units, and reusable input domains."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Iterable, Mapping, Optional, Tuple

from .errors import SchemaError, SourceLocation, UnitError


@dataclass(frozen=True)
class Dimension:
    powers: Tuple[Tuple[str, Fraction], ...] = ()

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Fraction]) -> "Dimension":
        return cls(tuple(sorted((key, value) for key, value in mapping.items() if value)))

    def _mapping(self) -> Dict[str, Fraction]:
        return dict(self.powers)

    def multiply(self, other: "Dimension") -> "Dimension":
        result = self._mapping()
        for key, value in other.powers:
            result[key] = result.get(key, Fraction(0)) + value
        return Dimension.from_mapping(result)

    def divide(self, other: "Dimension") -> "Dimension":
        result = self._mapping()
        for key, value in other.powers:
            result[key] = result.get(key, Fraction(0)) - value
        return Dimension.from_mapping(result)

    def power(self, exponent: Fraction) -> "Dimension":
        return Dimension.from_mapping({key: value * exponent for key, value in self.powers})

    @property
    def is_dimensionless(self) -> bool:
        return not self.powers

    def render(self) -> str:
        if not self.powers:
            return "dimensionless"
        pieces = []
        for key, value in self.powers:
            pieces.append(key if value == 1 else f"{key}^{value}")
        return "*".join(pieces)


DIMENSIONLESS = Dimension()


@dataclass(frozen=True)
class DomainSpec:
    name: str
    value_type: str = "number"
    unit_name: str = "dimensionless"
    minimum: Optional[str] = None
    maximum: Optional[str] = None
    integer: bool = False
    allowed_values: Tuple[object, ...] = ()


class UnitRegistry:
    """Game-neutral mathematical vocabulary plus workspace declarations."""

    def __init__(self) -> None:
        time = Dimension.from_mapping({"time": Fraction(1)})
        self.dimensions: Dict[str, dict] = {
            "time": {"name": "Time", "description": "Game-neutral physical time."}
        }
        self.units: Dict[str, Dimension] = {
            "dimensionless": DIMENSIONLESS,
            "time": time,
            "second": time,
            "millisecond": time,
        }
        self.unit_scales: Dict[str, Fraction] = {
            "dimensionless": Fraction(1),
            "time": Fraction(1),
            "second": Fraction(1),
            "millisecond": Fraction(1, 1000),
        }
        self.domains: Dict[str, DomainSpec] = {
            "probability": DomainSpec("probability", "number", "dimensionless", "0", "1"),
            "nonnegative_integer": DomainSpec(
                "nonnegative_integer", "number", "dimensionless", "0", None, True
            ),
            "positive_integer": DomainSpec(
                "positive_integer", "number", "dimensionless", "1", None, True
            ),
            "count": DomainSpec("count", "number", "dimensionless", "0", None, True),
        }
        self.builtin_dimensions = frozenset(self.dimensions)
        self.builtin_units = frozenset(self.units)
        self.builtin_domains = frozenset(self.domains)
        self._dimension_locations: Dict[str, SourceLocation] = {}
        self._unit_locations: Dict[str, SourceLocation] = {}
        self._domain_locations: Dict[str, SourceLocation] = {}

    def add_dimension(self, name: str, metadata: Mapping[str, object], location: SourceLocation) -> None:
        normalized = dict(metadata)
        if name in self.dimensions:
            # Display metadata is deliberately non-authoritative. Repeating the
            # same base-dimension name anywhere is mathematically identical.
            return
        self.dimensions[name] = normalized
        self._dimension_locations[name] = location

    def add_unit(
        self,
        name: str,
        powers: Mapping[str, Fraction],
        scale: Fraction,
        location: SourceLocation,
    ) -> None:
        unknown = set(powers) - set(self.dimensions)
        if unknown:
            raise SchemaError(
                "unit references undeclared dimension(s): " + ", ".join(sorted(unknown)),
                location,
            )
        dimension = Dimension.from_mapping(powers)
        if scale <= 0:
            raise SchemaError(f"unit {name!r} scale must be positive", location)
        if name in self.units:
            if self.units[name] != dimension or self.unit_scales[name] != scale:
                previous = self._unit_locations.get(name)
                suffix = f" at {previous.render()}" if previous else " built into the mathematical core"
                raise SchemaError(f"unit {name!r} conflicts with its declaration{suffix}", location)
            return
        self.units[name] = dimension
        self.unit_scales[name] = scale
        self._unit_locations[name] = location

    def add_domain(self, spec: DomainSpec, location: SourceLocation) -> None:
        if spec.unit_name not in self.units:
            raise SchemaError(f"domain references unsupported unit {spec.unit_name!r}", location)
        if spec.name in self.domains:
            def semantic_key(item: DomainSpec):
                number = lambda value: None if value is None else Fraction(str(value))
                allowed = frozenset(
                    value if isinstance(value, bool) else Fraction(str(value))
                    for value in item.allowed_values
                )
                return (
                    item.name,
                    item.value_type,
                    item.unit_name,
                    number(item.minimum),
                    number(item.maximum),
                    item.integer,
                    allowed,
                )

            if semantic_key(self.domains[spec.name]) != semantic_key(spec):
                previous_location = self._domain_locations.get(spec.name)
                previous = (
                    previous_location.render()
                    if previous_location is not None
                    else "the game-neutral mathematical core"
                )
                raise SchemaError(
                    f"domain {spec.name!r} conflicts with its declaration at {previous}", location
                )
            return
        self.domains[spec.name] = spec
        self._domain_locations[spec.name] = location

    def parse_unit(self, name: str, location: Optional[SourceLocation] = None) -> Dimension:
        if name not in self.units:
            supported = ", ".join(sorted(self.units))
            raise UnitError(
                f"unsupported unit {name!r}; declare it in entry.semantics.units"
                + (f"; available units: {supported}" if supported else ""),
                location,
            )
        return self.units[name]

    def scale(self, name: str, location: Optional[SourceLocation] = None) -> Fraction:
        self.parse_unit(name, location)
        return self.unit_scales[name]

    def render(self, dimension: Dimension) -> str:
        exact_names = sorted(
            name
            for name, value in self.units.items()
            if value == dimension and self.unit_scales[name] == 1
        )
        if not exact_names:
            exact_names = sorted(name for name, value in self.units.items() if value == dimension)
        if exact_names:
            if "dimensionless" in exact_names:
                return "dimensionless"
            if len(dimension.powers) == 1:
                dimension_name, exponent = dimension.powers[0]
                if exponent == 1 and dimension_name in exact_names:
                    return dimension_name
            return exact_names[0]
        return dimension.render()


def require_same(units: Iterable[Dimension], context: str) -> Dimension:
    units = list(units)
    if not units:
        return DIMENSIONLESS
    first = units[0]
    if any(unit != first for unit in units[1:]):
        rendered = ", ".join(unit.render() for unit in units)
        raise UnitError(f"incompatible units in {context}: {rendered}")
    return first
