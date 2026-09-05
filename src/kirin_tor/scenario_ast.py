"""Typed source AST for Process scenarios and analysis declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

from .errors import SourceLocation
from .process_ast import EventCallAst, ExpressionAst, TypeAst


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
class VariantInputAst:
    instance_id: str
    input_id: str
    value: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScenarioVariantAst:
    id: str
    inputs: Tuple[VariantInputAst, ...]
    label: Optional[str] = None
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
class EventDecisionAst:
    source: EventEndpointAst
    phase_id: str
    options: Tuple[str, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ConditionDecisionAst:
    condition: ExpressionAst
    phase_id: str
    options: Tuple[str, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ContinuousDecisionAst:
    maximum_occurrences: int
    start: ExpressionAst
    end: ExpressionAst
    phase_id: str
    options: Tuple[str, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class MeasureAst:
    id: str
    value_type: TypeAst
    value: ExpressionAst
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ObjectiveTermAst:
    direction: str
    measure_id: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ChanceConstraintAst:
    comparison: str
    threshold: ExpressionAst
    condition: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ObjectiveAst:
    id: str
    terms: Tuple[ObjectiveTermAst, ...]
    constraints: Tuple[ExpressionAst, ...] = ()
    path_constraints: Tuple[ExpressionAst, ...] = ()
    chance_constraints: Tuple[ChanceConstraintAst, ...] = ()
    label: Optional[str] = None
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
    variants: Tuple[ScenarioVariantAst, ...] = ()
    connections: Tuple[ConnectionAst, ...] = ()
    schedules: Tuple[ScenarioScheduleAst, ...] = ()
    actions: Tuple[CompositeActionAst, ...] = ()
    policies: Tuple[PolicyAst, ...] = ()
    decisions: Tuple[DecisionScheduleAst, ...] = ()
    event_decisions: Tuple[EventDecisionAst, ...] = ()
    condition_decisions: Tuple[ConditionDecisionAst, ...] = ()
    continuous_decisions: Tuple[ContinuousDecisionAst, ...] = ()
    measures: Tuple[MeasureAst, ...] = ()
    objectives: Tuple[ObjectiveAst, ...] = ()
    stop: Optional[ExpressionAst] = None
    bounds: Optional[ScenarioBoundsAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class SweepAxisAst:
    input_path: str
    start: ExpressionAst
    end: ExpressionAst
    step: ExpressionAst


@dataclass(frozen=True)
class SweepFamilyAst:
    id: str
    policy_id: str
    axes: Tuple[SweepAxisAst, ...] = ()
    enabled: bool = True
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class SweepAst:
    maximum_cases: ExpressionAst
    families: Tuple[SweepFamilyAst, ...]
    ranking: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class AnalysisAst:
    owner_id: str
    id: str
    label: Optional[str]
    scenario_path: str
    operation: str
    policy_ids: Tuple[str, ...] = ()
    objective_ids: Tuple[str, ...] = ()
    variant_ids: Tuple[str, ...] = ()
    search_method: Optional[str] = None
    time_tolerance: Optional[ExpressionAst] = None
    time_grid: Optional[ExpressionAst] = None
    maximum_evaluations: Optional[ExpressionAst] = None
    charts: Tuple["AnalysisChartAst", ...] = ()
    target: Optional[ExpressionAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)
    sweep: Optional[SweepAst] = None

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"


@dataclass(frozen=True)
class AnalysisChartAst:
    id: str
    kind: str
    label: Optional[str] = None
    series: Tuple[str, ...] = ()
    markers: Tuple[str, ...] = ()
    x: Optional[str] = None
    y: Optional[str] = None
    value: Optional[str] = None
    x_direction: Optional[str] = None
    y_direction: Optional[str] = None
    export_svg: Optional[str] = None
    export_csv: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)
