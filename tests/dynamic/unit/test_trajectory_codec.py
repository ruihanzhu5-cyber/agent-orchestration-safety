import copy
import pytest
from trustfork.runtime.dynamic.common import DynamicError,digest
from trustfork.scoring.trajectory_codec import encode_trajectory,decode_trajectory


def fixture():
    repeated={'text':'中文🙂\nquote " and null '+('abcdef'*200),'binary':{'base64':'//4AAQ=='}}
    return {'private_goals_removed':True,'task':{'request':None},'trajectory':[
        {'event_ref':f'b::e{i}','actor_id':'ABCD'[i%4],'stage_epoch':i//4,
         'event_type':'model_request_submitted','payload':{'history':[repeated]*8,'empty':{},'literal':{'@':'c0001'},'escape':{'@@':[]}}}
        for i in range(24)],'final_response':''}


def test_self_contained_codec_preserves_every_occurrence_and_reserved_values():
    view=fixture(); packed=encode_trajectory(view)
    assert decode_trajectory(packed)==view
    assert digest(decode_trajectory(packed))==packed['decoded_hash']
    assert len(packed['content_pool'])>0 and packed['statistics']['reference_occurrences']>0
    assert [x['event_ref'] for x in decode_trajectory(packed)['trajectory']]==[f'b::e{i}' for i in range(24)]
    assert len(str(packed))<len(str(view))/3


@pytest.mark.parametrize('kind',['hash','reference','cycle','root'])
def test_codec_rejects_corruption_and_missing_external_content(kind):
    packed=encode_trajectory(fixture()); key=next(iter(packed['content_pool']))
    if kind=='hash':packed['content_pool'][key]['hash']='0'*64
    if kind=='reference':packed['content_pool'].pop(key)
    if kind=='cycle':packed['content_pool'][key]['value']={'@':key}
    if kind=='root':packed['decoded_hash']='0'*64
    with pytest.raises(DynamicError):decode_trajectory(packed)


def test_private_goal_removal_must_precede_deduplication():
    with pytest.raises(DynamicError):encode_trajectory({'trajectory':[{'systemPrompt':'private'}]})
