"""Trusted, reusable target-project renderer. Never executes model supplied commands."""
from __future__ import annotations

import json
from pathlib import Path
import re
import secrets
import shutil

ASSETS = Path(__file__).with_name('assets')
STACK = {'frontend': 'Angular 20.1.6', 'uiKit': 'Angular Material 20.1.6', 'backend': '.NET 10 / C# 14', 'database': 'PostgreSQL 17.9 / PostGIS', 'mobile': 'PWA', 'messaging': 'Apache Kafka 4.1.2 + REST'}


def _validate(spec: dict) -> dict:
    from shared.models import AppSpec
    validated = AppSpec.model_validate(spec)
    if validated.critical_questions:
        raise ValueError('Critical questions must be resolved before rendering')
    return validated.model_dump()


def _openapi(spec: dict, parking: bool) -> dict:
    def operation(description, request=None, status='200'):
        op = {'summary': description, 'security': [{'demoBearer': []}], 'responses': {status: {'description': 'Success'}, '400': {'description': 'Validation error'}, '401': {'description': 'Authentication required'}, '403': {'description': 'Role not permitted'}}}
        if request:
            op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': request}}}
        return op
    paths = {
        '/api/schema': {'get': {'summary': 'Application specification', 'responses': {'200': {'description': 'AppSpec'}}}},
        '/api/auth/login': {'post': {**operation('Issue a demo role token; not production identity', {'type': 'object', 'required': ['role'], 'properties': {'role': {'type': 'string', 'enum': list(dict.fromkeys(spec['roles'] + ['admin'] + (['driver'] if parking else [])))}}}), 'security': []}},
        '/api/health': {'get': operation('Database version and PostGIS availability')},
    }
    schemas = {}
    for entity in spec['entities']:
        name = entity['name']
        properties = {f['name']: {'type': 'string' if f['type'] == 'datetime' else f['type'], **({'format': 'date-time'} if f['type'] == 'datetime' else {})} for f in entity['fields']}
        schemas[name] = {'type': 'object', 'additionalProperties': False, 'properties': properties, 'required': [f['name'] for f in entity['fields'] if f['required']]}
        ref = {'$ref': '#/components/schemas/' + name}
        route = '/api/entities/' + name
        paths[route] = {'get': operation('List '+name+' records'), 'post': operation('Create '+name+'; admin only', ref, '201')}
        paths[route+'/{id}'] = {'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}}], 'get': operation('Read '+name), 'put': operation('Replace '+name+'; admin only', ref), 'delete': operation('Delete '+name+'; admin only', status='204')}
    if parking:
        bodies = {
            'position': {'type': 'object', 'required': ['longitude', 'latitude'], 'properties': {'longitude': {'type': 'number', 'minimum': -180, 'maximum': 180}, 'latitude': {'type': 'number', 'minimum': -90, 'maximum': 90}}},
            'sessions': {'type': 'object', 'required': ['zoneId', 'durationMinutes', 'confirmDemoPayment'], 'properties': {'zoneId': {'type': 'string'}, 'durationMinutes': {'type': 'integer', 'minimum': 15, 'maximum': 1440}, 'confirmDemoPayment': {'type': 'boolean', 'const': True}}},
            'clock': {'type': 'object', 'required': ['advanceSeconds'], 'properties': {'advanceSeconds': {'type': 'integer', 'minimum': 0, 'maximum': 86400}}},
            'zones': {'type': 'object', 'required': ['id', 'name', 'rate', 'coordinates'], 'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}, 'rate': {'type': 'number', 'minimum': 0}, 'coordinates': {'type': 'array', 'items': {'type': 'array', 'items': {'type': 'number'}}}}},
        }
        for route, description in [('zones', 'List PostGIS zones'), ('active', 'Current position and active paid session'), ('history', 'Completed sessions for current actor'), ('events', 'Current actor route and warning events')]:
            paths['/api/parking/'+route] = {'get': operation(description)}
        for route, description in [('position', 'Report position, preserve existing paid session'), ('sessions', 'Explicitly confirm demo payment and start session'), ('zones', 'Create or update validated polygon; admin only'), ('clock', 'Advance controlled demo clock; admin only')]:
            paths.setdefault('/api/parking/'+route, {})['post'] = operation(description, bodies[route], '201' if route == 'sessions' else '200')
        paths['/api/parking/sessions/{id}/stop'] = {'parameters': [{'name': 'id', 'in': 'path', 'required': True, 'schema': {'type': 'string', 'format': 'uuid'}}], 'post': operation('Driver explicitly ends own session')}
    paths['/api/integrations']={'get':operation('Local mock provider contracts and fixture data')}
    paths['/api/events/activity']={'get':operation('Actor-scoped business activity processed by the Kafka consumer')}
    paths['/api/events/state']={'get':operation('Actor-scoped committed outbox event count')}
    paths['/api/events/evidence/{id}']={'parameters':[{'name':'id','in':'path','required':True,'schema':{'type':'string','format':'uuid'}}],
        'get':operation('Delivery and consumer evidence for an event owned by the current actor')}
    paths['/api/events/replay/{id}']={'parameters':[{'name':'id','in':'path','required':True,'schema':{'type':'string','format':'uuid'}}],
        'post':operation('Demo admin only, TEST_CLOCK_ENABLED=true: requeue an existing immutable event')}
    paths['/api/integrations/usage']={'get':operation('Admin-only business invocation counters')}
    for provider in spec['externalIntegrations']:
        for op in provider['operations']:
            paths[f"/api/integrations/{provider['id']}/{op['id']}"]={'post':operation(
                'MOCK ONLY: '+op['description'],{'type':'object','required':['requestId','input'],
                    'properties':{'requestId':{'type':'string'},'scenario':{'type':'string','enum':['success','declined','unavailable']},
                    'input':{'type':'object','example':op['inputExample']}}})}
    return {'openapi': '3.1.0', 'info': {'title': spec['title'], 'version': '1.0.0'}, 'servers': [{'url': '/'}], 'paths': paths, 'components': {'schemas': schemas, 'securitySchemes': {'demoBearer': {'type': 'http', 'scheme': 'bearer', 'description': 'Opaque demo role token from /api/auth/login; expires after 12h'}}}}


def render_project(spec: dict, destination: Path, run_id: str) -> dict:
    spec = _validate(spec)
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
        raise ValueError('Destination must be a new or empty directory')
    parking = any('parking' in capability.lower() for capability in spec['capabilities'])
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ASSETS, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns('node_modules', '.angular', 'dist', '__pycache__'))
    def write(path, content):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    encoded = json.dumps(spec, ensure_ascii=False, indent=2) + '\n'
    write('backend/app-spec.json', encoded)
    write('scripts/app-spec.json', encoded)
    write('app-spec.json', encoded)
    write('docs/mock-integrations.json',json.dumps({'mode':'mock','providers':spec['externalIntegrations']},ensure_ascii=False,indent=2)+'\n')
    write('docs/mock-integrations.md', '''# Локальные внешние интеграции

Все интеграции работают только в режиме mock. Нет реальных списаний, внешних тайлов, отправки сообщений и получения актуальных сторонних данных. Fixture-ответы и типизированные входы перечислены в mock-integrations.json. Не используйте их как реальные финансовые квитанции, дорожные маршруты или актуальные данные.

В предметном C# endpoint получите MockIntegrationProviders через DI и вызовите await mocks.Call(context, providerId, operationId, request). request — JsonElement с requestId (стабильный ключ одного действия), input (объект по inputFields) и scenario: success / declined / unavailable. Возвращается MockIntegrationResult с StatusCode и Body; проверяйте StatusCode и передавайте ошибку пользователю. Для карт рисуйте локальные GeoJSON/маршруты из fixture, без внешних тайлов и SDK. Для данных используйте тематические fixtures из контракта. success — воспроизводимый fixture-ответ, а не симуляция всех возможностей настоящего сервиса.

При успешном запросе Body содержит mode: mock, providerId, operationId, requestId, receiptId, success, data, createdAt. Для платежей в data отражаются фактические amount/currency запроса. Некорректные входы дают 400. Declined дает 402 для платежей и 422 для других типов; unavailable — 503. Повтор с тем же ключом и тем же содержимым возвращает сохраненную квитанцию; с другим содержимым — 409. Вызовы и результаты сохраняются в PostgreSQL и переживают перезапуск. Другой пользователь не может прочитать чужую квитанцию.

Прямой HTTP API /api/integrations/{providerId}/{operationId} предназначен для контрактной проверки. Предметные handlers вызывают Call через DI; их реальные обращения учитываются отдельно. GET /api/integrations/usage доступен admin для приемки. Доступность mock-провайдера сама по себе не доказывает, что его использует бизнес-сценарий.

Backend, consumer, Kafka, БД и checks подключены только к внутренней сети Docker. Frontend соединяет эту сеть с опубликованным localhost-портом; браузер ограничен CSP self. Изоляция runtime не запрещает скачивание зависимостей и образов при сборке и не относится к Qwen самого пайплайна.
''')
    write('.env', 'DB_PASSWORD=' + secrets.token_hex(24) + '\n')
    (destination/'.env').chmod(0o600)
    write('.gitignore', '.env\n**/node_modules/\n**/dist/\n**/bin/\n**/obj/\n')
    write('.dockerignore', '.env\nnode_modules\ndist\n')
    for folder in ['backend', 'frontend']:
        write(folder+'/.dockerignore', 'node_modules\ndist\n.angular\nbin\nobj\n')
    compose = {'services': {
        'db': {'build': './db', 'environment': {'POSTGRES_DB': 'app', 'POSTGRES_USER': 'app', 'POSTGRES_PASSWORD': '${DB_PASSWORD:?DB_PASSWORD is required}'}, 'volumes': ['db-data:/var/lib/postgresql/data'], 'healthcheck': {'test': ['CMD-SHELL', 'pg_isready -U app -d app'], 'interval': '3s', 'timeout': '3s', 'retries': 30}, 'restart': 'unless-stopped'},
        'backend': {'build': './backend', 'environment': {'DATABASE_URL': 'Host=db;Database=app;Username=app;Password=${DB_PASSWORD}', 'TEST_CLOCK_ENABLED': 'true', 'ASPNETCORE_ENVIRONMENT': 'Production'}, 'depends_on': {'db': {'condition': 'service_healthy'}}, 'healthcheck': {'test': ['CMD-SHELL', "bash -c 'exec 3<>/dev/tcp/127.0.0.1/8080; printf \"GET /health HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n\" >&3; head -n1 <&3 | grep -q 200'"], 'interval': '5s', 'timeout': '5s', 'retries': 30, 'start_period': '15s'}, 'restart': 'unless-stopped'},
        'frontend': {'build': './frontend', 'ports': ['127.0.0.1::80'], 'depends_on': {'backend': {'condition': 'service_healthy'}}, 'healthcheck': {'test': ['CMD-SHELL', 'wget -q -O /dev/null http://127.0.0.1/health'], 'interval': '5s', 'timeout': '5s', 'retries': 30}, 'restart': 'unless-stopped'},
        'checks': {'build': {'context': '.', 'dockerfile': 'scripts/Dockerfile'}, 'profiles': ['checks'], 'working_dir': '/checks', 'environment': {'BASE_URL': 'http://frontend'}, 'depends_on': {'frontend': {'condition': 'service_healthy'}}, 'command': ['python', '/checks/tests.py'], 'read_only': True, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true']},
    }, 'volumes': {'db-data': {}}}
    compose['services']['kafka'] = {
        'image':'apache/kafka:4.1.2', 'hostname':'kafka', 'restart':'unless-stopped',
        'environment': {
            'KAFKA_NODE_ID':'1', 'KAFKA_PROCESS_ROLES':'broker,controller',
            'KAFKA_LISTENERS':'PLAINTEXT://:9092,CONTROLLER://:9093',
            'KAFKA_ADVERTISED_LISTENERS':'PLAINTEXT://kafka:9092',
            'KAFKA_LISTENER_SECURITY_PROTOCOL_MAP':'CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT',
            'KAFKA_INTER_BROKER_LISTENER_NAME':'PLAINTEXT', 'KAFKA_CONTROLLER_LISTENER_NAMES':'CONTROLLER',
            'KAFKA_CONTROLLER_QUORUM_VOTERS':'1@kafka:9093', 'CLUSTER_ID':'4L6g3nShT-eMCtK--X86sw',
            'KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR':'1', 'KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS':'0',
            'KAFKA_TRANSACTION_STATE_LOG_MIN_ISR':'1', 'KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR':'1',
            'KAFKA_AUTO_CREATE_TOPICS_ENABLE':'false', 'KAFKA_LOG_DIRS':'/var/lib/kafka/data',
            'KAFKA_LOG_RETENTION_HOURS':'72', 'KAFKA_HEAP_OPTS':'-Xms256m -Xmx512m'},
        'volumes':['kafka-data:/var/lib/kafka/data'],
        'healthcheck':{'test':['CMD-SHELL','/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server kafka:9092 >/dev/null 2>&1'],
                       'interval':'10s','timeout':'10s','retries':18,'start_period':'20s'}}
    backend=compose['services']['backend']
    backend['environment']['KAFKA_BOOTSTRAP_SERVERS']='kafka:9092'
    backend['depends_on']['kafka']={'condition':'service_healthy'}
    compose['services']['event-consumer']={
        'build':'./backend', 'restart':'unless-stopped',
        'environment':{**backend['environment'],'APP_MODE':'consumer'},
        'depends_on':{'backend':{'condition':'service_healthy'},'kafka':{'condition':'service_healthy'}},
        'healthcheck':dict(backend['healthcheck'])}
    compose['services']['frontend']['depends_on']['event-consumer']={'condition':'service_healthy'}
    compose['services']['checks']['volumes']=['./event-results:/event-results']
    event_results=destination/'event-results';event_results.mkdir(exist_ok=True);event_results.chmod(0o777)
    compose['volumes']['kafka-data']={}
    compose['networks']={'app':{'internal':True},'default':{}}
    for name,service in compose['services'].items():
        service['networks']=['app','default'] if name=='frontend' else ['app']
    write('compose.yaml', json.dumps(compose, indent=2)+'\n')
    write('docs/openapi.json', json.dumps(_openapi(spec, parking), ensure_ascii=False, indent=2)+'\n')
    safe_run = re.sub(r'[^a-z0-9_]', '_', run_id.lower())[:48] or 'demo'
    write('README.md', f'''# {spec['title']}

Generated run: {run_id}. {spec['summary']}

## Start and verify

```sh
docker compose -p rwb_{safe_run} build
docker compose -p rwb_{safe_run} up -d --wait
docker compose -p rwb_{safe_run} run --rm checks
docker compose -p rwb_{safe_run} port frontend 80
```

Open the printed localhost port. Only the frontend is published. The database is a project-specific named volume. `.env` contains a randomly generated local database password; do not publish it.

## Contracts and data

Angular 20.1.6, Angular Material 20.1.6, installable PWA shell; .NET 10/C# 14 API; PostgreSQL 17.9 with PostGIS; Apache Kafka 4.1.2 and REST. See `docs/openapi.json` and `app-spec.json`. Generic records persist in a validated JSONB table: this supports all AppSpec field types and independent entities without invented relations. Admin creates/updates/deletes; all other roles can read. Model-owned additions are `backend/Generated/**` (called through `GeneratedExtensions.Map`) and `frontend/src/app/generated/**` (root `GeneratedPanel`). These additions are executed as application code, so use this local pipeline only with trusted operators.

## Business events

`backend` writes business state and an outbox event in one PostgreSQL transaction through `BusinessEvents.Enqueue`. Its publisher delivers the event to `app.business.v1`; the separate `event-consumer` persists an actor-scoped activity journal, exposed at `/api/events/activity` and in the optional journal below the main screen. The journal records completed actions; it does not send external messages. Third-party providers remain local mocks. The broker and consumer are internal Compose services; Kafka data has a named volume, no host port. The contract in `docs/event-contract.json` is derived from the frozen UI/API plan before code generation. Successful declared business endpoints expose `X-Business-Event-Id`; response JSON stays unchanged. Delivery is at least once with inbox deduplication, not a distributed exactly-once transaction. A single KRaft broker is intended for this hackathon demo. GitLab CI is prepared as configuration; no remote server/runner is provisioned by the generator.

## Demo access and limits

The login selector issues a random, expiring token for a chosen demo role. It deliberately proves role enforcement, not production identity: anyone reaching this local app can select admin. Tokens are stored hashed. No payment gateway, real funds, background mobile GPS, remote map tiles, push delivery, or iOS native app is provided. PWA shell may load offline; API data requires network. PNG icons (192/512) and manifest are included; installation requires a supporting browser and HTTPS or localhost. Requested external integrations use local persistent mock providers with typed inputs, fixture responses, failure scenarios and idempotent receipts. See docs/mock-integrations.md and docs/mock-integrations.json. Backend runtime has no external network route; model-owned code cannot enable real integrations.

## Parking capability

{'Enabled' if parking else 'Disabled'}. PostGIS `ST_Covers` includes boundaries; shared boundaries select the lexically first zone ID. A driver reports foreground GPS or an explicitly labelled demo route, then explicitly confirms a demo payment and duration (15–1440 minutes). Warning appears when 10 minutes remain, once per session, through polling. Crossing or leaving zones logs an event and payment advice without cancelling, moving or creating paid sessions. An explicit stop or expiry completes the session. The admin can save polygons and rates. Session costs are fixed at confirmation; later rate edits do not change them. The controllable clock is admin-only and enabled for this demo (`TEST_CLOCK_ENABLED=true`); turn it off for ordinary operation. Time is fixed after the first clock operation and advances only through that endpoint. No financial settlement or refunds are performed.

## Persistence verification

After the acceptance suite, restart backend, wait for health, and run:

```sh
docker compose -p rwb_{safe_run} run --rm -e PERSISTENCE_ONLY=1 checks
```

Acceptance creates and retains one updated record per entity to make restart verification observable. `docker compose down` retains database data; `down -v` deletes that project's data.
''')
    write('.gitlab-ci.yml', '''image: docker:27-cli
services:
  - name: docker:27-dind
variables:
  DOCKER_HOST: tcp://docker:2375
  DOCKER_TLS_CERTDIR: ""
stages: [verify]
verify:
  stage: verify
  script:
    - export TEST_CLOCK_ENABLED=true
    - export DB_PASSWORD="ci-${CI_PIPELINE_ID}-${CI_JOB_ID}"
    - docker compose --profile checks -p "rwb_ci_${CI_PIPELINE_ID}" build
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm checks python /checks/integration_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm checks
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" restart backend
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait backend
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e PERSISTENCE_ONLY=1 checks python /checks/integration_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e PERSISTENCE_ONLY=1 checks
  after_script:
    - export DB_PASSWORD="ci-${CI_PIPELINE_ID}-${CI_JOB_ID}"
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" logs --no-color > compose.log
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" down -v --remove-orphans
  artifacts:
    when: always
    paths: [compose.log, docs/openapi.json, app-spec.json]
''')
    files = sorted(str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file())
    return {'root': str(destination.resolve()), 'files': files, 'stack': STACK, 'parking': parking, 'acceptanceCommand': ['docker', 'compose', 'run', '--rm', 'checks']}
