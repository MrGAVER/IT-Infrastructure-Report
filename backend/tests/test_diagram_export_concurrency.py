"""
Код-ревью r3, A-06: тяжёлый экспорт диаграмм (.vsdx) не может занять весь пул потоков.

Замер (120 устройств, ~150 подключений, один запрос): .svg — единицы мс, .drawio — до 0,2 с, .vsdx — от 0,5 до 2,5 с (раньше десятки секунд:
библиотека vsdx при каждом копировании фигуры обходила всю страницу, рост был квадратичным; теперь копирование без повторного обхода).
Эндпоинт экспорта синхронный и работает в пуле потоков (по умолчанию ~40): десяток параллельных запросов .vsdx занял бы пул
надолго, и API перестало бы отвечать всем, включая вход. Теперь одновременно выполняется не больше
HEAVY_EXPORT_MAX_CONCURRENT экспортов тяжёлых форматов; лишний запрос сразу получает 503 с Retry-After (как проверка паролей на входе,
см. login._password_hash_slot), а не ждёт в очереди и не держит поток. Лёгкие форматы лимит не затрагивает.

Запуск: pytest backend/tests/test_diagram_export_concurrency.py -v
"""
from __future__ import annotations

import threading

import pytest

from app.api import diagrams as diagrams_module
from app.models import DeviceType, PhysicalDevice


@pytest.fixture
def diagram(client, db_session) -> dict:
    server_type = db_session.query(DeviceType).filter_by(name="Сервер").one()
    db_session.add(PhysicalDevice(device_type_id=server_type.id, serial_number="SN-EXPORT-LIMIT"))
    db_session.commit()
    return client.post("/api/v1/diagrams", json={"name": "Диаграмма лимита экспорта"}).json()


def _export(client, diagram_id: str, fmt: str):
    return client.get(f"/api/v1/diagrams/{diagram_id}/export", params={"format": fmt})


@pytest.fixture
def full_slots(monkeypatch) -> threading.BoundedSemaphore:
    """Все слоты тяжёлого экспорта заняты «чужими» запросами."""
    slots = threading.BoundedSemaphore(diagrams_module.HEAVY_EXPORT_MAX_CONCURRENT)
    for _ in range(diagrams_module.HEAVY_EXPORT_MAX_CONCURRENT):
        assert slots.acquire(blocking=False)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    return slots


# --- Контракт набора форматов --------------------------------------------------------------------------------------------------------
def test_vsdx_is_the_measured_heavy_format_and_the_light_ones_are_not():
    assert diagrams_module.HEAVY_EXPORT_FORMATS == frozenset({"vsdx"})
    assert {"svg", "drawio"}.isdisjoint(diagrams_module.HEAVY_EXPORT_FORMATS)


def test_every_heavy_format_is_a_real_export_format():
    # Переименование формата в EXPORT_FORMATS не должно молча снять с него лимит.
    assert diagrams_module.HEAVY_EXPORT_FORMATS <= set(diagrams_module.EXPORT_FORMATS)


def test_the_limit_is_small_but_not_a_single_lane():
    assert 2 <= diagrams_module.HEAVY_EXPORT_MAX_CONCURRENT <= 4


# --- Поведение эндпоинта ----------------------------------------------------------------------------------------------------------------
def test_a_heavy_export_is_refused_with_503_and_retry_after_when_all_slots_are_busy(client, diagram, full_slots, monkeypatch):
    called = []
    media_type, _ = diagrams_module.EXPORT_FORMATS["vsdx"]
    monkeypatch.setitem(diagrams_module.EXPORT_FORMATS, "vsdx", (media_type, lambda graph: called.append(graph) or b"x"))
    response = _export(client, diagram["id"], "vsdx")
    assert response.status_code == 503
    assert int(response.headers["Retry-After"]) >= 1
    assert "занят" in response.json()["detail"]
    assert called == [], "тяжёлая сериализация не должна начинаться, пока нет свободного слота"


@pytest.mark.parametrize("fmt", ["svg", "drawio"])
def test_light_formats_are_not_affected_by_busy_slots(client, diagram, full_slots, fmt):
    assert _export(client, diagram["id"], fmt).status_code == 200


def test_a_free_slot_lets_the_export_through_and_is_released_afterwards(client, diagram, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    for _ in range(3):  # единственный слот переиспользуется: после каждого ответа он свободен
        assert _export(client, diagram["id"], "vsdx").status_code == 200
    assert slots.acquire(blocking=False)


def test_the_slot_is_released_when_the_export_fails(client, diagram, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    media_type, _ = diagrams_module.EXPORT_FORMATS["vsdx"]

    def broken(graph):
        raise RuntimeError("сбой библиотеки vsdx")

    monkeypatch.setitem(diagrams_module.EXPORT_FORMATS, "vsdx", (media_type, broken))
    assert _export(client, diagram["id"], "vsdx").status_code == 500
    assert slots.acquire(blocking=False), "слот, не освобождённый после сбоя, навсегда уменьшил бы пропускную способность экспорта"


def test_unknown_diagram_and_format_are_answered_before_a_slot_is_needed(client, diagram, full_slots):
    assert _export(client, "does-not-exist", "vsdx").status_code == 404
    assert _export(client, diagram["id"], "pdf").status_code == 422


def test_a_refused_export_does_not_touch_the_database(client, db_session, diagram, full_slots):
    before = db_session.get(diagrams_module.SavedDiagram, diagram["id"]).last_export_format
    response = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "vsdx", "persist_export": "true"})
    assert response.status_code == 503
    db_session.expire_all()
    assert db_session.get(diagrams_module.SavedDiagram, diagram["id"]).last_export_format == before


# --- Сам слот ---------------------------------------------------------------------------------------------------------------------------
def test_slot_is_exclusive_up_to_the_limit_and_then_frees(monkeypatch):
    slots = threading.BoundedSemaphore(2)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    with diagrams_module._heavy_export_slot("vsdx"), diagrams_module._heavy_export_slot("vsdx"):
        with pytest.raises(diagrams_module.HTTPException) as refused:
            with diagrams_module._heavy_export_slot("vsdx"):
                pytest.fail("третий одновременный тяжёлый экспорт при лимите 2 допущен")
        assert refused.value.status_code == 503
    with diagrams_module._heavy_export_slot("vsdx"):
        pass  # после выхода слоты свободны


def test_a_light_format_never_takes_a_slot(monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    with diagrams_module._heavy_export_slot("svg"), diagrams_module._heavy_export_slot("drawio"):
        assert slots.acquire(blocking=False), "лёгкие форматы слотов не занимают"


def test_under_real_concurrency_no_more_than_the_limit_run_at_once(monkeypatch):
    """Пять потоков одновременно просят слот и удерживают его: внутрь попадают ровно HEAVY_EXPORT_MAX_CONCURRENT, остальные получают 503."""
    limit = diagrams_module.HEAVY_EXPORT_MAX_CONCURRENT
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", threading.BoundedSemaphore(limit))
    threads_count = limit + 3
    start = threading.Barrier(threads_count)
    release = threading.Event()
    lock = threading.Lock()
    inside = refused = peak = running = 0
    all_decided = threading.Barrier(threads_count + 1)

    def worker() -> None:
        nonlocal inside, refused, peak, running
        start.wait()
        try:
            with diagrams_module._heavy_export_slot("vsdx"):
                with lock:
                    inside += 1
                    running += 1
                    peak = max(peak, running)
                all_decided.wait(timeout=10)  # удерживаем слот, пока остальные не получат отказ
                release.wait(timeout=10)
                with lock:
                    running -= 1
        except diagrams_module.HTTPException as exc:
            assert exc.status_code == 503
            with lock:
                refused += 1
            all_decided.wait(timeout=10)

    threads = [threading.Thread(target=worker) for _ in range(threads_count)]
    for thread in threads:
        thread.start()
    all_decided.wait(timeout=10)
    release.set()
    for thread in threads:
        thread.join(timeout=10)
    assert (inside, refused, peak) == (limit, threads_count - limit, limit)
