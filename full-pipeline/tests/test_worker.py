import json
from pathlib import Path
import sys

import httpx
import pytest

from shared.settings import Settings
from worker.llm import ModelClient, ModelError, parse_json
from worker.tools import apply_patch, run_command, ToolError


def test_reasoning_and_fenced_json():
    assert parse_json('reasoning\n</think>\n```json\n{"ready":true}\n```') == {'ready': True}
    with pytest.raises(ModelError):
        parse_json('not JSON')
    with pytest.raises(ModelError):
        parse_json('{"x":1} trailing')


def test_real_protocol_usage_and_model_identity():
    calls = []
    def handler(request):
        calls.append(json.loads(request.content))
        assert request.headers['authorization'] == 'Bearer test-key'
        return httpx.Response(200, json={'choices':[{'message':{'content':'</think>{"ok":true}'}, 'finish_reason':'stop'}], 'usage':{'prompt_tokens':14,'completion_tokens':7}})
    client = ModelClient(Settings(llm_api_key='test-key'), transport=httpx.MockTransport(handler))
    result, usage = client.ask('system', 'user')
    assert result == {'ok': True}
    assert usage == {'modelCalls':1,'inputTokens':14,'outputTokens':7,'retries':0}
    assert calls[0]['model'] == 'qwen3.8-27b'
    assert calls[0]['chat_template_kwargs']=={'enable_thinking':False}


@pytest.mark.parametrize('response', [httpx.Response(503,text='secret'), httpx.Response(200,json={'choices':[{'message':{'content':'{}'},'finish_reason':'length'}]})])
def test_model_failure_is_not_success(response):
    client=ModelClient(Settings(llm_api_key='test-key'),transport=httpx.MockTransport(lambda r:response))
    with pytest.raises(ModelError): client.ask('system','user')


def test_patch_is_atomic_and_confined(tmp_path):
    good={'path':'backend/Generated/Extensions.cs','content':'public static class GeneratedExtensions { public static void Map(WebApplication app) {} }'}
    with pytest.raises(ValueError): apply_patch(tmp_path,{'files':[good,{'path':'compose.yaml','content':'evil'}]})
    assert not list(tmp_path.rglob('*.cs'))
    for path in ['backend/Generated/../../Program.cs','backend/Generated/bad.txt','frontend/src/app/generated/../app.ts']:
        with pytest.raises(ValueError): apply_patch(tmp_path,{'files':[{'path':path,'content':'x'}]})
    apply_patch(tmp_path,{'files':[good]})
    assert (tmp_path/good['path']).is_file()


def test_qwen_429_waits_then_recovers_and_records_actual_http_attempts(monkeypatch):
    replies=iter([httpx.Response(429,headers={'Retry-After':'7'}),httpx.Response(429,headers={'Retry-After':'1'}),
        httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':14,'completion_tokens':7}})])
    events=[]
    client=ModelClient(Settings(llm_api_key='test-key',llm_429_max_retries=2),
        transport=httpx.MockTransport(lambda r:next(replies)),on_retry=lambda *args:events.append(args))
    waits=[];monkeypatch.setattr(client.cancelled,'wait',lambda seconds:waits.append(seconds) or False)
    value,usage=client.ask('system','user')
    assert value=={'ok':True} and waits==[7,1] and len(events)==2
    assert usage=={'modelCalls':3,'inputTokens':None,'outputTokens':None,'retries':2}
    assert [attempt['httpStatus'] for attempt in client.attempts]==[429,429,200]
    assert client.attempts[-1]['inputTokens']==14


def test_qwen_429_retries_are_bounded_and_long_retry_after_is_not_ignored(monkeypatch):
    for retry_after,expected_calls in [(None,3),('10000',1)]:
        def handler(request): return httpx.Response(429,headers={'Retry-After':retry_after} if retry_after else {})
        client=ModelClient(Settings(llm_api_key='test-key',llm_429_max_retries=2),transport=httpx.MockTransport(handler))
        monkeypatch.setattr(client.cancelled,'wait',lambda seconds:False)
        with pytest.raises(ModelError,match='429'): client.ask('system','user')
        assert client.last_usage['modelCalls']==expected_calls


def test_qwen_busy_wait_is_cancellable_without_another_request(monkeypatch):
    client=ModelClient(Settings(llm_api_key='test-key'),transport=httpx.MockTransport(lambda r:httpx.Response(429)))
    monkeypatch.setattr(client.cancelled,'wait',lambda seconds:True)
    with pytest.raises(ModelError,match='отменено'): client.ask('system','user')
    assert client.last_usage['modelCalls']==1


def test_subprocess_timeout_and_secrets(tmp_path,monkeypatch):
    monkeypatch.setenv('LLM_API_KEY','never-in-child')
    result=run_command([sys.executable,'-c','import os;print(os.getenv("LLM_API_KEY","absent"))'],tmp_path,5)
    assert result['returnCode']==0 and result['output'].strip()=='absent'
    with pytest.raises(ToolError,match='timeout'):
        run_command([sys.executable,'-c','import time;time.sleep(5)'],tmp_path,0.05)


def test_no_shell_expansion(tmp_path):
    result=run_command([sys.executable,'-c','import sys;print(sys.argv[1])','$(touch hacked)'],tmp_path,5)
    assert '$(touch hacked)' in result['output'] and not (tmp_path/'hacked').exists()


def fixture_spec():
    return {'schemaVersion':1,'title':'Tickets','slug':'tickets','summary':'Ticket register','roles':['admin','user'],
        'requirements':[{'id':'R1','description':'Track tickets','acceptance':['Record persisted']}],
        'entities':[{'name':'Ticket','fields':[{'name':'title','type':'string','required':True}]}]}


class RecordingApi:
    def __init__(self): self.events=[];self.finished=None
    def progress(self,job,stage,attempt,status,message='',**extra):
        self.events.append((stage,status,extra))
    def finish(self,job,status,message,app_url=None): self.finished=(status,message,app_url)


def test_engine_external_failure_is_blocked_not_fake_success(tmp_path):
    from worker.engine import Engine
    class Offline:
        last_usage={'modelCalls':1,'inputTokens':None,'outputTokens':None,'retries':0}
        def ask(self,*args): raise ModelError('Qwen недоступен')
    api=RecordingApi()
    engine=Engine(Settings(artifact_root=tmp_path),api,{'runId':'00000000-0000-0000-0000-000000000001','requirements':'example'},model=Offline())
    assert engine.execute()=='blocked'
    assert api.finished[0]=='blocked' and api.finished[2] is None
    assert ('test','not_run') in [(s,status) for s,status,_ in api.events]
    assert not any(s=='deploy' and status=='passed' for s,status,_ in api.events)
    assert (engine.root/'reports/verification.md').exists()


def test_engine_bounded_repair_and_frozen_acceptance(tmp_path):
    from worker.engine import Engine
    patch={'files':[
        {'path':'backend/Generated/Extensions.cs','content':'public static class GeneratedExtensions { public static void Map(WebApplication app) {} }'},
        {'path':'frontend/src/app/generated/generated-panel.ts','content':'export class GeneratedPanel {}'}],
        'acceptanceTests':[{'requirementIds':['R1'],'name':'summary','role':'admin','steps':[{'method':'GET','path':'/api/generated/summary','status':200,'contains':{'total':0}}]}]}
    class FixtureModel:
        last_usage=None
        def __init__(self): self.calls=0
        def ask(self,*args):
            self.calls+=1
            import copy
            value=fixture_spec() if self.calls==1 else copy.deepcopy(patch)
            if self.calls>2:
                value['files'][0]['content']+='\n// candidate '+str(self.calls)
            return value,{'modelCalls':1,'inputTokens':1,'outputTokens':1,'retries':0}
    def failed_build(args,cwd,timeout):
        return {'returnCode':1 if 'build' in args else 0,'output':'compiler failure','command':args,'durationSeconds':0}
    api=RecordingApi();model=FixtureModel()
    engine=Engine(Settings(artifact_root=tmp_path),api,{'runId':'00000000-0000-0000-0000-000000000002','requirements':'example'},model=model,runner=failed_build)
    assert engine.execute()=='failed'
    assert engine.repairs==2 and model.calls==4
    assert (engine.project/'scripts/domain-acceptance.json').read_text().count('summary')==2
    assert len([r for r in engine.results if r['name'] in {'build','repair-candidate-build'}])==3
    assert engine.repair_counts=={'build':2,'test':0}
    assert (engine.project/'backend/Generated/Extensions.cs').read_text()==patch['files'][0]['content']
    transactions=list((engine.root/'reports/repair-transactions').glob('*.json'))
    assert len(transactions)==2
    assert all(json.loads(path.read_text())['status']=='rejected_and_restored' for path in transactions)


def test_domain_acceptance_cannot_contact_external_host():
    from shared.models import AppSpec
    from worker.engine import validate_acceptance
    value=[{'requirementIds':['R1'],'name':'external','role':'admin','steps':[{'method':'GET','path':'http://example.com','status':200}]}]
    with pytest.raises(ValueError): validate_acceptance(value,AppSpec.model_validate(fixture_spec()))


def test_public_acceptance_identity_is_bound_without_weakening_assertions():
    from shared.models import AppSpec
    from worker.engine import bind_acceptance_roles,validate_acceptance
    spec=AppSpec.model_validate({**fixture_spec(),'requiresLogin':False})
    original=[{'name':'business action','role':'admin','requirementIds':['R1'],
        'steps':[{'method':'POST','path':'/api/generated/pay','body':{'amount':100},'status':200,'contains':{'result':100}}]}]
    bound,audit=bind_acceptance_roles(original,spec)
    assert bound[0]['role']=='user' and original[0]['role']=='admin'
    assert bound[0]['steps']==original[0]['steps'] and audit[0]['executionRole']=='user'
    assert validate_acceptance(bound,spec)==bound
    with pytest.raises(ValueError,match='ролью интерфейса'): validate_acceptance(original,spec)


def test_audit_json_survives_docker_and_npm_notices():
    from worker.tools import command_json
    output='Pulling node image...\n{"metadata":{"vulnerabilities":{"high":8}},"vulnerabilities":{}}\nnpm notice update available'
    assert command_json(output,{'metadata','vulnerabilities'})['metadata']['vulnerabilities']['high']==8
    with pytest.raises(ValueError): command_json('network failed',{'metadata'})


def test_cleanup_runs_when_api_is_unavailable(tmp_path):
    from worker.engine import Engine
    class BrokenApi(RecordingApi):
        def progress(self,*args,**kwargs): raise RuntimeError('API unavailable')
    commands=[]
    def runner(args,cwd,timeout):
        commands.append(args)
        return {'returnCode':0,'output':'cleaned','command':args,'durationSeconds':0}
    engine=Engine(Settings(artifact_root=tmp_path),BrokenApi(),{'runId':'00000000-0000-0000-0000-000000000004','requirements':'example'},runner=runner)
    # Simulate an app directory already created when a reporting request fails.
    original=engine.event
    def event(stage,*args,**kwargs):
        if stage=='analysis':
            engine.project.mkdir(exist_ok=True)
        return original(stage,*args,**kwargs)
    engine.event=event
    assert engine.execute()=='failed'
    assert any('down' in command for command in commands)


def test_successful_build_log_with_error_words_is_not_blocked(tmp_path):
    from worker.engine import Engine
    # Real successful BuildKit output contained 502 inside this image digest.
    output=('#43 FROM docker.io/library/python:3.12-slim@sha256:'
        'aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159\n'
        'build tool documentation: TLS handshake timeout\nbackend Built checks Built')
    def runner(args,cwd,timeout):
        return {'returnCode':0,'output':output,'command':args,'durationSeconds':0}
    engine=Engine(Settings(artifact_root=tmp_path),RecordingApi(),
        {'runId':'00000000-0000-0000-0000-000000000014','requirements':'example'},runner=runner)
    engine.current='build'
    engine.build()
    assert engine.built_hash is not None and engine.repairs==0 and len(engine.results)==1


def test_registry_error_classification_ignores_successful_digest():
    from worker.recovery import infrastructure_failure,transient_network_failure
    digest='docker.io/library/python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159'
    assert not transient_network_failure(digest) and not infrastructure_failure(digest)
    assert transient_network_failure('unexpected status from HEAD request to https://registry-1.docker.io/v2/library/python/manifests/3.12-slim: 503 Service Unavailable')
    assert transient_network_failure('net/http: TLS handshake timeout')


def test_build_recovers_registry_timeout_without_model_or_source_changes(tmp_path,monkeypatch):
    from worker.engine import Engine
    class NoModel:
        def ask(self,*args): raise AssertionError('Infrastructure must not invoke Qwen')
    outputs=iter([(1,'failed to resolve source metadata: net/http: TLS handshake timeout'),
                  (1,'dial tcp: i/o timeout'),(0,'built')])
    def runner(args,cwd,timeout):
        code,output=next(outputs)
        return {'returnCode':code,'output':output,'command':args,'durationSeconds':0}
    engine=Engine(Settings(artifact_root=tmp_path),RecordingApi(),
        {'runId':'00000000-0000-0000-0000-000000000011','requirements':'example'},model=NoModel(),runner=runner)
    engine.current='build'
    source=engine.project/'backend/Generated/Extensions.cs';source.parent.mkdir(parents=True)
    source.write_text('unchanged application')
    pauses=[]
    monkeypatch.setattr(engine.cancelled,'wait',lambda seconds:pauses.append(seconds) or False)
    engine.build()
    assert engine.built_hash is not None and source.read_text()=='unchanged application'
    assert engine.repairs==0 and engine.attempt==1
    assert pauses==[5,15] and len(engine.results)==3


@pytest.mark.parametrize('output,count',[
    ('failed to resolve source metadata: net/http: TLS handshake timeout',3),
    ('failed to resolve source metadata: pull access denied',1),
])
def test_registry_retry_is_bounded_and_permanent_failure_stops(tmp_path,monkeypatch,output,count):
    from worker.engine import Engine,Blocked
    def runner(args,cwd,timeout):
        return {'returnCode':1,'output':output,'command':args,'durationSeconds':0}
    engine=Engine(Settings(artifact_root=tmp_path),RecordingApi(),
        {'runId':'00000000-0000-0000-0000-000000000012','requirements':'example'},runner=runner)
    engine.current='build'
    monkeypatch.setattr(engine.cancelled,'wait',lambda seconds:False)
    with pytest.raises(Blocked): engine.build()
    assert len(engine.results)==count and engine.repairs==0 and engine.built_hash is None


def test_compiler_error_does_not_trigger_network_retry(tmp_path):
    from worker.engine import Engine
    def runner(args,cwd,timeout):
        return {'returnCode':1,'output':'error CS1002: ; expected','command':args,'durationSeconds':0}
    engine=Engine(Settings(artifact_root=tmp_path),RecordingApi(),
        {'runId':'00000000-0000-0000-0000-000000000013','requirements':'example'},runner=runner)
    assert engine.build_command('build',engine.compose+['build'])['returnCode']==1
    assert len(engine.results)==1


def test_repair_scope_and_restore_delete_rejected_files(tmp_path):
    from worker.recovery import snapshot_sources,restore_sources,check_scope,source_hash
    folder=tmp_path/'backend/Generated';folder.mkdir(parents=True)
    (folder/'Extensions.cs').write_text('original')
    before=source_hash(tmp_path);snapshot=snapshot_sources(tmp_path)
    (folder/'Extensions.cs').write_text('bad candidate')
    (folder/'Wrong.cs').write_text('new rejected file')
    restore_sources(tmp_path,snapshot)
    assert source_hash(tmp_path)==before and not (folder/'Wrong.cs').exists()
    with pytest.raises(ValueError):
        check_scope({'files':[{'path':'backend/Generated/Extensions.cs','content':'x'}]},{'frontend'})


def test_release_rejects_modified_sources_and_frozen_checks(tmp_path):
    from worker.engine import Engine
    from worker.recovery import acceptance_hash,source_hash
    from worker.tools import ToolError
    engine=Engine(Settings(artifact_root=tmp_path),RecordingApi(),{'runId':'00000000-0000-0000-0000-000000000010','requirements':'example'})
    scripts=engine.project/'scripts';scripts.mkdir(parents=True)
    for name in ['tests.py','domain_checks.py','domain-acceptance.json','app-spec.json','Dockerfile','integration_checks.py']:
        (scripts/name).write_text('fixed')
    (engine.project/'docs').mkdir()
    (engine.project/'docs/mock-integrations.json').write_text('fixed')
    code=engine.project/'backend/Generated/Extensions.cs';code.parent.mkdir(parents=True);code.write_text('code')
    engine.frozen_checks=acceptance_hash(engine.project)
    engine.built_hash=engine.tested_hash=engine.deployed_hash=source_hash(engine.project)
    engine.app_url='http://127.0.0.1:12345'
    code.write_text('unverified change')
    with pytest.raises(ToolError): engine.release_evidence()
    (scripts/'domain-acceptance.json').write_text('weakened')
    with pytest.raises(ToolError,match='проверки изменились'): engine.assert_checks()
