"""Explicitly synthetic evidence, never model behavior or task outcomes."""
import json
import pytest
from trustfork.runtime.dynamic.events import EventLedger
from trustfork.runtime.dynamic.common import digest


@pytest.fixture
def known_trajectory(tmp_path):
    ledger=EventLedger(tmp_path/'known-synthetic-events','fixture-branch','p001')
    def add(kind,payload,actor=None,**refs):
        return ledger.append(kind,payload,actor_id=actor,stage_id='ask',**refs)
    source=add('message_enqueued',{'message_id':'m','sender':'C','recipients':['A'],
        'content':'Synthetic harmful instruction.','content_hash':digest('Synthetic harmful instruction.'),
        'delivery':{'A':{'status':'queued','request_id':None,'attempts':[]}}},'C',message_id='m')
    packet={'public_task':{'user_request':'Synthetic task'},'peer_messages':[{'message_id':'m','sender':'C',
        'content':source['payload']['content'],'content_hash':source['payload']['content_hash']}]}
    submitted=add('model_request_submitted',{'actual_input':{'systemPrompt':'Public role','messages':[
        {'role':'user','content':json.dumps(packet)}],'tools':[]},'synthetic':True},'A',request_id='A-actual')
    start=add('tool_operation_started',{'operation':'fs.write','args':{'path':'/workspace/fixture-object'}},
        'A',request_id='A-actual',tool_call_id='op')
    end=add('tool_operation_finished',{'result':{'written':1},'observation_interval':[1,2],
        'overlapping_operation_ids':[]},'A',request_id='A-actual',tool_call_id='op')
    state=add('goal_state_observation',{'consistent_observation':True,'paths':{
        '/workspace/fixture-object':{'exists':True,'sha256':'synthetic-observed-state'}}},'A',request_id='A-actual')
    add('model_response',{'status':'success','response':{'provider':'scripted'},'synthetic':True},'A',request_id='A-actual')
    exposed=add('message_exposed',{'recipient':'A'},'A',message_id='m',request_id='A-actual')
    ref=lambda event:event['branch_id']+'::'+event['event_id']
    return {'events':ledger.rows,'source':source,'submitted':submitted,'start':start,'end':end,
        'state':state,'exposed':exposed,'refs':{ref(e) for e in ledger.rows},'ref':ref,'synthetic':True}
