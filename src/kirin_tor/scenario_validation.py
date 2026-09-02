"""Whole-scenario phase, batch-conflict, and static-fuel validation."""

from __future__ import annotations

from collections import defaultdict
from fractions import Fraction
from typing import Dict, Iterator, List, Mapping, Sequence, Tuple

from .errors import SchemaError
from .process_ir import BranchEffectIR, EffectIR, EmitEffectIR, WhenEffectIR
from .process_validation import possible_handler_footprints
from .scenario_ir import (
    AtScheduleIR,
    CompositeActionIR,
    EveryScheduleIR,
    InstanceMemberRefIR,
    ProcessInstanceIR,
    ScenarioCallIR,
    ScenarioIR,
)


def _times(
    schedule: object, horizon: Fraction
) -> Iterator[Fraction]:
    if isinstance(schedule, AtScheduleIR):
        if schedule.time <= horizon:
            yield schedule.time
        return
    assert isinstance(schedule, EveryScheduleIR)
    end = min(horizon, schedule.end) if schedule.end is not None else horizon
    current = schedule.start
    while current <= end:
        yield current
        current += schedule.interval


def _nested_effects(effects: Sequence[EffectIR]) -> Iterator[EffectIR]:
    for effect in effects:
        yield effect
        if isinstance(effect, WhenEffectIR):
            yield from _nested_effects(effect.effects)
        elif isinstance(effect, BranchEffectIR):
            for case in effect.cases:
                yield from _nested_effects(case.effects)


def _check_call_batch(
    calls: Sequence[ScenarioCallIR],
    instances: Mapping[str, ProcessInstanceIR],
    label: str,
) -> None:
    grouped_calls: Dict[Tuple[str, object], List[ScenarioCallIR]] = defaultdict(list)
    for call in calls:
        grouped_calls[(call.target.instance_id, call.target.member)].append(call)
    for same_event in grouped_calls.values():
        if len(same_event) < 2:
            continue
        parameters = {item.id: item for item in same_event[0].parameters}
        for parameter_id, parameter in parameters.items():
            if parameter.reducer is not None:
                continue
            values = [
                next(
                    argument.value
                    for argument in call.arguments
                    if argument.parameter_id == parameter_id
                )
                for call in same_event
            ]
            if any(value != values[0] for value in values[1:]):
                raise SchemaError(
                    f"{label} sends unequal unreduced parameter {parameter_id!r}",
                    same_event[-1].location,
                )
    # Calls of exactly the same event are reduced into one handler invocation.
    triggers = {
        (call.target.instance_id, call.target.member): call.target
        for call in calls
    }
    by_instance: Dict[str, List[InstanceMemberRefIR]] = defaultdict(list)
    for target in triggers.values():
        by_instance[target.instance_id].append(target)
    for instance_id, targets in by_instance.items():
        alternatives = [(frozenset(), frozenset())]
        for target in targets:
            next_alternatives = []
            for existing_states, existing_slots in alternatives:
                for states, slots in possible_handler_footprints(
                    instances[instance_id].process, target.member
                ):
                    conflict = existing_states & states
                    if conflict:
                        state = sorted(item.member_id for item in conflict)[0]
                        raise SchemaError(
                            f"{label} can write instance {instance_id!r} state {state!r} "
                            "from more than one event",
                            calls[-1].location if calls else None,
                        )
                    slot_conflict = existing_slots & slots
                    if slot_conflict:
                        key = sorted(slot_conflict)[0][1]
                        raise SchemaError(
                            f"{label} can mutate instance {instance_id!r} schedule key "
                            f"{key!r} from more than one event",
                            calls[-1].location if calls else None,
                        )
                    next_alternatives.append(
                        (existing_states | states, existing_slots | slots)
                    )
            alternatives = list(dict.fromkeys(next_alternatives))


def _validate_phase_edges(scenario: ScenarioIR) -> None:
    instances = {item.id: item for item in scenario.instances}
    connections = defaultdict(list)
    connected_outputs = set()
    for connection in scenario.connections:
        connections[(connection.source.instance_id, connection.source.member)].append(
            connection.target
        )
        connected_outputs.add(
            (connection.source.instance_id, connection.source.member)
        )
    trigger_phases: Dict[Tuple[str, object], set[int]] = defaultdict(set)
    for schedule in scenario.schedules:
        for call in schedule.sends:
            trigger_phases[(call.target.instance_id, call.target.member)].add(
                call.phase.index
            )
    for action in scenario.actions:
        for call in action.sends:
            trigger_phases[(call.target.instance_id, call.target.member)].add(
                call.phase.index
            )

    phase_maps = {
        instance.id: {
            binding.process_phase.member.member_id: binding.scenario_phase
            for binding in instance.phases
        }
        for instance in scenario.instances
    }
    event_directions = {
        instance.id: {
            event.ref: event.direction for event in instance.process.events
        }
        for instance in scenario.instances
    }
    changed = True
    while changed:
        changed = False
        for instance in scenario.instances:
            for handler in instance.process.handlers:
                current_phases = trigger_phases.get((instance.id, handler.trigger), set())
                for effect in _nested_effects(handler.effects):
                    if not isinstance(effect, EmitEffectIR):
                        continue
                    connected = (instance.id, effect.call.event) in connected_outputs
                    if effect.phase is None:
                        if (
                            connected
                            or event_directions[instance.id][effect.call.event].value
                            == "internal"
                        ):
                            raise SchemaError(
                                "connected or internally handled emitted events require an explicit phase",
                                effect.location,
                            )
                        continue
                    emitted_phase = phase_maps[instance.id][effect.phase.member_id]
                    if any(emitted_phase.index <= index for index in current_phases):
                        raise SchemaError(
                            "an event emitted at the current time must use a later scenario phase",
                            effect.location,
                        )
                    key = (instance.id, effect.call.event)
                    before = len(trigger_phases[key])
                    trigger_phases[key].add(emitted_phase.index)
                    if len(trigger_phases[key]) != before:
                        changed = True
                    for target in connections.get(key, ()):
                        target_key = (target.instance_id, target.member)
                        before = len(trigger_phases[target_key])
                        trigger_phases[target_key].add(emitted_phase.index)
                        if len(trigger_phases[target_key]) != before:
                            changed = True


def validate_scenario_ir(scenario: ScenarioIR) -> None:
    """Validate all statically enumerable batches and visible fuel bounds."""

    instances = {item.id: item for item in scenario.instances}
    batches: Dict[Tuple[Fraction, int], List[ScenarioCallIR]] = defaultdict(list)
    external_events = 0
    for schedule in scenario.schedules:
        times = tuple(_times(schedule, scenario.bounds.horizon))
        external_events += len(times) * len(schedule.sends)
        for time in times:
            batches[(time, schedule.phase.index)].extend(schedule.sends)
    if external_events > scenario.bounds.maximum_events:
        raise SchemaError(
            "external schedules alone exceed scenario maximum_events",
            scenario.location,
        )
    for (time, phase), calls in batches.items():
        _check_call_batch(calls, instances, f"batch at {time} phase {phase}")

    decision_batches: Dict[Tuple[Fraction, int], list] = defaultdict(list)
    decisions = 0
    actions = {item.id: item for item in scenario.actions}
    for schedule in scenario.decisions:
        end = min(scenario.bounds.horizon, schedule.end) if schedule.end is not None else scenario.bounds.horizon
        current = schedule.start
        while current <= end:
            decisions += 1
            decision_batches[(current, schedule.phase.index)].append(schedule)
            current += schedule.interval
        for action_id in schedule.action_ids:
            action = actions[action_id]
            if any(call.phase != schedule.phase for call in action.sends):
                raise SchemaError(
                    f"action {action.id!r} send phases must match its decision phase",
                    action.location,
                )
    for schedule in (
        *scenario.event_decisions,
        *scenario.condition_decisions,
        *scenario.continuous_decisions,
    ):
        for action_id in schedule.action_ids:
            action = actions[action_id]
            if any(call.phase != schedule.phase for call in action.sends):
                raise SchemaError(
                    f"action {action.id!r} send phases must match its decision phase",
                    action.location,
                )
    maximum_static_decisions = decisions + sum(
        schedule.maximum_occurrences
        for schedule in scenario.continuous_decisions
    )
    if maximum_static_decisions > scenario.bounds.maximum_decisions:
        raise SchemaError(
            "fixed and continuous decision declarations exceed scenario maximum_decisions",
            scenario.location,
        )
    for key, schedules in decision_batches.items():
        if len(schedules) > 1:
            raise SchemaError(
                "more than one decision schedule occupies the same time and phase",
                schedules[-1].location,
            )
        base = batches.get(key, [])
        schedule = schedules[0]
        for action_id in schedule.action_ids:
            _check_call_batch(
                [*base, *actions[action_id].sends],
                instances,
                f"decision batch at {key[0]} phase {key[1]} using {action_id}",
            )
    for action in scenario.actions:
        phase_ids = {call.phase.id for call in action.sends}
        if len(phase_ids) != 1:
            raise SchemaError(
                f"composite action {action.id!r} must send one same-phase batch",
                action.location,
            )
        _check_call_batch(action.sends, instances, f"composite action {action.id!r}")
    _validate_phase_edges(scenario)
