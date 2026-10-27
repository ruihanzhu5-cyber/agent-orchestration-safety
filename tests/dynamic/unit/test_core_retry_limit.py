import json,pytest
from trustfork.runtime.dynamic.common import DynamicError
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.judge_client import JudgeClient
from trustfork.scoring.judge_request import prepare_judge_request
from test_provider_preparation import configuration
from test_first_api_judge import reply

@pytest.mark.parametrize('order',['length_then_json','json_then_length'])
def test_single_retry_never_turns_into_calibration_plus_repair(tmp_path,order):
 c=configuration();length=reply('');v=json.loads(length['body']);v['choices'][0]['finish_reason']='length';length['body']=json.dumps(v)
 bad=reply('not-json');replies=[length,bad] if order=='length_then_json' else [bad,length]
 seen=[]
 def http(*args):seen.append(1);return replies[len(seen)-1]
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'requests.jsonl',kind='judge',http=http,max_requests=3)
 p=prepare_judge_request({},rubric='rubric',format_instructions='JSON',output_budget=100,counter=len,judge_binding=c['logical_bindings']['gpt4o']);p['scorer_config']={'length_calibration_output_tokens':200,'max_total_attempts':2}
 with pytest.raises(DynamicError):JudgeClient(t).send_with_repair(p,request_id='bounded',pass_name='trajectory')
 assert t.count==len(seen)==2
 assert not ((tmp_path/'judge-capacity-calibrations.jsonl').exists() and (tmp_path/'judge-structure-repairs.jsonl').exists())
