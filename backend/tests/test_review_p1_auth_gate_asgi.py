"""Код-ревью С-5 и Н-8: шлюз доступа — чистый ASGI-middleware, заголовки безопасности ставит один слой.

Шлюз был функцией под BaseHTTPMiddleware: тот читает receive внутри группы задач anyio, и исключение предела тела запроса
приходило в FastAPI обёрнутым в ExceptionGroup и превращалось в 400. От этого в body_limit.py жил обход, подменявший любой
ответ приложения на 413. Теперь все слои над обработчиком — чистый ASGI, обход убран, а эти тесты на настоящем приложении
с включённой аутентификацией не дают вернуть BaseHTTPMiddleware и ловят то, что раньше закрывал обход.

Запуск: pytest backend/tests/test_review_p1_auth_gate_asgi.py -v
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.middleware.base import BaseHTTPMiddleware

from app import main as app_main
from app.constants import ErrorCode
from app.services.actor_context import NO_ACTOR, Actor, current_actor
from app.services.auth import AuthGateMiddleware

MANUFACTURERS = "/api/v1/resources/manufacturers"
MIB = 1024 * 1024


@pytest.fixture()
def admin_token(client) -> str:
    """Администратор создан, аутентификация включена; возвращает токен его сессии."""
    created = client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"})
    assert created.status_code == 201, created.text
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    login = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
    assert login.status_code == 200, login.text
    return login.json()["token"]


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _chunks(total_bytes: int):
    """JSON-тело `{"name": "xxx…"}` заданного размера кусками по 256 КиБ — без Content-Length (Transfer-Encoding: chunked)."""
    yield b'{"name": "'
    remaining = total_bytes
    while remaining > 0:
        size = min(256 * 1024, remaining)
        yield b"x" * size
        remaining -= size
    yield b'"}'


# --- устройство стека -------------------------------------------------------------------------------------------------------------


def test_no_layer_of_the_app_is_a_base_http_middleware():
    """Единственный слой на BaseHTTPMiddleware был шлюзом. Вернув такой слой, вернёшь и 400 вместо 413 на chunked-теле."""
    layers = [layer.cls for layer in app_main.app.user_middleware]
    assert AuthGateMiddleware in layers
    offenders = [layer for layer in layers if isinstance(layer, type) and issubclass(layer, BaseHTTPMiddleware)]
    assert offenders == []


# --- предел тела при включённой аутентификации ---------------------------------------------------------------------------------


def test_chunked_body_over_the_limit_is_413_not_400_with_auth_enabled(client, admin_token):
    """Именно то, что раньше закрывал обход в body_limit.py: тело читает обработчик под включённым шлюзом."""
    response = client.post(MANUFACTURERS, content=_chunks(3 * MIB), headers={**_bearer(admin_token), "Content-Type": "application/json"})

    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert detail["code"] == ErrorCode.REQUEST_BODY_TOO_LARGE
    assert response.headers["connection"] == "close"
    listing = client.get(MANUFACTURERS, headers=_bearer(admin_token), params={"q": "xxxxxxxx"})
    assert listing.json()["total"] == 0, "запись из отклонённого запроса не создана"


def test_chunked_body_within_the_limit_still_works_with_auth_enabled(client, admin_token):
    response = client.post(MANUFACTURERS, content=_chunks(200), headers={**_bearer(admin_token), "Content-Type": "application/json"})
    assert response.status_code == 201, response.text
    assert response.json()["name"] == "x" * 200


def test_the_gate_answers_before_an_oversized_body_is_read(client, admin_token):
    """Без токена шлюз отвечает 401, не читая тело: огромное chunked-тело анонима не доходит до обработчика."""
    response = client.post(MANUFACTURERS, content=_chunks(3 * MIB), headers={"Content-Type": "application/json"})
    assert response.status_code == 401


# --- ответы шлюза и заголовки безопасности (Н-8) ------------------------------------------------------------------------------------


@pytest.mark.parametrize("header", ["x-content-type-options", "x-frame-options", "referrer-policy", "content-security-policy", "cache-control"])
def test_gate_denials_carry_each_security_header_exactly_once(client, admin_token, header):
    """401 отдаёт сам шлюз. Раньше заголовки ему же приходилось ставить, теперь их ставит один внешний слой — без дублей."""
    response = client.get(MANUFACTURERS)
    assert response.status_code == 401
    assert len(response.headers.get_list(header)) == 1, response.headers.raw


def test_a_viewer_denial_is_403_with_security_headers(client, admin_token):
    created = client.post("/api/v1/auth/users", json={"username": "viewer", "password": "Viewer1234", "role": "viewer"}, headers=_bearer(admin_token))
    assert created.status_code == 201, created.text
    viewer = client.post("/api/v1/auth/login", json={"username": "viewer", "password": "Viewer1234"}).json()["token"]

    response = client.post(MANUFACTURERS, json={"name": "Не пройдёт"}, headers=_bearer(viewer))

    assert response.status_code == 403
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_static_paths_are_not_gated_and_still_get_security_headers(client, admin_token):
    response = client.get("/")
    assert response.status_code != 401
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "no-store" not in response.headers.get("cache-control", ""), "кэш статики шлюзом и заголовками API не затронут"


# --- сам middleware ----------------------------------------------------------------------------------------------------------------


def _scope(path: str, *, method: str = "GET", client_ip: str = "203.0.113.9") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost")],
        "client": (client_ip, 50000),
        "server": ("localhost", 8000),
    }


def _call(middleware, scope):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent


class _Probe:
    """Внутреннее «приложение»: запоминает, что видит под шлюзом."""

    def __init__(self) -> None:
        self.calls = 0
        self.actor: Actor | None = None
        self.state: dict | None = None

    async def __call__(self, scope, receive, send):
        self.calls += 1
        self.actor = current_actor.get()
        self.state = dict(scope.get("state", {}))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})


def test_api_request_gets_actor_and_state_and_the_actor_is_reset_afterwards(client):
    probe = _Probe()
    sent = _call(AuthGateMiddleware(probe), _scope("/api/v1/health"))

    assert sent[0]["status"] == 204 and probe.calls == 1
    assert probe.actor == Actor(ip="203.0.113.9")
    assert probe.state == {"auth_enabled": False, "user": None}, "request.state.* читают это из scope['state']"
    assert current_actor.get() == NO_ACTOR, "актор не протекает в следующий запрос"


def test_the_actor_is_reset_even_when_the_app_below_fails(client):
    class Boom:
        async def __call__(self, scope, receive, send):
            raise RuntimeError("упало")

    with pytest.raises(RuntimeError):
        _call(AuthGateMiddleware(Boom()), _scope("/api/v1/health"))
    assert current_actor.get() == NO_ACTOR


def test_non_api_requests_pass_through_untouched(client):
    probe = _Probe()
    scope = _scope("/assets/app.js")
    _call(AuthGateMiddleware(probe), scope)

    assert probe.calls == 1
    assert probe.actor == NO_ACTOR
    assert "state" not in scope


def test_non_http_scopes_pass_through_untouched():
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    asyncio.run(AuthGateMiddleware(inner)({"type": "lifespan"}, None, None))
    assert seen == ["lifespan"]


def test_a_denied_request_never_reaches_the_app_below(client, admin_token):
    probe = _Probe()
    sent = _call(AuthGateMiddleware(probe), _scope(MANUFACTURERS))

    assert sent[0]["status"] == 401
    assert probe.calls == 0
    assert current_actor.get() == NO_ACTOR
