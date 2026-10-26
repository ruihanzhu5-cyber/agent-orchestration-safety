from trustfork.runtime.dynamic.review_export import allowed

def test_reconnected_jsonl_journals_remain_publishable(tmp_path):
 for prefix in ('provider-requests-relay-','judge-requests-relay-'):
  p=tmp_path/'deepseek'/'history'/(prefix+'fixed.jsonl')
  assert allowed(p,tmp_path)
 assert not allowed(tmp_path/'deepseek'/'history'/'random-private.jsonl',tmp_path)
