"""Вывод launcher при перенаправлении в файл или канал (EXE не должен падать на кириллице).

Все сообщения launcher.py русские. Если вывод не в консоль (`InfraRegistry.exe > log.txt`, служба, планировщик задач, CI), Python на Windows берёт
кодировку ANSI системы: на английской Windows это cp1252, и `print("Создан файл настроек…")` падает с UnicodeEncodeError — EXE не запускался вовсе
(нашёл smoke-запуск EXE в CI на windows-latest: traceback из `load_exe_settings`). На русской Windows ANSI-кодировка cp1251 кириллицу умеет, поэтому
у разработчиков ошибка не воспроизводилась.

Запуск: pytest backend/tests/test_launcher_stdio.py -v  (launcher.py лежит в корне репозитория — тест добавляет его в sys.path)
"""

from __future__ import annotations

import importlib
import inspect
import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MESSAGE = "Создан файл настроек: C:\\данные\\infra_registry.toml"


@pytest.fixture()
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    sys.modules.pop("launcher", None)
    module = importlib.import_module("launcher")
    yield module
    sys.modules.pop("launcher", None)


class _Console(io.TextIOWrapper):
    """Поток, который выдаёт себя за консоль."""

    def isatty(self) -> bool:
        return True


def _stream(encoding: str, cls=io.TextIOWrapper) -> tuple[io.BytesIO, io.TextIOWrapper]:
    raw = io.BytesIO()
    return raw, cls(raw, encoding=encoding, write_through=True)


def test_the_redirect_really_crashes_without_the_fix():
    """Условие ошибки: кириллица в файл с кодировкой cp1252."""
    _, stream = _stream("cp1252")
    with pytest.raises(UnicodeEncodeError):
        print(MESSAGE, file=stream)


def test_cyrillic_survives_a_redirect_to_a_cp1252_file(launcher, monkeypatch):
    raw, out = _stream("cp1252")
    _, err = _stream("cp1252")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    launcher.configure_stdio()
    print(MESSAGE)
    print(MESSAGE, file=sys.stderr)

    assert raw.getvalue().decode("utf-8") == MESSAGE + "\n", "в файл и канал выводится UTF-8, а не «?» вместо букв"


def test_a_console_keeps_its_encoding_but_never_raises(launcher, monkeypatch):
    raw, console = _stream("cp1252", _Console)
    monkeypatch.setattr(sys, "stdout", console)
    monkeypatch.setattr(sys, "stderr", console)

    launcher.configure_stdio()
    print(MESSAGE)

    assert console.encoding == "cp1252", "кодировку консоли не трогаем"
    assert raw.getvalue().decode("cp1252").startswith("????"), "то, что консоль показать не может, заменяется, а не роняет запуск"


@pytest.mark.parametrize("missing", ["stdout", "stderr", "both"])
def test_missing_streams_are_ignored(launcher, monkeypatch, missing):
    """В сборке без консоли (`console=False`) sys.stdout/sys.stderr равны None."""
    if missing in ("stdout", "both"):
        monkeypatch.setattr(sys, "stdout", None)
    if missing in ("stderr", "both"):
        monkeypatch.setattr(sys, "stderr", None)
    launcher.configure_stdio()


def test_main_configures_the_streams_before_it_prints_anything(launcher):
    source = inspect.getsource(launcher.main)
    assert "configure_stdio()" in source
    assert source.index("configure_stdio()") < source.index("load_exe_settings()"), "первое сообщение печатает load_exe_settings (создание файла настроек)"
