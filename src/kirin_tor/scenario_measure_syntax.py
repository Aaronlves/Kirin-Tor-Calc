"""Public syntax registry for typed Scenario trajectory Measures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class TrajectoryMeasureSyntax:
    name: str
    label: str
    insertion: str
    terms: Tuple[str, ...]


TRAJECTORY_MEASURE_SYNTAX = (
    TrajectoryMeasureSyntax("final", "轨迹终值", "final($0)", ("终值", "最终值")),
    TrajectoryMeasureSyntax(
        "minimum_over_time",
        "轨迹最小值",
        "minimum_over_time($0)",
        ("最小值", "全程最小值"),
    ),
    TrajectoryMeasureSyntax(
        "minimum_where",
        "条件筛选最小值",
        "minimum_where($0, condition, default = value)",
        ("条件最小值", "筛选最小值"),
    ),
    TrajectoryMeasureSyntax(
        "maximum_over_time",
        "轨迹最大值",
        "maximum_over_time($0)",
        ("最大值", "全程最大值"),
    ),
    TrajectoryMeasureSyntax(
        "maximum_drawdown",
        "最大回撤",
        "maximum_drawdown($0)",
        ("回撤", "最大下降"),
    ),
    TrajectoryMeasureSyntax(
        "total_variation",
        "总变化量",
        "total_variation($0)",
        ("变化量", "波动"),
    ),
    TrajectoryMeasureSyntax(
        "variance_over_time",
        "时间加权方差",
        "variance_over_time($0)",
        ("轨迹方差", "方差"),
    ),
    TrajectoryMeasureSyntax(
        "sum_events",
        "事件参数总和",
        "sum_events(instance.output_event.$0)",
        ("事件求和", "输出事件总和"),
    ),
    TrajectoryMeasureSyntax(
        "count_events",
        "事件计数",
        "count_events(instance.output_event)$0",
        ("事件次数", "输出事件计数"),
    ),
    TrajectoryMeasureSyntax(
        "duration_where",
        "条件持续时间",
        "duration_where($0)",
        ("持续时间", "条件时长"),
    ),
    TrajectoryMeasureSyntax(
        "first_time",
        "条件首次成立时间",
        "first_time($0, default = horizon)",
        ("首次发生", "第一次成立"),
    ),
    TrajectoryMeasureSyntax(
        "last_before",
        "条件成立前最后值",
        "last_before($0, condition, default = value)",
        ("成立前最后值", "事件前状态"),
    ),
    TrajectoryMeasureSyntax(
        "stop_time",
        "停止时间",
        "stop_time()$0",
        ("结束时间", "生存时间"),
    ),
)

TRAJECTORY_MEASURE_OPERATIONS = frozenset(
    item.name for item in TRAJECTORY_MEASURE_SYNTAX
)
