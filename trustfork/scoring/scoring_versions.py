"""Explicit frozen-run rescoring and transactional version publication."""
from __future__ import annotations
import json
import shutil
import tempfile
from pathlib import Path
from trustfork.runtime.dynamic.common import DynamicError,digest,file_hash,read_json,write_json


def validate_scorer_lineage(origin,current,*,rescore=None):
    if origin==current:return
    if not rescore:raise DynamicError('run_scorer_hash_mismatch','Use explicit frozen-run rescoring')
    if rescore['frozen_identity']['origin_scorer_hash']!=origin or rescore['current_scorer_hash']!=current:
        raise DynamicError('rescore_scorer_lineage_mismatch','Original and new scorer hashes must both remain explicit')


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
            archive=value.get('workspace_tar') or value.get('path')
            if isinstance(archive,str) and value.get('sha256'):
                actual=Path(archive)
                if not actual.is_absolute():actual=root/actual
                if not actual.is_file() or file_hash(actual)!=value['sha256']:
                    raise DynamicError('frozen_archive_hash_mismatch','Frozen workspace/service archive changed or is missing')
            for key,item in value.items():
                if (key.endswith(('_tar','_path')) or key=='path') and isinstance(item,str):
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


def rescore_contract(path,*,reason,annotation_policy='pending',compatibility=None,new_annotations=None,source_audit=None,view_migration=None,scoring_profile=None):
    from .dynamic_pipeline import scorer_manifest
    if not reason.strip():raise DynamicError('rescore_reason_required','Describe why this frozen run needs new scoring')
    if annotation_policy not in ('pending','reuse','new'):
        raise DynamicError('invalid_annotation_policy',annotation_policy)
    if view_migration and annotation_policy!='new':raise DynamicError('view_migration_requires_new_judge','No annotation reuse across changed views')
    root=Path(path).parent;output=root/'scoring';current=read_json(output/'current_version.json')
    parent=output/current['path'];version=read_json(parent/'version.json')
    if current['path']!='versions/'+current['version_id'] or version.get('version_id')!=current['version_id'] or digest(version['identity'])!=current['version_id']:
        raise DynamicError('scoring_version_corrupt','Version identity and current pointer do not match')
    for name,h in version['files'].items():
        if file_hash(parent/name)!=h:raise DynamicError('scoring_version_corrupt',name)
    origin=frozen_identity(path)
    # Compare to the preserved original full view as well as immutable run manifest.
    previous_summary=read_json(parent/'run_summary.json')['data'] if 'data' in read_json(parent/'run_summary.json') else read_json(parent/'run_summary.json')
    if previous_summary['run_manifest_hash']!=origin['run_manifest_hash']:
        raise DynamicError('rescore_frozen_manifest_changed','Original binding/evidence differs')
    run=read_json(path)
    previous_identity=version['identity'].get('frozen_identity') or version['identity'].get('rescore',{}).get('frozen_identity')
    if previous_identity and previous_identity!=origin:
        raise DynamicError('rescore_frozen_evidence_changed','Frozen source differs from parent version')
    source_audit_hash=None
    if not previous_identity:
        if source_audit is None:raise DynamicError('rescore_source_seal_unknown','Legacy score lacks an event-envelope seal; supply a retained original source audit, never invent a baseline')
        audit=read_json(source_audit);source_hashes=audit.get('source_file_hashes',{})
        run_audited=source_hashes.get(str(Path(path).resolve()))==file_hash(Path(path))
        if not run_audited:
            # Old writers used canonical JSON plus newline. Recover its exact
            # bytes only when every original field is still in the archived summary.
            from trustfork.runtime.dynamic.common import canonical
            import hashlib
            if any(key not in previous_summary or previous_summary[key]!=value for key,value in run.items()):
                raise DynamicError('rescore_original_run_unknown','Original run bytes need a retained audit; summary fields were changed or overwritten')
            restored={key:previous_summary[key] for key in run}
            if hashlib.sha256(canonical(restored)+b'\n').hexdigest()!=file_hash(Path(path)):
                raise DynamicError('rescore_original_run_changed','Legacy canonical run bytes differ from the immutable summary')
        for name in (run['events_path'],run['prefix_events_path']):
            log=(root/name).resolve()
            if source_hashes.get(str(log))!=file_hash(log):
                raise DynamicError('rescore_legacy_source_audit_mismatch','Original event bytes are not proved by the supplied retained audit')
        source_audit_hash=file_hash(source_audit)
    current_scorer=scorer_manifest()
    if annotation_policy=='new':
        if new_annotations is None or read_json(new_annotations).get('scorer_manifest_hash')!=current_scorer['manifest_hash']:
            raise DynamicError('new_annotation_scorer_mismatch','New Judge output must explicitly bind this scorer')
    if annotation_policy=='reuse':
        prior=read_json(parent/'scorer_manifest.json')['data']
        annotation_path=root/'scoring_annotations.json'
        if not annotation_path.exists():raise DynamicError('annotation_reuse_unavailable','No original annotations to reuse')
        original_annotations=read_json(annotation_path)
        if original_annotations.get('scorer_manifest_hash')!=prior['manifest_hash'] or version['identity'].get('annotations_hash')!=digest(original_annotations):
            raise DynamicError('annotation_reuse_origin_mismatch','Parent score must bind these exact original annotations and their scorer')
        # Reuse is narrow: all Judge/annotation semantics must be identical.
        critical=('verifier.py','dynamic_adapter.py','annotation_contracts.py','annotation.schema.json',
            'judge_request.py','judge_client.py','trajectory_codec.py','contracts.schema.json','goal_observer.py','trajectory_observer.py',
            'metric_registry.py','metrics.v2.json','metrics.v2.schema.json','opportunity_rubric.v2.json','dynamic_metrics_v2.py','token_accounting.py')
        unchanged=all(prior['file_hashes'].get(k)==v for k,v in current_scorer['file_hashes'].items()
            if any(k.endswith(x) for x in critical))
        expected={'from_scorer':prior['manifest_hash'],'to_scorer':current_scorer['manifest_hash'],
            'judge_semantics_unchanged':True}
        if not unchanged or compatibility!=expected:
            raise DynamicError('annotation_reuse_incompatible','Explicit matching compatibility and unchanged Judge semantics required')
    result={'reason':reason,'annotation_policy':annotation_policy,
        'annotation_reuse_compatibility':compatibility if annotation_policy=='reuse' else None,
        'annotation_source_hash':file_hash(root/'scoring_annotations.json') if (root/'scoring_annotations.json').exists() else None,
        'judge_status':'reused_with_compatibility' if annotation_policy=='reuse' else 'new_annotations' if annotation_policy=='new' else 'pending_new_judge',
        'parent_version_id':current['version_id'],'frozen_identity':origin,
        'legacy_source_audit_hash':source_audit_hash,
        'current_scorer_hash':current_scorer['manifest_hash']}
    if view_migration:
        required={'old_view_version','new_view_version','old_view_hash','new_view_hash','builder_version','reason','field_mapping','raw_evidence_hash'}
        if set(view_migration)!=required or not view_migration['reason'] or not isinstance(view_migration['field_mapping'],dict) or view_migration['raw_evidence_hash']!=digest(origin) or view_migration['old_view_hash']!=read_json(parent/'trajectory_input.json')['content_hash']:raise DynamicError('view_migration_contract_invalid','Explicit source/target view and raw-evidence binding required')
        if view_migration['old_view_version']!=read_json(parent/'trajectory_input.json')['data'].get('view') or view_migration['builder_version']!='judge-bundle-v3':raise DynamicError('view_migration_contract_invalid','Source view or builder version mismatch')
        result['view_migration']=view_migration
    if scoring_profile is not None:result['scoring_profile']=scoring_profile
    if annotation_policy=='new':
        result.update(new_annotation_path=str(Path(new_annotations).resolve()),new_annotation_hash=file_hash(new_annotations))
    return result


def publish_score(path,*,mode,rescore,score):
    root=Path(path).parent;output=root/'scoring';output.mkdir(exist_ok=True)
    before=frozen_identity(path)
    if rescore and before!=rescore['frozen_identity']:
        raise DynamicError('rescore_frozen_evidence_changed','Frozen source changed since rescore was prepared')
    stage=Path(tempfile.mkdtemp(prefix='.scoring-pending-',dir=root))
    try:
        summary=score(path,mode=mode,output_override=stage,rescore=rescore,frozen_identity=before)
        if not (stage/'current_version.json').exists():return summary
        if frozen_identity(path)!=before:
            raise DynamicError('rescore_frozen_evidence_changed','Frozen evidence changed while scoring')
        if rescore:
            previous=output/'versions'/rescore['parent_version_id']/'trajectory_input.json'
            if read_json(previous)['content_hash']!=read_json(stage/'trajectory_input.json')['content_hash']:
                migration=rescore.get('view_migration')
                if not migration or rescore['annotation_policy']!='new' or migration['old_view_hash']!=read_json(previous)['content_hash'] or migration['new_view_hash']!=read_json(stage/'trajectory_input.json')['content_hash'] or migration['raw_evidence_hash']!=digest(before) or migration['new_view_version']!=read_json(stage/'trajectory_input.json')['data'].get('view'):raise DynamicError('rescore_original_view_changed','Changed view requires a validated migration and new Judge annotations')
                # Migration is already bound in the immutable version identity.
        pointer=read_json(stage/'current_version.json');target=output/pointer['path'];source=stage/pointer['path']
        if target.exists():
            if read_json(target/'version.json')!=read_json(source/'version.json'):
                raise DynamicError('immutable_scoring_conflict',pointer['version_id'])
            for name,h in read_json(target/'version.json')['files'].items():
                if file_hash(target/name)!=h:raise DynamicError('scoring_version_corrupt',name)
        else:
            target.parent.mkdir(exist_ok=True);source.rename(target)
        from .dynamic_pipeline import preserve_scoring_outputs
        preserve_scoring_outputs(output)
        # Compatibility flat outputs are copies; versions/current is authoritative.
        for f in stage.rglob('*'):
            if f.is_file() and f.relative_to(stage).parts[0] not in ('versions','current_version.json'):
                dest=output/f.relative_to(stage);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
        from trustfork.runtime.dynamic.artifacts import atomic_json
        atomic_json(output/'current_version.json',pointer)
        return summary
    finally:
        shutil.rmtree(stage)
