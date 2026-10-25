"""Prepare one explicit frozen H1/H2 bundle. No implicit real authorization."""
import argparse
from pathlib import Path
from trustfork.agents.pi_dynamic import PiDynamic,ScriptSource,ProviderSource
from trustfork.runtime.dynamic.common import DynamicError,read_json
from trustfork.runtime.dynamic.scripted_fixtures import history_scripts
from trustfork.runtime.dynamic.prepared_artifacts import prepare_history
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--team-model',choices=['gpt4o','deepseekflash'],required=True);p.add_argument('--history-pair-id',choices=['HIST1','HIST2'],required=True);p.add_argument('--mode',choices=['scripted-test','mock','api'],required=True);p.add_argument('--bindings',type=Path);p.add_argument('--mock-responses',type=Path);p.add_argument('--request-ceiling',type=int);p.add_argument('--allow-real-api',action='store_true');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():raise DynamicError('history_output_exists','Select a new preparation attempt')
 provider=None
 if a.mode!='scripted-test':
  if not a.bindings:p.error('--bindings required')
  from trustfork.runtime.dynamic.provider import ProviderTransport
  from collections import deque
  import threading
  replies=deque(read_json(a.mock_responses)) if a.mock_responses else deque();lock=threading.Lock()
  def reply(*unused):
   with lock:
    if not replies:raise DynamicError('mock_reply_exhausted','No fallback')
    return replies.popleft()
  provider=ProviderTransport(read_json(a.bindings),mode=a.mode,journal=a.out/'provider-requests.jsonl',authorize_real=a.allow_real_api,http=reply if a.mode=='mock' else None,max_requests=a.request_ceiling)
 runtime=PiDynamic('p001',a.out,team_model=a.team_model,history_pair_id=a.history_pair_id,provider=provider)
 bundle=prepare_history(runtime,ScriptSource(history_scripts()) if provider is None else ProviderSource(),a.out/'history-bundle.json')
 print(bundle['bundle_id'])
if __name__=='__main__':main()
