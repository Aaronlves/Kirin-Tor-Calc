"""Shared game-neutral vocabulary for the bounded process source and IR layers."""

from __future__ import annotations

from enum import Enum


class EventDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    INTERNAL = "internal"


class Reducer(str, Enum):
    SUM = "sum"
    MIN = "min"
    MAX = "max"
    ALL = "all"
    ANY = "any"


class BranchMode(str, Enum):
    INDEPENDENT = "independent"
    JOINT = "joint"


class ScheduleOperation(str, Enum):
    SCHEDULE = "schedule"
    REPLACE = "replace"


class ProcessMemberKind(str, Enum):
    INPUT = "input"
    STATE = "state"
    EVENT = "event"
    ACTION = "action"
    PHASE = "phase"
    KEY = "key"
    OBSERVATION = "observation"


class ExpressionSymbolKind(str, Enum):
    INPUT = "input"
    STATE = "state"
    LOCAL = "local"
    EVENT_PARAMETER = "event_parameter"
    STATIC_MEMBER = "static_member"
    UNIT = "unit"
    FUNCTION = "function"
    EVENT_CONTEXT = "event_context"
