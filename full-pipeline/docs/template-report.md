# Task 3: generated target templates

Scope: `templates/**`, `tests/test_templates.py`. Renderer interface: `render_project(spec: dict, destination: Path, run_id: str) -> dict` returns root, file list, stack metadata, parking flag and fixed acceptance command. Uses the shared AppSpec validator and refuses nonempty/symlink destinations.

## Implemented

- Angular 20.1.6, compatible Material 20.1.6, exact npm lockfile, actual Angular service worker, manifest and PNG192/512 icons. Generic schema-derived CRUD forms/list/edit/delete; role selector; responsive layout.
- .NET10/C#14 API with Npgsql10.0.0, JSONB persisted records for independently named entities, required/type/unknown-field checks. Random 12-hour opaque demo role tokens stored SHA256-hashed. Admin writes; other roles read. This is intentionally local demo identity, not a production authentication service. All logins for one role share its demo actor.
- PostgreSQL17.9 plus actual PostGIS extension and migration marker. Compose-project-specific persistent named volume. Only frontend publishes `127.0.0.1::80`; nginx proxies `/api` to internal backend8080. No host Docker socket inside target services.
- Optional `parking` capability: PostGIS polygon coverage; foreground GPS/manual explicitly labelled demo route; explicit session confirmation and duration; price fixed at confirmation; active session; warning once at <=10 remaining minutes; movement/zone-change/exit events preserve paid session; explicit stop/expiry and history. Admin can save validated zone polygons/rates and advance controlled demo clock. Seed areas are schematic SPb rectangles, not asserted official paid-parking boundaries. Shared boundary selects lexical zone ID.
- Map projection bounds and zone labels derive from all stored polygons, without remote map tiles.
- Trusted stdlib HTTP checks build into an immutable checks image, independent of model patches and compatible with Docker-in-Docker. OpenAPI3.1, generated README and GitLab CI with CI-specific DB_PASSWORD export. External GitLab execution remains unverified.
- Model extensions: global `GeneratedExtensions.Map(WebApplication app)` in backend/Generated/Extensions.cs; exported standalone Angular `GeneratedPanel` in frontend/src/app/generated/generated-panel.ts. Trusted infrastructure invokes both. These are arbitrary application code, so the local generator requires trusted operators.

## Verification record

1. Initial test-first run: `python -m pytest -q tests/test_templates.py` -> 3 failed (renderer absent), 2 skipped.
2. Implemented renderer: same command -> 3 passed, 2 skipped.
3. Added dangling-workflow guard: test failed because renderer accepted it; switched to shared AppSpec; -> 4 passed, 2 skipped.
4. Added PNG installability contract: failed with SVG-only icon; after adding PNG192/512 -> 4 passed, 2 skipped.
5. Project-wide snapshot `python -m pytest -q` -> 19 passed, 10 skipped, 1 unrelated Starlette/httpx deprecation warning (before additional test and concurrent components completed).
6. `npm install --package-lock-only --ignore-scripts --no-audit --no-fund --fetch-timeout=20000 --fetch-retries=0 --prefix templates/assets/frontend` -> exit0; lockfile created. Sandbox network stalled; retried elevated successfully. No system installation.
7. Real Docker integration first run: unrelated CRUD case passed including backend restart/persistence; parking reached warning threshold but event-list assertion failed. Diagnostic rerun reproduced HTTP200 with empty bytes from `/api/parking/events`. Root cause: expression-bodied `async (HttpContext c) => Results.Json(...)` selected ASP.NET RequestDelegate overload and discarded IResult. Fixed with explicit `async Task<IResult>`; the same trusted failing runtime test verified the repair. Final full integration rerun: **6 passed in 70.09s**, exit0. Both generated apps built Angular/.NET/PostGIS, became healthy, passed real HTTP acceptance, restarted backend, retained updated records, and cleaned their isolated containers/volumes. Command `RUN_TEMPLATE_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_templates.py`, log `/tmp/rwb-template-integration.log`. Two real AppSpecs: unrelated Ticket CRUD and Ticket plus parking. Includes build, Compose health, trusted HTTP suite, backend restart, persisted-record recheck, cleanup.

## Deliberate limits

The reusable baseline implements validated CRUD from AppSpec; arbitrary natural-language workflow descriptions do not automatically become working business processes. Model-owned extensions and requirements-specific tests must establish those separately. Parking is a bounded real capability with controlled time for acceptance; no real payment, financial settlement/refund, mobile background GPS, push delivery, official city-boundary dataset or native iOS application is claimed. Warning is delivered through polling. PWA shell supports offline loading; authenticated API data requires network. Existing JSONB records are not silently migrated to changed entity definitions; each generated run starts its own project/volume. Docker base images have pinned major/required PG patch tags but are not digest-locked; npm transitive versions are locked and Npgsql direct version is pinned.

Ruling: no Git operations because the isolated working directory is not a Git repository, per parent instruction. No original educational project files were modified.


## Final verification

- `RUN_TEMPLATE_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_templates.py > /tmp/rwb-template-integration.log 2>&1` -> **6 passed in 70.09s**, exit0. This is real Docker/runtime execution with deterministic fixture AppSpecs, not a live-model end-to-end claim.
- `.venv/bin/python -m pytest -q > /tmp/rwb-full-suite-template-check.log 2>&1` -> **30 passed, 10 skipped, 1 warning**, exit0. Skips are integration opt-ins without environment configuration; template Docker cases were separately enabled and passed above.
- First actual Angular build -> initial total526.21KB, bundle generation6.538s, Docker exit0. Final suite rebuilt current assets including SPb geometry, dynamic map projection and PNG icons.
- Source self-review verified generated extension hooks, compose isolation, fixed commands, schema validation, explicit demo labels, and the ASP.NET response overload repair. A browser install prompt and foreground device GPS were not manually exercised; manifest/service-worker delivery was tested through HTTP. Independent whole-project review belongs to the parent integration task.

Task3 complete. No unowned files or original project files changed. Temporary generated test projects remain under `/tmp`; their integration containers and volumes were removed by test cleanup. Built image layers remain as cache for the real pipeline.
