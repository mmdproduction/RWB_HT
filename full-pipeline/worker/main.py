import logging
import os
import socket
import time
from uuid import uuid4

from shared.settings import Settings
from worker.client import ApiClient, Heartbeat
from worker.engine import Engine
from worker.qwen_monitor import QwenMonitor


def main():
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    settings=Settings.from_env()
    api=ApiClient(settings,os.getenv('WORKER_ID',socket.gethostname()+'-'+uuid4().hex[:8]))
    logging.info('Worker started; model=%s',settings.llm_model)
    with QwenMonitor(settings,api):
        while True:
            try:
                job=api.claim()
                if job:
                    logging.info('Run %s claimed',job['runId'])
                    with Heartbeat(api,job) as heartbeat:
                        status=Engine(settings,api,job,cancelled=heartbeat.cancelled).execute()
                    logging.info('Run %s: %s',job['runId'],status)
                else: time.sleep(2)
            except KeyboardInterrupt: return
            except Exception as error:
                # Never dump HTTP request headers/environment or credential-bearing exception URLs.
                logging.error('Worker loop error: %s; retry in 5s',type(error).__name__)
                time.sleep(5)


if __name__=='__main__': main()
