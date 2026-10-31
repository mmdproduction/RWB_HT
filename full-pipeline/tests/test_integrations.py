"""Mock contracts, runtime isolation and generation boundaries; no external services."""
import copy
import json

import pytest

from shared.models import AppSpec
from templates.project import render_project


def integration_spec():
    return {'schemaVersion':1,'title':'Оплата','slug':'demo-payment','summary':'Демонстрационная оплата',
        'roles':['user'],'requirements':[{'id':'R1','description':'Оплатить заказ','acceptance':['Есть квитанция']}],
        'externalIntegrations':[{'id':'payments','name':'Оплата','kind':'payment','mode':'mock',
            'purpose':'Подтвердить оплату заказа без списания денег','requirementIds':['R1'],
            'operations':[{'id':'charge','description':'Демонстрационная оплата',
                'inputFields':[{'name':'amount','type':'number','required':True},{'name':'currency','type':'string','required':True}],
                'inputExample':{'amount':100,'currency':'RUB'},'response':{'status':'paid'}}]}]}


def test_contract_rejects_real_modes_bad_fixtures_and_unknown_requirements():
    assert AppSpec.model_validate(integration_spec()).externalIntegrations[0].mode=='mock'
    for mutation in ('live','unknown-requirement','wrong-input','empty-output','duplicate'):
        value=copy.deepcopy(integration_spec());provider=value['externalIntegrations'][0]
        if mutation=='live': provider['mode']='live'
        elif mutation=='unknown-requirement': provider['requirementIds']=['R404']
        elif mutation=='wrong-input': provider['operations'][0]['inputExample']['amount']='100'
        elif mutation=='empty-output': provider['operations'][0]['response']={}
        else: value['externalIntegrations'].append(copy.deepcopy(provider))
        with pytest.raises(ValueError): AppSpec.model_validate(value)


def test_renderer_emits_mock_manifest_and_isolates_runtime(tmp_path):
    root=tmp_path/'app';render_project(integration_spec(),root,'mock-contract')
    manifest=json.loads((root/'docs/mock-integrations.json').read_text())
    assert manifest['mode']=='mock' and manifest['providers'][0]['id']=='payments'
    compose=json.loads((root/'compose.yaml').read_text())
    assert compose['networks']['app']['internal'] is True
    assert compose['services']['backend']['networks']==['app']
    assert compose['services']['db']['networks']==['app']
    assert compose['services']['checks']['networks']==['app']
    assert set(compose['services']['frontend']['networks'])=={'app','default'}
    paths=json.loads((root/'docs/openapi.json').read_text())['paths']
    assert '/api/integrations/payments/charge' in paths


def test_generation_boundary_rejects_remote_calls_and_missing_provider_use(tmp_path):
    from shared.integrations import validate_generated_integrations
    root=tmp_path/'app';spec=AppSpec.model_validate(integration_spec())
    render_project(spec.model_dump(),root,'mock-contract')
    backend=root/'backend/Generated/Extensions.cs'
    backend.write_text('public class GeneratedExtensions { void Action() {} }')
    with pytest.raises(ValueError,match='MockIntegrationProviders'): validate_generated_integrations(root,spec)
    backend.write_text('MockIntegrationProviders mocks; var result = mocks.Call("payments", "charge");')
    (root/'frontend/src/app/generated/map.html').write_text('<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0L1 1"/></svg>')
    validate_generated_integrations(root,spec)
    backend.write_text('MockIntegrationProviders mocks; var result = mocks.Call(); new HttpClient();')
    with pytest.raises(ValueError,match='внешн'): validate_generated_integrations(root,spec)


def test_domain_acceptance_requires_declared_integration_coverage():
    from worker.engine import validate_acceptance
    spec=AppSpec.model_validate(integration_spec())
    tests=[{'name':'charge order','role':'user','requirementIds':['R1'],
        'steps':[{'method':'POST','path':'/api/generated/pay','body':{'amount':100},'status':200,'contains':{'status':'paid'}}]}]
    with pytest.raises(ValueError,match='integrationIds'): validate_acceptance(tests,spec)
    tests[0]['integrationIds']=['payments']
    tests.append({'name':'declined payment','role':'user','requirementIds':['R1'],'integrationIds':['payments'],
        'steps':[{'method':'POST','path':'/api/generated/pay','body':{'amount':100,'scenario':'declined'},'status':402,'contains':{'mode':'mock','error':'mock_declined'}}]})
    assert validate_acceptance(tests,spec)==tests


def test_integration_links_are_bound_from_requirements_without_inventing_scenarios():
    from worker.engine import bind_acceptance_integrations,validate_acceptance
    spec=AppSpec.model_validate(integration_spec())
    raw=[{'name':'paid','role':'user','requirementIds':['R1'],
        'steps':[{'method':'POST','path':'/api/generated/pay','body':{'amount':100},'status':200,'contains':{'status':'paid'}}]},
        {'name':'declined','role':'user','requirementIds':['R1'],
        'steps':[{'method':'POST','path':'/api/generated/pay','body':{'amount':100,'scenario':'declined'},'status':402,'contains':{'error':'mock_declined'}}]}]
    bound,audit=bind_acceptance_integrations(raw,spec)
    assert [test['integrationIds'] for test in bound]==[['payments'],['payments']]
    assert all(test['steps']==original['steps'] for test,original in zip(bound,raw))
    assert 'integrationIds' not in raw[0] and len(audit)==2
    assert validate_acceptance(bound,spec)==bound
    # Metadata alone cannot replace a missing positive/negative business scenario.
    with pytest.raises(ValueError,match='отказом'): validate_acceptance(bound[:1],spec)
    bound[0]['steps'][0]={'method':'POST','path':'/api/generated/pay','body':{},'status':204}
    with pytest.raises(ValueError,match='успешными'): validate_acceptance(bound,spec)


def test_integration_binding_does_not_guess_unrelated_or_invalid_links():
    from worker.engine import bind_acceptance_integrations
    spec=AppSpec.model_validate(integration_spec())
    raw=[{'name':'unrelated','requirementIds':['R2'],'steps':[]},
        {'name':'explicit invalid','requirementIds':['R1'],'integrationIds':['wrong-id'],'steps':[]}]
    bound,audit=bind_acceptance_integrations(raw,spec)
    assert bound[0].get('integrationIds',[])==[] and bound[1]['integrationIds']==['wrong-id'] and not audit
