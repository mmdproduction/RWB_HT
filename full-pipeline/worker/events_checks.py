"""Trusted Kafka evidence checks. Run by future acceptance, never model-provided code."""
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

BASE = os.environ.get('BASE_URL', 'http://frontend').rstrip('/')
RESULTS = Path('/event-results')
RECEIPTS = RESULTS / 'business-events.jsonl'
CONTRACT = Path('/checks/event-contract.json')


def request(method, path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try: response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as error: response = error
    raw = response.read()
    payload = json.loads(raw) if raw else None
    return response.status, payload


def login(role):
    status, body = request('POST', '/api/auth/login', {'role': role})
    assert status == 200, ('Kafka business login', status)
    return body['token']


def state(token):
    status, body = request('GET', '/api/events/state', token=token)
    assert status == 200, ('Kafka business state', status)
    return body['enqueued']


def evidence(receipt, token, minimum_deliveries=1, timeout=60):
    event_id = receipt['eventId']
    assert str(uuid.UUID(event_id)) == event_id, 'Kafka eventId must be a UUID'
    deadline = time.monotonic() + timeout
    actual = None
    while time.monotonic() < deadline:
        status, actual = request('GET', '/api/events/evidence/' + event_id, token=token)
        if status == 200 and actual.get('publishedAt') and actual.get('processedAt') and (actual.get('deliveries') or 0) >= minimum_deliveries and actual.get('lastConsumerOffset', -1) >= (actual.get('offset') or 0): break
        time.sleep(.5)
    assert status == 200 and actual.get('publishedAt') and actual.get('processedAt'), ('Kafka business event not delivered/processed', event_id, actual)
    envelope = actual['envelope']
    assert envelope['eventId'] == event_id and envelope['topic'] == 'app.business.v1' and envelope['schemaVersion'] == 1, ('Kafka event envelope', actual)
    assert envelope['endpointId'] == receipt['endpointId'] and envelope['eventType'] == receipt['endpointId'] + '.completed', ('Kafka event endpoint', actual)
    assert envelope['responseStatus'] == receipt['status'] and envelope['data'] == receipt['data'], ('Kafka event differs from business response', actual)
    assert envelope['actor'] == 'demo-' + receipt['role'], ('Kafka event actor', actual)
    assert actual['activityCount'] == 1 and actual['deliveries'] >= minimum_deliveries, ('Kafka event duplicated side effect', actual)
    assert actual['partition'] == actual['consumerPartition'] and actual['consumerOffset'] <= actual['offset'] <= actual['lastConsumerOffset'], ('Kafka event offsets not processed', actual)
    return actual


def record(event_id, endpoint, status, body, role, token):
    receipt = {'eventId': event_id, 'endpointId': endpoint['id'], 'status': status, 'data': body, 'role': role}
    evidence(receipt, token)
    RESULTS.mkdir(exist_ok=True)
    with RECEIPTS.open('a', encoding='utf-8') as output:
        output.write(json.dumps(receipt, ensure_ascii=False, allow_nan=False) + '\n')


def main():
    receipts = [json.loads(line) for line in RECEIPTS.read_text().splitlines() if line.strip()]
    expected = {e['endpointId'] for e in json.loads(CONTRACT.read_text())['events']}
    assert receipts and expected <= {r['endpointId'] for r in receipts}, ('Kafka business acceptance omits event endpoints', expected)
    tokens = {role: login(role) for role in {r['role'] for r in receipts}}
    baseline = {r['eventId']: evidence(r, tokens[r['role']]) for r in receipts}
    if os.environ.get('PERSISTENCE_ONLY') == '1':
        # Exercise real redelivery through outbox -> Kafka -> consumer, not an INSERT into inbox.
        admin = login('admin')
        unique = {r['eventId']: r for r in receipts}
        for event_id, receipt in unique.items():
            status, body = request('POST', '/api/events/replay/' + event_id, {}, admin)
            assert status == 200, ('Kafka event replay', status, body)
            after = evidence(receipt, tokens[receipt['role']], baseline[event_id]['deliveries'] + 1)
            assert after['processedAt'] == baseline[event_id]['processedAt'], 'Kafka event reprocessed the activity effect'
    result = {'passed': True, 'mode': 'persistence-redelivery' if os.environ.get('PERSISTENCE_ONLY') == '1' else 'business-delivery',
              'endpointIds': sorted(expected), 'eventIds': sorted({r['eventId'] for r in receipts})}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / ('persistence.json' if os.environ.get('PERSISTENCE_ONLY') == '1' else 'delivery.json')).write_text(json.dumps(result, indent=2))
    print('PASS Kafka business delivery, consumer history' + (' and restart/redelivery deduplication' if os.environ.get('PERSISTENCE_ONLY') == '1' else ''), flush=True)


if __name__ == '__main__': main()
