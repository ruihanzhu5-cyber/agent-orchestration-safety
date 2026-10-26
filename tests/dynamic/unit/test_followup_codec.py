import copy,json
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest
from trustfork.scoring.trajectory_codec import encode_trajectory_v2,decode_trajectory,encode_trajectory

def view():
 text="早期草稿🙂"*100
 return {"private_goals_removed":True,"trajectory":[{"event_id":str(i),"recipient":a,"partial":text+" suffix"*i,"message":text+" suffix"*i} for i,a in enumerate(["A","B","A","D"]*8)],"special":{"$s":2},"escape":{"$object":[["x",1]]},"empty":""}
def test_prefix_codec_preserves_every_update_exposure_unicode_and_escaped_key():
 original=view();before=digest(original);v2=encode_trajectory_v2(original)
 assert decode_trajectory(v2)==original and digest(original)==before
 assert decode_trajectory(encode_trajectory(original))==original
 assert any("base" in x for x in v2["string_pool"])
 assert len(json.dumps(v2,ensure_ascii=False))<len(json.dumps(original,ensure_ascii=False))
 assert v2["decoded_hash"]==before
@pytest.mark.parametrize("bad",["missing","cycle","bounds","unicode_hash"])
def test_bad_prefix_reference_does_not_guess_or_repair(bad):
 p=encode_trajectory_v2(view());i=next(i for i,v in enumerate(p["string_pool"]) if "base" in v)
 if bad=="missing":p["string_pool"][i]["base"]=999999
 if bad=="cycle":p["string_pool"][i]["base"]=i
 if bad=="bounds":p["string_pool"][i]["prefix_chars"]=99999999
 if bad=="unicode_hash":p["string_pool"][i]["hash"]="bad"
 with pytest.raises(DynamicError):decode_trajectory(p)
