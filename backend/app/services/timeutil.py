"""Единое представление времени: в БД — naive UTC, в API — ISO 8601 с явным смещением «+00:00».

Раньше два представления жили вместе. TimestampMixin клал в колонки DateTime (без timezone) aware-значения
`datetime.now(timezone.utc)`, а код аутентификации — naive UTC. SQLite/SQLAlchemy при чтении возвращают naive, поэтому запись,
созданная или изменённая в текущем запросе (`expire_on_commit=False`), отдавалась как `2026-10-19T18:09:18.219136+00:00`, а та же
запись при следующем чтении — как `2026-10-19T18:08:54.336386`, без смещения. Браузер трактует строку без смещения как
ЛОКАЛЬНОЕ время, и журнал аудита, «последний вход» и сессии показывались со сдвигом на часовой пояс пользователя
(для UTC+3 — на три часа раньше реального).

Правило теперь одно:
  • значения, которые мы пишем в БД, — `utcnow_naive()` (naive UTC; в PostgreSQL колонки `timestamp without time zone`,
    aware-значение было бы приведено по часовому поясу сессии БД, а не UTC);
  • значения, которые мы отдаём клиенту, — `iso_utc()`: naive считается UTC и получает «+00:00», aware приводится к UTC;
  • даты без времени (`date`, `YYYY-MM-DD`) не меняются.

Модуль не импортирует ничего из приложения: его используют и модели (`models.py`), и сервисы."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any


def utcnow_naive() -> datetime:
    """Текущее время UTC без tzinfo — значение по умолчанию для колонок DateTime и «сейчас» в сервисах."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime) -> datetime:
    """aware → UTC без tzinfo, naive возвращается как есть (в БД naive всегда означает UTC)."""
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def iso_utc(value: Any) -> Any:
    """Значение для JSON-ответа. datetime → ISO 8601 с «+00:00»; date → `YYYY-MM-DD`; всё остальное (в том числе None)
    возвращается без изменений — функцию можно применять ко всем колонкам подряд (services/serialization.serialize)."""
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value
