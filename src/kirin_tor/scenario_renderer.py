"""Canonical source renderer for scenario and analysis AST nodes."""

from __future__ import annotations

import json
from typing import List

from .scenario_ast import AnalysisAst, AtScheduleAst, EveryScheduleAst, ScenarioAst, ScenarioSendAst


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _expression(value) -> str:
    return " ".join(line.strip() for line in value.text.splitlines() if line.strip())


def _send(value: ScenarioSendAst, indent: str) -> str:
    arguments = ", ".join(
        f"{argument.parameter_id} = {_expression(argument.value)}"
        for argument in value.call.arguments
    )
    line = f"{indent}send {value.instance_id}.{value.call.event_id}({arguments})"
    if value.phase_id is not None:
        line += f" phase {value.phase_id}"
    return line


def render_scenario_ast(scenario: ScenarioAst) -> List[str]:
    header = f"scenario {scenario.id}"
    if scenario.label is not None:
        header += " " + _quoted(scenario.label)
    lines = [header + ":", "  phases:"]
    lines.extend(f"    - {phase.id}" for phase in scenario.phases)
    for instance in scenario.instances:
        lines.append(f"  use {instance.id} = {instance.process_path}:")
        lines.extend(
            f"    {binding.input_id} = {_expression(binding.value)}"
            for binding in instance.inputs
        )
        lines.extend(
            f"    phase {binding.process_phase_id} = {binding.scenario_phase_id}"
            for binding in instance.phases
        )
    for connection in scenario.connections:
        lines.append(
            f"  connect {connection.source.instance_id}.{connection.source.member_id} -> "
            f"{connection.target.instance_id}.{connection.target.member_id}"
        )
    for action in scenario.actions:
        line = f"  action {action.id}"
        if action.guard is not None:
            line += f" when {_expression(action.guard)}"
        lines.append(line + ":")
        lines.extend(_send(send, "    ") for send in action.sends)
    for policy in scenario.policies:
        lines.append(f"  policy {policy.id}:")
        if policy.sequence:
            lines.append("    sequence:")
            lines.extend(f"      - {option}" for option in policy.sequence)
        else:
            for rule in policy.rules:
                if rule.condition is None:
                    lines.append(f"    otherwise {rule.action_id}")
                else:
                    lines.append(
                        f"    choose {rule.action_id} when {_expression(rule.condition)}"
                    )
    for schedule in scenario.schedules:
        if isinstance(schedule, AtScheduleAst):
            lines.append(
                f"  at {_expression(schedule.time)} phase {schedule.phase_id}:"
            )
        elif isinstance(schedule, EveryScheduleAst):
            line = (
                f"  every {_expression(schedule.interval)} from "
                f"{_expression(schedule.start)}"
            )
            if schedule.end is not None:
                line += f" until {_expression(schedule.end)}"
            lines.append(f"{line} phase {schedule.phase_id}:")
        else:
            raise TypeError(f"unsupported scenario schedule {type(schedule).__name__}")
        # The containing schedule already fixes the phase; omit redundant
        # per-send phase in canonical source.
        for send in schedule.sends:
            canonical = ScenarioSendAst(
                send.instance_id, send.call, None, send.location
            )
            lines.append(_send(canonical, "    "))
    for decision in scenario.decisions:
        line = (
            f"  decide every {_expression(decision.interval)} from "
            f"{_expression(decision.start)}"
        )
        if decision.end is not None:
            line += f" until {_expression(decision.end)}"
        lines.append(f"{line} phase {decision.phase_id}:")
        lines.extend(f"    - {option}" for option in decision.options)
    if scenario.stop is not None:
        lines.append(f"  stop when {_expression(scenario.stop)}")
    assert scenario.bounds is not None
    lines.extend(
        [
            "  bounds:",
            f"    horizon = {_expression(scenario.bounds.horizon)}",
            f"    maximum_events = {_expression(scenario.bounds.maximum_events)}",
            f"    maximum_decisions = {_expression(scenario.bounds.maximum_decisions)}",
            f"    maximum_branches = {_expression(scenario.bounds.maximum_branches)}",
            f"    maximum_entities = {_expression(scenario.bounds.maximum_entities)}",
        ]
    )
    return lines


def render_analysis_ast(analysis: AnalysisAst) -> List[str]:
    header = f"analysis {analysis.id}"
    if analysis.label is not None:
        header += " " + _quoted(analysis.label)
    lines = [
        header + ":",
        f"  using = {analysis.scenario_path}",
        f"  operation = {analysis.operation}",
    ]
    if len(analysis.policy_ids) == 1:
        lines.append(f"  policy = {analysis.policy_ids[0]}")
    elif analysis.policy_ids:
        lines.append("  policies:")
        lines.extend(f"    - {policy_id}" for policy_id in analysis.policy_ids)
    if analysis.objective is not None:
        lines.append(
            f"  objective {analysis.objective_direction} {_expression(analysis.objective)}"
        )
    if analysis.tie_break is not None:
        lines.append(
            f"  then {analysis.tie_break_direction} {_expression(analysis.tie_break)}"
        )
    if analysis.target is not None:
        lines.append(f"  target = {_expression(analysis.target)}")
    return lines
