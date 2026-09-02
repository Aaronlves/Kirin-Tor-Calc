"""Exact bounded state-vector transitions for deterministic fixed timelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence

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
class TimelineAction:
    """One deterministic action: spend at start, gain at finish."""

    id: str
    duration: sp.Expr
    spends: Mapping[str, sp.Expr]
    gains: Mapping[str, sp.Expr]


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


def _state_key(resource_ids: Sequence[str], state: Mapping[str, sp.Expr]) -> tuple[sp.Expr, ...]:
    return tuple(state[resource_id] for resource_id in resource_ids)


def _deficits(
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


def _event(
    event_index: int,
    action_index: int,
    action: TimelineAction,
    action_count: int,
    failures: list[dict],
) -> dict:
    return {
        "step": event_index + 1,
        "cycle": event_index // action_count + 1,
        "position": action_index + 1,
        "action": action.id,
        "failures": failures,
    }


def analyze_fixed_timeline(
    resources: Mapping[str, ResourcePool],
    actions: Sequence[TimelineAction],
) -> dict:
    """Analyze an exact deterministic fixed sequence over a bounded resource vector."""

    resource_ids = tuple(sorted(resources))
    if not resource_ids:
        raise DomainError("a timeline requires at least one resource")
    if not actions:
        raise DomainError("a timeline requires at least one action")

    # First prove or disprove no-wait sustainability. Every component transition
    # is monotone in its own starting value, so a coordinate-wise non-decreasing
    # cycle boundary proves indefinite repetition.
    state: Dict[str, sp.Expr] = {
        resource_id: resources[resource_id].initial for resource_id in resource_ids
    }
    cycle_start = dict(state)
    first_no_wait_failure = None
    for event_index in range(MAX_CYCLE_ANALYSIS_EVENTS):
        action_index = event_index % len(actions)
        action = actions[action_index]
        failures = _deficits(action, state)
        if failures:
            first_no_wait_failure = _event(
                event_index, action_index, action, len(actions), failures
            )
            break
        for resource_id in resource_ids:
            pool = resources[resource_id]
            state[resource_id] = _cap(
                state[resource_id]
                - action.spends.get(resource_id, sp.Integer(0))
                + pool.regeneration * action.duration
                + action.gains.get(resource_id, sp.Integer(0)),
                pool.maximum,
            )
        if action_index == len(actions) - 1:
            if all(
                _greater_equal(state[resource_id], cycle_start[resource_id])
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
            cycle_start = dict(state)
    else:
        raise DomainError(
            f"timeline no-wait analysis exceeds {MAX_CYCLE_ANALYSIS_EVENTS} events"
        )

    # Then insert the minimum shared wait. All resource pools advance during
    # that wait; the slowest deficient pool determines when the action starts.
    state = {
        resource_id: resources[resource_id].initial for resource_id in resource_ids
    }
    elapsed = sp.Integer(0)
    total_wait = sp.Integer(0)
    states: dict[tuple[int, tuple[sp.Expr, ...]], tuple[int, sp.Expr, sp.Expr]] = {}
    first_wait = None
    for event_index in range(MAX_CYCLE_ANALYSIS_EVENTS):
        action_index = event_index % len(actions)
        action = actions[action_index]
        key = (action_index, _state_key(resource_ids, state))
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

        failures = _deficits(action, state)
        wait_candidates: list[tuple[str, sp.Expr]] = []
        cannot_recover = []
        for failure in failures:
            resource_id = failure["resource"]
            regeneration = resources[resource_id].regeneration
            if regeneration == 0:
                cannot_recover.append(
                    {**failure, "reason": "resource_cannot_recover"}
                )
            else:
                wait_candidates.append(
                    (
                        resource_id,
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
                ),
            }

        wait = (
            sp.simplify(sp.Max(*(candidate for _resource, candidate in wait_candidates)).doit())
            if wait_candidates
            else sp.Integer(0)
        )
        if wait != 0:
            limiting = [
                resource_id
                for resource_id, candidate in wait_candidates
                if sp.simplify(candidate - wait) == 0
            ]
            if first_wait is None:
                first_wait = {
                    **_event(event_index, action_index, action, len(actions), failures),
                    "duration": wait,
                    "limiting_resources": limiting,
                }
            for resource_id in resource_ids:
                pool = resources[resource_id]
                state[resource_id] = _cap(
                    state[resource_id] + pool.regeneration * wait,
                    pool.maximum,
                )

        elapsed = sp.simplify(elapsed + wait + action.duration)
        total_wait = sp.simplify(total_wait + wait)
        for resource_id in resource_ids:
            pool = resources[resource_id]
            state[resource_id] = _cap(
                state[resource_id]
                - action.spends.get(resource_id, sp.Integer(0))
                + pool.regeneration * action.duration
                + action.gains.get(resource_id, sp.Integer(0)),
                pool.maximum,
            )
    raise DomainError(
        f"timeline wait analysis exceeds {MAX_CYCLE_ANALYSIS_EVENTS} events"
    )
