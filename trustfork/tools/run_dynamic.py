"""Run an explicitly synthetic Pi/Docker test block; never a formal API matrix."""
import argparse
import json
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic, ScriptSource
from trustfork.runtime.dynamic.common import write_json
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts, history_scripts
from trustfork.runtime.dynamic.artifacts import resolve_output,Campaign,artifact_root
from trustfork.runtime.dynamic.common import DynamicError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['scripted-test'],required=True)
    parser.add_argument('--case',required=True)
    parser.add_argument('--protocol',choices=['S','F','L'],required=True)
    parser.add_argument('--conditions',nargs='+',choices=['HP','HA','MP','MA','normal','risk'],default=['HP','HA','MP','MA'])
    parser.add_argument('--layout',choices=['P1','P2','P3','P4'],default='P1')
    parser.add_argument('--main-model',choices=['gpt4o','deepseekflash'],default='gpt4o')
    parser.add_argument('--panel',choices=['primary','80_60','no_history','r70','self_on_request','reminder','strategy','repeat','late_join'],default='primary')
    parser.add_argument('--strategy',choices=['context_negotiation','peer_collaboration'])
    parser.add_argument('--repeat-id',type=int,choices=[0,1,2],default=0)
    parser.add_argument('--trial-workers',type=int,choices=[1],default=1)
    parser.add_argument('--out',type=Path)
    parser.add_argument('--campaign',help='New: existing verified campaign ID; block directory uses a safe slug')
    parser.add_argument('--recruit',nargs='*',choices=['C','D'],default=['C','D'])
    args=parser.parse_args()
    if args.campaign:
        campaign=Campaign(artifact_root()/'campaigns'/args.campaign);campaign.verify()
        from trustfork.runtime.dynamic.artifacts import safe_slug
        logical='|'.join((args.case,args.main_model,args.layout,args.protocol,args.panel,str(args.repeat_id),args.strategy or 'default'))
        args.out=campaign.block(logical)
    else:args.out=resolve_output(args.out)
    if args.out.exists():raise DynamicError('run_output_exists','Select a new output or reconcile the existing frozen block; never overwrite')
    runtime=PiDynamic(args.case,args.out,protocol=args.protocol,layout=args.layout,main_model=args.main_model,
        panel=args.panel,strategy=args.strategy,repeat_id=args.repeat_id)
    history=runtime.run_history(scripts=ScriptSource(history_scripts()))
    result=runtime.run_block(ScriptSource(branch_scripts(args.case,protocol=args.protocol,recruit=args.recruit)),conditions=args.conditions,history=history)
    write_json(args.out/'block.json',result)
    if args.campaign:campaign.index()
    print(json.dumps({'synthetic':True,'prefix_status':result.get('prefix_status',result.get('prefix',{}).get('status')),
        'branches':len(result['branches']),'run_statuses':[x['run_status'] for x in result['branches']],
        'real_model_requests':0,'real_judge_requests':0},indent=2))


if __name__=='__main__':main()
