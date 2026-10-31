# Full RUSSTECH Pipeline Implementation Plan

> **For agentic workers:** use executing-plans for dependent integration and dispatching-parallel-agents only for isolated component ownership. Steps use checkbox syntax.

**Goal:** реализовать весь локальный цикл от требований до проверенного и развернутого приложения.

**Architecture:** Angular UI, FastAPI API, PostgreSQL, Python worker, Qwen, generated Angular/.NET/PostGIS project. Shared schema and fixed execution tools connect components.

**Tech Stack:** Python>=3.12, FastAPI/Pydantic2/Psycopg3/HTTPX, Angular20.1.6, .NET10/C#14, PostgreSQL17.9/PostGIS, Docker Compose, GitLab CI.

**Spec:** docs/design.md; existing user-approved master RUSSTECH_ТЗ_и_план_16_часов.md.

## Global Constraints

- Variant A fixed; generated stack fixed; mobile=PWA.
- Original user files preserved; new implementation in isolated writable directory.
- No secret logging, no mock production model, no invented passing checks.
- Primary job states and public create/get/claim/finish behavior preserved.
- Bounded attempts, path checks, fresh run directories, immutable completed run.

## Review Focus

- Concurrent claims and stale lease writes cannot corrupt another worker's result.
- Model output cannot overwrite tool commands, tests, credentials or files outside run root.
- Missing model/tool/network produces explicit blocked/failed checks.
- Browser refresh, empty list, errors and terminal polling work.
- Generated app API/data/contracts and geospatial boundary behavior agree.

### Task 1: Contracts and validation

Files shared/models.py, shared/settings.py, tests/test_models.py, examples/*.md.
Produces AppSpec.model_validate, safe_relative_path and fixed stack metadata. Tests invalid names, duplicate IDs, dangling references, critical questions and traversal.
- [ ] Write failing tests and run them.
- [ ] Implement contracts and validation; run tests to green.

### Task 2: Persistent platform API

Files platform_api/{main,store,schema}.py/sql, tests/test_api.py.
Consumes shared settings; produces create_app(settings), PostgreSQL store and public/internal endpoints in design.
- [ ] Add failing tests for atomic claim/lease, progress idempotence, finishing, cursor and file boundaries.
- [ ] Implement additive schema and API; real PostgreSQL integration tests.

### Task 3: Generated target templates

Files templates/project.py and templates/assets/**, tests/test_templates.py.
Interface render_project(spec:dict,destination:Path,run_id:str)->dict. Produces Angular20.1.6/Material/PWA, .NET10 API, PG17.9/PostGIS, SQL, checks and docs. No work in API or worker files.
- [ ] Test generated files/stack and alternate domains before implementation.
- [ ] Implement compatible routes, migrations, actual CRUD and optional geo/parking capability.
- [ ] Build and execute generated project tests; report actual limitations.

### Task 4: Worker, model and tools

Files worker/{main,llm,engine,tools,documents}.py, tests/test_worker.py.
Consumes AppSpec, render_project, internal API. Produces claim/heartbeat/progress/finish, real Qwen HTTP adapter, bounded code patches and Docker execution.
- [ ] Failing tests for invalid model, transport failure, retry limit, timeout, stage order and honest statuses.
- [ ] Implement engine and fixed commands; validate paths and redact secrets.

### Task 5: Angular platform interface

Files frontend/**. Consumes public API card schema from design. Three screens: create/list, progress/logs and results/download. No model keys or internal worker key in browser.
- [ ] Validate loading/error/terminal states with browser test when available.
- [ ] Build Angular20.1.6 with UI Kit and proxy/API integration.

### Task 6: Packaging and documentation

Files compose.yaml, Dockerfile*, scripts/setup_env.py, scripts/model_probe.py, .gitlab-ci.yml, README.md, .env.example, requirements*.txt.
- [ ] Compose isolated API/db/ui/worker with correct host artifact path and secrets via environment.
- [ ] Provide SSH tunnel, model probe, one-command start and clean-start instructions.
- [ ] Add actual CI tests/artifact upload, document external GitLab limitations.

### Task 7: Integration and review

- [ ] Run unit and PostgreSQL tests, platform UI build and browser exercise.
- [ ] Run full model-to-app flow when reachable; otherwise explicit blocker plus tested fixture-only integration.
- [ ] Review whole implementation independently, repair material findings and rerun relevant suite.
- [ ] Record completed stages, evidence, limitations and startup command in final report.
