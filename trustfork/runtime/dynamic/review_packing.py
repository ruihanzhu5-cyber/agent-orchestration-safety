"""Lossless publication packing only; never used by runtime or scoring."""
import gzip,json,posixpath,re,hashlib
from pathlib import Path
from .common import canonical,DynamicError
def sha(v):return hashlib.sha256(v).hexdigest()
VERSION='review-lossless-packing-v1'

def pack_review_files(original):
 files=dict(original);duplicates=[];compressed=[];external=[]
 # Retain every conversation heading and payload; large payloads become stable links.
 for name,data in list(files.items()):
  if not name.endswith('/conversation.md'):continue
  def payload(match):
   raw=match.group(1).encode()
   if len(raw)<4096:return match.group(0)
   json.loads(raw) # only the exporter's generated JSON fences
   target='shared-text/'+sha(raw)+'.json'
   files[target]=raw+b'\n'
   external.append({'conversation':name,'payload_ref':target,'payload_sha256':sha(raw)})
   return '[Complete recorded JSON payload]('+posixpath.relpath(target,posixpath.dirname(name))+')'
  files[name]=re.sub(r'~~~json\n(.*?)\n~~~',payload,data.decode(),flags=re.S).encode()
 # Versioned scoring mirrors frequently repeat exactly the same complete JSON.
 groups={}
 for name,data in files.items():
  if name.endswith('.json') and '/' in name and len(data)>65536:groups.setdefault(sha(data),[]).append(name)
 for digest,names in groups.items():
  target=min(names,key=lambda n:(len(n),n))
  for name in names:
   if name==target:continue
   files[name]=canonical({'review_encoding':'content-reference-v1','review_duplicate_ref':target,'uncompressed_sha256':digest})+b'\n'
   duplicates.append({'path':name,'content_ref':target,'content_sha256':digest,'bytes_saved_before_compression':len(original.get(name,b''))-len(files[name])})
 rename={n:n+'.gz' for n,d in files.items() if n.endswith(('.json','.jsonl','.txt')) and '/' in n and len(d)>256*1024}
 packed={}
 # Leaf JSON/data files first, so large-record wrapper hashes can refer to stored bytes.
 for name,data in files.items():
  if name.endswith('.jsonl'):continue
  if name.endswith('.json'):
   try:v=json.loads(data)
   except ValueError:v=None
   if isinstance(v,dict) and v.get('review_encoding')=='content-reference-v1':
    v['review_duplicate_ref']=rename.get(v['review_duplicate_ref'],v['review_duplicate_ref']);data=canonical(v)+b'\n'
  if name.endswith('README.md') or name=='tests.md' or name.endswith('/conversation.md'):
   text=data.decode()
   def link(m):
    target=m.group(2)
    if '://' in target or target.startswith('#'):return m.group(0)
    old=posixpath.normpath(posixpath.join(posixpath.dirname(name),target))
    return '['+m.group(1)+']('+posixpath.relpath(rename[old],posixpath.dirname(name))+')' if old in rename else m.group(0)
   data=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,text).encode()
  target=rename.get(name,name)
  packed[target]=gzip.compress(data,mtime=0) if name in rename else data
  if name in rename:compressed.append({'original_review_path':name,'stored_path':target,'uncompressed_sha256':sha(data),'uncompressed_size':len(data),'stored_sha256':sha(packed[target]),'stored_size':len(packed[target])})
 for name,data in files.items():
  if not name.endswith('.jsonl'):continue
  rows=[]
  for line in data.splitlines():
   v=json.loads(line)
   if isinstance(v,dict) and set(v)=={'large_record_ref','export_hash','original_sequence'}:
    target=rename.get(v['large_record_ref'],v['large_record_ref'])
    if target not in packed:raise DynamicError('review_reference_missing',target)
    v.update(large_record_ref=target,export_hash=sha(packed[target]))
   rows.append(canonical(v)+b'\n')
  raw=b''.join(rows);target=rename.get(name,name)
  packed[target]=gzip.compress(raw,mtime=0) if name in rename else raw
  if name in rename:compressed.append({'original_review_path':name,'stored_path':target,'uncompressed_sha256':sha(raw),'uncompressed_size':len(raw),'stored_sha256':sha(packed[target]),'stored_size':len(packed[target])})
 for d in duplicates:d['content_ref']=rename.get(d['content_ref'],d['content_ref'])
 for e in external:e['payload_ref']=rename.get(e['payload_ref'],e['payload_ref'])
 note={'version':VERSION,'duplicate_files':duplicates,'gzip_files':compressed,'conversation_payload_refs':external,
  'reconstruction':'read_review_bytes expands gzip/content-reference-v1. JSONL large_record_ref wrappers preserve the original record and order. Source/export hashes are distinct; runtime/scoring originals are untouched.',
  'github_view':'GitHub may not expand gzip. Plain README/config/plan/results/costs/tests and conversation event indexes remain readable. Download and expand gzip to inspect complete large records.'}
 return packed,rename,note

def read_review_bytes(root,relative,_seen=None):
 root=Path(root).resolve();path=(root/relative).resolve()
 if root not in path.parents:raise DynamicError('review_reference_outside_root',relative)
 seen=set() if _seen is None else _seen
 if path in seen:raise DynamicError('review_reference_cycle',relative)
 seen.add(path);raw=path.read_bytes()
 if str(path).endswith('.gz'):raw=gzip.decompress(raw)
 try:v=json.loads(raw)
 except (ValueError,UnicodeError):return raw
 if isinstance(v,dict) and v.get('review_encoding')=='content-reference-v1':
  result=read_review_bytes(root,v['review_duplicate_ref'],seen)
  if sha(result)!=v['uncompressed_sha256']:raise DynamicError('review_reference_hash_mismatch',relative)
  return result
 return raw
