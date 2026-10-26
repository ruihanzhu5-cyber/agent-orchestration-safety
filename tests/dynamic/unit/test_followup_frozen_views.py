"""Regression on all four real sanitized frozen views, never synthetic substitutes."""
import json
from pathlib import Path
import pytest
from trustfork.runtime.dynamic.common import repo_root,digest,file_hash
from trustfork.runtime.dynamic.review_packing import read_review_bytes
from trustfork.scoring.trajectory_codec import encode_trajectory_v2,decode_trajectory
ROOT=repo_root()/"runs/published/first-api-20261026"
SOURCES=sorted(ROOT.glob("trajectories/*/scoring/trajectory_input.json*"))
# Top-level mirrors only: exactly four original GPT trajectories.
assert len(SOURCES)==4

@pytest.mark.parametrize("path",SOURCES,ids=lambda p:p.parents[1].name)
def test_real_frozen_view_roundtrip_source_hash_order_and_occurrences(path):
 before=file_hash(path)
 envelope=json.loads(read_review_bytes(ROOT,path.relative_to(ROOT).as_posix()))
 view=envelope["data"];original=digest(view)
 encoded=encode_trajectory_v2(view);decoded=decode_trajectory(encoded)
 assert decoded==view and digest(decoded)==original
 assert decoded["trajectory"]==view["trajectory"] and decoded["evidence_index"]==view["evidence_index"]
 assert file_hash(path)==before
