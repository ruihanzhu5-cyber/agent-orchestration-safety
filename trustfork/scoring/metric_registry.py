"""Single source for dynamic metric scopes, ranges, missingness and family."""
from functools import lru_cache
from copy import deepcopy
from trustfork.runtime.dynamic.common import read_json,config_dir,DynamicError
PROFILE='dynamic-homogeneous-v2'
@lru_cache(maxsize=1)
def _registry():return read_json(config_dir()/'metrics.v2.json')
def registry():return deepcopy(_registry())
def metric_spec(name):
 if name not in _registry()['metrics']:raise DynamicError('unknown_dynamic_metric',name)
 return deepcopy(_registry()['metrics'][name])
def score_metrics():return tuple(k for k,v in _registry()['metrics'].items() if v['table_role'] in ('main','secondary','mechanism'))
def confirmation_family():
 r=_registry();c=r['confirmation'];members=[(team,m,c['contrast']) for team in c['team_models'] for m,v in r['metrics'].items() if v['confirmation_family']]
 n=len(members);tail=c['alpha']/n/2
 return {**c,'members':members,'size':n,'confidence':1-c['alpha']/n,'quantiles':[tail,1-tail]}
def bounds(name):return metric_spec(name)['range']
def metric_summary(rows,name,*,planned=None,valid=None):
 from collections import Counter
 spec=metric_spec(name);counts=Counter(r['status'] for r in rows);assessed=[r for r in rows if r['status']=='complete'];app=[r for r in rows if r['status']!='not_applicable'];n=len(app);u=n-len(assessed)
 for r in assessed:
  if r.get('value') is None or not spec['range'][0]<=r['value']<=spec['range'][1]:raise DynamicError('metric_out_of_range',name)
 total=sum(r['value'] for r in assessed);a=sum(r['value']==1 for r in assessed)
 return {'metric_id':name,'N_planned':len(rows) if planned is None else planned,'N_valid':len(rows) if valid is None else valid,'N_applicable':n,'N_assessed':len(assessed),'positive':a if spec['unit']=='binary' else None,'N_unknown':counts['unknown'],'N_not_annotated':counts['not_annotated'],'N_error':counts['judge_error'],'N_not_applicable':counts['not_applicable'],'subset_mean':total/len(assessed) if assessed else None,'point_estimate':total/n if n and u==0 else None,'all_sample_bounds':[(total+u*spec['range'][0])/n,(total+u*spec['range'][1])/n] if n else [None,None],'range':spec['range'],'coverage':len(assessed)/n if n else None}
