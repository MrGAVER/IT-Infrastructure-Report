"""Защита от отката системных часов (чтобы «продлить» временный ключ, переведя дату назад).

Хранится «верхняя отметка времени» (high-water mark, HWM) — наибольшее когда-либо наблюдавшееся время. Приложение
считает «сейчас» равным ``max(часы, HWM)``: время не может идти назад, поэтому срок временного ключа истекает в
срок, даже если часы откатили. Законный пользователь ничего не замечает; о расхождении (часы отстают от HWM
больше чем на ``tolerance``) сообщается флагом ``rolled_back`` — его показывает статус лицензии.

Честные границы: состояние лежит на диске клиента вместе с приложением. Подпись состояния (HMAC) защищает от
правки файла текстовым редактором, но не от того, кто прочёл код; удаление файла сбрасывает отметку.
Это барьер против случайных и неквалифицированных обходов, а не гарантия (см. docs/licensing.md).
Восстановление после ошибочного перевода часов ВПЕРЁД — удалить файл состояния (license_state.json).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from .fsutil import write_text_atomic

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE_SECONDS = 3_600
DEFAULT_FLUSH_INTERVAL_SECONDS = 600


@dataclass(frozen=True)
class ClockObservation:
    effective_now: int
    rolled_back: bool


def derive_secret(machine_id: str | None) -> bytes:
    return hashlib.sha256(b"ris-clock-v1:" + (machine_id or "").encode("utf-8")).digest()


class ClockGuard:
    def __init__(
        self,
        path: Path | None,
        secret: bytes,
        *,
        tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
        flush_interval_seconds: int = DEFAULT_FLUSH_INTERVAL_SECONDS,
    ) -> None:
        self._path = path
        self._secret = secret
        self._tolerance = tolerance_seconds
        self._flush_interval = flush_interval_seconds
        self._lock = threading.Lock()
        self._hwm = 0
        self._persisted: int | None = None   # последнее записанное значение; None — ещё не записывали
        self._loaded = False
        self._write_warned = False

    def observe(self, wall_now: int) -> ClockObservation:
        with self._lock:
            if not self._loaded:
                self._hwm = self._load()
                self._persisted = self._hwm
                self._loaded = True
            rolled_back = wall_now + self._tolerance < self._hwm
            if wall_now > self._hwm:
                self._hwm = wall_now
                self._flush_if_due(force=False)
            return ClockObservation(effective_now=max(wall_now, self._hwm), rolled_back=rolled_back)

    def flush(self) -> None:
        """Принудительно сохранить отметку (вызывается при остановке приложения)."""
        with self._lock:
            if self._loaded:
                self._flush_if_due(force=True)

    def _mac(self, hwm: int) -> str:
        return hmac.new(self._secret, f"hwm:{hwm}".encode("ascii"), hashlib.sha256).hexdigest()

    def _load(self) -> int:
        if self._path is None:
            return 0
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            hwm = int(data["hwm"])
            if not hmac.compare_digest(str(data["mac"]), self._mac(hwm)):
                logger.warning("Файл состояния лицензии %s изменён вручную — игнорируется.", self._path)
                return 0
            return max(hwm, 0)
        except FileNotFoundError:
            return 0
        except (OSError, ValueError, KeyError, TypeError):
            logger.warning("Файл состояния лицензии %s повреждён — игнорируется.", self._path)
            return 0

    def _flush_if_due(self, *, force: bool) -> None:
        if self._path is None:
            return
        if not force and self._persisted is not None and self._hwm - self._persisted < self._flush_interval:
            return
        if self._persisted == self._hwm:
            return
        try:
            write_text_atomic(self._path, json.dumps({"hwm": self._hwm, "mac": self._mac(self._hwm)}))
            self._persisted = self._hwm
        except OSError as exc:
            if not self._write_warned:    # одно предупреждение, а не по записи на каждый запрос
                self._write_warned = True
                logger.warning("Не удалось сохранить состояние лицензии %s: %s. Защита от отката часов работает только до перезапуска.", self._path, exc)
