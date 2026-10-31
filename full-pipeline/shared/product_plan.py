"""Validated design artifacts; application code cannot redefine the quality contract."""
import json
import re
from typing import Literal

from pydantic import Field, JsonValue, model_validator
from shared.models import Contract, AppSpec
from shared.product_contract import validate_schema, validate_value, endpoint_for, REFERENCE, capture_schema, validate_reference_types

ID=r'^[a-z][a-z0-9-]{0,59}$'


class PlannedResponse(Contract):
    status: int = Field(ge=200,le=503)
    description: str = Field(min_length=1,max_length=1000)
    bodySchema: dict[str,JsonValue]
    example: dict[str,JsonValue] | list[JsonValue]

    @model_validator(mode='after')
    def coherent(self):
        if self.status>=500 and self.status!=503: raise ValueError('Do not plan server crashes as expected behavior')
        validate_schema(self.bodySchema)
        if self.status!=204: validate_value(self.example,self.bodySchema,'response example')
        return self


class PlannedEndpoint(Contract):
    id: str = Field(pattern=ID)
    method: Literal['GET','POST','PUT','DELETE']
    path: str = Field(pattern=r'^/api/generated/[A-Za-z0-9_/{\}-]{1,200}$')
    purpose: str = Field(min_length=1,max_length=1500)
    requirementIds: list[str] = Field(min_length=1,max_length=100)
    integrationIds: list[str] = Field(default_factory=list,max_length=12)
    requestSchema: dict[str,JsonValue] = Field(default_factory=lambda:{'type':'object','properties':{}})
    responses: list[PlannedResponse] = Field(min_length=1,max_length=8)
    businessRules: list[str] = Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def coherent(self):
        if '..' in self.path or len({x.status for x in self.responses})!=len(self.responses): raise ValueError('Invalid endpoint')
        if not re.fullmatch(r'/api/generated/[A-Za-z0-9_/-]+',re.sub(r'\{[A-Za-z][A-Za-z0-9_]*\}','value',self.path)):
            raise ValueError('Invalid endpoint path parameter')
        validate_schema(self.requestSchema)
        if self.requestSchema['type']!='object': raise ValueError('Request must be a JSON object')
        if not any(200<=x.status<300 for x in self.responses): raise ValueError('Endpoint needs a successful response')
        return self


class UiControl(Contract):
    id: str = Field(pattern=ID)
    label: str = Field(min_length=1,max_length=120)
    kind: Literal['text','number','email','date','time','datetime-local','textarea','select','checkbox','output']
    purpose: str = Field(min_length=1,max_length=1000)
    options: list[str] = Field(default_factory=list,max_length=40)


class UiAction(Contract):
    id: str = Field(pattern=ID)
    label: str = Field(min_length=1,max_length=120)
    kind: Literal['submit','navigate','reset']
    endpointId: str | None = None
    primary: bool = False


class PlannedScreen(Contract):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1,max_length=120)
    purpose: str = Field(min_length=1,max_length=1500)
    requirementIds: list[str] = Field(min_length=1,max_length=100)
    layout: str = Field(min_length=1,max_length=2000)
    controls: list[UiControl] = Field(min_length=1,max_length=40)
    actions: list[UiAction] = Field(default_factory=list,max_length=20)
    states: list[str] = Field(min_length=1,max_length=12)


class ProductPlan(Contract):
    schemaVersion: Literal[1]
    visualDirection: str = Field(min_length=1,max_length=3000)
    dataConsistencyRules: list[str] = Field(min_length=1,max_length=20)
    screens: list[PlannedScreen] = Field(min_length=1,max_length=12)
    endpoints: list[PlannedEndpoint] = Field(min_length=1,max_length=32)

    @model_validator(mode='after')
    def coherent(self):
        endpoint_ids={x.id for x in self.endpoints}
        if len(endpoint_ids)!=len(self.endpoints): raise ValueError('Duplicate endpoint ID')
        if len({(e.method,e.path) for e in self.endpoints})!=len(self.endpoints): raise ValueError('Duplicate endpoint route')
        ids=[]
        for screen in self.screens:
            ids += [screen.id]+[x.id for x in screen.controls]+[x.id for x in screen.actions]
            for action in screen.actions:
                if action.endpointId is not None and action.endpointId not in endpoint_ids: raise ValueError('Unknown action endpoint')
                if action.kind=='submit' and action.endpointId is None: raise ValueError('Submit action requires endpointId')
        if len(set(ids))!=len(ids): raise ValueError('Every UI data-testid must be globally unique')
        if not any(a.primary and a.kind=='submit' for s in self.screens for a in s.actions): raise ValueError('Plan needs an obvious primary action')
        if len(json.dumps(self.model_dump(),ensure_ascii=False,allow_nan=False))>220000: raise ValueError('Product plan too large')
        return self

    def validate_spec(self,spec:AppSpec):
        ids={r.id for r in spec.requirements}; providers={p.id for p in spec.externalIntegrations}; covered=set(); used=set()
        for item in [*self.screens,*self.endpoints]:
            if set(item.requirementIds)-ids: raise ValueError('Product plan refers to unknown requirements')
            covered.update(item.requirementIds)
        for endpoint in self.endpoints:
            if set(endpoint.integrationIds)-providers: raise ValueError('Product plan refers to unknown integrations')
            used.update(endpoint.integrationIds)
        if ids-covered:
            missing=[r.model_dump() for r in spec.requirements if r.id not in covered]
            raise ValueError('Plan omits requirements: '+', '.join(sorted(ids-covered))+
                '\nEvery requirement must be linked in a relevant screen or endpoint requirementIds. '
                'Requirements implemented by the trusted shell still need a link: for demo login, '
                'link the requirement to the business screen gated by shell login and explain this in its purpose. '
                'Do not add a second login screen or a generated authentication endpoint. '
                'Do not remove requirements or attach unrelated IDs merely to satisfy coverage.'+
                '\nMISSING REQUIREMENTS:\n'+json.dumps(missing,ensure_ascii=False))
        if providers-used: raise ValueError('Plan omits mock integrations: '+', '.join(sorted(providers-used)))
        return self


def validate_quality_acceptance(http_tests,browser_tests,plan:ProductPlan,spec:AppSpec):
    raw=plan.model_dump(); covered_endpoints=set(); http_covered=set()
    for test in http_tests:
        variables={}
        for step in test['steps']:
            references=set(REFERENCE.findall(json.dumps([step['path'],step.get('body'),step.get('contains')])))
            if references-set(variables): raise ValueError('Acceptance uses an uncaptured variable')
            endpoint=endpoint_for(raw,step['method'],REFERENCE.sub('value',step['path']))
            response=next((r for r in endpoint['responses'] if r['status']==step['status']),None)
            if response is None: raise ValueError('Acceptance status absent from API contract')
            if step['status']!=204:
                validate_value(step.get('contains',{}),response['bodySchema'],'acceptance subset',partial=True,references=True)
                validate_reference_types(step.get('contains',{}),response['bodySchema'],variables)
            if 200<=step['status']<300:
                if step['method'] in ('POST','PUT'):
                    validate_value(step.get('body',{}),endpoint['requestSchema'],'acceptance request',references=True)
                    validate_reference_types(step.get('body',{}),endpoint['requestSchema'],variables)
                covered_endpoints.add(endpoint['id'])
                http_covered.update(set(test['requirementIds']) & set(endpoint['requirementIds']))
            for name,path in step.get('capture',{}).items(): variables[name]=capture_schema(response['bodySchema'],path)
    if {e.id for e in plan.endpoints}-covered_endpoints: raise ValueError('HTTP acceptance omits planned successful endpoints: '+', '.join(sorted({e.id for e in plan.endpoints}-covered_endpoints)))
    if not isinstance(browser_tests,list) or not 1<=len(browser_tests)<=20: raise ValueError('Need declarative browserTests before implementation')
    controls={c.id:c for s in plan.screens for c in s.controls}
    actions={a.id:a for s in plan.screens for a in s.actions}
    targets=set(controls)|set(actions)|{s.id for s in plan.screens}
    allowed_roles=set(spec.roles)|{'admin','driver',spec.interface_role}
    required={r.id for r in spec.requirements}; ui_covered=set(); primary_proved=False
    for test in browser_tests:
        if not isinstance(test,dict) or set(test)-{'name','role','requirementIds','steps','outcome'}: raise ValueError('Invalid browser scenario fields')
        if test.get('outcome') not in ('success','validation-error','provider-failure'): raise ValueError('Browser scenario needs explicit outcome')
        if not isinstance(test.get('name'),str) or not 1<=len(test['name'])<=200: raise ValueError('Browser scenario needs name')
        if not isinstance(test.get('role'),str) or test['role'] not in allowed_roles or not spec.requiresLogin and test['role']!=spec.interface_role: raise ValueError('Browser scenario must use actual UI role')
        refs=test.get('requirementIds')
        if not isinstance(refs,list) or not refs or any(not isinstance(x,str) or x not in required for x in refs): raise ValueError('Unknown browser requirementIds')
        steps=test.get('steps')
        if not isinstance(steps,list) or not 1<=len(steps)<=40: raise ValueError('Browser scenario needs 1..40 steps')
        clicked_primary=False; result_asserted=False
        for step in steps:
            if not isinstance(step,dict) or set(step)-{'action','testId','value'}: raise ValueError('Invalid browser step')
            action=step.get('action'); target=step.get('testId')
            if not isinstance(target,str) or not isinstance(action,str) or target not in targets or action not in {'fill','select','check','click','expectText','expectVisible'}: raise ValueError('Unknown browser action/target')
            if action in {'fill','select','expectText'} and (not isinstance(step.get('value'),str) or len(step['value'])>4000): raise ValueError('Browser step needs string value')
            if action=='expectText' and not step['value'].strip(): raise ValueError('Empty browser assertion')
            if action=='check' and type(step.get('value')) is not bool: raise ValueError('Check requires boolean')
            if action=='fill' and (target not in controls or controls[target].kind in {'select','checkbox','output'}): raise ValueError('Fill requires a native text-like control')
            if action=='select' and (target not in controls or controls[target].kind!='select'): raise ValueError('Select requires a native select control')
            if action=='check' and (target not in controls or controls[target].kind!='checkbox'): raise ValueError('Check requires checkbox control')
            if action=='click' and target not in actions: raise ValueError('Click requires a planned action')
            if action=='click' and target in actions and actions[target].primary: clicked_primary=True
            if clicked_primary and action=='expectText' and target in controls and controls[target].kind=='output': result_asserted=True
        if result_asserted and test['outcome']=='success': primary_proved=True
        if any(s.get('action')=='expectText' for s in steps): ui_covered.update(refs)
    if not primary_proved: raise ValueError('Browser acceptance must execute primary action and assert its business output')
    if required-(http_covered|ui_covered): raise ValueError('Acceptance omits requirements: '+', '.join(sorted(required-http_covered-ui_covered)))
    if len(json.dumps(browser_tests,allow_nan=False))>100000: raise ValueError('Browser acceptance too large')
    return browser_tests
