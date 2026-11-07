"""Троттлинг попыток входа по паре «адрес клиента + логин» с экспоненциальной задержкой.

Зачем. Блокировка учётной записи после серии неудачных паролей (services/auth/lockout.py) защищает от
подбора, но сама становится оружием: любой, кто достаёт до /api/v1/auth/login, может держать
учётную запись администратора заблокированной, посылая неверные пароли. Троттлинг по паре
(IP, логин) гасит такой перебор на стороне нападающего: после нескольких неудач каждая следующая
попытка с того же адреса ждёт вдвое дольше, не затрагивая тот же логин с других адресов, в том числе
настоящего владельца. Блокировка аккаунта остаётся запасным рубежом против распределённого подбора.

Ключ (IP, логин) сам по себе обходится сменой логина: у каждой выдуманной пары своя «первая» попытка, и задержка не
наступает никогда. Поэтому services/auth/login.py держит второй экземпляр с ключом (IP, None) — счётчик на адрес целиком, с
более высоким порогом бесплатных попыток; запрос блокируется, если задержка назначена любому из двух ключей.

Состояние — в памяти процесса. При нескольких процессах backend счётчики независимы (каждый
процесс считает свои попытки), то есть реальный предел — число процессов × свой лимит; для
серверного развёртывания этого достаточно как первого рубежа, а общий для процессов счётчик
потребовал бы внешнего хранилища. Память ограничена: устаревшие записи вытесняются, а при
переполнении удаляются самые старые.

Пример:
    throttle = LoginThrottle()
    key = (client_ip, login.casefold())
    wait = throttle.retry_after(key)      # секунды до следующей разрешённой попытки, 0 — можно
    ...
    throttle.record_failure(key)          # после неверного пароля
    throttle.reset(key)                   # после успешного входа
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Hashable


@dataclass
class _Entry:
    failures: int
    last_failure: float
    blocked_until: float


class LoginThrottle:
    def __init__(
        self,
        *,
        free_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 900.0,
        window: float = 900.0,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if free_attempts < 0 or base_delay <= 0 or max_delay < base_delay or window <= 0 or max_keys < 1:
            raise ValueError("Недопустимые параметры троттлинга входа")
        self.free_attempts = free_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.window = window
        self.max_keys = max_keys
        self._clock = clock
        self._entries: dict[Hashable, _Entry] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: Hashable) -> float:
        """Сколько секунд осталось ждать до следующей попытки (0 — можно пробовать сейчас)."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return 0.0
            return max(0.0, entry.blocked_until - self._clock())

    def record_failure(self, key: Hashable) -> float:
        """Учитывает неудачную попытку и возвращает назначенную задержку (0 — пока попытки бесплатны)."""
        with self._lock:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is None or now - entry.last_failure > self.window:
                entry = _Entry(failures=0, last_failure=now, blocked_until=0.0)
            entry.failures += 1
            entry.last_failure = now
            delay = 0.0
            if entry.failures > self.free_attempts:
                exponent = entry.failures - self.free_attempts - 1
                # min по показателю степени — чтобы 2**exponent не разрастался до огромных чисел
                delay = min(self.base_delay * (2 ** min(exponent, 30)), self.max_delay)
            entry.blocked_until = now + delay
            self._entries[key] = entry
            if len(self._entries) > self.max_keys:
                self._evict(now)
            return delay

    def reset(self, key: Hashable) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _evict(self, now: float) -> None:
        """Сначала убираем записи, у которых окно давно истекло, затем — самые старые, пока не влезем."""
        for stale_key in [k for k, e in self._entries.items() if now - e.last_failure > self.window]:
            del self._entries[stale_key]
        overflow = len(self._entries) - self.max_keys
        if overflow > 0:
            for oldest_key in sorted(self._entries, key=lambda k: self._entries[k].last_failure)[:overflow]:
                del self._entries[oldest_key]
