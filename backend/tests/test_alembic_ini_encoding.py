"""backend/alembic.ini читается в локальной кодировке системы, а не в UTF-8 (EXE на не-русской Windows).

`alembic.config.Config` читает ini через `configparser`, а `alembic/env.py` — через `logging.config.fileConfig`; ни тот ни другой
не принимает кодировку, поэтому оба берут кодировку системы (locale.getpreferredencoding). На английской Windows это cp1252, и
кириллица в комментариях
ini (UTF-8) давала
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x8f` на первой же миграции: EXE не запускался (нашёл smoke-запуск EXE на
windows-latest). На русской Windows cp1251 такие байты читает, поэтому у разработчиков ошибка не воспроизводилась. Файл должен
быть только ASCII.

Запуск: pytest backend/tests/test_alembic_ini_encoding.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
INI = BACKEND / "alembic.ini"

# Python без UTF-8-режима в локали C кодирует и декодирует файлы как ASCII: тот же отказ, что cp1252 на английской Windows, но
# воспроизводится на Linux.
NARROW_LOCALE = {"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0", "PYTHONIOENCODING": "ascii"}

PROBE = """
import locale, sys
assert locale.getpreferredencoding(False).lower() in ("ansi_x3.4-1968", "ascii", "us-ascii"), locale.getpreferredencoding(False)
from alembic.config import Config
from logging.config import fileConfig
cfg = Config(sys.argv[1])
cfg.set_main_option("script_location", "alembic")
assert cfg.get_main_option("path_separator") == "os"
fileConfig(sys.argv[1], disable_existing_loggers=False)
print("ok")
"""


def test_the_ini_is_ascii_only():
    data = INI.read_bytes()
    bad = [i for i, byte in enumerate(data) if byte > 127]
    assert not bad, f"в alembic.ini не-ASCII байты (первый — смещение {bad[0]}); пишите комментарии латиницей"


def test_alembic_and_logging_read_the_ini_in_a_narrow_locale():
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(NARROW_LOCALE)
    result = subprocess.run([sys.executable, "-c", PROBE, str(INI)], capture_output=True, text=True, env=env, cwd=BACKEND, timeout=60)
    assert result.returncode == 0, result.stderr[-600:]
    assert result.stdout.strip() == "ok"
