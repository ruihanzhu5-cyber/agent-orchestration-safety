"""Create, index, verify or seal a persistent campaign without deleting originals."""
import argparse
import subprocess
from pathlib import Path
from trustfork.runtime.dynamic.artifacts import Campaign,artifact_root
from trustfork.runtime.dynamic.common import read_json,repo_root


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['create','index','verify','seal'])
    p.add_argument('--campaign-id',required=True)
    p.add_argument('--config',type=Path)
    p.add_argument('--plan',type=Path)
    p.add_argument('--mode',choices=['scripted-test','mock','api'],default='scripted-test')
    p.add_argument('--resume',action='store_true')
    p.add_argument('--archive',type=Path)
    a=p.parse_args()
    if a.action=='create':
        import json
        plan=[json.loads(line) for line in a.plan.read_text().splitlines()] if a.plan else []
        campaign=Campaign.create(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo_root(),text=True).strip(),
            dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=repo_root())),config=read_json(a.config) if a.config else {},
            plan=plan,mode=a.mode,campaign_id=a.campaign_id,resume=a.resume)
    else:campaign=Campaign(artifact_root()/'campaigns'/a.campaign_id)
    if a.action=='index':campaign.index()
    elif a.action=='verify':campaign.verify()
    elif a.action=='seal':
        if a.archive is None:p.error('--archive is required for seal')
        campaign.seal(a.archive)
    print(campaign.path)


if __name__=='__main__':main()
