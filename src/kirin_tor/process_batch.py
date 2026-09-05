"""Bounded parameter batches over source-declared Process policies.

This API owns no transition rules or optimizer. Each case uses the ordinary
exact distribution executor and source Measures. Callers may split a declared
finite batch into chunks for scheduling, but must retain failed cases.
"""
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Iterator, Optional, Sequence, Tuple

from .errors import KTError, ParameterError
from .process_analysis import _measure_expectations, _run_distribution
from .process_expression import ProcessValue
from .scenario_ir import ScenarioIR
from .units import UnitRegistry

MAX_PROCESS_BATCH_CASES = 10000


@dataclass(frozen=True)
class ProcessBatchCase:
    id: str
    policy_id: str
    inputs: Tuple[Tuple[str, str, ProcessValue], ...] = ()
    horizon: Optional[Fraction] = None


@dataclass(frozen=True)
class ProcessBatchOutcome:
    probability: Fraction
    measures: Tuple[Tuple[str, ProcessValue], ...]


@dataclass(frozen=True)
class ProcessBatchResult:
    case: ProcessBatchCase
    horizon: Fraction
    outcomes: Tuple[ProcessBatchOutcome, ...] = ()
    measure_expectations: Tuple[Tuple[str, Fraction], ...] = ()
    error: Optional[dict] = None


def run_process_batch(
    scenario: ScenarioIR,
    registry: UnitRegistry,
    cases: Sequence[ProcessBatchCase],
    *,
    maximum_cases: int,
) -> Iterator[ProcessBatchResult]:
    """Validate a finite batch up front, then yield compact exact case results.

    Horizons may shorten the source bound, never enlarge it. Existing per-run
    event/decision/branch fuel is retained. Domain, policy and fuel errors are
    returned per case; infrastructure/programming exceptions are not swallowed.
    A complete batch establishes results for its explicit cases, not a global
    optimum over other parameters or policies. No floating-point coercion occurs.
    """
    if type(maximum_cases) is not int or not 1 <= maximum_cases <= MAX_PROCESS_BATCH_CASES:
        raise ParameterError(f"maximum_cases must be in 1..{MAX_PROCESS_BATCH_CASES}")
    if not 1 <= len(cases) <= maximum_cases:
        raise ParameterError("Process batch must be nonempty and within maximum_cases")
    cases = tuple(cases)
    ids = [case.id for case in cases]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ParameterError("Process batch case ids must be nonempty and unique")
    policies = {policy.id: policy for policy in scenario.policies}

    def execute() -> Iterator[ProcessBatchResult]:
        for case in cases:
            horizon = scenario.bounds.horizon if case.horizon is None else case.horizon
            try:
                if not isinstance(horizon, Fraction) or not 0 < horizon <= scenario.bounds.horizon:
                    raise ParameterError("case horizon must be exact, positive and within the source horizon")
                if case.policy_id not in policies:
                    raise ParameterError(f"unknown Process policy {case.policy_id!r}")
                keys = [(instance, member) for instance, member, _ in case.inputs]
                if len(set(keys)) != len(keys):
                    raise ParameterError("duplicate Process input override")
                selected = replace(scenario, bounds=replace(scenario.bounds, horizon=horizon))
                outcomes, _ = _run_distribution(
                    selected, registry, policy=policies[case.policy_id],
                    include_trace=False, aggregate_equivalent_states=True,
                    input_overrides={(instance, member): value for instance, member, value in case.inputs},
                )
                yield ProcessBatchResult(
                    case, horizon,
                    tuple(ProcessBatchOutcome(row.probability, row.measures) for row in outcomes),
                    _measure_expectations(selected, outcomes),
                )
            except KTError as error:
                yield ProcessBatchResult(case, horizon, error=error.as_dict())

    return execute()
