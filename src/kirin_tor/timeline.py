"""Exact bounded state-vector transitions for deterministic fixed timelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence

import sympy as sp

from .errors import DomainError
from .limits import MAX_CYCLE_ANALYSIS_EVENTS


@dataclass(frozen=True)
class ResourcePool:
    """One bounded numeric state component with passive continuous flow."""

    id: str
    initial: sp.Expr
    maximum: sp.Expr
    regeneration: sp.Expr


@dataclass(frozen=True)
class ChargePool:
    """One action-local pool whose missing charges recover sequentially."""

    initial: int
    maximum: int
    recharge: sp.Expr


@dataclass(frozen=True)
class TimelineAction:
    """One deterministic action with resource and readiness transitions."""

    id: str
    state_id: str
    duration: sp.Expr
    spends: Mapping[str, sp.Expr]
    gains: Mapping[str, sp.Expr]
    cooldown: sp.Expr = sp.Integer(0)
    charges: Optional[ChargePool] = None


def _less(left: sp.Expr, right: sp.Expr) -> bool:
    verdict = sp.simplify(sp.Lt(left, right))
    if verdict in (sp.true, True):
        return True
    if verdict in (sp.false, False):
        return False
    raise DomainError(f"could not compare exact timeline values {left} and {right}")


def _greater_equal(left: sp.Expr, right: sp.Expr) -> bool:
    return not _less(left, right)


def _cap(value: sp.Expr, maximum: sp.Expr) -> sp.Expr:
    return sp.simplify(sp.Min(maximum, value).doit())


def _toward_zero(value: sp.Expr, elapsed: sp.Expr) -> sp.Expr:
    if _greater_equal(elapsed, value):
        return sp.Integer(0)
    return sp.simplify(value - elapsed)


def _action_specs(actions: Sequence[TimelineAction]) -> Dict[str, TimelineAction]:
    specs: Dict[str, TimelineAction] = {}
    for action in actions:
        previous = specs.get(action.state_id)
        if previous is not None and (
            previous.cooldown != action.cooldown or previous.charges != action.charges
        ):
            raise DomainError(
                f"timeline action state {action.state_id!r} has inconsistent readiness rules"
            )
        specs[action.state_id] = action
    return specs


def _initial_state(
    resources: Mapping[str, ResourcePool],
    specs: Mapping[str, TimelineAction],
) -> tuple[Dict[str, sp.Expr], Dict[str, sp.Expr], Dict[str, int], Dict[str, sp.Expr]]:
    resource_state = {
        resource_id: resources[resource_id].initial for resource_id in sorted(resources)
    }
    cooldowns = {
        state_id: sp.Integer(0)
        for state_id, action in sorted(specs.items())
        if action.cooldown != 0
    }
    charge_counts: Dict[str, int] = {}
    charge_remaining: Dict[str, sp.Expr] = {}
    for state_id, action in sorted(specs.items()):
        if action.charges is None:
            continue
        charge_counts[state_id] = action.charges.initial
        charge_remaining[state_id] = (
            action.charges.recharge
            if action.charges.initial < action.charges.maximum
            else sp.Integer(0)
        )
    return resource_state, cooldowns, charge_counts, charge_remaining


def _resource_key(
    resource_ids: Sequence[str], state: Mapping[str, sp.Expr]
) -> tuple[sp.Expr, ...]:
    return tuple(state[resource_id] for resource_id in resource_ids)


def _readiness_key(
    cooldown_ids: Sequence[str],
    charge_ids: Sequence[str],
    cooldowns: Mapping[str, sp.Expr],
    charge_counts: Mapping[str, int],
    charge_remaining: Mapping[str, sp.Expr],
) -> tuple[object, ...]:
    return (
        *(cooldowns[state_id] for state_id in cooldown_ids),
        *(
            value
            for state_id in charge_ids
            for value in (charge_counts[state_id], charge_remaining[state_id])
        ),
    )


def _full_state_key(
    resource_ids: Sequence[str],
    cooldown_ids: Sequence[str],
    charge_ids: Sequence[str],
    state: Mapping[str, sp.Expr],
    cooldowns: Mapping[str, sp.Expr],
    charge_counts: Mapping[str, int],
    charge_remaining: Mapping[str, sp.Expr],
) -> tuple[object, ...]:
    return (
        *_resource_key(resource_ids, state),
        *_readiness_key(
            cooldown_ids,
            charge_ids,
            cooldowns,
            charge_counts,
            charge_remaining,
        ),
    )


def _resource_deficits(
    action: TimelineAction,
    state: Mapping[str, sp.Expr],
) -> list[dict]:
    return [
        {
            "resource": resource_id,
            "available": state[resource_id],
            "required": amount,
        }
        for resource_id, amount in sorted(action.spends.items())
        if _less(state[resource_id], amount)
    ]


def _readiness_deficits(
    action: TimelineAction,
    cooldowns: Mapping[str, sp.Expr],
    charge_counts: Mapping[str, int],
    charge_remaining: Mapping[str, sp.Expr],
) -> list[dict]:
    failures = []
    cooldown = cooldowns.get(action.state_id, sp.Integer(0))
    if cooldown != 0:
        failures.append(
            {
                "kind": "cooldown",
                "action": action.id,
                "remaining": cooldown,
            }
        )
    if action.state_id in charge_counts and charge_counts[action.state_id] == 0:
        failures.append(
            {
                "kind": "charge",
                "action": action.id,
                "available": 0,
                "required": 1,
                "remaining": charge_remaining[action.state_id],
            }
        )
    return failures


def _event(
    event_index: int,
    action_index: int,
    action: TimelineAction,
    action_count: int,
    resource_failures: list[dict],
    readiness_failures: Optional[list[dict]] = None,
) -> dict:
    return {
        "step": event_index + 1,
        "cycle": event_index // action_count + 1,
        "position": action_index + 1,
        "action": action.id,
        # ``failures`` remains the internal compatibility name consumed by the
        # operation renderer for resource-specific fields.
        "failures": resource_failures,
        "readiness_failures": readiness_failures or [],
    }


def _advance_charges(
    elapsed: sp.Expr,
    specs: Mapping[str, TimelineAction],
    charge_counts: Dict[str, int],
    charge_remaining: Dict[str, sp.Expr],
) -> None:
    for state_id in sorted(charge_counts):
        charge = specs[state_id].charges
        assert charge is not None
        remaining_elapsed = elapsed
        while charge_counts[state_id] < charge.maximum and _greater_equal(
            remaining_elapsed, charge_remaining[state_id]
        ):
            remaining_elapsed = sp.simplify(
                remaining_elapsed - charge_remaining[state_id]
            )
            charge_counts[state_id] += 1
            charge_remaining[state_id] = (
                charge.recharge
                if charge_counts[state_id] < charge.maximum
                else sp.Integer(0)
            )
        if charge_counts[state_id] < charge.maximum:
            charge_remaining[state_id] = sp.simplify(
                charge_remaining[state_id] - remaining_elapsed
            )


def _advance_time(
    elapsed: sp.Expr,
    resources: Mapping[str, ResourcePool],
    specs: Mapping[str, TimelineAction],
    state: Dict[str, sp.Expr],
    cooldowns: Dict[str, sp.Expr],
    charge_counts: Dict[str, int],
    charge_remaining: Dict[str, sp.Expr],
) -> None:
    for resource_id, pool in resources.items():
        state[resource_id] = _cap(
            state[resource_id] + pool.regeneration * elapsed,
            pool.maximum,
        )
    for state_id in sorted(cooldowns):
        cooldowns[state_id] = _toward_zero(cooldowns[state_id], elapsed)
    _advance_charges(elapsed, specs, charge_counts, charge_remaining)


def _execute_action(
    action: TimelineAction,
    resources: Mapping[str, ResourcePool],
    specs: Mapping[str, TimelineAction],
    state: Dict[str, sp.Expr],
    cooldowns: Dict[str, sp.Expr],
    charge_counts: Dict[str, int],
    charge_remaining: Dict[str, sp.Expr],
) -> None:
    for resource_id, amount in action.spends.items():
        state[resource_id] = sp.simplify(state[resource_id] - amount)
    if action.state_id in cooldowns:
        cooldowns[action.state_id] = action.cooldown
    if action.state_id in charge_counts:
        charge = specs[action.state_id].charges
        assert charge is not None
        was_full = charge_counts[action.state_id] == charge.maximum
        charge_counts[action.state_id] -= 1
        if was_full:
            charge_remaining[action.state_id] = charge.recharge
    _advance_time(
        action.duration,
        resources,
        specs,
        state,
        cooldowns,
        charge_counts,
        charge_remaining,
    )
    for resource_id, amount in action.gains.items():
        state[resource_id] = _cap(
            state[resource_id] + amount, resources[resource_id].maximum
        )


def analyze_fixed_timeline(
    resources: Mapping[str, ResourcePool],
    actions: Sequence[TimelineAction],
) -> dict:
    """Analyze an exact fixed sequence over bounded resources and action readiness."""

    resource_ids = tuple(sorted(resources))
    if not resource_ids:
        raise DomainError("a timeline requires at least one resource")
    if not actions:
        raise DomainError("a timeline requires at least one action")
    specs = _action_specs(actions)
    cooldown_ids = tuple(
        state_id for state_id in sorted(specs) if specs[state_id].cooldown != 0
    )
    charge_ids = tuple(
        state_id for state_id in sorted(specs) if specs[state_id].charges is not None
    )

    # First prove or disprove no-wait sustainability. An identical readiness
    # phase plus a coordinate-wise non-decreasing resource boundary proves that
    # every later cycle can execute without inserted waits.
    state, cooldowns, charge_counts, charge_remaining = _initial_state(resources, specs)
    boundary_states = {
        _readiness_key(
            cooldown_ids,
            charge_ids,
            cooldowns,
            charge_counts,
            charge_remaining,
        ): dict(state)
    }
    first_no_wait_failure = None
    for event_index in range(MAX_CYCLE_ANALYSIS_EVENTS):
        action_index = event_index % len(actions)
        action = actions[action_index]
        resource_failures = _resource_deficits(action, state)
        readiness_failures = _readiness_deficits(
            action, cooldowns, charge_counts, charge_remaining
        )
        if resource_failures or readiness_failures:
            first_no_wait_failure = _event(
                event_index,
                action_index,
                action,
                len(actions),
                resource_failures,
                readiness_failures,
            )
            break
        _execute_action(
            action,
            resources,
            specs,
            state,
            cooldowns,
            charge_counts,
            charge_remaining,
        )
        if action_index == len(actions) - 1:
            readiness = _readiness_key(
                cooldown_ids,
                charge_ids,
                cooldowns,
                charge_counts,
                charge_remaining,
            )
            previous = boundary_states.get(readiness)
            if previous is not None and all(
                _greater_equal(state[resource_id], previous[resource_id])
                for resource_id in resource_ids
            ):
                return {
                    "cycle_status": "continuous",
                    "first_no_wait_failure": None,
                    "first_wait": None,
                    "blocked_at": None,
                    "occupied_per_cycle": sp.simplify(
                        sum(action.duration for action in actions)
                    ),
                }
            boundary_states[readiness] = dict(state)
    else:
        raise DomainError(
            f"timeline no-wait analysis exceeds {MAX_CYCLE_ANALYSIS_EVENTS} events"
        )

    # Then insert the minimum shared wait. Resources, cooldowns, and sequential
    # recharge all advance during the same wait; the slowest failed constraint
    # determines when the requested action can start.
    state, cooldowns, charge_counts, charge_remaining = _initial_state(resources, specs)
    elapsed = sp.Integer(0)
    total_wait = sp.Integer(0)
    states: dict[tuple[int, tuple[object, ...]], tuple[int, sp.Expr, sp.Expr]] = {}
    first_wait = None
    for event_index in range(MAX_CYCLE_ANALYSIS_EVENTS):
        action_index = event_index % len(actions)
        action = actions[action_index]
        key = (
            action_index,
            _full_state_key(
                resource_ids,
                cooldown_ids,
                charge_ids,
                state,
                cooldowns,
                charge_counts,
                charge_remaining,
            ),
        )
        if key in states:
            previous_event, previous_elapsed, previous_wait = states[key]
            return {
                "cycle_status": "waiting",
                "first_no_wait_failure": first_no_wait_failure,
                "first_wait": first_wait,
                "blocked_at": None,
                "period_steps": event_index - previous_event,
                "period_elapsed": sp.simplify(elapsed - previous_elapsed),
                "period_wait": sp.simplify(total_wait - previous_wait),
            }
        states[key] = (event_index, elapsed, total_wait)

        impossible = []
        for resource_id, amount in sorted(action.spends.items()):
            pool = resources[resource_id]
            if _less(pool.maximum, amount):
                impossible.append(
                    {
                        "resource": resource_id,
                        "reason": "cost_exceeds_maximum",
                        "available": state[resource_id],
                        "required": amount,
                    }
                )
        if impossible:
            return {
                "cycle_status": "blocked",
                "first_no_wait_failure": first_no_wait_failure,
                "first_wait": first_wait,
                "blocked_at": _event(
                    event_index, action_index, action, len(actions), impossible
                ),
            }

        resource_failures = _resource_deficits(action, state)
        readiness_failures = _readiness_deficits(
            action, cooldowns, charge_counts, charge_remaining
        )
        wait_candidates: list[tuple[str, sp.Expr]] = []
        cannot_recover = []
        for failure in resource_failures:
            resource_id = failure["resource"]
            regeneration = resources[resource_id].regeneration
            if regeneration == 0:
                cannot_recover.append(
                    {**failure, "reason": "resource_cannot_recover"}
                )
            else:
                wait_candidates.append(
                    (
                        f"resource:{resource_id}",
                        sp.simplify(
                            (failure["required"] - failure["available"])
                            / regeneration
                        ),
                    )
                )
        if cannot_recover:
            return {
                "cycle_status": "blocked",
                "first_no_wait_failure": first_no_wait_failure,
                "first_wait": first_wait,
                "blocked_at": _event(
                    event_index,
                    action_index,
                    action,
                    len(actions),
                    cannot_recover,
                    readiness_failures,
                ),
            }
        wait_candidates.extend(
            (f"{failure['kind']}:{failure['action']}", failure["remaining"])
            for failure in readiness_failures
        )

        wait = (
            sp.simplify(
                sp.Max(*(candidate for _constraint, candidate in wait_candidates)).doit()
            )
            if wait_candidates
            else sp.Integer(0)
        )
        if wait != 0:
            limiting_constraints = [
                constraint
                for constraint, candidate in wait_candidates
                if sp.simplify(candidate - wait) == 0
            ]
            limiting_resources = [
                constraint.split(":", 1)[1]
                for constraint in limiting_constraints
                if constraint.startswith("resource:")
            ]
            if first_wait is None:
                first_wait = {
                    **_event(
                        event_index,
                        action_index,
                        action,
                        len(actions),
                        resource_failures,
                        readiness_failures,
                    ),
                    "duration": wait,
                    "limiting_resources": limiting_resources,
                    "limiting_constraints": limiting_constraints,
                }
            _advance_time(
                wait,
                resources,
                specs,
                state,
                cooldowns,
                charge_counts,
                charge_remaining,
            )

        elapsed = sp.simplify(elapsed + wait + action.duration)
        total_wait = sp.simplify(total_wait + wait)
        _execute_action(
            action,
            resources,
            specs,
            state,
            cooldowns,
            charge_counts,
            charge_remaining,
        )
    raise DomainError(
        f"timeline wait analysis exceeds {MAX_CYCLE_ANALYSIS_EVENTS} events"
    )
