"""Менеджер лицензии: где лежит ключ, кэш результата проверки, активация нового ключа.

Ключ ищется в файле (``license.key`` в каталоге данных) и, если файла нет, в переменной окружения
``INFRA_REGISTRY_LICENSE_KEY`` (удобно для Docker secrets). Файл приоритетнее: именно туда пишет активация,
и свежеустановленный ключ не должен перекрываться забытым значением в окружении.

Проверка (подпись, привязки, срок) выполняется не на каждый запрос, а не реже раза в ``recheck_seconds``:
подпись Ed25519 стоит доли миллисекунды, но сбор адресов хоста — сокеты, а переход «срок истёк» должен
подхватываться без перезапуска долгоживущего процесса.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .clock_guard import ClockGuard, ClockObservation
from .codec import normalize_token
from .context import ContextProvider, HostContext, collect_host_context
from .fsutil import write_text_atomic
from .keys import KeyRing
from .models import PRODUCT_ID, LicenseReport, LicenseState
from .validator import evaluate_token

logger = logging.getLogger(__name__)

DEFAULT_RECHECK_SECONDS = 30
_ENFORCEMENT_SETTINGS = ("auto", "on", "off")


class LicenseActivationError(Exception):
    """Ключ отвергнут при активации; ``report`` объясняет почему. Установленный ранее ключ при этом не тронут."""

    def __init__(self, report: LicenseReport) -> None:
        super().__init__(report.reason or report.state.value)
        self.report = report


class LicenseStorageError(Exception):
    """Ключ верный, но сохранить его на диск не удалось (нет прав, диск только для чтения)."""


def resolve_enforcement(setting: str, *, has_keys: bool, frozen: bool) -> bool:
    """Включено ли принуждение.

    * ``auto`` (по умолчанию) — включено, если в сборку встроен хотя бы один публичный ключ;
    * ``on`` — включено всегда (без ключей в сборке любой ключ будет отвергнут);
    * ``off`` — выключено, но ТОЛЬКО вне собранного EXE: в EXE переменная окружения обход не даёт.
      Docker-образ и запуск из исходников содержат исходный код, где проверку отключить можно и без переменной,
      поэтому для них лицензия — договорная защита, а не техническая (см. docs/licensing.md).
    """
    mode = (setting or "auto").strip().lower()
    if mode not in _ENFORCEMENT_SETTINGS:
        raise ValueError(f"INFRA_REGISTRY_LICENSE_ENFORCEMENT должен быть одним из {_ENFORCEMENT_SETTINGS}, получено {setting!r}")
    if mode == "on":
        return True
    if mode == "off" and not frozen:
        return False
    return has_keys


class LicenseManager:
    def __init__(
        self,
        *,
        ring: KeyRing,
        key_file: Path,
        env_token: str = "",
        enforcement: bool = True,
        context_provider: ContextProvider = collect_host_context,
        clock_guard: ClockGuard | None = None,
        recheck_seconds: float = DEFAULT_RECHECK_SECONDS,
        time_source: Callable[[], float] = time.time,
        product: str = PRODUCT_ID,
    ) -> None:
        self._ring = ring
        self._key_file = key_file
        self._env_token = env_token
        self._enforcement = enforcement
        self._context_provider = context_provider
        self._guard = clock_guard
        self._recheck = recheck_seconds
        self._time = time_source
        self._product = product
        self._lock = threading.RLock()
        self._cached: LicenseReport | None = None
        self._cached_at = 0.0

    @property
    def enforcement(self) -> bool:
        return self._enforcement

    def report(self) -> LicenseReport:
        """Текущее состояние лицензии (с кэшем). Не бросает исключений: сбой чтения = состояние MISSING/INVALID."""
        if not self._enforcement:
            return LicenseReport(LicenseState.DISABLED, reason="enforcement_off", now=int(self._time()))
        with self._lock:
            tick = time.monotonic()
            if self._cached is not None and 0 <= tick - self._cached_at < self._recheck:
                return self._cached
            self._cached = self._evaluate_stored()
            self._cached_at = tick
            return self._cached

    def host(self) -> HostContext:
        return self._context_provider()

    def public_status(self) -> dict[str, Any]:
        """Состояние для GET /api/v1/license: без самого ключа и подписи; привязки показываются, имена параметров — без значений."""
        data = self.report().to_public_dict()
        data["enforcement"] = self._enforcement
        data["host"] = self.host().describe()
        return data

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None

    def flush(self) -> None:
        if self._guard is not None:
            self._guard.flush()

    def activate(self, token_text: str) -> LicenseReport:
        """Проверить ключ полностью (подпись, привязки к ЭТОМУ хосту, срок) и только потом сохранить.
        Недействительный ключ не затирает рабочий: LicenseActivationError, файл не меняется."""
        if not self._ring:
            raise LicenseActivationError(LicenseReport(LicenseState.INVALID, reason="no_public_keys", now=int(self._time())))
        token = normalize_token(token_text)
        with self._lock:
            report = self._evaluate(token)
            if report.state not in (LicenseState.VALID, LicenseState.GRACE):
                logger.warning("Отклонена активация ключа: состояние %s, причина %s", report.state.value, report.reason or report.mismatched)
                raise LicenseActivationError(report)
            try:
                write_text_atomic(self._key_file, token + "\n", private=True)
            except OSError as exc:
                raise LicenseStorageError(str(exc)) from exc
            self._cached = None
        logger.info("Лицензия активирована: %s, %s", report.payload.licensee if report.payload else "?", report.state.value)
        return self.report()

    def _read_token(self) -> str | None:
        try:
            text = self._key_file.read_text(encoding="utf-8").strip()
            if text:
                return text
        except FileNotFoundError:
            pass
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Не удалось прочитать файл лицензии %s: %s", self._key_file, exc)
        return self._env_token.strip() or None

    def _observe_clock(self) -> ClockObservation:
        wall = int(self._time())
        return self._guard.observe(wall) if self._guard is not None else ClockObservation(wall, False)

    def _evaluate(self, token: str) -> LicenseReport:
        clock = self._observe_clock()
        report = evaluate_token(token, ring=self._ring, host=self._context_provider(), now=clock.effective_now, product=self._product)
        return _with_rollback_flag(report, clock.rolled_back)

    def _evaluate_stored(self) -> LicenseReport:
        token = self._read_token()
        if token is None:
            return LicenseReport(LicenseState.MISSING, reason="no_key", now=self._observe_clock().effective_now)
        return self._evaluate(token)


def _with_rollback_flag(report: LicenseReport, rolled_back: bool) -> LicenseReport:
    if not rolled_back:
        return report
    return LicenseReport(report.state, report.reason, report.payload, report.mismatched, report.now, clock_rollback=True)
