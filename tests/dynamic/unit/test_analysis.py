import copy
import json
from collections import Counter
from pathlib import Path
import pytest
from trustfork.scoring.aggregate_dynamic import paired_effects,card_resamples,quantile,five_tables,select_attempts,write_tables,billing_summary,join_plan
from trustfork.scoring.dynamic_adapter import METRICS
from trustfork.scoring.dynamic_metrics import SEMANTIC
from trustfork.runtime.dynamic.common import DynamicError,read_json,config_dir
from trustfork.tools.generate_dynamic_manifest import generate_plan,auxiliary_plans,MECHANISM_LAYOUTS,MAINS


@pytest.fixture(scope='module')
def plan():return generate_plan()


def test_full_frozen_matrix_counts_profiles_pairs_and_real_checkpoint_absence(plan):
    assert len(plan)==1664 and len({r['plan_run_id'] for r in plan})==1664
    blocks=Counter(r['block_id'] for r in plan)
    assert len(blocks)==440 and Counter(blocks.values())=={4:392,2:48}
    assert Counter(r['panel'] for r in plan)=={'primary':1248,'80_60':128,'no_history':64,'r70':32,'self_on_request':32,'reminder':32,'strategy':32,'repeat':64,'late_join':32}
    assert sum(r['protocol']=='S' and r['panel']=='primary' for r in plan)==832
    assert sum(r['protocol']=='F' and r['panel']=='primary' for r in plan)==416
    assert all(r['run_id'] is None and r['checkpoint_id'] is None and not r['formal_ready'] and r['scorer_hash'] for r in plan)
    groups={}
    for row in plan:groups.setdefault(row['block_id'],{})[row['condition']]=row
    for group in groups.values():
        if 'HP' in group and 'HA' in group:
            assert group['HP']['profile_hash']==group['HA']['profile_hash']
            assert group['HP']['goal_hash']!=group['HA']['goal_hash']
        if 'MP' in group and 'MA' in group:assert group['MP']['profile_hash']==group['MA']['profile_hash']
        assert sorted(r['run_order'] for r in group.values())==list(range(len(group)))
    aux=auxiliary_plans();assert len(aux['histories'])==16 and len(aux['smoke'])==32
    assert sum(r['mechanism_sample'] for r in plan)==144
    frozen=read_json(config_dir()/'mechanism_layouts.json')['layouts']
    assert {case:tuple(value[m] for m in MAINS) for case,value in frozen.items()}==MECHANISM_LAYOUTS
    assert len({r['baseline_plan_ref'] for r in plan if r['panel'] in ('r70','self_on_request','reminder','strategy','repeat','late_join')})==32


def row(case,layout,condition,value,*,main='gpt4o',split='confirmation',protocol='S',panel='primary'):
    binary={'value':False,'status':'complete'}
    return {'run_id':f'{case}-{main}-{layout}-{protocol}-{panel}-{condition}','block_id':f'{case}|{main}|{layout}|{protocol}|{panel}',
        'case_id':case,'layout':layout,'condition':condition,'main_model':main,'split':split,'protocol':protocol,'panel':panel,
        'suite':'indirect','repeat_id':0,'strategy':None,'comparison_set_id':panel,'branch_attempt':0,'synthetic':True,'run_status':'valid_behavior',
        'scores':{m:{'metric':m,'value':value,'status':'complete','reason':None} for m in METRICS},
        'goal_observations':{key:copy.deepcopy(binary) for key in ('goal_observed_achieved','goal_terminal_achieved','postjoin_new_effect_observed','prejoin_goal_state')},
        'automatic_metrics':{'J':True,'U':True,'U_voluntary':False,'E':False,'substantive_participation':True,'peer_participation':False,
            'first_extra_handoff_characters':0,'delivery_coverage':{'queued_unique':0,'exposed_unique':0},
            'cumulative_exposure_to_q':{kind:{'raw_characters':0,'exact_hash_unique_characters':0,'raw_occurrences':0,'exact_unique_texts':0} for kind in ('Main','peer','tool')}},
        'semantic_metrics':{metric:{'value':None,'status':'not_annotated','evidence_refs':[]} for metric in SEMANTIC},'mechanism_sample':True}


def sample_rows(main='gpt4o'):
    rows=[]
    for case,layout,values in [('p001','P1',[30,60,10,20]),('p001','P2',[30,60,10,20]),('p004','P1',[0,100,0,0])]:
        rows.extend(row(case,layout,condition,value,main=main) for condition,value in zip(('HP','HA','MP','MA'),values))
    return rows


def test_tables_one_two_use_same_complete_card_equal_estimand_as_table_four():
    s=sample_rows();f=copy.deepcopy(s)
    for r in f:r.update(protocol='F',run_id=r['run_id']+'F',block_id=r['block_id']+'F')
    tables=five_tables(s+f,replicates=100)
    for name in ('table1','table2'):
        hp=next(r for r in tables[name] if r['condition']=='HP')
        assert hp['scores']['IAS']['value']==15
        assert hp['all_available_descriptive']['scores']['IAS']['value']==20
        assert hp['scores']['IAS']['eligible_complete_blocks']==3
        t4=next(r for r in tables['table4'] if r['metric']=='IAS' and r['suite']=='ALL' and r['protocol']==('S' if name=='table1' else 'F'))
        assert hp['scores']['IAS']['value']==t4['estimates']['HP']['value']


def test_primary_score_eligibility_is_metric_specific_and_does_not_filter_f_behavior():
    f=sample_rows()
    for r in f:r['protocol']='F';r['automatic_metrics'].update(J=False,U=False,U_voluntary=False)
    f[-1]['scores']['IAS'].update(value=None,status='judge_error',reason='capacity_unknown')
    table=five_tables(f,replicates=100)['table2'];hp=next(r for r in table if r['condition']=='HP')
    assert hp['scores']['IAS']['value']==30 and hp['scores']['SAF']['value']==15
    assert hp['scores']['IAS']['eligible_complete_blocks']==2
    assert hp['automatic']['J']['N_valid']==3 and hp['not_recruited']['point_estimate']==1


def test_equal_card_layout_weighting_and_exact_confirmation_endpoints():
    rows=sample_rows();result=paired_effects(rows,'IAS')
    assert result['estimates']['interaction']['value']==60  # (20+100)/2, not (20+20+100)/3
    assert result['complete_blocks']==3 and result['complete_cards']==2
    assert result['estimates']['interaction']['ci95']==[20,100]
    assert result['family8_endpoints']==[.003125,.996875]
    assert result['estimates']['interaction']['ci99_375_family8']==[20,100]
    assert result['bootstrap_replicates']==10000 and result['bootstrap_seed']==20261024
    assert card_resamples(('p001','p004')) is card_resamples(('p001','p004'))
    other=paired_effects(sample_rows('deepseekflash'),'IAS')
    assert other['estimates']==result['estimates']
    assert quantile([0,10,20,30],.25)==7.5


def test_incomplete_pair_status_sensitivity_and_protocol_repeat_separation():
    rows=sample_rows();rows[-3]['scores']['IAS'].update(value=None,status='unknown')
    result=paired_effects(rows,'IAS',replicates=100)
    assert result['complete_blocks']==2 and result['complete_cards']==1 and len(result['missing_blocks'])==1
    assert result['missing_sensitivity_interaction']==[10,60]
    repeated=copy.deepcopy(rows);repeated[0]['repeat_id']=1
    with pytest.raises(DynamicError,match='repeat_in_primary'):paired_effects(repeated,'IAS')
    f=[{**r,'protocol':'F'} for r in sample_rows()]
    assert not paired_effects(f,'IAS',replicates=100)['family8_applies']
    l=[{**r,'protocol':'L'} for r in sample_rows()]
    assert not paired_effects(l,'IAS',replicates=100)['family8_applies']


def test_five_tables_baseline_reuse_no_recruit_and_fixture_watermark(tmp_path):
    primary=sample_rows();f=[{**r,'protocol':'F','block_id':r['block_id']+'F','run_id':r['run_id']+'F'} for r in sample_rows()]
    f=copy.deepcopy(f)
    for r in f:r['automatic_metrics'].update(J=False,U=False,substantive_participation=False)
    supplement=copy.deepcopy(primary[1]);supplement.update(panel='r70',comparison_set_id='r70',run_id='supplement',block_id='supplement-block')
    tables=five_tables(primary+f+[supplement],replicates=100)
    assert all(name in tables for name in ('table1','table2','table3','table4','table5'))
    assert all(r['not_recruited']['point_estimate']==1 for r in tables['table2'])
    assert tables['table5'][0]['baseline_run_id']==primary[1]['run_id'] and tables['table5'][0]['baseline_reused']
    assert tables['table5'][0]['differences_from_primary_baseline']['IAS']['value']==0
    semantic=tables['table3'][0]['U_all'];assert semantic['N_not_annotated'] and semantic['point_estimate'] is None
    write_tables(tables,tmp_path,metadata={'synthetic':True,'purpose':'numeric fixture only'})
    assert len(list(tmp_path.glob('table*.json')))==len(list(tmp_path.glob('table*.csv')))==5
    assert read_json(tmp_path/'table1.json')['metadata']['synthetic']
    assert (tmp_path/'table1.csv').read_text().startswith('synthetic,')


def test_first_valid_attempt_not_best_value_and_duplicate_attempt_rejected():
    first=row('p001','P1','HP',80);failed={**first,'run_id':'failed','run_status':'infra_error'}
    valid={**first,'run_id':'valid','branch_attempt':1}
    selected,all_attempts=select_attempts([failed,valid]);assert selected[0]['run_id']=='valid' and len(all_attempts)==2
    with pytest.raises(DynamicError,match='duplicate_run_attempt'):select_attempts([first,copy.deepcopy(first)])


def test_completely_missing_planned_block_and_shared_prefix_billing():
    existing=[r for r in sample_rows() if r['case_id']=='p001']
    result=paired_effects(existing,'IAS',planned_blocks=[('p001','P1'),('p001','P2'),('p004','P1')],universe=['p001','p004'],replicates=100)
    assert result['planned_observed_blocks']==3 and len(result['missing_blocks'])==1
    assert result['missing_sensitivity_interaction']==[-90,110]
    physical={'attempt_key':'prefix::attempt','cost':10,'lineage_status':'resolved'}
    rows=[{'run_id':'a','request_billing':[physical,{'attempt_key':'a::own','cost':2}]},
          {'run_id':'b','request_billing':[physical,{'attempt_key':'b::own','cost':3}]}]
    bills=billing_summary(rows)
    assert bills['actual_cost']==15 and bills['branch_equivalent_known_cost_sum']==25
    missing=billing_summary(rows+[{'run_id':'infra'}]);assert missing['actual_cost'] is None


def test_synthetic_formal_scoring_rejected_before_any_judge(tmp_path,monkeypatch):
    from trustfork.scoring.dynamic_pipeline import score_run
    from trustfork.scoring import verifier
    monkeypatch.setattr(verifier,'call_judge',lambda *a,**k:pytest.fail('Unexpected judge API'))
    file=tmp_path/'run.json';file.write_text(json.dumps({'synthetic':True}))
    with pytest.raises(DynamicError,match='synthetic_formal_rejected'):score_run(file,mode='formal')
