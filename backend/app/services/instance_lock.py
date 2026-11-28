"""Защита от второй (и следующих) копий приложения на одной базе SQLite — на этом и на других компьютерах.

Зачем. SQLite блокирует файл лишь на время самой записи, а часть состояния приложения живёт в памяти процесса (см. README, «Известные
ограничения»). Две копии на одной базе гонятся за порты и миграции: вторая копия при старте делает резервную копию и выполняет
``alembic upgrade head`` на базе, которую первая уже использует. Поэтому проверка выполняется ДО миграций (``launcher.main``).

Как устроено. Рядом с файлом базы лежит маленькая служебная база SQLite (``<имя базы>.instance-lock``) с единственной строкой —
«арендой» (lease) владельца:

* **Захват.** ``BEGIN IMMEDIATE`` (SQLite сериализует писателей, в том числе по сетевой папке): строки нет — вставляем свою и работаем.
* **Пульс.** Владелец раз в ``heartbeat_interval`` секунд увеличивает счётчик ``heartbeat`` в своей строке.
* **Вторая копия.** Видит чужую строку и наблюдает за счётчиком. Изменился — владелец жив, запуск отказан (обычно за несколько секунд).
  Не менялся ``stale_after`` секунд — владелец упал, строка забирается (compare-and-swap по ``owner_id`` и ``heartbeat``: из двух
  одновременных претендентов побеждает один). Если владелец — процесс на этом же компьютере и его уже нет, строка забирается сразу.
* **Выход.** Штатное завершение удаляет строку; после аварии (закрытое окно консоли, выключение питания) строку освободит
  следующий запуск.
* **Самоотключение.** Если пульс не удаётся записать дольше ``self_fence_after`` секунд (пропала сетевая папка) или строка уже чужая,
  владелец вызывает ``on_lost`` и обязан остановить сервер: претендент заберёт аренду не раньше ``stale_after`` > ``self_fence_after``.

Часы разных компьютеров не сравниваются: каждый участник измеряет только длительности по своим монотонным часам, поэтому разница
во времени между компьютерами не влияет. Время старта в строке нужно только для сообщения человеку.

Ограничения (осознанные):

* Имена компьютеров в сети должны быть уникальны: «тот же компьютер» определяется по имени (``socket.gethostname()``).
* Защита действует для запуска через ``launcher.py``/EXE. Запуск ``uvicorn app.main:app`` напрямую её обходит.
* Приостановка процесса (сон ноутбука) дольше ``stale_after`` даёт окно до одного ``heartbeat_interval`` после пробуждения, пока
  старый владелец ещё не заметил потерю аренды: запись в базу по-прежнему защищена только самим SQLite.
* Надёжность не выше надёжности блокировок файлов у сетевой папки (SMB/NFS), как и у самой базы SQLite.
"""

from __future__ import annotations

import enum
import getpass
import logging
import os
import socket
import sqlite3
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .timeutil import utcnow_naive

logger = logging.getLogger(__name__)

SKIP_LOCK_ENV = "INFRA_REGISTRY_ALLOW_MULTIPLE_INSTANCES"
_SKIP_VALUES = {"1", "true", "yes"}
LOCK_SUFFIX = ".instance-lock"

_MAX_CLAIM_ATTEMPTS = 3
_SCHEMA = """
CREATE TABLE IF NOT EXISTS instance_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    owner_id TEXT NOT NULL,
    heartbeat INTEGER NOT NULL,
    host TEXT NOT NULL,
    pid INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    port INTEGER
)
"""
_COLUMNS = "owner_id, heartbeat, host, pid, user_name, started_at, port"


def lock_skipped_by_environment() -> bool:
    """Оператор осознанно отключил проверку (INFRA_REGISTRY_ALLOW_MULTIPLE_INSTANCES = 1/true/yes без учёта регистра)."""
    return os.getenv(SKIP_LOCK_ENV, "").strip().lower() in _SKIP_VALUES


def lock_path_for(db_path: Path) -> Path:
    """Файл аренды лежит рядом с базой: тот, кто видит базу, видит и его (общая папка — общая блокировка)."""
    return db_path.with_name(db_path.name + LOCK_SUFFIX)


@dataclass(frozen=True)
class LockTiming:
    """Временные параметры (секунды). Условие безопасности: владелец отключается раньше, чем претендент решит, что владельца нет."""

    heartbeat_interval: float = 5.0
    self_fence_after: float = 20.0
    stale_after: float = 30.0
    poll_interval: float = 1.0
    busy_timeout: float = 5.0

    def __post_init__(self) -> None:
        values = (self.heartbeat_interval, self.self_fence_after, self.stale_after, self.poll_interval, self.busy_timeout)
        if min(values) <= 0:
            raise ValueError("все интервалы блокировки должны быть положительными")
        if self.self_fence_after < 2 * self.heartbeat_interval:
            raise ValueError("self_fence_after должен быть не меньше двух интервалов пульса, иначе один сбой остановит приложение")
        if self.stale_after <= self.self_fence_after:
            raise ValueError("stale_after должен быть больше self_fence_after: владелец обязан отключиться раньше, чем его заменят")


@dataclass(frozen=True)
class LockHolder:
    """Кто сейчас держит аренду (поля совпадают с колонками таблицы по порядку)."""

    owner_id: str
    heartbeat: int
    host: str
    pid: int
    user: str
    started_at: str
    port: int | None

    def describe(self) -> str:
        port = f", порт {self.port}" if self.port else ""
        return f"компьютер «{self.host}», пользователь «{self.user}», процесс {self.pid}{port}, запущено {self.started_at} UTC"


class InstanceAlreadyRunning(RuntimeError):
    """База уже используется другой работающей копией приложения."""

    def __init__(self, holder: LockHolder, lock_path: Path) -> None:
        self.holder = holder
        self.lock_path = lock_path
        super().__init__(f"Эта база данных уже используется другой копией приложения: {holder.describe()}.")


class InstanceLockError(RuntimeError):
    """Файл аренды недоступен или повреждён: определить, запущена ли другая копия, нельзя (запуск отказан, а не разрешён)."""


class _Beat(enum.Enum):
    OK = "ok"
    LOST = "lost"
    FAILED = "failed"


def _posix_process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # сигнал 0 ничего не отправляет, только проверяет существование
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # процесс есть, но чужой
    return True


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


def _windows_process_exists(pid: int) -> bool:
    """Через OpenProcess/GetExitCodeProcess. ``os.kill(pid, 0)`` на Windows ЗАВЕРШАЕТ процесс (TerminateProcess), его здесь нельзя."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED  # «нет доступа» — процесс есть; «неверный параметр» — нет
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_exists(pid: int) -> bool:
    """Есть ли на этом компьютере живой процесс с таким PID. Сомнение трактуется как «есть»: ошибка ведёт к отказу запуска, не к захвату."""
    if pid <= 0:
        return False
    try:
        return _windows_process_exists(pid) if sys.platform == "win32" else _posix_process_exists(pid)
    except (OSError, AttributeError, ValueError) as exc:
        logger.debug("Не удалось проверить процесс %s: %s", pid, exc)
        return True


def _current_user() -> str:
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return "?"


class InstanceLock:
    """Аренда базы одним экземпляром приложения. Использование: ``with InstanceLock(path, port=8000) as lock: ...``

    ``on_lost(причина)`` вызывается из потока пульса, когда владение потеряно, — обработчик должен остановить запись в базу.
    Параметры ``host``, ``pid`` и ``process_probe`` нужны тестам; в приложении берутся значения текущего процесса.
    """

    def __init__(
        self,
        lock_path: Path,
        *,
        port: int | None = None,
        timing: LockTiming | None = None,
        on_lost: Callable[[str], None] | None = None,
        progress: Callable[[str], None] | None = None,
        host: str | None = None,
        pid: int | None = None,
        process_probe: Callable[[int], bool] = process_exists,
    ) -> None:
        self._path = Path(lock_path)
        self._port = port
        self._timing = timing or LockTiming()
        self._on_lost = on_lost
        self._progress = progress
        self._host = host or socket.gethostname()
        self._pid = os.getpid() if pid is None else pid
        self._process_probe = process_probe
        self._owner_id = uuid.uuid4().hex
        self._user = _current_user()
        self._started_at = utcnow_naive().strftime("%Y-%m-%d %H:%M:%S")
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._lost_reason: str | None = None
        self._acquired = False
        self._last_ok = 0.0
        self._thread: threading.Thread | None = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def lost(self) -> bool:
        return self._lost_reason is not None

    @property
    def lost_reason(self) -> str | None:
        return self._lost_reason

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()

    def set_on_lost(self, callback: Callable[[str], None]) -> None:
        """Назначает обработчик потери владения. Если владение уже потеряно (пока сервер ещё запускался) — вызывает его сразу."""
        with self._state_lock:
            self._on_lost = callback
            reason = self._lost_reason
        if reason is not None:
            callback(reason)

    def acquire(self) -> None:
        """Берёт аренду или бросает ``InstanceAlreadyRunning`` (база занята живой копией) либо
        ``InstanceLockError`` (файл аренды неисправен)."""
        if self._acquired:
            raise RuntimeError("аренда уже взята этим объектом")
        try:
            with closing(self._connect()) as conn:
                conn.execute(_SCHEMA)
                self._claim(conn)
        except sqlite3.Error as exc:
            raise InstanceLockError(f"Не удалось работать с файлом блокировки {self._path}: {exc}") from exc
        self._acquired = True
        self._last_ok = time.monotonic()
        self._thread = threading.Thread(target=self._heartbeat_loop, name="instance-lock-heartbeat", daemon=True)
        self._thread.start()

    def release(self) -> None:
        """Штатное освобождение. Идемпотентно и не бросает исключений: сбой удаления только записывается в журнал."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self._timing.busy_timeout + 1)
        if not self._acquired:
            return
        self._acquired = False
        if self.lost:
            return  # строка уже чужая
        try:
            with closing(self._connect()) as conn:
                conn.execute("DELETE FROM instance_lock WHERE id = 1 AND owner_id = ?", (self._owner_id,))
        except sqlite3.Error as exc:
            logger.warning(
                "Не удалось освободить блокировку %s: %s. Следующий запуск освободит её сам (не позже чем через %s с).",
                self._path,
                exc,
                self._timing.stale_after,
            )

    # --- захват -------------------------------------------------------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # Режим журнала по умолчанию (DELETE): WAL по сетевой папке не работает. Транзакции — вручную (isolation_level=None).
        return sqlite3.connect(str(self._path), timeout=self._timing.busy_timeout, isolation_level=None)

    @staticmethod
    @contextmanager
    def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    def _identity(self) -> tuple[str, str, int, str, str, int | None]:
        return (self._owner_id, self._host, self._pid, self._user, self._started_at, self._port)

    @staticmethod
    def _read(conn: sqlite3.Connection) -> LockHolder | None:
        row = conn.execute(f"SELECT {_COLUMNS} FROM instance_lock WHERE id = 1").fetchone()
        return LockHolder(*row) if row else None

    def _claim(self, conn: sqlite3.Connection) -> None:
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            holder = self._claim_if_free(conn)
            if holder is None:
                return
            if not self._holder_is_gone(conn, holder):
                raise InstanceAlreadyRunning(self._read(conn) or holder, self._path)
            if self._take_over(conn, holder):
                return
        raise InstanceLockError(f"Не удалось захватить блокировку {self._path}: запись о владельце постоянно меняется. Повторите запуск.")

    def _claim_if_free(self, conn: sqlite3.Connection) -> LockHolder | None:
        """None — аренда свободна и теперь наша; иначе — текущий владелец."""
        with self._transaction(conn):
            holder = self._read(conn)
            if holder is None:
                conn.execute(
                    "INSERT INTO instance_lock (id, owner_id, heartbeat, host, pid, user_name, started_at, port) "
                    "VALUES (1, ?, 0, ?, ?, ?, ?, ?)",
                    self._identity(),
                )
            return holder

    def _holder_is_gone(self, conn: sqlite3.Connection, holder: LockHolder) -> bool:
        """True — владельца нет: процесс на этом компьютере завершён, либо счётчик не менялся ``stale_after`` с,
        либо строку уже освободили."""
        if holder.host.casefold() == self._host.casefold() and not self._process_probe(holder.pid):
            return True
        if self._progress is not None:
            self._progress(f"База занята другой копией ({holder.describe()}). Проверяю, работает ли она…")
        deadline = time.monotonic() + self._timing.stale_after
        while time.monotonic() < deadline:
            time.sleep(self._timing.poll_interval)
            current = self._read(conn)
            if current is None:
                return True
            if (current.owner_id, current.heartbeat) != (holder.owner_id, holder.heartbeat):
                return False
        return True

    def _take_over(self, conn: sqlite3.Connection, holder: LockHolder) -> bool:
        """Compare-and-swap: заменяем строку, только если её никто не менял с момента наблюдения."""
        with self._transaction(conn):
            cursor = conn.execute(
                "UPDATE instance_lock SET owner_id = ?, heartbeat = 0, host = ?, pid = ?, user_name = ?, started_at = ?, port = ? "
                "WHERE id = 1 AND owner_id = ? AND heartbeat = ?",
                (*self._identity(), holder.owner_id, holder.heartbeat),
            )
            return cursor.rowcount == 1

    # --- пульс --------------------------------------------------------------------------------------------------------------------

    def _beat(self) -> _Beat:
        try:
            with closing(self._connect()) as conn:
                cursor = conn.execute("UPDATE instance_lock SET heartbeat = heartbeat + 1 WHERE id = 1 AND owner_id = ?", (self._owner_id,))
                owned = cursor.rowcount == 1
        except sqlite3.Error as exc:
            logger.warning("Не удалось обновить блокировку %s: %s", self._path, exc)
            return _Beat.FAILED
        return _Beat.OK if owned else _Beat.LOST

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._timing.heartbeat_interval):
            outcome = self._beat()
            if outcome is _Beat.OK:
                self._last_ok = time.monotonic()
            elif outcome is _Beat.LOST:
                self._declare_lost("Запись о владельце базы в файле блокировки заменена или удалена: базу заняла другая копия приложения.")
                return
            elif time.monotonic() - self._last_ok >= self._timing.self_fence_after:
                self._declare_lost(
                    f"Нет связи с файлом блокировки {self._path} дольше {self._timing.self_fence_after:g} с: "
                    "другая копия могла занять базу."
                )
                return

    def _declare_lost(self, reason: str) -> None:
        with self._state_lock:
            if self._stop.is_set():
                return  # идёт штатное завершение
            self._lost_reason = reason
            callback = self._on_lost
        logger.critical(reason)
        if callback is not None:
            try:
                callback(reason)
            except Exception:  # граница потока: сбой обработчика не должен скрыть причину и убить поток молча
                logger.exception("Обработчик потери блокировки завершился ошибкой")
