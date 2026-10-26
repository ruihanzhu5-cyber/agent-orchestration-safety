"""Export a stopped campaign without modifying original evidence."""
import argparse,os
from pathlib import Path
from trustfork.runtime.dynamic.artifacts import artifact_root
from trustfork.runtime.dynamic.common import read_json
from trustfork.runtime.dynamic.review_export import export_campaign
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--campaign',required=True);p.add_argument('--out',type=Path,required=True)
 p.add_argument('--bindings',type=Path);p.add_argument('--snapshot',action='store_true');a=p.parse_args()
 secrets=[]
 if a.bindings:secrets=[os.environ.get(b.get('key_env',''),'') for b in read_json(a.bindings)['logical_bindings'].values()]
 result=export_campaign(artifact_root()/'campaigns'/a.campaign,a.out,secrets=secrets,private_paths=[str(Path.home())],snapshot=a.snapshot)
 print('Exported '+str(len(result['files']))+' files; inspect the staged diff before push.')
if __name__=='__main__':main()
