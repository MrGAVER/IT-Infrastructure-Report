"""A-20: Dockerfile и docker-compose.yml — uvicorn это PID 1, код образа только для чтения, данные приложения в томе.

Раньше `CMD ["sh","-c","alembic upgrade head && uvicorn …"]` оставлял оболочку PID 1 (uvicorn — её потомок, SIGTERM от `docker stop`
до приложения не доходил, остановка ждала SIGKILL через 10 с), `chown -R app:app /app` делал исходный код и alembic записываемыми
для процесса приложения, а для /app/data (отчёты, при SQLite — база) не было тома.

Команда запуска вынесена в backend/docker-entrypoint.sh — перед `alembic upgrade head` скрипт делает резервную
копию SQLite-базы (app/services/db_backup.py); порядок и «не мигрировать без копии» проверяются здесь настоящей оболочкой `sh` на
копии скрипта, где python/alembic/uvicorn заменены заглушками.

docker daemon и доступ к реестру образов в этом окружении недоступны (собрать образ нельзя), поэтому проверка статическая, а
поведение `exec` проверяется настоящей оболочкой `sh` на тексте скрипта, где alembic и uvicorn заменены безобидными
командами. Не покрыто тестами: фактическая сборка, `docker stop` < 3 с и «Permission denied» при записи в /app/app.
Запуск: pytest backend/tests/test_docker_hardening.py -v
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "backend" / "Dockerfile"
ENTRYPOINT = ROOT / "backend" / "docker-entrypoint.sh"
COMPOSE = ROOT / "docker-compose.yml"
README = ROOT / "README.md"

BACKUP = "python -m app.services.db_backup"
ALEMBIC = "alembic upgrade head"
UVICORN = "uvicorn app.main:app --host 0.0.0.0 --port 8000"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _cmd_argv() -> list[str]:
    """CMD из Dockerfile в exec-форме."""
    match = re.search(r"^CMD (\[.*\])\s*$", _dockerfile(), re.MULTILINE)
    assert match, "в Dockerfile нет CMD в exec-форме"
    return json.loads(match.group(1))


def _entrypoint() -> str:
    """Текст скрипта запуска, который CMD отдаёт оболочке."""
    return ENTRYPOINT.read_text(encoding="utf-8")


def _entrypoint_commands() -> list[str]:
    """Команды скрипта по порядку, без комментариев и пустых строк."""
    return [line.strip() for line in _entrypoint().splitlines() if line.strip() and not line.strip().startswith("#")]


def _directive_lines() -> list[str]:
    """Инструкции Dockerfile без комментариев, со склеенными продолжениями строк."""
    text = re.sub(r"\\\n\s*", " ", _dockerfile())
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


class TestDockerfile:
    def test_cmd_runs_the_entrypoint_script_through_sh(self):
        assert _cmd_argv() == ["sh", "/app/docker-entrypoint.sh"]

    def test_entrypoint_is_copied_into_the_image_before_the_permissions_step(self):
        lines = _directive_lines()
        copy_at = next(i for i, line in enumerate(lines) if line.startswith("COPY backend/docker-entrypoint.sh"))
        chmod_at = next(i for i, line in enumerate(lines) if re.search(r"chmod\s+-R\s+a\+rX\s+/app\b", line))
        assert lines[copy_at].split()[-1] == "./docker-entrypoint.sh" and copy_at < chmod_at

    def test_backup_runs_before_migrations_and_uvicorn_replaces_the_shell(self):
        """Копия SQLite → alembic → exec uvicorn (PID 1 получает SIGTERM)."""
        assert _entrypoint_commands() == ["set -eu", BACKUP, ALEMBIC, f"exec {UVICORN}"]

    def test_entrypoint_uses_unix_line_endings(self):
        """CRLF в скрипте ломает `set -eu` в контейнере; .gitattributes фиксирует LF при checkout на Windows."""
        assert b"\r" not in ENTRYPOINT.read_bytes()
        assert "*.sh text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()

    def test_code_is_not_writable_by_the_application_user(self):
        lines = _directive_lines()
        assert not any(re.search(r"chown\s+-R\b.*\s/app(\s|$)", line) for line in lines), "chown -R /app отдаёт код процессу приложения"
        owned = [line for line in lines if "chown" in line]
        assert owned and all("/app/data" in line for line in owned if "chown" in line)
        assert any("mkdir -p /app/data" in line and "chown app:app /app/data" in line for line in lines)

    def test_data_directory_exists_before_the_user_switch_and_home_is_writable(self):
        lines = _directive_lines()
        user_at = next(i for i, line in enumerate(lines) if line == "USER app")
        mkdir_at = next(i for i, line in enumerate(lines) if "mkdir -p /app/data" in line)
        assert mkdir_at < user_at
        assert any("--home-dir /app/data" in line for line in lines)
        assert "ENV INFRA_REGISTRY_DATA_DIR=/app/data" in lines

    def test_code_stays_readable_for_the_application_user(self):
        assert any(re.search(r"chmod\s+-R\s+a\+rX\s+/app\b", line) for line in _directive_lines())

    def test_process_does_not_run_as_root(self):
        lines = _directive_lines()
        assert lines.index("USER app") < next(i for i, line in enumerate(lines) if line.startswith("CMD "))


class TestCompose:
    @pytest.fixture(scope="class")
    @classmethod
    def compose(cls) -> dict:
        return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))

    def test_application_data_directory_is_a_named_volume(self, compose):
        assert "appdata:/app/data" in compose["services"]["app"]["volumes"]
        assert "appdata" in compose["volumes"] and "pgdata" in compose["volumes"]

    def test_database_volume_is_kept(self, compose):
        assert "pgdata:/var/lib/postgresql/data" in compose["services"]["db"]["volumes"]

    def test_volume_path_matches_the_dockerfile_data_dir(self, compose):
        mount = next(v for v in compose["services"]["app"]["volumes"] if v.startswith("appdata:")).split(":", 1)[1]
        assert f"ENV INFRA_REGISTRY_DATA_DIR={mount}" in _dockerfile()


class TestPostgresBackupService:
    """pg_dump перед обновлением — одноразовый сервис compose с профилем backup (не стартует вместе с приложением)."""

    @pytest.fixture(scope="class")
    @classmethod
    def service(cls) -> dict:
        return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["db-backup"]

    def test_runs_only_on_request(self, service):
        assert service["profiles"] == ["backup"]

    def test_waits_for_the_database_and_writes_into_the_appdata_volume(self, service):
        assert service["depends_on"]["db"]["condition"] == "service_healthy"
        assert "appdata:/backup" in service["volumes"]

    def test_password_is_required_and_taken_from_env_not_from_the_command_line(self, service):
        assert "POSTGRES_PASSWORD:?" in service["environment"]["PGPASSWORD"]
        assert "PGPASSWORD" not in service["command"][0].replace("$${PGPASSWORD}", "")

    def test_dump_is_atomic_rotated_and_compose_dollars_are_escaped(self, service):
        script = service["command"][0]
        assert "pg_dump --format=custom" in script
        assert 'mv "$${target}.tmp" "$${target}"' in script, "оборванный дамп не должен выглядеть готовым"
        assert "tail -n +6" in script, "хранятся пять последних"
        unescaped = re.findall(r"(?<!\$)\$(?!\$)", script)
        assert unescaped == [], "одиночный `$` compose подставил бы сам: в контейнер попала бы пустая строка"


class TestScheduledPostgresBackupService:
    """F-13 код-ревью: периодическая копия PostgreSQL — постоянный сервис `db-backup-scheduled` (профиль backup-schedule).

    Раньше копия PostgreSQL делалась только руками перед обновлением. Сервис пишет дамп в каталог хоста, проверяет его `pg_restore --list`,
    хранит `BACKUP_KEEP` последних и сообщает о сбое. Docker здесь недоступен, поэтому скрипт из compose-файла выполняется настоящей
    оболочкой `sh`, а `pg_dump` и `pg_restore` заменены заглушками (настоящий `pg_dump` проверялся вручную на PostgreSQL 16).
    """

    ENV_KEYS = ("BACKUP_INTERVAL_SECONDS", "BACKUP_KEEP")

    @pytest.fixture(scope="class")
    @classmethod
    def service(cls) -> dict:
        return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]["db-backup-scheduled"]

    @pytest.fixture(scope="class")
    @classmethod
    def script(cls, service) -> str:
        """Текст скрипта так, как его увидит контейнер: compose превращает `$$` в `$`."""
        return service["command"][0].replace("$$", "$")

    # --- статические свойства сервиса ---------------------------------------------------------------------------------------------
    def test_runs_only_on_request_and_restarts_after_a_reboot(self, service):
        assert service["profiles"] == ["backup-schedule"]
        assert service["restart"] == "unless-stopped"

    def test_waits_for_the_database_and_takes_the_password_from_env(self, service):
        assert service["depends_on"]["db"]["condition"] == "service_healthy"
        assert "POSTGRES_PASSWORD:?" in service["environment"]["PGPASSWORD"]
        assert "PGPASSWORD" not in service["command"][0].replace("$${PGPASSWORD}", "")

    def test_copies_go_to_a_host_directory_and_not_into_the_appdata_volume(self, service):
        (mount,) = service["volumes"]
        assert mount == "${BACKUP_HOST_DIR:-./backups}:/backup"
        assert "appdata" not in mount and "pgdata" not in mount, "том Docker — тот же хост и та же судьба, что у базы"

    def test_parameter_names_and_defaults_are_the_agreed_ones(self, service):
        assert service["environment"]["BACKUP_INTERVAL_SECONDS"] == "${BACKUP_INTERVAL_SECONDS:-86400}"
        assert service["environment"]["BACKUP_KEEP"] == "${BACKUP_KEEP:-14}"

    def test_dump_is_private_checked_and_published_atomically(self, script):
        assert "umask 077" in script, "в копии хеши паролей и журнал аудита"
        assert script.index("pg_dump --format=custom") < script.index("pg_restore --list") < script.index('mv "${target}.tmp" "${target}"')

    def test_compose_dollars_are_escaped_in_the_script_and_in_the_healthcheck(self, service):
        for text in (service["command"][0], service["healthcheck"]["test"][1]):
            assert re.findall(r"(?<!\$)\$(?!\$)", text) == [], "одиночный `$` compose подставил бы сам: в контейнер попала бы пустая строка"

    def test_there_is_a_healthcheck_for_a_missing_fresh_copy(self, service):
        health = service["healthcheck"]
        assert "*.dump" in health["test"][1] and "-mmin" in health["test"][1]
        assert health["start_period"], "первая копия делается сразу после старта, но не мгновенно"

    def test_parameters_are_documented_in_env_example_and_the_copies_directory_is_ignored_by_git(self):
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in (*self.ENV_KEYS, "BACKUP_HOST_DIR"):
            assert f"# {key}=" in example, key
        assert "/backups/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines(), (
            "дамп с хешами паролей не должен попасть в git"
        )

    # --- поведение скрипта: настоящая оболочка, заглушки pg_dump / pg_restore -------------------------------------------------------
    @pytest.fixture()
    def sandbox(self, tmp_path):
        if shutil.which("sh") is None:
            pytest.skip("нужна оболочка sh")
        bin_dir, backup = tmp_path / "bin", tmp_path / "backup"
        bin_dir.mkdir()
        backup.mkdir()
        (bin_dir / "pg_dump").write_text(
            "#!/bin/sh\n"
            'for arg in "$@"; do case "$arg" in --file=*) out="${arg#--file=}";; esac; done\n'
            'echo PARTIAL > "$out"\n'
            'if [ -n "${FAKE_PG_FAIL:-}" ]; then echo "pg_dump: ошибка: FATAL: password authentication failed" >&2; exit 1; fi\n'
            'echo FAKEDUMP >> "$out"\n',
            encoding="utf-8",
        )
        (bin_dir / "pg_restore").write_text('#!/bin/sh\ngrep -q FAKEDUMP "$2"\n', encoding="utf-8")
        for name in ("pg_dump", "pg_restore"):
            (bin_dir / name).chmod(0o755)
        return tmp_path

    @staticmethod
    def _start(script: str, sandbox: Path, **env: str) -> subprocess.Popen:
        """Скрипт в своей группе процессов; вывод — в файлы, а не в каналы: осиротевший `sleep` держал бы каналы открытыми."""
        script = script.replace("/backup", str(sandbox / "backup"))
        environment = {
            "PATH": f"{sandbox / 'bin'}:/usr/bin:/bin",
            "PGDATABASE": "infra",
            "BACKUP_INTERVAL_SECONDS": "30",
            "BACKUP_KEEP": "3",
            **env,
        }
        with (sandbox / "out.log").open("wb") as out, (sandbox / "err.log").open("wb") as err:
            return subprocess.Popen(["sh", "-c", script], env=environment, stdout=out, stderr=err, start_new_session=True)

    @staticmethod
    def _wait_for(condition, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def _stop(process: subprocess.Popen, sandbox: Path) -> tuple[int, str, str, float]:
        """SIGTERM, как от `docker stop`; возвращает код выхода, stdout, stderr и время остановки."""
        started = time.monotonic()
        process.terminate()
        try:
            process.wait(timeout=5)
        finally:
            elapsed = time.monotonic() - started
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)  # осиротевший sleep: в контейнере его убило бы завершение PID 1
        out = (sandbox / "out.log").read_text(encoding="utf-8")
        err = (sandbox / "err.log").read_text(encoding="utf-8")
        return process.returncode, out, err, elapsed

    def test_a_copy_is_made_at_start_private_and_without_leftovers(self, script, sandbox):
        backup = sandbox / "backup"
        process = self._start(script, sandbox)
        assert self._wait_for(lambda: list(backup.glob("*.dump")))
        code, out, _, _ = self._stop(process, sandbox)
        (dump,) = backup.glob("*.dump")
        assert dump.name.startswith("infra.") and "FAKEDUMP" in dump.read_text(encoding="utf-8")
        assert oct(dump.stat().st_mode & 0o777) == "0o600", "umask 077"
        assert list(backup.glob("*.tmp")) == []
        assert "Резервная копия:" in out and code == 0

    def test_service_stops_at_once_on_sigterm_not_after_the_docker_stop_timeout(self, script, sandbox):
        backup = sandbox / "backup"
        process = self._start(script, sandbox, BACKUP_INTERVAL_SECONDS="3600")
        assert self._wait_for(lambda: list(backup.glob("*.dump")))
        time.sleep(0.2)  # цикл дошёл до sleep
        code, _, _, seconds = self._stop(process, sandbox)
        assert code == 0 and seconds < 3, f"остановка заняла {seconds:.1f} с"

    def test_only_the_newest_copies_are_kept_and_other_files_are_untouched(self, script, sandbox):
        backup = sandbox / "backup"
        now = time.time()
        for age, name in enumerate(["infra.20200101-000000.dump", "infra.20200102-000000.dump", "infra.20200103-000000.dump"], start=1):
            path = backup / name
            path.write_text("FAKEDUMP", encoding="utf-8")
            os.utime(path, (now - 3600 * (10 - age), now - 3600 * (10 - age)))
        other = backup / "заметка.txt"
        other.write_text("не копия", encoding="utf-8")
        process = self._start(script, sandbox, BACKUP_KEEP="2")
        assert self._wait_for(
            lambda: (
                len(list(backup.glob("infra.2026*.dump"))) + len(list(backup.glob("infra.20[3-9]*.dump"))) >= 1
                or len(list(backup.glob("*.dump"))) == 2
            )
        )
        time.sleep(0.3)
        self._stop(process, sandbox)
        names = sorted(path.name for path in backup.glob("*.dump"))
        assert len(names) == 2, names
        assert "infra.20200101-000000.dump" not in names and "infra.20200102-000000.dump" not in names
        assert other.exists()

    def test_a_failed_dump_is_reported_leaves_no_partial_file_and_does_not_stop_the_loop(self, script, sandbox):
        backup = sandbox / "backup"
        process = self._start(script, sandbox, FAKE_PG_FAIL="1", BACKUP_INTERVAL_SECONDS="1")
        time.sleep(2.5)  # не меньше двух проходов цикла
        assert process.poll() is None, "сбой одной копии не должен останавливать сервис"
        code, _, err, _ = self._stop(process, sandbox)
        assert err.count("ОШИБКА резервного копирования") >= 2 and "password authentication failed" in err
        assert list(backup.iterdir()) == [] and code == 0

    def test_an_unreadable_dump_is_not_published(self, script, sandbox):
        """pg_dump завершился успешно, но pg_restore --list дамп не читает: готовой копией он не становится."""
        (sandbox / "bin" / "pg_restore").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        backup = sandbox / "backup"
        process = self._start(script, sandbox, BACKUP_INTERVAL_SECONDS="1")
        time.sleep(1.5)
        _, _, err, _ = self._stop(process, sandbox)
        assert list(backup.iterdir()) == [] and "ОШИБКА резервного копирования" in err

    def test_a_stale_temporary_file_from_a_killed_run_is_removed_at_start(self, script, sandbox):
        backup = sandbox / "backup"
        stale = backup / "infra.20200101-000000.dump.tmp"
        stale.write_text("обрывок", encoding="utf-8")
        process = self._start(script, sandbox)
        assert self._wait_for(lambda: list(backup.glob("*.dump")))
        self._stop(process, sandbox)
        assert not stale.exists()

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("BACKUP_INTERVAL_SECONDS", "0"),
            ("BACKUP_INTERVAL_SECONDS", "abc"),
            ("BACKUP_INTERVAL_SECONDS", ""),
            ("BACKUP_INTERVAL_SECONDS", "-5"),
            ("BACKUP_KEEP", "0"),
            ("BACKUP_KEEP", "много"),
        ],
    )
    def test_a_bad_parameter_stops_the_service_instead_of_looping_or_making_copies(self, script, sandbox, name, value):
        process = self._start(script, sandbox, **{name: value})
        assert process.wait(timeout=10) == 64
        assert name in (sandbox / "err.log").read_text(encoding="utf-8")
        assert list((sandbox / "backup").iterdir()) == []

    # --- healthcheck ------------------------------------------------------------------------------------------------------------------
    def _health(self, service: dict, sandbox: Path, interval: str = "60") -> int:
        command = service["healthcheck"]["test"][1].replace("$$", "$").replace("/backup", str(sandbox / "backup"))
        return subprocess.run(
            ["sh", "-c", command], env={"PATH": "/usr/bin:/bin", "BACKUP_INTERVAL_SECONDS": interval}, check=False
        ).returncode

    def test_healthcheck_passes_with_a_fresh_copy_and_fails_without_one_or_with_only_old_ones(self, service, sandbox):
        backup = sandbox / "backup"
        assert self._health(service, sandbox) != 0, "копий нет"
        old = backup / "infra.20200101-000000.dump"
        old.write_text("FAKEDUMP", encoding="utf-8")
        long_ago = time.time() - 3 * 60  # интервал 60 с: допустимо до двух интервалов
        os.utime(old, (long_ago, long_ago))
        assert self._health(service, sandbox) != 0, "последняя копия старше двух интервалов"
        (backup / "infra.20261122-000000.dump").write_text("FAKEDUMP", encoding="utf-8")
        assert self._health(service, sandbox) == 0

    def test_healthcheck_tolerates_a_gap_of_almost_two_intervals(self, service, sandbox):
        backup = sandbox / "backup"
        dump = backup / "infra.20261122-000000.dump"
        dump.write_text("FAKEDUMP", encoding="utf-8")
        ago = time.time() - 90 * 60  # интервал сутки — копии нет полтора часа: это нормально
        os.utime(dump, (ago, ago))
        assert self._health(service, sandbox, interval="86400") == 0


def test_readme_explains_the_update_procedure_backups_and_the_single_instance_rule():
    text = README.read_text(encoding="utf-8")
    assert "docker compose --profile backup run --rm db-backup" in text
    assert "docker-entrypoint.sh" in text and "INFRA_REGISTRY_SKIP_BACKUP" in text
    assert "Один экземпляр приложения" in text and "--scale app=N" in text


def test_readme_describes_the_volumes_and_the_read_only_code():
    text = README.read_text(encoding="utf-8")
    assert "`appdata`" in text and "`pgdata`" in text and "/app/data" in text
    assert "PID 1" in text


@pytest.mark.skipif(shutil.which("sh") is None or not Path("/proc/self/comm").exists(), reason="нужны sh и /proc (Linux)")
class TestShellSemantics:
    """Скрипт запуска, где резервная копия и alembic заменены на `true`, а uvicorn — на `sleep`: кто становится процессом оболочки."""

    @staticmethod
    def _comm_of_the_shell_process(command: str) -> str:
        # Между fork и exec у дочернего процесса имя родителя (pytest/python): его тоже пропускаем, иначе на загруженной машине
        # читается имя ещё не запущенной оболочки и тест краснеет случайно.
        own_name = Path("/proc/self/comm").read_text().strip()
        process = subprocess.Popen(["sh", "-c", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                comm = Path(f"/proc/{process.pid}/comm").read_text().strip()
                if comm not in {"sh", own_name}:
                    return comm
                time.sleep(0.05)
            return Path(f"/proc/{process.pid}/comm").read_text().strip()
        finally:
            process.kill()
            subprocess.run(["pkill", "-P", str(process.pid)], check=False)
            process.wait()

    @staticmethod
    def _stubbed(text: str) -> str:
        return text.replace(BACKUP, "true").replace(ALEMBIC, "true").replace(UVICORN, "sleep 30")

    def test_with_exec_the_application_becomes_the_container_process(self):
        command = self._stubbed("\n".join(_entrypoint_commands()))
        assert "exec sleep 30" in command
        assert self._comm_of_the_shell_process(command) == "sleep"

    def test_without_exec_the_shell_stays_and_the_application_is_its_child(self):
        """Исходная проблема: без exec процесс контейнера остаётся оболочкой (она не пересылает SIGTERM)."""
        command = self._stubbed("\n".join(_entrypoint_commands())).replace("exec ", "")
        assert "exec" not in command
        assert self._comm_of_the_shell_process(command) == "sh"


@pytest.mark.skipif(shutil.which("sh") is None, reason="нужна оболочка sh")
class TestEntrypointOrdering:
    """Настоящий скрипт с заглушками python/alembic/uvicorn в PATH, журнал вызовов — по порядку; сбой копии не пускает дальше."""

    @staticmethod
    def _run(tmp_path: Path, backup_exit_code: int) -> tuple[subprocess.CompletedProcess, list[str]]:
        bin_dir, journal = tmp_path / "bin", tmp_path / "calls.log"
        bin_dir.mkdir()
        stubs = {
            "python": f'echo "python $*" >> "{journal}"; exit {backup_exit_code}',
            "alembic": f'echo "alembic $*" >> "{journal}"',
            "uvicorn": f'echo "uvicorn $*" >> "{journal}"',
        }
        for name, body in stubs.items():
            stub = bin_dir / name
            stub.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
            stub.chmod(0o755)
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
        result = subprocess.run(["sh", str(ENTRYPOINT)], env=env, capture_output=True, text=True, timeout=30)
        return result, journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []

    def test_backup_then_migration_then_server(self, tmp_path):
        result, calls = self._run(tmp_path, backup_exit_code=0)
        assert result.returncode == 0, result.stderr
        assert calls == ["python -m app.services.db_backup", "alembic upgrade head", "uvicorn app.main:app --host 0.0.0.0 --port 8000"]

    def test_failed_backup_stops_before_migration_and_server(self, tmp_path):
        result, calls = self._run(tmp_path, backup_exit_code=1)
        assert result.returncode == 1
        assert calls == ["python -m app.services.db_backup"], "без резервной копии миграцию не начинаем"
