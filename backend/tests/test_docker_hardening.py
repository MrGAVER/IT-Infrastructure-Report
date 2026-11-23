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

import json
import re
import shutil
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
