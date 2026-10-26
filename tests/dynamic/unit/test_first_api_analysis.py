import json
from trustfork.runtime.dynamic.first_api_analysis import analyze_campaign,generation
def test_stream_finish_usage_and_missing_are_distinct():
 f,u=generation({'headers':{'content-type':'text/event-stream'},'body':'data: {"choices":[{"finish_reason":"length"}],"usage":{"completion_tokens":10}}\n\ndata: [DONE]\n'})
 assert f=='length' and u['completion_tokens']==10
 assert generation({'body':'partial {'})==(None,None)
 assert generation({'body':'[]'})==(None,None)
def test_analysis_deduplicates_response_receipts_and_counts_only_submitted(tmp_path):
 def put(name,rows):
  p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
 sent={'transport_id':'t','request_id':'r','attempt_number':1,'kind':'model','source':'api','synthetic':False,'status':'submitted','model_id':'fixture','request_context':{'actor_id':'A'},'token_accounting':{'estimated_total_input_tokens':100}}
 reply={**sent,'status':'response','response':{'headers':{},'body':json.dumps({'choices':[{'finish_reason':'length'}],'usage':{'prompt_tokens':50,'completion_tokens':10,'completion_tokens_details':{'reasoning_tokens':6}}})}}
 put('probes/provider-requests.jsonl',[sent,{**reply,'status':'response_received'},reply])
 put('probes/capacity-checks.jsonl',[{'transport_id':'t','request_id':'r','status':'capacity_check_started'},{'transport_id':'t','request_id':'blocked','status':'capacity_check_started'},{'transport_id':'t','request_id':'blocked','status':'preflight_blocked','code':'provider_capacity_blocked'}])
 result=analyze_campaign(tmp_path)
 assert result['actual_call_audit']['real_model_requests']==1 and result['actual_call_audit']['real_judge_requests']==0
 assert result['truncation_rate']=={'numerator':1,'denominator':1,'unknown_finish_requests':0}
 assert result['capacity_refusal_rate']['numerator']==1 and result['capacity_refusal_rate']['denominator']==2
 assert result['per_actor']['fixture|A']['completion_tokens_reported']==10
 assert result['per_actor']['fixture|A']['reasoning_tokens_reported']==6
 assert result['budget'] is None and not (tmp_path/'campaign-budget.sqlite3').exists()
