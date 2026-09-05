from fractions import Fraction as F

import pytest

from kirin_tor.errors import ParameterError
from kirin_tor.process_batch import ProcessBatchCase, run_process_batch
from kirin_tor.workspace import Workspace, initialize


@pytest.fixture
def workspace(tmp_path):
    root = initialize(tmp_path / 'workspace')
    (root / 'entries/model.kirin').write_text('''@kirin 2
@entry batch
process counter:
  input amount: dimensionless = 1/3 in 0..2
  state value: dimensionless = 0
  event input add()
  on add():
    next value = value + amount
  observe current: dimensionless = value
scenario main:
  phases:
    - decision
  use actor = counter:
  action add:
    send actor.add() phase decision
  policy adding:
    choose add when actor.current < 10
    otherwise wait
  policy waiting:
    otherwise wait
  decide every 1 second from 1 second phase decision:
    - add
    - wait
  measure total: dimensionless = final(actor.current)
  bounds:
    horizon = 3 second
    maximum_events = 10
    maximum_decisions = 10
    maximum_branches = 10
    maximum_entities = 1
''')
    return Workspace.load(root)


def test_exact_cases_preserve_source_and_failures(workspace):
    source = workspace.scenarios['batch.main']
    cases = [ProcessBatchCase('default', 'adding'),
             ProcessBatchCase('half', 'adding', (('actor', 'amount', F(1, 2)),), F(2)),
             ProcessBatchCase('domain', 'adding', (('actor', 'amount', F(3)),)),
             ProcessBatchCase('unknown', 'missing'),
             ProcessBatchCase('wait', 'waiting')]
    rows = list(run_process_batch(source, workspace.units, cases, maximum_cases=5))
    assert [row.case.id for row in rows] == [case.id for case in cases]
    assert dict(rows[0].outcomes[0].measures)['total'] == F(1)
    assert dict(rows[1].outcomes[0].measures)['total'] == F(1)
    assert rows[2].error['code'] == 'domain_error'
    assert rows[3].error['code'] == 'parameter_error'
    assert dict(rows[4].measure_expectations)['total'] == F(0)
    assert source.bounds.horizon == F(3)


@pytest.mark.parametrize('cases,budget', [([],1), ([ProcessBatchCase('a','adding')],0),
    ([ProcessBatchCase('a','adding')]*2,2), ([ProcessBatchCase('a','adding'),ProcessBatchCase('b','adding')],1)])
def test_batch_rejects_invalid_budget_and_identity_before_execution(workspace, cases, budget):
    with pytest.raises(ParameterError):
        run_process_batch(workspace.scenarios['batch.main'], workspace.units, cases, maximum_cases=budget)


def test_case_cannot_expand_horizon_or_override_silently(workspace):
    cases = [ProcessBatchCase('long','adding',horizon=F(4)),
             ProcessBatchCase('duplicate','adding',(('actor','amount',F(1)),('actor','amount',F(2)))),
             ProcessBatchCase('unknown','adding',(('wrong','amount',F(1)),)),
             ProcessBatchCase('float','adding',(('actor','amount',0.1),))]
    rows=list(run_process_batch(workspace.scenarios['batch.main'],workspace.units,cases,maximum_cases=4))
    assert all(row.error and not row.outcomes for row in rows)


def test_batch_freezes_case_list_and_preserves_per_run_fuel(workspace):
    from dataclasses import replace
    source=workspace.scenarios['batch.main']
    source=replace(source,bounds=replace(source.bounds,maximum_events=1))
    cases=[ProcessBatchCase('exhausts','adding'),ProcessBatchCase('wait','waiting')]
    results=run_process_batch(source,workspace.units,cases,maximum_cases=2)
    cases.append(ProcessBatchCase('late','adding'))
    rows=list(results)
    assert len(rows)==2
    assert rows[0].error['code']=='process_fuel_exhausted'
    assert rows[1].error is None


def test_random_cases_use_exact_distribution_measures(workspace):
    path=workspace.root / 'entries/model.kirin'
    source=path.read_text().replace('    next value = value + amount', '''    branch coin independent:
      probability 1/3:
        next value = value + amount
      probability 2/3:
        next value = value''')
    path.write_text(source)
    ws=Workspace.load(workspace.root)
    row=next(run_process_batch(ws.scenarios['batch.main'],ws.units,
             [ProcessBatchCase('coin','adding',horizon=F(1))],maximum_cases=1))
    assert row.error is None
    assert sum(o.probability for o in row.outcomes)==1
    assert dict(row.measure_expectations)['total']==F(1,9)
    assert sorted(dict(o.measures)['total'] for o in row.outcomes)==[F(0),F(1,3)]
