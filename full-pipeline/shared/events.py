"""Deterministic event contract derived from the frozen REST/UI product plan."""
TOPIC = 'app.business.v1'


def assert_event_runtime(project, plan):
    import json
    config = json.loads((project/'compose.yaml').read_text())['services']
    broker = config.get('kafka', {})
    consumer = config.get('event-consumer', {})
    if broker.get('image') != 'apache/kafka:4.1.2' or broker.get('ports') or 'kafka-data:/var/lib/kafka/data' not in broker.get('volumes', []):
        raise ValueError('Fixed Kafka broker with persistent internal storage is required')
    if consumer.get('environment', {}).get('APP_MODE') != 'consumer':
        raise ValueError('Separate Kafka consumer is required')
    for service in ('backend', 'event-consumer'):
        if config[service].get('environment', {}).get('KAFKA_BOOTSTRAP_SERVERS') != 'kafka:9092':
            raise ValueError('Kafka client must use the internal broker')
    expected = event_contract(plan)
    for name in ('docs/event-contract.json', 'scripts/event-contract.json', 'backend/event-contract.json'):
        if json.loads((project/name).read_text()) != expected:
            raise ValueError('Kafka event contract differs from frozen product plan: ' + name)


def validate_event_implementation(project):
    import json
    import re
    contract = project/'docs/event-contract.json'
    if not contract.exists(): return
    code = '\n'.join(p.read_text() for p in (project/'backend/Generated').rglob('*.cs'))
    if re.search(r'\bbusiness_(?:outbox|inbox|activity)\b', code, re.I):
        raise ValueError('Kafka business tables are trusted; use BusinessEvents.Enqueue')
    if json.loads(contract.read_text())['events'] and not re.search(r'\.Enqueue\s*\(', code):
        raise ValueError('Kafka business actions must call BusinessEvents.Enqueue')


def event_contract(plan):
    if hasattr(plan, 'model_dump'): plan = plan.model_dump()
    submitted = {a['endpointId'] for s in plan['screens'] for a in s['actions'] if a['kind'] == 'submit'}
    return {'schemaVersion': 1, 'topic': TOPIC, 'consumerGroup': 'activity-v1',
            'delivery': 'at-least-once', 'consumerEffect': 'persist actor-scoped activity history',
            'events': [{'endpointId': e['id'], 'eventType': e['id'] + '.completed',
                        'label': e['purpose'], 'requirementIds': e['requirementIds'],
                        'method': e['method'], 'path': e['path'],
                        'successfulStatuses': [r['status'] for r in e['responses'] if 200 <= r['status'] < 300]}
                       for e in plan['endpoints'] if e['method'] != 'GET' or e['id'] in submitted]}
