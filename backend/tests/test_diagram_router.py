"""
Тесты на backend/app/api/diagrams.py — раздел 7 ТЗ (эндпоинты) и раздел 13 (план тестирования):
"Удаление DiagramIcon, на который есть ссылка, блокируется (409)"; "DELETE /diagrams/{id}
каскадно удаляет diagram_layouts/diagram_group_states".

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_router.py -v
"""
from __future__ import annotations

from app.models import Building, DeviceInterface, DeviceType, PhysicalDevice


def _seed_device(db_session, building=None) -> PhysicalDevice:
    server_type = db_session.query(DeviceType).filter_by(name="Сервер").one()
    device = PhysicalDevice(device_type_id=server_type.id, serial_number="SN-ROUTER-1", building_id=building.id if building else None)
    db_session.add(device)
    db_session.commit()
    return device


def test_create_diagram_generates_graph_and_saves_layout(client, db_session):
    building = Building(name="Здание Р1")
    db_session.add(building)
    db_session.commit()
    device = _seed_device(db_session, building)

    r = client.post("/api/v1/diagrams", json={"name": "Диаграмма 1", "group_by": "building", "collapse_threshold": 20})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Диаграмма 1"
    assert body["collapse_threshold"] == 20

    r2 = client.get(f"/api/v1/diagrams/{body['id']}")
    assert r2.status_code == 200
    detail = r2.json()
    node_ids = {n["id"] for n in detail["nodes"]}
    assert device.id in node_ids
    node = next(n for n in detail["nodes"] if n["id"] == device.id)
    assert "x" in node and "y" in node


def test_create_diagram_rejects_duplicate_name(client):
    payload = {"name": "Уникальная диаграмма", "group_by": "building"}
    assert client.post("/api/v1/diagrams", json=payload).status_code == 201
    r = client.post("/api/v1/diagrams", json=payload)
    assert r.status_code == 409


def test_create_diagram_validates_group_by(client):
    r = client.post("/api/v1/diagrams", json={"name": "Плохая диаграмма", "group_by": "не измерение"})
    assert r.status_code == 422


def test_create_diagram_validates_collapse_threshold(client):
    r = client.post("/api/v1/diagrams", json={"name": "Плохой порог", "collapse_threshold": 0})
    assert r.status_code == 422
    r2 = client.post("/api/v1/diagrams", json={"name": "Плохой порог 2", "collapse_threshold": "20"})
    assert r2.status_code == 422


def test_get_diagram_not_found(client):
    assert client.get("/api/v1/diagrams/does-not-exist").status_code == 404


def test_update_layout_persists_positions(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма раскладки"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": {"some-id": {"x": 42, "y": 99}}, "viewport": {"zoom": 1.5}})
    assert r.status_code == 200
    detail = client.get(f"/api/v1/diagrams/{diagram['id']}").json()
    assert detail["viewport"] == {"zoom": 1.5}


def test_update_layout_rejects_non_object_positions(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма raw"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": "not-an-object"})
    assert r.status_code == 422


def test_update_group_state_creates_and_updates(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма групп"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:x", json={"is_collapsed": True, "custom_threshold": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["is_collapsed"] is True
    assert body["custom_threshold"] == 3

    r2 = client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:x", json={"is_collapsed": False})
    assert r2.json()["is_collapsed"] is False
    assert r2.json()["custom_threshold"] == 3  # не тронуто, раз не передано в этом запросе


def test_update_group_state_validates_custom_threshold(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма групп 2"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:y", json={"custom_threshold": 0})
    assert r.status_code == 422


def test_regenerate_preserves_manual_layout_and_group_state(client, db_session):
    building = Building(name="Здание Р2")
    db_session.add(building)
    db_session.commit()
    device = _seed_device(db_session, building)

    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма regenerate", "group_by": "building"}).json()
    client.put(f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": {device.id: {"x": 555, "y": 777}}})
    client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:manual", json={"is_collapsed": True})

    r = client.post(f"/api/v1/diagrams/{diagram['id']}/regenerate")
    assert r.status_code == 200
    node = next(n for n in r.json()["nodes"] if n["id"] == device.id)
    assert node["x"] == 555 and node["y"] == 777  # ручная позиция не перезаписана

    group_state = client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:manual", json={}).json()
    assert group_state["is_collapsed"] is True  # явное состояние не сброшено


def test_duplicate_diagram_copies_layout_and_group_states(client, db_session):
    device = _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма-оригинал"}).json()
    client.put(f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": {device.id: {"x": 11, "y": 22}}})
    client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:dup", json={"is_collapsed": True, "custom_threshold": 7})

    r = client.post(f"/api/v1/diagrams/{diagram['id']}/duplicate")
    assert r.status_code == 201
    dup = r.json()
    assert dup["name"] == "Диаграмма-оригинал (копия)"

    dup_detail = client.get(f"/api/v1/diagrams/{dup['id']}").json()
    node = next(n for n in dup_detail["nodes"] if n["id"] == device.id)
    assert node["x"] == 11 and node["y"] == 22

    dup_group = client.put(f"/api/v1/diagrams/{dup['id']}/groups/building:dup", json={}).json()
    assert dup_group["custom_threshold"] == 7


def test_duplicate_diagram_not_found(client):
    assert client.post("/api/v1/diagrams/does-not-exist/duplicate").status_code == 404


def test_export_svg_returns_valid_svg(client, db_session):
    _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма экспорта SVG"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "svg"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.text.strip().startswith("<svg")


def test_export_drawio_returns_valid_xml(client, db_session):
    _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма экспорта drawio"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "drawio"})
    assert r.status_code == 200
    assert "<mxfile" in r.text or "<mxGraphModel" in r.text


def test_export_vsdx_returns_binary_content(client, db_session):
    _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма экспорта vsdx"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "vsdx"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.ms-visio.drawing"
    assert len(r.content) > 0


def test_export_updates_last_export_format(client, db_session):
    _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма last-export"}).json()
    client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "svg"})
    updated = client.get(f"/api/v1/diagrams/{diagram['id']}").json()
    assert updated["last_export_format"] == "svg"


def test_export_rejects_unknown_format(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма плохого формата"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "pdf"})
    assert r.status_code == 422


def test_delete_diagram_cascades_layout_and_group_states(client, db_session):
    """Раздел 13 ТЗ дословно: 'DELETE /diagrams/{id} каскадно удаляет
    diagram_layouts/diagram_group_states'."""
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма на удаление"}).json()
    client.put(f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": {"x": {"x": 1, "y": 1}}})
    client.put(f"/api/v1/diagrams/{diagram['id']}/groups/building:z", json={"is_collapsed": True})

    r = client.delete(f"/api/v1/diagrams/{diagram['id']}")
    assert r.status_code == 200

    from app.models import DiagramGroupState, DiagramLayout
    assert db_session.query(DiagramLayout).filter_by(saved_diagram_id=diagram["id"]).count() == 0
    assert db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram["id"]).count() == 0
    assert client.get(f"/api/v1/diagrams/{diagram['id']}").status_code == 404


def test_delete_diagram_not_found(client):
    assert client.delete("/api/v1/diagrams/does-not-exist").status_code == 404


def test_diagram_icon_deletion_blocked_when_referenced(client, db_session):
    """Раздел 13 ТЗ дословно: 'Удаление DiagramIcon, на который есть ссылка, блокируется (409),
    как и для остальных справочников' — общий механизм crud.py:_find_referencing_counts."""
    icon = client.post("/api/v1/resources/diagram-icons", json={"name": "Своя иконка", "svg_markup": "<svg/>"}).json()
    device = _seed_device(db_session)
    device.diagram_icon_id = icon["id"]
    db_session.commit()

    r = client.delete(f"/api/v1/resources/diagram-icons/{icon['id']}")
    assert r.status_code == 409

    device.diagram_icon_id = None
    db_session.commit()
    assert client.delete(f"/api/v1/resources/diagram-icons/{icon['id']}").status_code == 200


def test_diagram_icon_create_rejects_executable_svg(client):
    """Код-ревью п.3.1: проверка обязана жить на бэкенде (services/crud.py:_RESOURCE_VALIDATORS
    -> validate_svg_markup), а не только на фронтенде — иначе прямой POST в API в обход формы
    сохранял бы payload как есть."""
    r = client.post("/api/v1/resources/diagram-icons", json={"name": "Вредоносная", "svg_markup": '<svg onload="alert(1)"></svg>'})
    assert r.status_code == 422


def test_diagram_icon_update_rejects_executable_svg(client):
    icon = client.post("/api/v1/resources/diagram-icons", json={"name": "Безопасная", "svg_markup": "<svg/>"}).json()
    r = client.put(f"/api/v1/resources/diagram-icons/{icon['id']}", json={"svg_markup": "<svg><script>alert(1)</script></svg>"})
    assert r.status_code == 422


def test_device_category_deletion_blocked_when_referenced_by_device_type(client):
    """Аналогичная защита для device-categories, через ту же generic-механику."""
    category = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]
    r = client.delete(f"/api/v1/resources/device-categories/{category['id']}")
    assert r.status_code == 409


def test_switch_node_edge_carries_port_index_end_to_end(client, db_session):
    """Небольшой сквозной тест: устройство-коммутатор с интерфейсом, подключение — итоговый узел
    несёт port_ticks дескриптора, а ребро — port_index интерфейса (раздел 4.3/4.4 ТЗ)."""
    from app.models import Connection, ConnectionType

    switch_type = db_session.query(DeviceType).filter_by(name="Коммутатор L2").one()
    server_type = db_session.query(DeviceType).filter_by(name="Сервер").one()
    switch = PhysicalDevice(device_type_id=switch_type.id, serial_number="SW-END-1")
    server = PhysicalDevice(device_type_id=server_type.id, serial_number="SRV-END-1")
    db_session.add_all([switch, server])
    db_session.flush()
    switch_iface = DeviceInterface(physical_device_id=switch.id, name="Gi0/1", is_management=True, is_data_transfer=False)
    server_iface = DeviceInterface(physical_device_id=server.id, name="eth0", is_management=False, is_data_transfer=True)
    db_session.add_all([switch_iface, server_iface])
    db_session.flush()
    conn_type = db_session.query(ConnectionType).filter_by(name="Витая пара").one()
    db_session.add(Connection(source_interface_id=switch_iface.id, destination_interface_id=server_iface.id, connection_type_id=conn_type.id, is_active=True))
    db_session.commit()

    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма коммутатора"}).json()
    detail = client.get(f"/api/v1/diagrams/{diagram['id']}").json()
    switch_node = next(n for n in detail["nodes"] if n["id"] == switch.id)
    assert switch_node["icon"]["shape"] == "switch"
    assert switch_node["icon"]["port_ticks"] == 1
    edge = detail["edges"][0]
    assert edge["source_interface"]["port_index"] == 0
