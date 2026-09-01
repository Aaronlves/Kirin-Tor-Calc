"""CSV and Matplotlib adapters over the shared scan operation."""

from __future__ import annotations

import csv
import json
import math
import os
import uuid
import warnings
from pathlib import Path
from typing import Optional

from .errors import ParameterError, WorkspaceError


def write_scan_csv(scan: dict, path: Path, overwrite: bool = False) -> Path:
    path = path.resolve()
    if path.suffix.lower() != ".csv":
        raise ParameterError("scan data output must end in .csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspaceError(f"output file already exists; use --force to replace it: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    targets = scan["targets"]
    headers = [
        "x", "x_approximate", "x_unit", "parameters_json", "dependency_ids_json",
        "precision", "display_digits",
    ]
    for target in targets:
        headers.extend(
            [
                target,
                f"{target}__approximate",
                f"{target}__formatted",
                f"{target}__error",
                f"{target}__unit",
            ]
        )
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            for source in scan["rows"]:
                row = {
                    "x": source["x"],
                    "x_approximate": source["x_approximate"],
                    "x_unit": scan["x_unit"],
                    "parameters_json": json.dumps(scan.get("parameters", {}), sort_keys=True),
                    "dependency_ids_json": json.dumps(scan.get("dependency_ids", []), sort_keys=True),
                    "precision": scan.get("precision"),
                    "display_digits": scan.get("display_digits"),
                }
                for target in targets:
                    value = source["values"][target]
                    row[target] = value["exact"] or ""
                    row[f"{target}__approximate"] = value["approximate"] or ""
                    row[f"{target}__formatted"] = value.get("formatted") or ""
                    row[f"{target}__error"] = value["error"] or ""
                    row[f"{target}__unit"] = scan["units"][target]
                writer.writerow(row)
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise WorkspaceError(f"output file already exists: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return path


def write_grid_csv(grid: dict, path: Path, overwrite: bool = False) -> Path:
    """Write one two-axis scan without flattening away either input coordinate."""
    path = path.resolve()
    if path.suffix.lower() != ".csv":
        raise ParameterError("grid data output must end in .csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspaceError(f"output file already exists; use --force to replace it: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    headers = [
        "x",
        "x_approximate",
        "x_unit",
        "y",
        "y_approximate",
        "y_unit",
        "target",
        "value",
        "value_approximate",
        "value_formatted",
        "value_unit",
        "error",
        "parameters_json",
        "dependency_ids_json",
    ]
    try:
        with temporary.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            for source in grid["rows"]:
                value = source["value"]
                writer.writerow(
                    {
                        "x": source["x"],
                        "x_approximate": source["x_approximate"],
                        "x_unit": grid["x_unit"],
                        "y": source["y"],
                        "y_approximate": source["y_approximate"],
                        "y_unit": grid["y_unit"],
                        "target": grid["target"],
                        "value": value["exact"] or "",
                        "value_approximate": value["approximate"] or "",
                        "value_formatted": value.get("formatted") or "",
                        "value_unit": grid["unit"],
                        "error": value["error"] or "",
                        "parameters_json": json.dumps(
                            grid.get("parameters", {}), sort_keys=True
                        ),
                        "dependency_ids_json": json.dumps(
                            grid.get("dependency_ids", []), sort_keys=True
                        ),
                    }
                )
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise WorkspaceError(f"output file already exists: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return path


def render_plot(
    scan: dict,
    path: Path,
    overwrite: bool = False,
    title: Optional[str] = None,
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
    curve_labels: Optional[dict[str, str]] = None,
) -> Path:
    suffix = path.suffix.lower()
    if suffix not in {".svg", ".png"}:
        raise ParameterError("plot output must end in .svg or .png")
    try:
        from pyparsing import PyparsingDeprecationWarning
    except ImportError:  # pragma: no cover - Matplotlib provides pyparsing
        PyparsingDeprecationWarning = Warning
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=PyparsingDeprecationWarning, module=r"matplotlib\..*")
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager

    if suffix == ".svg":
        matplotlib.rcParams["svg.hashsalt"] = "kirin-tor-v1"

    available_fonts = {item.name for item in font_manager.fontManager.ttflist}
    for candidate in (
        "Hiragino Sans GB",
        "PingFang SC",
        "Arial Unicode MS",
        "Noto Sans CJK SC",
        "Microsoft YaHei",
        "SimHei",
        "Songti SC",
    ):
        if candidate in available_fonts:
            matplotlib.rcParams["font.sans-serif"] = [
                candidate,
                *matplotlib.rcParams.get("font.sans-serif", []),
            ]
            matplotlib.rcParams["axes.unicode_minus"] = False
            break

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise WorkspaceError(f"output file already exists; use --force to replace it: {path}")
    temporary = path.with_name(f".{path.stem}.{uuid.uuid4().hex}{path.suffix}")
    figure, axis = plt.subplots(figsize=(8, 5))
    try:
        explicit_labels = curve_labels or {}
        default_labels = scan.get("labels", {})

        def display_label(target: str) -> str:
            return explicit_labels.get(target, default_labels.get(target, target))

        xs = [float(row["x_approximate"]) for row in scan["rows"]]
        if any(not math.isfinite(value) for value in xs):
            raise ParameterError("plot axis contains values outside finite float display range")
        for target in scan["targets"]:
            ys = []
            for row in scan["rows"]:
                value = row["values"][target]
                if value["error"] is None:
                    converted = float(value["approximate"])
                    if not math.isfinite(converted):
                        raise ParameterError(
                            f"plot curve {target} contains values outside finite float display range"
                        )
                    ys.append(converted)
                else:
                    ys.append(math.nan)
            axis.plot(xs, ys, label=display_label(target))
        axis_name = scan.get("x_display_label") or scan["x"]
        axis.set_xlabel(x_label or f"{axis_name} [{scan['x_unit']}]")
        if len(scan["targets"]) == 1:
            target = scan["targets"][0]
            axis.set_ylabel(y_label or f"{display_label(target)} [{scan['units'][target]}]")
        else:
            axis.set_ylabel(y_label or "value (see legend and CSV units)")
            axis.legend()
        if title:
            axis.set_title(title)
        axis.grid(True, alpha=0.25)
        figure.tight_layout()
        figure.savefig(
            temporary,
            format=suffix[1:],
            metadata={"Date": None} if suffix == ".svg" else None,
        )
        if suffix == ".svg":
            normalized = "\n".join(
                line.rstrip() for line in temporary.read_text(encoding="utf-8").splitlines()
            )
            temporary.write_text(normalized + "\n", encoding="utf-8")
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise WorkspaceError(f"output file already exists: {path}") from exc
    finally:
        plt.close(figure)
        temporary.unlink(missing_ok=True)
    return path
