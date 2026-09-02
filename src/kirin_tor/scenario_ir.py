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
    ValueTypeIR,
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
class VariantInputIR:
    input: InstanceMemberRefIR
    value: TypedExpressionIR


@dataclass(frozen=True)
class ScenarioVariantIR:
    scenario_id: str
    id: str
    inputs: Tuple[VariantInputIR, ...]
    label: Optional[str] = None
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
class EventDecisionIR:
    source: InstanceMemberRefIR
    phase: ScenarioPhaseIR
    action_ids: Tuple[str, ...]
    allow_wait: bool
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ConditionDecisionIR:
    condition: TypedExpressionIR
    phase: ScenarioPhaseIR
    action_ids: Tuple[str, ...]
    allow_wait: bool
    continuous_crossing: bool
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ContinuousDecisionIR:
    maximum_occurrences: int
    start: Fraction
    end: Fraction
    phase: ScenarioPhaseIR
    action_ids: Tuple[str, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioBoundsIR:
    horizon: Fraction
    maximum_events: int
    maximum_decisions: int
    maximum_branches: int
    maximum_entities: int


@dataclass(frozen=True)
class TrajectoryMeasureExpressionIR:
    operation: str
    value: Optional[TypedExpressionIR] = None
    condition: Optional[TypedExpressionIR] = None
    event: Optional[InstanceMemberRefIR] = None
    parameter_id: Optional[str] = None
    default: Optional[TypedExpressionIR] = None


@dataclass(frozen=True)
class DerivedMeasureExpressionIR:
    value: TypedExpressionIR


MeasureExpressionIR = Union[TrajectoryMeasureExpressionIR, DerivedMeasureExpressionIR]


@dataclass(frozen=True)
class MeasureIR:
    scenario_id: str
    id: str
    value_type: ValueTypeIR
    expression: MeasureExpressionIR
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ObjectiveTermIR:
    direction: str
    measure_id: str


@dataclass(frozen=True)
class ObjectiveIR:
    scenario_id: str
    id: str
    terms: Tuple[ObjectiveTermIR, ...]
    constraints: Tuple[TypedExpressionIR, ...] = ()
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioIR:
    owner_id: str
    id: str
    label: Optional[str]
    phases: Tuple[ScenarioPhaseIR, ...]
    instances: Tuple[ProcessInstanceIR, ...]
    variants: Tuple[ScenarioVariantIR, ...]
    connections: Tuple[ConnectionIR, ...]
    schedules: Tuple[ScenarioScheduleIR, ...]
    actions: Tuple[CompositeActionIR, ...]
    policies: Tuple[PolicyIR, ...]
    decisions: Tuple[DecisionScheduleIR, ...]
    event_decisions: Tuple[EventDecisionIR, ...]
    condition_decisions: Tuple[ConditionDecisionIR, ...]
    continuous_decisions: Tuple[ContinuousDecisionIR, ...]
    observation_symbols: Tuple[SymbolRefIR, ...]
    measures: Tuple[MeasureIR, ...]
    objectives: Tuple[ObjectiveIR, ...]
    stop: Optional[TypedExpressionIR]
    bounds: ScenarioBoundsIR
    version: int = SCENARIO_IR_VERSION
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class AnalysisIR:
    owner_id: str
    id: str
    label: Optional[str]
    scenario_id: str
    operation: str
    policy_ids: Tuple[str, ...] = ()
    objective_ids: Tuple[str, ...] = ()
    variant_ids: Tuple[str, ...] = ()
    search_method: Optional[str] = None
    time_tolerance: Optional[Fraction] = None
    maximum_evaluations: Optional[int] = None
    charts: Tuple["AnalysisChartIR", ...] = ()
    target: Optional[TypedExpressionIR] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class AnalysisChartIR:
    analysis_id: str
    id: str
    kind: str
    label: Optional[str] = None
    series: Tuple[SymbolRefIR, ...] = ()
    markers: Tuple[Tuple[str, str], ...] = ()
    x_measure_id: Optional[str] = None
    y_measure_id: Optional[str] = None
    value_measure_id: Optional[str] = None
    x_direction: Optional[str] = None
    y_direction: Optional[str] = None
    export_svg: Optional[str] = None
    export_csv: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)
