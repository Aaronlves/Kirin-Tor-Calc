"""Resolved immutable IR for Process scenarios and analyses."""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional, Tuple, Union

from .errors import SourceLocation
from .process_ir import (
    EventArgumentIR,
    EventParameterIR,
    ProcessIR,
    ProcessMemberRefIR,
    SymbolRefIR,
    TypedExpressionIR,
)


SCENARIO_IR_VERSION = 1


@dataclass(frozen=True)
class ScenarioPhaseIR:
    scenario_id: str
    id: str
    index: int


@dataclass(frozen=True)
class InstanceMemberRefIR:
    scenario_id: str
    instance_id: str
    member: ProcessMemberRefIR


@dataclass(frozen=True)
class InstanceInputIR:
    input: InstanceMemberRefIR
    value: TypedExpressionIR


@dataclass(frozen=True)
class InstancePhaseIR:
    process_phase: InstanceMemberRefIR
    scenario_phase: ScenarioPhaseIR


@dataclass(frozen=True)
class ProcessInstanceIR:
    scenario_id: str
    id: str
    process: ProcessIR
    inputs: Tuple[InstanceInputIR, ...]
    phases: Tuple[InstancePhaseIR, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ConnectionIR:
    source: InstanceMemberRefIR
    target: InstanceMemberRefIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioCallIR:
    target: InstanceMemberRefIR
    parameters: Tuple[EventParameterIR, ...]
    arguments: Tuple[EventArgumentIR, ...]
    phase: ScenarioPhaseIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class AtScheduleIR:
    time: Fraction
    phase: ScenarioPhaseIR
    sends: Tuple[ScenarioCallIR, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EveryScheduleIR:
    interval: Fraction
    start: Fraction
    end: Optional[Fraction]
    phase: ScenarioPhaseIR
    sends: Tuple[ScenarioCallIR, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


ScenarioScheduleIR = Union[AtScheduleIR, EveryScheduleIR]


@dataclass(frozen=True)
class CompositeActionIR:
    scenario_id: str
    id: str
    guard: Optional[TypedExpressionIR]
    sends: Tuple[ScenarioCallIR, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class PolicyRuleIR:
    action_id: str
    condition: Optional[TypedExpressionIR] = None


@dataclass(frozen=True)
class PolicyIR:
    scenario_id: str
    id: str
    rules: Tuple[PolicyRuleIR, ...] = ()
    sequence: Tuple[str, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class DecisionScheduleIR:
    interval: Fraction
    start: Fraction
    end: Optional[Fraction]
    phase: ScenarioPhaseIR
    action_ids: Tuple[str, ...]
    allow_wait: bool
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioBoundsIR:
    horizon: Fraction
    maximum_events: int
    maximum_decisions: int
    maximum_branches: int
    maximum_entities: int


@dataclass(frozen=True)
class ScenarioIR:
    owner_id: str
    id: str
    label: Optional[str]
    phases: Tuple[ScenarioPhaseIR, ...]
    instances: Tuple[ProcessInstanceIR, ...]
    connections: Tuple[ConnectionIR, ...]
    schedules: Tuple[ScenarioScheduleIR, ...]
    actions: Tuple[CompositeActionIR, ...]
    policies: Tuple[PolicyIR, ...]
    decisions: Tuple[DecisionScheduleIR, ...]
    observation_symbols: Tuple[SymbolRefIR, ...]
    stop: Optional[TypedExpressionIR]
    bounds: ScenarioBoundsIR
    version: int = SCENARIO_IR_VERSION
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class ObjectiveIR:
    direction: str
    value: TypedExpressionIR


@dataclass(frozen=True)
class AnalysisIR:
    owner_id: str
    id: str
    label: Optional[str]
    scenario_id: str
    operation: str
    policy_ids: Tuple[str, ...] = ()
    objective: Optional[ObjectiveIR] = None
    tie_break: Optional[ObjectiveIR] = None
    target: Optional[TypedExpressionIR] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"
