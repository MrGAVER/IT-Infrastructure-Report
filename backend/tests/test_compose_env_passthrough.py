"""B-01 (код-ревью main b375f58): всё, что описано в .env.example, должно доходить до контейнера через docker-compose.yml.

Compose передаёт приложению только перечисленные в `environment` переменные (`env_file:` в файле нет, `.env` служит лишь для
подстановки `${…}`). Раньше пять настроек из .env.example в `environment` не попадали: оператор задавал, например,
INFRA_REGISTRY_ALLOWED_CLIENTS, а приложение работало без ограничения по адресам — отказ «в открытую сторону». Проверка сделана
намеренно простой (поиск `${КЛЮЧ` в тексте compose, а не разбор YAML): ключ, использованный где угодно (скажем, INFRA_REGISTRY_BIND
в `ports:`), считается доступным.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_TEXT = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

# «KEY=…» и «# KEY=…»; проза комментариев (в ней нет «=» сразу после слова из заглавных букв) не затрагивается.
_KEY_LINE = re.compile(r"\s*#?\s*([A-Z][A-Z0-9_]{3,})=")


def _documented_keys() -> set[str]:
    keys: set[str] = set()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        match = _KEY_LINE.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def _referenced_keys() -> set[str]:
    return set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)", COMPOSE_TEXT))


def test_documented_keys_are_found():
    # Страж не должен «проходить» на пустом множестве: если формат .env.example изменится и регулярное выражение перестанет
    # находить ключи, проверка ниже молча стала бы бессмысленной.
    keys = _documented_keys()
    assert {"POSTGRES_PASSWORD", "INFRA_REGISTRY_ALLOWED_CLIENTS", "INFRA_REGISTRY_ENABLE_DOCS"} <= keys


def test_every_documented_env_key_is_forwarded_by_compose():
    missing = sorted(_documented_keys() - _referenced_keys())
    assert not missing, (
        f"Ключи из .env.example не пробрасываются в контейнер ({missing}): оператор задаст значение, а приложение его "
        "не увидит. Добавьте их в app.environment docker-compose.yml."
    )


def test_csp_is_never_forwarded_with_an_empty_default():
    # Для INFRA_REGISTRY_CSP пустая строка — не «не задано», а «отключить Content-Security-Policy» (config.CSP_POLICY):
    # `${INFRA_REGISTRY_CSP:-}` в compose молча выключил бы защиту у каждого, кто эту переменную не задавал.
    assert not re.search(r"INFRA_REGISTRY_CSP\s*:\s*\$\{[^}]*:-\}", COMPOSE_TEXT)


def test_forwarded_numeric_keys_do_not_default_to_empty():
    # Пока config.py разбирает эти переменные «голым» int()/float(), пустое значение роняет запуск
    # (`ValueError: invalid literal for int() with base 10: ''`), и контейнер уходит в цикл перезапусков. После A-03 пусто безопасно,
    # но явные умолчания в compose делают результат независимым от порядка слияния пакетов A и B. Если решите хранить умолчания только в
    # config.py (пустое `${VAR:-}`), удалите этот тест вместе с переходом.
    numeric = (
        "INFRA_REGISTRY_REPORT_RETENTION_DAYS",
        "INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES",
        "INFRA_REGISTRY_SESSION_TTL_HOURS",
        "INFRA_REGISTRY_AUTH_MAX_ATTEMPTS",
        "INFRA_REGISTRY_AUTH_LOCKOUT_MINUTES",
        "INFRA_REGISTRY_AUTH_MIN_PASSWORD_LENGTH",
        "INFRA_REGISTRY_AUTH_KNOWN_CLIENT_DAYS",
    )
    empty_defaults = [key for key in numeric if re.search(rf"{key}\s*:\s*\$\{{[^}}]*:-\}}", COMPOSE_TEXT)]
    assert not empty_defaults, f"числовые настройки с пустым умолчанием: {empty_defaults}"
