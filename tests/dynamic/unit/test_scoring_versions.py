from trustfork.runtime.dynamic.common import write_json,read_json,DynamicError
from trustfork.scoring.dynamic_pipeline import preserve_scoring_outputs,freeze_scoring_version
import pytest


def test_old_outputs_and_multiple_annotation_versions_are_preserved(tmp_path):
    write_json(tmp_path/'scores.json',{'version':'old'})
    preserve_scoring_outputs(tmp_path)
    assert len(list((tmp_path/'legacy').rglob('scores.json')))==1
    write_json(tmp_path/'scores.json',{'version':'new'})
    one=freeze_scoring_version(tmp_path,{'annotation':'v1'})
    assert freeze_scoring_version(tmp_path,{'annotation':'v1'})==one
    write_json(tmp_path/'scores.json',{'version':'newer'})
    with pytest.raises(DynamicError):freeze_scoring_version(tmp_path,{'annotation':'v1'})
    two=freeze_scoring_version(tmp_path,{'annotation':'v2'})
    assert one!=two and read_json(tmp_path/'versions'/one/'scores.json')=={'version':'new'}
    assert read_json(next((tmp_path/'legacy').rglob('scores.json')))=={'version':'old'}
