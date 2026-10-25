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
    p.add_argument('--annotation-policy',choices=['pending','reuse','new'],default='pending')
    p.add_argument('--new-annotations',type=Path,help='New: versioned Judge sidecar; never replaces the original annotation file')
    p.add_argument('--source-audit',type=Path,help='Retained original call audit required for a legacy score without full event-envelope seal')
    p.add_argument('--compatibility',type=Path)
    p.add_argument('--view-migration',type=Path)
    p.add_argument('--scoring-profile',choices=['legacy-eight-v1','dynamic-homogeneous-v2'])
    a=p.parse_args()
    contract=rescore_contract(a.run,reason=a.reason,annotation_policy=a.annotation_policy,
        compatibility=read_json(a.compatibility) if a.compatibility else None,new_annotations=a.new_annotations,source_audit=a.source_audit,view_migration=read_json(a.view_migration) if a.view_migration else None,scoring_profile=a.scoring_profile)
    score_run(a.run,mode=a.mode,rescore=contract)


if __name__=='__main__':main()
