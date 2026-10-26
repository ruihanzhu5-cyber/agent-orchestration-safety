"""Normal-goal H1/H2 through the same PiDynamic stages, Docker and scheduler."""
from __future__ import annotations
import copy
import time
import uuid
import shutil
from pathlib import Path
from .common import DynamicError,digest,write_json
from .goals import LAYOUTS,NORMAL_GOAL,system_prompt
from .history import History
from .case_loader import load_case
from .initial_plan import parse_initial_plan, planning_contract, planning_identity


def execute_task(runtime,source,previous):
    """Keep failed/refused/budget-ended histories. Never select only successes."""
    from trustfork.agents.pi_dynamic import text_of
    runtime._initialize(runtime.out,'history_'+uuid.uuid4().hex)
    runtime.current_scripts=source;runtime.history=previous
    status='not_started';start=time.monotonic_ns();initial=None;frozen=None;sessions={}
    try:
        runtime.environment.prepare(runtime.case);runtime.resources=runtime._resources()
        runtime.environment.quiesce(time.monotonic()+30);runtime.environment.freeze()
        initial=runtime.environment.export_state()
        initial_directory=runtime.directory/'initial-state';initial_directory.mkdir()
        # export_state uses fixed final archive names. Preserve initial evidence
        # separately before resuming this task; never reuse it as the next task FS.
        def preserve(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('workspace_tar','path') and isinstance(item,str) and Path(item).is_file():
                        dest=initial_directory/Path(item).name;shutil.copyfile(item,dest);value[key]=str(dest)
                    elif isinstance(item,(dict,list)):preserve(item)
            elif isinstance(value,list):
                for item in value:preserve(item)
        preserve(initial);write_json(initial_directory/'state-export.json',initial)
        runtime.environment.compose('unpause');runtime.environment.frozen=False;runtime.environment.accepting=True
        for actor in ('Main','A','B'):
            prior=(previous or {}).get('actor_states',{}).get(actor,[])
            runtime._create_actor(actor,prior[-1]['session'] if prior else None)
        runtime.client.call(runtime.sessions['Main'],'set_coordination_phase',{'phase':'planning'})
        result=runtime._turn('Main','planning')
        while result['response']['stopReason']=='toolUse' and runtime.budget.available():result=runtime._turn('Main','planning')
        if result['response']['stopReason']=='length':
            runtime.termination_reason='output_limit'
            raise DynamicError('history_output_limit','Partial plan retained; no automatic continuation')
        plan=parse_initial_plan(text_of(result['response']),allowed_context_refs=planning_contract()['allowed_context_refs'],
            repair=lambda raw,prompt:text_of(runtime._turn('Main','format_repair',extra_packet={'format_repair':{'original':raw,'instruction':prompt}})['response']))
        for assignment in plan['plan']['assignments']:
            if not any(r['actor_id']==assignment['recipient'] and r['task_text']==assignment['task_text'] and r['status']=='queued' for r in runtime.delegations.rows):
                runtime.delegations.prepare(assignment['recipient'],assignment['task_text'],source='initial_plan',
                    stage_id=runtime.lifecycle.stage_id,context_refs=assignment.get('context_refs',[]))
        runtime.ledger.append('initial_plan',plan,actor_id='Main',stage_id=runtime.lifecycle.stage_id)
        runtime.lifecycle.transition('PLAN_READY');runtime.lifecycle.transition('RUNNING')
        runtime.client.call(runtime.sessions['Main'],'set_coordination_phase',{'phase':'history'})
        runtime._release();runtime.scheduler.enqueue_batch(['Main'],reason='history_initial_coordination')
        for index,stage in enumerate(runtime.case['stages']):
            runtime._run_stage()
            if runtime.termination_reason or index+1==len(runtime.case['stages']) or not runtime.budget.available():break
            following=runtime.case['stages'][index+1]
            runtime.lifecycle.close_stage(runtime.environment,next_stage=following,deadline=runtime.budget.deadline,drain=lambda epoch:None,
                reset=lambda epoch:runtime._stage_reset(epoch,True),migrate=lambda epoch,new:runtime._stage_reset(epoch,False))
            runtime.budget.new_stage();runtime.pending_final=None;runtime.confirming_final=False;runtime.resources=runtime._resources()
            for actor in list(runtime.sessions):
                if following['new_session']:
                    runtime.client.call(runtime.sessions[actor],'close');runtime._create_actor(actor)
                else:runtime.client.call(runtime.sessions[actor],'reload_resources',{'task_resources':runtime.resources,
                    'system_prompt':system_prompt(actor,NORMAL_GOAL,task_resources=[])})
            runtime.client.call(runtime.sessions['Main'],'set_coordination_phase',{'phase':'history'})
            runtime.scheduler.enqueue_batch(['Main'],reason='original_next_stage')
        runtime.termination_reason=runtime.termination_reason or runtime.budget.termination_reason()
        status='budget_ended' if runtime.termination_reason else 'completed_unjudged'
        runtime.lifecycle.propose_final(runtime.main_revision)
        frozen=runtime.lifecycle.finalize(runtime.environment,stage_deadline=runtime.budget.deadline,
            current_revision=lambda:runtime.main_revision,has_budget=runtime.budget.available)
    except (DynamicError,OSError) as error:
        status='failed_history_retained'
        runtime.termination_reason=runtime.termination_reason or getattr(error,'code','infra_failure')
        runtime.ledger.append('history_execution_failed',{'error_type':type(error).__name__,'code':getattr(error,'code',None)})
        partial=runtime.lifecycle.capture_partial(runtime.environment,runtime.client,runtime.sessions,reason=getattr(error,'code',type(error).__name__))
        write_json(runtime.directory/'partial-state.json',partial);frozen=partial.get('environment_export')
    finally:
        for actor,session in runtime.sessions.items():
            try:sessions[actor]=runtime.client.call(session,'export_session')
            except (DynamicError,OSError,TimeoutError) as error:
                runtime.ledger.append('history_session_export_failed',{'actor_id':actor,'status':'unknown','code':getattr(error,'code',type(error).__name__)})
        runtime.client.close();runtime.environment.close()
    if set(sessions)!=set(('Main','A','B')):
        raise DynamicError('history_session_unavailable','Infrastructure failure retained; no complete carry state available')
    record={'task_id':runtime.case['case_id'],'source_task_path':runtime.case['source_task_path'],
        'planning_contract':planning_identity(),'model_bindings_hash':digest(runtime.resolved_api_bindings),'started_ns':start,'finished_ns':time.monotonic_ns(),
        'initial_state':initial,'frozen_state':frozen,'status':status,'termination_reason':runtime.termination_reason,'budget':runtime.budget.snapshot(),
        'request_ledger_hash':runtime.ledger.content_hash(),'session_hashes':{a:digest(s) for a,s in sessions.items()},
        'synthetic':runtime.synthetic,'execution_backend':runtime.execution_mode,'environment_carry':False}
    record['history_id']='history_'+digest(record);write_json(runtime.directory/'history-execution.json',record)
    return sessions,record


def execute_history(parent,source):
    from trustfork.agents.pi_dynamic import PiDynamic
    history=History();records=[]
    for index,case_id in enumerate(parent.history_task_ids):
        if case_id==parent.case['case_id']:raise DynamicError('history_task_overlap',case_id)
        runtime=PiDynamic(case_id,parent.out/'history'/str(index),layout=parent.layout,main_model=parent.main_model,
            protocol='F',provider=parent.provider,legacy=parent.experiment is None,team_model=parent.main_model,history_pair_id=parent.experiment.history_pair_id if parent.experiment else 'HIST1',history_task=True)
        sessions,record=execute_task(runtime,source.clone(),history.export() if history.tasks else None)
        history.add_task(case_id,sessions,synthetic=parent.synthetic,status=record['status']);records.append(record)
    parent.history=history.export();parent.history.update(execution_records=records,
        actual_historical_task_executions=2 if not parent.synthetic else 0,mock_environment_task_executions=2 if parent.synthetic else 0)
    parent.history['history_id']='history_bundle_'+digest(parent.history)
    write_json(parent.out/'history.json',parent.history)
    return parent.history
