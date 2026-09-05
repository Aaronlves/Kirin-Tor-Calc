from fractions import Fraction
import json

import pytest

from kirin_tor.cli import app
from kirin_tor.errors import KTError, ParameterError
from kirin_tor.kirin_syntax import render_kirin_document
from kirin_tor.operations import analyze_process, process_analysis_request
from kirin_tor.records import replay
from kirin_tor.workspace import Workspace, initialize
from conftest import make_cli_runner

SOURCE = '''@kirin 2
@entry trial
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
    choose add when actor.current < 20
    otherwise wait
  policy waiting:
    otherwise wait
  decide every 1 second from 1 second phase decision:
    - add
    - wait
  measure positive: boolean = final(actor.current > 0)
  measure total: dimensionless = final(actor.current)
  bounds:
    horizon = 3 second
    maximum_events = 10
    maximum_decisions = 10
    maximum_branches = 10
    maximum_entities = 1
analysis sweep_it:
  using = main
  operation = sweep
  maximum_cases = 10
  ranking:
    - maximize positive
    - maximize total
  family amounts:
    policy = adding
    vary actor.amount from 1/3 to 1 step 1/3
  family wait:
    policy = waiting
  chart trajectory:
    kind = trajectory
    series:
      - actor.current
'''


def workspace(tmp_path, source=SOURCE):
    root=initialize(tmp_path/'workspace')
    (root/'entries/model.kirin').write_text(source)
    return Workspace.load(root)


def test_sweep_exact_ranking_and_case_trajectory(tmp_path):
    ws=workspace(tmp_path)
    r=analyze_process(ws,'trial.sweep_it',include_trace=False)
    assert r['planned_cases']==4 and r['ranking_complete']
    assert [c['id'] for c in r['cases']]==['amounts/3','amounts/2','amounts/1','wait/1']
    assert r['cases'][0]['measures']['total']['exact']=='3'
    assert r['cases'][1]['deltas']['total']['exact']=='-1'
    assert r['scope']=='declared_policy_grid' and 'charts' not in r
    selected=analyze_process(ws,'trial.sweep_it',case_id='amounts/2',include_trace=False)
    assert selected['case_id']=='amounts/2'
    assert selected['analysis_operation']=='sweep_case'
    assert selected['charts'][0]['kind']=='trajectory'
    assert selected['outcomes'][0]['measures']['total']=='2'
    request=process_analysis_request(ws,'trial.sweep_it',case_id='amounts/2')
    assert request['sweep']['case_count']==4 and request['case_id']=='amounts/2'
    with pytest.raises(ParameterError):
        process_analysis_request(ws,'trial.sweep_it',case_id='amounts/99')


def test_sweep_retains_failures_and_strict_ties(tmp_path):
    ws=workspace(tmp_path,SOURCE.replace('from 1/3 to 1 step 1/3','from 0 to 3 step 1'))
    r=analyze_process(ws,'trial.sweep_it')
    assert r['planned_cases']==5 and r['failed_cases']==1 and not r['ranking_complete']
    assert r['cases'][-1]['error']['code']=='domain_error'
    assert r['cases'][2]['rank']==r['cases'][3]['rank']==3


@pytest.mark.parametrize('old,new',[
 ('maximum_cases = 10','maximum_cases = 3'),
 ('step 1/3','step 0'),
 ('step 1/3','step 2/5'),
 ('actor.amount from','actor.missing from'),
 ('maximize total','maximize missing'),
 ('operation = sweep','operation = run'),
 ('policy = adding\n    vary','policy = missing\n    vary'),
 ('from 1/3','from 1 second'),
])
def test_sweep_rejects_invalid_declarations(tmp_path,old,new):
    with pytest.raises(KTError):
        workspace(tmp_path,SOURCE.replace(old,new))


def test_cli_saved_sweep_and_case_replay(tmp_path,monkeypatch):
    ws=workspace(tmp_path)
    monkeypatch.chdir(ws.root)
    runner=make_cli_runner()
    response=runner.invoke(app,['analyze','trial.sweep_it','--case','amounts/2','--no-trace','--save-run','selected','--json'])
    assert response.exit_code==0,response.output
    assert json.loads(response.output)['case_id']=='amounts/2'
    replayed = replay(ws, 'selected')
    assert replayed['matches_recorded_result']
    whole=runner.invoke(app,['analyze','trial.sweep_it','--no-trace','--save-run','whole','--json'])
    assert whole.exit_code==0,whole.output
    assert json.loads(whole.output)['planned_cases']==4
    assert replay(ws,'whole')['matches_recorded_result']
    plain=runner.invoke(app,['analyze','trial.sweep_it','--no-trace'])
    assert plain.exit_code==0 and '4/4' in plain.output
    # Round-trip source rendering must retain the author-declared grid and rank.
    path=ws.root/'entries/model.kirin'
    text=render_kirin_document(ws.get_entry('trial'))
    assert 'vary actor.amount from 1/3 to 1 step 1/3' in text
    path.write_text(text)
    loaded=Workspace.load(ws.root)
    assert loaded.analyses['trial.sweep_it'].sweep.case_count==4


def test_workbench_source_controls_and_case_record(tmp_path):
    from kirin_tor.workbench import Workbench
    ws=workspace(tmp_path)
    workbench=Workbench(ws.root)
    definition=workbench.bootstrap()['index']['analyses'][0]
    assert definition['analysis_operation']=='sweep'
    assert definition['sweep']['case_count']==4
    assert definition['sweep']['families'][0]['axes'][0]['start']=='1/3'
    assert definition['sweep']['maximum_cases_line'] > 0
    result=workbench.execute('process_analysis',{'target':'trial.sweep_it','case_id':'amounts/2','timeout':10})
    assert result['analysis_operation']=='sweep_case'


def test_sweep_progress_is_observational_and_does_not_change_result(tmp_path):
    from kirin_tor.timeout import set_progress_sink
    ws=workspace(tmp_path)
    progress=[]
    set_progress_sink(progress.append)
    try:
        result=analyze_process(ws,'trial.sweep_it',include_trace=False)
    finally:
        set_progress_sink(None)
    assert result['completed_cases']==4
    assert progress and all(p['stage']=='sweep' and 0<=p['completed']<=p['total']==4 for p in progress)
    assert [p['completed'] for p in progress]==sorted(p['completed'] for p in progress)


def test_disabled_families_are_retained_but_not_enumerated(tmp_path):
    ws=workspace(tmp_path,SOURCE.replace('  family amounts:\n','  family amounts:\n    enabled = false\n'))
    r=analyze_process(ws,'trial.sweep_it')
    assert r['planned_cases']==1 and r['cases'][0]['id']=='wait/1'


def test_workbench_sweep_reports_real_progress_and_cancels(tmp_path):
    import time
    from kirin_tor.web import OperationJobManager
    source=SOURCE.replace('maximum_cases = 10','maximum_cases = 10000').replace('from 1/3 to 1 step 1/3','from 0 to 9998 step 1')
    ws=workspace(tmp_path,source)
    jobs=OperationJobManager(ws.root)
    try:
        job=jobs.start('process_analysis',{'target':'trial.sweep_it','timeout':60},{})
        deadline=time.monotonic()+5
        while not job.get('progress') and time.monotonic()<deadline:
            time.sleep(.02)
            job=jobs.status(job['job_id'])
        assert job['progress']['total']==10000
        assert 0<=job['progress']['completed']<10000
        cancelled=jobs.cancel(job['job_id'])
        assert cancelled['state']=='cancelled' and not cancelled['cancellable']
    finally:
        jobs.close()
