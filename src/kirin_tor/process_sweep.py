"""Source-declared bounded policy/parameter sweeps; no gameplay semantics."""
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
from math import prod

from .errors import ParameterError, SchemaError
from .process_expression import compile_process_expression, evaluate_process_expression, validate_process_value
from .process_ir import BooleanTypeIR, NumberTypeIR
from .scenario_ir import SweepAxisIR, SweepFamilyIR, SweepIR


def lower_sweep(source, scenario, registry, symbols):
    if source.sweep is None:
        return None
    if source.policy_ids or source.objective_ids or source.variant_ids or source.search_method or source.target:
        raise SchemaError("sweep selects policies through families and ranks through ranking", source.location)
    number = NumberTypeIR("dimensionless", registry.parse_unit("dimensionless"))

    def exact(expression, value_type):
        value = evaluate_process_expression(compile_process_expression(expression, value_type, symbols, registry), {}, registry)
        if not isinstance(value, Fraction):
            raise SchemaError("sweep bounds must be exact numbers", expression.location)
        validate_process_value(value, value_type, registry, expression.location)
        return value

    budget = exact(source.sweep.maximum_cases, number)
    if budget.denominator != 1 or not 1 <= budget <= 10000:
        raise SchemaError("maximum_cases must be an integer in 1..10000", source.location)
    measures = {m.id: m for m in scenario.measures}
    names = [name for name, _ in source.sweep.ranking]
    if len(set(names)) != len(names):
        raise SchemaError("sweep ranking measures must be unique", source.location)
    for name in names:
        if name not in measures or not isinstance(measures[name].value_type, (NumberTypeIR, BooleanTypeIR)):
            raise SchemaError(f"sweep ranking requires a numeric or boolean Measure: {name!r}", source.location)
    instances = {i.id: i for i in scenario.instances}
    policies = {p.id for p in scenario.policies}
    families = []
    ids = set()
    total = 0
    for family in source.sweep.families:
        if family.id in ids or family.policy_id not in policies:
            raise SchemaError("sweep family ids must be unique and policies must exist", source.location)
        ids.add(family.id)
        axes = []
        paths = set()
        for axis in family.axes:
            instance_id, input_id = axis.input_path.split(".")
            instance = instances.get(instance_id)
            inputs = {} if instance is None else {i.ref.member_id: i for i in instance.process.inputs}
            declaration = inputs.get(input_id)
            if axis.input_path in paths or declaration is None or not isinstance(declaration.value_type, NumberTypeIR):
                raise SchemaError(f"vary requires a unique numeric instance input: {axis.input_path!r}", source.location)
            paths.add(axis.input_path)
            start, end, step = (exact(e, declaration.value_type) for e in (axis.start, axis.end, axis.step))
            if step <= 0 or end < start or ((end - start) / step).denominator != 1:
                raise SchemaError("vary needs a positive step and an inclusive, exactly divisible range", source.location)
            count = int((end - start) / step) + 1
            axes.append(SweepAxisIR(instance_id, input_id, start, step, count))
        if family.enabled:
            total += prod(axis.count for axis in axes)
        if total > budget:
            raise SchemaError(f"sweep exceeds maximum_cases ({total} > {budget})", source.location)
        families.append(SweepFamilyIR(family.id, family.policy_id, tuple(axes), family.enabled))
    if total == 0:
        raise SchemaError("sweep requires at least one enabled family", source.location)
    return SweepIR(int(budget), total, tuple(families), source.sweep.ranking)


def sweep_cases(analysis):
    from .process_batch import ProcessBatchCase
    if analysis.sweep is None:
        raise ParameterError("analysis is not a sweep")
    cases = []
    for family in analysis.sweep.families:
        if not family.enabled:
            continue
        axes = [range(axis.count) for axis in family.axes]
        for index, values in enumerate(product(*axes)):
            inputs = tuple((axis.instance_id, axis.input_id, axis.start + axis.step * offset)
                           for axis, offset in zip(family.axes, values))
            cases.append(ProcessBatchCase(f"{family.id}/{index + 1}", family.policy_id, inputs))
    return tuple(cases)


@dataclass(frozen=True)
class SweepAnalysisResult:
    rows: tuple


def execute_sweep(analysis, scenario, registry):
    from .process_batch import run_process_batch
    from .timeout import report_progress
    rows = []
    report_progress({"stage": "sweep", "completed": 0, "total": analysis.sweep.case_count})
    for row in run_process_batch(scenario, registry, sweep_cases(analysis), maximum_cases=analysis.sweep.maximum_cases):
        rows.append(row)
        report_progress({"stage": "sweep", "completed": len(rows), "total": analysis.sweep.case_count})
    return SweepAnalysisResult(tuple(rows))


def execute_sweep_case(analysis, scenario, registry, case_id, include_trace):
    from .process_analysis import RunAnalysisResult, _measure_expectations, _run_distribution
    case = next((case for case in sweep_cases(analysis) if case.id == case_id), None)
    if case is None:
        raise ParameterError(f"unknown sweep case {case_id!r}")
    policy = next(policy for policy in scenario.policies if policy.id == case.policy_id)
    outcomes, explored = _run_distribution(scenario, registry, policy=policy, include_trace=include_trace,
        input_overrides={(i, n): v for i, n, v in case.inputs}, aggregate_equivalent_states=not analysis.charts)
    return RunAnalysisResult(analysis.qualified_id, "run", outcomes, explored, _measure_expectations(scenario, outcomes))


def sweep_result_data(result, analysis, scenario):
    from .process_analysis import _value_data
    measures = {m.id: m for m in scenario.measures}

    def values(row):
        output = dict(row.measure_expectations)
        for name, declaration in measures.items():
            if isinstance(declaration.value_type, BooleanTypeIR):
                output[name] = all(dict(o.measures)[name] for o in row.outcomes)
        return output

    def key(row):
        output = values(row)
        return tuple(Fraction(output[name]) * (1 if direction == "maximize" else -1)
                     for name, direction in analysis.sweep.ranking)

    successful = sorted((row for row in result.rows if not row.error), key=lambda row: row.case.id)
    successful.sort(key=key, reverse=True)
    best = values(successful[0]) if successful else {}
    ranks = {}
    previous = None
    rank = 0
    for index, row in enumerate(successful):
        if key(row) != previous:
            rank = index + 1
        previous = key(row)
        ranks[row.case.id] = rank

    def delta(value):
        if value == 0:
            return "0"
        with localcontext() as context:
            context.prec = 6
            return format(Decimal(value.numerator) / Decimal(value.denominator), ".3E")

    rows = []
    for row in (*successful, *(r for r in result.rows if r.error)):
        output = {} if row.error else values(row)
        rows.append({"id": row.case.id, "policy": row.case.policy_id, "rank": ranks.get(row.case.id),
            "inputs": {f"{i}.{n}": _value_data(v) for i, n, v in row.case.inputs}, "error": row.error,
            "measures": {name: {"exact": _value_data(v), "approximate": float(v),
                                 "formatted": str(v).lower() if isinstance(v, bool) else format(float(v), ".6g")}
                         for name, v in output.items()},
            "deltas": {name: {"exact": _value_data(Fraction(output[name]) - Fraction(best[name])),
                              "formatted": delta(Fraction(output[name]) - Fraction(best[name]))}
                       for name, _ in analysis.sweep.ranking if name in output and name in best},
            "outcomes": [{"probability": _value_data(o.probability),
                          "measures": {k: _value_data(v) for k, v in o.measures}} for o in row.outcomes]})
    return {"cases": rows, "planned_cases": analysis.sweep.case_count, "completed_cases": len(result.rows),
            "failed_cases": len(result.rows) - len(successful), "ranking_complete": len(result.rows) == len(successful),
            "scope": "declared_policy_grid", "ranking": [{"measure": n, "direction": d, "label": measures[n].label or n}
                                                         for n, d in analysis.sweep.ranking]}
