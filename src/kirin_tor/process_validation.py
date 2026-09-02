"""Static semantic checks over fully lowered Process IR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Sequence, Tuple

from .errors import SchemaError
from .process_ir import (
    BranchEffectIR,
    CancelEffectIR,
    EffectIR,
    EventIdScheduleKeyIR,
    HandlerIR,
    NextEffectIR,
    ProcessIR,
    ProcessMemberRefIR,
    ScheduleEffectIR,
    StaticScheduleKeyIR,
    WhenEffectIR,
)


@dataclass(frozen=True)
class _Footprint:
    states: FrozenSet[ProcessMemberRefIR] = frozenset()
    schedule_slots: FrozenSet[Tuple[str, str]] = frozenset()


def _slot(effect: object) -> Tuple[str, str]:
    key = effect.key
    if isinstance(key, StaticScheduleKeyIR):
        return ("static", key.key.member_id)
    assert isinstance(key, EventIdScheduleKeyIR)
    return ("event_id", key.value.source)


def _combine(left: _Footprint, right: _Footprint, effect: EffectIR) -> _Footprint:
    state_conflicts = left.states & right.states
    if state_conflicts:
        state = sorted(item.member_id for item in state_conflicts)[0]
        raise SchemaError(
            f"transition can define next state {state!r} more than once",
            getattr(effect, "location", None),
        )
    slot_conflicts = left.schedule_slots & right.schedule_slots
    if slot_conflicts:
        _, key = sorted(slot_conflicts)[0]
        raise SchemaError(
            f"transition can mutate schedule key {key!r} more than once",
            getattr(effect, "location", None),
        )
    return _Footprint(
        left.states | right.states,
        left.schedule_slots | right.schedule_slots,
    )


def _sequence(effects: Sequence[EffectIR]) -> Tuple[_Footprint, ...]:
    alternatives: Tuple[_Footprint, ...] = (_Footprint(),)
    for effect in effects:
        effect_alternatives = _effect(effect)
        combined = []
        for existing in alternatives:
            for addition in effect_alternatives:
                combined.append(_combine(existing, addition, effect))
        # Equal footprints carry identical conflict information; collapsing
        # them keeps nested conditional validation bounded by source size.
        alternatives = tuple(dict.fromkeys(combined))
    return alternatives


def _effect(effect: EffectIR) -> Tuple[_Footprint, ...]:
    if isinstance(effect, NextEffectIR):
        return (_Footprint(states=frozenset({effect.state})),)
    if isinstance(effect, (ScheduleEffectIR, CancelEffectIR)):
        return (_Footprint(schedule_slots=frozenset({_slot(effect)})),)
    if isinstance(effect, WhenEffectIR):
        return (_Footprint(), *_sequence(effect.effects))
    if isinstance(effect, BranchEffectIR):
        return tuple(
            footprint
            for case in effect.cases
            for footprint in _sequence(case.effects)
        ) or (_Footprint(),)
    return (_Footprint(),)


def _handler_groups(handlers: Iterable[HandlerIR]):
    result = {}
    for handler in handlers:
        key = (handler.trigger.kind, handler.trigger.member_id)
        result.setdefault(key, []).append(handler)
    return result.values()


def validate_process_ir(process: ProcessIR) -> None:
    """Reject transitions whose simultaneous effects can conflict."""

    for handlers in _handler_groups(process.handlers):
        alternatives: Tuple[_Footprint, ...] = (_Footprint(),)
        for handler in handlers:
            handler_alternatives = _sequence(handler.effects)
            combined = []
            for existing in alternatives:
                for addition in handler_alternatives:
                    combined.append(
                        _combine(existing, addition, handler.effects[-1] if handler.effects else handler)
                    )
            alternatives = tuple(dict.fromkeys(combined))


def possible_handler_footprints(
    process: ProcessIR, trigger: ProcessMemberRefIR
) -> Tuple[Tuple[FrozenSet[ProcessMemberRefIR], FrozenSet[Tuple[str, str]]], ...]:
    """Expose finite transition alternatives for scenario batch validation."""

    handlers = [handler for handler in process.handlers if handler.trigger == trigger]
    alternatives: Tuple[_Footprint, ...] = (_Footprint(),)
    for handler in handlers:
        combined = []
        for existing in alternatives:
            for addition in _sequence(handler.effects):
                combined.append(
                    _Footprint(
                        existing.states | addition.states,
                        existing.schedule_slots | addition.schedule_slots,
                    )
                )
        alternatives = tuple(dict.fromkeys(combined))
    return tuple((item.states, item.schedule_slots) for item in alternatives)
