"""A-20: Dockerfile и docker-compose.yml — uvicorn это PID 1, код образа только для чтения, данные приложения в томе.

Раньше `CMD ["sh","-c","alembic upgrade head && uvicorn …"]` оставлял оболочку PID 1 (uvicorn — её потомок, SIGTERM от `docker stop`
до приложения не доходил, остановка ждала SIGKILL через 10 с), `chown -R app:app /app` делал исходный код и alembic записываемыми
для процесса приложения, а для /app/data (отчёты, при SQLite — база) не было тома.

docker daemon и доступ к реестру образов в этом окружении недоступны (собрать образ нельзя), поэтому проверка статическая, а
поведение `exec` проверяется настоящей оболочкой `sh` на команде из Dockerfile, где alembic и uvicorn заменены безобидными
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
COMPOSE = ROOT / "docker-compose.yml"
README = ROOT / "README.md"

ALEMBIC = "alembic upgrade head"
UVICORN = "uvicorn app.main:app --host 0.0.0.0 --port 8000"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _run_command() -> str:
    """Строка, которую оболочка получает из CMD (`sh -c <строка>`)."""
    match = re.search(r"^CMD (\[.*\])\s*$", _dockerfile(), re.MULTILINE)
    assert match, "в Dockerfile нет CMD в exec-форме"
    argv = json.loads(match.group(1))
    assert argv[:2] == ["sh", "-c"] and len(argv) == 3
    return argv[2]


def _directive_lines() -> list[str]:
    """Инструкции Dockerfile без комментариев, со склеенными продолжениями строк."""
    text = re.sub(r"\\\n\s*", " ", _dockerfile())
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


class TestDockerfile:
    def test_uvicorn_replaces_the_shell_so_it_gets_sigterm(self):
        command = _run_command()
        assert command == f"{ALEMBIC} && exec {UVICORN}"

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
    def compose(self) -> dict:
        return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))

    def test_application_data_directory_is_a_named_volume(self, compose):
        assert "appdata:/app/data" in compose["services"]["app"]["volumes"]
        assert "appdata" in compose["volumes"] and "pgdata" in compose["volumes"]

    def test_database_volume_is_kept(self, compose):
        assert "pgdata:/var/lib/postgresql/data" in compose["services"]["db"]["volumes"]

    def test_volume_path_matches_the_dockerfile_data_dir(self, compose):
        mount = next(v for v in compose["services"]["app"]["volumes"] if v.startswith("appdata:")).split(":", 1)[1]
        assert f"ENV INFRA_REGISTRY_DATA_DIR={mount}" in _dockerfile()


def test_readme_describes_the_volumes_and_the_read_only_code():
    text = README.read_text(encoding="utf-8")
    assert "`appdata`" in text and "`pgdata`" in text and "/app/data" in text
    assert "PID 1" in text


@pytest.mark.skipif(shutil.which("sh") is None or not Path("/proc/self/comm").exists(), reason="нужны sh и /proc (Linux)")
class TestShellSemantics:
    """Команда из Dockerfile, где alembic заменён на `true`, а uvicorn — на `sleep`: кто становится процессом оболочки."""

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

    def test_with_exec_the_application_becomes_the_container_process(self):
        command = _run_command().replace(ALEMBIC, "true").replace(UVICORN, "sleep 30")
        assert "exec sleep 30" in command
        assert self._comm_of_the_shell_process(command) == "sleep"

    def test_without_exec_the_shell_stays_and_the_application_is_its_child(self):
        """Исходная проблема: без exec процесс контейнера остаётся оболочкой (она не пересылает SIGTERM)."""
        command = _run_command().replace("exec ", "").replace(ALEMBIC, "true").replace(UVICORN, "sleep 30")
        assert "exec" not in command
        assert self._comm_of_the_shell_process(command) == "sh"
