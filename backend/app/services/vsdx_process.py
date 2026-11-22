"""Рендер .vsdx в отдельном процессе с таймаутом.

Зачем. Экспорт .vsdx — чисто вычислительная работа (секунды на сотни узлов), а эндпоинт синхронный и идёт в пуле потоков. В потоке
такую работу нельзя ни прервать, ни ограничить по времени: слот тяжёлого экспорта (api/diagrams.py) освобождается только когда
рендер сам
закончится — хоть через минуты, хоть после того, как клиент давно оборвал соединение. К тому же рендер делит GIL с обработкой
остальных запросов. В дочернем
процессе рендер можно убить по таймауту (слот освобождается, процесс исчезает) и он не отнимает время у потоков сервера.

Как устроено. Один процесс на один экспорт, запуск `spawn` (не `fork`: сервер многопоточный, fork из многопоточного процесса может
заблокироваться на чужой блокировке и на Windows недоступен). Граф уходит в процесс аргументом, готовый файл возвращается по каналу `Pipe`
(родитель сначала ждёт данные с таймаутом, потом читает — отправитель не зависает на заполненном канале). Процесс создаётся демоном:
остановка сервера не оставляет рендеров-сирот.

Шум в stdout. Библиотека vsdx печатает отладочные строки прямо в stdout (≈13 на узел и ещё столько же на каждую засечку порта — на
1000 узлов более ста тысяч строк на каждый экспорт). Подавить это в потоке сервера нельзя: `contextlib.redirect_stdout` подменяет
`sys.stdout` у
ВСЕГО процесса, то есть заглушил бы и чужие потоки. В дочернем процессе подмена безопасна: `_render_worker` перенаправляет stdout
в «никуда»
(os.devnull, а не StringIO — тот копил бы эти сотни тысяч строк в памяти).

Windows-EXE. Для запуска дочернего процесса из замороженного приложения PyInstaller `launcher.py` обязан вызвать
`multiprocessing.freeze_support()` первым делом под `if __name__ == "__main__"` — иначе каждый дочерний процесс запустил бы ещё одну копию
приложения (тест test_vsdx_process.py проверяет, что вызов на месте).

Пример: `data = export_vsdx_isolated(graph)`; при превышении времени — `VsdxRenderTimeout`, при сбое рендера — `VsdxRenderError` с
traceback процесса.
"""

from __future__ import annotations

import contextlib
import multiprocessing
import os
import traceback
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

VSDX_RENDER_TIMEOUT_SECONDS = 60.0  # ≈3 замеренных для 1000 узлов (MAX_VSDX_NODES, api/diagrams.py): запас на медленную машину
_STOP_GRACE_SECONDS = 5.0  # сколько ждать, пока процесс завершится сам или после terminate(), прежде чем убивать принудительно


class VsdxRenderTimeout(Exception):
    """Рендер .vsdx не уложился во время; процесс остановлен."""


class VsdxRenderError(Exception):
    """Рендер .vsdx завершился сбоем; текст — traceback из дочернего процесса (или причина, по которой результата нет)."""


def _render_worker(connection: Connection, graph: dict) -> None:
    """Тело дочернего процесса: рендерит граф и отправляет `("ok", байты)` или `("error", traceback)`. stdout процесса глушится."""
    from .diagram_export import export_vsdx  # импорт здесь: дочерний процесс тянет только пакет экспорта, а не весь модуль-родитель

    try:
        with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink):
            data = export_vsdx(graph)
        connection.send(("ok", data))
    except Exception:
        connection.send(("error", traceback.format_exc()))
    finally:
        connection.close()


def _stop(process: BaseProcess) -> None:
    """Гарантирует, что процесса больше нет: даёт закончиться самому, затем terminate(), затем kill()."""
    process.join(_STOP_GRACE_SECONDS)
    if process.is_alive():
        process.terminate()
        process.join(_STOP_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
        process.join()


def export_vsdx_isolated(graph: dict, *, timeout: float | None = None) -> bytes:
    """Готовый .vsdx для графа, отрисованный в дочернем процессе; `timeout` по умолчанию — VSDX_RENDER_TIMEOUT_SECONDS (читается
    при вызове)."""
    limit = VSDX_RENDER_TIMEOUT_SECONDS if timeout is None else timeout
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_render_worker, args=(sender, graph), name="vsdx-render", daemon=True)
    try:
        process.start()
    except Exception:
        receiver.close()
        sender.close()
        raise
    sender.close()  # у родителя остаётся только читающий конец: если процесс умрёт, recv() получит EOF, а не зависнет
    try:
        if not receiver.poll(limit):
            process.kill()  # не ждём вежливо: рендер уже просрочен
            raise VsdxRenderTimeout(f"рендер .vsdx не уложился в {limit:g} с")
        try:
            status, payload = receiver.recv()
        except EOFError:
            process.join(_STOP_GRACE_SECONDS)
            raise VsdxRenderError(f"процесс рендера .vsdx завершился без результата (код выхода {process.exitcode})") from None
    finally:
        receiver.close()
        _stop(process)
    if status != "ok":
        raise VsdxRenderError(payload)
    return payload
