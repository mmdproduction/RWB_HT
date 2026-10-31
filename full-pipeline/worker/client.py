import threading
import time
from uuid import uuid4

import httpx


class ApiClient:
    def __init__(self,settings,worker_id):
        self.settings,self.worker_id=settings,worker_id
        self.http=httpx.Client(base_url=settings.api_url,headers={'X-Worker-Key':settings.worker_key},timeout=20,trust_env=False)

    def post(self,path,body):
        for attempt in range(3):
            try:
                response=self.http.post(path,json=body)
                if response.status_code>=500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json() if response.status_code!=204 else None
            except (httpx.RequestError,httpx.HTTPStatusError) as error:
                if isinstance(error,httpx.HTTPStatusError) and error.response.status_code<500: raise
                if attempt==2: raise
                time.sleep(attempt+1)

    def claim(self):
        return self.post('/internal/jobs/claim',{'workerId':self.worker_id,'requestId':str(uuid4())})

    def qwen_status(self,status):
        response=self.http.post('/internal/services/qwen',json={'workerId':self.worker_id,**status},timeout=5)
        response.raise_for_status()

    def lease(self,job):
        return {'workerId':self.worker_id,'leaseToken':job['leaseToken']}

    def progress(self,job,stage,attempt,status,message='',**extra):
        body={**self.lease(job),'eventId':str(uuid4()),'stageId':stage,'attempt':attempt,'status':status,'message':message,**extra}
        return self.post('/internal/runs/'+job['runId']+'/progress',body)

    def finish(self,job,status,message,app_url=None):
        return self.post('/internal/runs/'+job['runId']+'/finish',{**self.lease(job),'status':status,'message':message,'appUrl':app_url})


class Heartbeat:
    def __init__(self,api,job):
        self.api,self.job=api,job
        self.stop=threading.Event();self.lost=False
        self.cancelled=threading.Event()
        self.thread=threading.Thread(target=self.loop,daemon=True)

    def loop(self):
        while not self.stop.wait(self.api.settings.heartbeat_seconds):
            try:
                self.api.post('/internal/runs/'+self.job['runId']+'/heartbeat',self.api.lease(self.job))
            except httpx.HTTPStatusError as error:
                if error.response.status_code==409:
                    self.lost=True
                    self.cancelled.set()
                    return
            except httpx.HTTPError:
                pass  # API expiration, not the worker, decides lease validity.

    def __enter__(self):
        self.thread.start();return self

    def __exit__(self,*args):
        self.stop.set();self.thread.join(timeout=2)
