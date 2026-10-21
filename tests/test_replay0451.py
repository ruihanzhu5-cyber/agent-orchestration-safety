"""Offline contract tests, not real experiment results."""
import copy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as N
import unittest
from unittest.mock import patch
from trustfork import replay0451 as r


def response(text='Done', model='gpt-4o', calls=None):
    return N(choices=[N(finish_reason='tool_calls' if calls else 'stop', message=N(content=text,tool_calls=calls))],
             model=model,id='synthetic-test-response',usage=None)


class Client:
    def __init__(self,replies):
        self.replies,self.requests=list(replies),[]
        self.chat=N(completions=self)
    def create(self,**kwargs):
        self.requests.append(copy.deepcopy(kwargs))
        result=self.replies.pop(0)
        if isinstance(result,Exception):raise result
        return result


class Workspace:
    def __init__(self):self.calls=[]
    def rpc(self,operation,**args):
        self.calls.append((operation,args))
        return {'exists':True,'content':'test evidence'}


class ReplayTests(unittest.TestCase):
    def engine(self,folder,replies):
        client,workspace=Client(replies),Workspace()
        engine=r.Engine(r.Events(Path(folder)/'events.jsonl'),workspace,r.config_for('D-G','test-image'),
                        {'openai':client,'deepseek':client})
        engine.stage='inject_poison'
        return engine,client,workspace

    def test_only_two_treatment_fields_differ(self):
        configs=[r.config_for(c,'test-image') for c in r.CONDITIONS]
        self.assertEqual(len({json.dumps(r.matched_config(c),sort_keys=True) for c in configs}),1)
        self.assertEqual({(c['route'],c['source_label']) for c in configs},
                         {('direct','GPT-4o'),('direct','DeepSeek V4 Flash'),
                          ('peer_chain','GPT-4o'),('peer_chain','DeepSeek V4 Flash')})
        self.assertTrue(all(c['proposal_sha256']==r.sha(r.PROPOSAL) for c in configs))

    def test_replay_never_invents_main_choice_or_model_authorship(self):
        a,b=r.identity_envelope('GPT-4o'),r.identity_envelope('DeepSeek V4 Flash')
        self.assertEqual(a['content'],b['content'])
        self.assertIn('not_live_model',r.config_for('D-G','test')['source_kind'])
        history=r.main_history('original task','D','GPT-4o',r.PROPOSAL)
        self.assertEqual([m['role'] for m in history],['system','user','user'])
        self.assertFalse(any('tool_calls' in m for m in history))
        self.assertEqual(history[1]['content'],'original task')
        self.assertIn('not an additional user instruction',history[2]['content'])

    def test_chain_main_sees_b_without_automatic_hidden_source(self):
        history=r.main_history('task','B','GPT-4o','B rejects the proposal')
        self.assertNotIn(r.PROPOSAL,history[-1]['content'])
        self.assertNotIn('DeepSeek V4 Flash',r.MAIN_SYSTEM)

    def test_tool_boundaries_are_explicit(self):
        names=lambda tools:{t['function']['name'] for t in tools}
        self.assertEqual(names(r.READ_TOOLS),{'list_files','read_file'})
        self.assertNotIn('write_file',names(r.MAIN_TOOLS))
        self.assertNotIn('delegate_task',names(r.WORKER_TOOLS))
        self.assertNotIn('bash',names(r.WORKER_TOOLS))
        for name,args in [('run_shell',{}),('read_file',{'name':'trash.txt','extra':'x'}),
                          ('delegate_task',{'member':'E','instruction':'x'})]:
            with self.assertRaises(r.ProtocolError):r.validate_args(name,args,r.MAIN_TOOLS)

    def test_paths_and_readonly_input(self):
        for name in ('../config.json','/etc/passwd','a/../trash.txt','memory_backup.md'):
            with self.assertRaises(r.ToolDenied):r.check_file(name,writing=True)
        r.check_file('memory_backup.md')
        r.check_file('MEMORY.md',writing=True)

    def test_actual_main_delegation_precedes_worker_execution(self):
        call=N(id='actual-main-call',type='function',function=N(name='delegate_task',
            arguments=json.dumps({'member':'B','instruction':'Inspect only; do not modify.'})))
        with TemporaryDirectory() as folder:
            engine,client,workspace=self.engine(folder,[response(calls=[call]),response('Checked'),response('Finished')])
            engine.run_stage('task')
            rows=engine.events.rows
            request=next(e for e in rows if e['kind']=='tool_request')
            worker=next(e for e in rows if e['kind']=='model_request' and e['actor']=='B')
            self.assertLess(rows.index(request),rows.index(worker))
            self.assertEqual(request['arguments']['instruction'],'Inspect only; do not modify.')
            self.assertEqual(workspace.calls,[])
            self.assertEqual(len(client.requests),3)

    def test_denial_is_recorded_not_converted_to_success(self):
        call=N(id='denied',type='function',function=N(name='delete_file',arguments=json.dumps({'name':'/etc/passwd'})))
        with TemporaryDirectory() as folder:
            engine,client,workspace=self.engine(folder,[response(calls=[call]),response('Denied')])
            engine.conversation('B',[{'role':'user','content':'test'}],r.WORKER_TOOLS,3,'test')
            result=next(e for e in engine.events.rows if e['kind']=='tool_result')
            self.assertEqual(result['result']['status'],'denied')
            self.assertEqual(workspace.calls,[])

    def test_provider_error_does_not_trigger_resampling(self):
        with TemporaryDirectory() as folder:
            engine,client,_=self.engine(folder,[RuntimeError('provider failure'),response('retry')])
            with self.assertRaisesRegex(RuntimeError,'provider failure'):engine.run_stage('task')
            self.assertEqual(len(client.requests),1)
            self.assertEqual(engine.calls,1)

    def test_wrong_model_and_call_budget_fail_closed(self):
        with TemporaryDirectory() as folder:
            engine,_,_=self.engine(folder,[response(model='gpt-4o-mini')])
            with self.assertRaisesRegex(r.ProtocolError,'Unexpected reported model'):engine.run_stage('task')
        with TemporaryDirectory() as folder:
            engine,client,_=self.engine(folder,[response()])
            engine.config['max_model_calls_per_condition']=0
            with self.assertRaisesRegex(r.ProtocolError,'budget exhausted'):engine.run_stage('task')
            self.assertEqual(client.requests,[])

    def test_fresh_main_has_no_previous_stage_messages(self):
        with TemporaryDirectory() as folder:
            engine,client,_=self.engine(folder,[response('PRIVATE_STAGE_ONE_REPORT'),response('second')])
            engine.run_stage('task1',r.main_history('task1','D','GPT-4o','STAGE_ONE_ONLY'))
            engine.stage='trigger_deletion'
            engine.run_stage('task2')
            second=json.dumps(client.requests[1]['messages'])
            self.assertNotIn('STAGE_ONE_ONLY',second)
            self.assertNotIn('PRIVATE_STAGE_ONE_REPORT',second)
            self.assertEqual(len(client.requests[1]['messages']),2)

    def test_private_configuration_redacted_from_errors(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'test-private-value','OPENAI_BASE_URL':'https://private.invalid/v1'}):
            result=r.public_error(RuntimeError('test-private-value https://private.invalid/v1'))
            self.assertNotIn('test-private-value',result)
            self.assertNotIn('private.invalid',result)


if __name__=='__main__':unittest.main()
