"""Атомарная синхронизация открытых портов ВМ: PUT /api/v1/vms/{id}/open-ports.

Раньше форма ВМ при каждом сохранении удаляла все порты ВМ и создавала их заново. Теперь сервер
сравнивает присланный список с БД по id (services/crud.py:sync_vm_open_ports): порты с id обновляются
на месте, без id создаются, отсутствующие в списке удаляются — id и дата создания сохраняются, а в
журнал аудита попадает только реальное изменение.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.models import AuditLog
from app.reporting import _open_ports_by_number

API = "/api/v1"


def _catalog(client, port: int, protocol_type: str) -> dict:
    """Запись справочника «Протоколы и порты» (часть уже засеяна по умолчанию — ищем, не создаём вслепую)."""
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    if match:
        return match
    r = client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type})
    assert r.status_code == 201, r.text
    return r.json()


def _vm(client, name: str = "vm-sync") -> dict:
    r = client.post(f"{API}/resources/vms", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _sync(client, vm_id: str, rows: list[dict] | None):
    body = {} if rows is None else {"open_ports": rows}
    return client.put(f"{API}/vms/{vm_id}/open-ports", json=body)


def _row(catalog: dict, **extra) -> dict:
    return {"protocol_catalog_id": catalog["id"], "transport_protocol": "TCP", "description": None, **extra}


def _stored(client, vm_id: str) -> list[dict]:
    return client.get(f"{API}/resources/open-ports", params={"owner_type": "virtual_machine", "owner_id": vm_id, "limit": 1000}).json()["items"]


def _audit_details(db_session, vm_id: str) -> list[str]:
    rows = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "vms", AuditLog.entity_id == vm_id, AuditLog.details.like("Открытые порты:%"))).all()
    return [r.details for r in rows]


class TestSyncVmOpenPorts:
    def test_creates_ports_and_returns_them_ordered_by_port_number(self, client):
        vm = _vm(client)
        https, ssh = _catalog(client, 443, "HTTPS"), _catalog(client, 22, "SSH")

        r = _sync(client, vm["id"], [_row(https), _row(ssh, description="админ")])

        assert r.status_code == 200, r.text
        assert [p["port"] for p in r.json()["items"]] == [22, 443]
        assert {p["description"] for p in _stored(client, vm["id"])} == {None, "админ"}

    def test_existing_ports_keep_their_ids_and_creation_time_on_resave(self, client):
        vm = _vm(client)
        ssh, https = _catalog(client, 22, "SSH"), _catalog(client, 443, "HTTPS")
        first = {p["port"]: p for p in _sync(client, vm["id"], [_row(ssh), _row(https)]).json()["items"]}

        # Повторное сохранение формы без правок: те же id в запросе.
        r = _sync(client, vm["id"], [_row(ssh, id=first[22]["id"]), _row(https, id=first[443]["id"])])

        assert r.status_code == 200, r.text
        again = {p["port"]: p for p in r.json()["items"]}
        assert {k: v["id"] for k, v in again.items()} == {k: v["id"] for k, v in first.items()}
        assert {k: v["created_at"] for k, v in again.items()} == {k: v["created_at"] for k, v in first.items()}
        assert len(_stored(client, vm["id"])) == 2  # ничего не задвоилось

    def test_edit_updates_in_place_add_creates_and_missing_is_deleted(self, client):
        vm = _vm(client)
        ssh, http, https = _catalog(client, 22, "SSH"), _catalog(client, 80, "HTTP"), _catalog(client, 443, "HTTPS")
        first = {p["port"]: p for p in _sync(client, vm["id"], [_row(ssh), _row(http)]).json()["items"]}

        # ssh: правка описания и транспорта; http: убран из списка; https: добавлен.
        r = _sync(client, vm["id"], [_row(ssh, id=first[22]["id"], transport_protocol="UDP", description="новое"), _row(https)])

        assert r.status_code == 200, r.text
        by_port = {p["port"]: p for p in r.json()["items"]}
        assert sorted(by_port) == [22, 443]
        assert by_port[22]["id"] == first[22]["id"]
        assert (by_port[22]["transport_protocol"], by_port[22]["description"]) == ("UDP", "новое")
        assert first[80]["id"] not in {p["id"] for p in _stored(client, vm["id"])}

    def test_two_rows_can_swap_port_numbers_in_one_request(self, client):
        """Поочерёдное обновление по одному упёрлось бы в проверку уникальности номера (строка A
        ещё занимает номер, который берёт строка B) — атомарная синхронизация проверяет список целиком."""
        vm = _vm(client)
        ssh, https = _catalog(client, 22, "SSH"), _catalog(client, 443, "HTTPS")
        first = {p["port"]: p for p in _sync(client, vm["id"], [_row(ssh), _row(https)]).json()["items"]}

        r = _sync(client, vm["id"], [_row(https, id=first[22]["id"]), _row(ssh, id=first[443]["id"])])

        assert r.status_code == 200, r.text
        assert {p["id"]: p["port"] for p in r.json()["items"]} == {first[22]["id"]: 443, first[443]["id"]: 22}

    def test_blank_placeholder_rows_are_skipped_and_empty_list_clears_ports(self, client):
        vm = _vm(client)
        ssh = _catalog(client, 22, "SSH")

        r = _sync(client, vm["id"], [_row(ssh), {"protocol_catalog_id": "", "transport_protocol": "TCP"}])
        assert [p["port"] for p in r.json()["items"]] == [22]

        r = _sync(client, vm["id"], [])
        assert r.status_code == 200 and r.json()["items"] == []
        assert _stored(client, vm["id"]) == []


class TestSyncVmOpenPortsValidation:
    def test_duplicate_port_numbers_are_rejected_and_nothing_is_changed(self, client):
        vm = _vm(client)
        http, proxy, ssh = _catalog(client, 80, "HTTP"), _catalog(client, 80, "HTTP-Proxy-Sync"), _catalog(client, 22, "SSH")
        _sync(client, vm["id"], [_row(ssh)])

        r = _sync(client, vm["id"], [_row(http), _row(proxy)])

        assert r.status_code == 422, r.text
        assert "80" in r.json()["detail"]
        assert [p["port"] for p in _stored_ports(client, vm["id"])] == [22]  # прежнее состояние осталось

    def test_foreign_port_id_is_rejected_and_rolls_back_the_whole_request(self, client):
        vm, other = _vm(client, "vm-a"), _vm(client, "vm-b")
        ssh, https = _catalog(client, 22, "SSH"), _catalog(client, 443, "HTTPS")
        foreign = _sync(client, other["id"], [_row(ssh)]).json()["items"][0]

        r = _sync(client, vm["id"], [_row(https), _row(ssh, id=foreign["id"])])

        assert r.status_code == 422, r.text
        assert _stored(client, vm["id"]) == []  # новая строка https тоже не сохранилась
        assert [p["id"] for p in _stored(client, other["id"])] == [foreign["id"]]  # порт чужой ВМ не тронут

    def test_same_port_id_twice_is_rejected(self, client):
        vm = _vm(client)
        ssh, https = _catalog(client, 22, "SSH"), _catalog(client, 443, "HTTPS")
        port = _sync(client, vm["id"], [_row(ssh)]).json()["items"][0]

        r = _sync(client, vm["id"], [_row(ssh, id=port["id"]), _row(https, id=port["id"])])

        assert r.status_code == 422, r.text

    def test_unknown_catalog_entry_is_rejected(self, client):
        vm = _vm(client)

        r = _sync(client, vm["id"], [{"protocol_catalog_id": "нет-такого-id", "transport_protocol": "TCP"}])

        assert r.status_code == 422, r.text

    def test_missing_open_ports_key_is_an_error_not_a_silent_wipe(self, client):
        vm = _vm(client)
        ssh = _catalog(client, 22, "SSH")
        _sync(client, vm["id"], [_row(ssh)])

        r = _sync(client, vm["id"], None)

        assert r.status_code == 422, r.text
        assert len(_stored(client, vm["id"])) == 1

    def test_unknown_vm_is_404(self, client):
        assert _sync(client, "нет-такой-вм", []).status_code == 404


def _stored_ports(client, vm_id: str) -> list[dict]:
    """Порты ВМ, отсортированные по номеру (list-ресурс отдаёт их без явной сортировки)."""
    return sorted(_stored(client, vm_id), key=lambda p: p["port"])


class TestSyncVmOpenPortsAudit:
    def test_audit_records_only_real_changes(self, client, db_session):
        vm = _vm(client)
        ssh, https = _catalog(client, 22, "SSH"), _catalog(client, 443, "HTTPS")
        first = {p["port"]: p for p in _sync(client, vm["id"], [_row(ssh), _row(https)]).json()["items"]}
        assert _audit_details(db_session, vm["id"]) == ["Открытые порты: добавлено 2, изменено 0, удалено 0"]

        # Сохранение без правок — новой записи в журнале нет.
        _sync(client, vm["id"], [_row(ssh, id=first[22]["id"]), _row(https, id=first[443]["id"])])
        assert len(_audit_details(db_session, vm["id"])) == 1

        # Правка одного порта и удаление другого.
        _sync(client, vm["id"], [_row(ssh, id=first[22]["id"], description="админ")])
        assert _audit_details(db_session, vm["id"])[-1] == "Открытые порты: добавлено 0, изменено 1, удалено 1"


class TestReportOrdersVmPortsByNumber:
    """Отчёт не должен зависеть от порядка записей в БД: порты ВМ обновляются на месте, порядок вставки
    перестал совпадать с порядком номеров."""

    def test_ports_are_sorted_by_number_then_transport_with_unknown_catalog_last(self):
        d = SimpleNamespace(protocol_catalog={"c22": SimpleNamespace(port=22), "c443": SimpleNamespace(port=443)})
        https = SimpleNamespace(id="a", protocol_catalog_id="c443", transport_protocol="TCP")
        ssh_udp = SimpleNamespace(id="b", protocol_catalog_id="c22", transport_protocol="UDP")
        ssh_tcp = SimpleNamespace(id="c", protocol_catalog_id="c22", transport_protocol="TCP")
        orphan = SimpleNamespace(id="d", protocol_catalog_id="нет", transport_protocol="TCP")

        ordered = _open_ports_by_number([orphan, https, ssh_udp, ssh_tcp], d)

        assert [p.id for p in ordered] == ["c", "b", "a", "d"]
