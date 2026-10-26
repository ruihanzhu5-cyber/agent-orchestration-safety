"""Disk-backed deterministic review leaves, compressed at shard completion."""
import gzip,lzma,hashlib,json,os,re,posixpath
from pathlib import Path
from collections.abc import MutableMapping
from .common import DynamicError,canonical,file_hash
class ReviewFiles(MutableMapping):
 def __init__(self,root,scan):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.scan=scan;self.meta={};self.max_leaf=0
 def __iter__(self):return iter(self.meta)
 def __len__(self):return len(self.meta)
 def __delitem__(self,key):del self.meta[key]
 def __getitem__(self,key):
  m=self.meta[key];raw=Path(m['disk']).read_bytes()
  return lzma.decompress(raw) if m['encoding']=='xz' else gzip.decompress(raw) if m['encoding']=='gzip' else raw
 def __setitem__(self,key,value):self.put_stream(key,[value])
 def put_stream(self,key,chunks):
  base=self.root/(hashlib.sha256(key.encode()).hexdigest()+'.raw');h=hashlib.sha256();size=0
  with base.open('wb') as out:
   for chunk in chunks:
    raw=chunk.encode() if isinstance(chunk,str) else chunk;self.scan(raw);h.update(raw);size+=len(raw);out.write(raw)
   out.flush();os.fsync(out.fileno())
  self.max_leaf=max(self.max_leaf,size)
  encoding='plain';disk=base
  if '/' in key and size>256*1024:
   encoding='xz' if key.endswith('.jsonl') else 'gzip';disk=base.with_suffix('.packed')
   with base.open('rb') as source,disk.open('wb') as target:
    if encoding=='xz':
     compressor=lzma.LZMACompressor(format=lzma.FORMAT_XZ,preset=1)
     while chunk:=source.read(65536):target.write(compressor.compress(chunk))
     target.write(compressor.flush())
    else:
     with gzip.GzipFile(filename='',mode='wb',fileobj=target,mtime=0) as compressor:
      while chunk:=source.read(65536):compressor.write(chunk)
    target.flush();os.fsync(target.fileno())
   base.unlink()
  self.meta[key]={'disk':str(disk),'encoding':encoding,'raw_size':size,'raw_hash':h.hexdigest(),'stored_size':disk.stat().st_size,'stored_hash':file_hash(disk)}
 def raw_total(self):return sum(m['raw_size'] for m in self.meta.values())
 def stored_total(self):return sum(m['stored_size'] for m in self.meta.values())
 def stored_info(self,key):return {'path':key,'size':self.meta[key]['stored_size'],'export_hash':self.meta[key]['stored_hash']}
 def finalize(self):
  renames={k:k+('.xz' if m['encoding']=='xz' else '.gz') for k,m in self.meta.items() if m['encoding']!='plain'}
  packed=ReviewFiles(self.root/'final',self.scan);packed.max_leaf=self.max_leaf;compressed=[]
  for key in list(self.meta):
   target=renames.get(key,key);m=self.meta[key]
   if key.endswith('.jsonl'):
    raw=self[key];rows=[];changed=False
    for line in raw.splitlines():
     v=json.loads(line)
     if isinstance(v,dict) and set(v)=={'large_record_ref','export_hash','original_sequence'}:
      ref=v['large_record_ref'];v.update(large_record_ref=renames.get(ref,ref),export_hash=self.meta[ref]['stored_hash']);changed=True
     rows.append(canonical(v)+b'\n')
    if changed:
     packed[key]=b''.join(rows);m=packed.meta.pop(key);packed.meta[target]=m
    else:packed.meta[target]=dict(m)
   elif key.endswith('README.md') or key=='tests.md':
    text=self[key].decode()
    def link(match):
     ref=match.group(2)
     if '://' in ref or ref.startswith('#'):return match.group(0)
     old=posixpath.normpath(posixpath.join(posixpath.dirname(key),ref))
     return '['+match.group(1)+']('+posixpath.relpath(renames[old],posixpath.dirname(key))+')' if old in renames else match.group(0)
    updated=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,text)
    if updated!=text:packed[target]=updated.encode();m=packed.meta[target]
    else:packed.meta[target]=dict(m)
   else:packed.meta[target]=dict(m)
   if m['encoding']!='plain':compressed.append({'original_review_path':key,'stored_path':target,'uncompressed_sha256':m['raw_hash'],'uncompressed_size':m['raw_size'],'stored_sha256':m['stored_hash'],'stored_size':m['stored_size']})
  note={'version':'review-streaming-packing-v3','gzip_files':[m for m in compressed if m['stored_path'].endswith('.gz')],'xz_files':[m for m in compressed if m['stored_path'].endswith('.xz')],'duplicate_files':[],'conversation_payload_refs':[],
   'reconstruction':'read_review_bytes expands standard gzip/XZ. JSONL large_record_ref preserves original rows and order. All source/export/uncompressed hashes are distinct. XZ preset1 bounds compressor memory; no runtime/Judge representation changes.'}
  return packed,renames,note
