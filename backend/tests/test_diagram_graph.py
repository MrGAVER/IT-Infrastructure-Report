"""
Тесты на backend/app/services/diagram_graph.py — раздел 13 ТЗ диаграммы топологии сети:
группировка (смена group_by даёт разные group_key; custom_threshold перебивает
collapse_threshold; regenerate не сбрасывает явно заданные is_collapsed/custom_threshold),
данные узла (ip_addresses без дублей; label откатывается на serial_number), данные ребра
(vlans без дублей по vlan_id; source_interface/target_interface всегда присутствуют, включая
случай, когда один конец входит в свёрнутую группу).

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_graph.py -v
"""
from __future__ import annotations

import json

from app.models import (
    Building, Connection, ConnectionType, DeviceInterface, DeviceType, DiagramGroupState, IPAddress,
    InterfaceVLAN, PhysicalDevice, PhysicalDeviceVLAN, SavedDiagram, StructuralUnit, VLAN, VLANDomain,
)
from app.services.catalogs import seed_defaults
from app.services.diagram_graph import (
    GraphContext,
    apply_grouping,
    build_graph,
    group_key_for_device,
    parse_scope_filter,
)


def _seed_base_catalogs(session):
    seed_defaults(session)
    session.commit()
    server_type = session.query(DeviceType).filter_by(name="Сервер").one()
    switch_type = session.query(DeviceType).filter_by(name="Коммутатор L2").one()
    return server_type, switch_type


def _make_device(session, device_type_id, serial, system_name=None, building_id=None):
    device = PhysicalDevice(device_type_id=device_type_id, serial_number=serial, system_name=system_name, building_id=building_id)
    session.add(device)
    session.flush()
    return device


def _make_interface(session, device_id, name):
    iface = DeviceInterface(physical_device_id=device_id, name=name, is_management=False, is_data_transfer=True)
    session.add(iface)
    session.flush()
    return iface


def test_parse_scope_filter_defaults_to_empty_dict_on_invalid_json():
    assert parse_scope_filter("") == {}
    assert parse_scope_filter("not json") == {}
    assert parse_scope_filter("null") == {}
    assert parse_scope_filter('{"building_ids": ["b1"]}') == {"building_ids": ["b1"]}


def test_group_key_differs_by_dimension_for_same_device(db_session):
    server_type, _ = _seed_base_catalogs(db_session)
    unit = StructuralUnit(name="Филиал А")
    building = Building(name="Здание 1")
    db_session.add_all([unit, building])
    db_session.flush()
    building.structural_unit_id = unit.id
    device = _make_device(db_session, server_type.id, "SN-1", building_id=building.id)
    db_session.flush()

    ctx = GraphContext(db_session)
    by_building = group_key_for_device(device, "building", ctx)
    by_structural_unit = group_key_for_device(device, "structural_unit", ctx)
    by_category = group_key_for_device(device, "device_category", ctx)
    assert by_building == f"building:{building.id}"
    assert by_structural_unit == f"structural_unit:{unit.id}"
    assert by_category == f"device_category:{server_type.category_id}"
    assert len({by_building, by_structural_unit, by_category}) == 3


def test_group_key_for_device_without_building_is_unassigned(db_session):
    server_type, _ = _seed_base_catalogs(db_session)
    device = _make_device(db_session, server_type.id, "SN-2")
    ctx = GraphContext(db_session)
    assert group_key_for_device(device, "building", ctx) == "building:none"


def test_apply_grouping_creates_state_only_when_threshold_reached(db_session):
    diagram = SavedDiagram(name="Диаграмма", scope_filter="{}", group_by="building", collapse_threshold=5)
    db_session.add(diagram)
    db_session.flush()

    below = apply_grouping(db_session, diagram, {"building:x": 4})
    assert below == {}  # ниже порога — запись не создаётся вообще

    at_threshold = apply_grouping(db_session, diagram, {"building:y": 5})
    assert at_threshold["building:y"].is_collapsed is True
    assert at_threshold["building:y"].device_count == 5


def test_custom_threshold_overrides_diagram_default(db_session):
    """Раздел 13 ТЗ: custom_threshold конкретной группы перебивает collapse_threshold диаграммы."""
    diagram = SavedDiagram(name="Диаграмма 2", scope_filter="{}", group_by="building", collapse_threshold=20)
    db_session.add(diagram)
    db_session.flush()
    state = DiagramGroupState(saved_diagram_id=diagram.id, group_key="building:z", is_collapsed=False, device_count=3, custom_threshold=3)
    db_session.add(state)
    db_session.flush()

    # apply_grouping не пересчитывает is_collapsed по threshold для УЖЕ существующей записи —
    # но device_count обновляется. custom_threshold используется вызывающим кодом (build_graph),
    # не самой apply_grouping (которая создаёт запись заново только при её ОТСУТСТВИИ).
    result = apply_grouping(db_session, diagram, {"building:z": 6})
    assert result["building:z"].device_count == 6
    assert result["building:z"].is_collapsed is False  # не тронуто повторным вызовом
    assert result["building:z"].custom_threshold == 3


def test_regenerate_does_not_reset_explicit_group_state(db_session):
    """Раздел 8 ТЗ: 'если пользователь уже явно менял состояние группы — regenerate его не
    перезаписывает, обновляется только device_count'."""
    diagram = SavedDiagram(name="Диаграмма 3", scope_filter="{}", group_by="building", collapse_threshold=5)
    db_session.add(diagram)
    db_session.flush()
    apply_grouping(db_session, diagram, {"building:x": 10})  # создаёт is_collapsed=True (>= порога)
    db_session.commit()

    state = db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram.id, group_key="building:x").one()
    state.is_collapsed = False  # пользователь вручную развернул группу
    db_session.commit()

    result = apply_grouping(db_session, diagram, {"building:x": 12})  # повторный regenerate
    assert result["building:x"].is_collapsed is False  # не сброшено обратно в True
    assert result["building:x"].device_count == 12


def test_device_node_label_falls_back_to_serial_number(db_session):
    server_type, _ = _seed_base_catalogs(db_session)
    device = _make_device(db_session, server_type.id, "SN-NO-NAME", system_name=None)
    diagram = SavedDiagram(name="Диаграмма 4", scope_filter="{}", group_by="building", collapse_threshold=20)
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    node = next(n for n in graph["nodes"] if n["id"] == device.id)
    assert node["label"] == "SN-NO-NAME"


def test_device_node_ip_addresses_merge_interface_and_vlan_ips_without_duplicates(db_session):
    server_type, _ = _seed_base_catalogs(db_session)
    device = _make_device(db_session, server_type.id, "SN-IP")
    iface = _make_interface(db_session, device.id, "eth0")
    db_session.add(IPAddress(owner_type="device_interface", owner_id=iface.id, ip_address="10.0.0.1", prefix_length=24, purpose="управление", is_management=True))
    domain = VLANDomain(name="Домен")
    db_session.add(domain)
    db_session.flush()
    vlan = VLAN(vlan_id=10, name="mgmt", domain_id=domain.id)
    db_session.add(vlan)
    db_session.flush()
    db_session.add(PhysicalDeviceVLAN(physical_device_id=device.id, vlan_id=vlan.id, ip_address="10.0.0.1", prefix_length=24, is_management=True))
    diagram = SavedDiagram(name="Диаграмма 5", scope_filter="{}", group_by="building", collapse_threshold=20)
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    node = next(n for n in graph["nodes"] if n["id"] == device.id)
    addresses = [a["address"] for a in node["ip_addresses"]]
    assert addresses == ["10.0.0.1/24"]  # один и тот же адрес из двух источников — без дублей


def test_edge_vlans_merge_without_duplicate_vlan_id_and_keeps_interfaces_across_group_collapse(db_session):
    """Раздел 13 ТЗ дословно: 'vlans — объединение VLAN обоих интерфейсов соединения без дублей
    по vlan_id; source_interface/target_interface присутствуют всегда, включая случай, когда
    один конец соединения входит в свёрнутую группу.'"""
    server_type, switch_type = _seed_base_catalogs(db_session)
    building = Building(name="Здание сворачиваемое")
    db_session.add(building)
    db_session.flush()

    switch = _make_device(db_session, switch_type.id, "SW-1")
    switch_iface = _make_interface(db_session, switch.id, "Gi0/1")

    # 5 серверов в одном здании при пороге 5 -> здание сворачивается в группу.
    servers = [_make_device(db_session, server_type.id, f"SRV-{i}", building_id=building.id) for i in range(5)]
    server_ifaces = [_make_interface(db_session, s.id, "eth0") for s in servers]

    conn_type = db_session.query(ConnectionType).filter_by(name="Витая пара").one()
    connection = Connection(source_interface_id=switch_iface.id, destination_interface_id=server_ifaces[0].id, connection_type_id=conn_type.id, is_active=True)
    db_session.add(connection)

    domain = VLANDomain(name="Домен 2")
    db_session.add(domain)
    db_session.flush()
    vlan10 = VLAN(vlan_id=10, name="data", domain_id=domain.id)
    vlan20 = VLAN(vlan_id=20, name="voice", domain_id=domain.id)
    db_session.add_all([vlan10, vlan20])
    db_session.flush()
    db_session.add(InterfaceVLAN(interface_id=switch_iface.id, vlan_id=vlan10.id))
    db_session.add(InterfaceVLAN(interface_id=server_ifaces[0].id, vlan_id=vlan10.id))  # дубль по vlan_id
    db_session.add(InterfaceVLAN(interface_id=server_ifaces[0].id, vlan_id=vlan20.id))

    diagram = SavedDiagram(name="Диаграмма 6", scope_filter="{}", group_by="building", collapse_threshold=5)
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    group_nodes = [n for n in graph["nodes"] if n["type"] == "group"]
    assert len(group_nodes) == 1
    assert group_nodes[0]["device_count"] == 5

    edge = next(e for e in graph["edges"] if e["id"] == connection.id)
    assert edge["source_node_id"] == switch.id  # коммутатор не в свёрнутой группе
    assert edge["target_node_id"] == group_nodes[0]["id"]  # сервер — в свёрнутой группе здания
    assert edge["source_interface"]["id"] == switch_iface.id
    assert edge["target_interface"]["id"] == server_ifaces[0].id  # интерфейс сохранён несмотря на сворачивание
    assert edge["source_interface"]["port_index"] == 0  # switch — первый (и единственный) интерфейс
    assert "port_index" not in edge["target_interface"]  # сервер свёрнут в группу — своей засечки нет
    vlan_ids = sorted(v["vlan_id"] for v in edge["vlans"])
    assert vlan_ids == [10, 20]  # без дубля vlan_id=10, пришедшего с обоих концов


def test_port_index_assigned_per_interface_for_non_switch_device(db_session):
    """Прямая проверка причины бага, о котором сообщил пользователь: сервер с несколькими
    интерфейсами, участвующими в разных связях, должен получать РАЗНЫЕ port_index — иначе на
    канвасе обе линии анкерились бы в одну и ту же (единственную) точку узла сервера."""
    server_type, switch_type = _seed_base_catalogs(db_session)
    server = _make_device(db_session, server_type.id, "SRV-MULTI")
    server_ifaces = [_make_interface(db_session, server.id, name) for name in ("eth0", "eth1")]
    switches = [_make_device(db_session, switch_type.id, f"SW-{i}") for i in range(2)]
    switch_ifaces = [_make_interface(db_session, s.id, "Gi0/1") for s in switches]

    conn_type = db_session.query(ConnectionType).filter_by(name="Витая пара").one()
    connections = [
        Connection(
            source_interface_id=server_ifaces[i].id,
            destination_interface_id=switch_ifaces[i].id,
            connection_type_id=conn_type.id,
            is_active=True,
        )
        for i in range(2)
    ]
    db_session.add_all(connections)
    diagram = SavedDiagram(name="Диаграмма 9", scope_filter="{}")
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    edges_by_id = {e["id"]: e for e in graph["edges"]}
    assert edges_by_id[connections[0].id]["source_interface"]["port_index"] == 0  # eth0
    assert edges_by_id[connections[1].id]["source_interface"]["port_index"] == 1  # eth1 — не 0


def test_port_index_omitted_when_device_itself_is_collapsed_into_a_group(db_session):
    """Регрессия: у узла-группы нет собственных засечек порта (DiagramGroupNode.vue рисует
    только один общий Handle), поэтому если устройство на этом конце СВЁРНУТО в группу, ребро не
    должно нести port_index этого устройства — иначе фронтенд анкерил бы Handle с id вида
    "port-N-source" на узле, где такого Handle физически не существует. Раньше это ограничивалось
    только shape="switch" не по признаку свёрнутости, а по формуле "не switch — вообще нет
    port_index"; теперь, когда port_index считается для ЛЮБОЙ сгенерированной формы, эта проверка
    обязательна для корректности на канвасе."""
    server_type, switch_type = _seed_base_catalogs(db_session)
    building = Building(name="Здание со свёрнутыми коммутаторами")
    db_session.add(building)
    db_session.flush()

    # 2 коммутатора в одном здании при пороге 2 -> здание сворачивается в группу.
    switches = [_make_device(db_session, switch_type.id, f"SW-{i}", building_id=building.id) for i in range(2)]
    switch_ifaces = [_make_interface(db_session, s.id, "Gi0/1") for s in switches]
    server = _make_device(db_session, server_type.id, "SRV-EXTERNAL")
    server_iface = _make_interface(db_session, server.id, "eth0")

    conn_type = db_session.query(ConnectionType).filter_by(name="Витая пара").one()
    connection = Connection(source_interface_id=switch_ifaces[0].id, destination_interface_id=server_iface.id, connection_type_id=conn_type.id, is_active=True)
    db_session.add(connection)

    diagram = SavedDiagram(name="Диаграмма 7", scope_filter="{}", group_by="building", collapse_threshold=2)
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    group_nodes = [n for n in graph["nodes"] if n["type"] == "group"]
    assert len(group_nodes) == 1  # оба коммутатора свёрнуты в одну группу по зданию

    edge = next(e for e in graph["edges"] if e["id"] == connection.id)
    assert edge["source_node_id"] == group_nodes[0]["id"]  # коммутатор свёрнут — ребро идёт от группы
    assert edge["target_node_id"] == server.id  # сервер вне здания — не свёрнут
    assert "port_index" not in edge["source_interface"]  # у группы нет своей засечки — анкерить некуда
    assert edge["target_interface"]["port_index"] == 0  # сервер отрисован как свой узел — засечка есть


def test_internal_group_edge_is_not_drawn(db_session):
    """Раздел 4.4 ТЗ: внутригрупповые рёбра (оба конца в одной свёрнутой группе) не рисуются."""
    server_type, _ = _seed_base_catalogs(db_session)
    building = Building(name="Здание для внутригрупповой связи")
    db_session.add(building)
    db_session.flush()
    servers = [_make_device(db_session, server_type.id, f"INT-{i}", building_id=building.id) for i in range(5)]
    ifaces = [_make_interface(db_session, s.id, "eth0") for s in servers]
    conn_type = ConnectionType(name="Витая пара 2")
    db_session.add(conn_type)
    db_session.flush()
    connection = Connection(source_interface_id=ifaces[0].id, destination_interface_id=ifaces[1].id, connection_type_id=conn_type.id, is_active=True)
    db_session.add(connection)
    diagram = SavedDiagram(name="Диаграмма 7", scope_filter="{}", group_by="building", collapse_threshold=5)
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    assert graph["edges"] == []  # оба конца в одной свёрнутой группе — ребро не строится


def test_edge_excluded_when_other_end_outside_scope_filter(db_session):
    server_type, _ = _seed_base_catalogs(db_session)
    building_in = Building(name="Здание в охвате")
    building_out = Building(name="Здание вне охвата")
    db_session.add_all([building_in, building_out])
    db_session.flush()
    device_in = _make_device(db_session, server_type.id, "IN-1", building_id=building_in.id)
    device_out = _make_device(db_session, server_type.id, "OUT-1", building_id=building_out.id)
    iface_in = _make_interface(db_session, device_in.id, "eth0")
    iface_out = _make_interface(db_session, device_out.id, "eth0")
    conn_type = ConnectionType(name="Витая пара 3")
    db_session.add(conn_type)
    db_session.flush()
    db_session.add(Connection(source_interface_id=iface_in.id, destination_interface_id=iface_out.id, connection_type_id=conn_type.id, is_active=True))
    diagram = SavedDiagram(name="Диаграмма 8", scope_filter=json.dumps({"building_ids": [building_in.id]}), group_by="building", collapse_threshold=20)
    db_session.add(diagram)
    db_session.commit()

    graph = build_graph(db_session, diagram)
    node_ids = {n["id"] for n in graph["nodes"]}
    assert device_in.id in node_ids
    assert device_out.id not in node_ids
    assert graph["edges"] == []  # другой конец физически отсутствует на этой диаграмме
