"""F-02 код-ревью: ожидаемые сбои запуска EXE — понятная ошибка с ожиданием Enter, а не трассировка.

`fail()` (launcher.py) умеет держать окно консоли открытым, но до сих пор им пользовались не все ветки: нельзя создать каталог данных
(нет прав на каталог рядом с EXE) или переменная окружения не разобралась при импорте `app.config` — пользователь видел «голую»
трассировку, и окно закрывалось вместе с процессом. Теперь это делает `launcher.prepare_environment()`.

Запуск: pytest backend/tests/test_launcher_startup_errors.py -v
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    sys.modules.pop("launcher", None)
    module = importlib.import_module("launcher")
    yield module
    sys.modules.pop("launcher", None)


@pytest.fixture()
def settings():
    from app.services.exe_settings import ExeSettings

    return ExeSettings()


@pytest.fixture()
def applied(launcher, monkeypatch):
    """В тестах `app.config` уже импортирован: настоящий `apply_environment` отказался бы работать (и не должен менять окружение)."""
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(launcher, "apply_environment", lambda overrides: calls.append(dict(overrides)))
    return calls


class TestPrepareEnvironment:
    def test_the_environment_points_at_the_data_directory(self, launcher, settings, applied, monkeypatch, tmp_path):
        monkeypatch.setattr(launcher, "data_dir", lambda: tmp_path)
        launcher.prepare_environment(settings, REPO_ROOT)
        assert len(applied) == 1
        env = applied[0]
        assert env["INFRA_REGISTRY_DATA_DIR"] == str(tmp_path)
        assert env["DATABASE_URL"] == f"sqlite:///{tmp_path / launcher.DB_FILENAME}"
        assert env["INFRA_REGISTRY_BUNDLE_DIR"] == str(REPO_ROOT)
        assert env["INFRA_REGISTRY_ALLOWED_CLIENTS"], "список клиентов из настроек EXE передаётся"

    def test_an_unwritable_data_directory_is_a_clear_exit_and_the_environment_is_untouched(
        self, launcher, settings, applied, monkeypatch, capsys
    ):
        def denied():
            raise PermissionError(13, "Отказано в доступе", "C:\\Program Files\\РИС")

        monkeypatch.setattr(launcher, "data_dir", denied)
        with pytest.raises(SystemExit) as exit_info:
            launcher.prepare_environment(settings, REPO_ROOT)
        assert exit_info.value.code == 2
        error = capsys.readouterr().err
        assert "Отказано в доступе" in error and "INFRA_REGISTRY_DATA_DIR" in error and "Traceback" not in error
        assert applied == [], "окружение не выставляется, если каталога данных нет"

    def test_failure_to_create_application_directories_is_a_clear_exit(self, launcher, settings, applied, monkeypatch, tmp_path, capsys):
        import app.config as app_config

        monkeypatch.setattr(launcher, "data_dir", lambda: tmp_path)

        def read_only(*directories):
            raise OSError(30, "Read-only file system", str(tmp_path / "reports"))

        monkeypatch.setattr(app_config, "ensure_data_dirs", read_only)
        with pytest.raises(SystemExit) as exit_info:
            launcher.prepare_environment(settings, REPO_ROOT)
        assert exit_info.value.code == 2
        error = capsys.readouterr().err
        assert "Read-only file system" in error and "reports" in error and "Traceback" not in error

    def test_a_bad_setting_value_is_a_clear_exit_that_names_the_variable(self, launcher, settings, applied, monkeypatch, tmp_path, capsys):
        import app.config as app_config

        monkeypatch.setattr(launcher, "data_dir", lambda: tmp_path)

        def bad_value(*directories):
            raise ValueError("INFRA_REGISTRY_REPORT_RETENTION_DAYS: ожидается число, получено 'abc'")

        monkeypatch.setattr(app_config, "ensure_data_dirs", bad_value)
        with pytest.raises(SystemExit) as exit_info:
            launcher.prepare_environment(settings, REPO_ROOT)
        assert exit_info.value.code == 2
        assert "INFRA_REGISTRY_REPORT_RETENTION_DAYS" in capsys.readouterr().err

    def test_a_wrong_import_order_is_a_programmer_error_and_stays_loud(self, launcher, settings, monkeypatch, tmp_path):
        """RuntimeError от apply_environment (app.config уже импортирован) не превращается в «ошибку пользователя»."""
        monkeypatch.setattr(launcher, "data_dir", lambda: tmp_path)
        with pytest.raises(RuntimeError, match="app.config уже импортирован"):
            launcher.prepare_environment(settings, REPO_ROOT)  # настоящий apply_environment: модуль уже загружен


def test_main_fails_cleanly_on_a_bad_environment_variable_in_a_real_process(tmp_path):
    """Сквозной случай: настоящий main() в отдельном процессе. Каталог рядом с «EXE» подменён на временный, иначе launcher создал бы
    infra_registry.toml в корне репозитория."""
    program = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(REPO_ROOT)!r})
        import launcher
        launcher.app_dir = lambda: Path({str(tmp_path)!r})
        sys.argv = ["launcher.py", "--no-browser", "--port", "8799"]
        launcher.main()
        """
    )
    env = {
        "PATH": "",
        "INFRA_REGISTRY_DATA_DIR": str(tmp_path / "data"),
        "INFRA_REGISTRY_REPORT_RETENTION_DAYS": "abc",
        "PYTHONIOENCODING": "utf-8",
    }
    result = subprocess.run(
        [sys.executable, "-c", program], env=env, capture_output=True, text=True, encoding="utf-8", timeout=120, cwd=tmp_path
    )
    assert result.returncode == 2, result.stderr
    assert "INFRA_REGISTRY_REPORT_RETENTION_DAYS" in result.stderr
    assert "Traceback" not in result.stderr
