"""
A-03 (код-ревью main @ b375f58): пустое значение числовой переменной окружения не должно ронять запуск.

Семь настроек разбирались «голым» `int(os.getenv(...))`/`float(...)`: незаполненная строка `VAR=` в `.env` давала при импорте `app.config` безымянный
`ValueError: invalid literal for int() with base 10: ''` — контейнер уходил в цикл перезапусков. Теперь все они идут через `config._number_env`: пусто —
значение по умолчанию, нечисловое или ниже допустимого — ошибка запуска с ИМЕНЕМ переменной.

Константы читаются при импорте модуля, поэтому реальные значения проверяются импортом `app.config` в отдельном процессе с нужным окружением.

Запуск: pytest backend/tests/test_config_number_env.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

# (переменная, константа в app.config, умолчание, допустимое значение → результат, значение ниже допустимого или None)
SETTINGS = [
    ("INFRA_REGISTRY_REPORT_RETENTION_DAYS", "REPORT_RETENTION_DAYS", 30, ("7", 7), None),  # 0 и меньше — «не удалять по возрасту» (report_cleanup)
    ("INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES", "MAX_REQUEST_BODY_BYTES", 2 * 1024 * 1024, ("1024", 1024), "-1"),
    ("INFRA_REGISTRY_SESSION_TTL_HOURS", "AUTH_SESSION_TTL_HOURS", 12.0, ("0.5", 0.5), "-1"),
    ("INFRA_REGISTRY_AUTH_MAX_ATTEMPTS", "AUTH_MAX_FAILED_ATTEMPTS", 10, ("3", 3), "0"),
    ("INFRA_REGISTRY_AUTH_LOCKOUT_MINUTES", "AUTH_LOCKOUT_MINUTES", 15.0, ("2.5", 2.5), "-0.5"),
    ("INFRA_REGISTRY_AUTH_MIN_PASSWORD_LENGTH", "AUTH_MIN_PASSWORD_LENGTH", 8, ("12", 12), "0"),
    ("INFRA_REGISTRY_AUTH_KNOWN_CLIENT_DAYS", "AUTH_KNOWN_CLIENT_DAYS", 30, ("14", 14), "-1"),
    ("INFRA_REGISTRY_AUDIT_RETENTION_DAYS", "AUDIT_RETENTION_DAYS", 0, ("90", 90), "-1"),  # A-05: срок хранения журнала аудита, 0 — не удалять (services/audit_retention)
]
ALL_ENV_NAMES = [setting[0] for setting in SETTINGS]
IDS = [setting[1] for setting in SETTINGS]

_PROBE = "import json, sys; sys.path.insert(0, sys.argv[1]); import app.config as config; print(json.dumps({name: getattr(config, name) for name in sys.argv[2:]}))"


def _import_config(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    """Импортирует app.config в чистом процессе: из окружения убраны все переменные таблицы SETTINGS, заданные в `env` — добавлены."""
    environment = {key: value for key, value in os.environ.items() if key not in ALL_ENV_NAMES}
    environment.update(DATABASE_URL="sqlite:///:memory:", INFRA_REGISTRY_DATA_DIR=str(tmp_path))
    environment.update(env)
    attributes = [setting[1] for setting in SETTINGS]
    return subprocess.run([sys.executable, "-c", _PROBE, str(BACKEND_DIR), *attributes], env=environment, capture_output=True, text=True, timeout=60)


def _error_line(process: subprocess.CompletedProcess) -> str:
    """Последняя строка traceback — само исключение. Проверять весь stderr нельзя: имя переменной попадает туда и через строку исходника в трассировке."""
    assert process.returncode != 0, "запуск должен был завершиться ошибкой"
    return process.stderr.strip().splitlines()[-1]


def _values(process: subprocess.CompletedProcess) -> dict:
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def test_defaults_when_nothing_is_set(tmp_path):
    values = _values(_import_config(tmp_path))
    assert values == {attr: default for _, attr, default, _, _ in SETTINGS}


@pytest.mark.parametrize(("env_name", "attr", "default", "valid", "below_minimum"), SETTINGS, ids=IDS)
@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
def test_blank_value_means_default_instead_of_crashing_the_start(tmp_path, env_name, attr, default, valid, below_minimum, blank):
    # Раньше: ValueError: invalid literal for int() with base 10: '' при импорте — запуск падал без имени переменной.
    values = _values(_import_config(tmp_path, **{env_name: blank}))
    assert values[attr] == default


@pytest.mark.parametrize(("env_name", "attr", "default", "valid", "below_minimum"), SETTINGS, ids=IDS)
def test_valid_value_is_applied(tmp_path, env_name, attr, default, valid, below_minimum):
    raw, expected = valid
    assert _values(_import_config(tmp_path, **{env_name: raw}))[attr] == expected


@pytest.mark.parametrize(("env_name", "attr", "default", "valid", "below_minimum"), SETTINGS, ids=IDS)
def test_non_numeric_value_fails_the_start_naming_the_variable(tmp_path, env_name, attr, default, valid, below_minimum):
    error = _error_line(_import_config(tmp_path, **{env_name: "abc"}))
    assert error.startswith("ValueError") and env_name in error, f"в ошибке запуска должно быть имя переменной, а не безымянный invalid literal: {error}"


@pytest.mark.parametrize(("env_name", "attr", "default", "valid", "below_minimum"), [setting for setting in SETTINGS if setting[4] is not None], ids=[setting[1] for setting in SETTINGS if setting[4] is not None])
def test_value_below_the_minimum_fails_the_start_naming_the_variable(tmp_path, env_name, attr, default, valid, below_minimum):
    error = _error_line(_import_config(tmp_path, **{env_name: below_minimum}))
    assert error.startswith("ValueError") and env_name in error, error


@pytest.mark.parametrize("raw", ["0", "-5"])
def test_report_retention_zero_and_negative_still_mean_never_delete(tmp_path, raw):
    # report_cleanup.py: 0 и меньше отключают очистку по возрасту — это документированное поведение, minimum у настройки намеренно не задан.
    assert _values(_import_config(tmp_path, INFRA_REGISTRY_REPORT_RETENTION_DAYS=raw))["REPORT_RETENTION_DAYS"] == int(raw)


FLOAT_SETTINGS = [setting for setting in SETTINGS if isinstance(setting[2], float)]


@pytest.mark.parametrize(("env_name", "attr", "default", "valid", "below_minimum"), FLOAT_SETTINGS, ids=[setting[1] for setting in FLOAT_SETTINGS])
@pytest.mark.parametrize("raw", ["inf", "Infinity", "nan", "-inf"])
def test_a_non_finite_float_fails_the_start_naming_the_variable(tmp_path, env_name, attr, default, valid, below_minimum, raw):
    # Раньше `inf` проходил проверку минимума (inf >= 0), а `nan` — любую (nan < 0 ложно): запуск шёл, и ошибка (OverflowError в timedelta) случалась
    # в рантайме, при первой блокировке учётной записи.
    error = _error_line(_import_config(tmp_path, **{env_name: raw}))
    assert error.startswith("ValueError") and env_name in error, error


def test_audit_retention_above_the_documented_maximum_fails_the_start_naming_the_variable(tmp_path):
    # Раньше верхней границы у переменной не было: 1000000 проходило при импорте, а `now - timedelta(days=…)` в очистке давало OverflowError
    # и роняло запуск сервера и каждое открытие журнала. README и .env.example обещают «не больше 3650».
    from app.constants import AUDIT_RETENTION_MAX_DAYS

    env_name, attr = "INFRA_REGISTRY_AUDIT_RETENTION_DAYS", "AUDIT_RETENTION_DAYS"
    assert _values(_import_config(tmp_path, **{env_name: str(AUDIT_RETENTION_MAX_DAYS)}))[attr] == AUDIT_RETENTION_MAX_DAYS
    for raw in (str(AUDIT_RETENTION_MAX_DAYS + 1), "1000000"):
        error = _error_line(_import_config(tmp_path, **{env_name: raw}))
        assert error.startswith("ValueError") and env_name in error and str(AUDIT_RETENTION_MAX_DAYS) in error, error


def test_documented_audit_retention_maximum_matches_the_constant():
    # Документация и код расходились (README: 3650, код: без границы); тест перечня переменных такого расхождения не видел.
    from app.constants import AUDIT_RETENTION_MAX_DAYS

    repository = BACKEND_DIR.parent
    for name in (".env.example", "README.md"):
        lines = [line for line in (repository / name).read_text(encoding="utf-8").splitlines() if "3650" in line or "наибольший срок" in line]
        assert lines, f"{name}: нет строки с наибольшим сроком хранения аудита"
        assert all(str(AUDIT_RETENTION_MAX_DAYS) in line for line in lines), f"{name}: граница в документации не равна AUDIT_RETENTION_MAX_DAYS"


class TestNumberEnvHelper:
    """Сам помощник (в процессе теста, без импорта модуля заново)."""

    def test_unset_blank_and_spaces_give_the_default(self, monkeypatch):
        from app.config import _number_env

        monkeypatch.delenv("INFRA_REGISTRY_TEST_NUMBER", raising=False)
        assert _number_env("INFRA_REGISTRY_TEST_NUMBER", 5, int) == 5
        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "  ")
        assert _number_env("INFRA_REGISTRY_TEST_NUMBER", 5, int) == 5

    def test_value_is_cast_and_trimmed(self, monkeypatch):
        from app.config import _number_env

        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", " 2.5 ")
        assert _number_env("INFRA_REGISTRY_TEST_NUMBER", 1.0, float) == 2.5

    def test_value_equal_to_the_minimum_is_accepted(self, monkeypatch):
        from app.config import _number_env

        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "1")
        assert _number_env("INFRA_REGISTRY_TEST_NUMBER", 10, int, minimum=1) == 1

    def test_error_messages_name_the_variable_and_chain_the_cause(self, monkeypatch):
        from app.config import _number_env

        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "1.5")
        with pytest.raises(ValueError, match=r"INFRA_REGISTRY_TEST_NUMBER: ожидается число, получено '1\.5'") as caught:
            _number_env("INFRA_REGISTRY_TEST_NUMBER", 10, int)
        assert isinstance(caught.value.__cause__, ValueError)
        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "0")
        with pytest.raises(ValueError, match="INFRA_REGISTRY_TEST_NUMBER: значение не может быть меньше 1"):
            _number_env("INFRA_REGISTRY_TEST_NUMBER", 10, int, minimum=1)

    def test_optional_variant_keeps_its_behaviour(self, monkeypatch):
        """_optional_number_env — частный случай: пусто → None, отрицательное → ошибка (прежнее поведение, его используют REPORT_MAX_FILES и DB_POOL_*)."""
        from app.config import _optional_number_env

        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "")
        assert _optional_number_env("INFRA_REGISTRY_TEST_NUMBER", int) is None
        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "0")
        assert _optional_number_env("INFRA_REGISTRY_TEST_NUMBER", int) == 0
        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "-1")
        with pytest.raises(ValueError, match="INFRA_REGISTRY_TEST_NUMBER"):
            _optional_number_env("INFRA_REGISTRY_TEST_NUMBER", int)

    def test_value_equal_to_the_maximum_is_accepted_and_above_it_names_the_variable(self, monkeypatch):
        from app.config import _number_env

        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "10")
        assert _number_env("INFRA_REGISTRY_TEST_NUMBER", 1, int, maximum=10) == 10
        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", "11")
        with pytest.raises(ValueError, match="INFRA_REGISTRY_TEST_NUMBER.*больше 10"):
            _number_env("INFRA_REGISTRY_TEST_NUMBER", 1, int, maximum=10)

    @pytest.mark.parametrize("raw", ["inf", "-inf", "nan"])
    def test_non_finite_floats_are_rejected_even_without_bounds(self, monkeypatch, raw):
        from app.config import _number_env

        monkeypatch.setenv("INFRA_REGISTRY_TEST_NUMBER", raw)
        with pytest.raises(ValueError, match="INFRA_REGISTRY_TEST_NUMBER.*конечное число"):
            _number_env("INFRA_REGISTRY_TEST_NUMBER", 1.0, float)
