"""Explicit frozen-run rescoring and transactional version publication."""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
from trustfork.runtime.dynamic.common import DynamicError,digest,file_hash,read_json,write_json


def frozen_identity(path):
    from .dynamic_pipeline import load_events
    path=Path(path);run=read_json(path);root=path.parent
    manifest=read_json(root/run['run_manifest_path'])
    if digest(manifest)!=run['run_manifest_hash']:
        raise DynamicError('run_manifest_hash_mismatch',run['run_id'])
    events=load_events(root,run)
    # Includes exact referenced archives, not just mutable export path strings.
    archives={}
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key.endswith(('_tar','_path')) and isinstance(item,str):
                    p=Path(item)
                    if not p.is_absolute():p=root/p
                    if p.is_file():archives[str(p)]=file_hash(p)
                elif isinstance(item,(dict,list)):visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(run.get('prefix_export',{}));visit(run.get('frozen_export',{}))
    return {'run_hash':file_hash(path),'run_manifest_hash':digest(manifest),
        'trajectory_hash':digest(events),'frozen_archives_hash':digest(archives),
        'model_bindings_hash':digest(manifest.get('resolved_api_bindings')),
        'origin_scorer_hash':manifest['scorer_hash']}


def rescore_contract(path,*,reason,annotation_policy='pending',compatibility=None):
    from .dynamic_pipeline import scorer_manifest
    if not reason.strip():raise DynamicError('rescore_reason_required','Describe why this frozen run needs new scoring')
    if annotation_policy not in ('pending','reuse'):
        raise DynamicError('invalid_annotation_policy',annotation_policy)
    root=Path(path).parent;output=root/'scoring';current=read_json(output/'current_version.json')
    parent=output/current['path'];version=read_json(parent/'version.json')
    for name,h in version['files'].items():
        if file_hash(parent/name)!=h:raise DynamicError('scoring_version_corrupt',name)
    origin=frozen_identity(path)
    # Compare to the preserved original full view as well as immutable run manifest.
    previous_summary=read_json(parent/'run_summary.json')['data'] if 'data' in read_json(parent/'run_summary.json') else read_json(parent/'run_summary.json')
    if previous_summary['run_manifest_hash']!=origin['run_manifest_hash']:
        raise DynamicError('rescore_frozen_manifest_changed','Original binding/evidence differs')
    previous_identity=version['identity'].get('rescore',{}).get('frozen_identity')
    if previous_identity and previous_identity!=origin:
        raise DynamicError('rescore_frozen_evidence_changed','Frozen source differs from parent version')
    current_scorer=scorer_manifest()
    if annotation_policy=='reuse':
        prior=read_json(parent/'scorer_manifest.json')['data']
        # Reuse is narrow: all Judge/annotation semantics must be identical.
        critical=('verifier.py','dynamic_adapter.py','annotation_contracts.py','annotation.schema.json',
            'judge_request.py','trajectory_codec.py','contracts.schema.json','goal_observer.py','trajectory_observer.py')
        unchanged=all(prior['file_hashes'].get(k)==v for k,v in current_scorer['file_hashes'].items()
            if any(k.endswith(x) for x in critical))
        expected={'from_scorer':prior['manifest_hash'],'to_scorer':current_scorer['manifest_hash'],
            'judge_semantics_unchanged':True}
        if not unchanged or compatibility!=expected:
            raise DynamicError('annotation_reuse_incompatible','Explicit matching compatibility and unchanged Judge semantics required')
    return {'reason':reason,'annotation_policy':annotation_policy,
        'annotation_reuse_compatibility':compatibility if annotation_policy=='reuse' else None,
        'annotation_source_hash':file_hash(root/'scoring_annotations.json') if (root/'scoring_annotations.json').exists() else None,
        'judge_status':'reused_with_compatibility' if annotation_policy=='reuse' else 'pending_new_judge',
        'parent_version_id':current['version_id'],'frozen_identity':origin,
        'current_scorer_hash':current_scorer['manifest_hash']}


def publish_score(path,*,mode,rescore,score):
    root=Path(path).parent;output=root/'scoring';output.mkdir(exist_ok=True)
    before=frozen_identity(path)
    if rescore and before!=rescore['frozen_identity']:
        raise DynamicError('rescore_frozen_evidence_changed','Frozen source changed since rescore was prepared')
    stage=Path(tempfile.mkdtemp(prefix='.scoring-pending-',dir=root))
    try:
        summary=score(path,mode=mode,output_override=stage,rescore=rescore)
        if not (stage/'current_version.json').exists():return summary
        if frozen_identity(path)!=before:
            raise DynamicError('rescore_frozen_evidence_changed','Frozen evidence changed while scoring')
        if rescore:
            previous=output/'versions'/rescore['parent_version_id']/'trajectory_input.json'
            if read_json(previous)['content_hash']!=read_json(stage/'trajectory_input.json')['content_hash']:
                raise DynamicError('rescore_original_view_changed','Original scoring trajectory must match exactly')
        pointer=read_json(stage/'current_version.json');target=output/pointer['path'];source=stage/pointer['path']
        if target.exists():
            if read_json(target/'version.json')!=read_json(source/'version.json'):
                raise DynamicError('immutable_scoring_conflict',pointer['version_id'])
        else:
            target.parent.mkdir(exist_ok=True);source.rename(target)
        from .dynamic_pipeline import preserve_scoring_outputs
        preserve_scoring_outputs(output)
        # Compatibility flat outputs are copies; versions/current is authoritative.
        for f in stage.rglob('*'):
            if f.is_file() and f.relative_to(stage).parts[0] not in ('versions','current_version.json'):
                dest=output/f.relative_to(stage);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
        write_json(output/'current_version.json',pointer)
        return summary
    finally:
        shutil.rmtree(stage)
