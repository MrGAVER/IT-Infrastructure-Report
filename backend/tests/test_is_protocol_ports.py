"""Открытые порты информационных систем («Протоколы передачи данных», ISProtocol) ведут себя как у ВМ.

Правила те же, что у открытых портов ВМ и порта устройства (tests/test_open_port_uniqueness.py,
tests/test_vm_open_ports_sync.py):
  * номер порта в пределах одной ИС не повторяется — и в PUT .../details, и в общем CRUD /is-protocols;
  * строки-плейсхолдеры без записи справочника пропускаются, несуществующая запись — понятная 422;
  * синхронизация идёт по id (diff): записи не пересоздаются, обмен номерами между строками допустим;
  * список читается по возрастанию номера порта;
  * уже существующие повторы показывает GET /integrity/open-port-duplicates и они не блокируют правку описания.

Плюс то же правило «не пересоздавать» для открытых портов портов устройства, которыми управляет группа.
"""

from __future__ import annotations

API = "/api/v1"


def _catalog(client, port: int, protocol_type: str) -> dict:
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    if match:
        return match
    r = client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type})
    assert r.status_code == 201, r.text
    return r.json()


def _system(client, name: str = "ИС с портами") -> dict:
    r = client.post(f"{API}/resources/information-systems", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _put_details(client, system_id: str, protocols: list[dict]):
    return client.put(f"{API}/resources/information-systems/{system_id}/details", json={"protocols": protocols})


def _stored(client, system_id: str) -> list[dict]:
    return client.get(f"{API}/resources/information-systems/{system_id}/details").json()["protocols"]


class TestDetailsSync:
    def test_duplicate_numbers_are_rejected_and_nothing_is_saved(self, client):
        system = _system(client)
        http, proxy = _catalog(client, 80, "HTTP"), _catalog(client, 80, "HTTP-Proxy-Test")
        ssh = _catalog(client, 22, "SSH")

        r = _put_details(client, system["id"], [{"protocol_catalog_id": http["id"]}, {"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": proxy["id"]}])

        assert r.status_code == 422, r.text
        assert "ИС с портами" in r.json()["detail"] and "80" in r.json()["detail"]
        assert _stored(client, system["id"]) == []

    def test_same_number_in_different_systems_is_fine(self, client):
        http = _catalog(client, 80, "HTTP")
        for name in ("ИС-1", "ИС-2"):
            system = _system(client, name)
            assert _put_details(client, system["id"], [{"protocol_catalog_id": http["id"]}]).status_code == 200

    def test_placeholder_rows_are_skipped_and_cleared_rows_are_removed(self, client):
        system = _system(client)
        ssh, http = _catalog(client, 22, "SSH"), _catalog(client, 80, "HTTP")
        saved = _put_details(client, system["id"], [{"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": http["id"]}]).json()["protocols"]
        ssh_row = next(p for p in saved if p["protocol_catalog_id"] == ssh["id"])
        http_row = next(p for p in saved if p["protocol_catalog_id"] == http["id"])

        # Строка http очищена (выбор снят) + пустой плейсхолдер: первая удаляется, второй игнорируется.
        r = _put_details(client, system["id"], [{"id": ssh_row["id"], "protocol_catalog_id": ssh["id"]}, {"id": http_row["id"], "protocol_catalog_id": ""}, {"protocol_catalog_id": ""}])

        assert r.status_code == 200, r.text
        assert [p["id"] for p in r.json()["protocols"]] == [ssh_row["id"]]

    def test_unknown_catalog_entry_is_a_clear_422_and_rolls_everything_back(self, client):
        system = _system(client)
        ssh = _catalog(client, 22, "SSH")

        r = _put_details(client, system["id"], [{"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": "no-such-entry"}])

        assert r.status_code == 422, r.text
        assert "справочник" in r.json()["detail"]
        assert _stored(client, system["id"]) == []

    def test_rows_are_updated_in_place_and_numbers_can_be_swapped(self, client):
        system = _system(client)
        ssh, http = _catalog(client, 22, "SSH"), _catalog(client, 80, "HTTP")
        first = _put_details(client, system["id"], [{"protocol_catalog_id": ssh["id"], "description": "админка"}, {"protocol_catalog_id": http["id"]}]).json()["protocols"]
        by_catalog = {p["protocol_catalog_id"]: p for p in first}

        # Две строки меняются номерами за один запрос — это не повтор, записи остаются теми же.
        r = _put_details(
            client,
            system["id"],
            [
                {"id": by_catalog[ssh["id"]]["id"], "protocol_catalog_id": http["id"], "description": "админка"},
                {"id": by_catalog[http["id"]]["id"], "protocol_catalog_id": ssh["id"]},
            ],
        )

        assert r.status_code == 200, r.text
        after = {p["id"]: p for p in r.json()["protocols"]}
        assert set(after) == {p["id"] for p in first}
        assert after[by_catalog[ssh["id"]]["id"]]["protocol_catalog_id"] == http["id"]
        assert after[by_catalog[ssh["id"]]["id"]]["created_at"] == by_catalog[ssh["id"]]["created_at"]

    def test_protocols_are_returned_by_ascending_port_number(self, client):
        system = _system(client)
        entries = [_catalog(client, port, name) for port, name in ((443, "HTTPS"), (22, "SSH"), (8080, "HTTP-Alt"), (80, "HTTP"))]

        _put_details(client, system["id"], [{"protocol_catalog_id": e["id"]} for e in entries])

        assert [p["protocol_catalog_id"] for p in _stored(client, system["id"])] == [e["id"] for e in sorted(entries, key=lambda e: e["port"])]


class TestGenericResource:
    def _protocol(self, client, system_id: str, catalog_id: str, **extra):
        return client.post(f"{API}/resources/is-protocols", json={"information_system_id": system_id, "protocol_catalog_id": catalog_id, **extra})

    def test_second_protocol_with_same_number_is_rejected(self, client):
        system = _system(client)
        http, proxy = _catalog(client, 80, "HTTP"), _catalog(client, 80, "HTTP-Proxy-Test")
        assert self._protocol(client, system["id"], http["id"]).status_code == 201

        r = self._protocol(client, system["id"], proxy["id"])

        assert r.status_code == 422, r.text
        assert "80" in r.json()["detail"]
        assert len(_stored(client, system["id"])) == 1

    def test_update_to_a_number_used_by_a_sibling_is_rejected(self, client):
        system = _system(client)
        http, ssh = _catalog(client, 80, "HTTP"), _catalog(client, 22, "SSH")
        self._protocol(client, system["id"], http["id"])
        ssh_row = self._protocol(client, system["id"], ssh["id"]).json()

        r = client.put(f"{API}/resources/is-protocols/{ssh_row['id']}", json={"protocol_catalog_id": http["id"]})

        assert r.status_code == 422, r.text

    def test_unrelated_edit_of_a_legacy_duplicate_row_still_works(self, client, db_session):
        from app.models import ISProtocol

        system = _system(client)
        http, proxy = _catalog(client, 80, "HTTP"), _catalog(client, 80, "HTTP-Proxy-Test")
        legacy = [ISProtocol(information_system_id=system["id"], protocol_catalog_id=c["id"]) for c in (http, proxy)]
        db_session.add_all(legacy)
        db_session.commit()

        r = client.put(f"{API}/resources/is-protocols/{legacy[0].id}", json={"description": "правка описания"})

        assert r.status_code == 200, r.text


class TestDiagnostics:
    def test_report_lists_information_systems_with_repeated_numbers(self, client, db_session):
        from app.models import ISProtocol

        system = _system(client, "ИС с дублями")
        http, proxy = _catalog(client, 80, "HTTP"), _catalog(client, 80, "HTTP-Proxy-Test")
        db_session.add_all([ISProtocol(information_system_id=system["id"], protocol_catalog_id=c["id"]) for c in (http, proxy)])
        db_session.commit()

        r = client.get(f"{API}/integrity/open-port-duplicates")

        assert r.status_code == 200, r.text
        assert r.json()["duplicates"] == [{"owner_type": "information_system", "owner_id": system["id"], "owner_name": "ИС с дублями", "port": 80, "count": 2}]


class TestGroupManagedPorts:
    """Порты, которыми управляет группа, при смене списка группы обновляются на месте, а не пересоздаются."""

    def _device(self, client) -> dict:
        category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        dt = client.post(f"{API}/resources/device-types", json={"name": "Тип группы портов", "category_id": category_id}).json()
        return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-GRP-INPLACE"}).json()

    def _apply(self, client, device_id: str, group_ports: list[dict], iface_id: str | None = None):
        group = {"key": "g1", "name": "Серверные", "manage_open_ports": True, "open_ports": group_ports}
        iface = {"name": "Gi0/1", "group_key": "g1", **({"id": iface_id} if iface_id else {})}
        return client.put(f"{API}/devices/{device_id}/interfaces", json={"interfaces": [iface], "groups": [group]})

    def _ports(self, client, iface_id: str) -> list[dict]:
        return client.get(f"{API}/resources/open-ports", params={"owner_type": "device_interface", "owner_id": iface_id, "limit": 100}).json()["items"]

    def test_changed_group_port_reuses_the_existing_row(self, client):
        dev = self._device(client)
        ssh, telnet, http = _catalog(client, 22, "SSH"), _catalog(client, 23, "Telnet"), _catalog(client, 80, "HTTP")
        r = self._apply(client, dev["id"], [{"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": http["id"]}])
        assert r.status_code == 200, r.text
        iface_id = r.json()["items"][0]["id"]
        before = {p["protocol_catalog_id"]: p for p in self._ports(client, iface_id)}

        group_id = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]["id"]
        group = {"id": group_id, "key": group_id, "name": "Серверные", "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": telnet["id"]}, {"protocol_catalog_id": http["id"]}]}
        # Клиент присылает порт с уже сохранёнными строками (как отправляет форма), а группа задаёт новый список.
        current = [{"id": p["id"], "protocol_catalog_id": p["protocol_catalog_id"]} for p in before.values()]
        r = client.put(f"{API}/devices/{dev['id']}/interfaces", json={"interfaces": [{"id": iface_id, "name": "Gi0/1", "group_key": group_id, "open_ports": current}], "groups": [group]})
        assert r.status_code == 200, r.text

        after = self._ports(client, iface_id)
        assert {p["protocol_catalog_id"] for p in after} == {telnet["id"], http["id"]}
        # Строка SSH переиспользована под Telnet (тот же id и дата создания), HTTP остался нетронутым.
        reused = next(p for p in after if p["protocol_catalog_id"] == telnet["id"])
        assert reused["id"] == before[ssh["id"]]["id"] and reused["created_at"] == before[ssh["id"]]["created_at"]
        assert next(p for p in after if p["protocol_catalog_id"] == http["id"])["id"] == before[http["id"]]["id"]

    def test_extra_rows_are_removed_and_missing_ones_created(self, client):
        dev = self._device(client)
        ssh, telnet, http = _catalog(client, 22, "SSH"), _catalog(client, 23, "Telnet"), _catalog(client, 80, "HTTP")
        r = self._apply(client, dev["id"], [{"protocol_catalog_id": ssh["id"]}])
        iface_id = r.json()["items"][0]["id"]
        group_id = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]["id"]

        def apply(ports):
            group = {"id": group_id, "key": group_id, "name": "Серверные", "manage_open_ports": True, "open_ports": ports}
            return client.put(f"{API}/devices/{dev['id']}/interfaces", json={"interfaces": [{"id": iface_id, "name": "Gi0/1", "group_key": group_id}], "groups": [group]})

        assert apply([{"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": telnet["id"]}, {"protocol_catalog_id": http["id"]}]).status_code == 200
        assert {p["protocol_catalog_id"] for p in self._ports(client, iface_id)} == {ssh["id"], telnet["id"], http["id"]}

        assert apply([{"protocol_catalog_id": http["id"]}]).status_code == 200
        assert [p["protocol_catalog_id"] for p in self._ports(client, iface_id)] == [http["id"]]
