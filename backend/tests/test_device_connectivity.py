"""GET /devices/{id}/free-interfaces и /devices/{id}/interface-connections
(services/device_connectivity.py): занятость портов и подключения устройства считает сервер, а не клиент
по общим спискам с потолком в 1000 записей."""
from __future__ import annotations

from app.models import Connection

API = "/api/v1"


def _device(client, serial: str, system_name: str | None = None) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    body = {"device_type_id": dt["id"], "serial_number": serial}
    if system_name:
        body["system_name"] = system_name
    return client.post(f"{API}/resources/devices", json=body).json()


def _with_ports(client, serial: str, names: list[str], system_name: str | None = None) -> tuple[dict, dict[str, dict]]:
    dev = _device(client, serial, system_name)
    r = client.put(f"{API}/devices/{dev['id']}/interfaces", json={"interfaces": [{"name": n} for n in names]})
    assert r.status_code == 200, r.text
    items = client.get(f"{API}/resources/interfaces", params={"physical_device_id": dev["id"], "limit": 1000}).json()["items"]
    return dev, {x["name"]: x for x in items}


def _connection_type(client) -> dict:
    items = client.get(f"{API}/resources/connection-types", params={"limit": 1000}).json()["items"]
    return next(x for x in items if x["name"] == "Витая пара")


def _connect(client, a: dict, b: dict, *, active: bool = True, description: str | None = None) -> dict:
    r = client.post(f"{API}/resources/connections", json={"source_interface_id": a["id"], "destination_interface_id": b["id"], "connection_type_id": _connection_type(client)["id"], "is_active": active, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


def _free(client, device_id: str, **params):
    return client.get(f"{API}/devices/{device_id}/free-interfaces", params=params)


def test_free_interfaces_are_listed_in_natural_order_with_their_roles(client):
    dev, _ = _with_ports(client, "SW-NAT", ["Gi0/10", "Gi0/2", "Gi0/1"])

    r = _free(client, dev["id"])

    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["name"] for x in body["items"]] == ["Gi0/1", "Gi0/2", "Gi0/10"]  # а не Gi0/1, Gi0/10, Gi0/2
    assert body["total"] == 3 and body["offset"] == 0 and body["limit"] == 100
    assert set(body["items"][0]) == {"id", "name", "is_management", "is_data_transfer", "vlan_mode", "occupied"}
    assert all(x["occupied"] is False for x in body["items"])


def test_ports_with_an_active_connection_on_either_side_are_not_free(client):
    dev, ports = _with_ports(client, "SW-OCC", ["g1", "g2", "g3"])
    other, theirs = _with_ports(client, "SRV-OCC", ["eth0", "eth1"])
    _connect(client, ports["g1"], theirs["eth0"])  # g1 — источник
    _connect(client, theirs["eth1"], ports["g2"])  # g2 — назначение

    names = [x["name"] for x in _free(client, dev["id"]).json()["items"]]

    assert names == ["g3"]


def test_an_inactive_connection_does_not_occupy_the_port(client):
    dev, ports = _with_ports(client, "SW-INACT", ["g1"])
    _, theirs = _with_ports(client, "SRV-INACT", ["eth0"])
    _connect(client, ports["g1"], theirs["eth0"], active=False)

    assert [x["name"] for x in _free(client, dev["id"]).json()["items"]] == ["g1"]


def test_include_returns_occupied_ports_flagged_and_ignores_foreign_ids(client):
    dev, ports = _with_ports(client, "SW-INC", ["g1", "g2"])
    _, theirs = _with_ports(client, "SRV-INC", ["eth0"])
    _connect(client, ports["g1"], theirs["eth0"])

    r = client.get(f"{API}/devices/{dev['id']}/free-interfaces", params={"include": [ports["g1"]["id"], theirs["eth0"]["id"]]})

    items = r.json()["items"]
    assert [(x["name"], x["occupied"]) for x in items] == [("g1", True), ("g2", False)]  # порт чужого устройства не просочился


def test_search_filters_by_name_case_insensitively_but_included_ports_bypass_it(client):
    dev, ports = _with_ports(client, "SW-SRCH", ["GigabitEthernet0/1", "GigabitEthernet0/2", "mgmt0"])

    assert [x["name"] for x in _free(client, dev["id"], q="gigabit").json()["items"]] == ["GigabitEthernet0/1", "GigabitEthernet0/2"]
    assert _free(client, dev["id"], q="gigabit").json()["total"] == 2
    forced = client.get(f"{API}/devices/{dev['id']}/free-interfaces", params={"q": "gigabit", "include": [ports["mgmt0"]["id"]]}).json()
    assert [x["name"] for x in forced["items"]] == ["GigabitEthernet0/1", "GigabitEthernet0/2", "mgmt0"]


def test_pagination_returns_consistent_pages_and_validates_the_limit(client):
    dev, _ = _with_ports(client, "SW-PAGE", [f"p{n}" for n in range(1, 8)])

    first = _free(client, dev["id"], limit=3).json()
    second = _free(client, dev["id"], limit=3, offset=3).json()
    last = _free(client, dev["id"], limit=3, offset=6).json()

    assert [x["name"] for x in first["items"]] == ["p1", "p2", "p3"]
    assert [x["name"] for x in second["items"]] == ["p4", "p5", "p6"]
    assert [x["name"] for x in last["items"]] == ["p7"]
    assert first["total"] == second["total"] == last["total"] == 7
    assert _free(client, dev["id"], limit=501).status_code == 422
    assert _free(client, dev["id"], limit=0).status_code == 422
    assert _free(client, dev["id"], offset=-1).status_code == 422


def test_free_interfaces_of_an_unknown_device_is_404(client):
    assert _free(client, "no-such-device").status_code == 404


def test_interface_connections_describe_the_peer_port_and_device(client):
    dev, ports = _with_ports(client, "SRV-IC", ["eth0", "eth1"])
    peer_dev, theirs = _with_ports(client, "SW-IC", ["Gi0/1"], system_name="sw-core")
    conn = _connect(client, ports["eth0"], theirs["Gi0/1"], description="патч-корд №5")

    items = client.get(f"{API}/devices/{dev['id']}/interface-connections").json()["items"]

    assert items == [{
        "interface_id": ports["eth0"]["id"],
        "connection_id": conn["id"],
        "connection_type_id": conn["connection_type_id"],
        "description": "патч-корд №5",
        "peer_interface_id": theirs["Gi0/1"]["id"],
        "peer_interface_name": "Gi0/1",
        "peer_device_id": peer_dev["id"],
        "peer_device_name": "sw-core",
        "peer_is_management": theirs["Gi0/1"]["is_management"],
        "peer_is_data_transfer": theirs["Gi0/1"]["is_data_transfer"],
        "peer_vlan_mode": theirs["Gi0/1"]["vlan_mode"],
    }]


def test_interface_connections_work_from_either_end_and_fall_back_to_the_serial_number(client):
    dev, ports = _with_ports(client, "SRV-END", ["eth0"])
    peer_dev, theirs = _with_ports(client, "SW-END", ["Gi0/1"])  # системного имени нет
    _connect(client, theirs["Gi0/1"], ports["eth0"])  # наш порт — назначение

    (item,) = client.get(f"{API}/devices/{dev['id']}/interface-connections").json()["items"]

    assert item["interface_id"] == ports["eth0"]["id"] and item["peer_interface_id"] == theirs["Gi0/1"]["id"]
    assert item["peer_device_name"] == "SW-END"


def test_a_cable_between_two_ports_of_the_same_device_is_reported_for_both_ports(client):
    dev, ports = _with_ports(client, "SRV-LOOP", ["eth0", "eth1"])
    _connect(client, ports["eth0"], ports["eth1"])

    items = client.get(f"{API}/devices/{dev['id']}/interface-connections").json()["items"]

    assert sorted((x["interface_id"], x["peer_interface_id"]) for x in items) == sorted([(ports["eth0"]["id"], ports["eth1"]["id"]), (ports["eth1"]["id"], ports["eth0"]["id"])])
    assert {x["peer_device_id"] for x in items} == {dev["id"]}


def test_interface_connections_skip_inactive_and_foreign_connections_and_unknown_devices(client, db_session):
    dev, ports = _with_ports(client, "SRV-SKIP", ["eth0", "eth1"])
    _, theirs = _with_ports(client, "SW-SKIP", ["g1", "g2"])
    _connect(client, ports["eth0"], theirs["g1"], active=False)
    _connect(client, theirs["g2"], _with_ports(client, "SW-SKIP-2", ["x"])[1]["x"])  # к нашему устройству отношения не имеет

    assert client.get(f"{API}/devices/{dev['id']}/interface-connections").json() == {"items": []}
    assert client.get(f"{API}/devices/no-such-device/interface-connections").status_code == 404
    assert db_session.query(Connection).count() == 2


def _options(client, **params):
    return client.get(f"{API}/devices/options", params=params)


def _labels(response) -> list[str]:
    return [x["label"] for x in response.json()["items"]]


def test_device_options_are_light_records_sorted_by_label_ignoring_case(client):
    _device(client, "SN-2", "beta-sw")
    _device(client, "SN-1", "Alpha-sw")
    _device(client, "SN-ONLY")  # без системного имени подписью служит серийный номер

    body = _options(client).json()

    assert [x["label"] for x in body["items"]] == ["Alpha-sw", "beta-sw", "SN-ONLY"]
    assert body["total"] == 3 and body["offset"] == 0 and body["limit"] == 50
    first = body["items"][0]
    assert set(first) == {"id", "label", "system_name", "serial_number"}  # без обогащения полного списка устройств
    assert (first["system_name"], first["serial_number"]) == ("Alpha-sw", "SN-1")
    assert body["items"][2]["system_name"] is None


def test_device_options_search_ignores_case_including_cyrillic_and_matches_name_or_serial(client):
    _device(client, "SN-100", "Коммутатор-А")
    _device(client, "SN-200", "Маршрутизатор")
    _device(client, "ABC-300", "core-switch")

    assert _labels(_options(client, q="КОММУТ")) == ["Коммутатор-А"]  # SQLite lower() кириллицу не понижает
    assert _labels(_options(client, q="маршрутиз")) == ["Маршрутизатор"]
    assert _labels(_options(client, q="CORE")) == ["core-switch"]
    assert _labels(_options(client, q="abc-3")) == ["core-switch"]  # по серийному номеру
    assert _labels(_options(client, q="  sn-1  ")) == ["Коммутатор-А"]  # пробелы по краям не мешают
    assert _options(client, q="нет такого").json() == {"items": [], "total": 0, "offset": 0, "limit": 50}


def test_device_options_include_bypasses_the_search_and_exclude_beats_include(client):
    a = _device(client, "SN-A", "alpha")
    b = _device(client, "SN-B", "bravo")
    _device(client, "SN-C", "charlie")

    assert _labels(_options(client, q="alp", include=[b["id"]])) == ["alpha", "bravo"]  # выбранный сосед виден при любом поиске
    assert _labels(_options(client, q="alp", include=["чужой-id"])) == ["alpha"]  # неизвестные id игнорируются
    assert _labels(_options(client, exclude=[a["id"]])) == ["bravo", "charlie"]
    assert _labels(_options(client, include=[a["id"]], exclude=[a["id"]])) == ["bravo", "charlie"]


def test_device_options_pagination_is_consistent_and_validates_parameters(client):
    for n in range(1, 8):
        _device(client, f"SN-{n}", f"sw-{n}")

    first = _options(client, limit=3).json()
    second = _options(client, limit=3, offset=3).json()
    last = _options(client, limit=3, offset=6).json()

    assert [x["label"] for x in first["items"]] == ["sw-1", "sw-2", "sw-3"]
    assert [x["label"] for x in second["items"]] == ["sw-4", "sw-5", "sw-6"]
    assert [x["label"] for x in last["items"]] == ["sw-7"]
    assert first["total"] == second["total"] == last["total"] == 7
    assert _options(client, limit=201).status_code == 422
    assert _options(client, limit=0).status_code == 422
    assert _options(client, offset=-1).status_code == 422


def test_device_options_route_is_not_shadowed_by_the_per_device_routes(client):
    dev, _ = _with_ports(client, "SN-ROUTE", ["p1"], "route-sw")

    assert _options(client).status_code == 200
    assert _free(client, dev["id"]).status_code == 200  # соседние маршруты /devices/{id}/… работают как прежде
