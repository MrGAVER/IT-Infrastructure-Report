"""Трещотка на алиасы настроек (F-06): новый код не импортирует значения `Settings` как модульные константы.

`config.Settings` — неизменяемый снимок настроек, но рядом с ним остались десятки алиасов-констант (`DATABASE_URL`, `FORWARDED_ALLOW_IPS`,
…), которые модули импортируют ПО ЗНАЧЕНИЮ (`from ..config import FORWARDED_ALLOW_IPS`), а тесты подменяют через monkeypatch. Такой импорт
фиксирует значение в момент первого импорта модуля: подмена настроек позже на него не действует, и поведение зависит от порядка импорта.
Прежние места оставлены (на них опираются тесты), но их число может только уменьшаться, а новый код читает снимок в момент вызова:

    from .. import config
    ...
    config.settings.backup_interval_hours

Сломали проверку, добавив `from ..config import <АЛИАС>`? Перейдите на `config.settings.<поле>`. Перевели модуль на `config.settings` —
удалите его строку из `ALLOWED` (проверка ниже не даст оставить устаревшую запись, иначе список перестанет быть трещоткой).

Запуск: pytest backend/tests/test_review_p3_config_aliases.py -v
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "backend" / "app" / "config.py"
SCANNED = (ROOT / "backend" / "app", ROOT / "backend" / "alembic", ROOT / "launcher.py")

# (файл относительно корня репозитория, имя алиаса): существующие импорты по значению. Только убывает.
ALLOWED: frozenset[tuple[str, str]] = frozenset(
    {
        ("backend/alembic/env.py", "APP_DATA_DIR"),
        ("backend/alembic/env.py", "DATABASE_URL"),
        ("backend/app/api/auth.py", "AUTH_SESSION_TTL_HOURS"),
        ("backend/app/api/frontend_assets.py", "FRONTEND_DIR"),
        ("backend/app/api/report_builder.py", "REPORT_DIR"),
        ("backend/app/api/reports.py", "REPORT_DIR"),
        ("backend/app/db.py", "DATABASE_URL"),
        ("backend/app/db.py", "DB_POOL_OPTIONS"),
        ("backend/app/main.py", "ACCEPT_IP_HOSTS"),
        ("backend/app/main.py", "ALLOWED_CLIENTS"),
        ("backend/app/main.py", "ALLOWED_HOSTS"),
        ("backend/app/main.py", "CORS_ALLOWED_ORIGINS"),
        ("backend/app/main.py", "DATABASE_URL"),
        ("backend/app/main.py", "ENABLE_DOCS"),
        ("backend/app/main.py", "FORWARDED_ALLOW_IPS"),
        ("backend/app/main.py", "FRONTEND_DIR"),
        ("backend/app/main.py", "MAX_REQUEST_BODY_BYTES"),
        ("backend/app/main.py", "SETUP_TOKEN"),
        ("backend/app/services/audit_retention.py", "AUDIT_RETENTION_DAYS"),
        ("backend/app/services/auth/guards.py", "SETUP_TOKEN"),
        ("backend/app/services/auth/lockout.py", "AUTH_KNOWN_CLIENT_DAYS"),
        ("backend/app/services/auth/lockout.py", "AUTH_LOCKOUT_MINUTES"),
        ("backend/app/services/auth/lockout.py", "AUTH_MAX_FAILED_ATTEMPTS"),
        ("backend/app/services/auth/login.py", "AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS"),
        ("backend/app/services/auth/passwords.py", "AUTH_MIN_PASSWORD_LENGTH"),
        ("backend/app/services/auth/proxy_headers.py", "FORWARDED_ALLOW_IPS"),
        ("backend/app/services/auth/security_headers.py", "CSP_POLICY"),
        ("backend/app/services/auth/sessions.py", "AUTH_SESSION_TTL_HOURS"),
        ("backend/app/services/db_backup.py", "DATABASE_URL"),
        ("backend/app/services/report_cleanup.py", "REPORT_MAX_FILES"),
        ("backend/app/services/report_cleanup.py", "REPORT_RETENTION_DAYS"),
    }
)


def _mentions_settings(node: ast.AST) -> bool:
    return any(isinstance(inner, ast.Name) and inner.id == "settings" for inner in ast.walk(node))


def settings_aliases(config_source: str) -> set[str]:
    """Имена верхнего уровня config.py, значение которых берётся из снимка `settings` (то есть алиасы полей `Settings`)."""
    aliases: set[str] = set()
    for node in ast.parse(config_source).body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and _mentions_settings(node.value)
        ):
            aliases.add(node.targets[0].id)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
            and _mentions_settings(node.value)
        ):
            aliases.add(node.target.id)
    return aliases


def alias_imports(source: str, relative_path: str, aliases: set[str]) -> set[tuple[str, str]]:
    """Импорты алиасов настроек по значению: `from app.config import X`, `from ..config import X` (где угодно в файле, в том числе внутри
    функций). `from . import config` и импорт функций (`ensure_data_dirs`) — не алиасы и не считаются."""
    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ImportFrom):
            continue
        from_config = (node.level >= 1 and node.module == "config") or (node.level == 0 and node.module == "app.config")
        if from_config:
            found.update((relative_path, item.name) for item in node.names if item.name in aliases)
    return found


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED:
        files.extend([root] if root.is_file() else sorted(root.rglob("*.py")))
    return files


def _current_imports() -> set[tuple[str, str]]:
    aliases = settings_aliases(CONFIG.read_text(encoding="utf-8"))
    found: set[tuple[str, str]] = set()
    for path in _python_files():
        found |= alias_imports(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix(), aliases)
    return found


def test_aliases_are_found_so_the_ratchet_is_not_vacuous():
    aliases = settings_aliases(CONFIG.read_text(encoding="utf-8"))

    assert {"DATABASE_URL", "FORWARDED_ALLOW_IPS", "AUTH_SESSION_TTL_HOURS", "APP_DATA_DIR"} <= aliases
    assert "ensure_data_dirs" not in aliases and "AUDIT_REPORT_SUBDIR" not in aliases, "функции и константы без снимка — не алиасы"
    assert len(_current_imports()) > 10


def test_no_new_imports_of_settings_aliases_by_value():
    new = sorted(_current_imports() - ALLOWED)

    assert not new, (
        f"Новые импорты значений настроек по значению: {new}. Читайте снимок в момент вызова: `from .. import config` и "
        "`config.settings.<поле>` — тогда подмена настроек (тесты, перезапуск планировщика) действует, а поведение не зависит от "
        "порядка импорта."
    )


def test_allowed_list_only_shrinks():
    stale = sorted(ALLOWED - _current_imports())

    assert not stale, f"Эти модули уже не импортируют алиасы — удалите строки из ALLOWED (список может только уменьшаться): {stale}"


def test_detector_sees_every_import_form_and_ignores_the_rest():
    aliases = {"DATABASE_URL", "REPORT_DIR"}
    source = (
        "from app.config import DATABASE_URL, ensure_data_dirs\n"
        "from ..config import REPORT_DIR as report_dir\n"
        "from . import config\n"
        "from .other import DATABASE_URL as not_from_config\n"
        "def late():\n"
        "    from ...config import DATABASE_URL\n"
    )

    found = alias_imports(source, "x.py", aliases)

    assert found == {("x.py", "DATABASE_URL"), ("x.py", "REPORT_DIR")}
