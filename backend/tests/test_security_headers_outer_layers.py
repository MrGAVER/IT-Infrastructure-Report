"""
A-04 (код-ревью main @ b375f58): заголовки безопасности на ответах, которые формируют внешние слои — 400 по Host, 403 по origin и клиенту, 413 по размеру тела.

Раньше заголовки (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Content-Security-Policy) ставил только шлюз доступа
(auth_gate_middleware), добавленный в приложение первым, то есть самый внутренний: ответы, которые TrustedHost, SameOriginGuard,
ClientAccess и BodySizeLimit отдают сами, до него не доходили. Теперь
SecurityHeadersMiddleware — самый внешний слой (main.py, после install_http_security) и единственный, кто их ставит: шлюз доступа
(AuthGateMiddleware) заголовки не трогает (код-ревью С-5, Н-8).

Запуск: pytest backend/tests/test_security_headers_outer_layers.py -v
"""

from __future__ import annotations

import asyncio
import ipaddress

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import MutableHeaders

from app.config import CSP_POLICY, MAX_REQUEST_BODY_BYTES
from app.main import install_http_security
from app.services.auth import security_headers
from app.services.auth.security_headers import SecurityHeadersMiddleware, apply_security_headers

API = "/api/v1"
BASIC = {"x-content-type-options": "nosniff", "x-frame-options": "DENY", "referrer-policy": "same-origin"}


def _assert_secured(response, *, csp: bool = True) -> None:
    for name, value in BASIC.items():
        assert response.headers.get(name) == value, f"{name}: {response.headers.get(name)!r} в ответе {response.status_code}"
    if csp:
        assert CSP_POLICY, "тест рассчитан на политику CSP по умолчанию (INFRA_REGISTRY_CSP не должен её отключать)"
        assert response.headers.get("content-security-policy") == CSP_POLICY


def _assert_no_duplicates(response) -> None:
    names = [name.lower() for name, _ in response.headers.multi_items()]
    for name in (*BASIC, "content-security-policy"):
        assert names.count(name) <= 1, f"заголовок {name} продублирован: {response.headers.multi_items()}"


# ---------------------------------------------------------------------------------------------------------------------
# Настоящее приложение: проверяется и сама проводка в main.py
# ---------------------------------------------------------------------------------------------------------------------


class TestRealApplication:
    def test_wrong_host_gets_400_with_security_headers(self, client):
        response = client.get(f"{API}/health", headers={"Host": "evil.example"})

        assert response.status_code == 400
        _assert_secured(response)

    def test_cross_origin_write_gets_403_with_security_headers(self, client):
        response = client.post(f"{API}/seed", headers={"Origin": "http://evil.example"})

        assert response.status_code == 403
        _assert_secured(response)

    def test_oversized_body_gets_413_with_security_headers(self, client):
        response = client.post(f"{API}/seed", content=b"x" * (MAX_REQUEST_BODY_BYTES + 1), headers={"Content-Type": "application/json"})

        assert response.status_code == 413
        _assert_secured(response)

    def test_regular_response_has_each_header_exactly_once(self, client):
        response = client.get(f"{API}/health")

        assert response.status_code == 200
        _assert_secured(response)
        _assert_no_duplicates(response)

    def test_error_from_the_gate_itself_has_each_header_exactly_once(self, client):
        response = client.get(f"{API}/this-route-does-not-exist")

        assert response.status_code == 404
        _assert_secured(response)
        _assert_no_duplicates(response)


class TestDocumentationPages:
    """Swagger UI и ReDoc грузят скрипты с CDN, поэтому CSP на них не ставится; базовые заголовки — как у всех (в настоящем приложении
    документация по умолчанию выключена)."""

    def test_openapi_json_gets_the_basic_headers_but_no_csp(self):
        app = FastAPI()
        app.add_middleware(SecurityHeadersMiddleware)

        response = TestClient(app).get("/openapi.json")

        assert response.status_code == 200
        _assert_secured(response, csp=False)
        assert "content-security-policy" not in response.headers


class TestRefusedByTheClientFilter:
    """403 от ClientAccessMiddleware — самый внешний из слоёв install_http_security, но всё равно внутри слоя заголовков."""

    def test_foreign_client_address_gets_403_with_security_headers(self):
        app = FastAPI()

        @app.get("/api/v1/ping")
        def ping() -> dict:
            return {"ok": True}

        install_http_security(app, allowed_hosts=["localhost"], cors_origins=[], allowed_clients=[ipaddress.ip_network("10.0.0.0/8")])
        app.add_middleware(SecurityHeadersMiddleware)

        response = TestClient(app, base_url="http://localhost:8000", client=("203.0.113.5", 50000)).get("/api/v1/ping")

        assert response.status_code == 403
        _assert_secured(response)


# ---------------------------------------------------------------------------------------------------------------------
# apply_security_headers / with_security_headers / SecurityHeadersMiddleware по отдельности
# ---------------------------------------------------------------------------------------------------------------------


class TestApplySecurityHeaders:
    def test_adds_the_basic_set_and_csp(self):
        headers = MutableHeaders(raw=[])

        apply_security_headers(headers, "/api/v1/health")

        assert {name: headers[name] for name in BASIC} == BASIC
        assert headers["content-security-policy"] == CSP_POLICY

    def test_does_not_overwrite_a_header_that_is_already_there_whatever_its_case(self):
        headers = MutableHeaders(raw=[])
        headers["X-Frame-Options"] = "SAMEORIGIN"  # MutableHeaders хранит имена в нижнем регистре, как требует ASGI
        headers["Content-Security-Policy"] = "default-src 'none'"

        apply_security_headers(headers, "/api/v1/health")

        assert headers["X-Frame-Options"] == "SAMEORIGIN"
        assert headers["Content-Security-Policy"] == "default-src 'none'"
        assert [name for name, _ in headers.items() if name.lower() == "x-frame-options"] == ["x-frame-options"]

    @pytest.mark.parametrize("path", sorted(security_headers._CSP_EXEMPT_PATHS))
    def test_documentation_paths_get_no_csp(self, path):
        headers = MutableHeaders(raw=[])

        apply_security_headers(headers, path)

        assert "content-security-policy" not in headers and headers["x-content-type-options"] == "nosniff"

    def test_empty_csp_setting_disables_only_that_header(self, monkeypatch):
        monkeypatch.setattr(security_headers, "CSP_POLICY", "")
        headers = MutableHeaders(raw=[])

        apply_security_headers(headers, "/")

        assert "content-security-policy" not in headers and headers["referrer-policy"] == "same-origin"


class TestSecurityHeadersMiddleware:
    @staticmethod
    def _run(app, scope) -> list[dict]:
        sent: list[dict] = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        asyncio.run(SecurityHeadersMiddleware(app)(scope, receive, send))
        return sent

    def test_response_start_without_headers_gets_them(self):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204})  # по ASGI заголовки необязательны
            await send({"type": "http.response.body", "body": b""})

        sent = self._run(app, {"type": "http", "path": "/api/v1/x"})

        start = MutableHeaders(raw=sent[0]["headers"])
        assert start["x-frame-options"] == "DENY" and start["content-security-policy"] == CSP_POLICY
        assert sent[1]["type"] == "http.response.body", "тело ответа проходит без изменений"

    def test_non_http_scopes_pass_through_untouched(self):
        seen: list[str] = []

        async def app(scope, receive, send):
            seen.append(scope["type"])
            await send({"type": "lifespan.startup.complete"})

        sent = self._run(app, {"type": "lifespan"})

        assert seen == ["lifespan"] and sent == [{"type": "lifespan.startup.complete"}]
