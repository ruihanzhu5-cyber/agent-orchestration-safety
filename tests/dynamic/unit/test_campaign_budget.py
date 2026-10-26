import multiprocessing
import pytest
from trustfork.runtime.dynamic.campaign_budget import CampaignBudget,price_cny
from trustfork.runtime.dynamic.common import DynamicError

def ledger(path):return CampaignBudget(path,campaign_id='first-api-20261026')
def reserve_worker(path,index,queue):
 try:
  row=ledger(path).reserve('p'+str(index),phase='engineering_smoke',reserved_cost_cny=60,metadata={'kind':'model'})
  queue.put(row['status'])
 except DynamicError as error:queue.put(error.code)

def test_two_processes_cannot_exceed_total_and_restart_does_not_reset(tmp_path):
 path=tmp_path/'budget.sqlite';ledger(path)
 ctx=multiprocessing.get_context('spawn');q=ctx.Queue()
 ps=[ctx.Process(target=reserve_worker,args=(path,i,q)) for i in range(2)]
 for p in ps:p.start()
 for p in ps:p.join(30);assert p.exitcode==0
 assert sorted(q.get(timeout=2) for _ in ps)==['campaign_cost_exhausted','reserved']
 assert ledger(path).summary()['remaining_cny']==40

def test_interface_subtotal_in_total_and_settlement_releases_unused(tmp_path):
 b=ledger(tmp_path/'b')
 b.reserve('a',phase='interface_probe',reserved_cost_cny=19,metadata={})
 with pytest.raises(DynamicError,match='campaign_phase_cost_exhausted'):b.reserve('b',phase='interface_probe',reserved_cost_cny=2,metadata={})
 b.submitted('a');b.settle('a',settled_cost_cny=2,usage={'completion_tokens':1,'completion_tokens_details':{'reasoning_tokens':1}})
 b.settle('a',settled_cost_cny=2,usage={'completion_tokens':1,'completion_tokens_details':{'reasoning_tokens':1}})
 b.reserve('b',phase='interface_probe',reserved_cost_cny=18,metadata={})
 b.reserve('c',phase='engineering_smoke',reserved_cost_cny=80,metadata={})
 assert b.summary()['remaining_cny']==0 and b.summary()['settled_cny']==2

def test_unknown_charge_stays_reserved_and_no_cancel_after_send(tmp_path):
 b=ledger(tmp_path/'b');b.reserve('a',phase='interface_probe',reserved_cost_cny=5,metadata={});b.submitted('a')
 b.settle('a',usage=None)
 assert b.summary()['unsettled_reserved_cny']==5
 with pytest.raises(DynamicError,match='campaign_cancel_after_send'):b.settle('a',cancelled_before_send=True)
 b.settle('a',settled_cost_cny=1,usage={'prompt_tokens':1})
 assert b.summary()['remaining_cny']==99

def test_reserve_identity_cancel_and_immutable_policy(tmp_path):
 path=tmp_path/'b';b=ledger(path)
 b.reserve('a',phase='interface_probe',reserved_cost_cny=1,metadata={'purpose':'judge_repair'})
 b.reserve('a',phase='interface_probe',reserved_cost_cny=1,metadata={'purpose':'judge_repair'})
 assert len(b.rows())==1
 with pytest.raises(DynamicError,match='campaign_request_identity_mismatch'):b.reserve('a',phase='interface_probe',reserved_cost_cny=2,metadata={})
 b.settle('a',cancelled_before_send=True);assert b.summary()['remaining_cny']==100
 with pytest.raises(DynamicError,match='campaign_policy_mismatch'):CampaignBudget(path,campaign_id='new-id')

def test_rate_wait_idempotent_and_oversize_fails_instead_of_waiting(tmp_path):
 b=ledger(tmp_path/'b')
 assert b.rate_wait('a',route='route',tokens=20,rpm=1,tpm=30,now=100)==0
 assert b.rate_wait('a',route='route',tokens=20,rpm=1,tpm=30,now=101)==0
 assert b.rate_wait('b',route='route',tokens=10,rpm=1,tpm=30,now=101)==59
 assert b.rate_wait('b',route='route',tokens=10,rpm=1,tpm=30,now=161)==0
 with pytest.raises(DynamicError,match='request_exceeds_tpm'):b.rate_wait('c',route='route',tokens=31,rpm=1,tpm=30)
 b.pause('route','estimate shortfall')
 with pytest.raises(DynamicError,match='provider_route_paused'):b.rate_wait('d',route='route',tokens=1,rpm=1,tpm=30)

def test_money_units_and_reasoning_is_not_double_billed():
 # completion_tokens already includes reasoning. Caller passes it exactly once.
 assert float(price_cny(1_000_000,1_000_000,{'input':.3,'output':1.2},8))==12
 with pytest.raises(DynamicError,match='provider_price_unknown'):price_cny(1,1,{'input':0,'output':0},8)

def test_declared_estimate_includes_private_reasoning_and_remains_unverified():
 from test_provider_preparation import configuration
 from trustfork.runtime.dynamic.token_accounting import count_request,engineering_counting_policy
 b=configuration()['logical_bindings']['gpt4o'];b['capability']['status']='declared'
 p=engineering_counting_policy(b)
 with_reason=count_request({'messages':[{'role':'assistant','content':'visible','reasoning_content':'私有推理'}]},p)
 without=count_request({'messages':[{'role':'assistant','content':'visible'}]},p)
 assert with_reason['input_tokens']-without['input_tokens']==len('私有推理'.encode())
 assert with_reason['policy_status']=='estimated' and b['capability']['status']=='declared'

def configured_campaign(path):
 from test_provider_preparation import configuration
 c=configuration();c['execution_scope']='engineering_smoke'
 for b in c['logical_bindings'].values():b['capability']['status']='declared'
 c['execution_limits']={kind:{'max_cost_usd':10,'requests_per_minute':100,'tokens_per_minute':1000000,
  'prices_per_million':{'exact-fixture':{'input':1,'output':2}}} for kind in ('model','judge')}
 c['campaign_budget']={'path':str(path),'campaign_id':'first-api-20261026','phase':'interface_probe',
  'pricing_basis':'synthetic mock fixture','conversion_basis':'synthetic rate','usd_to_cny_upper_bound':8,
  'account_price_upper_bound_confirmed':True}
 return c

def test_two_mock_transports_and_judge_settle_same_ledger(tmp_path):
 import json
 from trustfork.runtime.dynamic.provider import ProviderTransport
 c=configured_campaign(tmp_path/'money.sqlite');calls=[]
 def http(*args):
  calls.append(args)
  return {'status':200,'headers':{'content-type':'application/json'},
   'body':json.dumps({'usage':{'prompt_tokens':10,'completion_tokens':5,'completion_tokens_details':{'reasoning_tokens':3}}})}
 wire={'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':'exact-fixture','messages':[],'max_tokens':100})}
 for i,kind in enumerate(('model','judge','model')):
  t=ProviderTransport(c,mode='mock',journal=tmp_path/(str(i)+'.jsonl'),http=http,max_requests=2,kind=kind)
  t.request('gpt4o',wire,request_id='r'+str(i),context={'purpose':'history' if i==2 else kind})
 b=ledger(tmp_path/'money.sqlite')
 assert len(calls)==3 and len(b.rows())==3 and b.summary()['unsettled_reserved_cny']==0
 assert b.summary()['settled_cny']==pytest.approx(3*.00016)
 assert all(r['status']=='settled' for r in b.rows())

def test_capacity_and_tpm_reject_before_mock_http_and_no_money_charged(tmp_path):
 import json
 from trustfork.runtime.dynamic.provider import ProviderTransport
 c=configured_campaign(tmp_path/'b');c['logical_bindings']['gpt4o']['capability']['effective_context_tokens']=100
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'log',http=lambda *a:pytest.fail('must not send'),max_requests=2)
 wire={'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':'exact-fixture','messages':[],'max_tokens':10})}
 with pytest.raises(DynamicError,match='provider_capacity_blocked'):t.request('gpt4o',wire,request_id='r')
 assert t.count==0 and not t.journal.exists() and t.campaign.summary()['remaining_cny']==100
 c['logical_bindings']['gpt4o']['capability']['effective_context_tokens']=128000
 c['execution_limits']['model']['tokens_per_minute']=1
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'log2',http=lambda *a:pytest.fail('must not send'),max_requests=2)
 with pytest.raises(DynamicError,match='request_exceeds_tpm'):t.request('gpt4o',wire,request_id='r2')
 assert t.campaign.summary()['remaining_cny']==100 and t.count==0

def test_queue_wait_does_not_duplicate_or_send_until_slot(tmp_path,monkeypatch):
 import json
 from trustfork.runtime.dynamic.provider import ProviderTransport
 c=configured_campaign(tmp_path/'b');calls=[];sleeps=[]
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'log',http=lambda *a:(calls.append(a) or {'status':200,'headers':{},'body':'{}'}),max_requests=1)
 waits=iter([2,0]);monkeypatch.setattr(t.campaign,'rate_wait',lambda *a,**k:next(waits))
 monkeypatch.setattr('trustfork.runtime.dynamic.provider.time.sleep',lambda n:sleeps.append(n))
 wire={'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':'exact-fixture','messages':[],'max_tokens':10})}
 t.request('gpt4o',wire,request_id='r')
 assert len(calls)==1 and len(sleeps)==1 and t.count==1 and len(t.campaign.rows())==1
 assert t.campaign.rows()[0]['status']=='charge_unknown'

def test_per_route_credit_and_cny_conversion_override_global_legacy_factor(tmp_path):
 import copy,json
 from trustfork.runtime.dynamic.provider import ProviderTransport
 from trustfork.runtime.dynamic.common import digest
 c=configured_campaign(tmp_path/'mixed')
 deep=c['logical_bindings']['deepseekflash'];deep['model_id']='deep-fixture'
 route=digest({k:deep[k] for k in ('provider','base_url','model_id')})
 deep['capability']['route_fingerprint']=route;deep['capability']['tokenizer']['applicable_route']=route
 prices={'exact-fixture':{'input':2.5,'output':10,'unit_to_cny_upper_bound':3.5,'source_currency':'site-credit','conversion_basis':'confirmed group1, CNY3.5/credit'},
 'deep-fixture':{'input':2,'output':8,'unit_to_cny_upper_bound':1,'source_currency':'CNY','conversion_basis':'CNY funded official account'}}
 for limits in c['execution_limits'].values():limits['prices_per_million']=copy.deepcopy(prices)
 t=ProviderTransport(c,mode='mock',journal=tmp_path/'requests.jsonl',http=lambda *a:{'status':200,'headers':{},'body':json.dumps({'usage':{'prompt_tokens':10,'completion_tokens':5}})},max_requests=2)
 for alias,model in [('gpt4o','exact-fixture'),('deepseekflash','deep-fixture')]:
  t.request(alias,{'url':'https://mock.invalid/v1/chat/completions','method':'POST','body':json.dumps({'model':model,'messages':[],'max_tokens':100})},request_id=alias)
 rows={r['request_id']:r for r in t.campaign.rows()}
 assert rows['gpt4o']['settled']==263 and rows['deepseekflash']['settled']==60
 assert rows['gpt4o']['metadata']['source_currency']=='site-credit' and rows['deepseekflash']['metadata']['usd_to_cny_upper_bound']==1
 assert t.campaign.summary()['settled_cny']==pytest.approx(.000323)
