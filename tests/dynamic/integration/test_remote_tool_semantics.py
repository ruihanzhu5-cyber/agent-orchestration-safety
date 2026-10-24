import base64
import json
import shlex
import re
import struct
import zlib
import pytest
from trustfork.runtime.dynamic.case_loader import load_case
from trustfork.runtime.dynamic.environment import DockerEnvironment
from trustfork.runtime.dynamic.pi_client import PiClient
from trustfork.runtime.dynamic.common import DynamicError


@pytest.fixture
def tools(tmp_path):
    env=DockerEnvironment(tmp_path/'task');client=None
    try:
        env.prepare(load_case('p001'));client=PiClient(tmp_path/'control',env)
        session,_=client.create_session('C',branch_id='b',task_id='p001',system_prompt='fixture')
        serial=0
        def call(name,args):
            nonlocal serial
            serial+=1
            return client.call(session,'probe_tool',{'name':name,'args':args,'tool_call_id':f'tool_{serial}'},request_id=f'req_{serial}')['result']
        yield env,client,call,tmp_path
    finally:
        if client:client.close()
        env.close()


def native_grep(env,args):
    return native_tool(env,args,'grep')


def native_tool(env,args,name):
    # The oracle is the unmodified Pi factory already installed INSIDE Docker.
    locate=env.exec_work_operation('process.bash',{'command':'readlink -f "$(command -v pi)"'},'locate-pi')
    cli=base64.b64decode(locate['output']).decode().strip()
    assert cli.endswith('/dist/cli.js')
    module=cli.removesuffix('/dist/cli.js')+'/dist/index.js'
    factory={'grep':'createGrepToolDefinition','find':'createFindToolDefinition','read':'createReadToolDefinition'}[name]
    script='import {'+factory+'} from '+json.dumps('file://'+module)+";const args=JSON.parse(process.argv[1]);try{const result=await "+factory+"('/workspace').execute('native',args,undefined,undefined,{});console.log(JSON.stringify({ok:true,result}));}catch(e){console.log(JSON.stringify({ok:false,error:e.message}));}"
    result=env.exec_work_operation('process.argv',{'argv':['node','--input-type=module','-e',script,json.dumps(args)]},'native_'+name+str(abs(hash(json.dumps(args,sort_keys=True)))))
    assert result['exitCode']==0
    return json.loads(base64.b64decode(result['output']))


def test_find_native_empty_directories_globs_gitignore_limit_and_errors(tools):
    env,client,call,tmp=tools
    call('bash',{'command':"mkdir -p /workspace/fd-test/empty-dir /workspace/fd-test/nested /workspace/fd-test/.hidden-dir; printf ignored.txt > /workspace/fd-test/.gitignore; touch /workspace/fd-test/ignored.txt /workspace/fd-test/nested/unique.spec.ts /workspace/fd-test/.hidden-dir/hidden.txt"})
    for options in [{'pattern':'*'},{'pattern':'empty-*'},{'pattern':'nested/*.spec.ts'},
                    {'pattern':'*.spec.ts','limit':1},{'pattern':'absent*'}]:
        args={'path':'/workspace/fd-test',**options}
        expected=native_tool(env,args,'find')
        assert expected['ok']
        actual=call('find',args)
        assert actual==expected['result']
        assert 'ignored.txt' not in actual['content'][0]['text']
    assert call('find',{'path':'/workspace/fd-test','pattern':'empty-*'})['content'][0]['text']=='empty-dir/'
    host=tmp/'host-only-dir';host.mkdir();(host/'sentinel').write_text('HOST')
    args={'path':str(host),'pattern':'*'}
    expected=native_tool(env,args,'find');assert not expected['ok']
    with pytest.raises(DynamicError,match=re.escape(expected['error'])):
        call('find',args)
    assert (host/'sentinel').read_text()=='HOST'


def test_all_seven_tools_in_docker_and_native_grep_equivalence(tools):
    env,client,call,tmp=tools
    call('write',{'path':'/workspace/search/source.txt','content':'before\nDocker needle α\nafter\nDocker needle β\n'})
    call('edit',{'path':'/workspace/search/source.txt','edits':[{'oldText':'before','newText':'intro'}]})
    assert 'intro' in call('read',{'path':'/workspace/search/source.txt'})['content'][0]['text']
    assert 'source.txt' in call('ls',{'path':'/workspace/search'})['content'][0]['text']
    assert 'search/source.txt' in call('find',{'pattern':'*.txt','path':'/workspace'})['content'][0]['text']
    assert call('bash',{'command':'pwd'})['content'][0]['text'].strip()=='/workspace'
    for options in [dict(pattern='needle'),dict(pattern='NEEDLE',ignoreCase=True,context=1),
                    dict(pattern='Docker',literal=True,limit=1),dict(pattern='absent')]:
        args={'path':'/workspace/search',**options}
        expected=native_grep(env,args)
        assert expected['ok']
        assert call('grep',args)==expected['result']
    args={'pattern':'[invalid','path':'/workspace/search'}
    expected=native_grep(env,args)
    assert not expected['ok']
    with pytest.raises(DynamicError,match='regex parse error'):
        call('grep',args)
    # Same absolute path, different namespaces. Host text can never affect search.
    host=tmp/'same-name.txt';host.write_text('HOST_SENTINEL')
    call('write',{'path':str(host),'content':'DOCKER_SENTINEL'})
    assert call('grep',{'path':str(host),'pattern':'HOST_SENTINEL'})['content'][0]['text']=='No matches found'
    assert 'DOCKER_SENTINEL' in call('grep',{'path':str(host),'pattern':'DOCKER_SENTINEL'})['content'][0]['text']
    assert host.read_text()=='HOST_SENTINEL'


def test_bash_native_tail_truncation_full_output_is_in_task(tools):
    env,client,call,_=tools
    result=call('bash',{'command':"python -c 'for i in range(2100): print(\"line\",i)'"})
    assert result['details']['truncation']['truncated']
    path=result['details']['fullOutputPath']
    assert path.startswith('/tmp/pi-bash-')
    full=call('read',{'path':path,'offset':2099})['content'][0]['text']
    assert 'line 2099' in full
    assert str(client.root) not in json.dumps(result)


def test_real_docker_symlink_edit_and_write_share_original_queue(tools):
    env,client,call,_=tools
    call('write',{'path':'/workspace/target.txt','content':'old'})
    call('bash',{'command':'ln -s /workspace/target.txt /workspace/alias.txt'})
    session=next(iter(client.sessions))
    result=client.call(session,'execute_turn',{'messages':[{'role':'user','content':'batch','timestamp':1}],
        'script':{'tools':[{'id':'alias-write','name':'write','arguments':{'path':'/workspace/alias.txt','content':'first'}},
                           {'id':'target-edit','name':'edit','arguments':{'path':'/workspace/target.txt','edits':[{'oldText':'first','newText':'second'}]}}]}},request_id='alias-batch')
    assert result['status']=='success'
    ends=[e for e in result['events'] if e['type']=='tool_execution_end']
    assert len(ends)==2 and not any(e['isError'] for e in ends)
    assert call('read',{'path':'/workspace/target.txt'})['content'][0]['text']=='second'


def test_read_native_offsets_errors_and_binary_image_bytes(tools):
    env,client,call,_=tools
    call('write',{'path':'/workspace/read-lines.txt','content':'one\ntwo\nthree\n'})
    for options in [{'offset':2,'limit':1},{'offset':99},{'limit':1}]:
        args={'path':'/workspace/read-lines.txt',**options};expected=native_tool(env,args,'read')
        if expected['ok']:assert call('read',args)==expected['result']
        else:
            with pytest.raises(DynamicError,match=re.escape(expected['error'])):call('read',args)
    def chunk(kind,data):
        return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x00\xff\x00'))+chunk(b'IEND',b'')
    png=base64.b64encode(raw).decode()
    env.exec_work_operation('fs.write',{'path':'/workspace/pixel.png','data':png},'public-pixel-fixture')
    expected=native_tool(env,{'path':'/workspace/pixel.png'},'read');assert expected['ok']
    actual=call('read',{'path':'/workspace/pixel.png'})
    assert actual==expected['result'] and any(part['type']=='image' for part in actual['content'])
