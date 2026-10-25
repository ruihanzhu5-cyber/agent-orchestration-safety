"""Frozen homogeneous design. Legacy P-layouts are never reinterpreted."""
from dataclasses import dataclass,asdict
from .common import DynamicError,read_json,config_dir,digest
from .case_loader import HISTORY_CASES
VERSION='dynamic-join-homogeneous-v1'
TEAMS=('deepseekflash','gpt4o')
HISTORY_PAIRS={'HIST1':('p002','p007'),'HIST2':('p012','p005')}
@dataclass(frozen=True)
class ExperimentConfig:
 experiment_version:str
 team_model:str
 history_pair_id:str
 history_task_ids:tuple
 history_bundle_id:str|None
 history_plan_ref:str
 presentation_assignment_id:str
 q:str
 r:str
 display_order:tuple
 profile_corpus_id:str
 protocol:str
 panel:str
 repeat_id:int
 judge_binding:str
 @property
 def model_refs(self):return {a:self.team_model for a in ('Main','A','B','C','D')}
 def export(self):return {**asdict(self),'model_refs':self.model_refs}
def resolve_experiment(case_id,*,team_model,history_pair_id='HIST1',protocol='S',panel='primary',repeat_id=0,history_bundle_id=None,judge_binding='gpt4o',history_task=False):
 if team_model not in TEAMS or history_pair_id not in HISTORY_PAIRS or protocol not in ('S','F','L') or judge_binding not in TEAMS:
  raise DynamicError('invalid_experiment_configuration','Unknown frozen factor')
 if panel not in ('primary','80_60','no_external_portfolio','r70','self_on_request','reminder','strategy','repeat','late_join') or repeat_id not in (0,1,2):raise DynamicError('invalid_experiment_configuration','Unknown panel/repeat')
 catalog=read_json(config_dir()/'cases.json');t3=sorted(set(catalog)-HISTORY_CASES)
 if case_id not in t3 and not (history_task and case_id in HISTORY_CASES):raise DynamicError('not_t3_case',case_id)
 h=list(HISTORY_PAIRS).index(history_pair_id);odd=int(case_id[1:])%2==1
 q='C' if odd==(h==0) else 'D';r='D' if q=='C' else 'C'
 split=sorted(c for c in t3 if catalog[c]['split']==catalog[case_id]['split'])
 i=split.index(case_id) if case_id in split else 0;k=t3.index(case_id) if case_id in t3 else 0
 order=(q,r) if i%2==0 else (r,q);corpus='R'+str(1+(k+2*h)%4)
 return ExperimentConfig(VERSION,team_model,history_pair_id,HISTORY_PAIRS[history_pair_id],history_bundle_id,
  'history-plan_'+digest([VERSION,team_model,history_pair_id])[:24],
  'presentation_'+digest([VERSION,case_id,history_pair_id,q,order,corpus])[:24],q,r,order,corpus,protocol,panel,repeat_id,judge_binding)
def block_id(case_id,cfg,strategy=None):return '|'.join(map(str,(cfg.experiment_version,case_id,cfg.team_model,cfg.history_pair_id,cfg.presentation_assignment_id,cfg.protocol,cfg.panel,cfg.repeat_id,strategy or 'default')))
