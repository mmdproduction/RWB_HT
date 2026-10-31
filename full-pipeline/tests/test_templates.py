"""Renderer contract tests. Set RUN_TEMPLATE_INTEGRATION=1 for Docker acceptance."""
import importlib
import json
import os
from pathlib import Path
import subprocess

import pytest


def spec(parking=False):
    return {
        "schemaVersion": 1, "title": "Заявки сервиса", "slug": "service-desk",
        "summary": "Track requests", "roles": ["admin", "operator"],
        "requirements": [{"id": "R1", "description": "Manage tickets", "acceptance": ["Persist ticket"]}],
        "entities": [{"name": "Ticket", "fields": [
            {"name": "title", "type": "string", "required": True},
            {"name": "priority", "type": "integer", "required": True},
            {"name": "resolved", "type": "boolean", "required": False}]}],
        "workflows": [{"name": "Resolve", "description": "Close requests", "requirementIds": ["R1"]}],
        "capabilities": ["parking"] if parking else [], "assumptions": [], "questions": [],
    }


def renderer():
    try:
        module = importlib.import_module("templates.project")
    except ModuleNotFoundError:
        pytest.fail("The reusable project renderer is not implemented")
    return module.render_project


def test_renderer_emits_domain_schema_and_real_openapi(tmp_path):
    result = renderer()(spec(), tmp_path / "app", "test-run")
    root = tmp_path / "app"
    assert json.loads((root / "backend/app-spec.json").read_text())["entities"][0]["name"] == "Ticket"
    api = json.loads((root / "docs/openapi.json").read_text())
    assert "/api/entities/Ticket" in api["paths"]
    assert "/api/parking/position" not in api["paths"]
    assert api["components"]["schemas"]["Ticket"]["required"] == ["title", "priority"]
    assert api["components"]["schemas"]["Ticket"]["properties"]["priority"]["type"] == "integer"
    assert all((root / name).is_file() for name in result["files"])
    assert (root / "frontend/src/app/generated/generated-panel.ts").is_file()
    assert (root / "backend/Generated/Extensions.cs").is_file()
    compile((root / "scripts/tests.py").read_text(), "tests.py", "exec")


def test_generated_network_is_isolated_and_checks_are_trusted(tmp_path):
    renderer()(spec(True), tmp_path / "app", "geo")
    root = tmp_path / "app"
    compose = json.loads((root / "compose.yaml").read_text())
    assert set(compose["services"]) == {"db", "backend", "frontend", "checks"}
    assert compose["services"]["frontend"]["ports"] == ["127.0.0.1::80"]
    assert all("ports" not in compose["services"][s] for s in ["db", "backend", "checks"])
    assert compose["services"]["checks"]["command"] == ["python", "/checks/tests.py"]
    assert compose["services"]["backend"]["environment"]["TEST_CLOCK_ENABLED"] == "true"
    assert "/api/parking/position" in json.loads((root / "docs/openapi.json").read_text())["paths"]
    package = json.loads((root / "frontend/package.json").read_text())
    assert package["dependencies"]["@angular/core"] == "20.1.6"
    assert package["dependencies"]["@angular/material"].startswith("20.")
    assert package["dependencies"]["@angular/service-worker"] == "20.1.6"
    assert (root / "frontend/public/manifest.webmanifest").is_file()
    manifest = json.loads((root / 'frontend/public/manifest.webmanifest').read_text())
    icons = {icon['sizes']: icon['src'] for icon in manifest['icons']}
    assert set(icons) >= {'192x192', '512x512'}
    for size in ['192x192', '512x512']:
        assert (root / 'frontend/public' / icons[size]).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_renderer_refuses_overwrites_and_unsafe_spec(tmp_path):
    run = tmp_path / "app"
    run.mkdir()
    (run / "keep.txt").write_text("owned")
    with pytest.raises(ValueError):
        renderer()(spec(), run, "x")
    assert (run / "keep.txt").read_text() == "owned"
    bad = spec()
    bad["entities"][0]["name"] = "../../outside"
    with pytest.raises(ValueError):
        renderer()(bad, tmp_path / "bad", "x")
    assert not (tmp_path / "bad").exists()


@pytest.mark.skipif(os.environ.get("RUN_TEMPLATE_INTEGRATION") != "1", reason="requires Docker build and runtime")
@pytest.mark.parametrize("parking", [False, True])
def test_generated_project_build_and_http_acceptance(tmp_path, parking):
    root = tmp_path / "app"
    renderer()(spec(parking), root, "acceptance")
    project = f"rwb_template_{os.getpid()}_{int(parking)}"
    base = ["docker", "compose", "-p", project, "-f", str(root / "compose.yaml")]
    def run(*args, timeout=900):
        subprocess.run(base + list(args), cwd=root, check=True, timeout=timeout)
    try:
        run("build")
        run("up", "-d", "--wait", "db", "backend", "frontend")
        run("run", "--rm", "checks")
        run("restart", "backend")
        run("up", "-d", "--wait", "backend")
        run("run", "--rm", "-e", "PERSISTENCE_ONLY=1", "checks")
    finally:
        run("down", "-v", "--remove-orphans")


def test_renderer_rejects_incoherent_workflow_before_writing(tmp_path):
    invalid = spec()
    invalid['workflows'][0]['requirementIds'] = ['missing-requirement']
    with pytest.raises(ValueError):
        renderer()(invalid, tmp_path / 'invalid', 'invalid')
    assert not (tmp_path / 'invalid').exists()
