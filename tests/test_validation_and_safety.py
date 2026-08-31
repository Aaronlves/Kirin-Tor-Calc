from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
import sympy as sp

from kirin_tor.engine import Engine
from kirin_tor.errors import (
    DependencyCycleError,
    DomainError,
    ExpressionError,
    MathTimeoutError,
    ParameterError,
    ReferenceError,
    SchemaError,
    UnitError,
)
from kirin_tor.operations import evaluate, scan_values, solve_equation, transform
from kirin_tor.timeout import run_with_timeout
from kirin_tor.workspace import Workspace

from conftest import load_kirin, minimal_entry, write_kirin


def test_missing_parameter_and_undeclared_variable(example_workspace: Path) -> None:
    combo_path = example_workspace / "entries" / "组合模型.kirin"
    combo = load_kirin(combo_path)
    del combo["inputs"]["crit"]["default"]
    write_kirin(combo_path, combo)
    engine = Engine(Workspace.load(example_workspace))
    with pytest.raises(ParameterError, match="missing parameter"):
        evaluate(engine, "combo.total")

    combo["outputs"]["total"]["expression"] = "skill_a.expected(crti)"
    write_kirin(combo_path, combo)
    with pytest.raises(ExpressionError, match="undeclared variable 'crti'"):
        Engine(Workspace.load(example_workspace)).validate_all()


def test_duplicate_id_and_missing_reference(example_workspace: Path) -> None:
    duplicate = load_kirin(example_workspace / "entries" / "技能甲.kirin")
    write_kirin(example_workspace / "entries" / "重复.kirin", duplicate)
    with pytest.raises(SchemaError, match="duplicate id 'skill_a'"):
        Workspace.load(example_workspace)
    (example_workspace / "entries" / "重复.kirin").unlink()

    combo_path = example_workspace / "entries" / "组合模型.kirin"
    combo = load_kirin(combo_path)
    combo["outputs"]["total"]["expression"] = "missing_skill.expected(crit)"
    write_kirin(combo_path, combo)
    with pytest.raises(ReferenceError, match="missing reference"):
        Engine(Workspace.load(example_workspace)).validate_all()


def test_dependency_cycle_reports_path(example_workspace: Path) -> None:
    write_kirin(example_workspace / "entries" / "a.kirin", minimal_entry("a", "b.result"))
    write_kirin(example_workspace / "entries" / "b.kirin", minimal_entry("b", "a.result"))
    with pytest.raises(DependencyCycleError, match=r"a\.result -> b\.result -> a\.result"):
        Engine(Workspace.load(example_workspace)).resolve_target("a.result")


def test_probability_bounds_division_domain_and_unit_errors(example_workspace: Path) -> None:
    workspace = Workspace.load(example_workspace)
    with pytest.raises(ParameterError, match="above maximum"):
        evaluate(Engine(workspace), "combo.total", overrides={"crit": "1.01"})
    with pytest.raises(UnitError, match="incompatible units"):
        solve_equation(Engine(workspace), "combo.total", "crit", "3000 time", "0:1")
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(Engine(workspace), "skill_a.expected(2)")

    ratio = minimal_entry(
        "ratio",
        "x / x",
        inputs={"x": {"unit": "dimensionless"}},
    )
    write_kirin(example_workspace / "entries" / "ratio.kirin", ratio)
    engine = Engine(Workspace.load(example_workspace))
    symbolic = transform(engine, "simplify", "ratio.result", keep={"x"})
    assert symbolic["expression"] == "1"
    assert any("Ne(ratio.x, 0)" == condition for condition in symbolic["conditions"])
    with pytest.raises(DomainError, match="domain condition failed"):
        evaluate(Engine(Workspace.load(example_workspace)), "ratio.result", overrides={"x": "0"})

    conditional = minimal_entry(
        "conditional_domain",
        "if_else(x > 0, sqrt(x), sqrt(-x))",
        inputs={"x": {"unit": "dimensionless"}},
    )
    write_kirin(example_workspace / "entries" / "conditional.kirin", conditional)
    assert evaluate(
        Engine(Workspace.load(example_workspace)),
        "conditional_domain.result",
        overrides={"x": "1"},
    )["exact"] == "1"
    assert evaluate(
        Engine(Workspace.load(example_workspace)),
        "conditional_domain.result",
        overrides={"x": "-1"},
    )["exact"] == "1"

    combo_path = example_workspace / "entries" / "组合模型.kirin"
    combo = load_kirin(combo_path)
    combo["outputs"]["total"]["expression"] = "skill_a.base_damage + crit"
    write_kirin(combo_path, combo)
    with pytest.raises(UnitError, match="incompatible units"):
        Engine(Workspace.load(example_workspace)).validate_all()


def test_restricted_parser_blocks_code_and_complexity(example_workspace: Path) -> None:
    engine = Engine(Workspace.load(example_workspace))
    with pytest.raises(ExpressionError, match="not allowed or declared"):
        engine.resolve_target("__import__(1)")
    with pytest.raises(ExpressionError, match="nested attribute access|not allowed"):
        engine.resolve_target("skill_a.base_damage.real")
    with pytest.raises(ExpressionError, match="AST nodes|AST depth"):
        engine.resolve_target(" + ".join(["1"] * 110))
    with pytest.raises(ExpressionError, match="exponent"):
        engine.resolve_target("2 ** 101")
    assert evaluate(engine, "sum(i, i, 1, 3)")["exact"] == "6"


def test_kirin_decimal_is_exact_without_quotes(example_workspace: Path) -> None:
    scenario_path = example_workspace / "scenarios" / "decimal.kirin"
    scenario_path.write_text(
        "@kirin 1\n@scenario decimal\n\nvalues:\n  combo.crit = 0.2\n",
        encoding="utf-8",
    )
    result = evaluate(Engine(Workspace.load(example_workspace)), "combo.total", "decimal")
    assert result["exact"] == "2640"


def test_duplicate_kirin_members_are_rejected(example_workspace: Path) -> None:
    path = example_workspace / "entries" / "duplicate_key.kirin"
    path.write_text(
        "@kirin 1\n@entry duplicate\n\ninputs:\n  x: number[dimensionless] = 1\n  x: number[dimensionless] = 2\n",
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="duplicate input 'x'") as caught:
        Workspace.load(example_workspace)
    assert caught.value.location.line == 6


def test_legacy_business_entry_types_are_not_core_schema_types(example_workspace: Path) -> None:
    path = example_workspace / "entries" / "legacy.kirin"
    path.write_text("@kirin 1\n@skill legacy\n", encoding="utf-8")
    with pytest.raises(SchemaError, match="second declaration"):
        Workspace.load(example_workspace)


def test_invalid_scan_point_records_reason_instead_of_zero(example_workspace: Path) -> None:
    entry = minimal_entry(
        "root_model",
        "sqrt(x - 1/2)",
        inputs={"x": {"unit": "probability"}},
    )
    write_kirin(example_workspace / "entries" / "root.kirin", entry)
    scan = scan_values(Engine(Workspace.load(example_workspace)), "x", "0:1", 3, ["root_model.result"])
    first = scan["rows"][0]["values"]["root_model.result"]
    assert first["exact"] is None
    assert first["error"]
    assert scan["rows"][1]["values"]["root_model.result"]["exact"] == "0"


def _write_pid_and_sleep(path: str) -> None:
    Path(path).write_text(str(os.getpid()), encoding="ascii")
    time.sleep(30)


def test_timeout_terminates_worker_process(tmp_path: Path) -> None:
    pid_path = tmp_path / "worker.pid"
    timeout_seconds = 5.0 if sys.platform == "win32" else 0.2
    with pytest.raises(MathTimeoutError, match="terminated"):
        run_with_timeout(
            _write_pid_and_sleep,
            (str(pid_path),),
            timeout_seconds=timeout_seconds,
        )
    child_pid = int(pid_path.read_text(encoding="ascii"))
    if sys.platform != "win32":
        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
