"""Код-ревью Н-2 и Н-3: ответы API не кэшируются, публичный /health не раскрывает версию, CSP не допускает inline- и eval-скриптов.

Н-2: данные реестра на общем компьютере могли остаться в кэше браузера — у ответов /api/ не было Cache-Control. Публичный /health
(путь без входа, нужен Docker и CI) отдавал "version": по ней подбирают известные уязвимости.
Н-3: токен сессии лежит в localStorage, и любая XSS его прочитает; единственная защита второго рубежа — CSP без
'unsafe-inline' и 'unsafe-eval' для скриптов. Тест фиксирует это, чтобы послабление не появилось незаметно
(style-src 'unsafe-inline' — известный компромисс).

Запуск: pytest backend/tests/test_review_p1_api_cache_and_csp_hardening.py -v
"""

from __future__ import annotations

import pytest
from starlette.datastructures import MutableHeaders

from app.config import CSP_POLICY
from app.services.auth.security_headers import apply_security_headers

API = "/api/v1"


# --- Н-2: Cache-Control ----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [f"{API}/health", f"{API}/resources/devices", f"{API}/dashboard", f"{API}/auth/status"])
def test_api_responses_are_not_cacheable(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_error_responses_are_not_cacheable_either(client):
    """404 и 422 тоже сформированы приложением; внешний слой заголовков покрывает любой ответ, а не только успешные."""
    assert client.get(f"{API}/resources/no-such-resource").headers["cache-control"] == "no-store"
    assert client.get(f"{API}/resources/devices", params={"offset": -1}).headers["cache-control"] == "no-store"


def test_responses_of_the_blocked_layers_are_not_cacheable_too(client):
    response = client.get(f"{API}/health", headers={"Host": "evil.example"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"


def test_a_handler_may_set_its_own_cache_control():
    headers = MutableHeaders(raw=[])
    headers["Cache-Control"] = "private, max-age=30"
    apply_security_headers(headers, f"{API}/resources/devices")
    assert headers["cache-control"] == "private, max-age=30"
    assert [name for name, _ in headers.items() if name.lower() == "cache-control"] == ["cache-control"]


@pytest.mark.parametrize("path", ["/", "/assets/index-abc123.js", "/favicon.ico", "/docs", "/apiary", "/api"])
def test_only_api_paths_get_no_store(path):
    """Файлы интерфейса кэшируются как обычно — иначе при каждом открытии страницы заново качался бы весь клиент."""
    headers = MutableHeaders(raw=[])
    apply_security_headers(headers, path)
    assert "cache-control" not in headers, path


# --- Н-2: /health ----------------------------------------------------------------------------------------------------------------


def test_public_health_does_not_reveal_the_version(client):
    body = client.get(f"{API}/health").json()
    assert body == {"status": "ok", "service": "infra-registry"}
    assert "version" not in body


def test_health_does_not_reveal_the_version_when_authentication_is_on(client):
    assert client.post(f"{API}/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"}).status_code == 201
    assert client.put(f"{API}/auth/settings", json={"enabled": True}).status_code == 200
    anonymous = client.get(f"{API}/health")  # без токена: путь публичный, как и прежде — нужен проверке Docker
    assert anonymous.status_code == 200
    assert "version" not in anonymous.json()


def test_the_docker_healthcheck_only_needs_the_status_code():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parent.parent / "Dockerfile").read_text(encoding="utf-8")
    assert "/api/v1/health" in dockerfile and "version" not in dockerfile.split("HEALTHCHECK", 1)[1]


# --- Н-3: CSP --------------------------------------------------------------------------------------------------------------------


def _directives(policy: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for part in policy.split(";"):
        name, *values = part.split()
        result[name.lower()] = values
    return result


def test_default_csp_is_present_for_this_test():
    assert CSP_POLICY, "тест рассчитан на политику CSP по умолчанию (INFRA_REGISTRY_CSP не должен её отключать)"


def test_csp_forbids_inline_and_eval_scripts():
    directives = _directives(CSP_POLICY)
    # Скрипты регулирует script-src, а если его нет — default-src.
    script_sources = directives.get("script-src", directives.get("default-src", []))
    assert script_sources, "для скриптов не задано ни script-src, ни default-src — разрешено всё"
    assert "'unsafe-inline'" not in script_sources and "'unsafe-eval'" not in script_sources
    assert "*" not in script_sources and "data:" not in script_sources and "http:" not in script_sources


def test_unsafe_inline_is_allowed_only_for_styles():
    """Известный компромисс: Vue и DOMPurify ставят style-атрибуты. Больше нигде 'unsafe-inline' не появляется, 'unsafe-eval' — нигде."""
    for name, sources in _directives(CSP_POLICY).items():
        assert "'unsafe-eval'" not in sources, name
        if name != "style-src":
            assert "'unsafe-inline'" not in sources, name


def test_csp_keeps_the_other_basics():
    directives = _directives(CSP_POLICY)
    assert directives["object-src"] == ["'none'"]
    assert directives["frame-ancestors"] == ["'none'"]
    assert directives["connect-src"] == ["'self'"]
    assert directives["base-uri"] == ["'self'"]


def test_csp_is_sent_on_api_responses(client):
    assert client.get(f"{API}/health").headers["content-security-policy"] == CSP_POLICY
