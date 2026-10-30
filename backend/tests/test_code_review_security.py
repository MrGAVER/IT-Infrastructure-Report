"""Тесты исправлений безопасности по код-ревью (пп. 1–5).

Аутентификация по умолчанию ВЫКЛЮЧЕНА (AuthSettings.enabled=False) — это сознательное решение
владельца проекта, и оно не меняется. Исправления закрывают то, что при выключенной аутентификации
позволяло постороннему не просто читать открытый реестр, а захватить приложение: создать
администратора, включить аутентификацию и заблокировать владельца (п. 1), использовать открытый
CORS и подмену Host (п. 2), действовать без следа в журнале (п. 3), протащить исполняемый SVG (п. 4)
и атаковать вход (п. 5).

Запуск: pytest backend/tests/test_code_review_security.py -v
"""
from __future__ import annotations

import base64
import hashlib
import io
import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select

from app import config as app_config
from app.main import install_http_security
from app.models import AuditLog, User
from app.services import auth as auth_module
from app.services.diagram_export import export_svg
from app.services.diagram_icons import validate_svg_markup
from app.services.login_throttle import LoginThrottle

ADMIN = {"username": "admin", "password": "Admin1234", "role": "admin"}


def _create_admin(client) -> None:
    r = client.post("/api/v1/auth/users", json=ADMIN)
    assert r.status_code == 201, r.text


def _enable_auth_and_login(client) -> str:
    _create_admin(client)
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# п. 1. Захват приложения при выключенной аутентификации
# ---------------------------------------------------------------------------
class TestSetupAccess:
    def test_authentication_is_still_disabled_by_default(self, client):
        assert client.get("/api/v1/auth/status").json()["enabled"] is False
        # Открытый реестр остаётся открытым для чтения и записи — меняется только управление доступом.
        assert client.post("/api/v1/resources/manufacturers", json={"name": "Открыто"}).status_code == 201

    def test_remote_anonymous_cannot_take_over_while_auth_is_disabled(self, client_factory):
        remote = client_factory("203.0.113.7")
        r = remote.post("/api/v1/auth/users", json=ADMIN)
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "SETUP_ACCESS_DENIED"
        assert remote.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 403
        assert remote.get("/api/v1/auth/users").status_code == 403

    def test_remote_client_still_works_with_the_open_registry(self, client_factory):
        remote = client_factory("203.0.113.7")
        assert remote.get("/api/v1/resources/manufacturers").status_code == 200
        assert remote.post("/api/v1/resources/manufacturers", json={"name": "Удалённый"}).status_code == 201

    def test_localhost_can_set_up_authentication(self, client):
        _create_admin(client)
        assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200

    def test_localhost_behind_a_proxy_is_not_trusted(self, client):
        # Обратный прокси на той же машине делает адрес любого клиента равным 127.0.0.1.
        r = client.post("/api/v1/auth/users", json=ADMIN, headers={"X-Forwarded-For": "198.51.100.9"})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "SETUP_ACCESS_DENIED"

    def test_setup_token_lets_a_remote_client_in(self, client_factory, monkeypatch):
        monkeypatch.setattr(auth_module, "SETUP_TOKEN", "s3cret-token")
        remote = client_factory("203.0.113.7")
        assert remote.post("/api/v1/auth/users", json=ADMIN).status_code == 403
        assert remote.post("/api/v1/auth/users", json=ADMIN, headers={"X-Setup-Token": "wrong"}).status_code == 403
        r = remote.post("/api/v1/auth/users", json=ADMIN, headers={"X-Setup-Token": "s3cret-token"})
        assert r.status_code == 201, r.text

    def test_with_a_configured_token_localhost_needs_it_too(self, client, monkeypatch):
        monkeypatch.setattr(auth_module, "SETUP_TOKEN", "s3cret-token")
        assert client.post("/api/v1/auth/users", json=ADMIN).status_code == 403
        assert client.post("/api/v1/auth/users", json=ADMIN, headers={"X-Setup-Token": "s3cret-token"}).status_code == 201

    def test_enabled_auth_still_requires_an_admin_token_not_the_setup_token(self, client, monkeypatch):
        token = _enable_auth_and_login(client)
        monkeypatch.setattr(auth_module, "SETUP_TOKEN", "s3cret-token")
        assert client.get("/api/v1/auth/users", headers={"X-Setup-Token": "s3cret-token"}).status_code == 401
        assert client.get("/api/v1/auth/users", headers=_bearer(token)).status_code == 200


# ---------------------------------------------------------------------------
# п. 2. CORS по умолчанию закрыт, проверка Host
# ---------------------------------------------------------------------------
def _security_app(*, allowed_hosts, cors_origins) -> TestClient:
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    install_http_security(app, allowed_hosts=allowed_hosts, cors_origins=cors_origins)
    return TestClient(app, base_url="http://localhost")


class TestCorsAndHost:
    def test_defaults_are_same_origin_only(self):
        assert "*" not in app_config.CORS_ALLOWED_ORIGINS
        assert "*" not in app_config.ALLOWED_HOSTS

    def test_csv_env_parsing(self, monkeypatch):
        monkeypatch.setenv("X_TEST_LIST", " a , b,,c ")
        assert app_config._csv_env("X_TEST_LIST") == ["a", "b", "c"]
        monkeypatch.delenv("X_TEST_LIST")
        assert app_config._csv_env("X_TEST_LIST") == []
        assert app_config._csv_env("X_TEST_LIST", "h1,h2") == ["h1", "h2"]

    def test_foreign_origin_preflight_gets_no_cors_headers_by_default(self):
        client = _security_app(allowed_hosts=["localhost"], cors_origins=[])
        r = client.options("/ping", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "DELETE"})
        assert "access-control-allow-origin" not in r.headers
        r = client.get("/ping", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in r.headers

    def test_explicitly_listed_origin_is_allowed_and_others_are_not(self):
        client = _security_app(allowed_hosts=["localhost"], cors_origins=["http://localhost:5173"])
        ok = client.options("/ping", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "PUT"})
        assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
        bad = client.options("/ping", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "PUT"})
        assert bad.headers.get("access-control-allow-origin") is None

    def test_unknown_host_header_is_rejected(self):
        client = _security_app(allowed_hosts=["localhost", "127.0.0.1"], cors_origins=[])
        assert client.get("/ping").status_code == 200
        assert client.get("/ping", headers={"Host": "127.0.0.1:8000"}).status_code == 200
        assert client.get("/ping", headers={"Host": "rebind.evil.example"}).status_code == 400

    def test_wildcard_host_list_allows_any_host(self):
        client = _security_app(allowed_hosts=["*"], cors_origins=[])
        assert client.get("/ping", headers={"Host": "reestr.corp.local"}).status_code == 200

    def test_real_app_rejects_a_foreign_host(self, client):
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health", headers={"Host": "rebind.evil.example"}).status_code == 400


# ---------------------------------------------------------------------------
# п. 3. Автор действия в журнале аудита
# ---------------------------------------------------------------------------
def _audit_rows(db_session, entity_type: str) -> list[AuditLog]:
    db_session.expire_all()
    return list(db_session.scalars(select(AuditLog).where(AuditLog.entity_type == entity_type).order_by(AuditLog.created_at, AuditLog.id)).all())


class TestAuditActor:
    def test_action_of_a_logged_in_user_records_who_did_it(self, client, db_session):
        token = _enable_auth_and_login(client)
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Acme"}, headers=_bearer(token))
        assert r.status_code == 201, r.text
        row = _audit_rows(db_session, "manufacturers")[-1]
        admin = db_session.scalar(select(User).where(User.username == "admin"))
        assert row.actor_id == admin.id
        assert row.actor_username == "admin"
        assert row.actor_ip == "127.0.0.1"

    def test_with_auth_disabled_only_the_address_is_recorded(self, client_factory, db_session):
        remote = client_factory("203.0.113.7")
        assert remote.post("/api/v1/resources/manufacturers", json={"name": "Anon"}).status_code == 201
        row = _audit_rows(db_session, "manufacturers")[-1]
        assert row.actor_id is None and row.actor_username is None
        assert row.actor_ip == "203.0.113.7"

    def test_login_events_name_the_user(self, client, db_session):
        _enable_auth_and_login(client)
        login = _audit_rows(db_session, "auth")
        logins = [r for r in login if r.action == "LOGIN"]
        assert logins and logins[-1].actor_username == "admin" and logins[-1].actor_ip == "127.0.0.1"

    def test_failed_login_records_the_address(self, client, db_session):
        _create_admin(client)
        client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"})
        failed = [r for r in _audit_rows(db_session, "auth") if r.action == "LOGIN_FAILED"]
        assert failed and failed[-1].actor_ip == "127.0.0.1"

    def test_actor_does_not_leak_between_requests(self, client, db_session):
        token = _enable_auth_and_login(client)
        client.post("/api/v1/resources/manufacturers", json={"name": "First"}, headers=_bearer(token))
        client.post("/api/v1/auth/logout", headers=_bearer(token))
        assert auth_module.current_actor.get() == auth_module.Actor(None, None, None)

    def test_audit_page_and_export_show_the_actor(self, client):
        token = _enable_auth_and_login(client)
        headers = _bearer(token)
        client.post("/api/v1/resources/manufacturers", json={"name": "Acme"}, headers=headers)
        page = client.get("/api/v1/audit-log?q=Создание", headers=headers).json()
        assert any(item.get("actor_username") == "admin" for item in page["items"])

        report = client.post("/api/v1/reports/audit-log", headers=headers).json()
        content = client.get(report["download_url"], headers=headers).content
        sheet = load_workbook(io.BytesIO(content)).active
        header = [c.value for c in sheet[1]]
        assert "Пользователь" in header and "IP-адрес" in header
        user_column = header.index("Пользователь")
        assert "admin" in {row[user_column].value for row in sheet.iter_rows(min_row=2)}


# ---------------------------------------------------------------------------
# п. 4. SVG: белый список тегов и атрибутов
# ---------------------------------------------------------------------------
BYPASS_PAYLOADS = [
    '<s:script xmlns:s="http://www.w3.org/2000/svg">alert(1)</s:script>',  # префикс пространства имён
    '<use xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="&#106;avascript:alert(1)"/>',  # HTML-сущность в разрешённом теге
    '<a><set attributeName="href" to="data:text/html,x"/></a>',  # SMIL
    '<svg onload="alert(1)"></svg>',
    "<svg><script>alert(1)</script></svg>",
    '<svg ONLOAD="alert(1)"></svg>',
    '<svg><foreignObject><body onload="alert(1)"/></foreignObject></svg>',
    '<svg><a href="javascript:alert(1)">кликни</a></svg>',
    '<svg><image href="javascript:alert(1)"/></svg>',
    '<svg><use href="https://evil.example/x.svg#a"/></svg>',  # внешняя ссылка
    '<svg><rect style="fill:url(javascript:alert(1))"/></svg>',
    "<svg><style>@import url(https://evil.example/x.css)</style></svg>",
    '<!DOCTYPE svg [<!ENTITY x "boom">]><svg><text>&x;</text></svg>',  # сущности запрещены
    "<svg><rect></svg>",  # не XML
]

SAFE_ICONS = [
    None,
    "",
    '<svg viewBox="0 0 24 24"><rect width="24" height="24" fill="#4f7cff"/></svg>',
    '<svg><circle cx="5" cy="5" r="5" class="on-hover"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><defs><linearGradient id="g"><stop offset="0" stop-color="#000"/></linearGradient></defs><use xlink:href="#g"/><path d="M0 0L5 5" fill="url(#g)"/><text>on = off</text></svg>',
    '<?xml version="1.0" encoding="UTF-8"?><svg><g><title>Коммутатор</title><polygon points="0,0 5,5 0,5"/></g></svg>',
    '<rect width="10" height="10"/><circle r="3"/>',  # голый фрагмент из нескольких элементов
]


@pytest.mark.parametrize("markup", BYPASS_PAYLOADS)
def test_svg_validator_rejects_payloads(markup):
    with pytest.raises(HTTPException) as exc_info:
        validate_svg_markup(markup)
    assert exc_info.value.status_code == 422


@pytest.mark.parametrize("markup", SAFE_ICONS)
def test_svg_validator_accepts_plain_icons(markup):
    validate_svg_markup(markup)


def test_svg_validator_is_reached_through_the_catalog_api(client):
    r = client.post("/api/v1/resources/diagram-icons", json={"name": "SMIL", "svg_markup": BYPASS_PAYLOADS[2]})
    assert r.status_code == 422


def test_svg_export_embeds_a_custom_icon_as_an_image_not_as_raw_markup():
    marker = 'class="custom-mark"'
    graph = {
        "nodes": [{"id": "n1", "type": "device", "label": "sw", "x": 0, "y": 0,
                   "icon": {"mode": "custom", "svg_markup": f'<circle r="5" {marker}/>'}}],
        "edges": [],
    }
    svg = export_svg(graph)
    assert marker not in svg, "пользовательская разметка не должна попадать в документ как есть"
    match = re.search(r'href="data:image/svg\+xml;base64,([A-Za-z0-9+/=]+)"', svg)
    assert match, "иконка должна быть вложена как data-URI изображение"
    assert marker in base64.b64decode(match.group(1)).decode("utf-8")


# ---------------------------------------------------------------------------
# п. 5. Усиление аутентификации
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class TestLoginThrottle:
    def make(self, **kwargs) -> tuple[LoginThrottle, FakeClock]:
        clock = FakeClock()
        return LoginThrottle(clock=clock, **kwargs), clock

    def test_first_attempts_are_free(self):
        throttle, _ = self.make(free_attempts=3)
        for _ in range(3):
            assert throttle.retry_after(("1.1.1.1", "admin")) == 0
            throttle.record_failure(("1.1.1.1", "admin"))
        assert throttle.retry_after(("1.1.1.1", "admin")) == 0

    def test_delay_doubles_after_the_free_attempts_and_is_capped(self):
        throttle, clock = self.make(free_attempts=1, base_delay=1.0, max_delay=8.0)
        key = ("1.1.1.1", "admin")
        delays = []
        for _ in range(6):
            throttle.record_failure(key)
            delays.append(throttle.retry_after(key))
            clock.now += delays[-1]  # дождались конца задержки
        assert delays == [0, 1.0, 2.0, 4.0, 8.0, 8.0]

    def test_waiting_out_the_delay_allows_the_next_attempt(self):
        throttle, clock = self.make(free_attempts=1, base_delay=5.0)
        key = ("1.1.1.1", "admin")
        throttle.record_failure(key)
        throttle.record_failure(key)
        assert throttle.retry_after(key) == 5.0
        clock.now += 5.0
        assert throttle.retry_after(key) == 0

    def test_keys_are_independent(self):
        throttle, _ = self.make(free_attempts=1)
        for _ in range(3):
            throttle.record_failure(("1.1.1.1", "admin"))
        assert throttle.retry_after(("1.1.1.1", "admin")) > 0
        assert throttle.retry_after(("2.2.2.2", "admin")) == 0  # другой адрес
        assert throttle.retry_after(("1.1.1.1", "other")) == 0  # другой логин

    def test_success_resets_the_counter(self):
        throttle, _ = self.make(free_attempts=1)
        key = ("1.1.1.1", "admin")
        throttle.record_failure(key)
        throttle.record_failure(key)
        throttle.reset(key)
        assert throttle.retry_after(key) == 0

    def test_old_failures_are_forgotten_after_the_window(self):
        throttle, clock = self.make(free_attempts=1, base_delay=1.0, window=60.0)
        key = ("1.1.1.1", "admin")
        throttle.record_failure(key)
        throttle.record_failure(key)
        clock.now += 61.0
        throttle.record_failure(key)
        assert throttle.retry_after(key) == 0

    def test_memory_is_bounded(self):
        throttle, clock = self.make(free_attempts=1, window=10.0, max_keys=50)
        for i in range(500):
            throttle.record_failure((f"10.0.{i // 250}.{i % 250}", "admin"))
            clock.now += 1.0
        assert len(throttle) <= 50


class TestLoginHardening:
    def test_repeated_wrong_passwords_from_one_address_are_throttled(self, client):
        _create_admin(client)
        statuses = [client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"}).status_code for _ in range(5)]
        assert statuses[:3] == [401, 401, 401]
        assert 429 in statuses
        r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
        assert r.status_code == 429
        assert int(r.headers["retry-after"]) >= 1
        assert r.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"

    def test_unknown_logins_are_throttled_too(self, client):
        statuses = [client.post("/api/v1/auth/login", json={"username": "ghost", "password": "wrong-pass1"}).status_code for _ in range(6)]
        assert 429 in statuses

    def test_one_throttled_address_does_not_lock_the_real_admin_out(self, client_factory):
        local = client_factory("127.0.0.1")
        _create_admin(local)
        attacker = client_factory("203.0.113.7")
        for _ in range(8):
            attacker.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"})
        r = local.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
        assert r.status_code == 200, r.text  # учётная запись не заблокирована: атакующий упёрся в свой троттлинг

    def test_successful_login_resets_the_throttle(self, client):
        _create_admin(client)
        for _ in range(2):
            client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"})
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"}).status_code == 200
        for _ in range(3):
            assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"}).status_code == 401

    @pytest.mark.real_password_hashing
    def test_pbkdf2_uses_at_least_the_current_owasp_iteration_count(self):
        assert int(auth_module.hash_password("Passw0rd!").split("$")[1]) >= 600_000

    @pytest.mark.real_password_hashing
    def test_legacy_hashes_are_rehashed_on_login(self, client, db_session):
        _create_admin(client)
        user = db_session.scalar(select(User).where(User.username == "admin"))
        salt = b"0123456789abcdef"
        digest = hashlib.pbkdf2_hmac("sha256", b"Admin1234", salt, 260_000)
        user.password_hash = f"pbkdf2_sha256$260000${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
        db_session.commit()
        assert auth_module._needs_rehash(user.password_hash)
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"}).status_code == 200
        db_session.expire_all()
        assert int(db_session.scalar(select(User).where(User.username == "admin")).password_hash.split("$")[1]) >= 600_000

    def test_invalid_credentials_error_is_created_per_failure(self, db_session):
        errors = []
        for _ in range(2):
            with pytest.raises(HTTPException) as exc_info:
                auth_module.authenticate(db_session, "nobody", "Passw0rd!")
            errors.append(exc_info.value)
        assert errors[0] is not errors[1]
        assert errors[0].status_code == errors[1].status_code == 401

    def test_content_security_policy_on_app_and_api_responses(self, client):
        for path in ("/api/v1/health", "/"):
            policy = client.get(path).headers.get("content-security-policy", "")
            assert "default-src 'self'" in policy, path
            assert "frame-ancestors 'none'" in policy, path
            assert "script-src" not in policy or "'unsafe-inline'" not in policy.split("script-src")[1].split(";")[0], path

    def test_swagger_ui_is_exempt_from_the_policy(self, client):
        # /docs грузит скрипты со стороннего CDN — строгая политика сломала бы страницу документации.
        assert "content-security-policy" not in client.get("/docs").headers
