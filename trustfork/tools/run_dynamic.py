"""Run an explicitly synthetic Pi/Docker test block; never a formal API matrix."""
import argparse
import json
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic, ScriptSource,ProviderSource
from trustfork.runtime.dynamic.common import write_json
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts, history_scripts
from trustfork.runtime.dynamic.artifacts import resolve_output,Campaign,artifact_root
from trustfork.runtime.dynamic.common import DynamicError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['scripted-test','mock','api'],required=True,help='New: mock/API provider paths; default never inferred from credentials')
    parser.add_argument('--bindings',type=Path,help='New: exact provider binding file (no key values)')
    parser.add_argument('--allow-real-api',action='store_true',help='New: future per-run authorization; local real_api_enabled must also be true')
    parser.add_argument('--request-ceiling',type=int,help='New: campaign-wide provider attempt ceiling, including H1/H2')
    parser.add_argument('--mock-responses',type=Path,help='New: local HTTP reply array; mock has no external transport')
    parser.add_argument('--case',required=True)
    parser.add_argument('--protocol',choices=['S','F','L'],required=True)
    parser.add_argument('--conditions',nargs='+',choices=['HP','HA','MP','MA','normal','risk'],default=['HP','HA','MP','MA'])
    parser.add_argument('--layout',choices=['P1','P2','P3','P4'],default=None)
    parser.add_argument('--main-model',choices=['gpt4o','deepseekflash'],default='gpt4o')
    parser.add_argument('--panel',choices=['primary','80_60','no_history','no_external_portfolio','r70','self_on_request','reminder','strategy','repeat','late_join'],default='primary')
    parser.add_argument('--strategy',choices=['context_negotiation','peer_collaboration'])
    parser.add_argument('--repeat-id',type=int,choices=[0,1,2],default=0)
    parser.add_argument('--trial-workers',type=int,choices=[1],default=1)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--campaign',help='New: existing verified campaign ID; block directory uses a safe slug')
    parser.add_argument('--recruit',nargs='*',choices=['C','D'],default=['C','D'])
    parser.add_argument('--team-model',choices=['gpt4o','deepseekflash'])
    parser.add_argument('--history-pair-id',choices=['HIST1','HIST2'],default='HIST1')
    parser.add_argument('--history-bundle',type=Path)
    parser.add_argument('--prefix-artifact',type=Path)
    parser.add_argument('--generate-history-per-block',action='store_true',help='Exploration only; not a frozen campaign')
    parser.add_argument('--legacy',action='store_true',help='Explicit mixed-layout compatibility')
    args=parser.parse_args()
    if not args.history_bundle and not args.generate_history_per_block:parser.error('--history-bundle required; exploration must explicitly select --generate-history-per-block')
    if args.history_bundle and args.generate_history_per_block:parser.error('Select frozen bundle or exploration, never both')
    if args.campaign:
        campaign=Campaign(artifact_root()/'campaigns'/args.campaign);campaign.verify()
        from trustfork.runtime.dynamic.artifacts import safe_slug
        from trustfork.runtime.dynamic.common import read_json,repo_root,digest
        import subprocess
        identity=read_json(campaign.path/'campaign.json')['identity']
        current_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip()
        selected_config=read_json(args.bindings) if args.bindings else {}
        if identity['commit']!=current_commit or identity['mode']!=args.mode or identity['config_hash']!=digest(selected_config):raise DynamicError('campaign_invocation_mismatch','Source/config/mode changed; create a new campaign')
        if args.legacy:
            if args.layout is None:parser.error('--legacy requires an explicit --layout')
            logical='|'.join((args.case,args.main_model,args.layout,args.protocol,args.panel,str(args.repeat_id),args.strategy or 'default'))
        else:
            from trustfork.runtime.dynamic.experiment_config import resolve_experiment,block_id
            cfg=resolve_experiment(args.case,team_model=args.team_model or args.main_model,history_pair_id=args.history_pair_id,protocol=args.protocol,panel='late_join' if args.protocol=='L' and args.panel=='primary' else args.panel,repeat_id=args.repeat_id)
            logical=block_id(args.case,cfg,args.strategy)
            planned=[json.loads(line) for line in (campaign.path/'plan.jsonl').read_text().splitlines()]
            if planned:
                if args.generate_history_per_block:raise DynamicError('exploration_in_frozen_campaign','Frozen plans require explicit bundles')
                matches=[p for p in planned if p['block_id']==logical]
                if not set(args.conditions)<={p['condition'] for p in matches}:raise DynamicError('campaign_plan_scope_mismatch','Block/conditions are outside the frozen plan')
        args.out=campaign.block(logical)
    else:args.out=resolve_output(args.out)
    if args.out.exists():raise DynamicError('run_output_exists','Select a new output or reconcile the existing frozen block; never overwrite')
    provider=None
    if args.mode!='scripted-test':
        if not args.bindings:parser.error('--bindings required for mock/api; aliases never imply precise model IDs')
        from trustfork.runtime.dynamic.provider import ProviderTransport
        from trustfork.runtime.dynamic.common import read_json
        mock=None
        if args.mode=='mock':
            if not args.mock_responses:parser.error('--mock-responses required; mock cannot use network')
            from collections import deque
            import threading
            replies=deque(read_json(args.mock_responses));lock=threading.Lock()
            def mock(*unused):
                with lock:
                    if not replies:raise DynamicError('mock_reply_exhausted','No fallback response')
                    return replies.popleft()
        provider=ProviderTransport(read_json(args.bindings),mode=args.mode,journal=args.out/'provider-requests.jsonl',
            authorize_real=args.allow_real_api,http=mock,max_requests=args.request_ceiling,experiment=None if args.legacy else __import__('trustfork.runtime.dynamic.experiment_config',fromlist=['resolve_experiment']).resolve_experiment(args.case,team_model=args.team_model or args.main_model,history_pair_id=args.history_pair_id,protocol=args.protocol,panel='late_join' if args.protocol=='L' else args.panel,repeat_id=args.repeat_id))
    runtime=PiDynamic(args.case,args.out,protocol=args.protocol,layout=args.layout,main_model=args.main_model,
        panel=args.panel,strategy=args.strategy,repeat_id=args.repeat_id,provider=provider,team_model=args.team_model,history_pair_id=args.history_pair_id,legacy=args.legacy)
    from trustfork.runtime.dynamic.prepared_artifacts import load_history,load_prefix
    history=load_history(runtime,args.history_bundle,reuse_journal=args.out/'history-reuse.jsonl') if args.history_bundle else runtime.run_history(scripts=ScriptSource(history_scripts()) if provider is None else ProviderSource())
    prefix=load_prefix(runtime,args.prefix_artifact) if args.prefix_artifact else None
    result=runtime.run_block(ScriptSource(branch_scripts(args.case,protocol=args.protocol,recruit=args.recruit)) if provider is None else ProviderSource(),conditions=args.conditions,history=history,prefix=prefix)
    write_json(args.out/'block.json',result)
    if args.campaign:campaign.index()
    print(json.dumps({'synthetic':runtime.synthetic,'mode':args.mode,'prefix_status':result.get('prefix_status',result.get('prefix',{}).get('status')),
        'branches':len(result['branches']),'run_statuses':[x['run_status'] for x in result['branches']],
        'real_model_requests':provider.count if provider and provider.mode=='api' else 0,'real_judge_requests':0},indent=2))


if __name__=='__main__':main()
