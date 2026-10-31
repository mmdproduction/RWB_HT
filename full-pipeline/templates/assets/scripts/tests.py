"""Trusted stdlib HTTP acceptance suite; no commands supplied by the model."""
import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get('BASE_URL', 'http://frontend')
SPEC = json.load(open('/checks/app-spec.json', encoding='utf-8'))


def request(path, method='GET', body=None, token=None, status=200, base=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request((base or BASE) + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            code, data = res.status, res.read()
    except urllib.error.HTTPError as exc:
        code, data = exc.code, exc.read()
    assert code == status, f'{method} {path}: expected {status}, got {code}; {data[:1200]!r}'
    return json.loads(data) if data and data[:1] in (b'{', b'[') else data


def login(role):
    return request('/api/auth/login', 'POST', {'role': role})['token']


def payload(entity, changed=False):
    values = {'string': 'updated acceptance' if changed else 'acceptance record', 'integer': 9 if changed else 7,
              'number': 4.25 if changed else 3.5, 'boolean': changed, 'datetime': '2026-01-02T03:04:05Z'}
    return {f['name']: values[f['type']] for f in entity['fields']}


def run():
    # Direct backend check: Nginx's case-sensitive location would otherwise serve SPA fallback.
    request('/API/health',status=401,base='http://backend:8080')
    for attempt in range(60):
        try:
            request('/health')
            break
        except (OSError, AssertionError):
            if attempt == 59:
                raise
            time.sleep(1)
    admin = login('admin')
    health = request('/api/health', token=admin)
    assert health['postgres'].split()[0] == '17.9', health
    assert health['postgis'], health
    request('/api/entities/Unknown', status=401)
    request('/api/auth/login', 'POST', {'role': 'not-a-role'}, status=400)
    assert request('/api/schema')['slug'] == SPEC['slug']
    entities = SPEC['entities']
    if os.environ.get('PERSISTENCE_ONLY') == '1':
        for entity in entities:
            records = request('/api/entities/' + entity['name'], token=admin)
            assert any(row['data'] == payload(entity, True) for row in records), f'Lost persisted {entity["name"]}'
        print(json.dumps({'status': 'passed', 'checks': ['persistence_after_restart'] if entities else ['database_health_after_restart'],
            'notApplicable': [] if entities else ['business_record_persistence: no stored entities required by this product']}))
        return
    for entity in entities:
        path = '/api/entities/' + entity['name']
        fields = entity['fields']
        bad = {'__unknown': True}
        request(path, 'POST', bad, admin, 400)
        if fields:
            bad = payload(entity)
            bad[fields[0]['name']] = {'invalid': 'type'}
            request(path, 'POST', bad, admin, 400)
        required = [f for f in fields if f['required']]
        if required:
            bad = payload(entity)
            del bad[required[0]['name']]
            request(path, 'POST', bad, admin, 400)
        created = request(path, 'POST', payload(entity), admin, 201)
        record_path = path + '/' + created['id']
        assert request(record_path, token=admin)['data'] == payload(entity)
        updated = request(record_path, 'PUT', payload(entity, True), admin)
        assert updated['data'] == payload(entity, True)
        assert any(r['id'] == created['id'] for r in request(path, token=admin))
        disposable = request(path, 'POST', payload(entity), admin, 201)
        request(path + '/' + disposable['id'], 'DELETE', token=admin, status=204)
        request(path + '/' + disposable['id'], token=admin, status=404)
        nonadmin = next((r for r in SPEC['roles'] if r != 'admin'), None)
        if nonadmin:
            reader = login(nonadmin)
            request(path, token=reader)
            request(path, 'POST', payload(entity), reader, 403)
    if any('parking' in c.lower() for c in SPEC['capabilities']):
        check_parking(admin)
    assert b'<app-root>' in request('/')
    assert request('/manifest.webmanifest')['display'] == 'standalone'
    assert request('/ngsw.json')['configVersion'] == 1
    print(json.dumps({'status': 'passed', 'checks': ['auth', 'frontend', 'pwa'] + (['validation','dynamic_crud','persistence_write'] if entities else []) + (['postgis', 'parking_sessions', 'cross_zone', 'warning_once', 'history'] if any('parking' in c.lower() for c in SPEC['capabilities']) else [])}))


def check_parking(admin):
    driver = login('driver')
    p = '/api/parking'
    request(p + '/clock', 'POST', {'advanceSeconds': 0}, admin)
    request(p + '/clock', 'POST', {'advanceSeconds': 1}, driver, 403)
    request(p + '/zones', 'POST', {'id': 'invalid'}, driver, 403)
    zones = request(p + '/zones', token=driver)
    assert len(zones) >= 2
    request(p + '/position', 'POST', {'longitude': 999, 'latitude': 55}, driver, 400)
    def position(lon, lat=59.935):
        return request(p + '/position', 'POST', {'longitude': lon, 'latitude': lat}, driver)
    # Stable shared-boundary rule picks A.
    assert position(30.32)['zoneId'] == 'A'
    assert position(30.315)['zoneId'] == 'A'
    before = request(p + '/active', token=driver)
    if before['session']:
        request(p + '/sessions/' + before['session']['id'] + '/stop', 'POST', {}, driver)
    request(p + '/sessions', 'POST', {'zoneId': 'A', 'durationMinutes': 60}, driver, 400)
    started = request(p + '/sessions', 'POST', {'zoneId': 'A', 'durationMinutes': 60, 'confirmDemoPayment': True}, driver, 201)
    sid = started['id']
    assert request(p + '/active', token=driver)['session']['warning'] is False
    request(p + '/sessions', 'POST', {'zoneId': 'A', 'durationMinutes': 60, 'confirmDemoPayment': True}, driver, 409)
    assert position(30.325)['transition'] == 'zone_changed'
    active = request(p + '/active', token=driver)['session']
    assert active['id'] == sid and active['zoneId'] == 'A' and active['zoneMismatch'] is True
    position(30.335, 59.945)
    assert request(p + '/active', token=driver)['session']['id'] == sid
    request(p + '/clock', 'POST', {'advanceSeconds': 49 * 60}, admin)
    assert request(p + '/active', token=driver)['session']['warning'] is False
    request(p + '/clock', 'POST', {'advanceSeconds': 60}, admin)
    assert request(p + '/active', token=driver)['session']['warning'] is True
    request(p + '/active', token=driver)
    events = request(p + '/events', token=driver)
    assert len([e for e in events if e['kind'] == 'expiry_warning' and e['sessionId'] == sid]) == 1, events
    assert any(e['kind'] == 'zone_changed' for e in events)
    assert any(e['kind'] == 'left_zone' for e in events)
    request(p + '/sessions/' + sid + '/stop', 'POST', {}, driver)
    assert request(p + '/active', token=driver)['session'] is None
    assert any(s['id'] == sid for s in request(p + '/history', token=driver))
    # Admin-defined third polygon must affect the real PostGIS query.
    request(p + '/zones', 'POST', {'id': 'C', 'name': 'Acceptance zone', 'rate': 50,
            'coordinates': [[30.34, 59.93], [30.35, 59.93], [30.35, 59.94], [30.34, 59.94], [30.34, 59.93]]}, admin)
    assert position(30.345)['zoneId'] == 'C'
    position(30.335, 59.945)


if __name__ == '__main__':
    run()
