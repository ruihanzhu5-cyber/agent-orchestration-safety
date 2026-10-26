"""Prepare only pinned public tokenizer data. Never loads keys or sends model requests."""
import argparse,hashlib,urllib.request
from pathlib import Path
from trustfork.runtime.dynamic.common import read_json,config_dir,repo_root,DynamicError
from trustfork.runtime.dynamic.artifacts import atomic_json
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--out",type=Path);a=p.parse_args()
 spec=read_json(config_dir()/"tokenizers.v1.json")["deepseek-v41-text-v1"]
 path=a.out or repo_root()/spec["cache_relative"]
 if path.exists():
  raw=path.read_bytes()
 else:raw=urllib.request.urlopen(spec["source"],timeout=60).read()
 if hashlib.sha256(raw).hexdigest()!=spec["sha256"]:raise DynamicError("tokenizer_hash_mismatch","Official data differs from pinned revision")
 path.parent.mkdir(parents=True,exist_ok=True)
 if not path.exists():
  with path.open("xb") as stream:stream.write(raw)
 atomic_json(path.with_name("provenance.json"),spec)
 print("Pinned DeepSeek tokenizer present and hash verified; no model API request.")
if __name__=="__main__":main()
