"""Кэш готовых файлов тяжёлых экспортов диаграмм.

Зачем. Экспорт .vsdx — самый тяжёлый формат (секунды на сотни узлов), а скачивают его, как правило, повторно: тот же файл ещё раз, тот же
файл коллеге. Без кэша каждое такое скачивание занимает один из двух слотов тяжёлого экспорта (api/diagrams.py) и заново строит файл.

Ключ — отпечаток самого графа (`graph_fingerprint`), а НЕ пара (id диаграммы, `updated_at`): граф строится ещё и из устройств, портов и
подключений, правка которых `updated_at` диаграммы не меняет — с таким ключом пользователь получал бы устаревший файл. Отпечаток считается
по уже построенному графу (он дешёвый по сравнению с рендером), поэтому он точен по построению: тот же граф — тот же файл, любое изменение
узла, связи или раскладки — другой ключ, и кэш просто не попадает. Инвалидировать вручную нечего.

Чего кэш НЕ делает: не хранит ничего, кроме байтов готового файла (имя файла берётся из диаграммы при каждом ответе); не общий между процессами
(у каждого воркера свой, промах — просто рендер); вытесняет по давности использования (LRU), срока жизни нет — ключ содержит всё содержимое.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict

DEFAULT_MAX_ENTRIES = 16
DEFAULT_MAX_ENTRY_BYTES = 8 * 1024 * 1024  # файл крупнее не кэшируется: пара таких записей не должна вытеснить всё остальное и раздуть память


def graph_fingerprint(export_format: str, graph: dict) -> str:
    """Стабильный ключ кэша: тот же формат и тот же граф (порядок ключей словарей не важен) дают тот же ключ.

    Пример: `graph_fingerprint("vsdx", {"nodes": [], "edges": []})` — 64 шестнадцатеричных символа.
    """
    payload = json.dumps(graph, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{export_format}\0{payload}".encode("utf-8")).hexdigest()


class ExportCache:
    """Потокобезопасный LRU-кэш готовых файлов: `put(key, bytes)` и `get(key) -> bytes | None`."""

    def __init__(self, *, max_entries: int = DEFAULT_MAX_ENTRIES, max_entry_bytes: int = DEFAULT_MAX_ENTRY_BYTES) -> None:
        if max_entries < 1 or max_entry_bytes < 1:
            raise ValueError("max_entries и max_entry_bytes должны быть положительными")
        self._max_entries = max_entries
        self._max_entry_bytes = max_entry_bytes
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, bytes] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            data = self._entries.get(key)
            if data is not None:
                self._entries.move_to_end(key)
            return data

    def put(self, key: str, data: bytes) -> None:
        if len(data) > self._max_entry_bytes:
            return
        with self._lock:
            self._entries[key] = data
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


export_cache = ExportCache()
