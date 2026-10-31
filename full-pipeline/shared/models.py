from pathlib import Path, PurePosixPath
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
import json
import math
from datetime import datetime

RUN_STATES = ('queued', 'running', 'succeeded', 'failed', 'blocked', 'interrupted')
TERMINAL_STATES = frozenset(RUN_STATES[2:])
STAGES = ('analysis', 'design', 'generation', 'build', 'test', 'security', 'deploy', 'documentation')
STACK = {'frontend': 'Angular 20.1.6 + Angular Material / PWA', 'backend': 'C# 14 / ASP.NET Core .NET 10', 'database': 'PostgreSQL 17.9 / PostGIS', 'messaging': 'Apache Kafka 4.1.2 + REST', 'deployment': 'Docker Compose', 'model': 'qwen3.8-27b'}


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Requirement(Contract):
    id: str = Field(min_length=1, max_length=60, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')
    description: str = Field(min_length=1, max_length=4000)
    acceptance: list[str] = Field(min_length=1, max_length=20)
    sourceQuote: str = Field(default='',max_length=4000)


class EntityField(Contract):
    name: str = Field(pattern=r'^[a-z][A-Za-z0-9]{0,47}$')
    type: Literal['string', 'integer', 'number', 'boolean', 'datetime']
    required: bool = False


class Entity(Contract):
    name: str = Field(pattern=r'^[A-Z][A-Za-z0-9]{0,47}$')
    fields: list[EntityField] = Field(min_length=1, max_length=25)

    @model_validator(mode='after')
    def unique_fields(self):
        names = [f.name.lower() for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError('Duplicate entity field')
        return self


class Workflow(Contract):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4000)
    requirementIds: list[str] = Field(default_factory=list, max_length=100)


class Question(Contract):
    question: str = Field(min_length=1, max_length=2000)
    critical: bool = False


class Screen(Contract):
    name: str = Field(min_length=1,max_length=100)
    purpose: str = Field(min_length=1,max_length=2000)
    requirementIds: list[str] = Field(default_factory=list,max_length=100)


class MockOperation(Contract):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,47}$')
    description: str = Field(min_length=1,max_length=1000)
    inputFields: list[EntityField] = Field(default_factory=list,max_length=20)
    inputExample: dict[str,JsonValue] = Field(default_factory=dict)
    response: dict[str,JsonValue] = Field(min_length=1)

    @model_validator(mode='after')
    def valid_fixture(self):
        fields={f.name:f for f in self.inputFields}
        if len(fields)!=len(self.inputFields): raise ValueError('Duplicate integration input field')
        if set(self.inputExample)-set(fields): raise ValueError('Unknown integration example input')
        for name,field in fields.items():
            value=self.inputExample.get(name)
            if value is None:
                if field.required: raise ValueError('Missing required integration example input: '+name)
                continue
            valid={'string':isinstance(value,str) and len(value)<=4000 and (not field.required or bool(value.strip())),
                'integer':type(value) is int and -(2**63)<=value<2**63,
                'number':type(value) in (int,float) and abs(value)<=79228162514264337593543950335 and math.isfinite(value),
                'boolean':type(value) is bool,'datetime':False}.get(field.type,False)
            if field.type=='datetime' and isinstance(value,str):
                try: datetime.fromisoformat(value.replace('Z','+00:00'));valid=True
                except ValueError: pass
            if not valid: raise ValueError('Invalid integration example input: '+name)
        if len(json.dumps(self.response,allow_nan=False))>30000: raise ValueError('Integration fixture too large')
        return self


class ExternalIntegration(Contract):
    id: str = Field(pattern=r'^[a-z][a-z0-9-]{0,47}$')
    name: str = Field(min_length=1,max_length=150)
    kind: Literal['payment','maps','data','notifications','custom']
    mode: Literal['mock'] = 'mock'
    purpose: str = Field(min_length=1,max_length=2000)
    requirementIds: list[str] = Field(min_length=1,max_length=100)
    operations: list[MockOperation] = Field(min_length=1,max_length=8)

    @model_validator(mode='after')
    def valid_operations(self):
        if len({op.id for op in self.operations})!=len(self.operations): raise ValueError('Duplicate integration operation')
        if self.kind=='payment':
            for operation in self.operations:
                fields={f.name:f for f in operation.inputFields}
                if any(name not in fields or not fields[name].required or fields[name].type!=kind
                    for name,kind in [('amount','number'),('currency','string')]):
                    raise ValueError('Mock payment operations require amount:number and currency:string')
                if operation.inputExample['amount']<=0 or not re.fullmatch(r'[A-Z]{3}',operation.inputExample['currency']):
                    raise ValueError('Mock payment example requires positive amount and three-letter currency')
        return self


class AppSpec(Contract):
    schemaVersion: Literal[1]
    title: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=60, pattern=r'^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$')
    summary: str = Field(min_length=1, max_length=8000)
    businessGoal: str = Field(default='',max_length=3000)
    primaryAction: str = Field(default='',max_length=500)
    uiMode: Literal['focused','workspace'] = 'workspace'
    requiresLogin: bool = True
    screens: list[Screen] = Field(default_factory=list,max_length=20)
    outOfScope: list[str] = Field(default_factory=list,max_length=50)
    roles: list[str] = Field(default_factory=lambda: ['admin', 'user'], min_length=1, max_length=12)
    requirements: list[Requirement] = Field(min_length=1, max_length=100)
    entities: list[Entity] = Field(default_factory=list, max_length=12)
    workflows: list[Workflow] = Field(default_factory=list, max_length=100)
    capabilities: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=100)
    questions: list[Question] = Field(default_factory=list, max_length=20)
    externalIntegrations: list[ExternalIntegration] = Field(default_factory=list,max_length=12)

    @model_validator(mode='after')
    def coherent(self):
        ids = [r.id for r in self.requirements]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate requirement ID')
        names = [e.name.lower() for e in self.entities]
        if len(set(names)) != len(names):
            raise ValueError('Duplicate entity name')
        for workflow in self.workflows:
            if set(workflow.requirementIds) - set(ids):
                raise ValueError('Workflow refers to an unknown requirement')
        for screen in self.screens:
            if set(screen.requirementIds)-set(ids):
                raise ValueError('Screen refers to an unknown requirement')
        for requirement in self.requirements:
            if any(not a.strip() for a in requirement.acceptance):
                raise ValueError('Acceptance criteria cannot be blank')
        if len({p.id for p in self.externalIntegrations})!=len(self.externalIntegrations):
            raise ValueError('Duplicate external integration ID')
        for provider in self.externalIntegrations:
            if set(provider.requirementIds)-set(ids): raise ValueError('Integration refers to an unknown requirement')
        return self

    @property
    def interface_role(self):
        if any('parking' in c.lower() for c in self.capabilities): return 'driver'
        return 'user' if 'user' in self.roles else next((r for r in self.roles if r!='admin'),'user')

    @property
    def critical_questions(self):
        return [q.question for q in self.questions if q.critical]


def safe_path(root: Path, relative: str) -> Path:
    if not relative or '\\' in relative or re.match(r'^[A-Za-z]:', relative):
        raise ValueError('Expected a relative POSIX file path')
    item = PurePosixPath(relative)
    if item.is_absolute() or '..' in item.parts or str(item) == '.':
        raise ValueError('File must be inside the run directory')
    root = Path(root).resolve()
    path = root.joinpath(*item.parts)
    if not path.resolve().is_relative_to(root):
        raise ValueError('File path escapes the run directory')
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError('Symbolic links are not permitted')
        current = current.parent
    return path


def redact(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text
