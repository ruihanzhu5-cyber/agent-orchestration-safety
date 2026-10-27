"""Exact core citation expansion; never changes anchors or requests a new score."""
import copy,json
from .trajectory_codec import decode_trajectory

def resolve_core_references(prepared,value,allowed_refs):
    allowed=set(allowed_refs)
    rows=value.get('trajectory_judgements',{}) if isinstance(value,dict) else {}
    if not isinstance(rows,dict):return value,{}
    for row in rows.values():
        if not isinstance(row,dict) or not isinstance(row.get('evidence_refs',[]),list) or any(not isinstance(r,str) for r in row.get('evidence_refs',[])):return value,{}
    refs=[r for row in rows.values() if isinstance(row,dict) for r in row.get('evidence_refs',[])]
    if not any(isinstance(r,str) and r not in allowed for r in refs):return value,{}
    packed=json.loads(prepared['wire_payload']['messages'][1]['content'])
    if packed.get('representation_version')!='trajectory-lossless-v2':return value,{}
    view=decode_trajectory(packed)  # Full source checksum, DAG and prefix validation first.
    strings=[]
    for item in packed['string_pool']:
        strings.append(item['value'] if 'value' in item else strings[item['base']][:item['prefix_chars']]+item['suffix'])
    aliases=packed.get('key_aliases',{})
    def expand(x):
        if isinstance(x,dict):
            if set(x)=={'$s'}:return strings[x['$s']]
            if set(x)=={'$object'}:return {k:expand(v) for k,v in x['$object']}
            return {aliases.get(k,k):expand(v) for k,v in x.items()}
        if isinstance(x,list):return [expand(v) for v in x]
        return x
    dag=expand(packed['root']);pool=dag['content_pool'];memo={}
    def resolve(x):
        if isinstance(x,dict):
            if set(x)=={'@'}:
                key=x['@']
                if key not in memo:memo[key]=resolve(pool[key]['value'])
                return memo[key]
            if set(x)=={'@@'}:return {k:resolve(v) for k,v in x['@@']}
            return {k:resolve(v) for k,v in x.items()}
        if isinstance(x,list):return [resolve(v) for v in x]
        return x
    state=view.get('workspace_after',{});file_values={}
    for path,row in state.get('paths',{}).items():
        reference=(row.get('evidence_ref') or state.get('evidence_ref',''))+'#'+path
        if reference not in allowed:continue
        for key in ('sha256','content_b64','decoded_utf8'):
            text=row.get(key)
            if isinstance(text,str):file_values.setdefault(text,set()).add(reference)
    mapping={}
    for ref in refs:
        if ref in allowed or ref not in pool:continue
        node=resolve(pool[ref]['value'])
        if not isinstance(node,str):continue
        if node in allowed:mapping[ref]=node
        elif len(file_values.get(node,set()))==1:mapping[ref]=next(iter(file_values[node]))
        # Unknown or ambiguous nodes remain invalid; never guess or fuzzily match.
    out=copy.deepcopy(value)
    for row in out.get('trajectory_judgements',{}).values():
        row['evidence_refs']=list(dict.fromkeys(mapping.get(r,r) for r in row.get('evidence_refs',[])))
    return out,mapping
