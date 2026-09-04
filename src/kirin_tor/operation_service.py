"""Strict, revision-bound mathematical service exposed to sandboxed Plugins."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional, Sequence

import sympy as sp

from .application import ComparisonVariant, build_workspace_index, compare_variants
from .engine import Engine
from .errors import (
    InvalidRequestError,
    LimitExceededError,
    StaleRevisionError,
    UnknownIdentityError,
)
from .expression import parse_exact_number
from .limits import (
    MAX_COMPARISON_VARIANTS,
    MAX_EXPRESSION_LENGTH,
    MAX_PLUGIN_IDENTITY_CHARS,
    MAX_PLUGIN_OPERATION_TARGETS,
    MAX_PLUGIN_TARGET_INPUTS,
    MAX_PLUGIN_VARIANT_NAME_CHARS,
    MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS,
    MAX_SCAN_POINTS,
    PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS,
)
from .model_catalog import ModelCatalog
from .operations import (
    analyze_process,
    evaluate,
    evaluate_many,
    explain,
    scan_grid,
    scan_values,
    solve_equation,
)
from .plugin_protocol import PLUGIN_ACTIONS
from .workspace import Workspace


PLUGIN_NUMERIC_PRECISION = 30
PLUGIN_DISPLAY_DIGITS = 12


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise InvalidRequestError(f"{label} must be an object")
    return value


def _reject_unknown(payload: Mapping[str, object], allowed: set[str]) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise InvalidRequestError(
            "unknown request field(s): " + ", ".join(unknown)
        )


def _text(
    value: object,
    label: str,
    *,
    maximum: int = MAX_PLUGIN_IDENTITY_CHARS,
) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvalidRequestError(f"{label} must be bounded non-empty text")
    return value.strip()


def _positive_int(
    value: object,
    label: str,
    *,
    default: int,
    maximum: int,
) -> int:
    candidate = default if value is None else value
    if (
        not isinstance(candidate, int)
        or isinstance(candidate, bool)
        or candidate < 2
        or candidate > maximum
    ):
        raise LimitExceededError(f"{label} must be from 2 to {maximum}")
    return candidate


def _normalize_scalar(value: object, label: str) -> str:
    text = _text(value, label, maximum=MAX_EXPRESSION_LENGTH)
    if text.endswith("%"):
        number = parse_exact_number(text[:-1].strip())
        return sp.sstr(sp.simplify(number / 100))
    return text


class PluginOperationService:
    """Validate and execute only the operations in the public Plugin registry."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.catalog = ModelCatalog(workspace)
        self.revision = self.catalog.revision
        self.index = build_workspace_index(workspace)
        self.targets = {item.value: item for item in self.index.targets}
        self.inputs = {item.value: item for item in self.index.inputs}
        self.analyses = {item.value: item for item in self.index.analyses}

    def _revision(self, value: object) -> None:
        if not isinstance(value, str) or value != self.revision:
            raise StaleRevisionError(
                "operation targets an obsolete workspace revision"
            )

    def _target(self, value: object) -> str:
        target = _text(value, "target")
        if target not in self.targets:
            raise UnknownIdentityError(
                f"operation target is not a declared output: {target}"
            )
        return target

    def _target_list(self, value: object) -> list[str]:
        if not isinstance(value, list) or not value:
            raise InvalidRequestError("targets must be a non-empty array")
        if len(value) > MAX_PLUGIN_OPERATION_TARGETS:
            raise LimitExceededError(
                f"targets exceeds {MAX_PLUGIN_OPERATION_TARGETS} items"
            )
        targets = [self._target(item) for item in value]
        if len(targets) != len(set(targets)):
            raise InvalidRequestError("targets must be unique")
        return targets

    def _preset(self, value: object) -> Optional[str]:
        if value is None or value == "":
            return None
        preset = _text(value, "preset")
        if preset not in {item.value for item in self.index.presets}:
            raise UnknownIdentityError(f"unknown preset: {preset}")
        return preset

    def _allowed_inputs(self, targets: Sequence[str]) -> set[str]:
        return {
            input_id
            for target in targets
            for input_id in self.targets[target].inputs
        }

    def _input(self, value: object, allowed: set[str], label: str) -> str:
        input_id = _text(value, label)
        if input_id not in self.inputs or input_id not in allowed:
            raise UnknownIdentityError(
                f"{label} is not a declared dependency input: {input_id}"
            )
        return input_id

    def _overrides(
        self,
        value: object,
        allowed: set[str],
        *,
        excluded: set[str] | None = None,
    ) -> dict[str, str]:
        if value is None:
            return {}
        raw = _mapping(value, "overrides")
        if len(raw) > MAX_PLUGIN_TARGET_INPUTS:
            raise LimitExceededError(
                f"overrides exceeds {MAX_PLUGIN_TARGET_INPUTS} inputs"
            )
        blocked = excluded or set()
        result = {}
        for input_id, scalar in raw.items():
            if input_id not in self.inputs or input_id not in allowed:
                raise UnknownIdentityError(
                    f"override is not a declared dependency input: {input_id}"
                )
            if input_id in blocked:
                raise InvalidRequestError(
                    f"axis or solve variable may not also be overridden: {input_id}"
                )
            result[input_id] = _normalize_scalar(scalar, f"override {input_id}")
        return result

    def _operation_provenance(self, descriptor_id: str, kind: str) -> dict:
        matches = [
            descriptor
            for descriptor in self.catalog.descriptors
            if descriptor["id"] == descriptor_id and descriptor["kind"] == kind
        ]
        if len(matches) != 1:
            return {"origin": None, "source_location": None}
        return {
            "origin": matches[0]["origin"],
            "source_location": matches[0]["source_location"],
        }

    def _envelope(
        self,
        action: str,
        targets: Sequence[str],
        preset: Optional[str],
        overrides: Mapping[str, str],
        result: dict,
    ) -> dict:
        dependency_ids = sorted(result.get("dependency_ids", []))
        return {
            "status": "ok",
            "operation_id": uuid.uuid4().hex,
            "operation": action,
            "revision": self.revision,
            "targets": list(targets),
            "applied": {
                "preset": preset,
                "overrides": dict(sorted(overrides.items())),
            },
            "provenance": {
                "targets": [
                    {
                        "id": target,
                        **self._operation_provenance(target, "output"),
                    }
                    for target in targets
                ],
                "dependencies": [
                    {
                        "id": dependency,
                        **self._operation_provenance(dependency, "entry"),
                    }
                    for dependency in dependency_ids
                ],
            },
            "warnings": list(result.get("warnings", [])),
            "result": result,
        }

    def validate(self, action: str, payload: object, *, for_job: bool = False) -> dict:
        capability = PLUGIN_ACTIONS.get(action)
        if capability is None or capability["handler"] != "operation":
            raise InvalidRequestError(f"unsupported mathematical action: {action}")
        if (capability["execution"] == "job") != for_job:
            expected = "job" if capability["execution"] == "job" else "sync"
            raise InvalidRequestError(f"{action} requires {expected} execution")
        request = dict(_mapping(payload, "operation request"))
        self._revision(request.get("revision"))
        if action == "analyze":
            _reject_unknown(request, {"revision", "target", "include_trace"})
            target = _text(request.get("target"), "target")
            if target not in self.analyses:
                raise UnknownIdentityError(
                    f"analysis target is not a declared Process Analysis: {target}"
                )
            if not isinstance(request.get("include_trace", False), bool):
                raise InvalidRequestError("include_trace must be boolean")
        return request

    def execute(self, action: str, payload: object, *, for_job: bool = False) -> dict:
        request = self.validate(action, payload, for_job=for_job)
        engine = Engine(self.workspace)
        timeout = (
            MAX_PROCESS_ANALYSIS_TIMEOUT_SECONDS
            if for_job
            else PLUGIN_STANDARD_OPERATION_TIMEOUT_SECONDS
        )
        targets: list[str]
        preset: Optional[str] = None
        overrides: dict[str, str] = {}

        if action == "evaluate":
            _reject_unknown(request, {"revision", "target", "preset", "overrides"})
            targets = [self._target(request.get("target"))]
            preset = self._preset(request.get("preset"))
            overrides = self._overrides(
                request.get("overrides"), self._allowed_inputs(targets)
            )
            result = evaluate(
                engine,
                targets[0],
                preset,
                overrides,
                PLUGIN_NUMERIC_PRECISION,
                PLUGIN_DISPLAY_DIGITS,
                timeout,
            )
        elif action == "evaluate-many":
            _reject_unknown(request, {"revision", "targets", "preset", "overrides"})
            targets = self._target_list(request.get("targets"))
            preset = self._preset(request.get("preset"))
            overrides = self._overrides(
                request.get("overrides"), self._allowed_inputs(targets)
            )
            result = evaluate_many(
                engine,
                targets,
                preset,
                overrides,
                PLUGIN_NUMERIC_PRECISION,
                PLUGIN_DISPLAY_DIGITS,
                timeout,
            )
        elif action == "explain":
            _reject_unknown(request, {"revision", "target"})
            targets = [self._target(request.get("target"))]
            result = explain(engine, targets[0], timeout)
        elif action == "compare":
            _reject_unknown(request, {"revision", "target", "variants"})
            targets = [self._target(request.get("target"))]
            raw_variants = request.get("variants")
            if not isinstance(raw_variants, list) or not raw_variants:
                raise InvalidRequestError("variants must be a non-empty array")
            if len(raw_variants) > MAX_COMPARISON_VARIANTS:
                raise LimitExceededError(
                    f"variants exceeds {MAX_COMPARISON_VARIANTS} items"
                )
            allowed = self._allowed_inputs(targets)
            variants = []
            names = set()
            for index, raw_variant in enumerate(raw_variants):
                variant = _mapping(raw_variant, f"variant {index + 1}")
                _reject_unknown(variant, {"name", "preset", "overrides"})
                name = _text(
                    variant.get("name"),
                    f"variant {index + 1} name",
                    maximum=MAX_PLUGIN_VARIANT_NAME_CHARS,
                )
                if name in names:
                    raise InvalidRequestError("variant names must be unique")
                names.add(name)
                variants.append(
                    ComparisonVariant(
                        name,
                        self._preset(variant.get("preset")),
                        self._overrides(variant.get("overrides"), allowed),
                    )
                )
            result = compare_variants(
                self.workspace,
                targets[0],
                variants,
                precision=PLUGIN_NUMERIC_PRECISION,
                display_digits=PLUGIN_DISPLAY_DIGITS,
                timeout_seconds=timeout,
            )
        elif action == "scan":
            _reject_unknown(
                request,
                {"revision", "targets", "x", "range", "points", "preset", "overrides"},
            )
            targets = self._target_list(request.get("targets"))
            allowed = self._allowed_inputs(targets)
            x = self._input(request.get("x"), allowed, "x")
            points = _positive_int(
                request.get("points"), "points", default=41, maximum=MAX_SCAN_POINTS
            )
            range_text = _text(
                request.get("range"), "range", maximum=MAX_EXPRESSION_LENGTH
            )
            preset = self._preset(request.get("preset"))
            overrides = self._overrides(
                request.get("overrides"), allowed, excluded={x}
            )
            result = scan_values(
                engine,
                x,
                range_text,
                points,
                targets,
                preset,
                overrides,
                PLUGIN_NUMERIC_PRECISION,
                PLUGIN_DISPLAY_DIGITS,
                timeout,
            )
        elif action == "grid":
            _reject_unknown(
                request,
                {
                    "revision", "target", "x", "x_range", "x_points", "y",
                    "y_range", "y_points", "preset", "overrides",
                },
            )
            targets = [self._target(request.get("target"))]
            allowed = self._allowed_inputs(targets)
            x = self._input(request.get("x"), allowed, "x")
            y = self._input(request.get("y"), allowed, "y")
            if x == y:
                raise InvalidRequestError("grid axes must be distinct inputs")
            x_points = _positive_int(
                request.get("x_points"),
                "x_points",
                default=21,
                maximum=MAX_SCAN_POINTS,
            )
            y_points = _positive_int(
                request.get("y_points"),
                "y_points",
                default=21,
                maximum=MAX_SCAN_POINTS,
            )
            if x_points * y_points > MAX_SCAN_POINTS:
                raise LimitExceededError(
                    f"grid total points exceeds {MAX_SCAN_POINTS}"
                )
            x_range = _text(
                request.get("x_range"), "x_range", maximum=MAX_EXPRESSION_LENGTH
            )
            y_range = _text(
                request.get("y_range"), "y_range", maximum=MAX_EXPRESSION_LENGTH
            )
            preset = self._preset(request.get("preset"))
            overrides = self._overrides(
                request.get("overrides"), allowed, excluded={x, y}
            )
            result = scan_grid(
                engine,
                x,
                x_range,
                x_points,
                y,
                y_range,
                y_points,
                targets[0],
                preset,
                overrides,
                PLUGIN_NUMERIC_PRECISION,
                PLUGIN_DISPLAY_DIGITS,
                timeout,
            )
        elif action == "solve":
            _reject_unknown(
                request,
                {"revision", "target", "variable", "equals", "range", "preset", "overrides"},
            )
            targets = [self._target(request.get("target"))]
            allowed = self._allowed_inputs(targets)
            variable = self._input(request.get("variable"), allowed, "variable")
            equals = _text(
                request.get("equals"), "equals", maximum=MAX_EXPRESSION_LENGTH
            )
            range_value = request.get("range")
            range_text = (
                None
                if range_value is None or range_value == ""
                else _text(range_value, "range", maximum=MAX_EXPRESSION_LENGTH)
            )
            preset = self._preset(request.get("preset"))
            overrides = self._overrides(
                request.get("overrides"), allowed, excluded={variable}
            )
            result = solve_equation(
                engine,
                targets[0],
                variable,
                equals,
                range_text,
                preset,
                overrides,
                PLUGIN_NUMERIC_PRECISION,
                timeout,
            )
        elif action == "analyze":
            _reject_unknown(request, {"revision", "target", "include_trace"})
            target = _text(request.get("target"), "target")
            if target not in self.analyses:
                raise UnknownIdentityError(
                    f"analysis target is not a declared Process Analysis: {target}"
                )
            include_trace = request.get("include_trace", False)
            if not isinstance(include_trace, bool):
                raise InvalidRequestError("include_trace must be boolean")
            targets = [target]
            result = analyze_process(
                self.workspace,
                target,
                include_trace=include_trace,
                timeout_seconds=timeout,
            )
        else:  # registry and branch coverage are tested together
            raise InvalidRequestError(f"unsupported mathematical action: {action}")

        return self._envelope(action, targets, preset, overrides, result)
