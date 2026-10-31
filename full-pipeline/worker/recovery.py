"""Deterministic repair boundaries, source snapshots and release evidence."""
import hashlib
from pathlib import Path
import re

from shared.files import EXCLUDED_DIRECTORIES
from shared.models import safe_path

COMPONENT_ROOTS={'backend':'backend/Generated','frontend':'frontend/src/app/generated'}


def source_hash(project:Path):
    digest=hashlib.sha256()
    for directory in ('backend','frontend','db'):
        root=project/directory
        if not root.exists(): continue
        for path in sorted(root.rglob('*')):
            relative=path.relative_to(project)
            if path.is_symlink() or not path.is_file() or any(part in EXCLUDED_DIRECTORIES for part in relative.parts): continue
            if path.name.startswith('.env'): continue
            digest.update(relative.as_posix().encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def acceptance_hash(project:Path):
    digest=hashlib.sha256()
    for name in ('scripts/tests.py','scripts/domain_checks.py','scripts/domain-acceptance.json','scripts/app-spec.json','scripts/Dockerfile',
                 'scripts/integration_checks.py','docs/mock-integrations.json'):
        path=project/name
        if not path.is_file(): raise ValueError('Отсутствует зафиксированная проверка: '+name)
        digest.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    for name in ('scripts/browser_checks.py','scripts/browser-acceptance.json','scripts/Dockerfile.browser',
                 'scripts/product_contract.py','scripts/product-plan.json','docs/product-plan.json','docs/openapi.json',
                 'scripts/events_checks.py','scripts/event-contract.json','docs/event-contract.json'):
        path=project/name
        if path.exists(): digest.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()


def snapshot_sources(project:Path):
    snapshot={}
    for folder in COMPONENT_ROOTS.values():
        for path in (project/folder).rglob('*'):
            if path.is_file():
                relative=path.relative_to(project).as_posix()
                snapshot[relative]=safe_path(project,relative).read_bytes()
    return snapshot


def restore_sources(project:Path,snapshot):
    for folder in COMPONENT_ROOTS.values():
        for path in (project/folder).rglob('*'):
            if path.is_file() and path.relative_to(project).as_posix() not in snapshot:
                safe_path(project,path.relative_to(project).as_posix()).unlink()
    for relative,content in snapshot.items():
        target=safe_path(project,relative)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(content)


def check_scope(patch,components):
    files=patch.get('files')
    if not isinstance(files,list) or not files: raise ValueError('Модель не вернула files для исправления')
    prefixes=tuple(COMPONENT_ROOTS[name]+'/' for name in components)
    for item in files:
        if not isinstance(item,dict) or not isinstance(item.get('path'),str) or not item['path'].startswith(prefixes):
            raise ValueError('Исправление выходит за область ошибки: '+str(item.get('path') if isinstance(item,dict) else item))


def transient_network_failure(output):
    # Retry transport failures, never a generic "metadata" error (bad tag/auth).
    patterns=(r'tls handshake timeout',r'net/http: request canceled',r'i/o timeout',
        r'temporary failure in name resolution',r'connection reset by peer',
        r'network is unreachable',r'no route to host',r'connection timed out',
        r'(?:registry|docker\.io)[^\n]*\b(?:429 Too Many Requests|502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout)\b',
        r'toomanyrequests')
    return any(re.search(pattern,output,re.I) for pattern in patterns)


def infrastructure_failure(output):
    patterns=(r'network is unreachable',r'no route to host',r'tls handshake timeout',r'temporary failure in name resolution',
        r'failed to resolve source metadata',r'failed to authorize:.*(?:429|timeout)',r'toomanyrequests',
        r'cannot connect to the docker daemon',r'permission denied.*docker\.sock',r'no space left on device',
        r'failed to fetch.*(?:https?://|registry)',r'could not resolve host')
    if re.search(r'(?:container|service) [^\n]*(?:kafka|event-consumer)[^\n]*(?:unhealthy|failed to start)',output,re.I): return True
    return transient_network_failure(output) or any(re.search(pattern,output,re.I) for pattern in patterns)


def failure_components(output):
    components=set()
    if re.search(r'error\s+CS\d+|\.cs\(\d+|body was inferred|backend[^\n]*(?:unhealthy|error)|backend[^\n]*Unhandled',output,re.I):
        components.add('backend')
    if re.search(r'actual HTTP response|browser API response|Endpoint absent from frozen',output,re.I): components.add('backend')
    if re.search(r'Kafka business|Kafka event|BusinessEvents|X-Business-Event-Id',output,re.I): components.add('backend')
    if re.search(r'Frontend browser acceptance|Frontend horizontal|Frontend uncaught|Browser.*contract|data-testid',output,re.I): components.add('frontend')
    if re.search(r'error\s+(?:TS|NG)\d+|plugin angular-compiler|src/app/generated/[^\s]+:\d+|frontend[^\n]*(?:unhealthy|error)',output,re.I):
        components.add('frontend')
    if not components and re.search(r'AssertionError|/api/',output,re.I): components.add('backend')
    return components or {'backend','frontend'}
