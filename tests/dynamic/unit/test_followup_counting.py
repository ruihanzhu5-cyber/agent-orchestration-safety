import copy,json
import pytest
from test_provider_preparation import configuration
from trustfork.runtime.dynamic.common import digest,DynamicError,read_json,config_dir
from trustfork.runtime.dynamic.token_accounting import engineering_counting_policy,count_request
from trustfork.runtime.dynamic.provider import ProviderTransport
from trustfork.scoring.judge_request import prepare_judge_request

def deep_binding():
 b=configuration()["logical_bindings"]["deepseekflash"]
 b.update(provider="deepseek",base_url="https://api.deepseek.com",model_id="deepseek-v4-flash",engineering_counting="deepseek-v41-text-v1")
 route=digest({k:b[k] for k in ("provider","base_url","model_id")});b["capability"].update(status="declared",route_fingerprint=route)
 b["capability"]["tokenizer"]["applicable_route"]=route
 return b

def test_registered_official_count_is_shared_by_preparation_sender_and_escaping(tmp_path):
 b=deep_binding();c=configuration();c["logical_bindings"]["deepseekflash"]=b;c["judge_binding"]="deepseekflash";c["execution_scope"]="engineering_smoke"
 text={"evidence":"Unicode 原始🙂 \\n "+("continually growing draft "*50)}
 p=prepare_judge_request(text,rubric="rubric",format_instructions="JSON",output_budget=100,judge_binding=b,execution_scope="engineering_smoke")
 t=ProviderTransport(c,mode="mock",journal=tmp_path/"never-send",kind="judge",http=lambda *a:pytest.fail("offline only"),max_requests=1)
 counted=t.accounting(b,p["wire_payload"])
 assert counted==p["token_accounting"] and p["input_tokens"]==counted["input_tokens"]
 assert counted["decoded_input_utf8_bytes"]>counted["input_tokens"] and counted["service_prompt_tokens"] is None
 assert counted["tokenizer"]["id"]=="deepseek-v41-text-v1" and b["capability"]["status"]=="declared"
 escaped={"body":json.dumps(p["wire_payload"],ensure_ascii=True)}
 assert count_request(escaped,engineering_counting_policy(b))==counted
 wrong=copy.deepcopy(b);wrong.update(base_url="https://unregistered.invalid");wrong["capability"]["route_fingerprint"]=digest({k:wrong[k] for k in ("provider","base_url","model_id")});wrong["capability"]["tokenizer"]["applicable_route"]=wrong["capability"]["route_fingerprint"]
 with pytest.raises(DynamicError,match="counting_route_mismatch"):engineering_counting_policy(wrong)
