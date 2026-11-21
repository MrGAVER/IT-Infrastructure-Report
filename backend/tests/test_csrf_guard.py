"""A-07: защита от межсайтовых запросов (CSRF) — SameOriginGuardMiddleware.

Пока аутентификация выключена, чужая страница в браузере владельца могла вслепую отправить POST без тела
(`/api/v1/seed`, `/diagrams/{id}/duplicate`, `/reports/inventory` …): CORS защищает чтение ответа, но не сам запрос,
а проверка Host не спасает, потому что Host у такого запроса свой. Теперь POST/PUT/PATCH/DELETE на `/api/` с чужим
Origin либо с `Sec-Fetch-Site: cross-site` получают 403 `CROSS_ORIGIN_BLOCKED` до обработчика.

Запуск: pytest backend/tests/test_csrf_guard.py -v
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

import app.main as main_module
from app.constants import ErrorCode
from app.main import install_http_security
from app.services import csrf_guard
from app.services.csrf_guard import SameOriginGuardMiddleware, forwarded_host_trusted, is_cross_origin_request

from test_auth import _auth_headers, _bootstrap_admin, _login

EVIL = {"Origin": "http://evil.example"}
CROSS_SITE = {"Sec-Fetch-Site": "cross-site"}
UNSAFE = ["POST", "PUT", "PATCH", "DELETE"]
SAFE = ["GET", "HEAD"]


def _make_app(*, cors_origins=(), trust_forwarded_host=False) -> FastAPI:
    app = FastAPI()
    calls: list[str] = []
    app.state.calls = calls

    @app.api_route("/api/v1/thing", methods=UNSAFE + SAFE + ["OPTIONS"])
    def thing() -> dict:
        calls.append("api")
        return {"ok": True}

    @app.api_route("/other", methods=UNSAFE + SAFE)
    def other() -> dict:
        calls.append("other")
        return {"ok": True}

    install_http_security(
        app,
        allowed_hosts=["localhost", "127.0.0.1"],
        cors_origins=list(cors_origins),
        trust_forwarded_host=trust_forwarded_host,
    )
    return app


@pytest.fixture()
def guarded() -> TestClient:
    return TestClient(_make_app(), base_url="http://localhost:8000")


def _assert_blocked(response):
    assert response.status_code == 403, response.text
    detail = response.json()["detail"]
    assert detail["code"] == ErrorCode.CROSS_ORIGIN_BLOCKED == "CROSS_ORIGIN_BLOCKED"
    assert detail["message"]


# ---------------------------------------------------------------------------------------------------------------------
# (а) чужой origin и Sec-Fetch-Site: cross-site
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method", UNSAFE)
def test_foreign_origin_is_blocked_for_every_unsafe_method(guarded, method):
    _assert_blocked(guarded.request(method, "/api/v1/thing", headers=EVIL))
    assert guarded.app.state.calls == [], "обработчик не должен выполняться"


@pytest.mark.parametrize("method", UNSAFE)
def test_cross_site_fetch_metadata_is_blocked_even_without_origin(guarded, method):
    _assert_blocked(guarded.request(method, "/api/v1/thing", headers=CROSS_SITE))
    assert guarded.app.state.calls == []


def test_cross_site_is_blocked_even_if_origin_equals_host(guarded):
    _assert_blocked(guarded.post("/api/v1/thing", headers={"Origin": "http://localhost:8000", **CROSS_SITE}))


@pytest.mark.parametrize(
    "origin",
    [
        "null",  # изолированный iframe, file://
        "http://localhost:9999",  # другой порт того же хоста — другой origin
        "http://localhost.evil.example",
        "http://evil.example:8000",
        "http://[::1",  # мусор
        "",
        "   ",
    ],
)
def test_odd_and_mismatching_origins_are_blocked(guarded, origin):
    _assert_blocked(guarded.post("/api/v1/thing", headers={"Origin": origin}))


def test_same_site_other_port_without_listing_is_blocked(guarded):
    """Sec-Fetch-Site: same-site (скажем, localhost:5173 → localhost:8000) — не cross-site, но Origin не совпадает с Host."""
    _assert_blocked(guarded.post("/api/v1/thing", headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"}))


def test_response_is_json_with_structured_detail(guarded):
    response = guarded.post("/api/v1/thing", headers=EVIL)
    assert response.headers["content-type"].startswith("application/json")
    assert set(response.json()["detail"]) == {"code", "message"}


# ---------------------------------------------------------------------------------------------------------------------
# (б) тот же origin, (в) без Origin
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method", UNSAFE)
def test_origin_equal_to_host_passes(guarded, method):
    response = guarded.request(method, "/api/v1/thing", headers={"Origin": "http://localhost:8000", "Sec-Fetch-Site": "same-origin"})
    assert response.status_code == 200
    assert guarded.app.state.calls == ["api"]


def test_origin_comparison_ignores_case_and_scheme_behind_tls_proxy(guarded):
    assert guarded.post("/api/v1/thing", headers={"Origin": "HTTP://LOCALHOST:8000"}).status_code == 200
    assert guarded.post("/api/v1/thing", headers={"Origin": "https://localhost:8000"}).status_code == 200


def test_default_port_in_host_or_origin_does_not_cause_false_block():
    client = TestClient(_make_app(), base_url="http://localhost:80")  # Host: localhost:80
    assert client.post("/api/v1/thing", headers={"Origin": "http://localhost"}).status_code == 200
    client = TestClient(_make_app(), base_url="http://localhost")  # Host: localhost
    assert client.post("/api/v1/thing", headers={"Origin": "http://localhost:80"}).status_code == 200
    assert client.post("/api/v1/thing", headers={"Origin": "https://localhost:443"}).status_code == 200


def test_ipv6_host_matches_its_origin():
    # Host «[::1]:8000» не проходит TrustedHost в мини-приложении (разрешены localhost/127.0.0.1) — проверяем сравнитель.
    assert is_cross_origin_request(Headers({"host": "[::1]:8000", "origin": "http://[::1]:8000"})) is False
    assert is_cross_origin_request(Headers({"host": "[::1]:8000", "origin": "http://[::1]:9000"})) is True
    assert is_cross_origin_request(Headers({"host": "[::1]:443", "origin": "https://[::1]"})) is False


@pytest.mark.parametrize("method", UNSAFE)
def test_request_without_origin_passes_like_curl(guarded, method):
    assert guarded.request(method, "/api/v1/thing").status_code == 200


@pytest.mark.parametrize("fetch_site", ["same-origin", "same-site", "none"])
def test_other_fetch_site_values_without_origin_pass(guarded, fetch_site):
    assert guarded.post("/api/v1/thing", headers={"Sec-Fetch-Site": fetch_site}).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------
# (г) безопасные методы и пути вне /api/
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("headers", [EVIL, CROSS_SITE, {**EVIL, **CROSS_SITE}])
@pytest.mark.parametrize("method", SAFE)
def test_safe_methods_are_never_blocked(guarded, method, headers):
    assert guarded.request(method, "/api/v1/thing", headers=headers).status_code == 200


def test_options_with_foreign_origin_is_not_blocked_by_the_guard(guarded):
    response = guarded.options("/api/v1/thing", headers={**EVIL, "Access-Control-Request-Method": "POST"})
    assert response.status_code != 403 or response.json().get("detail", {}).get("code") != ErrorCode.CROSS_ORIGIN_BLOCKED


@pytest.mark.parametrize("path", ["/other", "/apix/v1/thing", "/static/app.js"])
def test_paths_outside_api_are_not_guarded(guarded, path):
    response = guarded.post(path, headers=EVIL)
    assert response.status_code != 403 or response.json().get("detail", {}).get("code") != ErrorCode.CROSS_ORIGIN_BLOCKED


def test_non_http_scopes_pass_through():
    import asyncio

    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    middleware = SameOriginGuardMiddleware(inner)
    asyncio.run(middleware({"type": "lifespan"}, None, None))
    asyncio.run(middleware({"type": "websocket", "method": "POST", "path": "/api/x", "headers": []}, None, None))
    assert seen == ["lifespan", "websocket"]


# ---------------------------------------------------------------------------------------------------------------------
# (д) origin из INFRA_REGISTRY_CORS_ORIGINS
# ---------------------------------------------------------------------------------------------------------------------
class TestConfiguredOrigins:
    def test_listed_origin_passes_and_unlisted_is_still_blocked(self):
        client = TestClient(_make_app(cors_origins=["http://localhost:5173"]), base_url="http://localhost:8000")
        assert client.post("/api/v1/thing", headers={"Origin": "http://localhost:5173"}).status_code == 200
        _assert_blocked(client.post("/api/v1/thing", headers=EVIL))
        _assert_blocked(client.post("/api/v1/thing", headers={"Origin": "http://localhost:5174"}))

    @pytest.mark.parametrize("configured", ["http://localhost:5173/", "HTTP://LocalHost:5173", " http://localhost:5173 "])
    def test_configured_value_is_normalized(self, configured):
        client = TestClient(_make_app(cors_origins=[configured]), base_url="http://localhost:8000")
        assert client.post("/api/v1/thing", headers={"Origin": "http://localhost:5173"}).status_code == 200

    def test_listed_origin_passes_even_when_browser_says_cross_site(self):
        """Отдельный фронтенд на другом домене администратор разрешил явно — Sec-Fetch-Site его не отменяет."""
        client = TestClient(_make_app(cors_origins=["https://reestr.example.com"]), base_url="http://localhost:8000")
        headers = {"Origin": "https://reestr.example.com", "Sec-Fetch-Site": "cross-site"}
        assert client.post("/api/v1/thing", headers=headers).status_code == 200

    def test_wildcard_means_any_origin_is_trusted(self):
        """При CORS «*» любая страница и так читает и меняет API через CORS — защищать от неё нечего."""
        client = TestClient(_make_app(cors_origins=["*"]), base_url="http://localhost:8000")
        assert client.post("/api/v1/thing", headers=EVIL).status_code == 200

    def test_wildcard_does_not_whitelist_the_literal_star_origin(self):
        guard = SameOriginGuardMiddleware(lambda *a: None, extra_origins=["*"])
        assert guard.allow_any_origin is True and "*" not in guard.trusted_origins

    def test_empty_entries_are_ignored(self):
        guard = SameOriginGuardMiddleware(lambda *a: None, extra_origins=["", "  ", "http://a.example"])
        assert guard.trusted_origins == frozenset({"http://a.example"})
        assert guard.allow_any_origin is False


# ---------------------------------------------------------------------------------------------------------------------
# X-Forwarded-Host: только за настоящим прокси
# ---------------------------------------------------------------------------------------------------------------------
class TestForwardedHost:
    PROXY_HEADERS = {"Origin": "https://reestr.corp", "X-Forwarded-Host": "reestr.corp"}

    def test_ignored_by_default(self):
        client = TestClient(_make_app(), base_url="http://localhost:8000")
        _assert_blocked(client.post("/api/v1/thing", headers=self.PROXY_HEADERS))

    def test_honoured_when_proxy_is_trusted(self):
        client = TestClient(_make_app(trust_forwarded_host=True), base_url="http://localhost:8000")
        assert client.post("/api/v1/thing", headers=self.PROXY_HEADERS).status_code == 200

    def test_first_value_of_the_list_is_used(self):
        client = TestClient(_make_app(trust_forwarded_host=True), base_url="http://localhost:8000")
        headers = {"Origin": "https://reestr.corp", "X-Forwarded-Host": "reestr.corp, proxy.internal"}
        assert client.post("/api/v1/thing", headers=headers).status_code == 200
        headers = {"Origin": "https://proxy.internal", "X-Forwarded-Host": "reestr.corp, proxy.internal"}
        _assert_blocked(client.post("/api/v1/thing", headers=headers))

    def test_trusted_proxy_does_not_make_a_foreign_origin_acceptable(self):
        client = TestClient(_make_app(trust_forwarded_host=True), base_url="http://localhost:8000")
        _assert_blocked(client.post("/api/v1/thing", headers={"Origin": "http://evil.example", "X-Forwarded-Host": "reestr.corp"}))

    def test_own_host_still_works_when_proxy_is_trusted(self):
        client = TestClient(_make_app(trust_forwarded_host=True), base_url="http://localhost:8000")
        assert client.post("/api/v1/thing", headers={"Origin": "http://localhost:8000", "X-Forwarded-Host": "reestr.corp"}).status_code == 200

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (None, False),
            ([], False),
            ([""], False),
            (["127.0.0.1"], False),  # значение uvicorn по умолчанию: прокси на этом же компьютере
            (["127.0.0.1", "::1"], False),
            (["127.0.0.0/8"], False),
            (["10.0.0.5"], True),
            (["10.0.0.0/24"], True),
            (["127.0.0.1", " 172.18.0.2 "], True),
            (["fd00::/8"], True),
            (["*"], True),
            (["proxy.local"], False),  # не адрес — игнорируется, как «литерал» в uvicorn
        ],
    )
    def test_forwarded_host_trusted(self, value, expected):
        assert forwarded_host_trusted(value) is expected

    def test_config_reads_forwarded_allow_ips(self, monkeypatch):
        from app.config import _csv_env

        monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1, 10.1.0.0/16")
        assert forwarded_host_trusted(_csv_env("FORWARDED_ALLOW_IPS")) is True
        monkeypatch.delenv("FORWARDED_ALLOW_IPS")
        assert forwarded_host_trusted(_csv_env("FORWARDED_ALLOW_IPS")) is False


# ---------------------------------------------------------------------------------------------------------------------
# Порядок слоёв и журнал
# ---------------------------------------------------------------------------------------------------------------------
def test_untrusted_host_is_rejected_before_the_guard():
    client = TestClient(_make_app(), base_url="http://evil.example")
    response = client.post("/api/v1/thing", headers=EVIL)
    assert response.status_code == 400, "TrustedHost снаружи: чужое имя Host отвергается раньше"


def test_blocked_origin_is_logged_once(guarded, caplog):
    csrf_guard._log_blocked_origin.cache_clear()
    with caplog.at_level(logging.WARNING, logger=csrf_guard.logger.name):
        for _ in range(3):
            guarded.post("/api/v1/thing", headers=EVIL)
        guarded.post("/api/v1/thing", headers={"Origin": "http://evil2.example"})
    messages = [r.getMessage() for r in caplog.records if "origin" in r.getMessage()]
    assert len(messages) == 2
    assert "http://evil.example" in messages[0] and "INFRA_REGISTRY_CORS_ORIGINS" in messages[0]


def test_log_line_cannot_be_inflated_by_a_huge_origin(guarded, caplog):
    csrf_guard._log_blocked_origin.cache_clear()
    with caplog.at_level(logging.WARNING, logger=csrf_guard.logger.name):
        guarded.post("/api/v1/thing", headers={"Origin": "http://" + "a" * 5000})
    assert all(len(r.getMessage()) < 600 for r in caplog.records)


def test_guard_is_installed_in_the_real_application():
    installed = [m.cls for m in main_module.app.user_middleware]
    assert SameOriginGuardMiddleware in installed
    # внутри TrustedHost/CORS (выше в списке — внешний слой) и снаружи auth_gate_middleware
    assert installed.index(SameOriginGuardMiddleware) < len(installed) - 1


# ---------------------------------------------------------------------------------------------------------------------
# Настоящее приложение: побочные эффекты и аутентификация
# ---------------------------------------------------------------------------------------------------------------------
def test_cross_site_duplicate_diagram_is_blocked_and_has_no_side_effect(client):
    created = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-07"})
    assert created.status_code == 201, created.text
    diagram_id = created.json()["id"]

    _assert_blocked(client.post(f"/api/v1/diagrams/{diagram_id}/duplicate", headers=EVIL))
    _assert_blocked(client.post(f"/api/v1/diagrams/{diagram_id}/duplicate", headers=CROSS_SITE))
    assert len(client.get("/api/v1/diagrams").json()) == 1, "копия не создана"

    assert client.post(f"/api/v1/diagrams/{diagram_id}/duplicate", headers={"Origin": "http://testserver"}).status_code == 201
    assert client.post(f"/api/v1/diagrams/{diagram_id}/duplicate").status_code == 201  # как curl
    assert len(client.get("/api/v1/diagrams").json()) == 3


def test_cross_site_seed_and_json_endpoints_are_blocked_in_the_real_app(client):
    _assert_blocked(client.post("/api/v1/seed", headers=EVIL))
    _assert_blocked(client.post("/api/v1/resources/manufacturers", json={"name": "Чужой"}, headers=EVIL))
    names = [m["name"] for m in client.get("/api/v1/resources/manufacturers", params={"limit": 500}).json()["items"]]
    assert "Чужой" not in names
    assert client.get("/api/v1/resources/manufacturers", headers=EVIL).status_code == 200


def test_guard_applies_when_authentication_is_enabled_and_does_not_break_login(client):
    _bootstrap_admin(client)
    # вход со своего origin работает (в том числе публичный путь /auth/login)
    own = {"Origin": "http://testserver"}
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"}, headers=own)
    assert response.status_code == 200, response.text
    token = response.json()["token"]
    # чужая страница не пройдёт даже с валидным токеном и даже на публичном пути
    _assert_blocked(client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"}, headers=EVIL))
    _assert_blocked(client.post("/api/v1/resources/manufacturers", json={"name": "Х"}, headers={**EVIL, **_auth_headers(token)}))
    assert client.post("/api/v1/resources/manufacturers", json={"name": "Свой"}, headers={**own, **_auth_headers(token)}).status_code == 201
    assert _login(client, "admin", "Admin1234")  # curl-подобный вход без Origin по-прежнему работает
