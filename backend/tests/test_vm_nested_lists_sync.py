"""Атомарная синхронизация IP-адресов и программных активов ВМ:
PUT /api/v1/vms/{id}/ip-addresses и PUT /api/v1/vms/{id}/deployed-software.

Так же, как открытые порты (см. test_vm_open_ports_sync.py): раньше форма ВМ при каждом сохранении
удаляла все записи списка и создавала их заново. Теперь сервер сравнивает присланный список с БД по
id (services/crud.py:_sync_owned_rows) — id и дата создания сохраняются, любая ошибка откатывает весь
запрос, а в журнал аудита попадает только реальное изменение.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog

API = "/api/v1"


def _vm(client, name: str = "vm-nested") -> dict:
    r = client.post(f"{API}/resources/vms", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _asset(client, name: str) -> dict:
    r = client.post(f"{API}/resources/software-assets", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _put(client, vm_id: str, path: str, key: str, rows: list[dict] | None):
    body = {} if rows is None else {key: rows}
    return client.put(f"{API}/vms/{vm_id}/{path}", json=body)


def _sync_ips(client, vm_id: str, rows: list[dict] | None):
    return _put(client, vm_id, "ip-addresses", "ip_addresses", rows)


def _sync_software(client, vm_id: str, rows: list[dict] | None):
    return _put(client, vm_id, "deployed-software", "deployed_software", rows)


def _stored(client, resource: str, vm_id: str) -> list[dict]:
    return client.get(f"{API}/resources/{resource}", params={"owner_type": "virtual_machine", "owner_id": vm_id, "limit": 1000}).json()["items"]


def _audit(db_session, vm_id: str, label: str) -> list[str]:
    rows = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "vms", AuditLog.entity_id == vm_id, AuditLog.details.like(f"{label}:%"))).all()
    return [r.details for r in rows]


def _ip(address: str, **extra) -> dict:
    return {"ip_address": address, "prefix_length": 24, "purpose": None, "is_management": False, **extra}


def _sw(asset: dict, **extra) -> dict:
    return {"software_asset_id": asset["id"], "version": None, **extra}


class TestSyncVmIpAddresses:
    def test_creates_ips_and_returns_them_ordered_by_address(self, client):
        vm = _vm(client)

        r = _sync_ips(client, vm["id"], [_ip("10.0.0.20"), _ip("10.0.0.5", purpose="LAN", is_management=True)])

        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert [i["ip_address"] for i in items] == ["10.0.0.20", "10.0.0.5"]  # порядок строк как у текста адреса
        by_ip = {i["ip_address"]: i for i in items}
        assert (by_ip["10.0.0.5"]["purpose"], by_ip["10.0.0.5"]["is_management"], by_ip["10.0.0.5"]["prefix_length"]) == ("LAN", True, 24)

    def test_existing_ips_keep_ids_and_creation_time_on_resave(self, client):
        vm = _vm(client)
        first = {i["ip_address"]: i for i in _sync_ips(client, vm["id"], [_ip("10.0.0.1"), _ip("10.0.0.2")]).json()["items"]}

        r = _sync_ips(client, vm["id"], [_ip("10.0.0.1", id=first["10.0.0.1"]["id"]), _ip("10.0.0.2", id=first["10.0.0.2"]["id"])])

        again = {i["ip_address"]: i for i in r.json()["items"]}
        assert {k: v["id"] for k, v in again.items()} == {k: v["id"] for k, v in first.items()}
        assert {k: v["created_at"] for k, v in again.items()} == {k: v["created_at"] for k, v in first.items()}
        assert len(_stored(client, "ip-addresses", vm["id"])) == 2

    def test_edit_updates_in_place_add_creates_and_missing_is_deleted(self, client):
        vm = _vm(client)
        first = {i["ip_address"]: i for i in _sync_ips(client, vm["id"], [_ip("10.0.0.1"), _ip("10.0.0.2")]).json()["items"]}

        r = _sync_ips(client, vm["id"], [_ip("10.0.0.1", id=first["10.0.0.1"]["id"], prefix_length="16", purpose="админ", is_management=True), _ip("10.0.0.3")])

        assert r.status_code == 200, r.text
        by_ip = {i["ip_address"]: i for i in r.json()["items"]}
        assert sorted(by_ip) == ["10.0.0.1", "10.0.0.3"]
        assert by_ip["10.0.0.1"]["id"] == first["10.0.0.1"]["id"]
        assert (by_ip["10.0.0.1"]["prefix_length"], by_ip["10.0.0.1"]["purpose"], by_ip["10.0.0.1"]["is_management"]) == (16, "админ", True)
        assert first["10.0.0.2"]["id"] not in {i["id"] for i in _stored(client, "ip-addresses", vm["id"])}

    def test_empty_prefix_is_stored_as_null_and_blank_rows_are_skipped(self, client):
        vm = _vm(client)

        r = _sync_ips(client, vm["id"], [_ip("10.0.0.1", prefix_length=""), {"ip_address": "  ", "prefix_length": ""}])

        assert [(i["ip_address"], i["prefix_length"]) for i in r.json()["items"]] == [("10.0.0.1", None)]
        assert _sync_ips(client, vm["id"], []).json()["items"] == []
        assert _stored(client, "ip-addresses", vm["id"]) == []

    def test_ips_of_another_vm_are_not_touched(self, client):
        vm, other = _vm(client, "vm-a"), _vm(client, "vm-b")
        _sync_ips(client, other["id"], [_ip("10.9.9.9")])

        _sync_ips(client, vm["id"], [_ip("10.0.0.1")])
        _sync_ips(client, vm["id"], [])

        assert [i["ip_address"] for i in _stored(client, "ip-addresses", other["id"])] == ["10.9.9.9"]


class TestSyncVmIpAddressesValidation:
    def test_invalid_ip_is_rejected_and_nothing_changes(self, client):
        vm = _vm(client)
        _sync_ips(client, vm["id"], [_ip("10.0.0.1")])

        r = _sync_ips(client, vm["id"], [_ip("10.0.0.2"), _ip("не ip адрес")])

        assert r.status_code == 422, r.text
        assert [i["ip_address"] for i in _stored(client, "ip-addresses", vm["id"])] == ["10.0.0.1"]  # откат: 10.0.0.2 не создан, 10.0.0.1 не удалён

    def test_invalid_prefix_and_too_long_purpose_are_rejected(self, client):
        vm = _vm(client)

        assert _sync_ips(client, vm["id"], [_ip("10.0.0.1", prefix_length=99)]).status_code == 422
        assert _sync_ips(client, vm["id"], [_ip("10.0.0.1", purpose="x" * 256)]).status_code == 422
        assert _stored(client, "ip-addresses", vm["id"]) == []

    def test_foreign_ip_id_is_rejected_and_rolls_back_the_whole_request(self, client):
        vm, other = _vm(client, "vm-a"), _vm(client, "vm-b")
        foreign = _sync_ips(client, other["id"], [_ip("10.9.9.9")]).json()["items"][0]

        r = _sync_ips(client, vm["id"], [_ip("10.0.0.1"), _ip("10.9.9.9", id=foreign["id"])])

        assert r.status_code == 422, r.text
        assert _stored(client, "ip-addresses", vm["id"]) == []
        assert [i["id"] for i in _stored(client, "ip-addresses", other["id"])] == [foreign["id"]]

    def test_same_id_twice_missing_key_and_unknown_vm(self, client):
        vm = _vm(client)
        item = _sync_ips(client, vm["id"], [_ip("10.0.0.1")]).json()["items"][0]

        assert _sync_ips(client, vm["id"], [_ip("10.0.0.1", id=item["id"]), _ip("10.0.0.2", id=item["id"])]).status_code == 422
        assert _sync_ips(client, vm["id"], None).status_code == 422  # не молчаливое удаление всех IP
        assert len(_stored(client, "ip-addresses", vm["id"])) == 1
        assert _sync_ips(client, "нет-такой-вм", []).status_code == 404


class TestSyncVmDeployedSoftware:
    def test_creates_edits_in_place_and_deletes_missing(self, client):
        vm = _vm(client)
        one_c, nginx, ad = _asset(client, "1С:Предприятие"), _asset(client, "nginx"), _asset(client, "Active Directory")
        first = {i["software_asset_id"]: i for i in _sync_software(client, vm["id"], [_sw(one_c, version="8.3.20"), _sw(nginx)]).json()["items"]}
        assert len(first) == 2

        r = _sync_software(client, vm["id"], [_sw(one_c, id=first[one_c["id"]]["id"], version="8.3.24"), _sw(ad)])

        assert r.status_code == 200, r.text
        by_asset = {i["software_asset_id"]: i for i in r.json()["items"]}
        assert sorted(by_asset) == sorted([one_c["id"], ad["id"]])
        assert by_asset[one_c["id"]]["id"] == first[one_c["id"]]["id"]
        assert by_asset[one_c["id"]]["version"] == "8.3.24"
        assert first[nginx["id"]]["id"] not in {i["id"] for i in _stored(client, "deployed-software", vm["id"])}

    def test_resave_keeps_ids_and_creation_time(self, client):
        vm = _vm(client)
        one_c = _asset(client, "1С:Предприятие")
        first = _sync_software(client, vm["id"], [_sw(one_c, version="8.3.20")]).json()["items"][0]

        again = _sync_software(client, vm["id"], [_sw(one_c, id=first["id"], version="8.3.20")]).json()["items"][0]

        assert (again["id"], again["created_at"]) == (first["id"], first["created_at"])

    def test_blank_rows_are_skipped_and_empty_list_clears(self, client):
        vm = _vm(client)
        one_c = _asset(client, "1С:Предприятие")

        r = _sync_software(client, vm["id"], [_sw(one_c), {"software_asset_id": "", "version": "8.3"}])
        assert len(r.json()["items"]) == 1

        assert _sync_software(client, vm["id"], []).json()["items"] == []
        assert _stored(client, "deployed-software", vm["id"]) == []


class TestSyncVmDeployedSoftwareValidation:
    def test_unknown_asset_is_a_422_and_nothing_changes(self, client):
        vm = _vm(client)
        one_c = _asset(client, "1С:Предприятие")
        _sync_software(client, vm["id"], [_sw(one_c)])

        r = _sync_software(client, vm["id"], [{"software_asset_id": "нет-такого-актива", "version": None}])

        assert r.status_code == 422, r.text
        assert [i["software_asset_id"] for i in _stored(client, "deployed-software", vm["id"])] == [one_c["id"]]

    def test_too_long_version_is_rejected(self, client):
        vm = _vm(client)
        one_c = _asset(client, "1С:Предприятие")

        assert _sync_software(client, vm["id"], [_sw(one_c, version="9" * 101)]).status_code == 422
        assert _stored(client, "deployed-software", vm["id"]) == []

    def test_foreign_id_missing_key_and_unknown_vm(self, client):
        vm, other = _vm(client, "vm-a"), _vm(client, "vm-b")
        one_c = _asset(client, "1С:Предприятие")
        foreign = _sync_software(client, other["id"], [_sw(one_c)]).json()["items"][0]

        assert _sync_software(client, vm["id"], [_sw(one_c, id=foreign["id"])]).status_code == 422
        assert _sync_software(client, vm["id"], None).status_code == 422
        assert [i["id"] for i in _stored(client, "deployed-software", other["id"])] == [foreign["id"]]
        assert _sync_software(client, "нет-такой-вм", []).status_code == 404


class TestSyncVmNestedListsAudit:
    def test_audit_records_only_real_changes(self, client, db_session):
        vm = _vm(client)
        first = {i["ip_address"]: i for i in _sync_ips(client, vm["id"], [_ip("10.0.0.1"), _ip("10.0.0.2")]).json()["items"]}
        assert _audit(db_session, vm["id"], "IP-адреса") == ["IP-адреса: добавлено 2, изменено 0, удалено 0"]

        _sync_ips(client, vm["id"], [_ip("10.0.0.1", id=first["10.0.0.1"]["id"]), _ip("10.0.0.2", id=first["10.0.0.2"]["id"])])  # без правок
        assert len(_audit(db_session, vm["id"], "IP-адреса")) == 1

        _sync_ips(client, vm["id"], [_ip("10.0.0.1", id=first["10.0.0.1"]["id"], purpose="админ")])
        assert _audit(db_session, vm["id"], "IP-адреса")[-1] == "IP-адреса: добавлено 0, изменено 1, удалено 1"

    def test_software_audit_label(self, client, db_session):
        vm = _vm(client)
        _sync_software(client, vm["id"], [_sw(_asset(client, "nginx"))])

        assert _audit(db_session, vm["id"], "Программные активы") == ["Программные активы: добавлено 1, изменено 0, удалено 0"]
