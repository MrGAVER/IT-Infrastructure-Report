"""A-02: docker-compose.yml по умолчанию не должен публиковать открытый на запись реестр.

Аутентификация выключена по умолчанию, а из контейнера включить её без токена установки нельзя (адрес клиента — шлюз
Docker, а не localhost). Поэтому compose обязан требовать INFRA_REGISTRY_SETUP_TOKEN и по умолчанию привязывать порт к
127.0.0.1. Docker в тестовой среде недоступен — проверяется сам файл (как test_docker_frontend_dirs.py проверяет Dockerfile).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
APP = COMPOSE["services"]["app"]


def _env_example() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def test_setup_token_is_required_with_a_message():
    value = APP["environment"]["INFRA_REGISTRY_SETUP_TOKEN"]
    assert re.fullmatch(r"\$\{INFRA_REGISTRY_SETUP_TOKEN:\?[^}]+\}", value), "токен установки должен быть обязательным (${VAR:?сообщение}): без него защиту из Docker не включить"


def test_postgres_password_is_still_required():
    assert APP["environment"]["POSTGRES_PASSWORD"].startswith("${POSTGRES_PASSWORD:?")
    assert COMPOSE["services"]["db"]["environment"]["POSTGRES_PASSWORD"].startswith("${POSTGRES_PASSWORD:?")


def test_app_port_is_bound_to_localhost_by_default():
    assert APP["ports"] == ["${INFRA_REGISTRY_BIND:-127.0.0.1}:8000:8000"], "без INFRA_REGISTRY_BIND порт должен слушать только 127.0.0.1"


def test_database_port_is_not_published():
    assert "ports" not in COMPOSE["services"]["db"]


def test_env_example_has_non_empty_token_placeholder_and_keeps_bind_local():
    env = _env_example()
    assert env.get("INFRA_REGISTRY_SETUP_TOKEN"), "в .env.example токен должен быть непустым плейсхолдером"
    assert "INFRA_REGISTRY_BIND" not in env, "INFRA_REGISTRY_BIND в .env.example должен быть закомментирован: по умолчанию только localhost"


def test_readme_documents_token_and_bind():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "INFRA_REGISTRY_BIND" in readme
    assert "INFRA_REGISTRY_SETUP_TOKEN" in readme
