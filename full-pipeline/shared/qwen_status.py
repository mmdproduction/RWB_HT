"""Sanitized worker connection reports and bounded, expiring public status."""
from collections import deque
from datetime import datetime,timezone
from threading import Lock
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field

MESSAGES={
    'available':'API отвечает, выбранная модель присутствует в каталоге.',
    'not_configured':'В worker не настроены адрес API, ключ или модель Qwen.',
    'invalid_config':'Некорректный адрес API Qwen. Проверьте настройки worker.',
    'unauthorized':'API отклонил доступ. Проверьте ключ и права.',
    'rate_limited':'API ограничивает запросы. Повторная проверка выполнится автоматически.',
    'server_error':'Сервер Qwen вернул ошибку.',
    'endpoint_error':'Адрес API не обслуживает ожидаемый запрос. Проверьте Base URL.',
    'model_missing':'API отвечает, но выбранной модели нет в каталоге.',
    'protocol_error':'API вернул неожиданный ответ вместо каталога моделей.',
    'timeout':'Qwen не ответил за отведенное время.',
    'unreachable':'Нет соединения с Qwen. Проверьте SSH-туннель и доступность сети.',
    'unknown':'Ожидаем первый отчет от worker.',
    'stale':'Нет свежего отчета от worker. Текущее соединение с Qwen неизвестно.',
    'config_mismatch':'Worker и API настроены на разные модели Qwen.',
}


class QwenReport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    workerId: str = Field(min_length=1,max_length=100)
    status: Literal['available','not_configured','invalid_config','unauthorized','rate_limited','server_error',
        'endpoint_error','model_missing','protocol_error','timeout','unreachable']
    model: str = Field(max_length=200)
    httpStatus: int | None = Field(default=None,ge=100,le=599)
    latencyMs: int | None = Field(default=None,ge=0,le=60000)


class QwenStatusCache:
    def __init__(self,model):
        self.model=model
        self.lock=Lock()
        self.report=None;self.received=None;self.last_available=None
        self.history=deque(maxlen=20)
        self.state='unknown'

    def update(self,report:QwenReport,now=None):
        now=now or datetime.now(timezone.utc)
        state=report.status if report.model==self.model else 'config_mismatch'
        with self.lock:
            if state!=self.state:
                self.history.append({'status':state,'message':MESSAGES[state],'checkedAt':now.isoformat()})
            self.report=report;self.received=now;self.state=state
            if state=='available': self.last_available=now

    def snapshot(self,now=None):
        now=now or datetime.now(timezone.utc)
        with self.lock:
            stale=self.received is not None and (now-self.received).total_seconds()>45
            status='stale' if stale else self.state
            return {'status':status,'message':MESSAGES[status],
                'model':self.report.model if self.report else self.model,
                'httpStatus':self.report.httpStatus if self.report else None,
                'latencyMs':self.report.latencyMs if self.report else None,
                'checkedAt':self.received.isoformat() if self.received else None,
                'lastAvailableAt':self.last_available.isoformat() if self.last_available else None,
                'staleAfterSeconds':45,'checkIntervalSeconds':15,
                'probe':'models_catalog','generationVerified':False,
                'history':list(reversed(self.history))}
