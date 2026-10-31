"""Observe Qwen from the worker's real network without chat completions."""
import logging
import threading
import time
from urllib.parse import urlsplit

import httpx


def probe(settings,transport=None):
    result={'status':'not_configured','model':settings.llm_model[:200],'httpStatus':None,'latencyMs':None}
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model: return result
    started=time.monotonic()
    try:
        parsed=urlsplit(settings.llm_base_url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            result['status']='invalid_config';return result
        with httpx.Client(timeout=httpx.Timeout(4,connect=3),trust_env=False,follow_redirects=False,transport=transport) as client:
            response=client.get(settings.llm_base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+settings.llm_api_key})
        code=response.status_code;result['httpStatus']=code
        if code in (401,403): result['status']='unauthorized'
        elif code==429: result['status']='rate_limited'
        elif code>=500: result['status']='server_error'
        elif code!=200: result['status']='endpoint_error'
        else:
            if len(response.content)>1_000_000: raise ValueError('Oversized models catalog')
            payload=response.json()
            data=payload.get('data') if isinstance(payload,dict) else None
            if not isinstance(data,list) or any(not isinstance(item,dict) or not isinstance(item.get('id'),str) for item in data):
                result['status']='protocol_error'
            else: result['status']='available' if any(item['id']==settings.llm_model for item in data) else 'model_missing'
    except httpx.TimeoutException: result['status']='timeout'
    except httpx.RequestError: result['status']='unreachable'
    except httpx.InvalidURL: result['status']='invalid_config'
    except ValueError: result['status']='protocol_error'
    finally: result['latencyMs']=min(60000,round((time.monotonic()-started)*1000))
    return result


class QwenMonitor:
    def __init__(self,settings,api):
        self.settings,self.api=settings,api
        self.stop=threading.Event()
        self.thread=threading.Thread(target=self.loop,name='qwen-connection-monitor',daemon=True)

    def loop(self):
        while not self.stop.is_set():
            try: self.api.qwen_status(probe(self.settings))
            except Exception as error:
                # Never include exceptions with credential-bearing URLs or response bodies.
                logging.warning('Qwen status report unavailable: %s',type(error).__name__)
            if self.stop.wait(15): return

    def __enter__(self):
        self.thread.start();return self

    def __exit__(self,*args):
        self.stop.set();self.thread.join(timeout=6)
