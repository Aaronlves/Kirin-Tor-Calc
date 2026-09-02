"""Canonical source renderer for typed bounded process declarations."""

from __future__ import annotations

import json
from typing import List, Sequence

from .process_ast import (
    BranchEffectAst,
    CancelEffectAst,
    EffectAst,
    EmitEffectAst,
    EventCallAst,
    LetEffectAst,
    NextEffectAst,
    ProcessAst,
    ScheduleEffectAst,
    TypeAst,
    WhenEffectAst,
)


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _expression(value: str) -> str:
    return " ".join(line.strip() for line in value.splitlines() if line.strip())


def _type(value: TypeAst) -> str:
    if value.name == "number":
        return f"number[{_type(value.arguments[0])}]"
    if value.name == "list":
        return f"list[{_type(value.arguments[0])}, {value.capacity}]"
    if value.name == "map":
        return (
            f"map[{_type(value.arguments[0])}, {_type(value.arguments[1])}, "
            f"{value.capacity}]"
        )
    return value.name


def _bound(value) -> str:
    if value is None:
        return ""
    assert value.minimum is not None and value.maximum is not None
    return f" in {_expression(value.minimum.text)}..{_expression(value.maximum.text)}"


def _parameters(parameters) -> str:
    result = []
    for parameter in parameters:
        item = f"{parameter.id}: {_type(parameter.value_type)}"
        if parameter.reducer is not None:
            item += f" reduce {parameter.reducer.value}"
        result.append(item)
    return ", ".join(result)


def _call(call: EventCallAst) -> str:
    arguments = ", ".join(
        f"{argument.parameter_id} = {_expression(argument.value.text)}"
        for argument in call.arguments
    )
    return f"{call.event_id}({arguments})"


def _effects(effects: Sequence[EffectAst], indent: str) -> List[str]:
    lines = []
    for effect in effects:
        if isinstance(effect, LetEffectAst):
            lines.append(
                f"{indent}let {effect.id}: {_type(effect.value_type)} = "
                f"{_expression(effect.value.text)}"
            )
        elif isinstance(effect, NextEffectAst):
            lines.append(
                f"{indent}next {effect.state_id} = {_expression(effect.value.text)}"
            )
        elif isinstance(effect, EmitEffectAst):
            line = f"{indent}emit {_call(effect.call)}"
            if effect.phase_id is not None:
                line += f" phase {effect.phase_id}"
            lines.append(line)
        elif isinstance(effect, ScheduleEffectAst):
            lines.append(
                f"{indent}{effect.operation.value} {_call(effect.call)} after "
                f"{_expression(effect.delay.text)} phase {effect.phase_id} key "
                f"{_expression(effect.key.text)}"
            )
        elif isinstance(effect, CancelEffectAst):
            lines.append(f"{indent}cancel {_expression(effect.key.text)}")
        elif isinstance(effect, WhenEffectAst):
            lines.append(f"{indent}when {_expression(effect.condition.text)}:")
            lines.extend(_effects(effect.effects, indent + "  "))
        elif isinstance(effect, BranchEffectAst):
            lines.append(f"{indent}branch {effect.id} {effect.mode.value}:")
            for case in effect.cases:
                lines.append(
                    f"{indent}  probability {_expression(case.probability.text)}:"
                )
                lines.extend(_effects(case.effects, indent + "    "))
        else:
            raise TypeError(f"unsupported process effect {type(effect).__name__}")
    return lines

def render_process_ast(process: ProcessAst) -> List[str]:
    """Render one process AST without consulting or mutating the raw schema."""

    header = f"process {process.id}"
    if process.label is not None:
        header += " " + _quoted(process.label)
    lines = [header + ":"]
    for item in process.inputs:
        line = f"  input {item.id}"
        if item.label is not None:
            line += " " + _quoted(item.label)
        line += f": {_type(item.value_type)}"
        if item.default is not None:
            line += " = " + _expression(item.default.text)
        line += _bound(item.bound)
        lines.append(line)
    for item in process.states:
        line = f"  state {item.id}"
        if item.label is not None:
            line += " " + _quoted(item.label)
        line += f": {_type(item.value_type)} = {_expression(item.initial.text)}"
        line += _bound(item.bound)
        lines.append(line)
    for item in process.requirements:
        lines.append(f"  require {_expression(item.text)}")
    for item in process.keys:
        lines.append(f"  key {item.id}")
    for item in process.phases:
        lines.append(f"  phase {item.id}")
    for item in process.events:
        lines.append(
            f"  event {item.direction.value} {item.id}({_parameters(item.parameters)})"
        )
    for item in process.actions:
        line = f"  action {item.id}({_parameters(item.parameters)})"
        if item.guard is not None:
            line += " when " + _expression(item.guard.text)
        lines.append(line)
    for item in process.flows:
        lines.append(
            f"  flow {item.state_id}({item.current_id}, {item.elapsed_id}) = "
            f"{_expression(item.value.text)}"
        )
    for item in process.handlers:
        line = f"  on {item.trigger_id}({', '.join(item.parameter_bindings)})"
        if item.guard is not None:
            line += " when " + _expression(item.guard.text)
        lines.append(line + ":")
        lines.extend(_effects(item.effects, "    "))
    for item in process.observations:
        line = f"  observe {item.id}"
        if item.label is not None:
            line += " " + _quoted(item.label)
        line += f": {_type(item.value_type)} = {_expression(item.value.text)}"
        lines.append(line)
    return lines
