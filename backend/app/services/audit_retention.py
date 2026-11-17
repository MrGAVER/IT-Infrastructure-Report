"""Политика хранения журнала аудита: срок хранения, очистка по сроку, настройки.

Журнал по смыслу нельзя удалять молча, поэтому по умолчанию он не очищается (срок 0). Срок задаёт администратор в форме «Настройки аудита»
(PUT /api/v1/audit-log/settings); если он не задан, действует INFRA_REGISTRY_AUDIT_RETENTION_DAYS (по умолчанию 0). Записи старше срока
удаляются:

* пакетами по BATCH_SIZE строк, каждый пакет — отдельная короткая транзакция (долгое удаление миллионов строк одной транзакцией держало бы
  блокировки и раздувало журнал БД); за один запуск — не более MAX_BATCHES_PER_RUN пакетов, остаток доберёт следующий запуск;
* только строки строго старше границы `now - срок`: запись, созданная ровно на границе, и все более новые остаются;
* не чаще раза в сутки (audit_settings.last_cleanup_at) — для ленивых запусков; сохранение настроек администратором запускает очистку сразу;
* перед удалением каждого пакета его строки записываются в файл архива и сбрасываются на диск (services/audit_archive.py, каталог
  `reports/audit/`): очистка не должна быть способом бесследно стереть журнал. Не удалось сохранить архив — пакет не удаляется,
  очистка считается неудавшейся (как сбой БД) и повторится при следующем запуске;
* факт очистки (число строк, граница и имя файла архива) пишется в сам журнал отдельной записью (раздел «audit-settings», действие DELETE).

Отдельного планировщика в приложении нет (как и у services/report_cleanup.py и уборки сессий), поэтому ленивые запуски — при старте сервера
и при открытии журнала (GET /api/v1/audit-log). Если журнал не открывают и сервер не перезапускают, очистка ждёт ближайшего из этих событий.

Пример:
    run_scheduled_cleanup(session)                      # ленивый запуск: срок задан и прошли сутки
    update_retention(session, 90)                       # срок 90 дней: сохранить и сразу очистить
    update_retention(session, None)                     # сбросить к значению по умолчанию (из окружения)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from .. import db as app_db  # через модуль, а не `from ..db import SessionLocal`: тесты подменяют app.db.SessionLocal
from ..config import AUDIT_RETENTION_DAYS
from ..constants import AUDIT_RETENTION_MAX_DAYS, AuditAction
from ..models import AuditLog, AuditSettings
from .actor_context import Actor
from .audit_archive import ARCHIVE_COLUMNS, AuditArchive, AuditArchiveError, audit_archive_dir
from .crud import audit
from .timeutil import utcnow_naive

logger = logging.getLogger(__name__)

SETTINGS_ID = "singleton"
AUDIT_ENTITY = "audit-settings"  # раздел записей об изменении настроек и об очистке; не 'audit-log' — записи этого раздела audit() не пишет
BATCH_SIZE = 1000
MAX_BATCHES_PER_RUN = 100  # 100 000 строк за запуск: страница журнала, открытая на «первой очистке» большого журнала, не зависает надолго
DELETE_CHUNK = 500  # id в одном DELETE: пакет 1000 строк делится так, чтобы не упереться в предел параметров старых SQLite (999)
CLEANUP_INTERVAL = timedelta(days=1)
# Ленивый запуск не принадлежит пользователю, открывшему журнал: запись об очистке подписана «системой», а не его именем.
SYSTEM_ACTOR = Actor(user_id=None, username="система", ip=None)


@dataclass(frozen=True)
class PurgeResult:
    removed: int
    cutoff: datetime  # записи строго старше этого момента (naive UTC) удалены
    complete: bool  # False — остановились на лимите пакетов за запуск, остаток удалит следующий запуск
    archive_path: Optional[Path] = None  # файл с копиями удалённых записей; None, если удалять было нечего


@dataclass(frozen=True)
class RetentionState:
    """Настройки хранения как значения предметной области: JSON с именами полей и ISO-строками собирает слой API (api/audit_log.py)."""

    retention_days: int  # действующий срок, 0 — не удалять
    is_default: bool  # срок в форме не задан, действует значение по умолчанию из окружения
    default_retention_days: int
    max_retention_days: int
    last_cleanup_at: Optional[datetime]  # naive UTC


@dataclass(frozen=True)
class RetentionUpdate:
    row: AuditSettings
    removed: int  # сколько записей удалено сразу при сохранении
    cleanup_failed: bool  # срок сохранён, но очистка не удалась (ошибка БД); повторится при ближайшем ленивом запуске


def get_audit_settings(session: Session) -> Optional[AuditSettings]:
    """Строка настроек или None, если их ещё ни разу не сохраняли (тогда действуют значения по умолчанию)."""
    return session.get(AuditSettings, SETTINGS_ID)


def get_or_create_audit_settings(session: Session) -> AuditSettings:
    row = get_audit_settings(session)
    if row is not None:
        return row
    row = AuditSettings(id=SETTINGS_ID)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Гонка двух первых записей: проигравший просто перечитывает строку победителя (как get_or_create_auth_settings).
        session.rollback()
        row = session.get(AuditSettings, SETTINGS_ID)
    else:
        session.refresh(row)
    return row


def effective_retention_days(row: Optional[AuditSettings]) -> int:
    """Действующий срок: заданный в форме, а если не задан — из окружения. 0 — не удалять."""
    if row is not None and row.retention_days is not None:
        return row.retention_days
    return AUDIT_RETENTION_DAYS


def retention_state(row: Optional[AuditSettings]) -> RetentionState:
    return RetentionState(
        retention_days=effective_retention_days(row),
        is_default=row is None or row.retention_days is None,
        default_retention_days=AUDIT_RETENTION_DAYS,
        max_retention_days=AUDIT_RETENTION_MAX_DAYS,
        last_cleanup_at=row.last_cleanup_at if row is not None else None,
    )


def cleanup_is_due(row: Optional[AuditSettings], now: datetime) -> bool:
    return row is None or row.last_cleanup_at is None or now - row.last_cleanup_at >= CLEANUP_INTERVAL


def _has_expired(session: Session, cutoff: datetime) -> bool:
    return bool(session.scalar(select(exists().where(AuditLog.created_at < cutoff))))


def _delete_by_ids(session: Session, ids: Sequence[str]) -> int:
    """Удаляет ровно перечисленные записи (теми же id, что попали в архив), порциями по DELETE_CHUNK. Возвращает число удалённых строк."""
    deleted = 0
    for start in range(0, len(ids), DELETE_CHUNK):
        chunk = ids[start : start + DELETE_CHUNK]
        statement = delete(AuditLog).where(AuditLog.id.in_(chunk)).execution_options(synchronize_session=False)
        deleted += session.execute(statement).rowcount or 0
    return deleted


def purge_expired_entries(
    session: Session,
    retention_days: int,
    *,
    now: datetime,
    batch_size: Optional[int] = None,
    max_batches: Optional[int] = None,
    archive_dir: Optional[Path] = None,
) -> PurgeResult:
    """Удаляет записи журнала строго старше `now - retention_days` пакетами по batch_size (по умолчанию BATCH_SIZE), старые первыми (индекс
    ix_audit_log_created_at_id).

    Пакет: читаем строки → записываем их в архив и сбрасываем на диск → удаляем ровно эти id → commit. Каждый пакет — своя короткая
    транзакция, поэтому и на SQLite, и на PostgreSQL (DELETE … LIMIT там нет) удаление миллионов строк не держит блокировки. Записи,
    которой нет в архиве, не удаляется никогда: сбой архива — `AuditArchiveError` до удаления пакета, уже удалённые пакеты остаются
    удалёнными (они сохранены). Короткий пакет (меньше batch_size) — последний. archive_dir — каталог архива (по умолчанию
    `reports/audit/`). Возвращает число удалённых строк, границу, признак «дочистили до конца» и файл архива."""
    if retention_days <= 0:
        raise ValueError("retention_days должен быть положительным: срок 0 означает «не удалять»")
    batch_size = batch_size or BATCH_SIZE  # размеры читаются при вызове, а не при определении функции: тесты подменяют константы модуля
    max_batches = max_batches or MAX_BATCHES_PER_RUN
    cutoff = now - timedelta(days=retention_days)
    expired = select(*ARCHIVE_COLUMNS).where(AuditLog.created_at < cutoff)
    oldest_batch = expired.order_by(AuditLog.created_at, AuditLog.id).limit(batch_size)
    removed = 0
    with AuditArchive(archive_dir or audit_archive_dir(), now=now) as archive:
        for _ in range(max_batches):
            rows = session.execute(oldest_batch).all()
            if rows:
                archive.write_batch(rows)
                removed += _delete_by_ids(session, [row.id for row in rows])
                session.commit()
            if len(rows) < batch_size:
                return PurgeResult(removed, cutoff, complete=True, archive_path=archive.path)
        return PurgeResult(removed, cutoff, complete=not _has_expired(session, cutoff), archive_path=archive.path)


def _days_text(days: int) -> str:
    return "не ограничен" if days == 0 else f"{days} дн."


def _describe_purge(days: int, result: PurgeResult) -> str:
    head = f"Очистка журнала по сроку хранения ({days} дн.): удалено записей — {result.removed}"
    text = f"{head}, граница — {result.cutoff:%d.%m.%Y %H:%M} UTC (удалены более старые)."
    if result.archive_path is not None:  # только имя: полный путь раскрывал бы устройство сервера всем, кто читает журнал
        text += f" Копия удалённых записей сохранена в файле {result.archive_path.name}."
    return text if result.complete else text + " Очистка продолжится при следующем запуске."


def run_cleanup(session: Session, *, now: datetime, actor: Optional[Actor]) -> Optional[PurgeResult]:
    """Один проход очистки по действующему сроку, без проверки «не чаще раза в сутки». None — срок не задан (0), делать нечего.

    Запись об очистке пишется, только если что-то удалено: ежедневная строка «удалено 0» засоряла бы журнал, а о том, что очистка идёт,
    говорит last_cleanup_at в форме настроек. actor=None — автор берётся из контекста запроса (администратор, сохранивший настройки)."""
    row = get_audit_settings(session)
    days = effective_retention_days(row)
    if days <= 0:
        return None
    row = row or get_or_create_audit_settings(session)  # last_cleanup_at некуда записать без строки
    result = purge_expired_entries(session, days, now=now)
    if result.removed:
        audit(session, AUDIT_ENTITY, SETTINGS_ID, AuditAction.DELETE, _describe_purge(days, result), actor=actor)
    # Дочистили — отмечаем; остановились на лимите пакетов — отметку снимаем, чтобы следующий запуск продолжил без ожидания суток.
    row.last_cleanup_at = now if result.complete else None
    session.commit()
    return result


def _claim_cleanup(session: Session, now: datetime) -> bool:
    """Атомарно «занимает» очередной ленивый запуск: один UPDATE с условием «очистка назначена» ставит last_cleanup_at = now.
    Побеждает ровно одна сессия (одновременные запросы, несколько воркеров), остальные получают False и ничего не удаляют: двойных
    записей «удалено N» и встречных DELETE больше нет. Строка настроек должна существовать (get_or_create_audit_settings).

    Core-UPDATE не знает о сессионной карте объектов, а у SessionLocal expire_on_commit=False, поэтому загруженная строка настроек
    устаревает — сбрасываем её, чтобы дальше читалось значение из БД."""
    is_due = or_(AuditSettings.last_cleanup_at.is_(None), AuditSettings.last_cleanup_at <= now - CLEANUP_INTERVAL)
    claim = update(AuditSettings).where(AuditSettings.id == SETTINGS_ID, is_due).values(last_cleanup_at=now)
    claimed = session.execute(claim.execution_options(synchronize_session=False)).rowcount
    session.commit()
    session.expire_all()
    return bool(claimed)


def _release_claim(session: Session, now: datetime, previous: Optional[datetime]) -> None:
    """Возвращает прежнюю отметку, если занятый запуск не состоялся (сбой): иначе неудачная очистка отложилась бы на сутки.
    Возвращает только свою отметку (last_cleanup_at == now) — отметку, которую успел поставить кто-то другой, не трогает.
    Сама не бросает ошибок."""
    try:
        ours = update(AuditSettings).where(AuditSettings.id == SETTINGS_ID, AuditSettings.last_cleanup_at == now)
        session.execute(ours.values(last_cleanup_at=previous).execution_options(synchronize_session=False))
        session.commit()
        session.expire_all()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("Не удалось вернуть отметку запуска очистки журнала аудита: следующая попытка — не раньше чем через сутки")


def run_scheduled_cleanup(session: Session, *, now: Optional[datetime] = None) -> int:
    """Ленивый запуск (старт сервера, открытие журнала): срок задан и с прошлой очистки прошли сутки. Возвращает число удалённых записей.

    Запуск сначала «занимается» атомарно (`_claim_cleanup`): из нескольких одновременных вызовов чистит один. Не состоялся из-за сбоя —
    отметка возвращается, и следующий запуск повторит попытку.

    Не бросает ошибок вообще: журнал открывают ради чтения, а сервер запускают ради работы, и сбой очистки — БД, неверный срок,
    любая непредвиденная ошибка — не должен ломать ни то ни другое. Ошибка пишется в журнал приложения (logger.exception).

    Вызывать из фона со своей сессией (`run_scheduled_cleanup_in_own_session`): очистка может идти долго, и держать ради неё запрос
    читателя журнала нельзя."""
    now = now or utcnow_naive()
    previous: Optional[datetime] = None
    claimed = False
    try:
        row = get_audit_settings(session)
        if effective_retention_days(row) <= 0 or not cleanup_is_due(row, now):
            return 0
        previous = row.last_cleanup_at if row is not None else None
        get_or_create_audit_settings(session)  # занять запуск можно только в существующей строке
        claimed = _claim_cleanup(session, now)
        if not claimed:
            return 0  # другой запуск успел раньше
        result = run_cleanup(session, now=now, actor=SYSTEM_ACTOR)
    except Exception:  # контракт функции — «не бросает»: широкий перехват здесь намеренный, ошибка не теряется, а пишется в лог
        session.rollback()
        logger.exception("Очистка журнала аудита по сроку хранения не выполнена")
        if claimed:
            _release_claim(session, now, previous)
        return 0
    return result.removed if result else 0


def run_scheduled_cleanup_in_own_session() -> int:
    """Точка входа фоновых запусков — задача после ответа `GET /audit-log` и старт сервера: своя сессия, закрывается здесь. Сессией запроса
    пользоваться нельзя: к моменту фоновой задачи она уже отдана обратно (get_db закрывает её), а удаление пакетами занимает секунды."""
    with app_db.SessionLocal() as session:
        return run_scheduled_cleanup(session)


def _describe_change(before: int, after: int, *, reset: bool) -> str:
    if before == after and not reset:
        # Значение равно действовавшему умолчанию, но в форме не задавалось — теперь задано явно и переживёт смену переменной окружения.
        return f"Срок хранения журнала аудита: {_days_text(after)} — зафиксирован в настройках (до этого действовало значение по умолчанию)"
    text = f"Срок хранения журнала аудита: {_days_text(before)} → {_days_text(after)}"
    return text + " (сброшен к значению по умолчанию)" if reset else text


def update_retention(session: Session, retention_days: Optional[int], *, now: Optional[datetime] = None) -> RetentionUpdate:
    """Сохраняет срок хранения (None — сбросить к значению по умолчанию), пишет об этом в журнал и сразу очищает по новому сроку.

    Сохранение — явное действие администратора, поэтому очистка идёт сразу, не дожидаясь суток. Значение, равное сохранённому, ничего не
    меняет: ни записи в журнале, ни очистки. last_cleanup_at сбрасывается: при новом сроке прежняя отметка ничего не значит, а если очистка
    остановилась на лимите пакетов, ленивый запуск продолжит её без ожидания суток. Ошибка очистки (БД или архива) не отменяет
    сохранённый срок."""
    now = now or utcnow_naive()
    row = get_or_create_audit_settings(session)
    if row.retention_days == retention_days:
        return RetentionUpdate(row, removed=0, cleanup_failed=False)
    before = effective_retention_days(row)
    row.retention_days = retention_days
    row.last_cleanup_at = None
    change = _describe_change(before, effective_retention_days(row), reset=retention_days is None)
    audit(session, AUDIT_ENTITY, SETTINGS_ID, AuditAction.UPDATE, change)
    session.commit()
    try:
        result = run_cleanup(session, now=now, actor=None)
    except (SQLAlchemyError, AuditArchiveError):
        session.rollback()
        logger.exception("Очистка журнала аудита после смены срока хранения не выполнена")
        return RetentionUpdate(row, removed=0, cleanup_failed=True)
    return RetentionUpdate(row, removed=result.removed if result else 0, cleanup_failed=False)
