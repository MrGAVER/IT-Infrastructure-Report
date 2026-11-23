"""Тесты файла настроек EXE-версии (infra_registry.toml рядом с EXE) и его чтения лаунчером.

Запуск: pytest backend/tests/test_exe_settings.py -v
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

from app.services import exe_settings
from app.services.exe_settings import (
    DEFAULT_SETTINGS_TEXT,
    SETTINGS_FILENAME,
    ExeSettings,
    SettingsError,
    ensure_settings_file,
    load_settings,
    parse_settings,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _with_clients(line: str) -> str:
    """Файл по умолчанию, в котором строка allowed_clients заменена так, как это сделает администратор."""
    return DEFAULT_SETTINGS_TEXT.replace("allowed_clients = []\n", line + "\n")


# ---------------------------------------------------------------------------
# Значения по умолчанию
# ---------------------------------------------------------------------------
class TestDefaults:
    def test_generated_file_parses_to_the_default_settings(self):
        assert parse_settings(DEFAULT_SETTINGS_TEXT) == ExeSettings()

    def test_default_is_local_only(self):
        settings = parse_settings(DEFAULT_SETTINGS_TEXT)
        assert settings.port == 8000
        assert settings.open_browser is True
        assert settings.allowed_clients == ()
        assert settings.network_access is False
        assert settings.listen_host == "127.0.0.1"

    def test_default_environment_allows_only_loopback_and_keeps_host_list(self):
        env = ExeSettings().environment()
        assert env == {"INFRA_REGISTRY_ALLOWED_CLIENTS": "127.0.0.0/8"}

    def test_empty_file_equals_defaults(self):
        assert parse_settings("") == ExeSettings()

    def test_missing_keys_fall_back_to_defaults(self):
        assert parse_settings("[server]\nport = 9000\n") == ExeSettings(port=9000)


class TestDocumentationExamples:
    """Примеры из комментариев файла должны быть рабочими: администратор копирует их как есть."""

    def _example_lines(self) -> list[str]:
        lines = [m.group(1) for m in re.finditer(r"^#\s+(allowed_clients = \[.+\])(?:\s+#.*)?$", DEFAULT_SETTINGS_TEXT, re.M)]
        assert len(lines) >= 4  # один адрес, несколько адресов, подсеть, подсеть + адреса
        return lines

    def test_every_allowed_clients_example_is_valid(self):
        for line in self._example_lines():
            settings = parse_settings(_with_clients(line))
            assert settings.network_access, line

    def test_documented_subnet_example(self):
        settings = parse_settings(_with_clients('allowed_clients = ["192.168.1.0/24"]'))
        assert settings.allowed_clients == ("192.168.1.0/24",)

    def test_allowed_hosts_example_is_valid(self):
        match = re.search(r"^#\s+(allowed_hosts = \[.+\])$", DEFAULT_SETTINGS_TEXT, re.M)
        assert match
        settings = parse_settings(DEFAULT_SETTINGS_TEXT.replace("allowed_hosts = []\n", match.group(1) + "\n"))
        assert settings.allowed_hosts == ("reestr-pc", "reestr-pc.corp.local")

    def test_file_explains_how_to_grant_access_to_addresses_and_subnets(self):
        for fragment in ("192.168.1.15", "192.168.1.0/24", "netsh advfirewall", "ipconfig"):
            assert fragment in DEFAULT_SETTINGS_TEXT


# ---------------------------------------------------------------------------
# Разбор значений
# ---------------------------------------------------------------------------
class TestParsing:
    def test_clients_with_network_access(self):
        settings = parse_settings(_with_clients('allowed_clients = ["192.168.1.15", "10.0.5.0/24"]'))
        assert settings.allowed_clients == ("192.168.1.15/32", "10.0.5.0/24")
        assert settings.network_access is True
        assert settings.listen_host == "0.0.0.0"
        assert settings.environment()["INFRA_REGISTRY_ALLOWED_CLIENTS"] == "127.0.0.0/8,192.168.1.15/32,10.0.5.0/24"

    def test_loopback_and_duplicates_are_dropped(self):
        settings = parse_settings(_with_clients('allowed_clients = ["127.0.0.1", "192.168.1.15", "192.168.1.15"]'))
        assert settings.allowed_clients == ("192.168.1.15/32",)

    def test_only_loopback_entries_keep_access_local(self):
        settings = parse_settings(_with_clients('allowed_clients = ["127.0.0.1"]'))
        assert settings.network_access is False
        assert settings.listen_host == "127.0.0.1"

    def test_allowed_hosts_extend_the_local_names(self):
        settings = parse_settings(DEFAULT_SETTINGS_TEXT.replace("allowed_hosts = []\n", 'allowed_hosts = ["reestr-pc", "*.corp.local"]\n'))
        assert settings.environment()["INFRA_REGISTRY_ALLOWED_HOSTS"] == "localhost,127.0.0.1,reestr-pc,*.corp.local"

    @pytest.mark.parametrize("port", [1, 8010, 65535])
    def test_valid_ports(self, port):
        assert parse_settings(f"[server]\nport = {port}\n").port == port

    @pytest.mark.parametrize("value", ["0", "65536", "-1", '"8000"', "true", "80.5"])
    def test_invalid_port(self, value):
        with pytest.raises(SettingsError, match=r"\[server\] port"):
            parse_settings(f"[server]\nport = {value}\n")

    def test_open_browser_must_be_boolean(self):
        assert parse_settings("[server]\nopen_browser = false\n").open_browser is False
        with pytest.raises(SettingsError, match="open_browser"):
            parse_settings('[server]\nopen_browser = "false"\n')


class TestValidationErrors:
    def test_unknown_key_is_an_error_not_silently_ignored(self):
        # Опечатка в имени параметра не должна тихо оставлять доступ закрытым (или настройку без силы).
        with pytest.raises(SettingsError, match="allowed_client"):
            parse_settings('[access]\nallowed_client = ["192.168.1.15"]\n')

    def test_unknown_section(self):
        with pytest.raises(SettingsError, match="Неизвестный раздел"):
            parse_settings("[network]\nport = 1\n")

    def test_section_must_be_a_table(self):
        with pytest.raises(SettingsError, match="таблицей"):
            parse_settings("server = 5\n")

    @pytest.mark.parametrize("value", ['"192.168.1.15"', "[1, 2]", '["192.168.1.15", 3]'])
    def test_clients_must_be_a_list_of_strings(self, value):
        with pytest.raises(SettingsError, match="список строк"):
            parse_settings(_with_clients(f"allowed_clients = {value}"))

    def test_invalid_address_names_the_value(self):
        with pytest.raises(SettingsError, match=r"allowed_clients.*192\.168\.1\.999"):
            parse_settings(_with_clients('allowed_clients = ["192.168.1.999"]'))

    def test_ipv6_is_not_supported(self):
        with pytest.raises(SettingsError, match="IPv4"):
            parse_settings(_with_clients('allowed_clients = ["fd00::/8"]'))

    @pytest.mark.parametrize("name", ["reestr-pc:8000", "http://reestr-pc", "reestr pc", "reestr/pc"])
    def test_host_names_must_be_plain_names(self, name):
        with pytest.raises(SettingsError, match="allowed_hosts"):
            parse_settings(f'[access]\nallowed_hosts = ["{name}"]\n')

    def test_ip_address_in_hosts_points_to_allowed_clients(self):
        with pytest.raises(SettingsError, match="allowed_clients"):
            parse_settings('[access]\nallowed_hosts = ["192.168.1.10"]\n')

    def test_broken_toml(self):
        with pytest.raises(SettingsError, match="повреждён"):
            parse_settings("[server\nport = 8000")

    def test_duplicated_key_after_pasting_an_example_without_removing_the_default_line(self):
        text = DEFAULT_SETTINGS_TEXT + 'allowed_clients = ["192.168.1.15"]\n'
        with pytest.raises(SettingsError, match="повреждён"):
            parse_settings(text)


# ---------------------------------------------------------------------------
# Файл на диске
# ---------------------------------------------------------------------------
class TestSettingsFile:
    def test_file_is_created_with_defaults_when_missing(self, tmp_path):
        path = tmp_path / SETTINGS_FILENAME
        assert ensure_settings_file(path) is True
        assert path.is_file()
        assert load_settings(path) == ExeSettings()
        assert path.read_text(encoding="utf-8").replace("\r\n", "\n") == DEFAULT_SETTINGS_TEXT

    def test_created_file_uses_windows_line_endings_for_notepad(self, tmp_path):
        path = tmp_path / SETTINGS_FILENAME
        ensure_settings_file(path)
        raw = path.read_bytes()
        assert b"\r\n" in raw
        assert b"\n" not in raw.replace(b"\r\n", b"")

    def test_existing_file_is_never_overwritten(self, tmp_path):
        path = tmp_path / SETTINGS_FILENAME
        path.write_text("[server]\nport = 9123\n", encoding="utf-8")
        assert ensure_settings_file(path) is False
        assert load_settings(path).port == 9123
        assert path.read_text(encoding="utf-8") == "[server]\nport = 9123\n"

    def test_load_accepts_utf8_bom(self, tmp_path):
        path = tmp_path / SETTINGS_FILENAME
        path.write_bytes(b"\xef\xbb\xbf" + b"[server]\nport = 9001\n")
        assert load_settings(path).port == 9001

    def test_load_rejects_non_utf8_with_a_clear_message(self, tmp_path):
        path = tmp_path / SETTINGS_FILENAME
        path.write_bytes("# комментарий\n".encode("cp1251"))
        with pytest.raises(SettingsError, match="UTF-8"):
            load_settings(path)

    def test_unwritable_directory_raises_oserror_for_the_caller(self, tmp_path):
        with pytest.raises(OSError):
            ensure_settings_file(tmp_path / "missing_dir" / SETTINGS_FILENAME)


# ---------------------------------------------------------------------------
# Лаунчер
# ---------------------------------------------------------------------------
@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    sys.modules.pop("launcher", None)
    module = importlib.import_module("launcher")
    monkeypatch.setattr(module, "app_dir", lambda: tmp_path)
    yield module
    sys.modules.pop("launcher", None)


class TestLauncherSettings:
    def test_first_start_creates_the_file_next_to_the_exe_with_local_only_defaults(self, launcher, tmp_path, capsys):
        settings, path = launcher.load_exe_settings()
        assert path == tmp_path / SETTINGS_FILENAME
        assert path.is_file()
        assert settings == ExeSettings()
        assert "Создан файл настроек" in capsys.readouterr().out

    def test_second_start_reads_the_edited_file_and_does_not_recreate_it(self, launcher, tmp_path, capsys):
        launcher.load_exe_settings()
        capsys.readouterr()  # сообщение первого запуска не нужно
        (tmp_path / SETTINGS_FILENAME).write_text(_with_clients('allowed_clients = ["192.168.1.0/24"]'), encoding="utf-8")
        settings, _ = launcher.load_exe_settings()
        assert settings.allowed_clients == ("192.168.1.0/24",)
        assert "Создан файл настроек" not in capsys.readouterr().out
        assert '"192.168.1.0/24"' in (tmp_path / SETTINGS_FILENAME).read_text(encoding="utf-8")

    def test_invalid_file_is_reported_not_replaced_by_defaults(self, launcher, tmp_path):
        (tmp_path / SETTINGS_FILENAME).write_text('[access]\nallowed_clients = ["oops"]\n', encoding="utf-8")
        with pytest.raises(SettingsError):
            launcher.load_exe_settings()
        # И файл остался как был — лаунчер не «чинит» его сам.
        assert "oops" in (tmp_path / SETTINGS_FILENAME).read_text(encoding="utf-8")

    def test_unwritable_directory_falls_back_to_local_only_defaults(self, launcher, monkeypatch, capsys):
        def deny(_path):
            raise PermissionError("read-only")

        monkeypatch.setattr(exe_settings, "ensure_settings_file", deny)
        settings, _ = launcher.load_exe_settings()
        assert settings == ExeSettings()
        assert "Используются настройки по умолчанию" in capsys.readouterr().out

    def test_fail_exits_with_code_2_and_prints_to_stderr(self, launcher, capsys):
        with pytest.raises(SystemExit) as exc:
            launcher.fail("что-то не так")
        assert exc.value.code == 2
        assert "что-то не так" in capsys.readouterr().err
