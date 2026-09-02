"""Derived multi-chart projections and artifacts for Process analyses."""

from __future__ import annotations

import csv
import os
import uuid
import warnings
from fractions import Fraction
from pathlib import Path
from typing import Dict, Mapping

from .errors import ParameterError, WorkspaceError
from .scenario_ir import AnalysisIR, ScenarioIR


def _exact(value) -> str:
    if isinstance(value, Fraction):
        return (
            str(value.numerator)
            if value.denominator == 1
            else f"{value.numerator}/{value.denominator}"
        )
    return str(value)


def _number(value) -> dict:
    return {"exact": _exact(value), "approximate": float(value)}


def _measure_units(scenario: ScenarioIR) -> Dict[str, str]:
    return {
        measure.id: getattr(measure.value_type, "unit_name", "dimensionless")
        for measure in scenario.measures
    }


def _observation_units(scenario: ScenarioIR) -> Dict[str, str]:
    return {
        symbol.id: getattr(symbol.value_type, "unit_name", "dimensionless")
        for symbol in scenario.observation_symbols
    }


def _run_markers(chart, run) -> list[dict]:
    result = []
    seen_events = set()
    for kind, target in chart.markers:
        if kind == "decision":
            result.extend(
                {
                    "kind": "decision",
                    "target": target,
                    "time": _exact(time),
                    "time_approximate": float(time),
                }
                for time, action in run.decisions
                if action == target
            )
            continue
        instance_id, member_id = target.split(".", 1)
        for entry in run.trace:
            if (
                entry.event_id is None
                or entry.event_id in seen_events
                or entry.instance_id != instance_id
                or entry.member_id != member_id
                or entry.kind not in {"handled", "no_op", "emit"}
            ):
                continue
            seen_events.add(entry.event_id)
            result.append(
                {
                    "kind": "event",
                    "target": target,
                    "time": _exact(entry.time),
                    "time_approximate": float(entry.time),
                }
            )
    return result


def _dominates(left: Mapping[str, object], right: Mapping[str, object], chart) -> bool:
    comparisons = []
    strict = False
    for axis, direction in (
        ("x", chart.x_direction),
        ("y", chart.y_direction),
    ):
        left_value = left[axis]
        right_value = right[axis]
        if direction == "maximize":
            comparisons.append(left_value >= right_value)
            strict = strict or left_value > right_value
        else:
            comparisons.append(left_value <= right_value)
            strict = strict or left_value < right_value
    return all(comparisons) and strict


def process_charts_data(result, analysis: AnalysisIR, scenario: ScenarioIR) -> list[dict]:
    """Project optimized runs/candidates without creating a second authority."""

    measure_units = _measure_units(scenario)
    observation_units = _observation_units(scenario)
    charts = []
    for chart in analysis.charts:
        projection = {
            "id": chart.id,
            "label": chart.label or chart.id,
            "kind": chart.kind,
            "export_svg": chart.export_svg,
            "export_csv": chart.export_csv,
        }
        if chart.kind == "trajectory":
            series = [symbol.id for symbol in chart.series]
            rows = []
            markers = []
            for variant in result.variants:
                for objective in variant.objectives:
                    for sample in objective.best.observation_samples:
                        values = dict(sample.values)
                        rows.append(
                            {
                                "variant": variant.variant_id,
                                "objective": objective.objective_id,
                                "time": _exact(sample.time),
                                "time_approximate": float(sample.time),
                                "phase": sample.phase,
                                "values": {
                                    name: _number(values[name]) for name in series
                                },
                            }
                        )
                    markers.extend(
                        {
                            **item,
                            "variant": variant.variant_id,
                            "objective": objective.objective_id,
                        }
                        for item in _run_markers(chart, objective.best)
                    )
            projection.update(
                {
                    "series": series,
                    "units": {name: observation_units[name] for name in series},
                    "rows": rows,
                    "markers": markers,
                }
            )
        elif chart.kind == "variant_comparison":
            series = [symbol.id for symbol in chart.series]
            projection.update(
                {
                    "series": series,
                    "units": {name: measure_units[name] for name in series},
                    "rows": [
                        {
                            "variant": variant.variant_id,
                            "objective": objective.objective_id,
                            "values": {
                                name: _number(dict(objective.measures)[name])
                                for name in series
                            },
                        }
                        for variant in result.variants
                        for objective in variant.objectives
                    ],
                }
            )
        elif chart.kind == "decision_surface":
            assert chart.value_measure_id is not None
            rows = []
            for variant in result.variants:
                for candidate in variant.candidates:
                    if len(candidate.decisions) < 2:
                        continue
                    value = dict(candidate.measures)[chart.value_measure_id]
                    rows.append(
                        {
                            "variant": variant.variant_id,
                            "x": _exact(candidate.decisions[0][0]),
                            "x_approximate": float(candidate.decisions[0][0]),
                            "y": _exact(candidate.decisions[1][0]),
                            "y_approximate": float(candidate.decisions[1][0]),
                            "value": _number(value),
                        }
                    )
            projection.update(
                {
                    "value_measure": chart.value_measure_id,
                    "unit": measure_units[chart.value_measure_id],
                    "rows": rows,
                }
            )
        else:
            assert chart.kind == "pareto"
            assert chart.x_measure_id is not None and chart.y_measure_id is not None
            raw_rows = []
            for variant in result.variants:
                for candidate in variant.candidates:
                    measures = dict(candidate.measures)
                    raw_rows.append(
                        {
                            "variant": variant.variant_id,
                            "x": measures[chart.x_measure_id],
                            "y": measures[chart.y_measure_id],
                            "decisions": candidate.decisions,
                        }
                    )
            rows = []
            for row in raw_rows:
                peers = [
                    other
                    for other in raw_rows
                    if other["variant"] == row["variant"]
                ]
                rows.append(
                    {
                        "variant": row["variant"],
                        "x": _number(row["x"]),
                        "y": _number(row["y"]),
                        "nondominated": not any(
                            _dominates(other, row, chart) for other in peers
                        ),
                        "decisions": [
                            {"time": _exact(time), "action": action}
                            for time, action in row["decisions"]
                        ],
                    }
                )
            projection.update(
                {
                    "x_measure": chart.x_measure_id,
                    "x_direction": chart.x_direction,
                    "x_unit": measure_units[chart.x_measure_id],
                    "y_measure": chart.y_measure_id,
                    "y_direction": chart.y_direction,
                    "y_unit": measure_units[chart.y_measure_id],
                    "rows": rows,
                }
            )
        charts.append(projection)
    return charts


def _prepare_output(path: Path, suffix: str, overwrite: bool) -> tuple[Path, Path]:
    path = path.resolve()
    if path.suffix.lower() != suffix:
        raise ParameterError(f"Process chart output must end in {suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspaceError(f"output file already exists; use --force to replace it: {path}")
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}{path.suffix}")
    return path, temporary


def _commit_output(temporary: Path, path: Path, overwrite: bool) -> None:
    if overwrite:
        os.replace(temporary, path)
        return
    try:
        os.link(temporary, path)
    except FileExistsError as exc:
        raise WorkspaceError(f"output file already exists: {path}") from exc


def write_process_chart_csv(chart: dict, path: Path, overwrite: bool = False) -> Path:
    path, temporary = _prepare_output(path, ".csv", overwrite)
    if chart["kind"] in {"trajectory", "variant_comparison"}:
        value_names = chart["series"]
    else:
        value_names = ()
    headers = ["variant", "objective", "time", "phase", "x", "y", "value", "nondominated", "decisions"]
    headers.extend(value_names)
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            for source in chart["rows"]:
                row = {name: "" for name in headers}
                for name in ("variant", "objective", "time", "phase", "x", "y", "nondominated"):
                    value = source.get(name)
                    if isinstance(value, dict):
                        value = value.get("exact")
                    if value is not None:
                        row[name] = value
                if "value" in source:
                    row["value"] = source["value"]["exact"]
                if "decisions" in source:
                    row["decisions"] = ";".join(
                        f"{item['time']}:{item['action']}"
                        for item in source["decisions"]
                    )
                for name in value_names:
                    row[name] = source["values"][name]["exact"]
                writer.writerow(row)
        _commit_output(temporary, path, overwrite)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def render_process_chart_svg(chart: dict, path: Path, overwrite: bool = False) -> Path:
    path, temporary = _prepare_output(path, ".svg", overwrite)
    try:
        from pyparsing import PyparsingDeprecationWarning
    except ImportError:  # pragma: no cover - Matplotlib provides pyparsing
        PyparsingDeprecationWarning = Warning
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PyparsingDeprecationWarning)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8, 5))
    try:
        if chart["kind"] == "trajectory":
            groups: Dict[tuple, list] = {}
            for row in chart["rows"]:
                groups.setdefault((row["variant"], row["objective"]), []).append(row)
            for (variant, objective), rows in groups.items():
                for series in chart["series"]:
                    axis.plot(
                        [row["time_approximate"] for row in rows],
                        [row["values"][series]["approximate"] for row in rows],
                        label=f"{variant}/{objective}/{series}",
                    )
            for marker in chart["markers"]:
                axis.axvline(marker["time_approximate"], alpha=0.12, color="black")
            axis.set_xlabel("time")
        elif chart["kind"] == "decision_surface":
            scatter = axis.scatter(
                [row["x_approximate"] for row in chart["rows"]],
                [row["y_approximate"] for row in chart["rows"]],
                c=[row["value"]["approximate"] for row in chart["rows"]],
            )
            figure.colorbar(scatter, ax=axis, label=chart["value_measure"])
            axis.set_xlabel("decision_time_1")
            axis.set_ylabel("decision_time_2")
        elif chart["kind"] == "pareto":
            for variant in sorted({row["variant"] for row in chart["rows"]}):
                rows = [row for row in chart["rows"] if row["variant"] == variant]
                axis.scatter(
                    [row["x"]["approximate"] for row in rows],
                    [row["y"]["approximate"] for row in rows],
                    label=variant,
                    alpha=0.6,
                )
            axis.set_xlabel(chart["x_measure"])
            axis.set_ylabel(chart["y_measure"])
        else:
            rows = chart["rows"]
            labels = [f"{row['variant']}/{row['objective']}" for row in rows]
            for series in chart["series"]:
                axis.plot(
                    range(len(rows)),
                    [row["values"][series]["approximate"] for row in rows],
                    marker="o",
                    label=series,
                )
            axis.set_xticks(range(len(rows)), labels, rotation=30, ha="right")
        axis.set_title(chart["label"])
        axis.grid(True, alpha=0.25)
        axis.legend(loc="best")
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r"Glyph .* missing from font")
            figure.tight_layout()
            figure.savefig(temporary, format="svg", metadata={"Date": None})
        normalized = "\n".join(
            line.rstrip()
            for line in temporary.read_text(encoding="utf-8").splitlines()
        )
        temporary.write_text(normalized + "\n", encoding="utf-8")
        _commit_output(temporary, path, overwrite)
    finally:
        plt.close(figure)
        temporary.unlink(missing_ok=True)
    return path
