"""Политика плановых копий SQLite: что действует сейчас и как её меняет администратор («Настройки → Резервные копии»).

Три параметра, у каждого свой источник, и приоритет у всех один — **окружение > настройки > умолчание**:

* интервал (`interval_hours`, 0 — копии выключены) и число хранимых копий (`keep`) — переменные `INFRA_REGISTRY_BACKUP_INTERVAL_HOURS` и
  `INFRA_REGISTRY_BACKUP_KEEP` (в EXE их выставляет `infra_registry.toml`, раздел `[backup]`). Заданные так, они в форме только показываются
  («задано в окружении»): администратор приложения не должен переопределять то, что оператор закрепил в `.env` или toml. Не заданы —
  действует значение из «Настроек» (`app_preferences`, ключи `backup.interval_hours` и `backup.keep`), а если и его нет — умолчание
  (24 ч, 7);
* каталог копий (`directory`) из интерфейса НЕ меняется: запись произвольного пути из веб-формы дала бы любому администратору приложения
  возможность класть копию всей базы (хэши паролей, журнал аудита) в раздаваемые каталоги или за пределы тома Docker. Каталог задаёт
  оператор — `INFRA_REGISTRY_BACKUP_DIR` — и форма его только показывает.

Сервис ничего не знает про HTTP и планировщик: владельцем ответа и перезапуска задачи остаётся `api/backup_settings.py`. Настройки
читаются из `config.settings` в момент вызова (подмена снимка в тестах действует). Повреждённое значение в БД (правка вручную)
считается не заданным — как у `services/preferences.py`: из-за настройки копий приложение не должно переставать запускаться.

Пример:
    policy = load_policy(session)                        # BackupPolicy(interval_hours=24.0, keep=7, ...)
    update = update_policy(session, {"keep": 14})        # пишет в app_preferences и в журнал аудита, коммитит
    update = update_policy(session, {"interval_hours": None})   # сбросить к умолчанию
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import config
from .. import db as app_db  # через модуль, а не `from ..db import SessionLocal`: тесты подменяют app.db.SessionLocal
from ..constants import BACKUP_MAX_INTERVAL_HOURS, BACKUP_MAX_KEEP, BACKUP_MIN_INTERVAL_HOURS, AuditAction
from ..models import AppPreference
from .crud import audit
from .db_backup import auto_backup_time, latest_auto_backup, sqlite_database_path
from .preferences import OWNER_GLOBAL
from .timeutil import to_naive_utc

logger = logging.getLogger(__name__)

AUDIT_ENTITY = "backup-settings"  # раздел записей об изменении настроек копий в журнале аудита
SETTINGS_ID = "singleton"
KEY_INTERVAL = "backup.interval_hours"
KEY_KEEP = "backup.keep"
# параметр (имя из config.BACKUP_PARAMETER_VARIABLES) → ключ app_preferences
STORED_KEYS = {"interval_hours": KEY_INTERVAL, "keep": KEY_KEEP}

Source = Literal["environment", "settings", "default"]
UNSUPPORTED_REASON = "Плановые копии средствами приложения делаются только для SQLite в файле; для PostgreSQL копии делает оператор СУБД."


class SettingPinnedByEnvironment(Exception):
    """Параметр задан окружением (или infra_registry.toml) и из интерфейса не меняется."""

    def __init__(self, parameter: str) -> None:
        self.parameter = parameter
        self.variable = config.BACKUP_PARAMETER_VARIABLES[parameter]
        super().__init__(f"Параметр задан переменной окружения {self.variable} и в настройках не меняется: измените его там.")


@dataclass(frozen=True)
class BackupPolicy:
    """Действующая политика плановых копий и откуда взято каждое значение."""

    interval_hours: float  # 0 — копии выключены
    keep: int
    directory: Path
    interval_source: Source
    keep_source: Source
    directory_source: Literal["environment", "default"]


@dataclass(frozen=True)
class PolicyUpdate:
    policy: BackupPolicy
    changed: bool  # False — присланное равно сохранённому: ни записи в журнале, ни перезапуска планировщика


@dataclass(frozen=True)
class LatestBackup:
    name: str
    size_bytes: int
    created_at: datetime  # naive UTC


def is_valid_interval(value: Any) -> bool:
    """Допустимое сохранённое значение интервала: 0 (выкл.) или от BACKUP_MIN_INTERVAL_HOURS до BACKUP_MAX_INTERVAL_HOURS. Нечисла (в том
    числе bool) — нет. Те же границы проверяет схема запроса; здесь — для значения, которое могли испортить прямой правкой БД."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    return value == 0 or BACKUP_MIN_INTERVAL_HOURS <= value <= BACKUP_MAX_INTERVAL_HOURS


def is_valid_keep(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= BACKUP_MAX_KEEP


_VALIDATORS = {KEY_INTERVAL: is_valid_interval, KEY_KEEP: is_valid_keep}


def _read_stored(session: Session) -> dict[str, Any]:
    """Сохранённые в «Настройках» значения {ключ: значение}; испорченные и недопустимые пропускаются (с предупреждением в лог)."""
    stored: dict[str, Any] = {}
    for key, is_valid in _VALIDATORS.items():
        row = session.get(AppPreference, (OWNER_GLOBAL, key))
        if row is None:
            continue
        try:
            value = json.loads(row.value)
        except ValueError:
            value = None
        if is_valid(value):
            stored[key] = value
        else:
            logger.warning("Настройка %s/%s испорчена или вне допустимых границ — пропущена, действует умолчание", OWNER_GLOBAL, key)
    return stored


def _resolve(parameter: str, key: str, stored: dict[str, Any], current: Any) -> tuple[Any, Source]:
    """(значение, источник) одного параметра: окружение > настройки > умолчание. `current` — значение снимка `config.settings`:
    из окружения, если параметр им задан, иначе умолчание."""
    if parameter in config.settings.backup_from_env:
        return current, "environment"
    if key in stored:
        return stored[key], "settings"
    return current, "default"


def policy_from_stored(stored: dict[str, Any]) -> BackupPolicy:
    settings = config.settings
    interval, interval_source = _resolve("interval_hours", KEY_INTERVAL, stored, settings.backup_interval_hours)
    keep, keep_source = _resolve("keep", KEY_KEEP, stored, settings.backup_keep)
    return BackupPolicy(
        interval_hours=float(interval),
        keep=int(keep),
        directory=settings.backup_dir,
        interval_source=interval_source,
        keep_source=keep_source,
        directory_source="environment" if "directory" in settings.backup_from_env else "default",
    )


def load_policy(session: Session) -> BackupPolicy:
    """Действующая политика (см. описание модуля)."""
    return policy_from_stored(_read_stored(session))


def environment_policy() -> BackupPolicy:
    """Политика без чтения БД: окружение и умолчания. Запасной вариант, когда настройки прочитать не удалось."""
    return policy_from_stored({})


def load_policy_or_environment() -> BackupPolicy:
    """Политика для запуска планировщика: в своей сессии; БД недоступна (нет таблицы, сбой) — окружение и умолчания, ошибка пишется в лог.

    Планировщик стартует в lifespan, и сбой чтения настроек не должен ронять запуск приложения: копии идут по умолчанию, пока БД не
    отвечает."""
    try:
        with app_db.SessionLocal() as session:
            return load_policy(session)
    except SQLAlchemyError:
        logger.exception("Не удалось прочитать настройки плановых копий из БД — действуют окружение и значения по умолчанию")
        return environment_policy()


def database_file() -> Optional[Path]:
    """Файл БД, который копирует планировщик; None — база не файловая SQLite (PostgreSQL, :memory:)."""
    return sqlite_database_path(config.settings.database_url)


def _interval_text(hours: float) -> str:
    return "выключены" if hours == 0 else f"каждые {hours:g} ч"


def _describe_change(before: BackupPolicy, after: BackupPolicy, patch: dict[str, Any]) -> str:
    parts = []
    if "interval_hours" in patch:
        parts.append(f"интервал: {_interval_text(before.interval_hours)} → {_interval_text(after.interval_hours)}")
    if "keep" in patch:
        parts.append(f"хранить копий: {before.keep} → {after.keep}")
    reset = [label for name, label in (("interval_hours", "интервал"), ("keep", "число копий")) if patch.get(name, 0) is None]
    text = "Плановые копии базы — " + "; ".join(parts)
    if reset:
        text += f" (сброшено к значению по умолчанию: {', '.join(reset)})"
    return text


def update_policy(session: Session, patch: dict[str, Any]) -> PolicyUpdate:
    """Сохраняет интервал и/или число копий (`None` — сбросить к умолчанию), пишет об этом в журнал аудита и коммитит.

    `patch` — только присланные поля (`interval_hours`, `keep`); значения уже проверены схемой запроса. Параметр, заданный окружением, не
    меняется: `SettingPinnedByEnvironment` (до любой записи — ни одно поле из присланных не сохраняется). Значение, равное сохранённому,
    ничего не меняет: ни записи в журнале, ни перезапуска планировщика. В журнале — кто (актёр запроса), старое и новое действующие
    значения."""
    unknown = set(patch) - set(STORED_KEYS)
    if unknown:
        raise ValueError(f"Неизвестные параметры плановых копий: {sorted(unknown)}")
    for parameter in patch:
        if parameter in config.settings.backup_from_env:
            raise SettingPinnedByEnvironment(parameter)

    stored = _read_stored(session)
    before = policy_from_stored(stored)
    changed = False
    for parameter, value in patch.items():
        key = STORED_KEYS[parameter]
        row = session.get(AppPreference, (OWNER_GLOBAL, key))
        if value is None:
            if row is not None:
                session.delete(row)
                changed = True
        elif row is None:
            session.add(AppPreference(owner=OWNER_GLOBAL, key=key, value=json.dumps(value)))
            changed = True
        elif stored.get(key) != value:  # испорченное значение (не попало в stored) тоже перезаписывается
            row.value = json.dumps(value)
            changed = True
    if not changed:
        return PolicyUpdate(before, changed=False)

    after = policy_from_stored(_stored_after(stored, patch))
    audit(session, AUDIT_ENTITY, SETTINGS_ID, AuditAction.UPDATE, _describe_change(before, after, patch))
    session.commit()
    return PolicyUpdate(after, changed=True)


def _stored_after(stored: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(stored)
    for parameter, value in patch.items():
        key = STORED_KEYS[parameter]
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def latest_backup(directory: Path) -> Optional[LatestBackup]:
    """Самая новая плановая копия в каталоге: имя файла, размер, момент создания (по метке в имени, а не по времени изменения файла —
    оно несёт состояние БД, см. db_backup.backup_scheduled). None — копий нет, база не в файле или каталог недоступен (отключённый сетевой
    диск): форма настроек показывает «копий ещё нет», а не ошибку."""
    db_path = database_file()
    if db_path is None:
        return None
    try:
        latest = latest_auto_backup(db_path, directory)
        if latest is None:
            return None
        created = datetime.fromtimestamp(auto_backup_time(latest), timezone.utc)
        return LatestBackup(latest.name, latest.stat().st_size, to_naive_utc(created))
    except OSError:
        logger.warning("Каталог плановых копий %s недоступен для чтения", directory, exc_info=True)
        return None
