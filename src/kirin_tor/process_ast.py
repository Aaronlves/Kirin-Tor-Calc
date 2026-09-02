"""Typed source AST for bounded process declarations.

The parser will produce these nodes instead of extending the current raw document
mapping with another nested schema. Expressions and names remain unresolved here;
semantic lowering turns them into :mod:`kirin_tor.process_ir` nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

from .errors import SourceLocation
from .process_model import BranchMode, EventDirection, Reducer, ScheduleOperation


@dataclass(frozen=True)
class ExpressionAst:
    text: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class TypeAst:
    """A source type name with optional generic arguments and finite capacity."""

    name: str
    arguments: Tuple["TypeAst", ...] = ()
    capacity: Optional[int] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class BoundAst:
    minimum: Optional[ExpressionAst] = None
    maximum: Optional[ExpressionAst] = None


@dataclass(frozen=True)
class InputAst:
    id: str
    value_type: TypeAst
    label: Optional[str] = None
    default: Optional[ExpressionAst] = None
    bound: Optional[BoundAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class StateAst:
    id: str
    value_type: TypeAst
    initial: ExpressionAst
    label: Optional[str] = None
    bound: Optional[BoundAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class KeyAst:
    id: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class PhaseAst:
    id: str
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventParameterAst:
    id: str
    value_type: TypeAst
    reducer: Optional[Reducer] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventAst:
    id: str
    direction: EventDirection
    parameters: Tuple[EventParameterAst, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ActionAst:
    id: str
    parameters: Tuple[EventParameterAst, ...] = ()
    guard: Optional[ExpressionAst] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventArgumentAst:
    parameter_id: str
    value: ExpressionAst


@dataclass(frozen=True)
class EventCallAst:
    event_id: str
    arguments: Tuple[EventArgumentAst, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class LetEffectAst:
    id: str
    value_type: TypeAst
    value: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class NextEffectAst:
    state_id: str
    value: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EmitEffectAst:
    call: EventCallAst
    phase_id: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScheduleEffectAst:
    operation: ScheduleOperation
    call: EventCallAst
    delay: ExpressionAst
    phase_id: str
    key: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class CancelEffectAst:
    key: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class WhenEffectAst:
    condition: ExpressionAst
    effects: Tuple["EffectAst", ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ProbabilityCaseAst:
    probability: ExpressionAst
    effects: Tuple["EffectAst", ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class BranchEffectAst:
    id: str
    mode: BranchMode
    cases: Tuple[ProbabilityCaseAst, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


EffectAst = Union[
    LetEffectAst,
    NextEffectAst,
    EmitEffectAst,
    ScheduleEffectAst,
    CancelEffectAst,
    WhenEffectAst,
    BranchEffectAst,
]


@dataclass(frozen=True)
class HandlerAst:
    trigger_id: str
    parameter_bindings: Tuple[str, ...] = ()
    guard: Optional[ExpressionAst] = None
    effects: Tuple[EffectAst, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class FlowAst:
    state_id: str
    current_id: str
    elapsed_id: str
    value: ExpressionAst
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ObservationAst:
    id: str
    value_type: TypeAst
    value: ExpressionAst
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ProcessAst:
    owner_id: str
    id: str
    label: Optional[str] = None
    inputs: Tuple[InputAst, ...] = ()
    states: Tuple[StateAst, ...] = ()
    requirements: Tuple[ExpressionAst, ...] = ()
    keys: Tuple[KeyAst, ...] = ()
    phases: Tuple[PhaseAst, ...] = ()
    events: Tuple[EventAst, ...] = ()
    actions: Tuple[ActionAst, ...] = ()
    flows: Tuple[FlowAst, ...] = ()
    handlers: Tuple[HandlerAst, ...] = ()
    observations: Tuple[ObservationAst, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"
