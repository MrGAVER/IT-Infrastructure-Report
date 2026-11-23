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
    r = client.put(
        f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": {"some-id": {"x": 42, "y": 99}}, "viewport": {"zoom": 1.5}}
    )
    assert r.status_code == 200
    detail = client.get(f"/api/v1/diagrams/{diagram['id']}").json()
    assert detail["viewport"] == {"zoom": 1.5}


def test_update_layout_rejects_non_object_positions(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма raw"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/layout", json={"node_positions": "not-an-object"})
    assert r.status_code == 422


def test_rename_diagram_updates_name(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Старое название"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/rename", json={"name": "Новое название"})
    assert r.status_code == 200
    assert r.json()["name"] == "Новое название"
    assert client.get(f"/api/v1/diagrams/{diagram['id']}").json()["name"] == "Новое название"


def test_rename_diagram_rejects_empty_name(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма для пустого имени"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/rename", json={"name": "   "})
    assert r.status_code == 422


def test_rename_diagram_rejects_duplicate_name(client):
    client.post("/api/v1/diagrams", json={"name": "Занятое имя"})
    other = client.post("/api/v1/diagrams", json={"name": "Диаграмма для переименования"}).json()
    r = client.put(f"/api/v1/diagrams/{other['id']}/rename", json={"name": "Занятое имя"})
    assert r.status_code == 409


def test_rename_diagram_allows_keeping_own_current_name(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "То же имя"}).json()
    r = client.put(f"/api/v1/diagrams/{diagram['id']}/rename", json={"name": "То же имя"})
    assert r.status_code == 200


def test_rename_diagram_not_found(client):
    r = client.put("/api/v1/diagrams/does-not-exist/rename", json={"name": "Что угодно"})
    assert r.status_code == 404


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
    # A-13: безопасный GET по умолчанию ничего не пишет; формат запоминается по явной просьбе клиента (persist_export).
    client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "svg", "persist_export": "true"})
    updated = client.get(f"/api/v1/diagrams/{diagram['id']}").json()
    assert updated["last_export_format"] == "svg"


def test_export_rejects_unknown_format(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма плохого формата"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "pdf"})
    assert r.status_code == 422


def test_export_failure_returns_clean_500_instead_of_raw_traceback(client, monkeypatch):
    """Реальная причина такого сбоя в проде оказалась окружением (EXE-сборка не паковала файлы
    данных vsdx/drawpyo — см. infra_registry.spec и test_pyinstaller_spec.py), но на случай
    ЛЮБОЙ другой непредвиденной причины экспорт должен отдавать понятную ошибку, а не голый
    500 без единого объяснения (см. try/except в export_diagram)."""
    import app.api.diagrams as diagrams_module

    def _boom(graph):
        raise RuntimeError("симулированный сбой стороннего пакета экспорта")

    monkeypatch.setitem(diagrams_module.EXPORT_FORMATS, "svg", ("image/svg+xml", _boom))
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма с падающим экспортом"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "svg"})
    assert r.status_code == 500
    assert ".svg" in r.json()["detail"]


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
    как и для остальных справочников' — общий механизм crud/:_find_referencing_counts."""
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
    """Код-ревью п.3.1: проверка обязана жить на бэкенде (services/crud/:_RESOURCE_VALIDATORS
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
    db_session.add(
        Connection(
            source_interface_id=switch_iface.id, destination_interface_id=server_iface.id, connection_type_id=conn_type.id, is_active=True
        )
    )
    db_session.commit()

    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма коммутатора"}).json()
    detail = client.get(f"/api/v1/diagrams/{diagram['id']}").json()
    switch_node = next(n for n in detail["nodes"] if n["id"] == switch.id)
    # Пункт 5 правки "диаграмма топологии сети": 'Коммутатор L2' теперь резолвится в
    # switch_l2 (собственная подкатегория 'Коммутаторы L2'), а не в общий 'switch' — см.
    # test_diagram_catalogs.py:test_l2_and_l3_switches_resolve_to_different_categories_with_distinct_shapes.
    assert switch_node["icon"]["shape"] == "switch_l2"
    assert switch_node["icon"]["port_ticks"] == 1
    edge = detail["edges"][0]
    assert edge["source_interface"]["port_index"] == 0


# --- A-04: валидация цвета/формы категории и экспорт с «грязными» данными ---------------------------------------------

DIRTY_COLOR = 'x" onload="alert(1)'


def _category_body(name: str, **extra) -> dict:
    return {"name": name, **extra}


def test_create_category_rejects_dirty_color(client):
    r = client.post("/api/v1/resources/device-categories", json=_category_body("Категория А-04 цвет", diagram_color=DIRTY_COLOR))
    assert r.status_code == 422, r.text
    assert "diagram_color" in r.text


def test_create_category_rejects_unknown_shape(client):
    r = client.post("/api/v1/resources/device-categories", json=_category_body("Категория А-04 форма", diagram_shape="hexagon"))
    assert r.status_code == 422, r.text
    assert "diagram_shape" in r.text


def test_create_category_accepts_valid_and_empty_values(client):
    for index, extra in enumerate(
        [
            {"diagram_color": "#4f7cff", "diagram_shape": "server"},
            {"diagram_color": "#4cf", "diagram_shape": "switch_l3"},
            {"diagram_color": "", "diagram_shape": ""},
            {},
        ]
    ):
        r = client.post("/api/v1/resources/device-categories", json=_category_body(f"Категория А-04 ок {index}", **extra))
        assert r.status_code == 201, r.text


def test_update_category_rejects_dirty_color_and_keeps_old_value(client):
    created = client.post("/api/v1/resources/device-categories", json=_category_body("Категория А-04 PUT", diagram_color="#112233")).json()
    r = client.put(
        f"/api/v1/resources/device-categories/{created['id']}", json={**_category_body("Категория А-04 PUT", diagram_color=DIRTY_COLOR)}
    )
    assert r.status_code == 422, r.text
    assert client.get(f"/api/v1/resources/device-categories/{created['id']}").json()["diagram_color"] == "#112233"


def test_update_category_rejects_unknown_shape(client):
    created = client.post("/api/v1/resources/device-categories", json=_category_body("Категория А-04 PUT форма")).json()
    r = client.put(
        f"/api/v1/resources/device-categories/{created['id']}", json=_category_body("Категория А-04 PUT форма", diagram_shape="zzz")
    )
    assert r.status_code == 422, r.text


def _dirty_the_category_of_the_seeded_device(db_session, color=DIRTY_COLOR, shape=None):
    from app.models import DeviceCategory

    device = _seed_device(db_session)
    device_type = db_session.get(DeviceType, device.device_type_id)
    category = db_session.get(DeviceCategory, device_type.category_id)
    category.diagram_color = color  # прямая запись мимо API: уже сохранённые «грязные» данные
    if shape is not None:
        category.diagram_shape = shape
    db_session.commit()


def test_export_svg_of_dirty_category_uses_default_color_and_has_no_injection(client, db_session):
    from app.services.diagram_icons import DEFAULT_COLOR

    _dirty_the_category_of_the_seeded_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-04 svg"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "svg"})
    assert r.status_code == 200
    assert "onload" not in r.text
    assert f'fill="{DEFAULT_COLOR}"' in r.text


def test_graph_json_of_dirty_category_carries_default_color(client, db_session):
    from app.services.diagram_icons import DEFAULT_COLOR, DEFAULT_SHAPE

    _dirty_the_category_of_the_seeded_device(db_session, shape="<script>")
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-04 json"}).json()
    nodes = client.get(f"/api/v1/diagrams/{diagram['id']}").json()["nodes"]
    icons = [n["icon"] for n in nodes if n["type"] == "device"]
    assert icons and all(i["color"] == DEFAULT_COLOR and i["shape"] == DEFAULT_SHAPE for i in icons)


def test_export_drawio_of_dirty_category_does_not_fail_and_has_no_foreign_style(client, db_session):
    _dirty_the_category_of_the_seeded_device(db_session, color="#fff;strokeColor=red")  # ровно 20 символов: колонка VARCHAR(20)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-04 drawio"}).json()
    r = client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": "drawio"})
    assert r.status_code == 200
    assert "strokeColor=red" not in r.text


# --- A-05: PUT /layout проверяет вход, а сохранённая раскладка не ломает чтение -----------------------------------------

import json as _json  # noqa: E402

import pytest  # noqa: E402


def _put_layout(client, diagram_id, **body):
    return client.put(f"/api/v1/diagrams/{diagram_id}/layout", json=body)


def _put_layout_raw(client, diagram_id, text):
    return client.put(f"/api/v1/diagrams/{diagram_id}/layout", content=text, headers={"content-type": "application/json"})


@pytest.mark.parametrize(
    "positions",
    [
        {"id": "str"},
        {"id": {"x": "a", "y": 1}},
        {"id": {"x": 1}},
        {"id": {"x": True, "y": 1}},
        {"id": None},
        {"id": [1, 2]},
        {"id": {"x": '1" onload="alert(1)', "y": 1}},
        {"k" * 201: {"x": 1, "y": 1}},
    ],
)
def test_put_layout_rejects_malformed_positions(client, positions):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 вход"}).json()
    assert _put_layout(client, diagram["id"], node_positions=positions).status_code == 422


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_put_layout_rejects_non_finite_numbers(client, token):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 NaN"}).json()
    r = _put_layout_raw(client, diagram["id"], '{"node_positions": {"id": {"x": %s, "y": 1}}}' % token)
    assert r.status_code == 422


def test_put_layout_limits_node_count(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 размер"}).json()
    too_many = {f"n{i}": {"x": i, "y": i} for i in range(5001)}
    assert _put_layout(client, diagram["id"], node_positions=too_many).status_code == 422
    exactly = {f"n{i}": {"x": i, "y": i} for i in range(5000)}
    assert _put_layout(client, diagram["id"], node_positions=exactly).status_code == 200


def test_rejected_put_keeps_the_previous_layout(client, db_session):
    from app.models import DiagramLayout

    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 сохранность"}).json()
    assert _put_layout(client, diagram["id"], node_positions={"keep": {"x": 1, "y": 2}}).status_code == 200
    assert _put_layout(client, diagram["id"], node_positions={"keep": "broken"}).status_code == 422
    db_session.expire_all()
    stored = db_session.query(DiagramLayout).filter_by(saved_diagram_id=diagram["id"]).one()
    assert _json.loads(stored.node_positions) == {"keep": {"x": 1, "y": 2}}


def test_put_layout_stores_only_x_and_y(client, db_session):
    from app.models import DiagramLayout

    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 лишние поля"}).json()
    assert _put_layout(client, diagram["id"], node_positions={"n": {"x": 1, "y": 2, "junk": "<script>"}}).status_code == 200
    db_session.expire_all()
    stored = db_session.query(DiagramLayout).filter_by(saved_diagram_id=diagram["id"]).one()
    assert _json.loads(stored.node_positions)["n"] == {"x": 1, "y": 2}


@pytest.mark.parametrize("viewport", [{"zoom": 1.5}, {"x": 1, "y": -2, "zoom": 0.5}, {"zoom": 2, "pan_x": 40, "pan_y": -10}, {}])
def test_put_layout_accepts_valid_viewport(client, viewport):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 viewport ок"}).json()
    assert _put_layout(client, diagram["id"], node_positions={}, viewport=viewport).status_code == 200
    assert client.get(f"/api/v1/diagrams/{diagram['id']}").json()["viewport"] == viewport


@pytest.mark.parametrize(
    "viewport", ["text", [1, 2], 5, {"zoom": "1"}, {"zoom": True}, {"zoom": None}, {"foo": 1}, {"zoom": 1, "x": {"a": 1}}]
)
def test_put_layout_rejects_invalid_viewport(client, viewport):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 viewport"}).json()
    assert _put_layout(client, diagram["id"], node_positions={}, viewport=viewport).status_code == 422


def test_put_layout_rejects_non_finite_viewport(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 viewport NaN"}).json()
    r = _put_layout_raw(client, diagram["id"], '{"node_positions": {}, "viewport": {"zoom": NaN}}')
    assert r.status_code == 422


def test_put_layout_without_viewport_keeps_the_saved_one(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 viewport остаётся"}).json()
    _put_layout(client, diagram["id"], node_positions={}, viewport={"zoom": 3})
    assert _put_layout(client, diagram["id"], node_positions={"a": {"x": 1, "y": 1}}).status_code == 200
    assert client.get(f"/api/v1/diagrams/{diagram['id']}").json()["viewport"] == {"zoom": 3}


def test_group_key_longer_than_200_is_rejected(client):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 group_key"}).json()
    assert client.put(f"/api/v1/diagrams/{diagram['id']}/groups/{'g' * 201}", json={"is_collapsed": True}).status_code == 422
    assert client.put(f"/api/v1/diagrams/{diagram['id']}/groups/{'g' * 200}", json={"is_collapsed": True}).status_code == 200


def _poison_layout(db_session, diagram_id, node_positions, viewport=None):
    """Прямая запись мимо API: так выглядят уже испорченные данные или раскладка, записанная прежней версией."""
    from app.models import DiagramLayout

    layout = db_session.query(DiagramLayout).filter_by(saved_diagram_id=diagram_id).one()
    layout.node_positions = node_positions
    layout.viewport = viewport
    db_session.commit()


@pytest.mark.parametrize(
    "stored",
    [
        '{{DEV}: "str"}',
        '{{DEV}: {"x": "1\\" onload=\\"alert(1)", "y": 1}}',
        '{{DEV}: {"x": NaN, "y": 1}}',
        "{{DEV}: [1, 2]}",
        "{{DEV}: null}",
        '["not", "an", "object"]',
        '"just a string"',
        "not json at all",
        "",
    ],
)
def test_poisoned_layout_does_not_break_get_regenerate_and_exports(client, db_session, stored):
    device = _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 испорчена"}).json()
    stored = stored.replace("{DEV}", _json.dumps(device.id))
    _poison_layout(db_session, diagram["id"], stored)

    r = client.get(f"/api/v1/diagrams/{diagram['id']}")
    assert r.status_code == 200, r.text
    node = next(n for n in r.json()["nodes"] if n["id"] == device.id)
    assert isinstance(node["x"], (int, float)) and isinstance(node["y"], (int, float))

    assert client.post(f"/api/v1/diagrams/{diagram['id']}/regenerate").status_code == 200
    for fmt in ("svg", "drawio", "vsdx"):
        assert client.get(f"/api/v1/diagrams/{diagram['id']}/export", params={"format": fmt}).status_code == 200, fmt


def test_regenerate_replaces_poisoned_positions_with_valid_ones(client, db_session):
    from app.models import DiagramLayout

    device = _seed_device(db_session)
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 регенерация"}).json()
    _poison_layout(db_session, diagram["id"], _json.dumps({device.id: "str", "ghost": {"x": "a", "y": 1}, "kept": {"x": 3, "y": 4}}))
    assert client.post(f"/api/v1/diagrams/{diagram['id']}/regenerate").status_code == 200
    db_session.expire_all()
    stored = _json.loads(db_session.query(DiagramLayout).filter_by(saved_diagram_id=diagram["id"]).one().node_positions)
    assert stored["kept"] == {"x": 3, "y": 4}, "корректные позиции сохраняются"
    assert "ghost" not in stored
    assert set(stored[device.id]) == {"x", "y"}


@pytest.mark.parametrize("viewport", ['"text"', '{"zoom": "a"}', "[1]", "not json", '{"zoom": NaN}', '{"unknown": 1}'])
def test_poisoned_viewport_is_read_as_absent(client, db_session, viewport):
    diagram = client.post("/api/v1/diagrams", json={"name": "Диаграмма А-05 viewport испорчен"}).json()
    _poison_layout(db_session, diagram["id"], "{}", viewport)
    r = client.get(f"/api/v1/diagrams/{diagram['id']}")
    assert r.status_code == 200
    assert r.json()["viewport"] is None
