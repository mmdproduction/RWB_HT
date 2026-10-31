from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from shared.models import STAGES, TERMINAL_STATES, redact, safe_path
from shared.settings import Settings


class StoreError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message
        super().__init__(message)


def identifier(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        raise StoreError(404, 'Запуск не найден') from None


def iso(value):
    return value.isoformat() if value else None


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connection(self):
        return psycopg.connect(self.settings.database_url, row_factory=dict_row, connect_timeout=5)

    def initialize(self):
        with self.connection() as conn:
            conn.execute(Path(__file__).with_name('schema.sql').read_text())
        self.settings.artifact_root.mkdir(parents=True, exist_ok=True)

    def expire(self):
        with self.connection() as conn:
            conn.execute("""UPDATE pipeline_runs SET status='interrupted',finished_at=now(),
                         message='Worker heartbeat expired; create a new run to retry'
                         WHERE status='running' AND heartbeat_at < now()-(%s * interval '1 second')""",
                         (self.settings.lease_seconds,))

    def create(self, requirements):
        run_id = uuid4()
        with self.connection() as conn:
            conn.execute('INSERT INTO pipeline_runs(id,requirements) VALUES (%s,%s)', (run_id, requirements))
        return {'runId': str(run_id), 'status': 'queued'}

    def claim(self, worker_id, request_id=None):
        self.expire()
        request_id=request_id or uuid4()
        token = uuid4()
        with self.connection() as conn:
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',(str(request_id),))
            previous=conn.execute('SELECT worker_id,payload FROM pipeline_claim_requests WHERE request_id=%s',(request_id,)).fetchone()
            if previous:
                if previous['worker_id']!=worker_id: raise StoreError(409,'claim requestId принадлежит другому worker')
                return previous['payload']
            row = conn.execute("""WITH candidate AS (
                SELECT id FROM pipeline_runs WHERE status='queued'
                ORDER BY created_at,id LIMIT 1 FOR UPDATE SKIP LOCKED)
                UPDATE pipeline_runs AS r SET status='running',worker_id=%s,lease_token=%s,
                started_at=now(),heartbeat_at=now() FROM candidate WHERE r.id=candidate.id
                RETURNING r.id,r.requirements,r.status,r.worker_id,r.lease_token""", (worker_id, token)).fetchone()
            result=({'runId': str(row['id']), 'requirements': row['requirements'], 'status': row['status'],
                'workerId': row['worker_id'], 'leaseToken': str(row['lease_token'])} if row else None)
            conn.execute('INSERT INTO pipeline_claim_requests(request_id,worker_id,payload) VALUES(%s,%s,%s)',(request_id,worker_id,Jsonb(result)))
        return result

    def owned(self, conn, run_id, worker_id, lease_token, terminal=False):
        row = conn.execute('SELECT * FROM pipeline_runs WHERE id=%s FOR UPDATE', (identifier(run_id),)).fetchone()
        if row is None:
            raise StoreError(404, 'Запуск не найден')
        if row['worker_id'] != worker_id or str(row['lease_token']) != str(lease_token):
            raise StoreError(409, 'Задание принадлежит другому исполнителю или lease устарел')
        if row['status'] != 'running' and not terminal:
            raise StoreError(409, 'Запуск уже не выполняется')
        return row

    def heartbeat(self, run_id, body):
        self.expire()
        with self.connection() as conn:
            self.owned(conn, run_id, body['workerId'], body['leaseToken'])
            conn.execute('UPDATE pipeline_runs SET heartbeat_at=now() WHERE id=%s', (identifier(run_id),))
        return {'ok': True}

    def progress(self, run_id, body):
        self.expire()
        run_uuid = identifier(run_id)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        root = self.settings.artifact_root / str(run_uuid)
        for artifact in body.get('artifacts', []):
            try:
                path = safe_path(root, artifact['path'])
            except ValueError as error:
                raise StoreError(400, str(error)) from None
            if not path.is_file() or path.name == '.env':
                raise StoreError(400, 'Артефакт отсутствует или недоступен')
        with self.connection() as conn:
            run = self.owned(conn, run_id, body['workerId'], body['leaseToken'], terminal=True)
            previous = conn.execute('SELECT payload_hash FROM pipeline_attempts WHERE run_id=%s AND event_id=%s',
                                    (run_uuid, UUID(body['eventId']))).fetchone()
            if previous:
                if previous['payload_hash'] != digest:
                    raise StoreError(409, 'eventId уже использован с другим содержимым')
                return {'ok': True, 'duplicate': True}
            if run['status'] != 'running':
                raise StoreError(409, 'Завершенный запуск нельзя изменить')
            stage, attempt, status = body['stageId'], body['attempt'], body['status']
            old = conn.execute('SELECT * FROM pipeline_steps WHERE run_id=%s AND stage_id=%s', (run_uuid, stage)).fetchone()
            if old and (attempt < old['attempt'] or (old['status'] == 'passed' and attempt == old['attempt'] and status != 'passed')):
                raise StoreError(409, 'Устаревшая попытка или обратный переход стадии')
            message = redact(body.get('message', ''), self.settings.secrets)
            conn.execute('INSERT INTO pipeline_attempts(run_id,event_id,stage_id,attempt,payload_hash) VALUES (%s,%s,%s,%s,%s)',
                         (run_uuid, UUID(body['eventId']), stage, attempt, digest))
            conn.execute("""INSERT INTO pipeline_steps(run_id,stage_id,status,attempt,message,finished_at)
                VALUES (%s,%s,%s,%s,%s,CASE WHEN %s IN ('passed','failed','blocked','not_run') THEN now() ELSE NULL END)
                ON CONFLICT(run_id,stage_id) DO UPDATE SET status=excluded.status,attempt=excluded.attempt,
                message=excluded.message,finished_at=excluded.finished_at""", (run_uuid, stage, status, attempt, message, status))
            for line in body.get('logs', []):
                conn.execute('INSERT INTO pipeline_logs(run_id,stage_id,message) VALUES (%s,%s,%s)',
                             (run_uuid, stage, redact(line, self.settings.secrets)))
            for artifact in body.get('artifacts', []):
                conn.execute("""INSERT INTO pipeline_artifacts(id,run_id,name,kind,path) VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT(run_id,path) DO UPDATE SET name=excluded.name,kind=excluded.kind""",
                             (uuid4(), run_uuid, artifact['name'], artifact['kind'], artifact['path']))
            metrics = dict(run['metrics'])
            delta = body.get('metrics') or {}
            for key in ('modelCalls', 'retries'):
                metrics[key] = metrics.get(key, 0) + delta.get(key, 0)
            for key in ('inputTokens', 'outputTokens'):
                if key in delta or delta.get('modelCalls', 0):
                    if delta.get(key) is None or metrics.get(key) is None:
                        metrics[key] = None
                        metrics['tokenUsageComplete'] = False
                    else:
                        metrics[key] += delta[key]
            conn.execute('UPDATE pipeline_runs SET metrics=%s,heartbeat_at=now() WHERE id=%s', (Jsonb(metrics), run_uuid))
        return {'ok': True, 'duplicate': False}

    def finish(self, run_id, body):
        self.expire()
        run_uuid = identifier(run_id)
        message = redact(body.get('message', ''), self.settings.secrets)
        app_url, repository_url = body.get('appUrl'), body.get('repositoryUrl')
        with self.connection() as conn:
            run = self.owned(conn, run_id, body['workerId'], body['leaseToken'], terminal=True)
            if run['status'] in TERMINAL_STATES:
                if (run['status'], run['message'], run['app_url'], run['repository_url']) != (body['status'], message, app_url, repository_url):
                    raise StoreError(409, 'Итог завершенного запуска неизменяем')
                return {'runId': str(run_uuid), 'status': run['status']}
            if body['status'] == 'succeeded':
                checks = conn.execute('SELECT stage_id,status FROM pipeline_steps WHERE run_id=%s', (run_uuid,)).fetchall()
                states = {r['stage_id']: r['status'] for r in checks}
                missing = [stage for stage in STAGES if states.get(stage) != 'passed']
                if missing or not app_url:
                    raise StoreError(409, 'Успех требует доступного приложения и пройденных стадий: ' + ', '.join(missing))
            conn.execute("""UPDATE pipeline_runs SET status=%s,message=%s,app_url=%s,repository_url=%s,
                         finished_at=now(),heartbeat_at=now() WHERE id=%s""",
                         (body['status'], message, app_url, repository_url, run_uuid))
        return {'runId': str(run_uuid), 'status': body['status']}

    def _artifacts(self, conn, run_uuid):
        rows = conn.execute('SELECT * FROM pipeline_artifacts WHERE run_id=%s ORDER BY created_at,id', (run_uuid,)).fetchall()
        return [{'artifactId': str(r['id']), 'name': r['name'], 'kind': r['kind'], 'path': r['path'],
                 'url': f"/api/runs/{run_uuid}/artifacts/{r['id']}"} for r in rows]

    def get(self, run_id):
        self.expire()
        run_uuid = identifier(run_id)
        with self.connection() as conn:
            row = conn.execute('SELECT * FROM pipeline_runs WHERE id=%s', (run_uuid,)).fetchone()
            if row is None:
                raise StoreError(404, 'Запуск не найден')
            step_rows = conn.execute('SELECT * FROM pipeline_steps WHERE run_id=%s', (run_uuid,)).fetchall()
            artifacts = self._artifacts(conn, run_uuid)
        mapping = {r['stage_id']: r for r in step_rows}
        stages = []
        for stage in STAGES:
            step = mapping.get(stage, {})
            stages.append({'stageId': stage, 'status': step.get('status', 'pending'), 'attempt': step.get('attempt', 0),
                           'message': step.get('message', ''), 'startedAt': iso(step.get('started_at')), 'finishedAt': iso(step.get('finished_at'))})
        metrics = dict(row['metrics'])
        start = row['started_at'] or row['created_at']
        metrics['durationSeconds'] = round(((row['finished_at'] or datetime.now(timezone.utc)) - start).total_seconds(), 2)
        return {'runId': str(row['id']), 'requirements': row['requirements'], 'status': row['status'],
                'createdAt': iso(row['created_at']), 'startedAt': iso(row['started_at']), 'finishedAt': iso(row['finished_at']),
                'message': row['message'], 'appUrl': row['app_url'], 'repositoryUrl': row['repository_url'],
                'stages': stages, 'metrics': metrics, 'artifacts': artifacts}

    def list(self):
        self.expire()
        with self.connection() as conn:
            rows = conn.execute('SELECT id,requirements,status,created_at,finished_at,message FROM pipeline_runs ORDER BY created_at DESC LIMIT 100').fetchall()
        return [{'runId': str(r['id']), 'requirements': r['requirements'], 'status': r['status'], 'createdAt': iso(r['created_at']),
                 'finishedAt': iso(r['finished_at']), 'message': r['message']} for r in rows]

    def logs(self, run_id, after=0):
        self.get(run_id)
        with self.connection() as conn:
            rows = conn.execute('SELECT * FROM pipeline_logs WHERE run_id=%s AND cursor>%s ORDER BY cursor LIMIT 500', (identifier(run_id), after)).fetchall()
        return {'items': [{'cursor': r['cursor'], 'stageId': r['stage_id'], 'createdAt': iso(r['created_at']), 'message': r['message']} for r in rows],
                'nextCursor': rows[-1]['cursor'] if rows else after}

    def artifacts(self, run_id):
        self.get(run_id)
        with self.connection() as conn:
            return self._artifacts(conn, identifier(run_id))
