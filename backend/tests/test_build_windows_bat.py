"""A-15: build_windows.bat копирует существующие файлы, проверяет каждое копирование и сообщает верный путь к данным.

Раньше скрипт копировал `README_EXE.md` из корня, которого нет в репозитории, а единственный `if errorlevel 1` стоял после
ДВУХ команд copy и видел результат только второй: сборка без инструкции считалась успешной. Итоговое сообщение
«Данные: %LOCALAPPDATA%\\InfraRegistry» было неверным: база лежит рядом с EXE (или в INFRA_REGISTRY_DATA_DIR).

Тест статический (запустить .bat здесь негде — нет Windows): разбирает скрипт, проверяет наличие копируемых файлов и
соответствие installer/README_EXE.md коду (ключи файла настроек, число копий базы) и README.md.
Запуск: pytest backend/tests/test_build_windows_bat.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.services import exe_settings

ROOT = Path(__file__).resolve().parents[2]
BAT = ROOT / "installer" / "build_windows.bat"
README_EXE = ROOT / "installer" / "README_EXE.md"
README = ROOT / "README.md"
LAUNCHER = ROOT / "launcher.py"
DB_BACKUP = ROOT / "backend" / "app" / "services" / "db_backup.py"

COPY_LINE = re.compile(r"^copy\s+/Y\s+(?P<src>\S+)\s+(?P<dst>\S+)(?P<tail>.*)$", re.IGNORECASE)


def _bat_lines() -> list[str]:
    return BAT.read_text(encoding="utf-8").splitlines()


def _copy_commands() -> list[tuple[int, str, str, str]]:
    found = []
    for index, line in enumerate(_bat_lines()):
        match = COPY_LINE.match(line.strip())
        if match:
            found.append((index, match["src"], match["dst"], match["tail"].strip()))
    return found


def test_the_script_copies_the_instruction_and_the_launcher_script():
    sources = {src.replace("\\", "/") for _, src, _, _ in _copy_commands()}
    assert {"installer/README_EXE.md", "installer/run_infra_registry.bat"} <= sources


@pytest.mark.parametrize("source", [src for _, src, _, _ in _copy_commands()])
def test_every_copied_file_exists_in_the_repository(source):
    """Именно так ошибка и жила: README_EXE.md копировался из корня, где его нет."""
    assert (ROOT / source.replace("\\", "/")).is_file(), f"{source} отсутствует в репозитории"


def test_every_copy_is_checked_on_its_own():
    commands = _copy_commands()
    lines = _bat_lines()
    assert commands
    for index, source, _, tail in commands:
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        checked = tail.replace(" ", "") == "||exit/b1" or next_line.replace(" ", "").lower() == "iferrorlevel1exit/b1"
        assert checked, f"копирование {source} не проверяется: ошибка будет проглочена"


def test_pyinstaller_failure_stops_the_build():
    lines = [line.strip() for line in _bat_lines()]
    position = next(i for i, line in enumerate(lines) if "PyInstaller" in line and not line.lower().startswith("rem"))
    assert lines[position + 1].replace(" ", "").lower() == "iferrorlevel1exit/b1"


def test_final_message_names_the_real_data_location():
    text = BAT.read_text(encoding="utf-8")
    message = next(line for line in text.splitlines() if line.lower().startswith("echo данные"))
    assert "LOCALAPPDATA" not in text
    assert "рядом с InfraRegistry.exe" in message and "INFRA_REGISTRY_DATA_DIR" in message
    launcher = LAUNCHER.read_text(encoding="utf-8")
    assert 'os.getenv("INFRA_REGISTRY_DATA_DIR", str(app_dir()))' in launcher, "сообщение должно соответствовать launcher.data_dir()"
    assert "рядом с исполняемым файлом" in README.read_text(encoding="utf-8")


class TestReadmeExe:
    @pytest.fixture(scope="class")
    @classmethod
    def text(cls) -> str:
        return README_EXE.read_text(encoding="utf-8")

    def test_covers_start_data_backup_and_network_access(self, text):
        for needle in (
            "InfraRegistry.exe",
            "infra_registry.toml",
            "infra_registry.db",
            "reports",
            "INFRA_REGISTRY_DATA_DIR",
            ".bak",
            "allowed_clients",
            "брандмауэр",
            "http://127.0.0.1:8000",
            "--port",
            "--no-browser",
        ):
            assert needle.lower() in text.lower(), f"в инструкции нет «{needle}»"

    def test_documented_settings_exist_and_defaults_match_the_code(self, text):
        documented = set(re.findall(r"`\[(\w+)\] (\w+)`", text))
        known = {(section, key) for section, keys in exe_settings._KNOWN_KEYS.items() for key in keys}
        assert documented == known, f"таблица настроек расходится с кодом: {documented ^ known}"
        assert f"`{exe_settings.DEFAULT_PORT}`" in text

    def test_number_of_kept_backups_matches_the_backup_module(self, text):
        """Копию делает общий модуль app/services/db_backup.py (его же использует docker-entrypoint.sh), а не сам launcher.py."""
        keep = re.search(r"^BACKUPS_TO_KEEP = (\d+)$", DB_BACKUP.read_text(encoding="utf-8"), re.MULTILINE)
        assert keep and f"{keep.group(1)} последних" in text
        assert "infra_registry.pre-" in text

    def test_does_not_send_the_user_to_the_wrong_folder(self, text):
        assert "LOCALAPPDATA" not in text and "AppData" not in text
