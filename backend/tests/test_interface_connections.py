"""Подключения портов из формы устройства: PUT /devices/{id}/interfaces с ключом connection в
элементе interfaces (services/interface_connections.py, вызывается из services/crud/interfaces.py:sync_interfaces).

Главные инварианты:
* подключение создаётся в той же транзакции, что и порты, — в том числе для порта, которого до
  запроса не существовало (у него ещё нет id, поэтому отдельным запросом подключение не создать);
* ключа connection нет — подключения не трогаются; null — порт отключается;
* любая ошибка (занятый сосед, неизвестный тип линии) откатывает и порты тоже.
"""
from __future__ import annotations

from app.models import Connection

API = "/api/v1"


def _device(client, serial: str) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _connection_type(client, name: str = "Витая пара") -> dict:
    items = client.get(f"{API}/resources/connection-types", params={"limit": 1000}).json()["items"]
    return next(x for x in items if x["name"] == name)


def _sync(client, device_id: str, interfaces: list[dict]):
    return client.put(f"{API}/devices/{device_id}/interfaces", json={"interfaces": interfaces})


def _ports(client, device_id: str) -> dict[str, dict]:
    items = client.get(f"{API}/resources/interfaces", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {x["name"]: x for x in items}


def _connections(client) -> list[dict]:
    return client.get(f"{API}/resources/connections", params={"limit": 1000}).json()["items"]


def _peer_port(client, serial: str = "SW-PEER", name: str = "Gi0/1") -> dict:
    """Порт на другом устройстве — соседний порт для подключения."""
    peer = _device(client, serial)
    assert _sync(client, peer["id"], [{"name": name}]).status_code == 200
    return _ports(client, peer["id"])[name]


def _conn(peer: dict, connection_type: dict, description: str | None = None) -> dict:
    return {"peer_interface_id": peer["id"], "connection_type_id": connection_type["id"], "description": description}


def test_connection_is_created_together_with_a_brand_new_port(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-1")

    r = _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, ct, "патч-корд №5")}, {"name": "eth1"}])

    assert r.status_code == 200, r.text
    own = _ports(client, dev["id"])["eth0"]
    (conn,) = _connections(client)
    assert conn["source_interface_id"] == own["id"] and conn["destination_interface_id"] == peer["id"]
    assert conn["connection_type_id"] == ct["id"] and conn["description"] == "патч-корд №5" and conn["is_active"] is True
    assert conn["destination_interface_name"] == "Gi0/1"


def test_missing_connection_key_does_not_touch_existing_connection(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-2")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, ct)}])
    own = _ports(client, dev["id"])["eth0"]

    r = _sync(client, dev["id"], [{"id": own["id"], "name": "eth0", "description": "переименовали описание"}])

    assert r.status_code == 200, r.text
    assert len(_connections(client)) == 1


def test_changing_type_and_description_updates_the_same_connection_in_place(client):
    peer = _peer_port(client)
    twisted, fiber = _connection_type(client), _connection_type(client, "Оптическое волокно")
    dev = _device(client, "SRV-3")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, twisted)}])
    own = _ports(client, dev["id"])["eth0"]
    (before,) = _connections(client)

    r = _sync(client, dev["id"], [{"id": own["id"], "name": "eth0", "connection": _conn(peer, fiber, "uplink")}])

    assert r.status_code == 200, r.text
    (after,) = _connections(client)
    assert after["id"] == before["id"]
    assert after["connection_type_id"] == fiber["id"] and after["description"] == "uplink"
    assert after["source_interface_id"] == own["id"]  # направление не перевернулось


def test_switching_peer_reuses_connection_keeps_direction_and_resets_approval(client, db_session):
    first = _peer_port(client, "SW-A")
    second = _peer_port(client, "SW-B")
    ct = _connection_type(client)
    dev = _device(client, "SRV-4")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(first, ct)}])
    own = _ports(client, dev["id"])["eth0"]
    (before,) = _connections(client)
    row = db_session.get(Connection, before["id"])
    row.port_config_approved_signature = "approved-for-previous-peer"
    db_session.commit()

    r = _sync(client, dev["id"], [{"id": own["id"], "name": "eth0", "connection": _conn(second, ct)}])

    assert r.status_code == 200, r.text
    (after,) = _connections(client)
    assert after["id"] == before["id"]
    assert after["source_interface_id"] == own["id"] and after["destination_interface_id"] == second["id"]
    db_session.expire_all()
    assert db_session.get(Connection, before["id"]).port_config_approved_signature is None


def test_null_disconnects_the_port(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-5")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, ct)}])
    own = _ports(client, dev["id"])["eth0"]

    r = _sync(client, dev["id"], [{"id": own["id"], "name": "eth0", "connection": None}])

    assert r.status_code == 200, r.text
    assert _connections(client) == []
    assert "eth0" in _ports(client, dev["id"])  # сам порт остался


def test_occupied_peer_returns_409_and_rolls_back_the_new_ports(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    first, second = _device(client, "SRV-6"), _device(client, "SRV-7")
    assert _sync(client, first["id"], [{"name": "eth0", "connection": _conn(peer, ct)}]).status_code == 200

    r = _sync(client, second["id"], [{"name": "brand-new-port", "connection": _conn(peer, ct)}])

    assert r.status_code == 409, r.text
    assert "уже участвует" in r.json()["detail"]
    assert _ports(client, second["id"]) == {}  # транзакция откатилась целиком, порт не создан
    assert len(_connections(client)) == 1


def test_invalid_connection_payload_is_rejected_with_422(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-8")

    cases = [
        ({"peer_interface_id": peer["id"]}, "тип физической линии"),
        ({"connection_type_id": ct["id"]}, "соседнее устройство"),
        ({"peer_interface_id": "no-such-port", "connection_type_id": ct["id"]}, "порт для подключения не найден"),
        ({"peer_interface_id": peer["id"], "connection_type_id": "no-such-type"}, "тип физической линии связи не найден"),
        ("eth1", "объектом или null"),
    ]
    for connection, expected in cases:
        r = _sync(client, dev["id"], [{"name": "eth0", "connection": connection}])
        assert r.status_code == 422, (connection, r.text)
        assert expected in r.json()["detail"], (connection, r.json())
    assert _ports(client, dev["id"]) == {} and _connections(client) == []


def test_port_cannot_be_connected_to_itself(client):
    ct = _connection_type(client)
    dev = _device(client, "SRV-9")
    _sync(client, dev["id"], [{"name": "eth0"}])
    own = _ports(client, dev["id"])["eth0"]

    r = _sync(client, dev["id"], [{"id": own["id"], "name": "eth0", "connection": _conn(own, ct)}])

    assert r.status_code == 422 and "самому себе" in r.json()["detail"]


def test_removing_a_connected_port_gives_a_clear_409_and_works_after_disconnect(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-10")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, ct)}, {"name": "eth1"}])
    ports = _ports(client, dev["id"])

    blocked = _sync(client, dev["id"], [{"id": ports["eth1"]["id"], "name": "eth1"}])

    assert blocked.status_code == 409
    assert "«eth0»" in blocked.json()["detail"] and "FOREIGN KEY" not in blocked.json()["detail"]
    assert len(_ports(client, dev["id"])) == 2  # ничего не удалено

    assert _sync(client, dev["id"], [{"id": ports["eth0"]["id"], "name": "eth0", "connection": None}, {"id": ports["eth1"]["id"], "name": "eth1"}]).status_code == 200
    assert _sync(client, dev["id"], [{"id": ports["eth1"]["id"], "name": "eth1"}]).status_code == 200
    assert list(_ports(client, dev["id"])) == ["eth1"]


def test_connection_changes_are_written_to_the_audit_log(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-11")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, ct)}])
    own = _ports(client, dev["id"])["eth0"]
    _sync(client, dev["id"], [{"id": own["id"], "name": "eth0", "connection": None}])

    items = client.get(f"{API}/resources/audit-log", params={"entity_type": "connections", "limit": 50}).json()["items"]

    assert sorted(x["action"] for x in items) == ["CREATE", "DELETE"]


def test_port_freed_in_the_same_request_can_be_taken_regardless_of_row_order(client):
    peer = _peer_port(client)
    ct = _connection_type(client)
    dev = _device(client, "SRV-12")
    _sync(client, dev["id"], [{"name": "eth0", "connection": _conn(peer, ct)}, {"name": "eth1"}])
    ports = _ports(client, dev["id"])

    # eth1 (раньше в списке) занимает порт соседа, который eth0 освобождает в этом же запросе.
    r = _sync(client, dev["id"], [
        {"id": ports["eth1"]["id"], "name": "eth1", "connection": _conn(peer, ct)},
        {"id": ports["eth0"]["id"], "name": "eth0", "connection": None},
    ])

    assert r.status_code == 200, r.text
    (conn,) = _connections(client)
    assert conn["source_interface_id"] == ports["eth1"]["id"] and conn["destination_interface_id"] == peer["id"]


def test_connection_has_no_incoming_references():
    """Основание для прямого удаления подключения при «Отключить» (см. ALLOWED_DELETIONS в
    test_deletion_guards.py): на таблицу connections не ссылается ни один внешний ключ. Появится ссылка —
    удаление должно пойти через crud.assert_deletable(), а не напрямую."""
    from app.models import Base

    referencing = sorted(
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "connections"
    )
    assert referencing == []


# ---------------------------------------------------------------------------------------------
# Обмен соседями в одном запросе и ссылки peer_row (порты без id, порты одного устройства)
# ---------------------------------------------------------------------------------------------

def _device_with_ports(client, serial: str, names: list[str]) -> tuple[dict, dict[str, dict]]:
    dev = _device(client, serial)
    assert _sync(client, dev["id"], [{"name": n} for n in names]).status_code == 200
    return dev, _ports(client, dev["id"])


def _by_ports(client) -> dict[frozenset, dict]:
    return {frozenset((c["source_interface_id"], c["destination_interface_id"])): c for c in _connections(client)}


def test_two_ports_can_swap_their_neighbours_in_one_request(client):
    """A: eth0—g1, eth1—g2  →  eth0—g2, eth1—g1. До плана подключений это упиралось в 409: порт
    g2 в момент проверки eth0 ещё был занят подключением eth1."""
    _, theirs = _device_with_ports(client, "SW-SWAP", ["g1", "g2"])
    ct = _connection_type(client)
    dev, own = _device_with_ports(client, "SRV-SWAP", ["eth0", "eth1"])
    assert _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g1"], ct)},
        {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g2"], ct)},
    ]).status_code == 200
    before = {frozenset((c["source_interface_id"], c["destination_interface_id"])): c["id"] for c in _connections(client)}

    r = _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g2"], ct)},
        {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g1"], ct)},
    ])

    assert r.status_code == 200, r.text
    after = _by_ports(client)
    assert set(after) == {frozenset((own["eth0"]["id"], theirs["g2"]["id"])), frozenset((own["eth1"]["id"], theirs["g1"]["id"]))}
    # Подключения переставлены на месте: те же записи, а не удалены и созданы заново.
    assert {c["id"] for c in after.values()} == set(before.values())


def test_swap_fails_with_409_when_the_other_side_is_not_part_of_the_request(client):
    """Порт соседа занят подключением, которое этот запрос не трогает, — освобождать его нечем."""
    _, theirs = _device_with_ports(client, "SW-NOSWAP", ["g1", "g2"])
    ct = _connection_type(client)
    dev, own = _device_with_ports(client, "SRV-NOSWAP", ["eth0", "eth1"])
    _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g1"], ct)},
        {"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(theirs["g2"], ct)},
    ])

    r = _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(theirs["g2"], ct)},
        {"id": own["eth1"]["id"], "name": "eth1"},  # ключа connection нет — подключение eth1—g2 остаётся
    ])

    assert r.status_code == 409, r.text
    assert frozenset((own["eth0"]["id"], theirs["g1"]["id"])) in _by_ports(client)  # откат: eth0 по-прежнему на g1


def test_two_new_ports_of_the_same_device_are_connected_via_peer_row(client):
    ct = _connection_type(client)
    dev = _device(client, "SRV-LOOP")

    r = _sync(client, dev["id"], [
        {"name": "eth0", "connection": {"peer_row": 1, "connection_type_id": ct["id"], "description": "перемычка"}},
        {"name": "eth1"},
    ])

    assert r.status_code == 200, r.text
    ports = _ports(client, dev["id"])
    (conn,) = _connections(client)
    assert (conn["source_interface_id"], conn["destination_interface_id"]) == (ports["eth0"]["id"], ports["eth1"]["id"])
    assert conn["description"] == "перемычка"


def test_saved_port_is_connected_to_a_new_port_of_the_same_device_via_peer_row(client):
    ct = _connection_type(client)
    dev, own = _device_with_ports(client, "SRV-MIX", ["eth0"])

    r = _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": {"peer_row": 1, "connection_type_id": ct["id"]}},
        {"name": "eth1"},
    ])

    assert r.status_code == 200, r.text
    (conn,) = _connections(client)
    assert {conn["source_interface_id"], conn["destination_interface_id"]} == {own["eth0"]["id"], _ports(client, dev["id"])["eth1"]["id"]}


def test_two_saved_ports_of_the_same_device_can_be_connected_by_id(client):
    ct = _connection_type(client)
    dev, own = _device_with_ports(client, "SRV-SAME", ["eth0", "eth1"])

    r = _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": _conn(own["eth1"], ct)},
        {"id": own["eth1"]["id"], "name": "eth1"},
    ])

    assert r.status_code == 200, r.text
    assert len(_connections(client)) == 1


def test_a_cable_described_from_both_sides_is_one_connection(client):
    ct = _connection_type(client)
    dev = _device(client, "SRV-BOTH")

    r = _sync(client, dev["id"], [
        {"name": "eth0", "connection": {"peer_row": 1, "connection_type_id": ct["id"]}},
        {"name": "eth1", "connection": {"peer_row": 0, "connection_type_id": ct["id"]}},
    ])

    assert r.status_code == 200, r.text
    assert len(_connections(client)) == 1


def test_a_cable_described_from_both_sides_with_different_parameters_is_rejected(client):
    twisted, fiber = _connection_type(client), _connection_type(client, "Оптическое волокно")
    dev = _device(client, "SRV-BOTH-DIFF")

    r = _sync(client, dev["id"], [
        {"name": "eth0", "connection": {"peer_row": 1, "connection_type_id": twisted["id"]}},
        {"name": "eth1", "connection": {"peer_row": 0, "connection_type_id": fiber["id"]}},
    ])

    assert r.status_code == 422 and "задано дважды" in r.json()["detail"], r.text
    assert _ports(client, dev["id"]) == {} and _connections(client) == []


def test_a_port_cannot_be_claimed_by_two_different_connections_of_one_request(client):
    ct = _connection_type(client)
    dev = _device(client, "SRV-CLAIM")

    r = _sync(client, dev["id"], [
        {"name": "eth0", "connection": {"peer_row": 2, "connection_type_id": ct["id"]}},
        {"name": "eth1", "connection": {"peer_row": 2, "connection_type_id": ct["id"]}},
        {"name": "eth2"},
    ])

    assert r.status_code == 409 and "«eth2»" in r.json()["detail"], r.text
    assert _ports(client, dev["id"]) == {} and _connections(client) == []


def test_invalid_peer_row_values_are_rejected(client):
    ct = _connection_type(client)
    peer = _peer_port(client, "SW-ROWS")
    dev = _device(client, "SRV-ROWS")

    cases = [
        ({"peer_row": 5, "connection_type_id": ct["id"]}, "нет элемента с номером 5"),
        ({"peer_row": -1, "connection_type_id": ct["id"]}, "неотрицательным целым"),
        ({"peer_row": True, "connection_type_id": ct["id"]}, "неотрицательным целым"),
        ({"peer_row": "1", "connection_type_id": ct["id"]}, "неотрицательным целым"),
        ({"peer_row": 0, "connection_type_id": ct["id"]}, "самому себе"),
        ({"peer_row": 1, "peer_interface_id": peer["id"], "connection_type_id": ct["id"]}, "одним из полей"),
    ]
    for connection, expected in cases:
        r = _sync(client, dev["id"], [{"name": "eth0", "connection": connection}, {"name": "eth1"}])
        assert r.status_code == 422, (connection, r.text)
        assert expected in r.json()["detail"], (connection, r.json())
    assert _ports(client, dev["id"]) == {} and _connections(client) == []


def test_peer_row_pointing_at_a_busy_saved_port_still_returns_409(client):
    ct = _connection_type(client)
    peer = _peer_port(client, "SW-BUSY")
    dev, own = _device_with_ports(client, "SRV-BUSY", ["eth0", "eth1"])
    _sync(client, dev["id"], [{"id": own["eth1"]["id"], "name": "eth1", "connection": _conn(peer, ct)}, {"id": own["eth0"]["id"], "name": "eth0"}])

    r = _sync(client, dev["id"], [
        {"id": own["eth0"]["id"], "name": "eth0", "connection": {"peer_row": 1, "connection_type_id": ct["id"]}},
        {"id": own["eth1"]["id"], "name": "eth1"},
    ])

    assert r.status_code == 409 and "уже участвует" in r.json()["detail"], r.text
