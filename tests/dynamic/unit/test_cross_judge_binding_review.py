import copy,pytest
from trustfork.runtime.dynamic.common import digest,DynamicError
from trustfork.scoring.dynamic_pipeline import judge_pass_binding

def test_explicit_new_scoring_binding_keeps_legacy_origin_and_rejects_tamper():
 old={'model_id':'old-judge'};new={'model_id':'new-judge','provider':'official','base_url':'https://example.invalid'}
 m={'judge_binding_identity_version':'judge-binding-snapshot-v1','resolved_judge_binding':new,'resolved_judge_binding_hash':digest(new)}
 assert judge_pass_binding({},old)==old
 assert judge_pass_binding(m,old)==new and old=={'model_id':'old-judge'}
 bad=copy.deepcopy(m);bad['resolved_judge_binding']['model_id']='tampered'
 with pytest.raises(DynamicError,match='annotation_judge_binding_invalid'):judge_pass_binding(bad,old)
 for bad in ({'resolved_judge_binding_hash':'incomplete'},dict(m,judge_binding_identity_version='unknown')):
  with pytest.raises(DynamicError,match='annotation_judge_binding_invalid'):judge_pass_binding(bad,old)
 secret=dict(new,key_env='not-a-secret-but-not-needed');bad=dict(m,resolved_judge_binding=secret,resolved_judge_binding_hash=digest(secret))
 with pytest.raises(DynamicError,match='annotation_judge_binding_invalid'):judge_pass_binding(bad,old)
