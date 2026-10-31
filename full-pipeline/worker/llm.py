import json
import re
import math
import random
import threading
import time
from email.utils import parsedate_to_datetime
from datetime import timezone

import httpx

from shared.settings import Settings


class ModelError(RuntimeError):
    pass


def parse_json(content):
    if not isinstance(content,str):
        raise ModelError('Модель вернула пустой ответ')
    content=content.rsplit('</think>',1)[-1].strip()
    if content.startswith('```'):
        content=re.sub(r'^```(?:json)?\s*','',content)
        content=re.sub(r'\s*```$','',content)
    try:
        result=json.loads(content)
    except (ValueError,TypeError) as error:
        raise ModelError('Ответ модели не является полным JSON') from error
    if not isinstance(result,dict):
        raise ModelError('Модель должна вернуть JSON object')
    return result


class ModelClient:
    def __init__(self,settings:Settings,transport=None,cancelled=None,on_retry=None):
        self.settings=settings
        self.client=httpx.Client(timeout=settings.llm_timeout,transport=transport,trust_env=False)
        self.last_usage=None
        self.attempts=[]
        self.cancelled=cancelled or threading.Event()
        self.on_retry=on_retry

    @staticmethod
    def retry_after(header):
        if not header: return None
        try:
            seconds=float(header)
            return max(0,seconds) if math.isfinite(seconds) else None
        except ValueError:
            try:
                date=parsedate_to_datetime(header)
                if date.tzinfo is None: date=date.replace(tzinfo=timezone.utc)
                return max(0,date.timestamp()-time.time())
            except (ValueError,TypeError,OverflowError): return None

    def ask(self,system,user):
        self.last_usage={'modelCalls':0,'inputTokens':None,'outputTokens':None,'retries':0}
        self.attempts=[]
        if not self.settings.llm_api_key:
            raise ModelError('LLM_API_KEY не настроен')
        retries=max(0,min(8,self.settings.llm_429_max_retries))
        budget=self.settings.llm_429_wait_seconds
        budget=max(0,min(600,budget)) if math.isfinite(budget) else 180
        started=time.monotonic()
        for index in range(retries+1):
            if self.cancelled.is_set(): raise ModelError('Ожидание Qwen отменено: worker lease утрачен')
            if index and time.monotonic()-started>=budget:
                raise ModelError(f'Qwen HTTP 429: окно ожидания {budget:g} с исчерпано; повторите запуск позже')
            self.last_usage['modelCalls']+=1
            if index: self.last_usage['retries']+=1
            attempt={'number':index+1,'httpStatus':None,'inputTokens':None,'outputTokens':None}
            self.attempts.append(attempt)
            request_started=time.monotonic()
            try:
                response=self.client.post(self.settings.llm_base_url+'/chat/completions',
                    headers={'Authorization':'Bearer '+self.settings.llm_api_key},json={
                    'model':self.settings.llm_model,'temperature':0.1,'max_tokens':self.settings.llm_max_tokens,
                    'chat_template_kwargs':{'enable_thinking':False},
                    'messages':[{'role':'system','content':system},{'role':'user','content':user}]})
                attempt['httpStatus']=response.status_code
                if response.status_code!=429:
                    response.raise_for_status()
                    payload=response.json()
                    usage=payload.get('usage') or {}
                    attempt.update(inputTokens=usage.get('prompt_tokens'),outputTokens=usage.get('completion_tokens'))
                    # A rejected response without usage must not be presented as known zero cost.
                    if index==0: self.last_usage.update(inputTokens=attempt['inputTokens'],outputTokens=attempt['outputTokens'])
                    choice=payload['choices'][0]
                    if choice.get('finish_reason')=='length':
                        raise ModelError('Ответ модели обрезан лимитом токенов; уменьшите требования или увеличьте LLM_MAX_TOKENS')
                    return parse_json(choice['message']['content']),self.last_usage.copy()
            except httpx.HTTPStatusError as error:
                raise ModelError(f'Qwen HTTP {error.response.status_code}; проверьте доступ и ключ') from None
            except httpx.TimeoutException:
                # A timed-out request may still run server-side: do not duplicate it automatically.
                raise ModelError(f'Qwen не завершил HTTP-ответ за {self.settings.llm_timeout}s; увеличьте LLM_TIMEOUT или сократите требования') from None
            except httpx.RequestError:
                raise ModelError('Qwen недоступен: проверьте SSH-туннель и LLM_BASE_URL') from None
            except (KeyError,ValueError,IndexError,TypeError) as error:
                raise ModelError('Некорректный протокол ответа Qwen') from error
            finally: attempt['durationSeconds']=round(time.monotonic()-request_started,3)
            if index==retries:
                raise ModelError(f'Qwen HTTP 429: сервер отклонил все {index+1} попыток; лимит автоматических повторов исчерпан')
            delay=self.retry_after(response.headers.get('Retry-After'))
            delay=max(1,delay) if delay is not None else min(60,10*2**index)+random.uniform(0,2)
            if delay>budget-(time.monotonic()-started):
                raise ModelError(f'Qwen HTTP 429: ожидание следующего повтора превышает лимит {budget:g} с; повторите запуск позже')
            attempt['retryDelaySeconds']=round(delay,3)
            if self.on_retry: self.on_retry(index+2,retries+1,delay)
            if delay>budget-(time.monotonic()-started):
                raise ModelError(f'Qwen HTTP 429: окно ожидания {budget:g} с исчерпано; повторите запуск позже')
            if self.cancelled.wait(delay): raise ModelError('Ожидание Qwen отменено: worker lease утрачен')
