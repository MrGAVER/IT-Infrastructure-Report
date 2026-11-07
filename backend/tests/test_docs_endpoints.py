"""A-18: интерактивная документация API (/docs, /redoc, /openapi.json) выключена по умолчанию.

Раньше три адреса отдавались всем без входа (проверка доступа касается только /api/*) и раскрывали карту API и модели данных,
а Swagger UI грузит скрипты с внешнего CDN. Теперь они включаются переменной INFRA_REGISTRY_ENABLE_DOCS=1.

Приложение создаётся при импорте app.main, адреса документации задаются в `FastAPI(...)` один раз, поэтому состояние
«включено» проверяем в отдельном процессе с нужной переменной окружения, а не перезагрузкой модуля в процессе тестов.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
DOC_PATHS = ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect")

_PROBE = textwrap.dedent(
    """
    import json, sys
    from fastapi.testclient import TestClient
    from app import main
    client = TestClient(main.app, base_url="http://localhost")
    out = {}
    for path in %r:
        response = client.get(path)
        out[path] = [response.status_code, response.headers.get("content-type", ""), "content-security-policy" in response.headers]
    print("PROBE" + json.dumps(out))
    """
) % (DOC_PATHS,)


def _probe(tmp_path: Path, enable_docs: str | None) -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith("INFRA_REGISTRY_") and key != "DATABASE_URL"}
    env["INFRA_REGISTRY_DATA_DIR"] = str(tmp_path)
    if enable_docs is not None:
        env["INFRA_REGISTRY_ENABLE_DOCS"] = enable_docs
    result = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); exec(sys.stdin.read())" % str(BACKEND_DIR)],
                            input=_PROBE, capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    line = next(line for line in result.stdout.splitlines() if line.startswith("PROBE"))
    return json.loads(line[len("PROBE"):])


@pytest.mark.parametrize("value", [None, "", "0", "false", "no"])
def test_documentation_is_off_by_default_and_answers_404_not_the_spa_fallback(tmp_path, value):
    for path, (status, content_type, _csp) in _probe(tmp_path, value).items():
        assert status == 404, path
        assert "text/html" not in content_type, f"{path}: оболочка интерфейса вместо 404"


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_documentation_can_be_enabled_by_the_environment_variable(tmp_path, value):
    result = _probe(tmp_path, value)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert result[path][0] == 200, path
    assert "application/json" in result["/openapi.json"][1]
    # Swagger UI и ReDoc грузят скрипты с CDN — строгая политика им снята намеренно (services/auth/security_headers._CSP_EXEMPT_PATHS).
    assert result["/docs"][2] is False and result["/redoc"][2] is False


def test_the_spa_fallback_still_serves_client_side_routes(client):
    # Исключение для путей документации не должно задеть обычные маршруты интерфейса (в тестовой среде dist может
    # отсутствовать — тогда 500 с понятным текстом, но не 404).
    assert client.get("/devices").status_code in (200, 500)


def test_the_openapi_schema_is_still_available_to_the_application_itself():
    from app.main import app

    assert "/api/v1/health" in app.openapi()["paths"]


def test_resource_schema_does_not_leak_function_reprs(client):
    from app.registry import MODEL_MAP

    assert MODEL_MAP
    for resource in MODEL_MAP:
        response = client.get(f"/api/v1/resources/{resource}/schema")
        assert response.status_code == 200, resource
        assert "<function" not in response.text and " at 0x" not in response.text, resource
        for column in response.json()["columns"]:
            assert "default" in column, (resource, column)  # контракт: ключ присутствует всегда


def test_callable_defaults_are_null_and_scalar_defaults_stay_strings():
    from app.models import DeviceCategory
    from app.services.crud.columns import columns_for

    columns = {column["name"]: column for column in columns_for(DeviceCategory)}
    assert columns["id"]["default"] is None  # default=lambda: str(uuid4())
    assert columns["created_at"]["default"] is None  # default=utcnow_naive
    from app.models import DiagramLayout

    layout = {column["name"]: column for column in columns_for(DiagramLayout)}
    assert layout["auto_layout_algorithm"]["default"] == "hierarchical"
