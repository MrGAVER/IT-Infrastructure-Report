"""
A-06 (код-ревью main @ b375f58): управление дочерним процессом в services/vsdx_process.py на поддельном процессе и канале.

Настоящий процесс покрытием не виден (тело `_render_worker` выполняется в другом процессе), а аварийные ветви — «процесс не завершился сам», «процесс не запустился»,
«процесс умер без результата» — реальным запуском не воспроизвести надёжно, поэтому здесь `multiprocessing.get_context("spawn")` подменён: проверяется порядок действий —
join → terminate → join → kill → join, закрытие обоих концов канала при сбое запуска, текст ошибки с кодом выхода, kill по таймауту.

Запуск: pytest backend/tests/test_vsdx_process_control_flow.py -v
"""

from __future__ import annotations

import pytest

from app.services import vsdx_process
from app.services.vsdx_process import VsdxRenderError, VsdxRenderTimeout, export_vsdx_isolated

GRACE = vsdx_process._STOP_GRACE_SECONDS


class _FakeProcess:
    """Процесс, у которого is_alive() отвечает по заранее заданной очереди; все вызовы записываются."""

    def __init__(self, alive=(), *, exitcode=None, start_error: Exception | None = None) -> None:
        self._alive = list(alive)
        self.exitcode = exitcode
        self.start_error = start_error
        self.calls: list[tuple] = []

    def start(self) -> None:
        self.calls.append(("start",))
        if self.start_error:
            raise self.start_error

    def join(self, timeout=None) -> None:
        self.calls.append(("join", timeout))

    def is_alive(self) -> bool:
        return self._alive.pop(0) if self._alive else False

    def terminate(self) -> None:
        self.calls.append(("terminate",))

    def kill(self) -> None:
        self.calls.append(("kill",))


class _FakeEnd:
    """Конец канала: poll/recv по сценарию, close запоминается."""

    def __init__(self, *, ready=True, message=None, error: Exception | None = None) -> None:
        self.ready, self.message, self.error = ready, message, error
        self.closed = False
        self.polled_with: list[float] = []

    def poll(self, timeout) -> bool:
        self.polled_with.append(timeout)
        return self.ready

    def recv(self):
        if self.error:
            raise self.error
        return self.message

    def close(self) -> None:
        self.closed = True


class _FakeContext:
    def __init__(self, process: _FakeProcess, receiver: _FakeEnd, sender: _FakeEnd) -> None:
        self.process, self.pipe = process, (receiver, sender)
        self.process_kwargs: dict = {}

    def Pipe(self, duplex=True):  # noqa: N802 — имя метода multiprocessing
        assert duplex is False, "канал односторонний: родитель только читает"
        return self.pipe

    def Process(self, **kwargs):  # noqa: N802
        self.process_kwargs = kwargs
        return self.process


@pytest.fixture()
def wire(monkeypatch):
    def install(process: _FakeProcess, receiver: _FakeEnd, sender: _FakeEnd | None = None) -> _FakeContext:
        context = _FakeContext(process, receiver, sender or _FakeEnd())
        monkeypatch.setattr(vsdx_process.multiprocessing, "get_context", lambda method: context if method == "spawn" else pytest.fail(f"запуск не через spawn: {method}"))
        return context

    return install


class TestStop:
    def test_process_that_ends_by_itself_is_only_joined(self):
        process = _FakeProcess(alive=[False])

        vsdx_process._stop(process)

        assert process.calls == [("join", GRACE)]

    def test_process_that_does_not_end_is_terminated(self):
        process = _FakeProcess(alive=[True, False])

        vsdx_process._stop(process)

        assert process.calls == [("join", GRACE), ("terminate",), ("join", GRACE)]

    def test_process_that_ignores_terminate_is_killed_and_awaited_without_a_limit(self):
        process = _FakeProcess(alive=[True, True])

        vsdx_process._stop(process)

        assert process.calls == [("join", GRACE), ("terminate",), ("join", GRACE), ("kill",), ("join", None)]


class TestExportIsolated:
    GRAPH = {"nodes": [], "edges": []}

    def test_failed_start_closes_both_pipe_ends_and_passes_the_error_on(self, wire):
        process, receiver, sender = _FakeProcess(start_error=OSError("не хватает памяти")), _FakeEnd(), _FakeEnd()
        wire(process, receiver, sender)

        with pytest.raises(OSError, match="не хватает памяти"):
            export_vsdx_isolated(self.GRAPH, timeout=1)

        assert receiver.closed and sender.closed, "ни один конец канала не остался открытым"
        assert process.calls == [("start",)], "процесса нет — останавливать нечего"

    def test_process_that_died_without_a_result_gives_an_error_with_its_exit_code(self, wire):
        process, receiver, sender = _FakeProcess(alive=[False], exitcode=-9), _FakeEnd(error=EOFError()), _FakeEnd()
        wire(process, receiver, sender)

        with pytest.raises(VsdxRenderError) as caught:
            export_vsdx_isolated(self.GRAPH, timeout=1)

        assert str(caught.value) == "процесс рендера .vsdx завершился без результата (код выхода -9)"
        assert caught.value.__cause__ is None, "EOFError не тянется в цепочку исключений: причина уже в тексте"
        assert receiver.closed and sender.closed
        assert process.calls[:2] == [("start",), ("join", GRACE)], "родитель дожидается кода выхода до формирования текста"

    def test_slow_render_is_killed_and_reported_as_a_timeout(self, wire):
        process, receiver = _FakeProcess(alive=[False]), _FakeEnd(ready=False)
        wire(process, receiver)

        with pytest.raises(VsdxRenderTimeout, match=r"рендер \.vsdx не уложился в 0\.5 с"):
            export_vsdx_isolated(self.GRAPH, timeout=0.5)

        assert receiver.polled_with == [0.5]
        assert ("kill",) in process.calls, "просроченный рендер убивается сразу, без вежливого ожидания"
        assert receiver.closed

    def test_render_error_from_the_child_is_raised_with_its_traceback(self, wire):
        process, receiver = _FakeProcess(alive=[False]), _FakeEnd(message=("error", "Traceback: KeyError 'label'"))
        wire(process, receiver)

        with pytest.raises(VsdxRenderError, match="KeyError 'label'"):
            export_vsdx_isolated(self.GRAPH, timeout=1)

    def test_successful_render_returns_the_bytes_and_launches_a_daemon_with_the_graph(self, wire):
        process, receiver, sender = _FakeProcess(alive=[False]), _FakeEnd(message=("ok", b"PK-vsdx")), _FakeEnd()
        context = wire(process, receiver, sender)

        data = export_vsdx_isolated(self.GRAPH, timeout=1)

        assert data == b"PK-vsdx"
        assert sender.closed, "у родителя остаётся только читающий конец канала"
        assert context.process_kwargs["daemon"] is True and context.process_kwargs["name"] == "vsdx-render"
        assert context.process_kwargs["args"] == (sender, self.GRAPH)
        assert context.process_kwargs["target"] is vsdx_process._render_worker

    def test_default_timeout_is_taken_when_none_is_given(self, wire, monkeypatch):
        monkeypatch.setattr(vsdx_process, "VSDX_RENDER_TIMEOUT_SECONDS", 3.0)
        process, receiver = _FakeProcess(alive=[False]), _FakeEnd(message=("ok", b"PK"))
        wire(process, receiver)

        export_vsdx_isolated(self.GRAPH)

        assert receiver.polled_with == [3.0]
