from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from kirin_tor.process_analysis import (
    ReachAnalysisResult,
    SteadyAnalysisResult,
    execute_process_analysis,
)
from kirin_tor.workspace import Workspace, initialize


def _workspace(root: Path) -> Workspace:
    root = initialize(root)
    (root / "entries" / "finite_chain.kirin").write_text(
        """@kirin 2
@entry finite_chain

process proc_cycle:
  input proc_chance: probability = 1/4
  state cooldown: boolean = false
  event input step()
  on step():
    branch next_state independent:
      probability proc_chance:
        next cooldown = true
      probability 1 - proc_chance:
        next cooldown = false
  observe is_cooldown: boolean = cooldown

scenario one_step:
  phases:
    - step
  use actor = proc_cycle:
  at 0 second phase step:
    send actor.step()
  bounds:
    horizon = 1 second
    maximum_events = 1
    maximum_decisions = 1
    maximum_branches = 8
    maximum_entities = 1

analysis stationary:
  using = one_step
  operation = steady

scenario three_steps:
  phases:
    - step
  use actor = proc_cycle:
  every 1 second from 0 second until 2 second phase step:
    send actor.step()
  bounds:
    horizon = 3 second
    maximum_events = 3
    maximum_decisions = 1
    maximum_branches = 64
    maximum_entities = 1

analysis reaches_cooldown:
  using = three_steps
  operation = reach
  target = actor.is_cooldown
""",
        encoding="utf-8",
    )
    return Workspace.load(root)


def test_finite_random_state_uses_process_steady_and_reach(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path / "state")
    steady = execute_process_analysis(
        workspace.analyses["finite_chain.stationary"],
        workspace.scenarios["finite_chain.one_step"],
        workspace.units,
    )
    assert isinstance(steady, SteadyAnalysisResult)
    probabilities = {
        dict(state)["actor.cooldown"]: probability
        for state, probability in zip(steady.states, steady.probabilities)
    }
    assert probabilities == {False: Fraction(3, 4), True: Fraction(1, 4)}

    reach = execute_process_analysis(
        workspace.analyses["finite_chain.reaches_cooldown"],
        workspace.scenarios["finite_chain.three_steps"],
        workspace.units,
    )
    assert isinstance(reach, ReachAnalysisResult)
    assert reach.probability == Fraction(37, 64)
