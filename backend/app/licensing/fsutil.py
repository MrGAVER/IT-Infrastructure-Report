"""Атомарная запись файла: либо видна новая версия целиком, либо старая — обрыв записи не оставляет битый файл."""
from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str, *, private: bool = False) -> None:
    """Записать ``text`` во временный файл рядом и подменить им ``path`` (os.replace атомарна и на Windows).
    ``private`` — права 0600 (на Windows chmod лишь снимает флаг «только чтение»; ACL каталога данных остаются в силе)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if private:
            with contextlib.suppress(OSError):
                os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
