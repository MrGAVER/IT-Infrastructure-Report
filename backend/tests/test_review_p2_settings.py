"""Н-5: настройки — неизменяемый ``Settings``, импорт ``app.config`` без побочных эффектов, ``ensure_data_dirs()``.

Раньше ``config.py`` при импорте создавал каталоги данных и отчётов (любой скрипт или тест, импортировавший модуль, оставлял папки в текущем
каталоге), а лаунчер выставлял переменные окружения ДО импорта приложения, не имея защиты от нарушения этого порядка. Теперь:

* окружение разбирает ``Settings.from_env()`` (можно передать свой словарь, не трогая ``os.environ``), объект неизменяем;
* прежние имена ``config.APP_DATA_DIR``, ``config.ALLOWED_HOSTS`` и т. д. остались псевдонимами его значений;
* каталоги создаёт ``ensure_data_dirs()`` — из lifespan, launcher.py и alembic/env.py;
* ``launcher.apply_environment`` отказывается менять окружение, если ``app.config`` уже импортирован.

Запуск: pytest backend/tests/test_review_p2_settings.py -v
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import config

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


def _clean_environment(**extra: str) -> dict[str, str]:
    """Окружение дочернего процесса без настроек приложения, которые conftest выставил для самих тестов."""
    env = {key: value for key, value in os.environ.items() if not key.startswith(("INFRA_REGISTRY_", "POSTGRES_")) and key != "DATABASE_URL"}
    env.update(extra)
    return env


class TestImportHasNoSideEffects:
    def test_importing_config_creates_no_directories_and_ensure_data_dirs_creates_them(self, tmp_path):
        data_dir = tmp_path / "not-created-yet"
        script = (
            f"import json, sys\nsys.path.insert(0, {str(BACKEND_DIR)!r})\nimport app.config as config\n"
            "after_import = [config.APP_DATA_DIR.exists(), config.REPORT_DIR.exists()]\n"
            "config.ensure_data_dirs()\nafter_call = [config.APP_DATA_DIR.exists(), config.REPORT_DIR.exists()]\n"
            f"print(json.dumps({{'after_import': after_import, 'after_call': after_call, 'reports': str(config.REPORT_DIR)}}))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=tmp_path,
            env=_clean_environment(INFRA_REGISTRY_DATA_DIR=str(data_dir)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])
        assert report["after_import"] == [False, False], "импорт app.config снова создаёт каталоги"
        assert report["after_call"] == [True, True]
        assert Path(report["reports"]) == (data_dir / "reports").resolve()

    def test_alembic_cli_creates_the_data_directory_for_the_default_sqlite_file(self, tmp_path):
        """Docker: `alembic upgrade head` из docker-entrypoint.sh запускается до приложения; каталог данных раньше создавал импорт app.config."""
        data_dir = tmp_path / "fresh" / "data"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=_clean_environment(INFRA_REGISTRY_DATA_DIR=str(data_dir)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        assert result.returncode == 0, result.stderr[-2000:]
        assert (data_dir / "infra_registry.db").is_file()


class TestEnsureDataDirs:
    def test_creates_the_given_directories_with_parents_and_is_idempotent(self, tmp_path):
        first, second = tmp_path / "a" / "b", tmp_path / "c"
        config.ensure_data_dirs(first, second)
        config.ensure_data_dirs(first, second)
        assert first.is_dir() and second.is_dir()

    def test_without_arguments_uses_the_current_config_values(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        monkeypatch.setattr(config, "APP_DATA_DIR", data_dir)
        monkeypatch.setattr(config, "REPORT_DIR", data_dir / "reports")
        config.ensure_data_dirs()
        assert (data_dir / "reports").is_dir()

    def test_an_uncreatable_directory_is_an_explicit_error(self, tmp_path):
        occupied = tmp_path / "file"
        occupied.write_text("не каталог", encoding="utf-8")
        with pytest.raises(OSError):
            config.ensure_data_dirs(occupied / "reports")


class TestSettings:
    def test_defaults_without_any_environment(self, tmp_path):
        settings = config.Settings.from_env({"INFRA_REGISTRY_DATA_DIR": str(tmp_path)})
        assert settings.data_dir == tmp_path.resolve()
        assert settings.report_dir == tmp_path.resolve() / "reports"
        assert settings.database_url == f"sqlite:///{tmp_path.resolve() / 'infra_registry.db'}"
        assert settings.allowed_hosts == ("localhost", "127.0.0.1")
        assert settings.report_max_files == 200
        assert settings.max_request_body_bytes == 2 * 1024 * 1024
        assert settings.enable_docs is False
        assert settings.auth_lockout_known_client_bypass is True
        assert not settings.db_pool_options

    def test_values_come_from_the_given_mapping_and_the_process_environment_is_untouched(self, tmp_path):
        before = dict(os.environ)
        settings = config.Settings.from_env(
            {
                "INFRA_REGISTRY_DATA_DIR": str(tmp_path),
                "INFRA_REGISTRY_ALLOWED_HOSTS": "reestr.corp.local, localhost",
                "INFRA_REGISTRY_AUDIT_RETENTION_DAYS": "90",
                "INFRA_REGISTRY_ENABLE_DOCS": "yes",
                "INFRA_REGISTRY_DB_POOL_SIZE": "20",
                "INFRA_REGISTRY_AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS": "off",
            }
        )
        assert settings.allowed_hosts == ("reestr.corp.local", "localhost")
        assert settings.audit_retention_days == 90
        assert settings.enable_docs is True
        assert settings.db_pool_options == {"pool_size": 20}
        assert settings.auth_lockout_known_client_bypass is False
        assert dict(os.environ) == before

    def test_an_invalid_value_names_the_variable(self):
        with pytest.raises(ValueError, match="INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES"):
            config.Settings.from_env({"INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES": "много"})

    def test_settings_are_immutable(self):
        settings = config.Settings.from_env({"INFRA_REGISTRY_DB_POOL_SIZE": "5"})
        with pytest.raises(dataclasses.FrozenInstanceError):
            settings.enable_docs = True  # type: ignore[misc]
        with pytest.raises(TypeError):
            settings.db_pool_options["pool_size"] = 99  # type: ignore[index]

    def test_old_module_names_stay_aliases_of_the_settings_values(self):
        assert config.APP_DATA_DIR == config.settings.data_dir
        assert config.settings.report_dir == config.settings.data_dir / "reports"
        assert config.ALLOWED_HOSTS == list(config.settings.allowed_hosts) and isinstance(config.ALLOWED_HOSTS, list)
        assert config.DB_POOL_OPTIONS == dict(config.settings.db_pool_options)
        assert config.CSP_POLICY == config.settings.csp_policy


class TestLifespanAndLauncher:
    def test_lifespan_creates_the_data_directories(self, client_factory, monkeypatch):
        from app import main as app_main

        calls: list[tuple] = []
        monkeypatch.setattr(app_main, "ensure_data_dirs", lambda *directories: calls.append(directories))
        client_factory()  # вход в TestClient запускает lifespan
        assert calls == [()]

    @pytest.fixture()
    def launcher(self, monkeypatch):
        monkeypatch.syspath_prepend(str(REPO_ROOT))
        sys.modules.pop("launcher", None)
        module = importlib.import_module("launcher")
        yield module
        sys.modules.pop("launcher", None)

    def test_apply_environment_refuses_to_run_after_the_config_was_imported(self, launcher, monkeypatch):
        monkeypatch.setattr(launcher.os, "environ", {})
        assert "app.config" in sys.modules
        with pytest.raises(RuntimeError, match="app.config"):
            launcher.apply_environment({"INFRA_REGISTRY_ALLOWED_CLIENTS": "127.0.0.0/8"})
        assert launcher.os.environ == {}

    def test_apply_environment_sets_the_variables_while_the_config_is_not_imported(self, launcher, monkeypatch):
        monkeypatch.delitem(sys.modules, "app.config")
        monkeypatch.setattr(launcher.os, "environ", {})
        launcher.apply_environment({"INFRA_REGISTRY_ALLOWED_CLIENTS": "127.0.0.0/8", "DATABASE_URL": "sqlite:///x.db"})
        assert launcher.os.environ == {"INFRA_REGISTRY_ALLOWED_CLIENTS": "127.0.0.0/8", "DATABASE_URL": "sqlite:///x.db"}
