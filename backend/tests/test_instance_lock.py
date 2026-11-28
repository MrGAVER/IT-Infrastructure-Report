"""Защита от второй копии приложения на одной базе SQLite (app/services/instance_lock.py).

Тесты идут с малыми интервалами (десятки миллисекунд), поэтому проверяют логику, а не реальные 5/20/30 секунд. «Другой компьютер»
изображается другим именем хоста; «убитая копия» — настоящий процесс, завершённый SIGKILL/terminate.

Запуск: pytest backend/tests/test_instance_lock.py -v
"""

from __future__ import annotations

import ctypes
import os
import sqlite3
import subprocess
import sys
import textwrap
import threading
import time
from contextlib import closing
from pathlib import Path

import pytest

from app.services import instance_lock
from app.services.instance_lock import (
    InstanceAlreadyRunning,
    InstanceLock,
    InstanceLockError,
    LockTiming,
    lock_path_for,
    lock_skipped_by_environment,
    process_exists,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent

FAST = LockTiming(heartbeat_interval=0.05, self_fence_after=0.2, stale_after=0.6, poll_interval=0.02, busy_timeout=2.0)


@pytest.fixture()
def lock_file(tmp_path) -> Path:
    return tmp_path / "infra_registry.db.instance-lock"


def make_lock(path: Path, host: str, pid: int, **kwargs) -> InstanceLock:
    kwargs.setdefault("timing", FAST)
    kwargs.setdefault("process_probe", lambda _pid: True)  # по умолчанию считаем чужие процессы живыми
    return InstanceLock(path, host=host, pid=pid, **kwargs)


def read_row(path: Path):
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT owner_id, heartbeat, host, pid FROM instance_lock").fetchone()


def stop_heartbeat_without_release(lock: InstanceLock) -> None:
    """Имитация аварии: пульс прекращается, строка остаётся (как после закрытого окна консоли или отключения питания)."""
    lock._stop.set()
    lock._thread.join(timeout=2)


class TestAcquireAndRelease:
    def test_free_lock_is_acquired_and_released(self, lock_file):
        lock = make_lock(lock_file, "PC-A", 100, port=8000)
        lock.acquire()
        row = read_row(lock_file)
        assert row[2:] == ("PC-A", 100)
        lock.release()
        assert read_row(lock_file) is None
        lock.release()  # идемпотентно

    def test_released_lock_can_be_taken_at_once(self, lock_file):
        with make_lock(lock_file, "PC-A", 100):
            pass
        started = time.monotonic()
        with make_lock(lock_file, "PC-B", 200):
            assert time.monotonic() - started < FAST.stale_after, "после штатного выхода ждать не нужно"

    def test_live_owner_blocks_a_second_copy_and_is_named_in_the_error(self, lock_file):
        with make_lock(lock_file, "PC-A", 100, port=8000):
            started = time.monotonic()
            with pytest.raises(InstanceAlreadyRunning) as raised:
                make_lock(lock_file, "PC-B", 200).acquire()
            assert time.monotonic() - started < FAST.stale_after, "живого владельца видно по пульсу раньше, чем истечёт срок"
        holder = raised.value.holder
        assert (holder.host, holder.pid, holder.port) == ("PC-A", 100, 8000)
        assert "PC-A" in str(raised.value) and "100" in str(raised.value) and "8000" in str(raised.value)

    def test_the_second_copy_on_the_same_computer_is_blocked_too(self, lock_file):
        with make_lock(lock_file, "PC-A", 100):
            with pytest.raises(InstanceAlreadyRunning):
                make_lock(lock_file, "pc-a", 101).acquire()  # то же имя компьютера в другом регистре, процесс 100 «жив»


class TestTakeoverOfDeadOwner:
    def test_owner_that_stopped_beating_is_replaced_after_the_stale_period(self, lock_file):
        dead = make_lock(lock_file, "PC-A", 100)
        dead.acquire()
        stop_heartbeat_without_release(dead)
        started = time.monotonic()
        with make_lock(lock_file, "PC-B", 200):
            assert time.monotonic() - started >= FAST.stale_after, "чужого владельца не отбираем раньше срока"
            assert read_row(lock_file)[2:] == ("PC-B", 200)

    def test_dead_process_on_the_same_computer_is_replaced_immediately(self, lock_file):
        dead = make_lock(lock_file, "PC-A", 100)
        dead.acquire()
        stop_heartbeat_without_release(dead)
        started = time.monotonic()
        with make_lock(lock_file, "pc-a", 101, process_probe=lambda pid: False):
            assert time.monotonic() - started < FAST.stale_after
            assert read_row(lock_file)[3] == 101

    def test_the_dead_process_shortcut_does_not_apply_to_other_computers(self, lock_file):
        """PID чужого компьютера на этом ничего не значит: «процесса нет» не повод забирать аренду."""
        owner = make_lock(lock_file, "PC-A", 100)
        owner.acquire()
        try:
            with pytest.raises(InstanceAlreadyRunning):
                make_lock(lock_file, "PC-B", 200, process_probe=lambda pid: False).acquire()
        finally:
            owner.release()

    def test_waiting_for_a_silent_owner_is_reported(self, lock_file):
        dead = make_lock(lock_file, "PC-A", 100)
        dead.acquire()
        stop_heartbeat_without_release(dead)
        messages: list[str] = []
        with make_lock(lock_file, "PC-B", 200, progress=messages.append):
            pass
        assert len(messages) == 1 and "PC-A" in messages[0]

    def test_simultaneous_starts_produce_exactly_one_owner(self, lock_file):
        results: list[str] = []
        guard = threading.Lock()
        barrier = threading.Barrier(6)

        def start(index: int) -> None:
            lock = make_lock(lock_file, f"PC-{index}", 1000 + index)
            barrier.wait()
            try:
                lock.acquire()
                outcome = "owner"
            except InstanceAlreadyRunning:
                outcome = "refused"
            with guard:
                results.append(outcome)
            if outcome == "owner":
                time.sleep(0.4)  # держим аренду, пока остальные завершат проверку
                lock.release()

        threads = [threading.Thread(target=start, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        assert sorted(results) == ["owner"] + ["refused"] * 5


class TestLossOfOwnership:
    def test_replaced_row_makes_the_owner_report_the_loss(self, lock_file):
        lost = threading.Event()
        reasons: list[str] = []
        lock = make_lock(lock_file, "PC-A", 100, on_lost=lambda reason: (reasons.append(reason), lost.set()))
        lock.acquire()
        with closing(sqlite3.connect(lock_file, isolation_level=None)) as conn:
            conn.execute("UPDATE instance_lock SET owner_id = 'someone-else'")
        assert lost.wait(timeout=3), "потеря владения замечена по очередному пульсу"
        assert lock.lost and "другая копия" in reasons[0]
        lock.release()
        assert read_row(lock_file)[0] == "someone-else", "чужую строку при выходе не удаляем"

    def test_owner_stops_itself_when_the_lock_file_becomes_unreachable(self, lock_file, monkeypatch):
        lost = threading.Event()
        lock = make_lock(lock_file, "PC-A", 100, on_lost=lambda reason: lost.set())
        lock.acquire()

        def unreachable():
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(lock, "_connect", unreachable)
        started = time.monotonic()
        assert lost.wait(timeout=3)
        elapsed = time.monotonic() - started
        assert FAST.self_fence_after - 0.1 <= elapsed < FAST.stale_after + 1, "отключение раньше, чем претендент заберёт аренду"
        assert "Нет связи" in lock.lost_reason
        monkeypatch.undo()
        lock.release()

    def test_handler_set_after_the_loss_is_called_at_once(self, lock_file):
        lock = make_lock(lock_file, "PC-A", 100)
        lock.acquire()
        with closing(sqlite3.connect(lock_file, isolation_level=None)) as conn:
            conn.execute("DELETE FROM instance_lock")
        deadline = time.monotonic() + 3
        while not lock.lost and time.monotonic() < deadline:
            time.sleep(0.02)
        assert lock.lost
        reasons: list[str] = []
        lock.set_on_lost(reasons.append)
        assert len(reasons) == 1
        lock.release()

    def test_failing_handler_does_not_kill_the_heartbeat_thread_silently(self, lock_file):
        def broken(reason: str) -> None:
            raise RuntimeError("сбой обработчика")

        lock = make_lock(lock_file, "PC-A", 100, on_lost=broken)
        lock.acquire()
        with closing(sqlite3.connect(lock_file, isolation_level=None)) as conn:
            conn.execute("DELETE FROM instance_lock")
        deadline = time.monotonic() + 3
        while not lock.lost and time.monotonic() < deadline:
            time.sleep(0.02)
        assert lock.lost
        lock.release()


class TestErrors:
    def test_missing_directory_is_a_lock_error_not_a_free_pass(self, tmp_path):
        lock = make_lock(tmp_path / "нет-такой-папки" / "x.instance-lock", "PC-A", 100)
        with pytest.raises(InstanceLockError, match="файлом блокировки"):
            lock.acquire()

    def test_corrupted_lock_file_is_a_lock_error(self, lock_file):
        lock_file.write_bytes("это не база SQLite".encode() * 100)
        with pytest.raises(InstanceLockError):
            make_lock(lock_file, "PC-A", 100).acquire()

    def test_acquiring_twice_with_one_object_is_a_programmer_error(self, lock_file):
        with make_lock(lock_file, "PC-A", 100) as lock:
            with pytest.raises(RuntimeError, match="уже взята"):
                lock.acquire()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"heartbeat_interval": 0},
            {"self_fence_after": 1.0, "heartbeat_interval": 5.0},  # меньше двух пульсов
            {"self_fence_after": 30.0, "stale_after": 30.0},  # владелец не успевает отключиться раньше замены
        ],
    )
    def test_unsafe_timing_is_rejected(self, kwargs):
        with pytest.raises(ValueError):
            LockTiming(**kwargs)

    def test_default_timing_is_safe(self):
        timing = LockTiming()
        assert timing.heartbeat_interval * 2 <= timing.self_fence_after < timing.stale_after


class TestHelpers:
    def test_lock_file_lies_next_to_the_database(self):
        assert lock_path_for(Path("/data/infra_registry.db")) == Path("/data/infra_registry.db.instance-lock")

    @pytest.mark.parametrize(
        ("value", "expected"), [("1", True), (" TRUE ", True), ("yes", True), ("0", False), ("", False), ("да", False)]
    )
    def test_skip_switch_accepts_only_explicit_values(self, monkeypatch, value, expected):
        monkeypatch.setenv(instance_lock.SKIP_LOCK_ENV, value)
        assert lock_skipped_by_environment() is expected

    def test_skip_switch_is_off_by_default(self, monkeypatch):
        monkeypatch.delenv(instance_lock.SKIP_LOCK_ENV, raising=False)
        assert lock_skipped_by_environment() is False


class TestProcessExists:
    def test_current_process_exists(self):
        assert process_exists(os.getpid()) is True

    @pytest.mark.parametrize("pid", [0, -1])
    def test_invalid_pid_does_not_exist(self, pid):
        assert process_exists(pid) is False

    def test_finished_process_does_not_exist(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait(timeout=30)
        assert process_exists(child.pid) is False

    def test_unknown_error_is_treated_as_alive(self, monkeypatch):
        def broken(pid):
            raise OSError("неизвестная ошибка")

        monkeypatch.setattr(instance_lock, "_posix_process_exists", broken)
        monkeypatch.setattr(instance_lock, "_windows_process_exists", broken)
        assert process_exists(12345) is True

    @pytest.mark.parametrize(
        ("handle", "last_error", "exit_code", "expected"),
        [
            (77, 0, 259, True),  # STILL_ACTIVE
            (77, 0, 0, False),  # процесс завершился
            (0, 5, 0, True),  # ERROR_ACCESS_DENIED: процесс есть, но чужой
            (0, 87, 0, False),  # ERROR_INVALID_PARAMETER: такого PID нет
        ],
    )
    def test_windows_branch_uses_winapi_and_never_os_kill(self, monkeypatch, handle, last_error, exit_code, expected):
        """os.kill(pid, 0) на Windows завершает процесс — ветка Windows обязана ходить только через OpenProcess."""
        calls: list[str] = []

        class FakeFunction:
            def __init__(self, name, result):
                self.name, self.result = name, result

            def __call__(self, *args):
                calls.append(self.name)
                if self.name == "GetExitCodeProcess":
                    args[1]._obj.value = exit_code
                return self.result

        class FakeKernel32:
            OpenProcess = FakeFunction("OpenProcess", handle)
            GetExitCodeProcess = FakeFunction("GetExitCodeProcess", 1)
            CloseHandle = FakeFunction("CloseHandle", 1)

        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: FakeKernel32, raising=False)
        monkeypatch.setattr(ctypes, "get_last_error", lambda: last_error, raising=False)
        monkeypatch.setattr(os, "kill", lambda *args: pytest.fail("os.kill на Windows завершил бы чужой процесс"))
        assert process_exists(4242) is expected
        assert ("CloseHandle" in calls) is bool(handle)


def test_killed_copy_in_a_real_process_is_replaced_without_waiting(lock_file):
    """Сквозной случай: настоящий процесс берёт аренду и убивается без штатного выхода (закрытое окно консоли)."""
    program = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(BACKEND_DIR)!r})
        from pathlib import Path
        from app.services.instance_lock import InstanceLock, LockTiming
        timing = LockTiming(heartbeat_interval=0.05, self_fence_after=0.2, stale_after=0.6, poll_interval=0.02, busy_timeout=2.0)
        lock = InstanceLock(Path({str(lock_file)!r}), port=8000, timing=timing)
        lock.acquire()
        print("ready", flush=True)
        time.sleep(60)
        """
    )
    child = subprocess.Popen([sys.executable, "-c", program], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        # Имя компьютера и проверка процесса настоящие: живую копию на этом компьютере видно по пульсу — отказ, а не захват.
        with pytest.raises(InstanceAlreadyRunning) as raised:
            InstanceLock(lock_file, timing=FAST).acquire()
        assert raised.value.holder.pid == child.pid
        child.kill()
        child.wait(timeout=30)
        started = time.monotonic()
        with InstanceLock(lock_file, timing=FAST) as lock:
            assert time.monotonic() - started < FAST.stale_after, "упавшую копию на этом компьютере заменяют сразу, не дожидаясь срока"
            assert not lock.lost
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=30)
        child.stdout.close()
