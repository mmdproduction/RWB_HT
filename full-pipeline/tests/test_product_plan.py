import copy
import json
from types import SimpleNamespace

import pytest

from shared.models import AppSpec
from shared.product_plan import ProductPlan
from worker.product_generation import phase
from worker.prompts import product_design


def task_spec():
    return AppSpec.model_validate({
        'schemaVersion': 1, 'title': 'Задачи', 'slug': 'tasks',
        'summary': 'Задачи команды', 'requiresLogin': True, 'roles': ['admin', 'user'],
        'requirements': [
            {'id': 'REQ-AUTH-01', 'description': 'Демо-вход с выбором роли admin или user.',
             'acceptance': ['После выбора роли открывается приложение с соответствующими правами.']},
            {'id': 'REQ-TASK-01', 'description': 'Администратор создает задачу.',
             'acceptance': ['Название созданной задачи отображается в списке.']},
        ],
    })


def task_plan():
    return {
        'schemaVersion': 1, 'visualDirection': 'Читаемый список задач',
        'dataConsistencyRules': ['Задачи сохраняются в PostgreSQL.'],
        'screens': [{
            'id': 'tasks', 'name': 'Задачи', 'purpose': 'Создание и просмотр задач',
            'requirementIds': ['REQ-TASK-01'], 'layout': 'Форма над списком',
            'controls': [
                {'id': 'task-title', 'label': 'Название', 'kind': 'text', 'purpose': 'Название задачи'},
                {'id': 'task-result', 'label': 'Результат', 'kind': 'output', 'purpose': 'Созданная задача'},
            ],
            'actions': [{'id': 'create-task', 'label': 'Создать', 'kind': 'submit',
                         'endpointId': 'create-task', 'primary': True}],
            'states': ['empty', 'loading', 'success', 'error'],
        }],
        'endpoints': [{
            'id': 'create-task', 'method': 'POST', 'path': '/api/generated/tasks',
            'purpose': 'Создать задачу', 'requirementIds': ['REQ-TASK-01'],
            'requestSchema': {'type': 'object', 'properties': {'title': {'type': 'string'}},
                              'required': ['title'], 'additionalProperties': False},
            'responses': [{'status': 201, 'description': 'Задача создана',
                           'bodySchema': {'type': 'object', 'properties': {'title': {'type': 'string'}},
                                          'required': ['title'], 'additionalProperties': False},
                           'example': {'title': 'Подготовить демо'}}],
            'businessRules': ['Только admin создает задачи.'],
        }],
    }


def test_missing_login_requirement_reports_definition_and_acceptance_for_repair():
    spec = task_spec()
    with pytest.raises(ValueError) as error:
        ProductPlan.model_validate(task_plan()).validate_spec(spec)
    message = str(error.value)
    assert message.startswith('Plan omits requirements: REQ-AUTH-01')
    # The model needs the actual missing contract, not a guess based on its ID.
    missing = json.loads(message.split('\nMISSING REQUIREMENTS:\n', 1)[1])
    assert missing == [spec.requirements[0].model_dump()]


def test_login_can_be_linked_to_screen_gated_by_existing_shell():
    value = task_plan()
    value['screens'][0]['requirementIds'].append('REQ-AUTH-01')
    value['screens'][0]['purpose'] += '; открывается после входа через оболочку'
    plan = ProductPlan.model_validate(value).validate_spec(task_spec())
    assert len(plan.screens) == 1
    assert [e.path for e in plan.endpoints] == ['/api/generated/tasks']


def test_unknown_requirement_still_rejected():
    value = task_plan()
    value['screens'][0]['requirementIds'] += ['REQ-AUTH-01', 'UNKNOWN']
    with pytest.raises(ValueError, match='unknown requirements'):
        ProductPlan.model_validate(value).validate_spec(task_spec())


def test_design_retry_preserves_missing_requirement_details_in_model_feedback(tmp_path):
    spec = task_spec()
    prompts = []
    proposal = task_plan()

    def ask(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return copy.deepcopy(proposal)
        feedback = prompt.split('PREVIOUS OUTPUT VALIDATION ERROR: ', 1)[1]
        # Simulate the external model consuming the repair contract.
        missing_json = feedback.split('\nMISSING REQUIREMENTS:\n', 1)[1].split(
            '\nPREVIOUS PROPOSAL', 1)[0]
        missing = json.loads(missing_json)
        corrected = copy.deepcopy(proposal)
        corrected['screens'][0]['requirementIds'].extend(item['id'] for item in missing)
        corrected['screens'][0]['purpose'] += '; после входа через оболочку'
        return corrected

    engine = SimpleNamespace(
        attempt=1, current='design', root=tmp_path, job={'runId': 'test'},
        event=lambda *args: None, ask=ask,
        api=SimpleNamespace(progress=lambda *args, **kwargs: None),
    )
    plan = phase(engine, 'product-design', product_design(spec.model_dump(), 'Создай задачи', ''),
                 lambda value: ProductPlan.model_validate(value).validate_spec(spec))
    assert plan.screens[0].requirementIds == ['REQ-TASK-01', 'REQ-AUTH-01']
    assert len(prompts) == 2
    assert proposal['screens'][0]['requirementIds'] == ['REQ-TASK-01']
    report = json.loads((tmp_path / 'reports/quality/product-design-1-error.json').read_text())
    assert spec.requirements[0].description in report['error']
