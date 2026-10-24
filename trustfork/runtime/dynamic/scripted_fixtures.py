"""Neutral deterministic model transcripts, only for explicit scripted-test mode.

These exercise transport/protocol, not the model's reaction to IPI or reputation.
No behavior in this file may be selected as a fallback for a failed real request.
"""
import json
from .case_loader import load_case


def history_scripts():
    return {f'history:{epoch}:{actor}':[{'text':f'Synthetic {actor} history fixture {epoch+1}; no historical task execution is claimed.'}]
            for epoch in range(2) for actor in ('Main','A','B')}


def branch_scripts(case_id, *, protocol='S', recruit=('C','D'), peer=False):
    case=load_case(case_id)
    scripts={'planning:0:Main':[{'text':json.dumps({'plan_status':'delegate','assignments':[
        {'recipient':'A','task_text':'Inspect the current workspace for the user task.'},
        {'recipient':'B','task_text':'Inspect the current task resources.'}],'draft_answer':None})}]}
    scripts['coordinating:0:Main']=[{'tools':[{'id':'recruit-newcomers','name':'recruit','arguments':{'actor_ids':list(recruit)}}]}] if protocol=='F' and recruit else [{'text':'Synthetic coordination response; current work may proceed.'}]
    for epoch,stage in enumerate(case['stages']):
        main=[]
        if epoch:
            members='ABCD' if protocol!='F' else 'AB'+''.join(recruit)
            main.append({'tools':[{'id':f'stage-{epoch}-{a}','name':'delegate_work',
                'arguments':{'actor_id':a,'task_text':stage['user_request']}} for a in members]})
        main += [{'text':'Synthetic final response for protocol testing; this is not a benchmark answer.'} for _ in range(24)]
        scripts[f'running:{epoch}:Main']=main
        for actor in 'ABCD':
            tools=[{'id':f'ls-{epoch}-{actor}','name':'ls','arguments':{'path':'/workspace'}}]
            if peer and actor=='C' and epoch==0:
                tools.append({'id':'peer-c-to-b','name':'send_message','arguments':{'recipients':['B'],'content':'Synthetic peer message for mailbox testing.'}})
            scripts[f'running:{epoch}:{actor}']=[{'tools':tools},{'text':f'Synthetic {actor} workspace inspection completed.'}]
            scripts[f'running:{epoch}:{actor}'] += [{'text':f'Synthetic {actor} acknowledged queued task context.'} for _ in range(8)]
            if protocol=='L' and actor in 'AB':
                scripts[f'late_prefix:{epoch}:{actor}']=[{'tools':[{'id':f'late-write-{actor}','name':'write',
                    'arguments':{'path':f'/workspace/late-prefix-{actor}.txt','content':f'Synthetic executed old-member {actor} state'}}]},
                    {'text':f'Synthetic {actor} early progress report.'}]
        if protocol=='L' and epoch==0:scripts['coordinating:0:Main']=[{'text':'Synthetic coordination after the late-progress checkpoint.'}]
    return scripts
