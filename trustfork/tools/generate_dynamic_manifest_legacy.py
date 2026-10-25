"""Enumerate the frozen v9 plan; plan references are not executed checkpoints."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from trustfork.runtime.dynamic import PROTOCOL_VERSION
from trustfork.runtime.dynamic.case_loader import CONFIRM_CASES, HISTORY_CASES
from trustfork.runtime.dynamic.common import BASE_COMMIT, canonical, digest, read_json, repo_root, write_json
from trustfork.runtime.dynamic.goals import LAYOUTS, focal_actor, bind_goals
from trustfork.runtime.dynamic.profile_service import assigned_corpus, build_profile,ProfileService

MAINS=('gpt4o','deepseekflash')
CONDITIONS=('HP','HA','MP','MA')
FOUR=('p004','p006','p008','p028')
# Appendix B, GPT Main / DS Main, frozen before observing behavior.
MECHANISM_LAYOUTS={
 'p001':('P3','P2'),'p004':('P3','P2'),'p009':('P4','P1'),'p011':('P3','P2'),
 'p014':('P1','P4'),'p006':('P2','P3'),'p016':('P1','P4'),'p017':('P3','P2'),
 'p018':('P4','P1'),'p019':('P1','P4'),'p003':('P2','P3'),'p008':('P1','P4'),
 'p023':('P2','P3'),'p024':('P4','P1'),'p025':('P1','P4'),'p026':('P4','P1'),
 'p028':('P1','P4'),'p029':('P2','P3')}


def block_ref(case,main,layout,protocol,panel='primary',repeat=0,strategy=None):
    return '|'.join((case,main,layout,protocol,panel,str(repeat),strategy or 'default'))


def plan_ref(block,condition):
    return 'plan_'+digest([block,condition])[:24]


def generate_plan(catalog=None):
    from trustfork.scoring.dynamic_pipeline import scorer_manifest
    scorer_hash=scorer_manifest()['manifest_hash']
    catalog=catalog or read_json(repo_root()/'trustfork/config/dynamic/cases.json')
    t3=sorted(set(catalog)-HISTORY_CASES)
    if len(t3)!=26 or set(MECHANISM_LAYOUTS)!={c for c in t3 if catalog[c]['split']=='discovery'}:
        raise ValueError('Frozen split or Appendix B mismatch')
    specs=[]
    def add(cases,layouts,protocol,panel='primary',conditions=CONDITIONS,repeats=(0,),strategies=(None,)):
        for case in cases:
            for main_index,main in enumerate(MAINS):
                selected=layouts if layouts else (MECHANISM_LAYOUTS[case][main_index],)
                for layout in selected:
                    for repeat in repeats:
                        for strategy in strategies:
                            specs.append((case,main,layout,protocol,panel,conditions,repeat,strategy))
    add(t3,('P1','P2','P3','P4'),'S')
    add(t3,('P1','P3'),'F')
    add(sorted(CONFIRM_CASES),('P1','P3'),'S','80_60')
    add(sorted(CONFIRM_CASES),('P1','P3'),'S','no_history',('normal','risk'))
    for panel in ('r70','self_on_request','reminder'):
        add(FOUR,None,'S',panel)
    add(FOUR,None,'S','strategy',('HA','MA'),strategies=('context_negotiation','peer_collaboration'))
    add(FOUR,None,'S','repeat',repeats=(1,2))
    add(FOUR,None,'L','late_join')
    rows=[]
    bundle_cache={};visible_hash_cache={}
    for case_id,main,layout,protocol,panel,conditions,repeat,strategy in specs:
        case=catalog[case_id];q=focal_actor(case_id,layout);r='D' if q=='C' else 'C'
        corpus=assigned_corpus(int(case_id[1:]),int(layout[1]))
        block=block_ref(case_id,main,layout,protocol,panel,repeat,strategy)
        order=sorted(conditions,key=lambda c:(hashlib.sha256((block+'|'+c).encode()).hexdigest(),c))
        prefix=block_ref(case_id,main,layout,'early','common_prefix')
        if protocol=='L':prefix+='|late_progress'
        for condition in conditions:
            level='none' if panel=='no_history' else (('80' if condition[0]=='H' else '60') if panel=='80_60' else condition[0])
            normalized=('HA' if condition=='risk' else 'HP') if panel=='no_history' else condition
            key=(q,level,corpus)
            if key not in bundle_cache:bundle_cache[key]=build_profile(q,level,corpus=corpus)
            bundle=bundle_cache[key]
            goals=bind_goals(case,layout,normalized)
            if strategy:
                goals['goals'][q]+='\n'+read_json(repo_root()/'trustfork/config/dynamic/profiles.json')['strategies'][strategy]
            peer_corpus='R'+str(int(corpus[1])%4+1)
            peer_key=(r,'M' if panel=='r70' else 'none',peer_corpus)
            if peer_key not in bundle_cache:bundle_cache[peer_key]=build_profile(r,peer_key[1],corpus=peer_corpus)
            visible_key=(key,peer_key,panel=='reminder')
            if visible_key not in visible_hash_cache:
                service=ProfileService('plan', {q:bundle,r:bundle_cache[peer_key]},reminder=panel=='reminder')
                visible_hash_cache[visible_key]=digest({a:service.get_public_profile(a,'full') for a in (q,r)})
            baseline=block_ref(case_id,main,layout,'S')
            model_refs={**{a:LAYOUTS[layout][a] for a in 'ABCD'},'Main':main,'judge':'gpt4o'}
            row={'schema_version':'1.0','protocol_version':PROTOCOL_VERSION,'mode':'plan-only','kind':'formal',
                'plan_run_id':plan_ref(block,condition),'run_id':None,'block_id':block,'checkpoint_id':None,'prefix_plan_ref':prefix,
                'case_id':case_id,'source_revision':BASE_COMMIT,'source_task_path':case['source_task_path'],
                'source_asset_hash':case['deployed_asset_hash'],'split':case['split'],'suite':case['suite'],
                'layout':layout,'main_model':main,'q':q,'r':r,'condition':condition,'goal_condition':normalized,
                'protocol':protocol,'panel':panel,'repeat_id':repeat,'strategy':strategy,
                'model_refs':model_refs,'resolved_api_bindings':None,'corpus':None if panel=='no_history' else corpus,
                'profile_hash':visible_hash_cache[visible_key],'sample_hash':bundle['artifact_hash'],
                'goal_hash':digest(goals['goals']),'prompt_config_hash':digest(['common_replace_v1',panel,strategy]),
                'scorer_hash':scorer_hash,'budget':{'requests':120,'output_tokens':48000,'per_request':4096,'stage_seconds':1200},
                'run_order':order.index(condition),'baseline_run_id':None,
                'baseline_plan_ref':plan_ref(baseline,normalized) if panel!='primary' else None,
                'mechanism_sample':panel=='primary' and protocol=='S' and case_id in MECHANISM_LAYOUTS and layout==MECHANISM_LAYOUTS[case_id][MAINS.index(main)],
                'base_task_family':case['base_task_family'],'unresolved':['precise_api_bindings','executed_history','actual_checkpoint_id','judge_context_capacity'],
                'formal_ready':False}
            rows.append(row)
    counts=Counter(x['block_id'] for x in rows)
    if len(rows)!=1664 or len(counts)!=440 or Counter(counts.values())!={4:392,2:48}:
        raise ValueError('Frozen matrix count mismatch')
    if len({x['plan_run_id'] for x in rows})!=1664 or sum(x['mechanism_sample'] for x in rows)!=144:
        raise ValueError('Duplicate runs or incorrect mechanism sample')
    for main in MAINS:
        sample=[x for x in rows if x['mechanism_sample'] and x['main_model']==main and x['condition']=='HP']
        if Counter(x['q'] for x in sample)!={'C':9,'D':9} or Counter(x['model_refs'][x['q']] for x in sample)!={'gpt4o':9,'deepseekflash':9}:
            raise ValueError('Appendix B balance mismatch')
    return rows


def auxiliary_plans():
    histories=[{'kind':'history','main_model':m,'layout':layout,'task_id':task,'history_order':i+1,
                'mode':'plan-only','run_id':None,'real_model_requests':0}
               for m in MAINS for layout in LAYOUTS for i,task in enumerate(LAYOUTS[layout]['history'])]
    smoke=[{'kind':'smoke','case_id':case,'main_model':main,'layout':'P1','protocol':protocol,'condition':condition,
            'mode':'plan-only','run_id':None,'checkpoint_id':None}
           for case in ('p001','p024') for main in MAINS for protocol in ('S','F') for condition in CONDITIONS]
    return {'histories':histories,'smoke':smoke}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-only',action='store_true',required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();rows=generate_plan()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_bytes(b''.join(canonical(x)+b'\n' for x in rows))
    write_json(args.out.with_suffix('.auxiliary.json'),auxiliary_plans())
    summary={'formal_branches':len(rows),'blocks':len({x['block_id'] for x in rows}),'mechanism_branches':144,
        'histories':16,'smoke':32,'executed':0,'real_model_requests':0,'real_judge_requests':0,'mode':'plan-only',
        'counts_by_panel':dict(Counter(x['panel'] for x in rows)),'formal_ready':False}
    write_json(args.out.with_suffix('.summary.json'),summary)
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
