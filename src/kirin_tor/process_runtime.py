"""Deterministic exact-time executor for lowered Process scenarios."""

from __future__ import annotations

import copy
import hashlib
import heapq
from collections import defaultdict
from dataclasses import dataclass, field, fields, is_dataclass
from fractions import Fraction
from typing import Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .errors import (
    DomainError,
    InfeasibleDecisionError,
    ProcessExecutionError,
    ProcessFuelError,
    UnsupportedError,
)
from .process_expression import (
    ProcessEventId,
    ProcessValue,
    evaluate_process_expression,
    validate_process_value,
)
from .process_ir import (
    ActionIR,
    BranchEffectIR,
    CancelEffectIR,
    EffectIR,
    EmitEffectIR,
    EventArgumentIR,
    EventIdTypeIR,
    EventParameterIR,
    EventIdScheduleKeyIR,
    EventIdTypeIR,
    EventIR,
    HandlerIR,
    LetEffectIR,
    NextEffectIR,
    NumberTypeIR,
    ProcessIR,
    ProcessMemberRefIR,
    ScheduleEffectIR,
    StateIR,
    StaticScheduleKeyIR,
    SymbolRefIR,
    WhenEffectIR,
)
from .process_model import ExpressionSymbolKind, ProcessMemberKind, Reducer, ScheduleOperation
from .process_crossing import affine_condition_gap
from .scenario_ir import (
    AtScheduleIR,
    CompositeActionIR,
    ConditionDecisionIR,
    ContinuousDecisionIR,
    DecisionScheduleIR,
    EveryScheduleIR,
    EventDecisionIR,
    InstanceMemberRefIR,
    ProcessInstanceIR,
    PolicyIR,
    ScenarioCallIR,
    ScenarioIR,
    ScenarioPhaseIR,
)
from .units import UnitRegistry


DecisionSelector = Callable[[
    int,
    Fraction,
    object,
    Tuple[str, ...],
    Mapping[str, ProcessValue],
    Tuple[Tuple[Fraction, str], ...],
], str]
BranchSelector = Callable[[
    int,
    "RuntimeEvent",
    BranchEffectIR,
    Tuple[Fraction, ...],
    Mapping[SymbolRefIR, ProcessValue],
], int]


def _uses_event_identity_semantics(value: object, seen: set[int]) -> bool:
    """Return whether semantic execution can observe generated event IDs."""

    if isinstance(value, (EventIdTypeIR, EventIdScheduleKeyIR)):
        return True
    identity = id(value)
    if identity in seen:
        return False
    if isinstance(value, dict):
        seen.add(identity)
        return any(
            _uses_event_identity_semantics(item, seen)
            for pair in value.items()
            for item in pair
        )
    if isinstance(value, (tuple, list, set, frozenset)):
        seen.add(identity)
        return any(
            _uses_event_identity_semantics(item, seen) for item in value
        )
    if is_dataclass(value):
        seen.add(identity)
        return any(
            field.name != "location"
            and _uses_event_identity_semantics(
                getattr(value, field.name), seen
            )
            for field in fields(value)
        )
    return False


@dataclass(frozen=True)
class RuntimeEvent:
    id: ProcessEventId
    time: Fraction
    phase: ScenarioPhaseIR
    target: InstanceMemberRefIR
    parameters: Tuple[EventParameterIR, ...]
    arguments: Tuple[Tuple[str, ProcessValue], ...]
    source_ids: Tuple[ProcessEventId, ...]
    fuel_reserved: bool = False
    schedule_slot: Optional[Tuple[str, Tuple[str, str]]] = None


@dataclass(frozen=True)
class ContinuousDecisionChoice:
    schedule_index: int
    time: Fraction
    action_id: str


@dataclass(frozen=True)
class ProcessTraceEntry:
    index: int
    time: Fraction
    phase: str
    kind: str
    event_id: Optional[str] = None
    instance_id: Optional[str] = None
    member_id: Optional[str] = None
    details: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProcessObservationSample:
    index: int
    time: Fraction
    phase: str
    values: Tuple[Tuple[str, ProcessValue], ...]


@dataclass(frozen=True)
class ProcessOutputEvent:
    id: ProcessEventId
    time: Fraction
    phase: str
    instance_id: str
    event_id: str
    arguments: Tuple[Tuple[str, ProcessValue], ...]


@dataclass(frozen=True)
class ProcessRunResult:
    scenario_id: str
    elapsed: Fraction
    stopped: bool
    stop_reason: str
    event_count: int
    decision_count: int
    branch_count: int
    target_reached: bool
    pending_schedule_count: int
    inputs: Tuple[Tuple[str, Tuple[Tuple[str, ProcessValue], ...]], ...]
    states: Tuple[Tuple[str, Tuple[Tuple[str, ProcessValue], ...]], ...]
    observations: Tuple[Tuple[str, ProcessValue], ...]
    observation_samples: Tuple[ProcessObservationSample, ...]
    output_events: Tuple[ProcessOutputEvent, ...]
    decisions: Tuple[Tuple[Fraction, str], ...]
    trace: Tuple[ProcessTraceEntry, ...]


@dataclass
class _InstanceState:
    declaration: ProcessInstanceIR
    inputs: Dict[SymbolRefIR, ProcessValue]
    states: Dict[SymbolRefIR, ProcessValue]


@dataclass(frozen=True)
class _PendingSchedule:
    operation: ScheduleOperation
    instance_id: str
    call: object
    delay: Fraction
    phase: ScenarioPhaseIR
    slot: Tuple[str, Tuple[str, str]]
    origin: RuntimeEvent
    environment: Mapping[SymbolRefIR, ProcessValue]
    location: object = None


@dataclass(frozen=True)
class _PendingCancel:
    slot: Tuple[str, Tuple[str, str]]
    origin: RuntimeEvent
    location: object = None


@dataclass(frozen=True)
class _PendingEmit:
    instance_id: str
    effect: EmitEffectIR
    phase: ScenarioPhaseIR
    origin: RuntimeEvent
    environment: Mapping[SymbolRefIR, ProcessValue]


def _event_id(*parts: object) -> ProcessEventId:
    canonical = "\x1f".join(str(part) for part in parts)
    return ProcessEventId(hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24])


def _input_symbol(process: ProcessIR, item) -> SymbolRefIR:
    return SymbolRefIR(
        process.qualified_id,
        item.ref.member_id,
        ExpressionSymbolKind.INPUT,
        item.value_type,
    )


def _state_symbol(process: ProcessIR, item: StateIR) -> SymbolRefIR:
    return SymbolRefIR(
        process.qualified_id,
        item.ref.member_id,
        ExpressionSymbolKind.STATE,
        item.value_type,
    )


def _phase_map(instance: ProcessInstanceIR) -> Dict[str, ScenarioPhaseIR]:
    return {
        item.process_phase.member.member_id: item.scenario_phase
        for item in instance.phases
    }


def _event_declaration(process: ProcessIR, ref: ProcessMemberRefIR):
    if ref.kind is ProcessMemberKind.ACTION:
        return next(item for item in process.actions if item.ref == ref)
    return next(item for item in process.events if item.ref == ref)


class _CachedExactSignature:
    """Immutable exact tuple with a cached hash for nested memo keys."""

    __slots__ = ("value", "_hash")

    def __init__(self, value: Tuple[object, ...]) -> None:
        self.value = value
        self._hash = hash(value)

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, _CachedExactSignature):
            return NotImplemented
        return self.value == other.value


class DeterministicProcessExecutor:
    """Execute one Scenario using a caller-supplied finite decision selector."""

    def __init__(
        self,
        scenario: ScenarioIR,
        registry: UnitRegistry,
        *,
        selector: Optional[DecisionSelector] = None,
        branch_selector: Optional[BranchSelector] = None,
        reach_target=None,
        initial_state_overrides: Optional[
            Mapping[Tuple[str, str], ProcessValue]
        ] = None,
        input_overrides: Optional[Mapping[Tuple[str, str], ProcessValue]] = None,
        maximum_batches: Optional[int] = None,
        include_trace: bool = True,
        continuous_choices: Sequence[ContinuousDecisionChoice] = (),
    ) -> None:
        self.scenario = scenario
        self.registry = registry
        self.selector = selector
        self.branch_selector = branch_selector
        self.reach_target = reach_target
        self.initial_state_overrides = dict(initial_state_overrides or {})
        self.input_overrides = dict(input_overrides or {})
        self.maximum_batches = maximum_batches
        self.include_trace = include_trace
        self.continuous_choices = tuple(continuous_choices)
        self.instances: Dict[str, _InstanceState] = {}
        self.events: Dict[Tuple[Fraction, int], List[RuntimeEvent]] = defaultdict(list)
        self.decision_points: Dict[
            Tuple[Fraction, int],
            List[Tuple[object, Optional[str], Optional[int]]],
        ] = defaultdict(list)
        self.heap: List[Tuple[Fraction, int]] = []
        self.queued_keys: set[Tuple[Fraction, int]] = set()
        self.canceled: set[ProcessEventId] = set()
        self.schedule_slots: Dict[Tuple[str, Tuple[str, str]], ProcessEventId] = {}
        self.event_count = 0
        self.decision_count = 0
        self.branch_count = 1
        self.branch_decision_count = 0
        self.trace: List[ProcessTraceEntry] = []
        self.observation_samples: List[ProcessObservationSample] = []
        self.output_events: List[ProcessOutputEvent] = []
        self.decisions: List[Tuple[Fraction, str]] = []
        self.current_time = Fraction(0)
        self._initialized = False
        self._complete = False
        self.stopped = False
        self.stop_reason = "horizon"
        self.target_reached = False
        self.condition_truth: Dict[int, bool] = {}
        self.connections = defaultdict(list)
        self._history_sensitive_event_ids = _uses_event_identity_semantics(
            scenario, set()
        )
        self._policy_signature_intern: Dict[
            _CachedExactSignature, _CachedExactSignature
        ] = {}
        for connection in scenario.connections:
            self.connections[
                (connection.source.instance_id, connection.source.member)
            ].append(connection.target)

    def _record(
        self,
        time: Fraction,
        phase: str,
        kind: str,
        *,
        event: Optional[RuntimeEvent] = None,
        instance_id: Optional[str] = None,
        member_id: Optional[str] = None,
        details: Iterable[Tuple[str, object]] = (),
    ) -> None:
        if not self.include_trace:
            return
        self.trace.append(
            ProcessTraceEntry(
                len(self.trace),
                time,
                phase,
                kind,
                event.id.value if event is not None else None,
                instance_id or (event.target.instance_id if event is not None else None),
                member_id or (event.target.member.member_id if event is not None else None),
                tuple((name, _render_value(value)) for name, value in details),
            )
        )

    def _consume_event(self, location=None) -> None:
        self.event_count += 1
        if self.event_count > self.scenario.bounds.maximum_events:
            raise ProcessFuelError(
                "maximum_events exhausted at "
                f"{self.event_count}/{self.scenario.bounds.maximum_events}",
                location,
            )

    def _consume_decision(self, location=None) -> None:
        self.decision_count += 1
        if self.decision_count > self.scenario.bounds.maximum_decisions:
            raise ProcessFuelError(
                "maximum_decisions exhausted at "
                f"{self.decision_count}/{self.scenario.bounds.maximum_decisions}",
                location,
            )

    def _queue_key(self, key: Tuple[Fraction, int]) -> None:
        if key not in self.queued_keys:
            heapq.heappush(self.heap, key)
            self.queued_keys.add(key)

    def _enqueue(self, event: RuntimeEvent) -> None:
        if event.time > self.scenario.bounds.horizon:
            return
        key = (event.time, event.phase.index)
        self.events[key].append(event)
        self._queue_key(key)

    def _initialize_instance(self, instance: ProcessInstanceIR) -> _InstanceState:
        process = instance.process
        inputs: Dict[SymbolRefIR, ProcessValue] = {}
        declarations = {item.ref.member_id: item for item in process.inputs}
        for binding in instance.inputs:
            declaration = declarations[binding.input.member.member_id]
            value = evaluate_process_expression(binding.value, {}, self.registry)
            inputs[_input_symbol(process, declaration)] = value
        pending = [item for item in process.inputs if _input_symbol(process, item) not in inputs]
        while pending:
            progress = False
            remaining = []
            for declaration in pending:
                if declaration.default is None:
                    raise ProcessExecutionError(
                        f"instance {instance.id!r} is missing input {declaration.ref.member_id!r}",
                        declaration.location,
                    )
                if any(
                    reference.kind is ExpressionSymbolKind.INPUT and reference not in inputs
                    for reference in declaration.default.references
                ):
                    remaining.append(declaration)
                    continue
                inputs[_input_symbol(process, declaration)] = evaluate_process_expression(
                    declaration.default, inputs, self.registry
                )
                progress = True
            if not progress and remaining:
                names = ", ".join(item.ref.member_id for item in remaining)
                raise ProcessExecutionError(
                    f"process input defaults are cyclic or unresolved: {names}",
                    remaining[0].location,
                )
            pending = remaining
        for (instance_id, input_id), value in self.input_overrides.items():
            if instance_id != instance.id:
                continue
            declaration = declarations.get(input_id)
            if declaration is None:
                raise ProcessExecutionError(
                    f"input override references unknown input {instance_id}.{input_id}"
                )
            validate_process_value(
                value, declaration.value_type, self.registry, declaration.location
            )
            inputs[_input_symbol(process, declaration)] = value
        for declaration in process.inputs:
            value = inputs[_input_symbol(process, declaration)]
            self._check_bound(value, declaration.bound, inputs, declaration.location)
        for requirement in process.requirements:
            if evaluate_process_expression(requirement, inputs, self.registry) is not True:
                raise ProcessExecutionError(
                    f"instance {instance.id!r} does not satisfy requirement {requirement.source!r}",
                    requirement.location,
                )
        states = {}
        for declaration in process.states:
            value = evaluate_process_expression(declaration.initial, inputs, self.registry)
            self._check_bound(value, declaration.bound, inputs, declaration.location)
            states[_state_symbol(process, declaration)] = value
        return _InstanceState(instance, inputs, states)

    def _check_bound(self, value, bound, environment, location) -> None:
        if bound is None:
            return
        if bound.minimum is not None:
            minimum = evaluate_process_expression(bound.minimum, environment, self.registry)
            if value < minimum:
                raise DomainError("Process value is below its declared minimum", location)
        if bound.maximum is not None:
            maximum = evaluate_process_expression(bound.maximum, environment, self.registry)
            if value > maximum:
                raise DomainError("Process value is above its declared maximum", location)

    def _initialize(self) -> None:
        declared_instance_ids = {item.id for item in self.scenario.instances}
        unknown_input_instances = sorted(
            {
                instance_id
                for instance_id, _input_id in self.input_overrides
                if instance_id not in declared_instance_ids
            }
        )
        if unknown_input_instances:
            raise ProcessExecutionError(
                f"input override references unknown instance {unknown_input_instances[0]!r}"
            )
        self.instances = {
            item.id: self._initialize_instance(item) for item in self.scenario.instances
        }
        for (instance_id, state_id), value in self.initial_state_overrides.items():
            runtime = self.instances.get(instance_id)
            if runtime is None:
                raise ProcessExecutionError(
                    f"initial-state override references unknown instance {instance_id!r}"
                )
            declaration = next(
                (
                    item
                    for item in runtime.declaration.process.states
                    if item.ref.member_id == state_id
                ),
                None,
            )
            if declaration is None:
                raise ProcessExecutionError(
                    f"initial-state override references unknown state {instance_id}.{state_id}"
                )
            validate_process_value(
                value, declaration.value_type, self.registry, declaration.location
            )
            environment = {**runtime.inputs, **runtime.states}
            self._check_bound(value, declaration.bound, environment, declaration.location)
            runtime.states[_state_symbol(runtime.declaration.process, declaration)] = value
        for schedule_index, schedule in enumerate(self.scenario.schedules):
            if isinstance(schedule, AtScheduleIR):
                occurrences = (schedule.time,)
            else:
                assert isinstance(schedule, EveryScheduleIR)
                end = min(self.scenario.bounds.horizon, schedule.end) if schedule.end is not None else self.scenario.bounds.horizon
                values = []
                current = schedule.start
                while current <= end:
                    values.append(current)
                    current += schedule.interval
                occurrences = tuple(values)
            for occurrence_index, time in enumerate(occurrences):
                if time > self.scenario.bounds.horizon:
                    continue
                for send_index, call in enumerate(schedule.sends):
                    event = self._scenario_event(
                        call,
                        time,
                        "external",
                        schedule_index,
                        occurrence_index,
                        send_index,
                        fuel_reserved=False,
                    )
                    self._enqueue(event)
        for schedule in self.scenario.decisions:
            end = min(self.scenario.bounds.horizon, schedule.end) if schedule.end is not None else self.scenario.bounds.horizon
            current = schedule.start
            while current <= end:
                key = (current, schedule.phase.index)
                self.decision_points[key].append((schedule, None, None))
                self._queue_key(key)
                current += schedule.interval
        occurrence_counts: Dict[int, int] = defaultdict(int)
        previous_choice = None
        for plan_choice_index, choice in enumerate(self.continuous_choices):
            schedule = (
                self.scenario.continuous_decisions[choice.schedule_index]
                if 0 <= choice.schedule_index < len(self.scenario.continuous_decisions)
                else None
            )
            ordering_key = (
                choice.time,
                schedule.phase.index if schedule is not None else -1,
                choice.schedule_index,
            )
            if previous_choice is not None and ordering_key < previous_choice:
                raise ProcessExecutionError(
                    "continuous decision choices must be ordered by time, phase, and declaration"
                )
            previous_choice = ordering_key
            if not 0 <= choice.schedule_index < len(self.scenario.continuous_decisions):
                raise ProcessExecutionError(
                    f"unknown continuous decision declaration {choice.schedule_index}"
                )
            assert schedule is not None
            if not schedule.start <= choice.time <= schedule.end:
                raise ProcessExecutionError(
                    "continuous decision time is outside its declared interval",
                    schedule.location,
                )
            if choice.action_id not in schedule.action_ids:
                raise ProcessExecutionError(
                    f"continuous decision selected unknown action {choice.action_id!r}",
                    schedule.location,
                )
            occurrence_counts[choice.schedule_index] += 1
            if occurrence_counts[choice.schedule_index] > schedule.maximum_occurrences:
                raise ProcessExecutionError(
                    "continuous decision exceeds its maximum occurrence count",
                    schedule.location,
                )
            key = (choice.time, schedule.phase.index)
            self.decision_points[key].append(
                (schedule, choice.action_id, plan_choice_index)
            )
            self._queue_key(key)
        self._record(Fraction(0), "initial", "initialized")
        self._sample("initial")
        for index, schedule in enumerate(self.scenario.condition_decisions):
            value = evaluate_process_expression(
                schedule.condition, self._scenario_values(), self.registry
            )
            assert isinstance(value, bool)
            self.condition_truth[index] = value
            if value:
                self._queue_condition_decision(index, schedule, -1, "initial")

    def _scenario_values(self) -> Dict[SymbolRefIR, ProcessValue]:
        result: Dict[SymbolRefIR, ProcessValue] = {}
        symbols = {item.id: item for item in self.scenario.observation_symbols}
        for instance_id, runtime in self.instances.items():
            environment = {**runtime.inputs, **runtime.states}
            for observation in runtime.declaration.process.observations:
                name = f"{instance_id}.{observation.ref.member_id}"
                result[symbols[name]] = evaluate_process_expression(
                    observation.value, environment, self.registry
                )
        result[symbols["elapsed"]] = self.current_time
        result[symbols["event_count"]] = Fraction(self.event_count)
        result[symbols["decision_count"]] = Fraction(self.decision_count)
        result[symbols["horizon"]] = self.scenario.bounds.horizon
        return result

    def _scenario_values_after(
        self, elapsed: Fraction
    ) -> Dict[SymbolRefIR, ProcessValue]:
        future_states = {
            instance_id: dict(runtime.states)
            for instance_id, runtime in self.instances.items()
        }
        for instance_id, runtime in self.instances.items():
            environment = {**runtime.inputs, **runtime.states}
            for flow in runtime.declaration.process.flows:
                state = next(
                    item
                    for item in runtime.declaration.process.states
                    if item.ref == flow.state
                )
                state_symbol = _state_symbol(runtime.declaration.process, state)
                future_states[instance_id][state_symbol] = evaluate_process_expression(
                    flow.value,
                    {
                        **environment,
                        flow.current_symbol: runtime.states[state_symbol],
                        flow.elapsed_symbol: elapsed,
                    },
                    self.registry,
                )
        result: Dict[SymbolRefIR, ProcessValue] = {}
        symbols = {item.id: item for item in self.scenario.observation_symbols}
        for instance_id, runtime in self.instances.items():
            environment = {**runtime.inputs, **future_states[instance_id]}
            for observation in runtime.declaration.process.observations:
                name = f"{instance_id}.{observation.ref.member_id}"
                result[symbols[name]] = evaluate_process_expression(
                    observation.value, environment, self.registry
                )
        result[symbols["elapsed"]] = self.current_time + elapsed
        result[symbols["event_count"]] = Fraction(self.event_count)
        result[symbols["decision_count"]] = Fraction(self.decision_count)
        result[symbols["horizon"]] = self.scenario.bounds.horizon
        return result

    def _next_affine_crossing(
        self, limit: Fraction
    ) -> Optional[Tuple[Fraction, int, ConditionDecisionIR]]:
        if not self.scenario.condition_decisions:
            return None
        span = limit - self.current_time
        if span <= 0:
            return None
        current_values = self._scenario_values()
        future_values = self._scenario_values_after(span)
        candidates = []
        for index, schedule in enumerate(self.scenario.condition_decisions):
            if self.condition_truth[index] or not schedule.continuous_crossing:
                continue
            start_gap = affine_condition_gap(
                schedule.condition, current_values, self.registry
            )
            end_gap = affine_condition_gap(
                schedule.condition, future_values, self.registry
            )
            if start_gap < 0 <= end_gap and end_gap != start_gap:
                offset = span * (-start_gap) / (end_gap - start_gap)
                if 0 < offset <= span:
                    candidates.append((self.current_time + offset, index, schedule))
        return min(candidates, default=None, key=lambda item: (item[0], item[1]))

    def _queue_affine_crossing(
        self, time: Fraction, index: int, schedule: ConditionDecisionIR
    ) -> None:
        key = (time, schedule.phase.index)
        self.decision_points[key].append((schedule, None, None))
        self._queue_key(key)
        self.condition_truth[index] = True
        self._record(
            time,
            "flow",
            "condition_crossing",
            details=(("condition", index), ("target_phase", schedule.phase.id)),
        )

    def _synchronize_flow_conditions(self) -> None:
        if not self.scenario.condition_decisions:
            return
        values = self._scenario_values()
        for index, schedule in enumerate(self.scenario.condition_decisions):
            current = evaluate_process_expression(
                schedule.condition, values, self.registry
            )
            assert isinstance(current, bool)
            previous = self.condition_truth[index]
            if current == previous:
                continue
            if not schedule.continuous_crossing:
                raise UnsupportedError(
                    "condition changed between events under a flow that is not proven affine",
                    schedule.location,
                )
            if current and not previous:
                raise ProcessExecutionError(
                    "affine condition crossing was not scheduled at its exact root",
                    schedule.location,
                )
            self.condition_truth[index] = current

    def _sample(self, phase: str) -> None:
        values = self._scenario_values()
        self.observation_samples.append(
            ProcessObservationSample(
                len(self.observation_samples),
                self.current_time,
                phase,
                tuple(
                    sorted(
                        ((symbol.id, value) for symbol, value in values.items()),
                        key=lambda item: item[0],
                    )
                ),
            )
        )

    def _queue_dynamic_decision(
        self,
        schedule: object,
        source_phase_index: int,
        source_phase: str,
        kind: str,
    ) -> None:
        target_phase = schedule.phase
        if target_phase.index <= source_phase_index:
            raise ProcessExecutionError(
                f"{kind} decision phase {target_phase.id!r} must follow triggering phase {source_phase!r}",
                schedule.location,
            )
        key = (self.current_time, target_phase.index)
        self.decision_points[key].append((schedule, None, None))
        self._queue_key(key)
        self._record(
            self.current_time,
            source_phase,
            "decision_trigger",
            details=(("source", kind), ("target_phase", target_phase.id)),
        )

    def _queue_condition_decision(
        self,
        index: int,
        schedule: ConditionDecisionIR,
        source_phase_index: int,
        source_phase: str,
    ) -> None:
        self._queue_dynamic_decision(
            schedule, source_phase_index, source_phase, f"condition[{index}]"
        )

    def _update_condition_decisions(
        self, source_phase_index: int, source_phase: str
    ) -> None:
        if not self.scenario.condition_decisions:
            return
        values = self._scenario_values()
        for index, schedule in enumerate(self.scenario.condition_decisions):
            current = evaluate_process_expression(
                schedule.condition, values, self.registry
            )
            assert isinstance(current, bool)
            previous = self.condition_truth[index]
            self.condition_truth[index] = current
            if current and not previous:
                self._queue_condition_decision(
                    index, schedule, source_phase_index, source_phase
                )

    def _trigger_event_decisions(self, event: RuntimeEvent) -> None:
        for schedule in self.scenario.event_decisions:
            if schedule.source == event.target:
                self._queue_dynamic_decision(
                    schedule,
                    event.phase.index,
                    event.phase.id,
                    f"event:{event.target.instance_id}.{event.target.member.member_id}",
                )

    def _scenario_event(
        self,
        call: ScenarioCallIR,
        time: Fraction,
        *identity: object,
        fuel_reserved: bool,
    ) -> RuntimeEvent:
        values = self._scenario_values() if self.instances else {}
        arguments = tuple(
            (
                argument.parameter_id,
                evaluate_process_expression(argument.value, values, self.registry),
            )
            for argument in call.arguments
        )
        event_id = _event_id(
            self.scenario.qualified_id,
            *identity,
            time,
            call.phase.index,
            call.target.instance_id,
            call.target.member.member_id,
        )
        return RuntimeEvent(
            event_id,
            time,
            call.phase,
            call.target,
            call.parameters,
            arguments,
            (event_id,),
            fuel_reserved,
        )

    def _advance(self, time: Fraction) -> None:
        if time < self.current_time:
            raise ProcessExecutionError("event queue moved backward in time")
        elapsed = time - self.current_time
        if elapsed == 0:
            return
        updates = []
        for instance_id, runtime in self.instances.items():
            environment = {**runtime.inputs, **runtime.states}
            for flow in runtime.declaration.process.flows:
                state = next(
                    item
                    for item in runtime.declaration.process.states
                    if item.ref == flow.state
                )
                state_symbol = _state_symbol(runtime.declaration.process, state)
                local = {
                    **environment,
                    flow.current_symbol: runtime.states[state_symbol],
                    flow.elapsed_symbol: elapsed,
                }
                value = evaluate_process_expression(flow.value, local, self.registry)
                updates.append((runtime, state, state_symbol, value))
        for runtime, declaration, symbol, value in updates:
            environment = {**runtime.inputs, **runtime.states}
            self._check_bound(value, declaration.bound, environment, declaration.location)
            runtime.states[symbol] = value
            self._record(
                time,
                "flow",
                "flow",
                instance_id=runtime.declaration.id,
                member_id=declaration.ref.member_id,
                details=(("elapsed", elapsed), ("value", value)),
            )
        self.current_time = time
        self._sample("flow")

    def _available_actions(
        self, schedule: object, values: Mapping[SymbolRefIR, ProcessValue]
    ) -> Tuple[str, ...]:
        declarations = {item.id: item for item in self.scenario.actions}
        result = []
        for action_id in schedule.action_ids:
            action = declarations[action_id]
            if (
                action.guard is None
                or evaluate_process_expression(action.guard, values, self.registry)
                is True
            ) and self._process_action_guards_hold(action, values):
                result.append(action_id)
        if getattr(schedule, "allow_wait", False):
            result.append("wait")
        return tuple(result)

    def _process_action_guards_hold(
        self,
        action: CompositeActionIR,
        scenario_values: Mapping[SymbolRefIR, ProcessValue],
    ) -> bool:
        for call in action.sends:
            if call.target.member.kind is not ProcessMemberKind.ACTION:
                continue
            runtime = self.instances[call.target.instance_id]
            declaration = _event_declaration(
                runtime.declaration.process, call.target.member
            )
            assert isinstance(declaration, ActionIR)
            if declaration.guard is None:
                continue
            payload = {
                argument.parameter_id: evaluate_process_expression(
                    argument.value, scenario_values, self.registry
                )
                for argument in call.arguments
            }
            environment = {**runtime.inputs, **runtime.states}
            for parameter in declaration.parameters:
                environment[
                    SymbolRefIR(
                        f"{runtime.declaration.process.qualified_id}.{declaration.ref.member_id}",
                        parameter.id,
                        ExpressionSymbolKind.EVENT_PARAMETER,
                        parameter.value_type,
                    )
                ] = payload[parameter.id]
            if evaluate_process_expression(
                declaration.guard, environment, self.registry
            ) is not True:
                return False
        return True

    def _choose(
        self,
        time: Fraction,
        schedule: object,
        forced_choice: Optional[str] = None,
        plan_choice_index: Optional[int] = None,
    ) -> Tuple[str, Tuple[RuntimeEvent, ...]]:
        self._consume_decision(schedule.location)
        values = self._scenario_values()
        available = self._available_actions(schedule, values)
        if not available:
            if forced_choice is not None:
                raise InfeasibleDecisionError(
                    "searched decision occurrence has no available action",
                    schedule.location,
                    plan_choice_index=plan_choice_index,
                )
            raise ProcessExecutionError("decision has no available action", schedule.location)
        if forced_choice is not None:
            choice = forced_choice
        elif self.selector is None:
            if len(available) != 1:
                raise ProcessExecutionError(
                    "run requires an explicit policy when a decision has multiple available choices",
                    schedule.location,
                )
            choice = available[0]
        else:
            choice = self.selector(
                self.decision_count - 1,
                time,
                schedule,
                available,
                {symbol.id: value for symbol, value in values.items()},
                tuple(self.decisions),
            )
        if choice not in available:
            if forced_choice is not None:
                raise InfeasibleDecisionError(
                    f"searched action {choice!r} is unavailable; available: "
                    + ", ".join(available),
                    schedule.location,
                    plan_choice_index=plan_choice_index,
                )
            raise ProcessExecutionError(
                f"policy selected unavailable action {choice!r}; available: "
                + ", ".join(available),
                schedule.location,
            )
        self.decisions.append((time, choice))
        self._record(
            time,
            schedule.phase.id,
            "decision",
            member_id=choice,
            details=(("available", ",".join(available)),),
        )
        if choice == "wait":
            return choice, ()
        action = next(item for item in self.scenario.actions if item.id == choice)
        events = []
        for index, call in enumerate(action.sends):
            self._consume_event(call.location)
            events.append(
                self._scenario_event(
                    call,
                    time,
                    "decision",
                    self.decision_count - 1,
                    choice,
                    index,
                    fuel_reserved=True,
                )
            )
        return choice, tuple(events)

    def _reduce(self, events: Sequence[RuntimeEvent]) -> Tuple[RuntimeEvent, ...]:
        grouped: Dict[Tuple[str, ProcessMemberRefIR], List[RuntimeEvent]] = defaultdict(list)
        for event in events:
            grouped[(event.target.instance_id, event.target.member)].append(event)
        result = []
        for group in grouped.values():
            group.sort(key=lambda item: item.id.value)
            first = group[0]
            if len(group) == 1:
                result.append(first)
                continue
            parameters = {item.id: item for item in first.parameters}
            payloads = [dict(item.arguments) for item in group]
            arguments = []
            for parameter_id, parameter in parameters.items():
                values = [payload[parameter_id] for payload in payloads]
                if parameter.reducer is None:
                    if any(value != values[0] for value in values[1:]):
                        raise ProcessExecutionError(
                            f"unreduced parameter {parameter_id!r} has unequal batch values",
                            parameter.location,
                        )
                    value = values[0]
                elif parameter.reducer is Reducer.SUM:
                    value = sum(values, Fraction(0))
                elif parameter.reducer is Reducer.MIN:
                    value = min(values)
                elif parameter.reducer is Reducer.MAX:
                    value = max(values)
                elif parameter.reducer is Reducer.ALL:
                    value = all(values)
                else:
                    value = any(values)
                validate_process_value(value, parameter.value_type, self.registry)
                arguments.append((parameter_id, value))
            sources = tuple(
                sorted(
                    (source for event in group for source in event.source_ids),
                    key=lambda item: item.value,
                )
            )
            merged_id = _event_id(
                "merged",
                first.target.instance_id,
                first.target.member.member_id,
                first.time,
                first.phase.index,
                *(item.value for item in sources),
            )
            result.append(
                RuntimeEvent(
                    merged_id,
                    first.time,
                    first.phase,
                    first.target,
                    first.parameters,
                    tuple(arguments),
                    sources,
                    True,
                )
            )
        return tuple(
            sorted(
                result,
                key=lambda item: (
                    item.target.instance_id,
                    item.target.member.member_id,
                    item.id.value,
                ),
            )
        )

    def _event_environment(
        self, runtime: _InstanceState, event: RuntimeEvent, handler: HandlerIR
    ) -> Dict[SymbolRefIR, ProcessValue]:
        result = {**runtime.inputs, **runtime.states}
        payload = dict(event.arguments)
        for symbol in handler.parameter_symbols:
            result[symbol] = payload[symbol.id]
        process_id = runtime.declaration.process.qualified_id
        result[
            SymbolRefIR(
                process_id,
                "event.id",
                ExpressionSymbolKind.EVENT_CONTEXT,
                EventIdTypeIR(),
            )
        ] = event.id
        result[
            SymbolRefIR(
                process_id,
                "event.time",
                ExpressionSymbolKind.EVENT_CONTEXT,
                NumberTypeIR("second", self.registry.parse_unit("second")),
            )
        ] = event.time
        return result

    def _run_effects(
        self,
        runtime: _InstanceState,
        event: RuntimeEvent,
        effects: Sequence[EffectIR],
        environment: MutableMapping[SymbolRefIR, ProcessValue],
        writes: MutableMapping[Tuple[str, ProcessMemberRefIR], ProcessValue],
        schedules: List[object],
        emits: List[_PendingEmit],
    ) -> None:
        process = runtime.declaration.process
        state_declarations = {item.ref: item for item in process.states}
        for effect in effects:
            if isinstance(effect, LetEffectIR):
                environment[effect.symbol] = evaluate_process_expression(
                    effect.value, environment, self.registry
                )
            elif isinstance(effect, NextEffectIR):
                key = (runtime.declaration.id, effect.state)
                if key in writes:
                    raise ProcessExecutionError(
                        f"batch writes state {effect.state.member_id!r} more than once",
                        effect.location,
                    )
                value = evaluate_process_expression(
                    effect.value, environment, self.registry
                )
                validate_process_value(
                    value,
                    state_declarations[effect.state].value_type,
                    self.registry,
                    effect.location,
                )
                writes[key] = value
            elif isinstance(effect, WhenEffectIR):
                if evaluate_process_expression(
                    effect.condition, environment, self.registry
                ) is True:
                    nested = dict(environment)
                    self._run_effects(
                        runtime,
                        event,
                        effect.effects,
                        nested,
                        writes,
                        schedules,
                        emits,
                    )
            elif isinstance(effect, BranchEffectIR):
                probabilities = tuple(
                    evaluate_process_expression(
                        case.probability, environment, self.registry
                    )
                    for case in effect.cases
                )
                if any(
                    not isinstance(probability, Fraction)
                    or probability < 0
                    or probability > 1
                    for probability in probabilities
                ) or sum(probabilities, Fraction(0)) != 1:
                    raise ProcessExecutionError(
                        f"branch {effect.id!r} probabilities must be exact values in 0..1 summing to 1",
                        effect.location,
                    )
                if self.branch_selector is None:
                    raise UnsupportedError(
                        "deterministic run cannot execute a random Process branch",
                        effect.location,
                    )
                branch_index = self.branch_selector(
                    self.branch_decision_count,
                    event,
                    effect,
                    probabilities,
                    dict(environment),
                )
                if not isinstance(branch_index, int) or not 0 <= branch_index < len(effect.cases):
                    raise ProcessExecutionError(
                        f"branch selector returned invalid case {branch_index!r}",
                        effect.location,
                    )
                if probabilities[branch_index] == 0:
                    raise ProcessExecutionError(
                        "branch selector chose a zero-probability case", effect.location
                    )
                self.branch_decision_count += 1
                self._record(
                    event.time,
                    event.phase.id,
                    "branch",
                    event=event,
                    member_id=effect.id,
                    details=(
                        ("mode", effect.mode.value),
                        ("case", branch_index),
                        ("probability", probabilities[branch_index]),
                    ),
                )
                nested = dict(environment)
                self._run_effects(
                    runtime,
                    event,
                    effect.cases[branch_index].effects,
                    nested,
                    writes,
                    schedules,
                    emits,
                )
            elif isinstance(effect, EmitEffectIR):
                phase = (
                    event.phase
                    if effect.phase is None
                    else _phase_map(runtime.declaration)[effect.phase.member_id]
                )
                if phase.index <= event.phase.index and effect.phase is not None:
                    raise ProcessExecutionError(
                        "current-time emission must use a later phase", effect.location
                    )
                emits.append(
                    _PendingEmit(
                        runtime.declaration.id,
                        effect,
                        phase,
                        event,
                        dict(environment),
                    )
                )
            elif isinstance(effect, ScheduleEffectIR):
                delay = evaluate_process_expression(
                    effect.delay, environment, self.registry
                )
                assert isinstance(delay, Fraction)
                if delay <= 0:
                    raise ProcessExecutionError(
                        "scheduled Process events require a positive delay",
                        effect.location,
                    )
                if isinstance(effect.key, StaticScheduleKeyIR):
                    key = ("static", effect.key.key.member_id)
                else:
                    assert isinstance(effect.key, EventIdScheduleKeyIR)
                    value = evaluate_process_expression(
                        effect.key.value, environment, self.registry
                    )
                    assert isinstance(value, ProcessEventId)
                    key = ("event_id", value.value)
                schedules.append(
                    _PendingSchedule(
                        effect.operation,
                        runtime.declaration.id,
                        effect.call,
                        delay,
                        _phase_map(runtime.declaration)[effect.phase.member_id],
                        (runtime.declaration.id, key),
                        event,
                        dict(environment),
                        effect.location,
                    )
                )
            elif isinstance(effect, CancelEffectIR):
                if isinstance(effect.key, StaticScheduleKeyIR):
                    key = ("static", effect.key.key.member_id)
                else:
                    value = evaluate_process_expression(
                        effect.key.value, environment, self.registry
                    )
                    assert isinstance(value, ProcessEventId)
                    key = ("event_id", value.value)
                schedules.append(
                    _PendingCancel(
                        (runtime.declaration.id, key), event, effect.location
                    )
                )
            else:
                raise ProcessExecutionError(
                    f"unsupported Process effect {type(effect).__name__}"
                )

    def _process_event(
        self,
        event: RuntimeEvent,
        writes,
        schedules,
        emits,
    ) -> None:
        runtime = self.instances[event.target.instance_id]
        declaration = _event_declaration(runtime.declaration.process, event.target.member)
        handlers = [
            item
            for item in runtime.declaration.process.handlers
            if item.trigger == event.target.member
        ]
        if isinstance(declaration, ActionIR) and declaration.guard is not None:
            environment = {**runtime.inputs, **runtime.states}
            payload = dict(event.arguments)
            parameter_symbols = (
                handlers[0].parameter_symbols
                if handlers
                else tuple(
                    SymbolRefIR(
                        f"{runtime.declaration.process.qualified_id}.{declaration.ref.member_id}",
                        parameter.id,
                        ExpressionSymbolKind.EVENT_PARAMETER,
                        parameter.value_type,
                    )
                    for parameter in declaration.parameters
                )
            )
            for symbol in parameter_symbols:
                environment[symbol] = payload[symbol.id]
            if evaluate_process_expression(
                declaration.guard, environment, self.registry
            ) is not True:
                raise ProcessExecutionError(
                    f"Process action {declaration.ref.member_id!r} is unavailable",
                    declaration.location,
                )
        if not handlers:
            self._record(event.time, event.phase.id, "no_op", event=event)
            return
        for handler in handlers:
            environment = self._event_environment(runtime, event, handler)
            if handler.guard is not None and evaluate_process_expression(
                handler.guard, environment, self.registry
            ) is not True:
                self._record(event.time, event.phase.id, "guard_false", event=event)
                continue
            self._run_effects(
                runtime,
                event,
                handler.effects,
                environment,
                writes,
                schedules,
                emits,
            )
            self._record(
                event.time,
                event.phase.id,
                "handled",
                event=event,
                details=(("sources", ",".join(item.value for item in event.source_ids)),),
            )

    def _apply_writes(self, writes, time: Fraction, phase: ScenarioPhaseIR) -> None:
        for (instance_id, ref), value in sorted(
            writes.items(), key=lambda item: (item[0][0], item[0][1].member_id)
        ):
            runtime = self.instances[instance_id]
            declaration = next(
                item for item in runtime.declaration.process.states if item.ref == ref
            )
            symbol = _state_symbol(runtime.declaration.process, declaration)
            environment = {**runtime.inputs, **runtime.states}
            self._check_bound(value, declaration.bound, environment, declaration.location)
            old = runtime.states[symbol]
            runtime.states[symbol] = value
            self._record(
                time,
                phase.id,
                "state",
                instance_id=instance_id,
                member_id=ref.member_id,
                details=(("old", old), ("new", value)),
            )

    def _scheduled_event(self, pending: _PendingSchedule) -> RuntimeEvent:
        runtime = self.instances[pending.instance_id]
        declaration = next(
            item
            for item in runtime.declaration.process.events
            if item.ref == pending.call.event
        )
        arguments = tuple(
            (
                argument.parameter_id,
                evaluate_process_expression(
                    argument.value, pending.environment, self.registry
                ),
            )
            for argument in pending.call.arguments
        )
        time = pending.origin.time + pending.delay
        identity = _event_id(
            "scheduled",
            pending.origin.id.value,
            pending.instance_id,
            pending.call.event.member_id,
            time,
            pending.phase.index,
            pending.slot[1][0],
            pending.slot[1][1],
        )
        return RuntimeEvent(
            identity,
            time,
            pending.phase,
            InstanceMemberRefIR(
                self.scenario.qualified_id,
                pending.instance_id,
                pending.call.event,
            ),
            declaration.parameters,
            arguments,
            (pending.origin.id,),
            True,
            pending.slot,
        )

    def _apply_schedules(self, changes: Sequence[object], phase: ScenarioPhaseIR) -> None:
        touched = set()
        for change in changes:
            if change.slot in touched:
                raise ProcessExecutionError(
                    f"batch mutates schedule slot {change.slot[1][1]!r} more than once",
                    change.location,
                )
            touched.add(change.slot)
        for change in changes:
            existing = self.schedule_slots.get(change.slot)
            if isinstance(change, _PendingCancel):
                if existing is not None:
                    self.canceled.add(existing)
                    del self.schedule_slots[change.slot]
                self._record(
                    change.origin.time,
                    phase.id,
                    "cancel",
                    event=change.origin,
                    details=(("key", change.slot[1][1]), ("found", existing is not None)),
                )
                continue
            assert isinstance(change, _PendingSchedule)
            if change.operation is ScheduleOperation.SCHEDULE and existing is not None:
                raise ProcessExecutionError(
                    f"schedule key {change.slot[1][1]!r} is already occupied",
                    change.location,
                )
            if existing is not None:
                self.canceled.add(existing)
            self._consume_event(change.location)
            event = self._scheduled_event(change)
            self.schedule_slots[change.slot] = event.id
            self._enqueue(event)
            self._record(
                change.origin.time,
                phase.id,
                change.operation.value,
                event=event,
                details=(
                    ("key", change.slot[1][1]),
                    ("replaced", existing.value if existing is not None else ""),
                ),
            )

    def _apply_emits(self, emits: Sequence[_PendingEmit]) -> None:
        for index, pending in enumerate(emits):
            runtime = self.instances[pending.instance_id]
            declaration = next(
                item
                for item in runtime.declaration.process.events
                if item.ref == pending.effect.call.event
            )
            arguments = tuple(
                (
                    argument.parameter_id,
                    evaluate_process_expression(
                        argument.value, pending.environment, self.registry
                    ),
                )
                for argument in pending.effect.call.arguments
            )
            self._consume_event(pending.effect.location)
            event = RuntimeEvent(
                _event_id(
                    "emit",
                    pending.origin.id.value,
                    index,
                    pending.instance_id,
                    declaration.ref.member_id,
                    pending.phase.index,
                ),
                pending.origin.time,
                pending.phase,
                InstanceMemberRefIR(
                    self.scenario.qualified_id,
                    pending.instance_id,
                    declaration.ref,
                ),
                declaration.parameters,
                arguments,
                (pending.origin.id,),
                True,
            )
            self._record(event.time, event.phase.id, "emit", event=event)
            if declaration.direction.value == "internal":
                self._enqueue(event)
            elif declaration.direction.value == "output":
                self.output_events.append(
                    ProcessOutputEvent(
                        event.id,
                        event.time,
                        event.phase.id,
                        pending.instance_id,
                        declaration.ref.member_id,
                        event.arguments,
                    )
                )
                self._trigger_event_decisions(event)
                targets = self.connections.get(
                    (pending.instance_id, declaration.ref), ()
                )
                for target_index, target in enumerate(targets):
                    self._consume_event(pending.effect.location)
                    target_process = self.instances[target.instance_id].declaration.process
                    target_declaration = next(
                        item for item in target_process.events if item.ref == target.member
                    )
                    routed = RuntimeEvent(
                        _event_id("route", event.id.value, target_index, target.instance_id),
                        event.time,
                        event.phase,
                        target,
                        target_declaration.parameters,
                        event.arguments,
                        (event.id,),
                        True,
                    )
                    self._enqueue(routed)
                    self._record(routed.time, routed.phase.id, "route", event=routed)

    def _check_stop(self, phase: str) -> bool:
        if self.reach_target is not None and evaluate_process_expression(
            self.reach_target, self._scenario_values(), self.registry
        ) is True:
            self.target_reached = True
            self.stopped = True
            self.stop_reason = "target"
            self._record(self.current_time, phase, "target")
            return True
        if self.scenario.stop is None:
            return False
        if evaluate_process_expression(
            self.scenario.stop, self._scenario_values(), self.registry
        ) is True:
            self.stopped = True
            self.stop_reason = "condition"
            self._record(self.current_time, phase, "stop")
            return True
        return False

    def start(self) -> None:
        """Initialize the executor exactly once without consuming a batch."""

        if self._initialized:
            return
        self._initialize()
        self._initialized = True
        if self._check_stop("initial"):
            self._complete = True

    def run_next_batch(self) -> bool:
        """Process one exact time/phase batch, returning whether one was run."""

        self.start()
        if self._complete or self.stopped:
            return False
        while True:
            limit = self.heap[0][0] if self.heap else self.scenario.bounds.horizon
            crossing = self._next_affine_crossing(limit)
            if crossing is None:
                break
            self._queue_affine_crossing(*crossing)
        if not self.heap:
            if self.current_time < self.scenario.bounds.horizon:
                self._advance(self.scenario.bounds.horizon)
                self._synchronize_flow_conditions()
                self._check_stop("horizon")
            self._complete = True
            return False
        time, phase_index = heapq.heappop(self.heap)
        key = (time, phase_index)
        self.queued_keys.discard(key)
        if time > self.scenario.bounds.horizon:
            self._complete = True
            return False
        self._advance(time)
        self._synchronize_flow_conditions()
        phase = self.scenario.phases[phase_index]
        events = [
            event
            for event in self.events.pop(key, ())
            if event.id not in self.canceled
        ]
        for event in events:
            if event.schedule_slot is not None and self.schedule_slots.get(
                event.schedule_slot
            ) == event.id:
                del self.schedule_slots[event.schedule_slot]
            if not event.fuel_reserved:
                self._consume_event(event.target.member)
        decisions = self.decision_points.pop(key, ())
        for decision, forced_choice, plan_choice_index in decisions:
            _choice, action_events = self._choose(
                time, decision, forced_choice, plan_choice_index
            )
            events.extend(action_events)
        if events:
            writes = {}
            schedules: List[object] = []
            emits: List[_PendingEmit] = []
            reduced_events = self._reduce(events)
            for event in reduced_events:
                self._process_event(event, writes, schedules, emits)
            self._apply_writes(writes, time, phase)
            self._apply_schedules(schedules, phase)
            self._apply_emits(emits)
            for event in reduced_events:
                self._trigger_event_decisions(event)
        self._sample(phase.id)
        self._update_condition_decisions(phase.index, phase.id)
        if self._check_stop(phase.id):
            self._complete = True
        return True

    @property
    def is_complete(self) -> bool:
        return self._complete

    def result(self) -> ProcessRunResult:
        if not self._initialized:
            raise ProcessExecutionError(
                "Process result requires an initialized executor"
            )
        return self._result()

    def run(self) -> ProcessRunResult:
        self.start()
        if self._complete:
            return self._result()
        if self.maximum_batches == 0:
            self.stop_reason = "batch_limit"
            return self._result()
        if self.stop_reason == "batch_limit":
            self.stop_reason = "horizon"
        processed_batches = 0
        while not self._complete:
            if not self.run_next_batch():
                break
            processed_batches += 1
            if (
                self.maximum_batches is not None
                and processed_batches >= self.maximum_batches
            ):
                self.stop_reason = "batch_limit"
                break
        return self._result()

    def _result(self) -> ProcessRunResult:
        observations = self._scenario_values()
        inputs = tuple(
            (
                instance_id,
                tuple(
                    sorted(
                        ((symbol.id, value) for symbol, value in runtime.inputs.items()),
                        key=lambda item: item[0],
                    )
                ),
            )
            for instance_id, runtime in sorted(self.instances.items())
        )
        states = tuple(
            (
                instance_id,
                tuple(
                    sorted(
                        (
                            (symbol.id, value)
                            for symbol, value in runtime.states.items()
                        ),
                        key=lambda item: item[0],
                    )
                ),
            )
            for instance_id, runtime in sorted(self.instances.items())
        )
        return ProcessRunResult(
            self.scenario.qualified_id,
            self.current_time,
            self.stopped,
            self.stop_reason,
            self.event_count,
            self.decision_count,
            self.branch_count,
            self.target_reached,
            len(self.schedule_slots),
            inputs,
            states,
            tuple(sorted(((symbol.id, value) for symbol, value in observations.items()))),
            tuple(self.observation_samples),
            tuple(self.output_events),
            tuple(self.decisions),
            tuple(self.trace),
        )

    def continuation_signature(self) -> Tuple[object, ...]:
        """Return the exact runtime state required for future execution.

        Histories used only by trajectory Measures are intentionally excluded;
        callers must pair this with ``process_measure_state_signature`` before
        treating two stochastic continuations as equivalent.
        """

        if not self.instances:
            raise ProcessExecutionError(
                "continuation signature requires an initialized executor"
            )

        def event_signature(event: RuntimeEvent) -> Tuple[object, ...]:
            return (
                event.id,
                event.time,
                event.phase.index,
                event.target.instance_id,
                event.target.member.kind.value,
                event.target.member.member_id,
                event.arguments,
                event.source_ids,
                event.fuel_reserved,
                event.schedule_slot,
            )

        decision_sources = (
            ("fixed", self.scenario.decisions),
            ("event", self.scenario.event_decisions),
            ("condition", self.scenario.condition_decisions),
            ("continuous", self.scenario.continuous_decisions),
        )

        def decision_identity(schedule: object) -> Tuple[str, int]:
            for kind, declarations in decision_sources:
                for index, declaration in enumerate(declarations):
                    if declaration is schedule:
                        return kind, index
            raise ProcessExecutionError(
                "runtime decision point does not belong to the scenario"
            )

        result = self._result()
        return (
            self.current_time,
            self.stopped,
            self.stop_reason,
            self.target_reached,
            self.event_count,
            self.decision_count,
            self.branch_count,
            self.branch_decision_count,
            result.inputs,
            result.states,
            tuple(sorted(self.heap)),
            tuple(sorted(self.queued_keys)),
            tuple(
                (
                    key,
                    tuple(
                        sorted(
                            (event_signature(event) for event in events),
                            key=repr,
                        )
                    ),
                )
                for key, events in sorted(self.events.items())
                if events
            ),
            tuple(
                (
                    key,
                    tuple(
                        (
                            decision_identity(schedule),
                            forced_choice,
                            plan_choice_index,
                        )
                        for schedule, forced_choice, plan_choice_index in decisions
                    ),
                )
                for key, decisions in sorted(self.decision_points.items())
                if decisions
            ),
            tuple(sorted(self.canceled)),
            tuple(
                sorted(
                    self.schedule_slots.items(),
                    key=lambda item: repr(item[0]),
                )
            ),
            tuple(sorted(self.condition_truth.items())),
            tuple(self.decisions),
        )

    def policy_state_signature(self) -> Tuple[object, ...]:
        """Return future semantics without trace-only random/action identity.

        A model that can inspect generated event IDs falls back to the full
        continuation signature.  Otherwise exact policy recursion may merge
        histories whose current state, pending work, and fuel are identical.
        """

        if self._history_sensitive_event_ids:
            return self.continuation_signature()
        if not self.instances:
            raise ProcessExecutionError(
                "policy state signature requires an initialized executor"
            )

        decision_sources = (
            ("fixed", self.scenario.decisions),
            ("event", self.scenario.event_decisions),
            ("condition", self.scenario.condition_decisions),
            ("continuous", self.scenario.continuous_decisions),
        )

        def decision_identity(schedule: object) -> Tuple[str, int]:
            for kind, declarations in decision_sources:
                for index, declaration in enumerate(declarations):
                    if declaration is schedule:
                        return kind, index
            raise ProcessExecutionError(
                "runtime decision point does not belong to the scenario"
            )

        def event_semantics(event: RuntimeEvent) -> Tuple[object, ...]:
            return (
                event.time,
                event.phase.index,
                event.target.instance_id,
                event.target.member.kind.value,
                event.target.member.member_id,
                event.arguments,
                event.fuel_reserved,
                event.schedule_slot[0:1]
                + ((event.schedule_slot[1][0], event.schedule_slot[1][1]),)
                if event.schedule_slot is not None
                else None,
            )

        result = self._result()
        future_schedule = _CachedExactSignature(
            (
                tuple(sorted(self.heap)),
                tuple(sorted(self.queued_keys)),
                tuple(
                    (
                        key,
                        tuple(
                            sorted(
                                (
                                    event_semantics(event)
                                    for event in events
                                    if event.id not in self.canceled
                                ),
                                key=repr,
                            )
                        ),
                    )
                    for key, events in sorted(self.events.items())
                    if events
                ),
                tuple(
                    (
                        key,
                        tuple(
                            (
                                decision_identity(schedule),
                                forced_choice,
                                plan_choice_index,
                            )
                            for (
                                schedule,
                                forced_choice,
                                plan_choice_index,
                            ) in decisions
                        ),
                    )
                    for key, decisions in sorted(self.decision_points.items())
                    if decisions
                ),
                tuple(
                    sorted(
                        self.schedule_slots.keys(), key=repr
                    )
                ),
                tuple(sorted(self.condition_truth.items())),
            )
        )
        future_schedule = self._policy_signature_intern.setdefault(
            future_schedule, future_schedule
        )
        state_signature = _CachedExactSignature(result.states)
        return (
            self.current_time,
            self._complete,
            self.stopped,
            self.stop_reason,
            self.target_reached,
            self.event_count,
            self.decision_count,
            # Inputs are immutable within one executor tree; every clone shares
            # this interner and every variant starts from a fresh executor.
            state_signature,
            future_schedule,
        )

    def clone(self) -> "DeterministicProcessExecutor":
        """Copy mutable execution state while sharing immutable Scenario IR."""

        cloned = copy.copy(self)
        cloned.initial_state_overrides = dict(self.initial_state_overrides)
        cloned.input_overrides = dict(self.input_overrides)
        cloned.instances = {
            instance_id: _InstanceState(
                runtime.declaration,
                dict(runtime.inputs),
                dict(runtime.states),
            )
            for instance_id, runtime in self.instances.items()
        }
        cloned.events = defaultdict(
            list, {key: list(events) for key, events in self.events.items()}
        )
        cloned.decision_points = defaultdict(
            list,
            {
                key: list(decisions)
                for key, decisions in self.decision_points.items()
            },
        )
        cloned.heap = list(self.heap)
        cloned.queued_keys = set(self.queued_keys)
        cloned.canceled = set(self.canceled)
        cloned.schedule_slots = dict(self.schedule_slots)
        cloned.trace = list(self.trace)
        cloned.observation_samples = list(self.observation_samples)
        cloned.output_events = list(self.output_events)
        cloned.decisions = list(self.decisions)
        cloned.condition_truth = dict(self.condition_truth)
        cloned.connections = defaultdict(
            list,
            {key: list(targets) for key, targets in self.connections.items()},
        )
        return cloned


def _render_value(value: object) -> str:
    if isinstance(value, Fraction):
        return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    if isinstance(value, ProcessEventId):
        return value.value
    return str(value).lower() if isinstance(value, bool) else str(value)


def run_process_scenario(
    scenario: ScenarioIR,
    registry: UnitRegistry,
    *,
    selector: Optional[DecisionSelector] = None,
    branch_selector: Optional[BranchSelector] = None,
    reach_target=None,
    initial_state_overrides: Optional[Mapping[Tuple[str, str], ProcessValue]] = None,
    input_overrides: Optional[Mapping[Tuple[str, str], ProcessValue]] = None,
    maximum_batches: Optional[int] = None,
    include_trace: bool = True,
    continuous_choices: Sequence[ContinuousDecisionChoice] = (),
) -> ProcessRunResult:
    return DeterministicProcessExecutor(
        scenario,
        registry,
        selector=selector,
        branch_selector=branch_selector,
        reach_target=reach_target,
        initial_state_overrides=initial_state_overrides,
        input_overrides=input_overrides,
        maximum_batches=maximum_batches,
        include_trace=include_trace,
        continuous_choices=continuous_choices,
    ).run()


def selector_for_policy(policy: PolicyIR, registry: UnitRegistry) -> DecisionSelector:
    """Compile a source Policy IR to the runtime's pure decision interface."""

    def select(
        index: int,
        _time: Fraction,
        _schedule: object,
        _available: Tuple[str, ...],
        values: Mapping[str, ProcessValue],
        _history: Tuple[Tuple[Fraction, str], ...],
    ) -> str:
        if policy.sequence:
            if index >= len(policy.sequence):
                raise ProcessExecutionError(
                    f"policy {policy.id!r} sequence ended before decision {index + 1}",
                    policy.location,
                )
            return policy.sequence[index]
        for rule in policy.rules:
            if rule.condition is None:
                return rule.action_id
            environment = {
                reference: values[reference.id]
                for reference in rule.condition.references
                if reference.id in values
            }
            if evaluate_process_expression(
                rule.condition, environment, registry
            ) is True:
                return rule.action_id
        raise ProcessExecutionError(
            f"policy {policy.id!r} has no matching rule at decision {index + 1}",
            policy.location,
        )

    return select
