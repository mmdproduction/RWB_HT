from datetime import datetime,timezone,timedelta

import httpx

from shared.settings import Settings


def test_probe_verifies_exact_model_without_chat_request():
    from worker.qwen_monitor import probe
    def handler(request):
        assert request.url.path=='/v1/models' and request.method=='GET'
        assert request.headers['authorization']=='Bearer private-test-key'
        return httpx.Response(200,json={'data':[{'id':'qwen3.8-27b'}]})
    result=probe(Settings(llm_api_key='private-test-key'),transport=httpx.MockTransport(handler))
    assert result['status']=='available' and result['httpStatus']==200
    assert 'private-test-key' not in str(result) and 'llm_base_url' not in result


def test_probe_distinguishes_access_limit_protocol_and_model_errors():
    from worker.qwen_monitor import probe
    for response,expected in [
        (httpx.Response(401,text='private response'),'unauthorized'),
        (httpx.Response(429),'rate_limited'),(httpx.Response(503),'server_error'),
        (httpx.Response(200,json={'data':[{'id':'another-model'}]}),'model_missing'),
        (httpx.Response(200,text='<html>proxy</html>'),'protocol_error'),
    ]:
        value=probe(Settings(llm_api_key='test-key'),transport=httpx.MockTransport(lambda r:response))
        assert value['status']==expected and 'private response' not in str(value)


def test_cache_expires_success_instead_of_showing_stale_green():
    from shared.qwen_status import QwenStatusCache,QwenReport
    cache=QwenStatusCache('qwen3.8-27b')
    now=datetime(2026,10,30,tzinfo=timezone.utc)
    assert cache.snapshot(now)['status']=='unknown'
    cache.update(QwenReport(workerId='worker1',status='available',model='qwen3.8-27b',httpStatus=200,latencyMs=20),now)
    assert cache.snapshot(now+timedelta(seconds=10))['status']=='available'
    assert cache.snapshot(now+timedelta(seconds=46))['status']=='stale'
    cache.update(QwenReport(workerId='worker1',status='timeout',model='qwen3.8-27b'),now+timedelta(seconds=50))
    result=cache.snapshot(now+timedelta(seconds=51))
    assert result['status']=='timeout' and len(result['history'])==2 and result['lastAvailableAt']==now.isoformat()
