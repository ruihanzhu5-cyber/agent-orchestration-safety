"""Explicitly re-score frozen behavior, preserving original runs and score versions."""
import argparse
from pathlib import Path
from trustfork.runtime.dynamic.common import read_json
from trustfork.scoring.scoring_versions import rescore_contract
from trustfork.scoring.dynamic_pipeline import score_run


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--mode',choices=['formal','test-fixtures'],required=True)
    p.add_argument('--reason',required=True)
    p.add_argument('--annotation-policy',choices=['pending','reuse'],default='pending')
    p.add_argument('--compatibility',type=Path)
    a=p.parse_args()
    contract=rescore_contract(a.run,reason=a.reason,annotation_policy=a.annotation_policy,
        compatibility=read_json(a.compatibility) if a.compatibility else None)
    score_run(a.run,mode=a.mode,rescore=contract)


if __name__=='__main__':main()
