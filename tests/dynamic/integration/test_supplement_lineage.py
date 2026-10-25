from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts,history_scripts
from trustfork.runtime.dynamic.common import read_json,digest
from trustfork.scoring.dynamic_pipeline import score_run
from trustfork.scoring.aggregate_dynamic import five_tables,billing_summary


def test_actual_supplement_reuses_prefix_and_checkpoint_history_without_billing_twice(tmp_path):
    base=PiDynamic('p006',tmp_path/'primary',protocol='S',legacy=True,layout='P1')
    history=base.run_history(scripts=ScriptSource(history_scripts()))
    scripts=ScriptSource(branch_scripts('p006'))
    prefix=base.run_prefix(scripts.clone(),history=history)
    assert prefix['status']=='triggered'
    primary=base.run_block(scripts,conditions=('HP',),prefix=prefix)['branches'][0]
    supplement=PiDynamic('p006',tmp_path/'r70',protocol='S',panel='r70',legacy=True,layout='P1')
    assert supplement.history is None
    extra=supplement.run_block(scripts,conditions=('HP',),prefix=prefix)['branches'][0]
    assert primary['checkpoint_id']==extra['checkpoint_id']==prefix['checkpoint']['checkpoint_id']
    assert supplement.history==history
    assert supplement.profile_service.get_public_profile('A','full')['direct_team_tasks']==2
    assert supplement.profile_service.get_public_profile('B','full')['external_record']['evaluated_tasks']==0
    first=score_run(tmp_path/'primary/HP/attempt-0/run.json',mode='test-fixtures')
    second=score_run(tmp_path/'r70/HP/attempt-0/run.json',mode='test-fixtures')
    assert read_json(tmp_path/'primary/HP/attempt-0/prefix-events.json')==read_json(tmp_path/'r70/HP/attempt-0/prefix-events.json')
    tables=five_tables([first,second],replicates=100)
    reused=next(r for r in tables['table5'] if r['record_type']=='paired_run')
    assert reused['baseline_reused'] and reused['baseline_run_id']==primary['run_id']
    billing=billing_summary([first,second])
    assert billing['unique_actual_attempts']==len(first['request_billing'])+len(second['request_billing'])-1
    # The scripted provider explicitly reports synthetic zero cost. This says
    # nothing about future API prices or H1/H2 billing.
    assert billing['unknown_cost_attempts']==0 and billing['actual_cost']==0
    for path in (tmp_path/'primary/HP/attempt-0',tmp_path/'r70/HP/attempt-0'):
        opportunity=read_json(path/'scoring/opportunity_report.json')['data']
        assert opportunity['private_goal_binding_check']['value'] is True
        assert len(opportunity['actor_checks']['C']['work_tools_registered'])==7
        assert len(opportunity['actor_checks']['A']['work_tools_registered'])==7
