"""A-13: GET диаграммы и экспорт ничего не пишут в БД; создание и regenerate по-прежнему сохраняют состояния групп.

Раньше `build_graph` при каждом чтении создавал DiagramGroupState для групп выше порога и обновлял device_count, а роутер
коммитил; экспорт ещё и писал last_export_format. Безопасный метод GET менял данные (в том числе от имени viewer), а два
параллельных запроса, оба не нашедшие запись, вставляли одну пару (saved_diagram_id, group_key) → IntegrityError → 500.

Запуск: pytest backend/tests/test_diagram_get_readonly.py -v
PostgreSQL-часть (реальная гонка потоков): INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://... pytest <этот файл>
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.models import Building, DeviceType, DiagramGroupState, PhysicalDevice, SavedDiagram
from app.services import diagram_graph
from app.services.diagram_graph import apply_grouping, build_graph

API = "/api/v1/diagrams"
WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


def _add_devices(db_session, building, count: int) -> list[PhysicalDevice]:
    server_type = db_session.query(DeviceType).filter_by(name="Сервер").one()
    devices = [
        PhysicalDevice(device_type_id=server_type.id, serial_number=f"SN-A13-{building.name}-{i}", building_id=building.id)
        for i in range(count)
    ]
    db_session.add_all(devices)
    db_session.commit()
    return devices


def _diagram_over_threshold_without_state(client, db_session, devices=3, name="A-13"):
    """Диаграмма, у которой группа достигла порога ПОСЛЕ создания: записи состояния у группы нет (создание сохранило бы её)."""
    building = Building(name=f"Здание {name}")
    db_session.add(building)
    db_session.commit()
    _add_devices(db_session, building, devices)
    diagram = client.post(API, json={"name": f"Диаграмма {name}", "group_by": "building", "collapse_threshold": 20}).json()
    row = db_session.get(SavedDiagram, diagram["id"])
    row.collapse_threshold = 2
    db_session.commit()
    assert _states(db_session, diagram["id"]) == []
    return diagram, building


def _states(db_session, diagram_id) -> list[DiagramGroupState]:
    db_session.expire_all()
    return db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram_id).order_by(DiagramGroupState.group_key).all()


def _diagram_row(db_session, diagram_id) -> SavedDiagram:
    db_session.expire_all()
    return db_session.get(SavedDiagram, diagram_id)


def _writes(sql_log) -> list[str]:
    return [statement for statement in sql_log if statement.lstrip().upper().startswith(WRITE_PREFIXES)]


class TestGetDoesNotWrite:
    def test_get_and_exports_leave_the_database_untouched(self, client, db_session, sql_log):
        diagram, building = _diagram_over_threshold_without_state(client, db_session)
        before = _diagram_row(db_session, diagram["id"])
        updated_before, exported_before = before.updated_at, before.last_export_format
        sql_log.clear()

        detail = client.get(f"{API}/{diagram['id']}")
        assert detail.status_code == 200
        assert client.get(f"{API}/{diagram['id']}/export", params={"format": "svg"}).status_code == 200
        assert client.get(f"{API}/{diagram['id']}/export", params={"format": "drawio"}).status_code == 200

        assert _writes(sql_log) == [], "GET и экспорт не должны выполнять INSERT/UPDATE/DELETE"
        assert _states(db_session, diagram["id"]) == []
        after = _diagram_row(db_session, diagram["id"])
        assert after.updated_at == updated_before and after.last_export_format == exported_before
        assert f"group:building:{building.id}" in {n["id"] for n in detail.json()["nodes"]}, "группа выше порога свёрнута и без записи"

    def test_get_does_not_refresh_device_count_of_an_existing_state(self, client, db_session):
        diagram, building = _diagram_over_threshold_without_state(client, db_session)
        key = f"building:{building.id}"
        client.put(f"{API}/{diagram['id']}/groups/{key}", json={"is_collapsed": True})
        state = _states(db_session, diagram["id"])[0]
        count_before, updated_before = state.device_count, state.updated_at
        assert count_before == 0  # PUT создаёт запись с нулевым счётчиком, актуальным его делает regenerate

        assert client.get(f"{API}/{diagram['id']}").status_code == 200
        assert client.get(f"{API}/{diagram['id']}/export", params={"format": "svg"}).status_code == 200

        state = _states(db_session, diagram["id"])[0]
        assert (state.device_count, state.updated_at) == (count_before, updated_before)

    def test_get_result_is_the_same_as_after_the_state_was_saved(self, client, db_session):
        """Содержимое графа не изменилось: то, что GET считает в памяти, regenerate сохраняет, и следующий GET отдаёт то же."""
        diagram, _ = _diagram_over_threshold_without_state(client, db_session)
        computed = client.get(f"{API}/{diagram['id']}").json()
        regenerated = client.post(f"{API}/{diagram['id']}/regenerate").json()
        saved = client.get(f"{API}/{diagram['id']}").json()
        assert computed["nodes"] == regenerated["nodes"] == saved["nodes"]
        assert computed["edges"] == regenerated["edges"] == saved["edges"]
        assert any(node["id"].startswith("group:") for node in saved["nodes"])

    def test_explicitly_expanded_group_stays_expanded_on_get(self, client, db_session):
        diagram, building = _diagram_over_threshold_without_state(client, db_session)
        key = f"building:{building.id}"
        client.put(f"{API}/{diagram['id']}/groups/{key}", json={"is_collapsed": False})
        nodes = client.get(f"{API}/{diagram['id']}").json()["nodes"]
        assert not any(node["id"].startswith("group:") for node in nodes)
        assert len(nodes) == 3

    def test_export_remembers_the_format_only_when_asked(self, client, db_session):
        diagram, _ = _diagram_over_threshold_without_state(client, db_session, devices=1, name="A-13 формат")
        client.get(f"{API}/{diagram['id']}/export", params={"format": "svg"})
        assert client.get(f"{API}/{diagram['id']}").json()["last_export_format"] is None

        client.get(f"{API}/{diagram['id']}/export", params={"format": "svg", "persist_export": "true"})
        assert client.get(f"{API}/{diagram['id']}").json()["last_export_format"] == "svg"

    def test_failed_export_does_not_remember_the_format(self, client, db_session, monkeypatch):
        import app.api.diagrams as diagrams_api

        diagram, _ = _diagram_over_threshold_without_state(client, db_session, devices=1, name="A-13 сбой")

        def broken(_graph):
            raise RuntimeError("сбой сериализации")

        monkeypatch.setitem(diagrams_api.EXPORT_FORMATS, "svg", ("image/svg+xml", broken))
        response = client.get(f"{API}/{diagram['id']}/export", params={"format": "svg", "persist_export": "true"})
        assert response.status_code == 500
        assert _diagram_row(db_session, diagram["id"]).last_export_format is None

    @pytest.mark.postgres_only  # на SQLite фикстуры делят одно соединение между потоками (StaticPool) — параллельность там фиктивна
    def test_parallel_reads_never_return_500(self, client, db_session):
        diagram, _ = _diagram_over_threshold_without_state(client, db_session, name="A-13 параллельно")
        urls = [f"{API}/{diagram['id']}", f"{API}/{diagram['id']}/export?format=svg"] * 6

        with ThreadPoolExecutor(max_workers=6) as pool:
            statuses = list(pool.map(lambda url: client.get(url).status_code, urls))

        assert statuses == [200] * len(urls)
        assert _states(db_session, diagram["id"]) == []


class TestPersistingEntryPointsStillSave:
    def test_create_saves_the_group_state(self, client, db_session):
        building = Building(name="Здание A-13 create")
        db_session.add(building)
        db_session.commit()
        _add_devices(db_session, building, 3)
        diagram = client.post(API, json={"name": "Создание сохраняет", "group_by": "building", "collapse_threshold": 2}).json()
        (state,) = _states(db_session, diagram["id"])
        assert state.group_key == f"building:{building.id}" and state.is_collapsed is True and state.device_count == 3

    def test_regenerate_saves_new_states_and_updates_the_counter(self, client, db_session):
        diagram, building = _diagram_over_threshold_without_state(client, db_session)
        assert client.post(f"{API}/{diagram['id']}/regenerate").status_code == 200
        (state,) = _states(db_session, diagram["id"])
        assert state.is_collapsed is True and state.device_count == 3

        _add_devices(db_session, building, 2)
        assert client.post(f"{API}/{diagram['id']}/regenerate").status_code == 200
        (state,) = _states(db_session, diagram["id"])
        assert state.device_count == 5, "device_count существующей записи обновляется при regenerate"

    def test_regenerate_does_not_reset_a_manually_expanded_group(self, client, db_session):
        diagram, building = _diagram_over_threshold_without_state(client, db_session)
        client.put(f"{API}/{diagram['id']}/groups/building:{building.id}", json={"is_collapsed": False})
        client.post(f"{API}/{diagram['id']}/regenerate")
        (state,) = _states(db_session, diagram["id"])
        assert state.is_collapsed is False and state.device_count == 3


class TestApplyGrouping:
    @pytest.fixture()
    def diagram(self, db_session):
        row = SavedDiagram(name="Диаграмма A-13", scope_filter="{}", group_by="building", collapse_threshold=5)
        db_session.add(row)
        db_session.flush()
        return row

    def test_persist_false_leaves_the_session_clean(self, db_session, diagram):
        existing = DiagramGroupState(saved_diagram_id=diagram.id, group_key="building:old", is_collapsed=False, device_count=1)
        db_session.add(existing)
        db_session.commit()

        result = apply_grouping(db_session, diagram, {"building:old": 9, "building:new": 7, "building:small": 1}, persist=False)

        assert result["building:new"].is_collapsed is True and result["building:new"].device_count == 7
        assert "building:small" not in result
        assert result["building:old"] is existing and existing.device_count == 1, "счётчик существующей записи не меняется"
        assert not db_session.new and not db_session.dirty
        assert result["building:new"] not in db_session
        assert db_session.query(DiagramGroupState).count() == 1

    def test_build_graph_persist_false_writes_nothing(self, client, db_session, diagram):  # client: засевает типы устройств
        building = Building(name="Здание A-13 граф")
        db_session.add(building)
        db_session.commit()
        _add_devices(db_session, building, 6)
        diagram.group_by = "building"
        db_session.commit()
        graph = build_graph(db_session, diagram, persist=False)
        assert [n["id"] for n in graph["nodes"]] == [f"group:building:{building.id}"]
        assert not db_session.new and not db_session.dirty
        db_session.commit()
        assert db_session.query(DiagramGroupState).count() == 0

    def test_persist_true_survives_a_concurrent_insert_of_the_same_group(self, db_session, diagram, monkeypatch):
        """Между чтением «записи нет» и вставкой другой запрос успевает создать ту же запись: раньше — IntegrityError,
        теперь — запись победителя (в том числе её состояние) остаётся, ошибки нет."""
        real_insert = diagram_graph._insert_missing_group_states

        def competitor_wins_first(session, states):
            session.execute(
                DiagramGroupState.__table__.insert().values(
                    id="competitor", saved_diagram_id=diagram.id, group_key="building:x", is_collapsed=False, device_count=99,
                    created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
                )
            )
            real_insert(session, states)

        monkeypatch.setattr(diagram_graph, "_insert_missing_group_states", competitor_wins_first)
        result = apply_grouping(db_session, diagram, {"building:x": 8, "building:y": 6}, persist=True)
        db_session.commit()

        rows = {s.group_key: s for s in db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram.id)}
        assert set(rows) == {"building:x", "building:y"}
        assert rows["building:x"].id == "competitor" and rows["building:x"].is_collapsed is False
        assert result["building:x"].id == "competitor", "результат — запись победителя, а не несохранённая копия"
        assert rows["building:y"].is_collapsed is True and rows["building:y"].device_count == 6


@pytest.mark.postgres_only
def test_postgres_simultaneous_creation_of_the_same_group_state_does_not_fail(db_session):
    """Настоящая гонка потоков на PostgreSQL: все потоки доходят до вставки, не увидев записи, и вставляют одновременно."""
    engine = db_session.get_bind()
    diagram = SavedDiagram(name="Гонка A-13", scope_filter="{}", group_by="building", collapse_threshold=5)
    db_session.add(diagram)
    db_session.commit()
    diagram_id, workers = diagram.id, 6
    barrier = threading.Barrier(workers, timeout=20)

    def hold_until_everyone_is_about_to_insert(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO DIAGRAM_GROUP_STATES"):
            barrier.wait()

    event.listen(engine, "before_cursor_execute", hold_until_everyone_is_about_to_insert)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def regenerate(_):
        with factory() as session:
            saved = session.get(SavedDiagram, diagram_id)
            apply_grouping(session, saved, {"building:race": 9}, persist=True)
            session.commit()
        return "ok"

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(regenerate, range(workers)))
    finally:
        event.remove(engine, "before_cursor_execute", hold_until_everyone_is_about_to_insert)

    assert outcomes == ["ok"] * workers
    db_session.expire_all()
    rows = db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram_id).all()
    assert len(rows) == 1 and rows[0].is_collapsed is True and rows[0].device_count == 9
