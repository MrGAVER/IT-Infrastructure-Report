"""
Код-ревью r3, ИА-01 (уровни 1 и 2): потолок размера диаграммы для .vsdx и кэш готовых экспортов.

Потолок (MAX_VSDX_NODES) проверяется ДО захвата слота тяжёлого экспорта: слишком большая диаграмма получает понятный 422 сразу, а не
занимает слот и не ждёт таймаута. Кэш хранит готовый файл тяжёлого формата под отпечатком самого графа (а не под `updated_at` диаграммы:
граф строится ещё и из устройств и подключений, правка которых `updated_at` диаграммы не меняет — с таким ключом отдавался бы устаревший
файл). Повторное скачивание того же графа не занимает слот и не запускает рендер.

Запуск: pytest backend/tests/test_diagram_export_limits.py -v
"""

from __future__ import annotations

import threading

import pytest

from app.api import diagrams as diagrams_module
from app.models import DeviceType, PhysicalDevice
from app.services.export_cache import ExportCache, graph_fingerprint


def _add_device(db_session, serial: str) -> None:
    server_type = db_session.query(DeviceType).filter_by(name="Сервер").one()
    db_session.add(PhysicalDevice(device_type_id=server_type.id, serial_number=serial))
    db_session.commit()


@pytest.fixture
def diagram(client, db_session) -> dict:
    _add_device(db_session, "SN-EXPORT-CACHE-1")
    return client.post("/api/v1/diagrams", json={"name": "Диаграмма кэша экспорта"}).json()


def _export(client, diagram_id: str, fmt: str):
    return client.get(f"/api/v1/diagrams/{diagram_id}/export", params={"format": fmt})


@pytest.fixture
def counted(monkeypatch) -> list[dict]:
    """Подменяет сериализаторы всех форматов счётчиком вызовов: возвращает список графов, с которыми их вызывали."""
    calls: list[dict] = []
    for fmt, (media_type, _) in list(diagrams_module.EXPORT_FORMATS.items()):
        monkeypatch.setitem(
            diagrams_module.EXPORT_FORMATS, fmt, (media_type, lambda graph, fmt=fmt: calls.append(graph) or f"{fmt}-{len(calls)}".encode())
        )
    return calls


@pytest.fixture
def full_slots(monkeypatch) -> threading.BoundedSemaphore:
    slots = threading.BoundedSemaphore(diagrams_module.HEAVY_EXPORT_MAX_CONCURRENT)
    for _ in range(diagrams_module.HEAVY_EXPORT_MAX_CONCURRENT):
        assert slots.acquire(blocking=False)
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    return slots


# --- Потолок размера (уровень 1)
# -----------------------------------------------------------------------------------------------------------
def test_the_node_ceiling_is_a_sane_positive_number():
    assert 100 <= diagrams_module.MAX_VSDX_NODES <= 5000


def test_a_diagram_above_the_ceiling_is_refused_with_422_and_never_serialized(client, diagram, counted, monkeypatch):
    monkeypatch.setattr(diagrams_module, "MAX_VSDX_NODES", 0)  # в диаграмме один узел — больше потолка
    response = _export(client, diagram["id"], "vsdx")
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "vsdx" in detail.lower() and "1" in detail and "0" in detail  # понятно: формат, сколько узлов, какой максимум
    assert ".svg" in detail and ".drawio" in detail  # и что делать вместо этого
    assert counted == []


def test_the_ceiling_is_checked_before_a_slot_is_taken(client, diagram, counted, full_slots, monkeypatch):
    monkeypatch.setattr(diagrams_module, "MAX_VSDX_NODES", 0)
    assert _export(client, diagram["id"], "vsdx").status_code == 422, (
        "при занятых слотах слишком большая диаграмма должна получить 422, а не 503"
    )


def test_a_diagram_exactly_at_the_ceiling_is_exported(client, diagram, counted, monkeypatch):
    monkeypatch.setattr(diagrams_module, "MAX_VSDX_NODES", 1)
    assert _export(client, diagram["id"], "vsdx").status_code == 200


@pytest.mark.parametrize("fmt", ["svg", "drawio"])
def test_the_ceiling_does_not_apply_to_light_formats(client, diagram, counted, monkeypatch, fmt):
    monkeypatch.setattr(diagrams_module, "MAX_VSDX_NODES", 0)
    assert _export(client, diagram["id"], fmt).status_code == 200


# --- Кэш в эндпоинте (уровень 2)
# -----------------------------------------------------------------------------------------------------------
def test_a_repeated_heavy_export_of_the_same_graph_is_served_from_the_cache(client, diagram, counted):
    first = _export(client, diagram["id"], "vsdx")
    second = _export(client, diagram["id"], "vsdx")
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert len(counted) == 1, "второй экспорт того же графа не должен запускать рендер"


def test_a_cache_hit_does_not_need_a_free_slot(client, diagram, counted, monkeypatch):
    assert _export(client, diagram["id"], "vsdx").status_code == 200
    slots = threading.BoundedSemaphore(1)
    assert slots.acquire(blocking=False)  # единственный слот занят
    monkeypatch.setattr(diagrams_module, "_HEAVY_EXPORT_SLOTS", slots)
    assert _export(client, diagram["id"], "vsdx").status_code == 200, "готовый файл отдаётся без слота"
    assert len(counted) == 1


def test_a_changed_infrastructure_invalidates_the_cache(client, db_session, diagram, counted):
    """Ключ — граф, а не `updated_at` диаграммы: новое устройство меняет граф, и файл должен быть построен заново."""
    assert _export(client, diagram["id"], "vsdx").status_code == 200
    _add_device(db_session, "SN-EXPORT-CACHE-2")
    assert _export(client, diagram["id"], "vsdx").status_code == 200
    assert len(counted) == 2, "после добавления устройства устаревший файл из кэша отдаваться не должен"
    assert len(counted[1]["nodes"]) == len(counted[0]["nodes"]) + 1


def test_light_formats_are_not_cached(client, diagram, counted):
    _export(client, diagram["id"], "svg")
    _export(client, diagram["id"], "svg")
    assert len(counted) == 2


def test_the_filename_comes_from_the_diagram_not_from_the_cache(client, diagram, counted):
    """Кэшируются только байты файла: переименование диаграммы меняет имя скачиваемого файла и при попадании в кэш."""
    first = _export(client, diagram["id"], "vsdx")
    assert client.put(f"/api/v1/diagrams/{diagram['id']}/rename", json={"name": "Новое имя"}).status_code == 200
    second = _export(client, diagram["id"], "vsdx")
    assert len(counted) == 1
    assert first.headers["content-disposition"] != second.headers["content-disposition"]
    assert "Новое имя" not in first.headers["content-disposition"]


def test_a_failed_export_is_not_cached(client, diagram, monkeypatch):
    media_type, _ = diagrams_module.EXPORT_FORMATS["vsdx"]
    attempts = []

    def flaky(graph):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("сбой библиотеки vsdx")
        return b"ok"

    monkeypatch.setitem(diagrams_module.EXPORT_FORMATS, "vsdx", (media_type, flaky))
    assert _export(client, diagram["id"], "vsdx").status_code == 500
    assert _export(client, diagram["id"], "vsdx").status_code == 200
    assert len(attempts) == 2


# --- ExportCache и отпечаток графа
# ----------------------------------------------------------------------------------------------------------
def test_cache_returns_what_was_stored_and_none_for_a_miss():
    cache = ExportCache(max_entries=2)
    assert cache.get("a") is None
    cache.put("a", b"1")
    assert cache.get("a") == b"1"
    assert len(cache) == 1


def test_cache_evicts_the_least_recently_used_entry():
    cache = ExportCache(max_entries=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    assert cache.get("a") == b"1"  # «a» использован недавно, значит, вытесняться должен «b»
    cache.put("c", b"3")
    assert cache.get("b") is None
    assert cache.get("a") == b"1" and cache.get("c") == b"3"


def test_cache_does_not_store_an_entry_above_the_size_limit():
    cache = ExportCache(max_entries=2, max_entry_bytes=3)
    cache.put("small", b"123")
    cache.put("big", b"1234")
    assert cache.get("small") == b"123"
    assert cache.get("big") is None


def test_cache_clear_and_invalid_arguments():
    cache = ExportCache(max_entries=1)
    cache.put("a", b"1")
    cache.clear()
    assert len(cache) == 0
    with pytest.raises(ValueError):
        ExportCache(max_entries=0)
    with pytest.raises(ValueError):
        ExportCache(max_entries=1, max_entry_bytes=0)


def test_graph_fingerprint_ignores_key_order_but_not_content_or_format():
    graph = {"nodes": [{"id": "a", "x": 1, "y": 2}], "edges": []}
    reordered = {"edges": [], "nodes": [{"y": 2, "x": 1, "id": "a"}]}
    assert graph_fingerprint("vsdx", graph) == graph_fingerprint("vsdx", reordered)
    assert graph_fingerprint("vsdx", graph) != graph_fingerprint("svg", graph)
    moved = {"nodes": [{"id": "a", "x": 5, "y": 2}], "edges": []}
    assert graph_fingerprint("vsdx", graph) != graph_fingerprint("vsdx", moved)
