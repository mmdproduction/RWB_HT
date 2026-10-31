from contextlib import asynccontextmanager
import hmac
import io
from typing import Literal
from uuid import UUID
import zipfile
from urllib.parse import quote

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from platform_api.store import Store, StoreError, identifier
from shared.models import STAGES, STACK, safe_path
from shared.settings import Settings
from shared.files import list_files, public_file, EXCLUDED_DIRECTORIES, language
from shared.models import redact
from shared.qwen_status import QwenReport,QwenStatusCache


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class CreateRun(Input):
    requirements: str = Field(min_length=1, max_length=100000)

    @field_validator('requirements')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Требования не должны быть пустыми')
        return value


class WorkerIdentity(Input):
    workerId: str = Field(min_length=1, max_length=100)


class Claim(WorkerIdentity):
    requestId: UUID | None = None


class Lease(WorkerIdentity):
    leaseToken: UUID


class Artifact(Input):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=50)
    path: str = Field(min_length=1, max_length=500)


class Delta(Input):
    modelCalls: int = Field(default=0, ge=0, le=20)
    inputTokens: int | None = Field(default=None, ge=0)
    outputTokens: int | None = Field(default=None, ge=0)
    retries: int = Field(default=0, ge=0, le=20)


class Progress(Lease):
    eventId: UUID
    stageId: str
    attempt: int = Field(ge=1, le=3)
    status: Literal['pending', 'running', 'passed', 'failed', 'blocked', 'not_run']
    message: str = Field(default='', max_length=20000)
    logs: list[str] = Field(default_factory=list, max_length=30)
    artifacts: list[Artifact] = Field(default_factory=list, max_length=30)
    metrics: Delta | None = None

    @field_validator('stageId')
    @classmethod
    def known_stage(cls, value):
        if value not in STAGES:
            raise ValueError('Неизвестная стадия')
        return value

    @field_validator('logs')
    @classmethod
    def bounded_logs(cls, value):
        if any(len(line) > 20000 for line in value):
            raise ValueError('Запись лога слишком велика')
        return value


class Finish(Lease):
    status: Literal['succeeded', 'failed', 'blocked']
    message: str = Field(default='', max_length=20000)
    appUrl: HttpUrl | None = None
    repositoryUrl: HttpUrl | None = None


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    store = Store(settings)
    qwen_status=QwenStatusCache(settings.llm_model)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title='RUSSTECH AI Pipeline', version='1.0.0', lifespan=lifespan)
    app.state.store, app.state.settings = store, settings
    app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in settings.cors_origins.split(',')],
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    @app.exception_handler(StoreError)
    async def store_error(request, error):
        return JSONResponse({'detail': error.message}, status_code=error.status)

    @app.exception_handler(psycopg.Error)
    async def database_error(request, error):
        return JSONResponse({'detail': 'Ошибка PostgreSQL; проверьте готовность сервиса и миграции'}, status_code=503)

    def worker_key(x_worker_key: str | None = Header(default=None)):
        if not settings.worker_key:
            raise HTTPException(503, 'WORKER_KEY не настроен')
        if not x_worker_key or not hmac.compare_digest(x_worker_key, settings.worker_key):
            raise HTTPException(401, 'Неверный ключ исполнителя')

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/ready')
    def ready():
        with store.connection() as conn:
            conn.execute('SELECT 1')
        return {'status': 'ready'}

    @app.get('/api/config')
    def config():
        return {'stack': STACK, 'model': settings.llm_model, 'modelConfigured': bool(settings.llm_api_key and settings.llm_base_url),
                'workerConfigured': bool(settings.worker_key), 'stages': list(STAGES)}

    @app.get('/api/qwen/status')
    def qwen_connection(response:Response):
        response.headers['Cache-Control']='no-store'
        return qwen_status.snapshot()

    @app.post('/internal/services/qwen',dependencies=[Depends(worker_key)],status_code=204)
    def qwen_report(body:QwenReport):
        # Only model identity and bounded counters enter the public cache, never URLs or keys.
        body=body.model_copy(update={'model':redact(body.model,settings.secrets)})
        qwen_status.update(body)
        return Response(status_code=204)

    @app.post('/api/runs', status_code=202)
    def create(body: CreateRun):
        return store.create(body.requirements)

    @app.get('/api/runs')
    def list_runs():
        return store.list()

    @app.get('/api/runs/{run_id}')
    def get_run(run_id: str):
        return store.get(run_id)

    @app.get('/api/runs/{run_id}/logs')
    def logs(run_id: str, after: int = Query(default=0, ge=0)):
        return store.logs(run_id, after)

    @app.get('/api/runs/{run_id}/artifacts')
    def artifacts(run_id: str):
        return store.artifacts(run_id)

    def run_root(run_id):
        store.get(run_id)
        return settings.artifact_root / str(identifier(run_id))

    @app.get('/api/runs/{run_id}/files')
    def files(run_id: str):
        root=run_root(run_id)
        try: items=list_files(root)
        except ValueError as error: raise HTTPException(413,str(error)) from None
        prefix=f'/api/runs/{identifier(run_id)}/files/'
        for item in items:
            suffix='?path='+quote(item['path'],safe='')
            item['contentUrl']=prefix+'content'+suffix if item['viewable'] else None
            item['downloadUrl']=prefix+'download'+suffix if not item['restricted'] else None
        return {'items':items,'count':len(items),'excludedDirectories':sorted(EXCLUDED_DIRECTORIES)}

    def requested_file(run_id,relative):
        try: return public_file(run_root(run_id),relative)
        except PermissionError as error: raise HTTPException(403,str(error)) from None
        except ValueError as error: raise HTTPException(400,str(error)) from None
        except FileNotFoundError: raise HTTPException(404,'Файл не найден') from None

    @app.get('/api/runs/{run_id}/files/content')
    def file_content(run_id: str,path: str=Query(min_length=1,max_length=1500)):
        source=requested_file(run_id,path)
        with source.open('rb') as file: raw=file.read(2_000_001)
        if b'\0' in raw: raise HTTPException(415,'Это двоичный файл; используйте скачивание')
        content=redact(raw[:2_000_000].decode('utf-8',errors='replace'),settings.secrets)
        return {'path':path,'content':content,'language':language(source),'size':source.stat().st_size,'truncated':len(raw)>2_000_000}

    @app.get('/api/runs/{run_id}/files/download')
    def download_file(run_id: str,path: str=Query(min_length=1,max_length=1500)):
        source=requested_file(run_id,path)
        return FileResponse(source,filename=source.name)

    @app.get('/api/runs/{run_id}/artifacts/{artifact_id}')
    def artifact(run_id: str, artifact_id: str):
        records = store.artifacts(run_id)
        record = next((r for r in records if r['artifactId'] == artifact_id), None)
        if record is None:
            raise HTTPException(404, 'Артефакт не найден')
        try:
            path = public_file(settings.artifact_root / str(identifier(run_id)), record['path'])
        except (ValueError,PermissionError,FileNotFoundError):
            raise HTTPException(404, 'Артефакт недоступен') from None
        if not path.is_file() or path.name == '.env':
            raise HTTPException(404, 'Артефакт недоступен')
        return FileResponse(path, filename=path.name)

    @app.get('/api/runs/{run_id}/download')
    def download(run_id: str):
        root=run_root(run_id)
        try: records=list_files(root)
        except ValueError as error: raise HTTPException(413,str(error)) from None
        buffer = io.BytesIO()
        total = 0
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for record in records:
                if record['restricted']: continue
                try:
                    path = public_file(root, record['path'])
                except (ValueError,PermissionError,FileNotFoundError):
                    continue
                if not path.is_file() or path.name == '.env':
                    continue
                total += path.stat().st_size
                if total > 100_000_000:
                    raise HTTPException(413, 'Архив превышает лимит 100 МБ; скачайте артефакты отдельно')
                archive.write(path, record['path'])
        buffer.seek(0)
        return StreamingResponse(buffer, media_type='application/zip', headers={'Content-Disposition': f'attachment; filename="run-{identifier(run_id)}.zip"'})

    dependencies = [Depends(worker_key)]

    @app.post('/internal/jobs/claim', dependencies=dependencies)
    def claim(body: Claim):
        result = store.claim(body.workerId,body.requestId)
        return result if result else Response(status_code=204)

    @app.post('/internal/runs/{run_id}/heartbeat', dependencies=dependencies)
    def heartbeat(run_id: str, body: Lease):
        return store.heartbeat(run_id, body.model_dump(mode='json'))

    @app.post('/internal/runs/{run_id}/progress', dependencies=dependencies)
    def progress(run_id: str, body: Progress):
        return store.progress(run_id, body.model_dump(mode='json', exclude_none=True))

    @app.post('/internal/runs/{run_id}/finish', dependencies=dependencies)
    def finish(run_id: str, body: Finish):
        return store.finish(run_id, body.model_dump(mode='json'))

    return app


app = create_app()
