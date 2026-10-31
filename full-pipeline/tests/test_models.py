import copy
import importlib
from pathlib import Path

import pytest


def module():
    assert importlib.util.find_spec('shared.models') is not None, 'AppSpec and file boundary validation are not implemented'
    return importlib.import_module('shared.models')


def example_spec():
    return {
        'schemaVersion': 1, 'title': 'Service requests', 'slug': 'service-requests',
        'summary': 'Track requests and their status', 'roles': ['admin', 'user'],
        'requirements': [{'id': 'FR-01', 'description': 'Create a request', 'acceptance': ['Created request is persisted']}],
        'entities': [{'name': 'Ticket', 'fields': [{'name': 'title', 'type': 'string', 'required': True}]}],
        'workflows': [{'name': 'Create ticket', 'description': 'User submits title', 'requirementIds': ['FR-01']}],
        'capabilities': ['crud'], 'assumptions': [], 'questions': []
    }


def test_valid_spec_round_trip():
    m = module()
    spec = m.AppSpec.model_validate(example_spec())
    assert spec.model_dump()['entities'][0]['name'] == 'Ticket'
    assert spec.model_dump()['schemaVersion'] == 1


@pytest.mark.parametrize('change', ['traversal_slug', 'entity_identifier', 'duplicate_requirement', 'dangling_reference', 'unknown_type', 'duplicate_field'])
def test_invalid_spec_is_rejected(change):
    m = module()
    from pydantic import ValidationError
    value = copy.deepcopy(example_spec())
    if change == 'traversal_slug': value['slug'] = '../outside'
    if change == 'entity_identifier': value['entities'][0]['name'] = 'Ticket; DROP TABLE'
    if change == 'duplicate_requirement': value['requirements'].append(value['requirements'][0])
    if change == 'dangling_reference': value['workflows'][0]['requirementIds'] = ['FR-99']
    if change == 'unknown_type': value['entities'][0]['fields'][0]['type'] = 'shell'
    if change == 'duplicate_field': value['entities'][0]['fields'].append(value['entities'][0]['fields'][0])
    with pytest.raises(ValidationError):
        m.AppSpec.model_validate(value)


def test_critical_questions_are_explicit():
    m = module()
    value = example_spec()
    value['questions'] = [{'question': 'Which role may approve?', 'critical': True}]
    assert m.AppSpec.model_validate(value).critical_questions == ['Which role may approve?']


@pytest.mark.parametrize('path', ['../key', '/etc/passwd', 'a/../../key', 'C:\\keys.txt', 'a\\..\\key', '.'])
def test_paths_cannot_escape_run_root(tmp_path, path):
    m = module()
    with pytest.raises(ValueError): m.safe_path(tmp_path, path)


def test_symlink_escape_is_rejected(tmp_path):
    m = module()
    root = tmp_path / 'run'; root.mkdir()
    (root / 'out').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError): m.safe_path(root, 'out/secret')


def test_valid_nested_file_is_allowed(tmp_path):
    assert module().safe_path(tmp_path, 'docs/report.md') == tmp_path / 'docs' / 'report.md'
