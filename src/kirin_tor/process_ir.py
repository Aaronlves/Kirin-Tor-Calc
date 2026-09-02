"""Resolved, typed intermediate representation for bounded processes.

The IR is immutable and contains no raw source mappings. It deliberately models
only game-neutral types, references, events, and effects. Parser lowering,
semantic validation, and execution are separate later stages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Union

from .errors import SourceLocation
from .process_model import (
    BranchMode,
    EventDirection,
    ExpressionSymbolKind,
    ProcessMemberKind,
    Reducer,
    ScheduleOperation,
)
from .units import Dimension


PROCESS_IR_VERSION = 1


@dataclass(frozen=True)
class BooleanTypeIR:
    domain_id: Optional[str] = None


@dataclass(frozen=True)
class NumberTypeIR:
    unit_name: str
    dimension: Dimension
    domain_id: Optional[str] = None
    integer: bool = False


@dataclass(frozen=True)
class SymbolicTypeIR:
    domain_id: str


@dataclass(frozen=True)
class ObjectTypeIR:
    type_id: str


@dataclass(frozen=True)
class EventIdTypeIR:
    pass


@dataclass(frozen=True)
class ListTypeIR:
    item_type: "ValueTypeIR"
    capacity: int


@dataclass(frozen=True)
class MapTypeIR:
    key_type: "ValueTypeIR"
    value_type: "ValueTypeIR"
    capacity: int


ValueTypeIR = Union[
    BooleanTypeIR,
    NumberTypeIR,
    SymbolicTypeIR,
    ObjectTypeIR,
    EventIdTypeIR,
    ListTypeIR,
    MapTypeIR,
]


@dataclass(frozen=True)
class ProcessMemberRefIR:
    process_id: str
    member_id: str
    kind: ProcessMemberKind


@dataclass(frozen=True)
class SymbolRefIR:
    owner_id: str
    id: str
    kind: ExpressionSymbolKind
    value_type: ValueTypeIR


@dataclass(frozen=True)
class TypedExpressionIR:
    source: str
    result_type: ValueTypeIR
    references: Tuple[SymbolRefIR, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class BoundIR:
    minimum: Optional[TypedExpressionIR] = None
    maximum: Optional[TypedExpressionIR] = None


@dataclass(frozen=True)
class InputIR:
    ref: ProcessMemberRefIR
    value_type: ValueTypeIR
    label: Optional[str] = None
    default: Optional[TypedExpressionIR] = None
    bound: Optional[BoundIR] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class StateIR:
    ref: ProcessMemberRefIR
    value_type: ValueTypeIR
    initial: TypedExpressionIR
    label: Optional[str] = None
    bound: Optional[BoundIR] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class KeyIR:
    ref: ProcessMemberRefIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class PhaseIR:
    ref: ProcessMemberRefIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventParameterIR:
    id: str
    value_type: ValueTypeIR
    reducer: Optional[Reducer] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventIR:
    ref: ProcessMemberRefIR
    direction: EventDirection
    parameters: Tuple[EventParameterIR, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ActionIR:
    ref: ProcessMemberRefIR
    parameters: Tuple[EventParameterIR, ...] = ()
    guard: Optional[TypedExpressionIR] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EventArgumentIR:
    parameter_id: str
    value: TypedExpressionIR


@dataclass(frozen=True)
class EventCallIR:
    event: ProcessMemberRefIR
    arguments: Tuple[EventArgumentIR, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class StaticScheduleKeyIR:
    key: ProcessMemberRefIR


@dataclass(frozen=True)
class EventIdScheduleKeyIR:
    value: TypedExpressionIR


ScheduleKeyIR = Union[StaticScheduleKeyIR, EventIdScheduleKeyIR]


@dataclass(frozen=True)
class LetEffectIR:
    symbol: SymbolRefIR
    value: TypedExpressionIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class NextEffectIR:
    state: ProcessMemberRefIR
    value: TypedExpressionIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class EmitEffectIR:
    call: EventCallIR
    phase: Optional[ProcessMemberRefIR] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ScheduleEffectIR:
    operation: ScheduleOperation
    call: EventCallIR
    delay: TypedExpressionIR
    phase: ProcessMemberRefIR
    key: ScheduleKeyIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class CancelEffectIR:
    key: ScheduleKeyIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class WhenEffectIR:
    condition: TypedExpressionIR
    effects: Tuple["EffectIR", ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ProbabilityCaseIR:
    probability: TypedExpressionIR
    effects: Tuple["EffectIR", ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class BranchEffectIR:
    id: str
    mode: BranchMode
    cases: Tuple[ProbabilityCaseIR, ...]
    location: Optional[SourceLocation] = field(default=None, compare=False)


EffectIR = Union[
    LetEffectIR,
    NextEffectIR,
    EmitEffectIR,
    ScheduleEffectIR,
    CancelEffectIR,
    WhenEffectIR,
    BranchEffectIR,
]


@dataclass(frozen=True)
class HandlerIR:
    trigger: ProcessMemberRefIR
    parameter_symbols: Tuple[SymbolRefIR, ...] = ()
    guard: Optional[TypedExpressionIR] = None
    effects: Tuple[EffectIR, ...] = ()
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class FlowIR:
    state: ProcessMemberRefIR
    current_symbol: SymbolRefIR
    elapsed_symbol: SymbolRefIR
    value: TypedExpressionIR
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ObservationIR:
    ref: ProcessMemberRefIR
    value_type: ValueTypeIR
    value: TypedExpressionIR
    label: Optional[str] = None
    location: Optional[SourceLocation] = field(default=None, compare=False)


@dataclass(frozen=True)
class ProcessIR:
    owner_id: str
    id: str
    label: Optional[str] = None
    inputs: Tuple[InputIR, ...] = ()
    states: Tuple[StateIR, ...] = ()
    requirements: Tuple[TypedExpressionIR, ...] = ()
    keys: Tuple[KeyIR, ...] = ()
    phases: Tuple[PhaseIR, ...] = ()
    events: Tuple[EventIR, ...] = ()
    actions: Tuple[ActionIR, ...] = ()
    flows: Tuple[FlowIR, ...] = ()
    handlers: Tuple[HandlerIR, ...] = ()
    observations: Tuple[ObservationIR, ...] = ()
    version: int = PROCESS_IR_VERSION
    location: Optional[SourceLocation] = field(default=None, compare=False)

    @property
    def qualified_id(self) -> str:
        return f"{self.owner_id}.{self.id}"
