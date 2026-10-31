import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient

KEY = 'test-worker-key'
HEADERS = {'X-Worker-Key': KEY}


@pytest.fixture
def api(tmp_path):
    assert importlib.util.find_spec('platform_api.main') is not None, 'Persistent worker protocol is not implemented'
    from platform_api.main import create_app
    from shared.settings import Settings
    url = os.getenv('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to a dedicated PostgreSQL test database')
    settings = Settings(database_url=url, worker_key=KEY, artifact_root=tmp_path, lease_seconds=3)
    with TestClient(create_app(settings)) as client:
        import psycopg
        with psycopg.connect(url) as conn:
            conn.execute('TRUNCATE pipeline_runs, pipeline_claim_requests CASCADE')
        yield client, settings


def create(client):
    response = client.post('/api/runs', json={'requirements': 'Build a service request tracker'})
    assert response.status_code == 202
    return response.json()['runId']


def claim(client):
    response = client.post('/internal/jobs/claim', json={'workerId': 'worker-1'}, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def lease(job):
    return {'workerId': job['workerId'], 'leaseToken': job['leaseToken']}


def test_create_validation_and_persistence(api):
    client, _ = api
    assert client.post('/api/runs', json={'requirements': '   '}).status_code == 422
    run_id = create(client)
    card = client.get('/api/runs/' + run_id).json()
    assert card['status'] == 'queued'
    assert card['requirements'] == 'Build a service request tracker'
    assert client.get('/api/runs').json()[0]['runId'] == run_id
    assert client.get('/api/runs/not-a-uuid').status_code == 404


def test_qwen_status_reports_require_worker_key_and_hide_credentials(api):
    client,_=api
    report={'workerId':'worker-1','status':'available','model':'qwen3.8-27b','httpStatus':200,'latencyMs':12}
    assert client.post('/internal/services/qwen',json=report).status_code==401
    assert client.post('/internal/services/qwen',json=report,headers=HEADERS).status_code==204
    response=client.get('/api/qwen/status')
    value=response.json()
    assert response.headers['cache-control']=='no-store'
    assert value['status']=='available' and value['latencyMs']==12 and value['generationVerified'] is False
    assert KEY not in response.text and 'baseUrl' not in value and 'workerId' not in value


def test_worker_authentication_and_claim_once(api):
    client, _ = api
    run_id = create(client)
    assert client.post('/internal/jobs/claim', json={'workerId': 'worker-1'}).status_code == 401
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.post('/internal/jobs/claim', json={'workerId': 'worker-1'}, headers=HEADERS), range(2)))
    assert sorted(r.status_code for r in results) == [200, 204]
    job = next(r.json() for r in results if r.status_code == 200)
    assert job['runId'] == run_id and job['status'] == 'running'
    assert job['leaseToken']


def test_claim_retry_returns_same_lease_without_abandoning_job(api):
    client,_=api
    first,second=create(client),create(client)
    body={'workerId':'worker-1','requestId':str(uuid.uuid4())}
    a=client.post('/internal/jobs/claim',json=body,headers=HEADERS)
    b=client.post('/internal/jobs/claim',json=body,headers=HEADERS)
    assert a.status_code==b.status_code==200 and a.json()==b.json()
    assert a.json()['runId']==first
    assert client.get('/api/runs/'+second).json()['status']=='queued'
    assert client.post('/internal/jobs/claim',json={**body,'workerId':'other'},headers=HEADERS).status_code==409


def test_progress_is_idempotent_and_has_cursor(api):
    client, _ = api
    create(client); job = claim(client)
    body = {**lease(job), 'eventId': str(uuid.uuid4()), 'stageId': 'analysis', 'attempt': 1,
            'status': 'passed', 'message': 'analysis completed', 'logs': ['one line'],
            'metrics': {'modelCalls': 1, 'inputTokens': 11, 'outputTokens': 8}}
    path = f"/internal/runs/{job['runId']}/progress"
    assert client.post(path, json=body, headers=HEADERS).status_code == 200
    assert client.post(path, json=body, headers=HEADERS).status_code == 200
    card = client.get('/api/runs/' + job['runId']).json()
    assert card['metrics']['modelCalls'] == 1
    assert card['metrics']['inputTokens'] == 11
    assert card['stages'][0]['status'] == 'passed'
    log = client.get(f"/api/runs/{job['runId']}/logs").json()
    assert len(log['items']) == 1
    assert client.get(f"/api/runs/{job['runId']}/logs?after={log['nextCursor']}").json()['items'] == []
    changed = {**body, 'message': 'changed payload'}
    assert client.post(path, json=changed, headers=HEADERS).status_code == 409


def test_wrong_lease_and_terminal_state_are_rejected(api):
    client, _ = api
    run_id = create(client); job = claim(client)
    path = f'/internal/runs/{run_id}/finish'
    bad = {**lease(job), 'leaseToken': str(uuid.uuid4()), 'status': 'failed'}
    assert client.post(path, json=bad, headers=HEADERS).status_code == 409
    good = {**lease(job), 'status': 'failed', 'message': 'actual compiler failure'}
    assert client.post(path, json=good, headers=HEADERS).status_code == 200
    assert client.post(path, json=good, headers=HEADERS).status_code == 200
    assert client.post(path, json={**good, 'status': 'succeeded'}, headers=HEADERS).status_code == 409
    assert client.get('/api/runs/' + run_id).json()['message'] == 'actual compiler failure'


def test_success_requires_real_stage_results(api):
    client, _ = api
    run_id = create(client); job = claim(client)
    response = client.post(f'/internal/runs/{run_id}/finish', json={**lease(job), 'status': 'succeeded'}, headers=HEADERS)
    assert response.status_code == 409


def test_expired_worker_is_interrupted(api):
    client, settings = api
    import psycopg
    run_id = create(client); job = claim(client)
    with psycopg.connect(settings.database_url) as conn:
        conn.execute("UPDATE pipeline_runs SET heartbeat_at=now()-interval '10 minutes' WHERE id=%s", (uuid.UUID(run_id),))
    assert client.get('/api/runs/' + run_id).json()['status'] == 'interrupted'
    assert client.post(f'/internal/runs/{run_id}/heartbeat', json=lease(job), headers=HEADERS).status_code == 409


def test_artifacts_and_secret_boundaries(api):
    client, settings = api
    run_id = create(client); job = claim(client)
    folder = settings.artifact_root / run_id / 'docs'; folder.mkdir(parents=True)
    (folder / 'report.md').write_text('Verified report')
    event = {**lease(job), 'eventId': str(uuid.uuid4()), 'stageId': 'documentation', 'attempt': 1,
             'status': 'passed', 'artifacts': [{'name': 'Report', 'kind': 'document', 'path': 'docs/report.md'}],
             'logs': ['internal key: ' + KEY]}
    assert client.post(f'/internal/runs/{run_id}/progress', json=event, headers=HEADERS).status_code == 200
    artifacts = client.get(f'/api/runs/{run_id}/artifacts').json()
    assert len(artifacts) == 1
    assert client.get(artifacts[0]['url']).text == 'Verified report'
    assert client.get(f'/api/runs/{run_id}/download').status_code == 200
    assert KEY not in client.get(f'/api/runs/{run_id}/logs').text
    event['eventId'] = str(uuid.uuid4()); event['artifacts'][0]['path'] = '../outside.env'
    assert client.post(f'/internal/runs/{run_id}/progress', json=event, headers=HEADERS).status_code in (400, 422)


def test_failing_stage_cannot_be_reported_as_success(api):
    client, _ = api
    run_id = create(client); job = claim(client)
    event = {**lease(job), 'eventId': str(uuid.uuid4()), 'stageId': 'build', 'attempt': 1, 'status': 'failed', 'message': 'compile error'}
    assert client.post(f'/internal/runs/{run_id}/progress', json=event, headers=HEADERS).status_code == 200
    assert client.post(f'/internal/runs/{run_id}/finish', json={**lease(job), 'status': 'succeeded'}, headers=HEADERS).status_code == 409
