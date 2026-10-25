"""Persistent campaign paths and provenance indexes; no task-workspace mounts."""
from __future__ import annotations
from contextlib import contextmanager
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import uuid
import hashlib
from .common import DynamicError,canonical,digest,file_hash,read_json


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def file_lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('ab') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def append_jsonl(path,value):
    """One authoritative append log; interrupted suffix is never a valid event."""
    path=Path(path)
    with file_lock(path.with_name(path.name+'.lock')):
        if path.exists() and path.stat().st_size:
            with path.open('rb') as previous:
                previous.seek(-1,os.SEEK_END)
                if previous.read()!=b'\n':
                    raise DynamicError('incomplete_jsonl_suffix','Reconcile interrupted suffix; never append success to it')
        with path.open('ab') as stream:
            stream.write(canonical(value)+b'\n');stream.flush();os.fsync(stream.fileno())


def artifact_root():
    value=os.environ.get('TRUSTFORK_ARTIFACT_ROOT')
    if not value or not Path(value).is_absolute():
        raise DynamicError('artifact_root_unconfigured','Set an audited absolute TRUSTFORK_ARTIFACT_ROOT')
    return Path(value).resolve()


def safe_slug(logical_id):
    short=re.sub('[^A-Za-z0-9_-]+','-',logical_id).strip('-')[:48] or 'block'
    if short.upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:short='block-'+short
    return short+'-'+digest(logical_id)[:12]


class Campaign:
    def __init__(self,path):self.path=Path(path)

    @classmethod
    def create(cls,*,commit,config,plan,mode,campaign_id=None,resume=False,dirty=False):
        if mode not in ('scripted-test','mock','api'):raise DynamicError('invalid_campaign_mode',mode)
        name=campaign_id or datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+commit[:8]+'-'+uuid.uuid4().hex[:8]
        if not re.fullmatch('[A-Za-z0-9_-]{1,120}',name):raise DynamicError('unsafe_campaign_id',name)
        path=artifact_root()/'campaigns'/name
        identity={'commit':commit,'config_hash':digest(config),'plan_hash':digest(plan),'mode':mode,'dirty':bool(dirty)}
        try:path.mkdir(parents=True,exist_ok=False)
        except FileExistsError:
            if not resume:raise DynamicError('campaign_exists','Explicit verified resume required')
            previous=read_json(path/'campaign.json')
            if previous['identity']!=identity:raise DynamicError('campaign_resume_mismatch','Commit/dirty/config/plan/mode changed')
            append_jsonl(path/'resume.jsonl',{'identity_hash':digest(identity),'resumed_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
            cls(path).verify()
            return cls(path)
        atomic_json(path/'campaign.json',{'campaign_id':name,'identity':identity,'status':'open',
            'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'formal_ready':False})
        for entry in plan:append_jsonl(path/'plan.jsonl',entry)
        for directory in ('history','blocks','analysis','diagnostics','test-results'): (path/directory).mkdir()
        cls(path).index();return cls(path)

    def block(self,block_id):return self.path/'blocks'/safe_slug(block_id)

    def attempt(self,block_id,condition,number,*,resume=False):
        if condition not in ('HP','HA','MP','MA','normal','risk') or type(number) is not int or number<0:
            raise DynamicError('unsafe_attempt_path',str((condition,number)))
        path=self.block(block_id)/condition/f'attempt-{number}'
        if path.exists():
            if not resume:raise DynamicError('attempt_exists','Evidence is immutable; select a new attempt or verified resume')
            self.verify()
            if not (path/'run.json').is_file():raise DynamicError('attempt_incomplete','Reconcile partial work; do not replay side effects')
        else:path.mkdir(parents=True)
        return path

    def index(self):
        with file_lock(self.path/'.index.lock'):
            previous={r['path']:r for r in read_json(self.path/'artifact-index.json')['files']} if (self.path/'artifact-index.json').exists() else {}
            rows=[]
            paths=[]
            for directory,dirs,files in os.walk(self.path,followlinks=False):
                paths.extend(Path(directory)/name for name in dirs+files)
            for path in sorted(paths):
                if path.is_symlink():
                    target=os.readlink(path);name=path.relative_to(self.path).as_posix()
                    rows.append({'path':name,'size':path.lstat().st_size,'sha256':hashlib.sha256(os.fsencode(target)).hexdigest(),
                        'type':'symlink','target':target,'followed':False,'role':name.split('/')[0],'source':{}})
                    continue
                if not path.is_file() or path==self.path/'artifact-index.json' or path.name.endswith(('.lock','.tmp')):continue
                name=path.relative_to(self.path).as_posix()
                prior=previous.get(name,{})
                source=prior.get('source',{})
                if path.suffix=='.json':
                    try:
                        value=read_json(path)
                        if isinstance(value,dict):
                            value=value.get('data',value)
                            source={k:value[k] for k in ('run_id','block_id','history_id','checkpoint_id','version_id',
                                'request_hash','request_id','condition','stage_id','actor_id','attempt_id') if k in value}
                    except (ValueError,OSError):
                        source={'parse_status':'invalid_json_not_success'}
                rows.append({'path':name,'size':path.stat().st_size,'sha256':file_hash(path),
                    'role':name.split('/')[0],'source':source})
            atomic_json(self.path/'artifact-index.json',{'version':'campaign-index-v1','files':rows,'content_hash':digest(rows)})
            return rows

    def verify(self):
        index=read_json(self.path/'artifact-index.json')
        if index['content_hash']!=digest(index['files']):raise DynamicError('artifact_index_corrupt','Index hash differs')
        for row in index['files']:
            path=self.path/row['path']
            if row.get('type')=='symlink':
                if not path.is_symlink() or hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()!=row['sha256']:
                    raise DynamicError('artifact_hash_mismatch',row['path'])
                continue
            if not path.is_file() or path.is_symlink() or file_hash(path)!=row['sha256']:
                raise DynamicError('artifact_hash_mismatch',row['path'])
        return index

    def finish(self,status):
        if status not in ('complete','failed','blocked'):raise DynamicError('invalid_campaign_status',status)
        value=read_json(self.path/'campaign.json');value.update(status=status,finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        atomic_json(self.path/'campaign.json',value);self.index()

    def seal(self,destination):
        self.index();self.verify();destination=Path(destination)
        if destination.exists():raise DynamicError('archive_exists','Existing archives are never overwritten')
        if self.path.resolve() in destination.resolve().parents:raise DynamicError('archive_inside_campaign','Choose a second location outside the campaign')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tarfile.open(destination,'x:gz') as archive:
            archive.add(self.path,arcname=self.path.name)
        atomic_json(destination.with_name(destination.name+'.sha256.json'),{'sha256':file_hash(destination),'campaign_id':self.path.name})
        return destination


def resolve_output(out,*,campaign=None,role='diagnostics'):
    """Retain --out; optionally place it under an existing campaign."""
    if campaign:
        campaign=Campaign(artifact_root()/'campaigns'/campaign)
        campaign.verify()
        return campaign.path/role/(out.name if out else uuid.uuid4().hex)
    if out is None:raise DynamicError('output_required','Select --out or --campaign')
    return Path(out)
