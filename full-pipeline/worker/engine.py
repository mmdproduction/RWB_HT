import json
import copy
import math
from pathlib import Path
import re
import shutil
import threading
from uuid import UUID

import httpx

from shared.models import AppSpec, STAGES, redact
from shared.provenance import restore_source_quotes
from shared.integrations import validate_generated_integrations, assert_mock_runtime
from templates.project import render_project
from worker import prompts
from worker.product_generation import design_product, prepare_acceptance, generate_components, validate_ui_contract
from shared.product_contract import REFERENCE
from worker.documents import documents, source_archive
from worker.llm import ModelClient, ModelError
from worker.tools import apply_patch, run_command, ToolError, write_json, command_json
from worker.recovery import (source_hash, acceptance_hash, snapshot_sources, restore_sources,
                             check_scope, infrastructure_failure, transient_network_failure, failure_components)


class Blocked(RuntimeError): pass


def bind_acceptance_roles(value,spec):
    """Execution identity belongs to the trusted UI policy, not to model output."""
    bound=copy.deepcopy(value)
    audit=[]
    if not spec.requiresLogin and isinstance(bound,list):
        for test in bound:
            if not isinstance(test,dict): continue
            if test.get('role')!=spec.interface_role:
                audit.append({'scenario':test.get('name'),'modelRole':test.get('role'),'executionRole':spec.interface_role})
                test['role']=spec.interface_role
    return bound,audit


def bind_acceptance_integrations(value,spec):
    """Traceability links only: real provider calls are checked independently at runtime."""
    bound=copy.deepcopy(value)
    audit=[]
    known={provider.id for provider in spec.externalIntegrations}
    if isinstance(bound,list):
        for test in bound:
            if not isinstance(test,dict): continue
            requirements=test.get('requirementIds')
            references=test.get('integrationIds',[])
            if not isinstance(requirements,list) or any(not isinstance(x,str) for x in requirements): continue
            if not isinstance(references,list) or any(not isinstance(x,str) for x in references) or set(references)-known: continue
            linked={p.id for p in spec.externalIntegrations if set(p.requirementIds)&set(requirements)}
            added=linked-set(references)
            if added:
                test['integrationIds']=sorted(set(references)|linked)
                audit.append({'scenario':test.get('name'),'requirementIds':requirements,'addedIntegrationIds':sorted(added),
                    'reason':'Shared requirementIds; metadata binding is not proof of provider execution'})
    return bound,audit


def validate_acceptance(value,spec):
    if not isinstance(value,list) or not 1<=len(value)<=20: raise ValueError('Нужны предметные HTTP acceptanceTests')
    ids={r.id for r in spec.requirements}
    integration_ids={provider.id for provider in spec.externalIntegrations}
    covered_integrations=set()
    failure_integrations=set()
    roles=set(spec.roles)|{'admin','driver'}
    public_role=spec.interface_role
    if not spec.requiresLogin: roles.add(public_role)
    for test in value:
        if not isinstance(test,dict): raise ValueError('Сценарий должен быть JSON object')
        if not isinstance(test.get('name'),str) or not 1<=len(test['name'])<=200: raise ValueError('Имя сценария не задано')
        if not isinstance(test.get('role'),str) or test['role'] not in roles: raise ValueError('Неизвестная роль теста')
        if not spec.requiresLogin and test['role']!=public_role:
            raise ValueError(f'Публичное приложение должно проверяться с ролью интерфейса {public_role}, а не admin')
        if not isinstance(test.get('requirementIds'),list) or not test['requirementIds'] or any(not isinstance(item,str) or item not in ids for item in test['requirementIds']): raise ValueError('Тест ссылается на неизвестные требования')
        references=test.get('integrationIds',[])
        if not isinstance(references,list) or any(not isinstance(item,str) for item in references) or set(references)-integration_ids:
            raise ValueError('Некорректные integrationIds в предметной приемке')
        if not isinstance(test.get('steps'),list) or not 1<=len(test['steps'])<=20: raise ValueError('Нужны HTTP steps')
        for step in test['steps']:
            if not isinstance(step,dict): raise ValueError('HTTP step должен быть JSON object')
            captures=step.get('capture',{})
            if not isinstance(captures,dict) or len(captures)>10 or any(not isinstance(key,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,47}',key) or not isinstance(path,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*){0,7}',path) for key,path in captures.items()):
                raise ValueError('Invalid acceptance capture')
            if step.get('method') not in {'GET','POST','PUT','DELETE'}: raise ValueError('Недопустимый HTTP method')
            if step['method'] in {'POST','PUT'} and ('body' not in step or not isinstance(step['body'],(dict,list))):
                raise ValueError(f"Сценарий {test['name']}: {step['method']} {step.get('path','')} требует явного JSON body с входными данными; для запроса без параметров укажите body: {{}}")
            if not isinstance(step.get('path'),str) or not re.fullmatch(r'/api/generated/[A-Za-z0-9_/?=&.%+-]{1,300}',REFERENCE.sub('value',step['path'])) or '..' in step['path']:
                raise ValueError('Acceptance endpoint должен быть внутри /api/generated/')
            if type(step.get('status')) is not int or not (200<=step['status']<=499 or step['status']==503): raise ValueError('Неверный HTTP status')
            if captures and not 200<=step['status']<300: raise ValueError('Capture requires successful response')
            if step['status']==204 and (step.get('contains') or captures): raise ValueError('204 has no JSON body, assertions or captured values')
            if not isinstance(step.get('contains',{}),(dict,list)): raise ValueError('contains должен быть JSON object/array')
            if 200<=step['status']<300 and step['status']!=204 and not step.get('contains'):
                raise ValueError(f"Сценарий {test['name']}: успешный ответ должен проверять бизнес-результат в contains")
        if any(200<=step['status']<300 and step.get('contains') for step in test['steps']): covered_integrations.update(references)
        if any(step['status'] in (402,422,503) and step.get('contains') for step in test['steps']): failure_integrations.update(references)
    if len(json.dumps(value))>100000: raise ValueError('Слишком большой набор тестов')
    if integration_ids-covered_integrations:
        raise ValueError('Приемка должна покрывать integrationIds успешными бизнес-сценариями: '+', '.join(sorted(integration_ids-covered_integrations)))
    if integration_ids-failure_integrations:
        raise ValueError('Приемка должна покрывать integrationIds отказом mock-провайдера (402/422/503): '+', '.join(sorted(integration_ids-failure_integrations)))
    return value


class Engine:
    def __init__(self,settings,api,job,model=None,runner=run_command,cancelled=None):
        self.settings,self.api,self.job=settings,api,job
        self.root=settings.artifact_root/str(UUID(job['runId']))
        self.project=self.root/'project'
        self.cancelled=cancelled or threading.Event()
        self.model=model or ModelClient(settings,cancelled=self.cancelled,on_retry=self.qwen_retry)
        self.runner=runner
        self.model_requests=0
        self.spec=None; self.product_plan=None; self.results=[]; self.current='analysis'; self.attempt=1
        self.states={};self.app_url=None;self.repairs=0;self.completed=False
        self.repair_counts={'build':0,'test':0}
        self.stage_attempts={}
        self.built_hash=None;self.tested_hash=None;self.deployed_hash=None;self.frozen_checks=None
        self.compose=['docker','compose','-p','rwb-checks-'+job['runId'].replace('-','')[:16]]
        self.test_compose=self.compose.copy()

    def event(self,stage,status,message='',**extra):
        if self.cancelled.is_set(): raise Blocked('Worker lease утрачен; выполнение остановлено')
        self.states[stage]=status
        self.stage_attempts[stage]=self.attempt
        self.api.progress(self.job,stage,self.attempt,status,redact(message,self.settings.secrets),**extra)

    def qwen_retry(self,next_attempt,total_attempts,delay):
        self.event(self.current,'running',f'Qwen занят (HTTP 429). Повтор HTTP-запроса {next_attempt}/{total_attempts} через {math.ceil(delay)} с; текущий этап сохраняется')

    def ask(self,prompt):
        self.model_requests+=1
        usage=None
        try:
            value,usage=self.model.ask(prompts.SYSTEM,prompt)
            return value
        except ModelError:
            if self.cancelled.is_set(): raise Blocked('Worker lease утрачен; ожидание Qwen отменено') from None
            raise
        finally:
            usage=usage or self.model.last_usage
            attempts=getattr(self.model,'attempts',None)
            if attempts is not None:
                write_json(self.root/f'reports/qwen-call-{self.model_requests:02}.json',{'attempts':attempts,'metrics':usage})
            if usage and not self.cancelled.is_set():
                self.api.progress(self.job,self.current,self.attempt,'running','Qwen: учтен фактический вызов',metrics=usage)

    def command(self,name,args,timeout=None,cwd=None):
        if self.cancelled.is_set(): raise Blocked('Worker lease утрачен; выполнение остановлено')
        self.api.progress(self.job,self.current,self.attempt,'running','Выполняется '+name)
        try:
            kwargs=({'cancel':self.cancelled,'env':{'TEST_CLOCK_ENABLED':'true'} if self.compose==self.test_compose else {}} if self.runner is run_command else {})
            result=self.runner(args,cwd or self.project,timeout or self.settings.command_timeout,**kwargs)
        except (ToolError,OSError) as error:
            result={'command':args,'returnCode':-1,'output':str(error),'durationSeconds':None}
        result['output']=redact(result['output'],self.settings.secrets)
        index=len(self.results)+1
        report=f'reports/{index:02}-{name}.json'
        write_json(self.root/report,result)
        log=self.root/report.replace('.json','.log');log.write_text(result['output'],encoding='utf-8')
        self.results.append({'name':name,'report':report,**{k:v for k,v in result.items() if k!='output'}})
        self.api.progress(self.job,self.current,self.attempt,'running',name+': returnCode='+str(result['returnCode']),
            logs=[result['output'][-18000:] or '(нет вывода)'],artifacts=[{'name':name+' — отчет','kind':'check','path':report},{'name':name+' — лог','kind':'log','path':report.replace('.json','.log')}])
        return result

    def require(self,result):
        if result['returnCode']!=0: raise ToolError(result['output'][-18000:])

    def context(self):
        files=['backend/Program.cs','backend/schema.sql','backend/Generated/Extensions.cs','frontend/src/app/generated/generated-panel.ts','frontend/src/app/product-api.ts','docs/mock-integrations.md']
        if (self.project/'docs/event-contract.json').exists(): files.append('docs/event-contract.json')
        if any('parking' in cap.lower() for cap in self.spec.capabilities): files.append('backend/Parking.cs')
        if (self.project/'docs/product-plan.json').exists(): files.append('docs/product-plan.json')
        context='\n'.join('FILE '+name+'\n'+(self.project/name).read_text() for name in files)
        app=(self.project/'frontend/src/app/app.ts').read_text()
        # Only token/login code is needed; the rest of the shell is immutable.
        return context+'\nFRONTEND SHELL (read only):\n'+app[:10000]

    def assert_checks(self):
        if self.product_plan is not None:
            from shared.events import assert_event_runtime
            assert_event_runtime(self.project,self.product_plan)
        if self.frozen_checks and acceptance_hash(self.project)!=self.frozen_checks:
            raise ToolError('Приемочные проверки изменились после генерации; продолжение запрещено')

    def stop_on_infrastructure(self,output):
        if infrastructure_failure(output):
            raise Blocked('Сбой инфраструктуры; исходники не изменяются.\n'+output[-12000:])

    def build_command(self,name,args):
        # Only idempotent builds are retried; no Qwen calls or public attempt increment.
        for index in range(3):
            result=self.command(name if index==0 else f'{name}-network-retry-{index}',args)
            if result['returnCode']==0: return result
            if not transient_network_failure(result['output']):
                self.stop_on_infrastructure(result['output'])
                return result
            if index==2:
                raise Blocked('Сеть сборки недоступна после трех попыток; исходники не изменяются. '
                    'Проверьте доступ Docker к registry и повторите запуск.\n'+result['output'][-12000:])
            delay=(5,15)[index]
            self.api.progress(self.job,self.current,self.attempt,'running',
                f'Временный сетевой сбой сборки. Повтор {index+2}/3 через {delay} с; исходники не изменяются')
            if self.cancelled.wait(delay): raise Blocked('Worker lease утрачен; повтор сборки отменен')

    def repair(self,diagnostic):
        from shared.events import validate_event_implementation
        stage=self.current
        if stage not in self.repair_counts: raise ToolError('Автоисправление не разрешено на стадии '+stage)
        self.stop_on_infrastructure(diagnostic)
        targets=failure_components(diagnostic)
        original_failure=diagnostic
        while self.repair_counts[stage]<2:
            self.repair_counts[stage]+=1;self.repairs+=1
            self.attempt=self.repair_counts[stage]+1
            number=self.repair_counts[stage]
            self.event(stage,'running',f'Автоисправление {number}/2: '+', '.join(sorted(targets)),metrics={'retries':1})
            self.assert_checks()
            snapshot=snapshot_sources(self.project)
            before=source_hash(self.project)
            files={name:content.decode('utf-8') for name,content in snapshot.items()}
            acceptance=json.loads((self.project/'scripts/domain-acceptance.json').read_text())
            foundation='\n'.join('FILE '+name+'\n'+(self.project/name).read_text() for name in
                ['backend/Program.cs','backend/schema.sql','frontend/src/app/product-api.ts','docs/mock-integrations.md'])
            report={'stage':stage,'attempt':number,'allowedComponents':sorted(targets),'beforeHash':before,'status':'proposed'}
            report_path=self.root/f'reports/repair-transactions/{stage}-{number}.json'
            committed=False
            try:
                prompt=prompts.repair(self.spec.model_dump(),files,diagnostic,acceptance,self.job['requirements'],foundation)
                prompt+='\nFROZEN PRODUCT PLAN:\n'+json.dumps(self.product_plan.model_dump() if self.product_plan else {},ensure_ascii=False)
                if (self.project/'docs/event-contract.json').exists(): prompt+='\nFROZEN KAFKA CONTRACT:\n'+(self.project/'docs/event-contract.json').read_text()
                prompt+='\nFROZEN BROWSER ACCEPTANCE:\n'+(self.project/'scripts/browser-acceptance.json').read_text() if self.product_plan else ''
                prompt+='\nALLOWED REPAIR COMPONENTS: '+', '.join(sorted(targets))+'. Do not change files belonging to any other component.'
                patch=self.ask(prompt)
                write_json(self.root/f'reports/repair-{stage}-{number}.json',patch)
                check_scope(patch,targets)
                report['changedPaths']=apply_patch(self.project,patch)
                validate_generated_integrations(self.project,self.spec)
                validate_event_implementation(self.project)
                if self.product_plan is not None: validate_ui_contract(self.project,self.product_plan)
                self.assert_checks()
                candidate=source_hash(self.project)
                report['candidateHash']=candidate
                if candidate==before: raise ValueError('Предложенная правка не изменила исходники')
                result=self.build_command('repair-candidate-build',self.compose+['--profile','checks','build'])
                report['buildReturnCode']=result['returnCode']
                if result['returnCode']!=0:
                    self.stop_on_infrastructure(result['output'])
                    targets|=failure_components(result['output'])
                    raise ValueError('Кандидат не компилируется; он будет отменен.\n'+result['output'][-14000:])
                self.built_hash=candidate;self.tested_hash=None;self.deployed_hash=None
                committed=True
                report['status']='compiled_pending_acceptance'
                self.event(stage,'running','Правка компилируется; далее обязательна повторная приемка')
                return
            except (ValueError,ModelError) as error:
                report['status']='rejected_and_restored'
                report['reason']=redact(str(error),self.settings.secrets)[-18000:]
                diagnostic=original_failure+'\nPREVIOUS CANDIDATE WAS REJECTED AND SOURCES RESTORED:\n'+str(error)[-14000:]
                restore_sources(self.project,snapshot)
                if isinstance(error,ModelError) and any(part in str(error) for part in ('HTTP','недоступен','не настроен','не завершил HTTP')):
                    raise Blocked(str(error)) from None
                self.api.progress(self.job,stage,self.attempt,'running','Неудачная правка отменена; исходники восстановлены',logs=[report['reason']])
            finally:
                if not committed: restore_sources(self.project,snapshot)
                if report['status']=='proposed': report['status']='aborted_and_restored'
                write_json(report_path,report)
        raise ToolError(f'Исчерпаны две попытки исправления стадии {stage}; последняя неуспешная правка отменена.\n'+diagnostic[-12000:])

    def build(self):
        while True:
            self.assert_checks()
            if self.spec is not None:
                validate_generated_integrations(self.project,self.spec)
                assert_mock_runtime(self.project)
            fingerprint=source_hash(self.project)
            if self.built_hash==fingerprint: return
            result=self.build_command('build',self.compose+['--profile','checks','build'])
            if result['returnCode']==0:
                self.built_hash=fingerprint
                return
            self.stop_on_infrastructure(result['output'])
            self.event(self.current,'failed','Сборка не прошла; диагностический лог сохранен')
            self.repair(result['output'])

    def test(self):
        while True:
            self.assert_checks()
            self.build()
            # Dedicated disposable DB for each acceptance attempt; never deploy its clock/tokens/fixtures.
            self.require(self.command('reset-test-environment',self.compose+['down','-v','--remove-orphans']))
            result=self.command('start-for-tests',self.compose+['up','-d','--wait','--wait-timeout','180'])
            if result['returnCode']==0:
                result=self.command('mock-contracts',self.compose+['--profile','checks','run','--rm','checks','python','/checks/integration_checks.py'])
            if result['returnCode']==0:
                result=self.command('domain-acceptance',self.compose+['--profile','checks','run','--rm','checks','python','/checks/domain_checks.py'])
            if result['returnCode']==0 and self.product_plan is not None:
                result=self.command('kafka-business-delivery',self.compose+['--profile','checks','run','--rm','checks','python','/checks/events_checks.py'])
            if result['returnCode']==0:
                result=self.command('mock-business-usage',self.compose+['--profile','checks','run','--rm','-e','BUSINESS_USAGE_ONLY=1','checks','python','/checks/integration_checks.py'])
            if result['returnCode']==0 and self.product_plan is not None:
                result=self.command('domain-restart-persistence',self.compose+['restart','kafka','backend','event-consumer'])
                if result['returnCode']==0: result=self.command('domain-wait-after-restart',self.compose+['up','-d','--wait','--wait-timeout','180'])
                if result['returnCode']==0: result=self.command('kafka-restart-redelivery',self.compose+['--profile','checks','run','--rm','-e','PERSISTENCE_ONLY=1','checks','python','/checks/events_checks.py'])
                if result['returnCode']==0: result=self.command('domain-mock-persistence',self.compose+['--profile','checks','run','--rm','-e','PERSISTENCE_ONLY=1','checks','python','/checks/integration_checks.py'])
                if result['returnCode']==0: result=self.command('reset-base-fixture',self.compose+['down','-v','--remove-orphans'])
                if result['returnCode']==0: result=self.command('start-base-fixture',self.compose+['up','-d','--wait','--wait-timeout','180'])
                if result['returnCode']==0: result=self.command('base-mock-contracts',self.compose+['--profile','checks','run','--rm','checks','python','/checks/integration_checks.py'])
            if result['returnCode']==0:
                result=self.command('base-acceptance',self.compose+['--profile','checks','run','--rm','checks'])
            if result['returnCode']==0:
                result=self.command('restart-persistence',self.compose+['restart','backend'])
            if result['returnCode']==0:
                result=self.command('wait-after-restart',self.compose+['up','-d','--wait','--wait-timeout','180'])
            if result['returnCode']==0:
                result=self.command('mock-persistence',self.compose+['--profile','checks','run','--rm','-e','PERSISTENCE_ONLY=1','checks','python','/checks/integration_checks.py'])
            if result['returnCode']==0:
                result=self.command('persistence-acceptance',self.compose+['--profile','checks','run','--rm','-e','PERSISTENCE_ONLY=1','checks'])
            if result['returnCode']==0 and self.product_plan is not None:
                for width in (360,1280):
                    result=self.command(f'reset-browser-fixture-{width}',self.compose+['down','-v','--remove-orphans'])
                    if result['returnCode']==0: result=self.command(f'start-browser-fixture-{width}',self.compose+['up','-d','--wait','--wait-timeout','180'])
                    if result['returnCode']==0: result=self.command(f'browser-acceptance-{width}',self.compose+['--profile','checks','run','--rm','-e',f'VIEWPORT_WIDTH={width}','browser_checks'])
                    if result['returnCode']!=0: break
            if result['returnCode']==0:
                self.assert_checks()
                self.tested_hash=source_hash(self.project)
                if self.tested_hash!=self.built_hash: raise ToolError('Исходники изменились во время приемки')
                self.api.progress(self.job,'build',self.stage_attempts.get('build',1),'passed','Актуальные исходники скомпилированы и прошли повторную приемку')
                return
            self.stop_on_infrastructure(result['output'])
            result=self.runtime_diagnostic(result)
            self.event('test','failed','Приемка не прошла; диагностический лог сохранен')
            self.repair(result['output'])
            self.event('test','running','Повтор всей приемки после принятого исправления')

    def runtime_diagnostic(self,result):
        # Preserve the process exception for startup, API and post-restart failures alike.
        logs=self.command('runtime-service-logs',self.compose+['logs','--no-color','--tail','120','backend','db','frontend','kafka','event-consumer'],timeout=30)
        state=self.command('runtime-service-state',self.compose+['ps','--all','--format','json'],timeout=30)
        return {**result,'output':result['output']+'\nACTUAL SERVICE LOGS:\n'+logs['output']+'\nCONTAINER STATE:\n'+state['output']}

    def security(self):
        # Fixed audit commands; model source does not choose them. Mount source read-only.
        npm=self.command('npm-audit',['docker','run','--rm','-v',str(self.project/'frontend')+':/source:ro','-w','/tmp/audit','node:24-bookworm-slim',
            'sh','-c','cp /source/package*.json . && npm audit --omit=dev --json'],timeout=240)
        try:
            audit=command_json(npm['output'],{'metadata','vulnerabilities'})
        except ValueError: raise Blocked('npm audit не удалось выполнить; см. отчет')
        dotnet=self.command('dotnet-audit',['docker','run','--rm','-v',str(self.project/'backend')+':/source:ro','-w','/tmp/audit','mcr.microsoft.com/dotnet/sdk:10.0',
            'sh','-c','cp -r /source/. . && dotnet restore --verbosity quiet >/tmp/restore.log 2>&1 && dotnet list package --vulnerable --include-transitive --format json'],timeout=300)
        if dotnet['returnCode']!=0 or 'projects' not in dotnet['output']:
            raise Blocked('Аудит NuGet не выполнен; см. dotnet-audit')
        scanned=0
        for path in self.project.rglob('*'):
            if not path.is_file() or path.name=='.env' or path.stat().st_size>2000000: continue
            if any(part in {'node_modules','dist','obj','bin','.angular'} for part in path.parts): continue
            text=path.read_text(errors='replace');scanned+=1
            if any(secret and len(secret)>8 and secret in text for secret in self.settings.secrets):
                raise ToolError('Обнаружен секрет платформы в '+str(path.relative_to(self.project)))
        report={'policy':'hackathon informational dependency audit; platform secret leakage blocks deployment',
            'filesScanned':scanned,'npmVulnerabilities':audit['metadata'].get('vulnerabilities'),
            'demoAuthentication':True,'externalGitLabExecuted':False,'limits':'Public untrusted use is unsupported; fixed-version vulnerabilities require manual disposition.'}
        write_json(self.root/'reports/security.json',report)
        (self.root/'reports/security.md').write_text('# Безопасность\n\nАудит выполнен. Находки зависимостей информационные для прототипа на фиксированном стеке.\n\n```json\n'+json.dumps(report,ensure_ascii=False,indent=2)+'\n```\n\nПолные результаты: npm-audit и dotnet-audit. Демо-вход позволяет выбрать admin; только доверенная локальная среда.',encoding='utf-8')

    def deploy(self):
        self.assert_checks()
        assert_mock_runtime(self.project)
        fingerprint=source_hash(self.project)
        if not self.frozen_checks or fingerprint!=self.built_hash or fingerprint!=self.tested_hash:
            raise ToolError('Выпуск запрещен: актуальные исходники не прошли сборку и приемку')
        self.require(self.command('cleanup-test-environment',self.test_compose+['down','-v','--remove-orphans']))
        configuration=json.loads((self.project/'compose.yaml').read_text())
        configuration['services']['backend']['environment']['TEST_CLOCK_ENABLED']='${TEST_CLOCK_ENABLED:-false}'
        (self.project/'compose.yaml').write_text(json.dumps(configuration,indent=2)+'\n')
        with (self.project/'README.md').open('a',encoding='utf-8') as readme:
            readme.write('\n\n## Final deployment\n\nAcceptance used a separate disposable database. This deployment starts fresh; test clock is disabled by default. CI explicitly enables TEST_CLOCK_ENABLED=true for acceptance only.\n')
        self.compose=['docker','compose','-p','rwb-app-'+self.job['runId'].replace('-','')[:16]]
        self.require(self.build_command('deployment-build',self.compose+['build']))
        deployment=self.command('deployment-up',self.compose+['up','-d','--wait','--wait-timeout','180'])
        if deployment['returnCode']!=0:
            self.stop_on_infrastructure(deployment['output'])
            self.require(self.runtime_diagnostic(deployment))
        result=self.command('deployment-port',self.compose+['port','frontend','80'])
        self.require(result)
        match=re.search(r':(\d+)\s*$',result['output'])
        if not match: raise ToolError('Не удалось определить порт приложения')
        port=match.group(1)
        with httpx.Client(timeout=15,trust_env=False) as client:
            response=client.get('http://127.0.0.1:'+port+'/health');response.raise_for_status()
            response=client.get('http://127.0.0.1:'+port+'/');response.raise_for_status()
        self.app_url=f'http://{self.settings.public_host}:{port}'
        if source_hash(self.project)!=fingerprint: raise ToolError('Исходники изменились во время развертывания')
        self.deployed_hash=fingerprint
        write_json(self.root/'reports/deployment.json',{'appUrl':self.app_url,'localHealthVerified':True,'composeProject':self.compose[-1],
            'sourceHash':fingerprint,'testedHash':self.tested_hash,'checksHash':self.frozen_checks})

    def release_evidence(self):
        self.assert_checks()
        if self.spec is not None: assert_mock_runtime(self.project)
        fingerprint=source_hash(self.project)
        if not self.frozen_checks or not self.app_url or not all(value==fingerprint for value in (self.built_hash,self.tested_hash,self.deployed_hash)):
            raise ToolError('Нет согласованных доказательств сборки, приемки и запуска текущих исходников')
        evidence={'sourceHash':fingerprint,'buildHash':self.built_hash,'acceptanceHash':self.tested_hash,
            'deploymentHash':self.deployed_hash,'frozenChecksHash':self.frozen_checks,
            'automaticRepairsByStage':self.repair_counts,'repairTransactions':'reports/repair-transactions/',
            'executionMode':'automatic_worker','appUrl':self.app_url}
        if self.product_plan is not None:
            browser=[]
            for width in (360,1280):
                candidates=[item for item in self.results if item['name']==f'browser-acceptance-{width}']
                if not candidates or candidates[-1]['returnCode']!=0: raise ToolError(f'Нет доказательства браузерной приёмки на ширине {width}px')
                browser.append(candidates[-1]['report'])
            evidence['generationMode']='contract-first-sequential'
            evidence['acceptanceFrozenBeforeImplementation']=True
            evidence['browserAcceptanceReports']=browser
            evidence['productPlan']='docs/product-plan.json'
            kafka=[]
            for name in ('kafka-business-delivery','kafka-restart-redelivery'):
                candidates=[item for item in self.results if item['name']==name]
                if not candidates or candidates[-1]['returnCode']!=0: raise ToolError('Нет доказательства Kafka: '+name)
                kafka.append(candidates[-1]['report'])
            evidence['messaging']={'broker':'Apache Kafka 4.1.2','topic':'app.business.v1',
                'contract':'docs/event-contract.json','consumer':'event-consumer','acceptanceReports':kafka}
        evidence['externalIntegrationMode']='mock'
        evidence['externalIntegrationIds']=[p.id for p in self.spec.externalIntegrations] if self.spec else []
        write_json(self.root/'reports/pipeline-evidence.json',evidence)

    def register_reports(self):
        paths=[p for p in (self.root/'reports').rglob('*') if p.is_file()]
        if (self.root/'project.zip').exists(): paths.append(self.root/'project.zip')
        if (self.root/'app-spec.json').exists(): paths.append(self.root/'app-spec.json')
        for index in range(0,len(paths),25):
            self.api.progress(self.job,'documentation',self.attempt,'running','Сохранение артефактов',artifacts=[
                {'name':p.name,'kind':'source' if p.suffix=='.zip' else 'report','path':str(p.relative_to(self.root))} for p in paths[index:index+25]])

    def execute(self):
        self.root.mkdir(parents=True,exist_ok=False)
        (self.root/'reports').mkdir()
        (self.root/'requirements.md').write_text(self.job['requirements'],encoding='utf-8')
        try:
            for stage in STAGES:
                self.current=stage;self.attempt=1
                self.event(stage,'running','Начало стадии')
                if stage=='analysis':
                    analysis_feedback=''
                    for attempt in range(1,4):
                        self.attempt=attempt
                        try:
                            raw=self.ask(prompts.analysis(self.job['requirements'])+analysis_feedback)
                            write_json(self.root/f'reports/analysis-attempt-{attempt}.json',raw)
                            self.spec=AppSpec.model_validate(raw)
                            if self.spec.uiMode=='focused' and (not self.spec.businessGoal or not self.spec.primaryAction or not self.spec.screens):
                                raise ValueError('Предметное приложение требует businessGoal, primaryAction и screens; опишите фактическую задачу пользователя')
                            quote_audit=restore_source_quotes(self.spec,self.job['requirements'])
                            write_json(self.root/'reports/source-quote-audit.json',quote_audit)
                            if quote_audit['unverifiedCount']:
                                self.api.progress(self.job,stage,attempt,'running',
                                    'Анализ продолжен; неподтвержденных цитат: '+str(quote_audit['unverifiedCount']),
                                    logs=['Некоторые sourceQuote не найдены в оригинале и не считаются точными цитатами. Подробнее: reports/source-quote-audit.json'])
                            break
                        except (ValueError,ModelError) as error:
                            self.event(stage,'failed',str(error)[:18000])
                            if isinstance(error,ModelError) and ('недоступен' in str(error) or 'HTTP' in str(error) or 'не настроен' in str(error)):
                                raise Blocked(str(error))
                            if attempt==3: raise
                            analysis_feedback='\nPREVIOUS ANALYSIS VALIDATION ERROR: '+str(error)[:4000]+'\nReturn corrected AppSpec without inventing additional business scope.'
                            self.api.progress(self.job,stage,attempt+1,'running','Повтор разбора требований',metrics={'retries':1})
                    write_json(self.root/'app-spec.json',self.spec.model_dump())
                    brief=['# Бизнес-задача','',self.spec.businessGoal or self.spec.summary,'',
                        '## Главное действие','',self.spec.primaryAction or 'См. сценарии ниже','',
                        '## Экраны','']+[f'- {screen.name}: {screen.purpose}' for screen in self.spec.screens]+[
                        '', '## Не входит в задачу','']+['- '+item for item in self.spec.outOfScope]+[
                        '', '## Допущения','']+['- '+item for item in self.spec.assumptions]+[
                        '', '## Исходный запрос (без изменений)','',self.job['requirements']]
                    (self.root/'reports/business-brief.md').write_text('\n'.join(brief),encoding='utf-8')
                    if self.spec.critical_questions: raise Blocked('\n'.join(self.spec.critical_questions))
                elif stage=='design':
                    render_project(self.spec.model_dump(),self.project,self.job['runId'])
                    (self.project/'.env.example').write_text('DB_PASSWORD=replace-with-unique-password\n')
                    design_product(self)
                    prepare_acceptance(self)
                    self.frozen_checks=acceptance_hash(self.project)
                    write_json(self.root/'reports/frozen-acceptance.json',{'hash':self.frozen_checks,'immutable':True,'frozenBeforeImplementation':True})
                elif stage=='generation':
                    generate_components(self)
                elif stage=='build': self.build()
                elif stage=='test': self.test()
                elif stage=='security': self.security()
                elif stage=='deploy': self.deploy()
                elif stage=='documentation':
                    self.release_evidence()
                    documents(self.root,self.spec.model_dump(),self.results,'Все обязательные локальные стадии выполнены.',self.app_url)
                    source_archive(self.project,self.root/'project.zip')
                    write_json(self.root/'reports/run-manifest.json',{'runId':self.job['runId'],'stages':{**self.states,'documentation':'passed'},'appUrl':self.app_url,'results':self.results})
                    self.register_reports()
                self.event(stage,'passed','Стадия выполнена'+(' · находки смотрите в security.md' if stage=='security' else ''))
            self.release_evidence()
            self.api.finish(self.job,'succeeded','Приложение автоматически собрано, проверено и запущено. Перед использованием прочитайте ограничения и отчет безопасности.',self.app_url)
            self.completed=True
        except Exception as error:
            status='blocked' if isinstance(error,(Blocked,ModelError)) else 'failed'
            message=redact(str(error),self.settings.secrets)[:18000] or type(error).__name__
            try:
                self.event(self.current,status,message)
                for stage in STAGES:
                    if stage not in self.states: self.event(stage,'not_run','Не выполнена после остановки предыдущей стадии')
            except Exception:
                pass # Local diagnostics and cleanup must work even when API/lease is unavailable.
            documents(self.root,self.spec.model_dump() if self.spec else None,self.results,message,self.app_url)
            if self.project.exists(): source_archive(self.project,self.root/'project.zip')
            self.current='documentation'
            try:
                self.register_reports()
                self.event('documentation','passed','Сохранены диагностические отчеты остановленного запуска')
                self.api.finish(self.job,status,message)
            except Exception:
                pass
            return status
        finally:
            # No API dependency here: failed/interrupted runs cannot leave app containers alive.
            if not self.completed:
                if self.project.exists():
                    for index,command in enumerate({tuple(self.compose),tuple(self.test_compose)}):
                        try:
                            result=self.runner(list(command)+['down','--remove-orphans'],self.project,60)
                            result['output']=redact(result['output'],self.settings.secrets)
                            write_json(self.root/f'reports/cleanup-{index}.json',result)
                        except Exception: pass
        return 'succeeded'
