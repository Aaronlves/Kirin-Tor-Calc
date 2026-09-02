from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from kirin_tor.process_analysis import RunAnalysisResult, execute_process_analysis
from kirin_tor.workspace import Workspace, initialize


def _workspace(root: Path) -> Workspace:
    root = initialize(root)
    (root / "entries" / "bounded_iteration.kirin").write_text(
        """@kirin 2
@entry bounded_iteration

process failure_protection:
  input steps: nonnegative_integer = 3 in 0..5
  input base_chance: probability = 1/10
  input increase: probability = 1/20
  input cap: probability = 3/10
  state current: probability = base_chance
  state index: count = 0 in 0..5
  event input start()
  event internal advance()
  key next_step
  phase step
  on start() when index < steps:
    next current = min(current + increase, cap)
    next index = index + 1
    when index + 1 < steps:
      schedule advance() after 1 second phase step key next_step
  on advance() when index < steps:
    next current = min(current + increase, cap)
    next index = index + 1
    when index + 1 < steps:
      schedule advance() after 1 second phase step key next_step
  observe chance: probability = current
  observe completed_steps: count = index

scenario three_failures:
  phases:
    - step
  use actor = failure_protection:
    phase step = step
  at 0 second phase step:
    send actor.start()
  measure final_chance: probability = final(actor.chance)
  measure final_steps: count = final(actor.completed_steps)
  bounds:
    horizon = 5 second
    maximum_events = 5
    maximum_decisions = 1
    maximum_branches = 1
    maximum_entities = 1

analysis result:
  using = three_failures
  operation = run
""",
        encoding="utf-8",
    )
    return Workspace.load(root)


def test_bounded_iteration_uses_process_events_and_shared_runtime(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path / "iteration")
    result = execute_process_analysis(
        workspace.analyses["bounded_iteration.result"],
        workspace.scenarios["bounded_iteration.three_failures"],
        workspace.units,
    )
    assert isinstance(result, RunAnalysisResult)
    assert len(result.outcomes) == 1
    assert dict(result.outcomes[0].measures) == {
        "final_chance": Fraction(1, 4),
        "final_steps": Fraction(3),
    }
    assert result.outcomes[0].result.event_count == 3
