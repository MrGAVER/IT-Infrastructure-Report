"""
Код-ревью r3, ИА-01 (уровень 3) и ИА-07: рендер .vsdx в дочернем процессе с таймаутом и без шума в stdout.

Проверяется: файл из дочернего процесса — настоящий .vsdx; по таймауту процесс убит, а не брошен работать; сбой рендера доходит до родителя
с traceback; stdout процесса пуст (библиотека vsdx печатает отладочные строки на каждый узел); эндпоинт отвечает 504 и освобождает слот;
launcher.py вызывает freeze_support() (без него замороженный EXE на Windows запускал бы копию приложения на каждый рендер).

Запуск: pytest backend/tests/test_vsdx_process.py -v
"""

from __future__ import annotations

import ast
import io
import multiprocessing
import threading
import time
import zipfile
from pathlib import Path

import pytest
from pyinstaller_spec_eval import evaluate_spec

from app.api import diagrams as diagrams_module
from app.models import DeviceType, PhysicalDevice
from app.services import vsdx_process
from app.services.diagram_export import export_vsdx
from app.services.vsdx_process import VsdxRenderError, VsdxRenderTimeout, export_vsdx_isolated

ROOT = Path(__file__).resolve().parents[2]


def _graph(nodes: int = 2) -> dict:
    return {
        "nodes": [
            {
                "id": f"d{i}",
                "type": "device",
                "label": f"sw-{i}",
                "x": i * 300,
                "y": 0,
                "icon": {"mode": "generated", "shape": "switch", "color": "#4f7cff", "glyph": '<rect x="2" y="6" width="20" height="9"/>', "port_ticks": 4},
            }
            for i in range(nodes)
        ],
        "edges": [],
    }


def _render_children() -> list:
    return [p for p in multiprocessing.active_children() if p.name == "vsdx-render"]


class _FakeConnection:
    def __init__(self) -> None:
        self.sent: list = []
        self.closed = False

    def send(self, message) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True


# --- Результат дочернего процесса -----------------------------------------------------------------------------------------------------------
def test_the_isolated_render_returns_a_real_vsdx_package():
    data = export_vsdx_isolated(_graph(), timeout=120)
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        page = package.read("visio/pages/page1.xml").decode("utf-8")
    assert "sw-0" in page and "sw-1" in page


def test_the_isolated_render_matches_the_in_process_one_in_page_content():
    graph = _graph(3)
    with zipfile.ZipFile(io.BytesIO(export_vsdx_isolated(graph, timeout=120))) as isolated, zipfile.ZipFile(io.BytesIO(export_vsdx(graph))) as direct:
        assert sorted(isolated.namelist()) == sorted(direct.namelist())
        assert isolated.read("visio/pages/page1.xml") == direct.read("visio/pages/page1.xml")


def test_no_render_process_is_left_behind_after_a_successful_export():
    export_vsdx_isolated(_graph(1), timeout=120)
    assert _render_children() == []


# --- Таймаут и сбои --------------------------------------------------------------------------------------------------------------------------
def test_a_render_that_is_too_slow_raises_a_timeout_and_the_process_is_killed():
    # Запуск spawn + импорт библиотек заведомо дольше 10 мс — рендер не успевает.
    started = time.monotonic()
    with pytest.raises(VsdxRenderTimeout, match="не уложился"):
        export_vsdx_isolated(_graph(2000), timeout=0.01)  # 2000 узлов рендерятся заметно дольше ожидания в _stop (5 с)
    assert time.monotonic() - started < vsdx_process._STOP_GRACE_SECONDS, "просроченный рендер убивается сразу, а не после вежливого ожидания"
    assert _render_children() == [], "просроченный процесс должен быть остановлен, а не оставлен работать"


def test_the_default_timeout_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(vsdx_process, "VSDX_RENDER_TIMEOUT_SECONDS", 0.01)
    with pytest.raises(VsdxRenderTimeout):
        export_vsdx_isolated(_graph())
    assert _render_children() == []


def test_a_render_failure_reaches_the_parent_with_the_child_traceback():
    broken = {"nodes": [{"id": "x"}], "edges": []}  # у узла нет обязательных полей
    with pytest.raises(VsdxRenderError) as failure:
        export_vsdx_isolated(broken, timeout=120)
    assert "Traceback" in str(failure.value) and "KeyError" in str(failure.value)
    assert _render_children() == []


def test_the_default_timeout_leaves_a_safe_margin_over_the_measured_worst_case():
    """Замер: ≈19 мс на узел (1000 узлов — около 19 с). Таймаут обязан быть минимум вдвое больше времени рендера диаграммы на потолке
    MAX_VSDX_NODES, иначе допустимая по размеру диаграмма на машине чуть медленнее замерной прерывалась бы."""
    assert diagrams_module.MAX_VSDX_NODES * 0.019 * 2 <= vsdx_process.VSDX_RENDER_TIMEOUT_SECONDS


# --- ИА-07: stdout ---------------------------------------------------------------------------------------------------------------------------
def test_the_vsdx_library_is_noisy_when_called_directly(capsys):
    """Контроль для теста ниже: если библиотека перестала печатать, тот тест проходил бы вхолостую — пересмотрите ИА-07."""
    export_vsdx(_graph())
    assert capsys.readouterr().out.strip() != ""


def test_the_worker_silences_stdout_and_sends_the_file(capsys):
    connection = _FakeConnection()
    vsdx_process._render_worker(connection, _graph())
    assert capsys.readouterr().out == ""
    ((status, payload),) = connection.sent
    assert status == "ok" and payload[:2] == b"PK"
    assert connection.closed


def test_the_worker_reports_a_failure_instead_of_dying_silently():
    connection = _FakeConnection()
    vsdx_process._render_worker(connection, {"nodes": [{"id": "x"}], "edges": []})
    ((status, payload),) = connection.sent
    assert status == "error" and "KeyError" in payload
    assert connection.closed


def test_an_isolated_export_prints_nothing_to_the_server_stdout(capfd):
    export_vsdx_isolated(_graph(), timeout=120)
    assert capfd.readouterr().out == ""


# --- Эндпоинт --------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def diagram(client, db_session) -> dict:
    server_type = db_session.query(DeviceType).filter_by(name="Сервер").one()
    db_session.add(PhysicalDevice(device_type_id=server_type.id, serial_number="SN-EXPORT-TIMEOUT"))
    db_session.commit()
    return client.post("/api/v1/diagrams", json={"name": "Диаграмма таймаута"}).json()


def test_the_endpoint_answers_504_on_a_render_timeout_and_frees_the_slot(client, diagram, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    monkeypatch.setattr(vsdx_process, "VSDX_RENDER_TIMEOUT_SECONDS", 0.01)
    response = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "vsdx"})
    assert response.status_code == 504
    assert "прервано" in response.json()["detail"] and ".svg" in response.json()["detail"]
    assert slots.acquire(blocking=False), "слот, не освобождённый после таймаута, навсегда уменьшил бы пропускную способность экспорта"
    assert _render_children() == []


def test_a_timed_out_export_is_not_cached(client, diagram, monkeypatch):
    monkeypatch.setattr(vsdx_process, "VSDX_RENDER_TIMEOUT_SECONDS", 0.01)
    assert client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "vsdx"}).status_code == 504
    monkeypatch.setattr(vsdx_process, "VSDX_RENDER_TIMEOUT_SECONDS", 120.0)  # следующая попытка — с нормальным таймаутом
    assert client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "vsdx"}).status_code == 200


# --- Windows-EXE -----------------------------------------------------------------------------------------------------------------------------
def test_launcher_calls_freeze_support_before_main():
    """Рендер в дочернем процессе (spawn) в замороженном EXE работает только при freeze_support() первым делом под __main__-охраной."""
    tree = ast.parse((ROOT / "launcher.py").read_text(encoding="utf-8"))
    guard = next(
        node for node in tree.body if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and getattr(node.test.left, "id", None) == "__name__"
    )
    calls = [ast.unparse(stmt.value.func) for stmt in guard.body if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)]
    assert calls[:2] == ["multiprocessing.freeze_support", "main"], f"вызовы под __main__: {calls}"


def test_the_render_module_is_picked_up_by_the_pyinstaller_spec_automatically(monkeypatch):
    """Спецификация находит модули пакета `app` сама, поэтому новый модуль не нужно перечислять в hiddenimports вручную."""
    assert "app.services.vsdx_process" in evaluate_spec(monkeypatch)["hiddenimports"]
