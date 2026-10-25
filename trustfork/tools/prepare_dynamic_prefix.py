"""Prepare a reusable early prefix from an explicitly supplied history bundle."""
import argparse
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource,ProviderSource
from trustfork.runtime.dynamic.prepared_artifacts import load_history,save_prefix
from trustfork.runtime.dynamic.scripted_fixtures import branch_scripts
from trustfork.runtime.dynamic.common import DynamicError,read_json
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--case',required=True);p.add_argument('--team-model',choices=['gpt4o','deepseekflash'],required=True);p.add_argument('--history-pair-id',choices=['HIST1','HIST2'],required=True);p.add_argument('--history-bundle',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--mode',choices=['scripted-test','mock','api'],required=True);p.add_argument('--bindings',type=Path);p.add_argument('--mock-responses',type=Path);p.add_argument('--request-ceiling',type=int);p.add_argument('--allow-real-api',action='store_true');a=p.parse_args()
 if a.out.exists():raise DynamicError('prefix_output_exists','Choose a new preparation attempt')
 provider=None
 if a.mode!='scripted-test':
  if not a.bindings:p.error('--bindings required')
  from trustfork.runtime.dynamic.provider import ProviderTransport
  from collections import deque
  replies=deque(read_json(a.mock_responses)) if a.mock_responses else deque()
  def reply(*unused):
   if not replies:raise DynamicError('mock_reply_exhausted','No fallback')
   return replies.popleft()
  provider=ProviderTransport(read_json(a.bindings),mode=a.mode,journal=a.out/'provider-requests.jsonl',authorize_real=a.allow_real_api,http=reply if a.mode=='mock' else None,max_requests=a.request_ceiling)
 runtime=PiDynamic(a.case,a.out,team_model=a.team_model,history_pair_id=a.history_pair_id,provider=provider)
 history=load_history(runtime,a.history_bundle)
 prefix=runtime.run_prefix(ScriptSource(branch_scripts(a.case,protocol='S')) if provider is None else ProviderSource(),history=history)
 save_prefix(runtime,prefix,a.out/'prefix-artifact.json');print(prefix['checkpoint']['checkpoint_id'])
if __name__=='__main__':main()
