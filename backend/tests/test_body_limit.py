"""F-06 (этап 1): предел размера тела запроса — BodySizeLimitMiddleware.

Раньше предела не было: обработчики с ``payload: dict`` и pydantic-модели читают тело целиком, и запрос в сотни мегабайт
FastAPI разбирал бы в память. Теперь тело больше INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES получает 413 ``REQUEST_BODY_TOO_LARGE``:

* по заголовку Content-Length — до обработчика, тело не читается вовсе;
* без заголовка (chunked) либо с заниженным — по счёту байт в потоке; ответ именно 413, а не 400 «error parsing the body», в
  который FastAPI превращает любое обычное исключение из чтения тела.

Запуск: pytest backend/tests/test_body_limit.py -v
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import MAX_REQUEST_BODY_BYTES
from app.constants import ErrorCode
from app.main import install_http_security
from app.services.body_limit import BodySizeLimitMiddleware, describe_limit, too_large_detail

API = "/api/v1"
LIMIT = 1000
ORIGIN = "http://localhost:5173"


def _make_app(*, max_bytes: int = LIMIT, cors_origins=()) -> FastAPI:
    app = FastAPI()
    calls: list[int] = []
    app.state.calls = calls

    @app.api_route("/api/v1/echo", methods=["POST", "PUT", "PATCH", "DELETE", "GET"])
    async def echo(request: Request) -> dict:
        body = await request.body()
        calls.append(len(body))
        return {"size": len(body)}

    @app.post("/api/v1/json")
    def json_endpoint(payload: dict) -> dict:
        calls.append(len(json.dumps(payload)))
        return {"keys": len(payload)}

    install_http_security(
        app,
        allowed_hosts=["localhost", "127.0.0.1"],
        cors_origins=list(cors_origins),
        max_body_bytes=max_bytes,
    )
    return app


@pytest.fixture()
def limited() -> TestClient:
    return TestClient(_make_app(), base_url="http://localhost:8000")


def _assert_too_large(response, max_bytes: int = LIMIT):
    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert detail["code"] == ErrorCode.REQUEST_BODY_TOO_LARGE == "REQUEST_BODY_TOO_LARGE"
    assert describe_limit(max_bytes) in detail["message"]
    assert "INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES" in detail["message"]


# ---------------------------------------------------------------------------------------------------------------------
# (а) граница предела
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("size", [0, 1, LIMIT - 1, LIMIT])
def test_body_up_to_the_limit_passes(limited, size):
    response = limited.post("/api/v1/echo", content=b"x" * size)
    assert response.status_code == 200, response.text
    assert response.json() == {"size": size}


def test_body_one_byte_over_the_limit_is_rejected(limited):
    _assert_too_large(limited.post("/api/v1/echo", content=b"x" * (LIMIT + 1)))
    assert limited.app.state.calls == [], "обработчик не должен выполняться: тело не читается"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "GET"])
def test_limit_applies_to_every_method(limited, method):
    """Тело есть не только у POST/PUT/PATCH; список методов, который можно обойти, ничего не стоит."""
    _assert_too_large(limited.request(method, "/api/v1/echo", content=b"x" * (LIMIT + 1)))
    assert limited.app.state.calls == []


def test_request_without_body_is_not_affected(limited):
    response = limited.get("/api/v1/echo")
    assert response.status_code == 200
    assert response.json() == {"size": 0}


def test_huge_json_body_is_rejected_before_parsing(limited):
    body = json.dumps({"k": "v" * 50_000})
    response = limited.post("/api/v1/json", content=body, headers={"Content-Type": "application/json"})
    _assert_too_large(response)
    assert limited.app.state.calls == []


# ---------------------------------------------------------------------------------------------------------------------
# (б) объявленный Content-Length и поток без него
# ---------------------------------------------------------------------------------------------------------------------
def test_declared_content_length_over_limit_is_rejected_without_reading_body(limited):
    """Заголовок говорит о большом теле — отказ сразу, ответ закрывает соединение (оставшиеся байты не станут «следующим запросом»)."""
    response = limited.post("/api/v1/echo", content=b"x", headers={"Content-Length": str(LIMIT * 100)})
    _assert_too_large(response)
    assert response.headers["connection"] == "close"
    assert limited.app.state.calls == []


def test_chunked_body_over_limit_is_rejected_with_413_not_400(limited):
    """Без Content-Length (Transfer-Encoding: chunked) считаются байты потока. Именно 413: исключение из receive, не
    унаследованное от fastapi.HTTPException, FastAPI подменил бы на 400 «error parsing the body»."""
    chunks = [b"x" * 400] * 4  # 1600 > LIMIT
    response = limited.post("/api/v1/echo", content=iter(chunks))
    _assert_too_large(response)
    assert limited.app.state.calls == []


def test_chunked_json_body_over_limit_is_rejected_with_413(limited):
    """То же для обработчика с ``payload: dict``: тело читает сам FastAPI."""
    chunks = [b'{"a": "', b"x" * 600, b"x" * 600, b'"}']
    response = limited.post("/api/v1/json", content=iter(chunks), headers={"Content-Type": "application/json"})
    _assert_too_large(response)
    assert limited.app.state.calls == []


@pytest.mark.parametrize("path", ["/api/v1/echo", "/api/v1/json"])
def test_chunked_body_over_limit_closes_the_connection(limited, path):
    """413 по потоку несёт Connection: close — клиент уже слал тело, и остаток не должен разобраться как следующий запрос.
    (Те же проверки на настоящем приложении с включённой аутентификацией — test_review_p1_auth_gate_asgi.py.)"""
    chunks = [b'{"a": "', b"x" * 600, b"x" * 600, b'"}']
    response = limited.post(path, content=iter(chunks), headers={"Content-Type": "application/json"})
    _assert_too_large(response)
    assert response.headers["connection"] == "close"


def test_chunked_body_within_limit_passes(limited):
    chunks = [b"x" * 300] * 3
    response = limited.post("/api/v1/echo", content=iter(chunks))
    assert response.status_code == 200, response.text
    assert response.json() == {"size": 900}


def test_understated_content_length_does_not_bypass_the_limit():
    """Content-Length занижен (200), а тело на деле больше предела: подсчёт по потоку всё равно срабатывает.

    Настоящий сервер оборвал бы такой запрос сам; здесь проверяется именно middleware, поэтому гоним сырой ASGI-вызов."""
    app = _make_app()
    sent: list[dict] = []
    body = b"x" * (LIMIT + 500)
    messages = [
        {"type": "http.request", "body": body[:600], "more_body": True},
        {"type": "http.request", "body": body[600:], "more_body": False},
    ]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/echo",
        "raw_path": b"/api/v1/echo",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-length", b"200")],
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 8000),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413
    assert app.state.calls == []


@pytest.mark.parametrize("raw", ["abc", "-5", "", "1e3"])
def test_invalid_content_length_header_falls_back_to_stream_counting(raw):
    """Нечисловой/отрицательный Content-Length не ломает middleware: решает подсчёт по потоку."""
    app = _make_app()
    sent: list[dict] = []
    messages = [{"type": "http.request", "body": b"x" * 10, "more_body": False}]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/echo",
        "raw_path": b"/api/v1/echo",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), (b"content-length", raw.encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("localhost", 8000),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 200
    assert app.state.calls == [10]


# ---------------------------------------------------------------------------------------------------------------------
# (в) отключение, другие типы запросов, CORS
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("max_bytes", [0, -1])
def test_non_positive_limit_disables_the_check(max_bytes):
    client = TestClient(_make_app(max_bytes=max_bytes), base_url="http://localhost:8000")
    response = client.post("/api/v1/echo", content=b"x" * (LIMIT * 10))
    assert response.status_code == 200
    assert response.json() == {"size": LIMIT * 10}


def test_non_http_scopes_pass_through():
    """lifespan и websocket не имеют тела запроса и не проверяются."""
    seen: list[str] = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    middleware = BodySizeLimitMiddleware(inner, max_bytes=1)

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        pass

    asyncio.run(middleware({"type": "lifespan"}, receive, send))
    asyncio.run(middleware({"type": "websocket", "headers": [(b"content-length", b"999")]}, receive, send))
    assert seen == ["lifespan", "websocket"]


def test_413_carries_cors_headers_for_allowed_origin():
    """Лимит стоит внутри CORS: на dev-сервере браузер получает читаемый 413, а не безликую CORS-ошибку."""
    client = TestClient(_make_app(cors_origins=[ORIGIN]), base_url="http://localhost:8000")
    response = client.post("/api/v1/echo", content=b"x" * (LIMIT + 1), headers={"Origin": ORIGIN})
    _assert_too_large(response)
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_413_for_foreign_origin_is_blocked_earlier_by_origin_guard():
    """Чужой origin отсекается проверкой происхождения раньше лимита: 403, а не 413."""
    client = TestClient(_make_app(), base_url="http://localhost:8000")
    response = client.post("/api/v1/echo", content=b"x" * (LIMIT + 1), headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == ErrorCode.CROSS_ORIGIN_BLOCKED


# ---------------------------------------------------------------------------------------------------------------------
# (г) сообщение пользователю
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("max_bytes", "expected"),
    [
        (2 * 1024 * 1024, "2 МБ"),
        (10 * 1024 * 1024, "10 МБ"),
        (512 * 1024, "512 КБ"),
        (1024, "1 КБ"),
        (700, "700 байт"),
        (1536, "1536 байт"),
    ],
)
def test_describe_limit_has_no_fractions(max_bytes, expected):
    assert describe_limit(max_bytes) == expected


def test_error_detail_has_code_and_message_like_other_api_errors():
    detail = too_large_detail(2 * 1024 * 1024)
    assert set(detail) == {"code", "message"}
    assert detail["code"] == "REQUEST_BODY_TOO_LARGE"
    assert "2 МБ" in detail["message"]


# ---------------------------------------------------------------------------------------------------------------------
# (д) настоящее приложение: предел подключён и не мешает обычной работе
# ---------------------------------------------------------------------------------------------------------------------
def test_default_limit_is_two_mebibytes():
    assert MAX_REQUEST_BODY_BYTES == 2 * 1024 * 1024


def test_real_app_rejects_oversized_body(client):
    response = client.post(
        f"{API}/diagrams",
        content=json.dumps({"name": "Большая", "description": "x" * (MAX_REQUEST_BODY_BYTES + 1)}),
        headers={"Content-Type": "application/json"},
    )
    _assert_too_large(response, MAX_REQUEST_BODY_BYTES)


def test_real_app_rejects_oversized_chunked_body(client):
    """Тот же запрос без Content-Length: проверка подключена к настоящему приложению, а не только к тестовому."""
    payload = json.dumps({"name": "Большая", "description": "x" * (MAX_REQUEST_BODY_BYTES + 1)}).encode()
    chunks = [payload[i : i + 256 * 1024] for i in range(0, len(payload), 256 * 1024)]
    response = client.post(f"{API}/diagrams", content=iter(chunks), headers={"Content-Type": "application/json"})
    _assert_too_large(response, MAX_REQUEST_BODY_BYTES)


def test_real_app_still_accepts_ordinary_requests(client):
    response = client.post(f"{API}/diagrams", json={"name": "Обычная", "group_by": "structural_unit", "collapse_threshold": 10})
    assert response.status_code == 201, response.text


# Самые тяжёлые легитимные запросы: предел обязан пропускать их с запасом. Размеры измеряются, а не принимаются на веру.
def _json_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def test_layout_for_maximum_node_count_fits_with_margin():
    """5000 узлов (MAX_LAYOUT_NODES) с ключами в 200 символов — предельная раскладка диаграммы."""
    from app.services.diagram_graph import MAX_LAYOUT_KEY_LENGTH, MAX_LAYOUT_NODES

    positions = {f"{i:0{MAX_LAYOUT_KEY_LENGTH}d}": {"x": 123456.789, "y": -123456.789} for i in range(MAX_LAYOUT_NODES)}
    size = _json_size({"node_positions": positions, "viewport": {"x": 1.5, "y": 2.5, "zoom": 1.25}})
    assert size < MAX_REQUEST_BODY_BYTES, f"предельная раскладка ({size} байт) не помещается в предел {MAX_REQUEST_BODY_BYTES}"


def test_largest_useful_svg_icon_fits_with_margin():
    """Иконка длиннее MAX_CUSTOM_ICON_SVG_LENGTH пропускается экспортом, то есть бесполезна; даже если каждый символ в JSON
    записан как \\uXXXX (6 байт), она помещается в предел."""
    from app.services.diagram_export import MAX_CUSTOM_ICON_SVG_LENGTH

    markup = "я" * MAX_CUSTOM_ICON_SVG_LENGTH
    size = len(json.dumps({"name": "Иконка", "svg_markup": markup}, ensure_ascii=True).encode("ascii"))
    assert size < MAX_REQUEST_BODY_BYTES, f"иконка предельной длины ({size} байт) не помещается в предел {MAX_REQUEST_BODY_BYTES}"


def test_device_with_large_interface_stack_fits_with_margin():
    """Устройство-стек: 200 портов с подинтерфейсами, адресами и открытыми портами — на порядок больше реальных конфигураций."""
    interfaces = [
        {
            "name": f"GigabitEthernet1/0/{i}",
            "description": "Порт доступа, подключение рабочей станции бухгалтерии",
            "vlan_mode": "trunk",
            "all_vlans": True,
            "ips": [{"ip_address": f"10.{i // 250}.{i % 250}.{j}", "prefix_length": 24} for j in range(1, 5)],
            "subinterfaces": [{"name": f"{i}.{k}", "vlan_id": "00000000-0000-0000-0000-000000000000"} for k in range(1, 20)],
        }
        for i in range(200)
    ]
    size = _json_size({"interfaces": interfaces})
    assert size < MAX_REQUEST_BODY_BYTES // 2, f"стек из 200 портов занимает {size} байт — больше половины предела"
