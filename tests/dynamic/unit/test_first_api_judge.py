import json
from collections import deque
import pytest
from test_provider_preparation import configuration
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.judge_request import prepare_judge_request
from trustfork.runtime.dynamic.common import DynamicError

def prepared(c):
 return prepare_judge_request({'frozen':'same evidence'},rubric='rubric',format_instructions='JSON',output_budget=100,counter=len,judge_binding=c['logical_bindings']['gpt4o'])
def reply(text,finish='stop',reasoning=''):
 return {'status':200,'headers':{'content-type':'application/json'},'body':json.dumps({'choices':[{'finish_reason':finish,'message':{'content':text,'reasoning_content':reasoning}}]})}
def unknown_result():
 return {'trajectory_judgements':{k:{'value':None,'status':'unknown','evidence_refs':[]} for k in ('ias','saf','vf','ei','terminal_safety','task_utility')}}

def test_one_structural_repair_retains_first_failure_and_frozen_evidence(tmp_path):
 c=configuration();p=prepared(c);responses=deque([reply('{'),reply(json.dumps(unknown_result()))]);sent=[]
 def http(url,body,*args):sent.append(json.loads(body));return responses.popleft()
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'judge.jsonl',http=http,max_requests=4,kind='judge')
 result=JudgeClient(t).send_with_repair(p,request_id='j',pass_name='trajectory',evidence_refs=[])
 assert t.count==2 and result['structure_attempts']==2 and result['original_request_hash']==p['request_hash']
 assert sent[0]['messages']==p['wire_payload']['messages'] and sent[1]['messages'][:2]==sent[0]['messages']
 assert all(r['value'] is None for r in result['result']['trajectory_judgements'].values())
 records=[json.loads(x) for x in (tmp_path/'judge-structure-repairs.jsonl').read_text().splitlines()]
 assert len(records)==1 and records[0]['frozen_representation_hash']==p['representation_hash']

@pytest.mark.parametrize('reason',['length','empty_reasoning_only','invented_evidence'])
def test_judge_has_at_most_two_attempts_and_no_reasoning_as_score(tmp_path,reason):
 c=configuration();p=prepared(c)
 if reason=='length':r=reply('{}','length')
 elif reason=='empty_reasoning_only':r=reply('',reasoning=json.dumps(unknown_result()))
 else:
  bad=unknown_result();bad['trajectory_judgements']['ias']={'value':0,'status':'complete','evidence_refs':['invented']}
  r=reply(json.dumps(bad))
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'judge.jsonl',http=lambda *a:r,max_requests=5,kind='judge')
 with pytest.raises(DynamicError):JudgeClient(t).send_with_repair(p,request_id='j',pass_name='trajectory',evidence_refs=[])
 assert t.count==(1 if reason=='length' else 2)

def test_thinking_judge_repair_replays_private_reasoning_and_counts_it(tmp_path):
 c=configuration();c['judge_binding']='deepseekflash'
 b=c['logical_bindings']['deepseekflash'];b.update(thinking='enabled',reasoning_effort='high')
 b['supported_parameters']+=['thinking','reasoning_effort']
 from trustfork.scoring.judge_request import prepare_judge_pass
 bundle={'views':{'trajectory':{'frozen':'same evidence'}},'prompts':{'trajectory':'rubric'},'formats':{'trajectory':'JSON'},'builder_version':'fixture','scoring_profile':'legacy-eight-v1','sanitizer':{},'response_ids':[]}
 p=prepare_judge_pass(bundle,'trajectory',binding=b,scorer_config={'trajectory_representation':'legacy-full','trajectory_output_budget_tokens':100,'temperature':.2},counter=len)
 sent=[];replies=deque([reply('{',reasoning='PRIVATE_JUDGE_REASONING'),reply(json.dumps(unknown_result()),reasoning='REPAIRED')])
 def http(url,body,*args):sent.append(json.loads(body));return replies.popleft()
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'judge.jsonl',http=http,max_requests=2,kind='judge')
 result=JudgeClient(t).send_with_repair(p,request_id='deep-j',pass_name='trajectory',evidence_refs=[])
 assert result['structure_attempts']==2
 assert sent[1]['messages'][-2]['reasoning_content']=='PRIVATE_JUDGE_REASONING'
 assert 'temperature' not in sent[1] and sent[1]['reasoning_effort']=='high'
 assert sent[1]['messages'][:2]==sent[0]['messages']
