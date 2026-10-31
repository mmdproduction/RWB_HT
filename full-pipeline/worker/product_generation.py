"""Sequential product planning and component generation using one frozen contract."""
import json
import re
import shutil
from pathlib import Path

from shared.product_plan import ProductPlan, validate_quality_acceptance
from shared.integrations import validate_generated_integrations
from shared.events import event_contract, validate_event_implementation
from worker import prompts
from worker.llm import ModelError
from worker.tools import apply_patch, write_json
from worker.recovery import snapshot_sources, restore_sources, check_scope


def phase(engine,name,prompt,validate):
    feedback=''
    for attempt in range(1,4):
        # Public stages cannot move backwards in attempt number when a subphase changes.
        engine.attempt=max(engine.attempt,attempt)
        engine.event(engine.current,'running',name+' · попытка '+str(attempt))
        value=None
        try:
            value=engine.ask(prompt+feedback)
            write_json(engine.root/f'reports/quality/{name}-{attempt}.json',value)
            return validate(value)
        except (ValueError,ModelError) as error:
            message=str(error)
            write_json(engine.root/f'reports/quality/{name}-{attempt}-error.json',{'error':message})
            if isinstance(error,ModelError) and any(word in message for word in ('HTTP','недоступен','не завершил','не настроен','lease')): raise
            if attempt==3: raise
            feedback='\nPREVIOUS OUTPUT VALIDATION ERROR: '+message[:8000]
            if value is not None:
                feedback+='\nPREVIOUS PROPOSAL (correct it; preserve scope and frozen contracts):\n'+json.dumps(value,ensure_ascii=False)[:120000]
            engine.attempt=max(engine.attempt,attempt+1)
            engine.api.progress(engine.job,engine.current,engine.attempt,'running','Повтор этапа '+name,metrics={'retries':1})


def design_product(engine):
    spec=engine.spec
    def validate(value): return ProductPlan.model_validate(value).validate_spec(spec)
    plan=phase(engine,'product-design',prompts.product_design(spec.model_dump(),engine.job['requirements'],engine.context()),validate)
    engine.product_plan=plan
    raw=plan.model_dump()
    events=event_contract(raw)
    for path in (engine.project/'backend/event-contract.json',engine.project/'scripts/event-contract.json',
                 engine.project/'docs/event-contract.json',engine.root/'reports/event-contract.json'):
        write_json(path,events)
    for path in (engine.root/'product-plan.json',engine.root/'reports/product-plan.json',
                 engine.project/'docs/product-plan.json',engine.project/'scripts/product-plan.json'):
        write_json(path,raw)
    # The same frozen business contract is used by frontend, backend and acceptance.
    document=json.loads((engine.project/'docs/openapi.json').read_text())
    for endpoint in raw['endpoints']:
        operation={'operationId':endpoint['id'],'summary':endpoint['purpose'],
                   'security':[{'demoBearer':[]}], 'responses':{str(response['status']):{
                       'description':response['description'],**({'content':{'application/json':{
                           'schema':response['bodySchema'],'example':response['example']}}} if response['status']!=204 else {})}
                       for response in endpoint['responses']}}
        if endpoint['method'] in ('POST','PUT'):
            operation['requestBody']={'required':True,'content':{'application/json':{'schema':endpoint['requestSchema']}}}
        parameters=re.findall(r'\{([A-Za-z][A-Za-z0-9_]*)\}',endpoint['path'])
        if parameters: operation['parameters']=[{'name':name,'in':'path','required':True,'schema':{'type':'string'}} for name in parameters]
        if endpoint['id'] in {e['endpointId'] for e in events['events']}:
            for status,response in operation['responses'].items():
                if 200<=int(status)<300:
                    response['headers']={'X-Business-Event-Id':{'description':'Committed outbox event ID; processing is asynchronous',
                        'schema':{'type':'string','format':'uuid'}}}
        document['paths'].setdefault(endpoint['path'],{})[endpoint['method'].lower()]=operation
    document['x-messaging-contract']='event-contract.json'
    write_json(engine.project/'docs/openapi.json',document)
    with (engine.project/'README.md').open('a',encoding='utf-8') as readme:
        readme.write('\n\n## Product-specific implementation\n\nThe main screen is GeneratedPanel for every capability. No parking or CRUD screen is forced by the shell. UI/API design is saved in docs/product-plan.json and docs/openapi.json. Acceptance is planned before implementation and frozen; HTTP and browser scenarios are stored in scripts/domain-acceptance.json and scripts/browser-acceptance.json. Backend and frontend are generated sequentially against this contract. Browser acceptance uses isolated databases per viewport (360px and 1280px); screenshots and reports are saved in browser-results/. Browser automation checks behavior and layout overflow, not overall aesthetic quality.\n')
    return plan


def prepare_acceptance(engine):
    # Imported here to keep Engine's existing validator available without an import cycle.
    from worker.engine import bind_acceptance_roles, bind_acceptance_integrations, validate_acceptance
    plan=engine.product_plan
    def validate(value):
        if set(value)-{'acceptanceTests','browserTests'}: raise ValueError('Acceptance planner may return only acceptanceTests and browserTests')
        tests,roles=bind_acceptance_roles(value.get('acceptanceTests'),engine.spec)
        tests,integrations=bind_acceptance_integrations(tests,engine.spec)
        tests=validate_acceptance(tests,engine.spec)
        browser=validate_quality_acceptance(tests,value.get('browserTests'),plan,engine.spec)
        return {'acceptanceTests':tests,'browserTests':browser,'roleAudit':roles,'integrationAudit':integrations}
    result=phase(engine,'acceptance-plan',prompts.product_acceptance(engine.spec.model_dump(),plan.model_dump(),engine.job['requirements']),validate)
    write_json(engine.root/'reports/acceptance-plan.json',result)
    write_json(engine.root/'reports/acceptance-role-audit.json',result['roleAudit'])
    write_json(engine.root/'reports/acceptance-integration-audit.json',{'adjustments':result['integrationAudit'],'executionVerified':False})
    write_json(engine.project/'scripts/domain-acceptance.json',result['acceptanceTests'])
    write_json(engine.project/'scripts/browser-acceptance.json',result['browserTests'])
    here=Path(__file__).parent
    shutil.copyfile(here/'domain_checks.py',engine.project/'scripts/domain_checks.py')
    shutil.copyfile(here/'browser_checks.py',engine.project/'scripts/browser_checks.py')
    shutil.copyfile(here/'events_checks.py',engine.project/'scripts/events_checks.py')
    shutil.copyfile(here.parent/'shared/product_contract.py',engine.project/'scripts/product_contract.py')
    dockerfile=engine.project/'scripts/Dockerfile'
    dockerfile.write_text(dockerfile.read_text().replace('USER 65534:65534',
        'COPY scripts/domain_checks.py scripts/domain-acceptance.json scripts/product_contract.py scripts/product-plan.json scripts/events_checks.py scripts/event-contract.json ./\nUSER 65534:65534'))
    (engine.project/'scripts/Dockerfile.browser').write_text('''FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
RUN pip install --no-cache-dir playwright==1.64.1
WORKDIR /checks
COPY scripts/browser_checks.py scripts/browser-acceptance.json scripts/product_contract.py scripts/product-plan.json scripts/app-spec.json ./
ENV HOME=/tmp PYTHONUNBUFFERED=1
CMD ["python", "/checks/browser_checks.py"]
''')
    config=json.loads((engine.project/'compose.yaml').read_text())
    config['services']['browser_checks']={
        'build':{'context':'.','dockerfile':'scripts/Dockerfile.browser'},'profiles':['checks'],
        'environment':{'BASE_URL':'http://frontend','RESULTS_DIR':'/results'},'networks':['app'],
        'depends_on':{'frontend':{'condition':'service_healthy'}},'init':True,'read_only':True,
        'tmpfs':['/tmp:rw,size=512m'],'shm_size':'256mb','mem_limit':'1g','cap_drop':['ALL'],
        'security_opt':['no-new-privileges:true'],'volumes':['./browser-results:/results']}
    write_json(engine.project/'compose.yaml',config)
    results=engine.project/'browser-results';results.mkdir(exist_ok=True);results.chmod(0o777)
    ci=engine.project/'.gitlab-ci.yml'
    ci.write_text(QUALITY_CI)
    return result


def validate_ui_contract(project,plan):
    text='\n'.join(path.read_text() for path in (project/'frontend/src/app/generated').rglob('*') if path.is_file() and path.suffix in {'.ts','.html'})
    required={s.id for s in plan.screens}|{c.id for s in plan.screens for c in s.controls}|{a.id for s in plan.screens for a in s.actions}
    actual=set(re.findall(r'''data-testid\s*=\s*["']([a-z][a-z0-9-]*)["']''',text))
    if required-actual: raise ValueError('Frontend omits planned data-testid: '+', '.join(sorted(required-actual)))


def generate_components(engine):
    engine.assert_checks()
    acceptance={'acceptanceTests':json.loads((engine.project/'scripts/domain-acceptance.json').read_text()),
                'browserTests':json.loads((engine.project/'scripts/browser-acceptance.json').read_text())}
    merged=[];notes=[]
    for component in ('backend','frontend'):
        def validate(value):
            if not isinstance(value.get('implementationNotes',[]),list) or any(not isinstance(note,str) for note in value.get('implementationNotes',[])): raise ValueError('implementationNotes must be strings')
            if set(value)-{'files','implementationNotes'}: raise ValueError('Implementation cannot redefine acceptance or design')
            check_scope(value,{component})
            required='backend/Generated/Extensions.cs' if component=='backend' else 'frontend/src/app/generated/generated-panel.ts'
            if required not in {item.get('path') for item in value.get('files',[])}: raise ValueError('Missing component entry point: '+required)
            snapshot=snapshot_sources(engine.project)
            try:
                apply_patch(engine.project,value)
                validate_generated_integrations(engine.project,engine.spec)
                if component=='backend': validate_event_implementation(engine.project)
                if component=='frontend': validate_ui_contract(engine.project,engine.product_plan)
                engine.assert_checks()
            except Exception:
                restore_sources(engine.project,snapshot)
                raise
            return value
        result=phase(engine,'generate-'+component,prompts.product_implementation(component,engine.spec.model_dump(),
                     engine.product_plan.model_dump(),acceptance,engine.job['requirements'],engine.context()),validate)
        merged.extend(result['files']);notes.extend(result.get('implementationNotes',[]))
    write_json(engine.root/'reports/generation.json',{'files':merged,'implementationNotes':notes,
        'acceptanceTests':acceptance['acceptanceTests'],'browserTests':acceptance['browserTests'],
        'mode':'contract-first-sequential','acceptanceFrozenBeforeCode':True})


QUALITY_CI = '''image: docker:27-cli
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
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm checks python /checks/domain_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm checks python /checks/events_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e BUSINESS_USAGE_ONLY=1 checks python /checks/integration_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" restart kafka backend event-consumer
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait backend
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e PERSISTENCE_ONLY=1 checks python /checks/events_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e PERSISTENCE_ONLY=1 checks python /checks/integration_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" down -v --remove-orphans
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm checks python /checks/integration_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm checks
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" restart backend
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait backend
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e PERSISTENCE_ONLY=1 checks python /checks/integration_checks.py
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e PERSISTENCE_ONLY=1 checks
    - mkdir -p browser-results && chmod 777 browser-results
    - |
      set -e
      for width in 360 1280; do
        docker compose -p "rwb_ci_${CI_PIPELINE_ID}" down -v --remove-orphans
        docker compose -p "rwb_ci_${CI_PIPELINE_ID}" up -d --wait
        docker compose -p "rwb_ci_${CI_PIPELINE_ID}" run --rm -e VIEWPORT_WIDTH=$width browser_checks
      done
  after_script:
    - export DB_PASSWORD="ci-${CI_PIPELINE_ID}-${CI_JOB_ID}"
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" logs --no-color > compose.log
    - docker compose -p "rwb_ci_${CI_PIPELINE_ID}" down -v --remove-orphans
  artifacts:
    when: always
    paths: [compose.log, docs/openapi.json, docs/product-plan.json, docs/event-contract.json, app-spec.json, browser-results/, event-results/]
'''
