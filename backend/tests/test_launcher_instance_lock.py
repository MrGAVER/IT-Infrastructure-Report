"""Вторая копия приложения на той же базе SQLite: поведение launcher.py (запуск EXE).

Сама логика аренды проверена в test_instance_lock.py; здесь — что launcher берёт её ДО миграций, отказывает вторую копию понятным
текстом (код 2, без трассировки), останавливает сервер при потере аренды и не ломается при отключённой проверке.

Запуск: pytest backend/tests/test_launcher_instance_lock.py -v
"""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from app.services.instance_lock import SKIP_LOCK_ENV, InstanceLock, LockTiming, lock_path_for

REPO_ROOT = Path(__file__).resolve().parents[2]
FAST = LockTiming(heartbeat_interval=0.05, self_fence_after=0.2, stale_after=0.6, poll_interval=0.02, busy_timeout=2.0)


@pytest.fixture()
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    sys.modules.pop("launcher", None)
    module = importlib.import_module("launcher")
    yield module
    sys.modules.pop("launcher", None)


@pytest.fixture()
def db_path(tmp_path) -> Path:
    return tmp_path / "infra_registry.db"


def foreign_owner(db_path: Path) -> InstanceLock:
    """Копия «на другом компьютере», уже работающая с этой базой."""
    lock = InstanceLock(lock_path_for(db_path), port=8000, timing=FAST, host="OTHER-PC", pid=4321)
    lock.acquire()
    return lock


class TestAcquireInstanceLock:
    def test_free_database_gives_a_lock_that_is_released_on_exit(self, launcher, db_path, monkeypatch):
        monkeypatch.delenv(SKIP_LOCK_ENV, raising=False)
        lock = launcher.acquire_instance_lock(db_path, 8000)
        assert lock is not None and lock_path_for(db_path).exists()
        lock.release()
        with InstanceLock(lock_path_for(db_path), timing=FAST):
            pass  # после освобождения база снова доступна без ожидания

    def test_busy_database_is_a_clear_exit_naming_the_other_copy(self, launcher, db_path, monkeypatch, capsys):
        monkeypatch.delenv(SKIP_LOCK_ENV, raising=False)
        owner = foreign_owner(db_path)
        try:
            with pytest.raises(SystemExit) as exit_info:
                launcher.acquire_instance_lock(db_path, 8001)
        finally:
            owner.release()
        assert exit_info.value.code == 2
        error = capsys.readouterr().err
        assert "OTHER-PC" in error and "4321" in error and "только одна копия" in error and "Traceback" not in error

    def test_unusable_lock_file_refuses_to_start_and_names_the_way_out(self, launcher, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv(SKIP_LOCK_ENV, raising=False)
        with pytest.raises(SystemExit) as exit_info:
            launcher.acquire_instance_lock(tmp_path / "нет-такой-папки" / "infra_registry.db", 8000)
        assert exit_info.value.code == 2
        error = capsys.readouterr().err
        assert "файлом блокировки" in error and SKIP_LOCK_ENV in error and "Traceback" not in error

    def test_the_switch_disables_the_check_loudly(self, launcher, db_path, monkeypatch, capsys):
        owner = foreign_owner(db_path)
        try:
            monkeypatch.setenv(SKIP_LOCK_ENV, "1")
            assert launcher.acquire_instance_lock(db_path, 8000) is None
        finally:
            owner.release()
        assert "ВНИМАНИЕ" in capsys.readouterr().out


class TestLockLoss:
    def test_server_is_asked_to_stop_and_then_killed_if_it_hangs(self, launcher):
        class FakeServer:
            should_exit = False

        exited = threading.Event()
        codes: list[int] = []

        def fake_exit(code: int) -> None:
            codes.append(code)
            exited.set()

        server = FakeServer()
        launcher.stop_after_lock_loss(server, "блокировка потеряна", force_exit_after=0.05, exit_func=fake_exit)
        assert server.should_exit is True, "сначала штатная остановка"
        assert exited.wait(timeout=2) and codes == [launcher.EXIT_CODE_LOCK_LOST], "затем принудительный выход"

    def test_serve_stops_the_server_on_loss_and_exits_with_an_error(self, launcher, monkeypatch, capsys):
        import uvicorn

        servers: list[object] = []

        class FakeServer:
            should_exit = False

            def __init__(self, config):
                servers.append(self)

            def run(self):
                handler["callback"]("потеряна")  # владение потеряно, пока сервер работает
                assert self.should_exit is True

        class FakeLock:
            lost = True
            lost_reason = "Блокировка потеряна."

            def set_on_lost(self, callback):
                handler["callback"] = callback

        handler: dict = {}
        monkeypatch.setattr(uvicorn, "Config", lambda *args, **kwargs: object())
        monkeypatch.setattr(uvicorn, "Server", FakeServer)
        monkeypatch.setattr(launcher, "stop_after_lock_loss", lambda server, reason: setattr(server, "should_exit", True))
        with pytest.raises(SystemExit) as exit_info:
            launcher.serve(object(), type("S", (), {"listen_host": "127.0.0.1"})(), 8000, FakeLock())
        assert exit_info.value.code == 2
        assert "Блокировка потеряна" in capsys.readouterr().err

    def test_serve_without_a_lock_just_runs_the_server(self, launcher, monkeypatch):
        import uvicorn

        ran: list[bool] = []

        class FakeServer:
            def __init__(self, config):
                pass

            def run(self):
                ran.append(True)

        monkeypatch.setattr(uvicorn, "Config", lambda *args, **kwargs: object())
        monkeypatch.setattr(uvicorn, "Server", FakeServer)
        launcher.serve(object(), type("S", (), {"listen_host": "127.0.0.1"})(), 8000, None)
        assert ran == [True]


class TestMain:
    def test_main_takes_the_lock_before_migrations_and_releases_it_in_finally(self, launcher):
        source = inspect.getsource(launcher.main)
        assert source.index("acquire_instance_lock(") < source.index("migrate_or_fail()"), (
            "иначе вторая копия успела бы сделать копию и обновить базу, которую уже использует первая"
        )
        assert source.index("try:") < source.index("migrate_or_fail()") < source.index("finally:") < source.index("release()")

    def test_a_second_real_copy_is_refused_before_it_touches_the_database(self, tmp_path):
        """Сквозной случай: настоящий launcher.main() в отдельном процессе при занятой базе. Миграции не выполнялись — базы нет."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        owner = foreign_owner(data_dir / "infra_registry.db")
        program = textwrap.dedent(
            f"""
            import sys
            from pathlib import Path
            sys.path.insert(0, {str(REPO_ROOT)!r})
            import launcher
            launcher.app_dir = lambda: Path({str(tmp_path)!r})
            sys.argv = ["launcher.py", "--no-browser", "--port", "8798"]
            launcher.main()
            """
        )
        env = {"PATH": "", "INFRA_REGISTRY_DATA_DIR": str(data_dir), "PYTHONIOENCODING": "utf-8"}
        try:
            result = subprocess.run(
                [sys.executable, "-c", program], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path
            )
        finally:
            owner.release()
        assert result.returncode == 2, result.stderr
        assert "OTHER-PC" in result.stderr and "Traceback" not in result.stderr
        assert not (data_dir / "infra_registry.db").exists(), "отказанная копия не должна создавать или обновлять базу"
        assert not list(data_dir.glob("*.bak")), "и не должна делать резервные копии"
