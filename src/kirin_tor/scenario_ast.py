"""Typed source AST for Process scenarios and analysis declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

from .errors import SourceLocation
from .process_ast import EventCallAst, ExpressionAst


@dataclass(frozen=True)
class ScenarioPhaseAst:
    id: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class InstanceInputAst:
    input_id: str
    value: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class InstancePhaseAst:
    process_phase_id: str
    scenario_phase_id: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ProcessInstanceAst:
    id: str
    process_path: str
    inputs: Tuple[InstanceInputAst, ...] = ()
    phases: Tuple[InstancePhaseAst, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventEndpointAst:
    instance_id: str
    member_id: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ConnectionAst:
    source: EventEndpointAst
    target: EventEndpointAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioSendAst:
    instance_id: str
    call: EventCallAst
    phase_id: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class AtScheduleAst:
    time: ExpressionAst
    phase_id: str
    sends: Tuple[ScenarioSendAst, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EveryScheduleAst:
    interval: ExpressionAst
    start: ExpressionAst
    end: Optional[ExpressionAst]
    phase_id: str
    sends: Tuple[ScenarioSendAst, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


ScenarioScheduleAst = Union[AtScheduleAst, EveryScheduleAst]


@dataclass(frozen=True)
class CompositeActionAst:
    id: str
    guard: Optional[ExpressionAst]
    sends: Tuple[ScenarioSendAst, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class PolicyRuleAst:
    action_id: str
    condition: Optional[ExpressionAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class PolicyAst:
    id: str
    rules: Tuple[PolicyRuleAst, ...] = ()
    sequence: Tuple[str, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class DecisionScheduleAst:
    interval: ExpressionAst
    start: ExpressionAst
    end: Optional[ExpressionAst]
    phase_id: str
    options: Tuple[str, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioBoundsAst:
    horizon: ExpressionAst
    maximum_events: ExpressionAst
    maximum_decisions: ExpressionAst
    maximum_branches: ExpressionAst
    maximum_entities: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioAst:
    owner_id: str
    id: str
    label: Optional[str] = None
    phases: Tuple[ScenarioPhaseAst, ...] = ()
    instances: Tuple[ProcessInstanceAst, ...] = ()
    connections: Tuple[ConnectionAst, ...] = ()
    schedules: Tuple[ScenarioScheduleAst, ...] = ()
    actions: Tuple[CompositeActionAst, ...] = ()
    policies: Tuple[PolicyAst, ...] = ()
    decisions: Tuple[DecisionScheduleAst, ...] = ()
    stop: Optional[ExpressionAst] = None
    bounds: Optional[ScenarioBoundsAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class AnalysisAst:
    owner_id: str
    id: str
    label: Optional[str]
    scenario_path: str
    operation: str
    policy_ids: Tuple[str, ...] = ()
    objective_direction: Optional[str] = None
    objective: Optional[ExpressionAst] = None
    tie_break_direction: Optional[str] = None
    tie_break: Optional[ExpressionAst] = None
    target: Optional[ExpressionAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"
