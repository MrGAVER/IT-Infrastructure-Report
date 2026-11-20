"""Кэш рассчитанного плана согласования для постраничного показа (services/port_sync_reconcile.py).

Зачем. План согласования считается целиком (подключения → порты → решения правил), а в окне плана его
элементы показываются страницами. Без кэша каждая следующая страница пересчитывала бы весь план заново —
при тысячах подключений это секунды на каждое «Показать ещё». Поэтому первая страница считает план и кладёт
его элементы в кэш, а следующие страницы того же плана (тот же `plan_hash`) берутся срезом из кэша без
запросов к БД.

Ключ — область плана (`scope_key`: список подключений и правило) вместе с `plan_hash`: один и тот же хеш у
планов разных областей (например, пустой план) не смешивается.

Что кэш НЕ делает:
  * применение плана его не использует — `apply` всегда считает план заново и сверяет `plan_hash`, поэтому
    устаревший снимок в кэше не может привести к записи не того, что видел пользователь;
  * не хранит ничего, кроме готовых словарей элементов и сводки (ни ORM-объектов, ни сессий);
  * не общий между процессами: у каждого воркера свой кэш, промах в другом воркере — просто пересчёт.

Устаревание. Снимок живёт `ttl_seconds` с момента расчёта и вытесняется по давности использования, если планов
больше `max_entries`; сбрасывается целиком после применения плана и после любой правки правил
(`clear`). Правки самих портов и подключений кэш не отслеживает — их ограничивает TTL.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

DEFAULT_TTL_SECONDS = 300.0
DEFAULT_MAX_ENTRIES = 4


@dataclass(frozen=True)
class CachedPlan:
    """Снимок плана: ВСЕ элементы к показу в порядке показа и сводка по всему плану."""

    items: tuple[dict[str, Any], ...]
    summary: dict[str, int]


def scope_key(connection_ids: Any, rule_id: str | None) -> str:
    """Стабильный ключ области плана: те же подключения (в том же порядке — от него зависит порядок
    элементов) и то же правило дают тот же ключ."""
    raw = json.dumps([connection_ids, rule_id], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PlanCache:
    """Потокобезопасный кэш планов с TTL и вытеснением по давности (LRU).

    clock подменяется в тестах, чтобы не ждать реальное время:
        cache = PlanCache(ttl_seconds=10, clock=fake_clock)
        cache.put(scope_key(None, None), "hash", CachedPlan(items=(), summary={}))
        cache.get(scope_key(None, None), "hash")   # CachedPlan или None (нет / истёк / вытеснен)
    """

    def __init__(self, *, ttl_seconds: float = DEFAULT_TTL_SECONDS, max_entries: int = DEFAULT_MAX_ENTRIES, clock: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("ttl_seconds и max_entries должны быть положительными")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[tuple[str, str], tuple[float, CachedPlan]] = OrderedDict()

    def get(self, scope: str, plan_hash: str) -> CachedPlan | None:
        key = (scope, plan_hash)
        with self._lock:
            self._drop_expired()
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return entry[1]

    def put(self, scope: str, plan_hash: str, plan: CachedPlan) -> None:
        key = (scope, plan_hash)
        with self._lock:
            self._drop_expired()
            self._entries[key] = (self._clock() + self._ttl, plan)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._entries)

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, (expires, _) in self._entries.items() if expires <= now]:
            del self._entries[key]


# Один кэш на процесс — им пользуются предпросмотр, применение (сброс) и правка правил (сброс).
plan_cache = PlanCache()
