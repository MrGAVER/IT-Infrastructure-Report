"""Сверка режима порта (trunk / access) и назначенных VLAN у портов-соседей подключения —
через API дашборда: расхождения, список граней, одобрение и его сброс при изменении VLAN/режима.

Запуск: pytest backend/tests/test_connection_port_mode_vlans.py -v
"""
from __future__ import annotations

import pytest

from app.models import Connection, DeviceInterface, InterfaceVLAN, VLAN, VLANDomain
from app.services.port_config import vlan_fingerprint


@pytest.fixture()
def cable(client) -> str:
    return client.post("/api/v1/resources/connection-types", json={"name": "Витая пара (режим/VLAN)"}).json()["id"]


@pytest.fixture()
def device_type(client) -> str:
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    return client.post("/api/v1/resources/device-types", json={"name": "Тип для режима/VLAN", "category_id": category_id}).json()["id"]


class Lab:
    """Пара портов-соседей с одинаковой ролью «передача данных» и управляемыми режимом/VLAN."""

    def __init__(self, client, db_session, device_type: str, cable: str) -> None:
        self.client, self.db, self.cable = client, db_session, cable
        self.vlans: dict[tuple[int, str | None], VLAN] = {}
        self.src = self._port(device_type, "LAB-A")
        self.dst = self._port(device_type, "LAB-B")
        self.connection_id = client.post(
            "/api/v1/resources/connections",
            json={"source_interface_id": self.src, "destination_interface_id": self.dst, "connection_type_id": cable},
        ).json()["id"]

    def _port(self, device_type: str, serial: str) -> str:
        device = self.client.post("/api/v1/resources/devices", json={"device_type_id": device_type, "serial_number": serial, "system_name": serial.lower()}).json()
        response = self.client.put(
            f"/api/v1/devices/{device['id']}/interfaces",
            json={"interfaces": [{"name": "p1", "is_management": False, "is_data_transfer": True}]},
        )
        return response.json()["items"][0]["id"]

    def vlan(self, number: int, domain_id: str | None = None) -> VLAN:
        key = (number, domain_id)
        if key not in self.vlans:
            row = VLAN(vlan_id=number, name=f"vlan{number}", domain_id=domain_id)
            self.db.add(row)
            self.db.flush()
            self.vlans[key] = row
        return self.vlans[key]

    def configure(self, interface_id: str, mode: str | None = None, vlans: tuple[VLAN, ...] | None = None) -> None:
        """Меняет режим и/или набор VLAN порта напрямую в БД — как это делают любые пути записи."""
        iface = self.db.get(DeviceInterface, interface_id)
        if mode is not None:
            iface.vlan_mode = mode
        if vlans is not None:
            for link in self.db.query(InterfaceVLAN).filter_by(interface_id=interface_id).all():
                self.db.delete(link)
            self.db.flush()
            self.db.add_all(InterfaceVLAN(interface_id=interface_id, vlan_id=v.id, mode=iface.vlan_mode) for v in vlans)
        self.db.commit()

    def row(self) -> dict:
        page = self.client.get("/api/v1/connections").json()
        return next(c for c in page["items"] if c["id"] == self.connection_id)

    def summary(self) -> dict:
        return self.client.get("/api/v1/connections").json()["summary"]

    def approve(self) -> dict:
        response = self.client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [self.connection_id]})
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture()
def lab(client, db_session, device_type, cable) -> Lab:
    return Lab(client, db_session, device_type, cable)


def test_identical_mode_and_vlans_are_ok_and_exposed_in_the_row(lab):
    v10, v20 = lab.vlan(10), lab.vlan(20)
    lab.configure(lab.src, "trunk", (v20, v10))
    lab.configure(lab.dst, "trunk", (v10, v20))

    row = lab.row()

    assert row["port_config_status"] == "ok" and row["port_config_diff"] == []
    assert (row["source_vlan_mode"], row["destination_vlan_mode"]) == ("trunk", "trunk")
    assert (row["source_vlans"], row["destination_vlans"]) == ([10, 20], [10, 20])


def test_trunk_against_access_is_a_mode_mismatch(lab):
    lab.configure(lab.src, "trunk")
    lab.configure(lab.dst, "access")

    row = lab.row()

    assert row["port_config_status"] == "mismatch"
    assert row["port_config_diff"] == ["mode"]
    assert (row["source_vlan_mode"], row["destination_vlan_mode"]) == ("trunk", "access")
    assert lab.summary()["mismatch"] == 1


def test_different_vlan_sets_are_a_vlan_mismatch(lab):
    lab.configure(lab.src, "trunk", (lab.vlan(10), lab.vlan(20)))
    lab.configure(lab.dst, "trunk", (lab.vlan(10), lab.vlan(30)))

    row = lab.row()

    assert row["port_config_status"] == "mismatch" and row["port_config_diff"] == ["vlans"]
    assert (row["source_vlans"], row["destination_vlans"]) == ([10, 20], [10, 30])


def test_mismatch_reports_every_differing_facet(lab):
    lab.configure(lab.src, "access", (lab.vlan(10),))
    lab.configure(lab.dst, "trunk")
    lab.db.get(DeviceInterface, lab.dst).is_management = True
    lab.db.commit()

    assert lab.row()["port_config_diff"] == ["role", "mode", "vlans"]


def test_same_vlan_tag_in_different_domains_is_the_same_vlan(lab, db_session):
    """Сравниваются номера (802.1Q-теги), а не записи справочника."""
    domain_a, domain_b = VLANDomain(name="Домен A"), VLANDomain(name="Домен B")
    db_session.add_all([domain_a, domain_b])
    db_session.flush()
    lab.configure(lab.src, "access", (lab.vlan(10, domain_a.id),))
    lab.configure(lab.dst, "access", (lab.vlan(10, domain_b.id),))

    assert lab.row()["port_config_status"] == "ok"


def test_inactive_connection_with_different_modes_is_not_a_mismatch(lab, db_session):
    lab.configure(lab.src, "trunk")
    lab.configure(lab.dst, "access")
    db_session.get(Connection, lab.connection_id).is_active = False
    db_session.commit()

    row = lab.row()

    assert row["port_config_status"] == "ok" and row["port_config_diff"] == []
    assert lab.summary()["mismatch"] == 0


def test_approving_a_mode_mismatch_and_dropping_it_when_the_mode_changes(lab):
    lab.configure(lab.src, "trunk")
    lab.configure(lab.dst, "access")

    assert lab.approve()["approved_count"] == 1
    assert lab.row()["port_config_status"] == "approved"

    lab.configure(lab.dst, "trunk")        # выровняли режимы — расхождения нет
    assert lab.row()["port_config_status"] == "ok"

    lab.configure(lab.dst, "access")       # режимы снова разошлись так же — одобрение прежнее, но
    assert lab.row()["port_config_status"] == "approved"  # подпись описывает ту же пару «trunk>access»


def test_approval_is_dropped_when_the_vlan_set_changes_afterwards(lab):
    lab.configure(lab.src, "trunk", (lab.vlan(10),))
    lab.configure(lab.dst, "trunk", (lab.vlan(20),))
    lab.approve()
    assert lab.row()["port_config_status"] == "approved"

    lab.configure(lab.dst, vlans=(lab.vlan(20), lab.vlan(30)))  # другое расхождение — нужно смотреть заново

    assert lab.row()["port_config_status"] == "mismatch"


def test_legacy_role_only_signature_still_approves_a_role_only_mismatch_but_not_a_new_mode_mismatch(lab, db_session):
    """Подписи, записанные до появления проверки режима и VLAN, не должны пропасть после обновления."""
    db_session.get(DeviceInterface, lab.src).is_management = True
    db_session.get(DeviceInterface, lab.src).is_data_transfer = False
    db_session.get(Connection, lab.connection_id).port_config_approved_signature = "management>data"
    db_session.commit()
    assert lab.row()["port_config_status"] == "approved"

    lab.configure(lab.dst, "access")  # к одобренной разнице ролей добавилась неодобренная разница режимов

    assert lab.row()["port_config_status"] == "mismatch"


def test_approve_audit_entry_names_the_differing_facets_and_vlans(lab):
    lab.configure(lab.src, "trunk", (lab.vlan(10), lab.vlan(20)))
    lab.configure(lab.dst, "access", (lab.vlan(10),))
    lab.approve()

    entries = lab.client.get("/api/v1/resources/audit-log", params={"limit": 1000}).json()["items"]
    details = next(e["details"] for e in entries if e["entity_type"] == "connections" and e["details"].startswith("Одобрено расхождение"))

    assert "режим порта, VLAN" in details
    assert "режим trunk, VLAN: 10, 20" in details and "режим access, VLAN: 10" in details


def test_stored_signature_is_the_python_signature_and_fits_the_column(lab, db_session):
    lab.configure(lab.src, "trunk", tuple(lab.vlan(n) for n in range(1, 40)))
    lab.configure(lab.dst, "access", (lab.vlan(10),))
    lab.approve()

    signature = db_session.get(Connection, lab.connection_id).port_config_approved_signature

    assert signature == f"|mode:trunk>access|vlan:{vlan_fingerprint(range(1, 40))}>{vlan_fingerprint([10])}"
    assert len(signature) <= 255


def test_search_matches_the_port_mode(lab):
    lab.configure(lab.src, "access")
    lab.configure(lab.dst, "access")

    assert [c["id"] for c in lab.client.get("/api/v1/connections", params={"q": "access"}).json()["items"]] == [lab.connection_id]
    assert lab.client.get("/api/v1/connections", params={"q": "trunk"}).json()["items"] == []


def test_orphan_connection_has_empty_mode_and_vlans(lab, db_session):
    """Порт удалён в обход внешних ключей — подключение остаётся в списке со статусом ok."""
    from sqlalchemy import text

    db_session.execute(text("PRAGMA foreign_keys=OFF"))
    db_session.execute(text("DELETE FROM device_interfaces WHERE id = :i"), {"i": lab.dst})
    db_session.commit()

    row = lab.row()

    assert row["port_config_status"] == "ok" and row["port_config_diff"] == []
    assert row["destination_vlan_mode"] is None and row["destination_vlans"] == []


# --- предпросмотр сверки пары портов для формы подключения ---------------------------------

def _preview(lab: Lab, **params) -> dict:
    query = {"source_interface_id": lab.src, "destination_interface_id": lab.dst, **params}
    response = lab.client.get("/api/v1/connections/port-config/preview", params=query)
    assert response.status_code == 200, response.text
    return response.json()


def test_preview_of_matching_ports_is_ok_and_describes_both_sides(lab):
    lab.configure(lab.src, "trunk", (lab.vlan(20), lab.vlan(10)))
    lab.configure(lab.dst, "trunk", (lab.vlan(10), lab.vlan(20)))

    result = _preview(lab)

    assert result["status"] == "ok" and result["diff"] == []
    assert result["source"] == {"interface_id": lab.src, "role": "data", "mode": "trunk", "vlans": [10, 20]}
    assert result["destination"] == {"interface_id": lab.dst, "role": "data", "mode": "trunk", "vlans": [10, 20]}


def test_preview_reports_mode_and_vlan_differences_before_anything_is_saved(lab):
    lab.configure(lab.src, "trunk", (lab.vlan(10), lab.vlan(20)))
    lab.configure(lab.dst, "access", (lab.vlan(10),))

    result = _preview(lab)

    assert result["status"] == "mismatch"
    assert result["diff"] == ["mode", "vlans"]
    assert (result["source"]["vlans"], result["destination"]["vlans"]) == ([10, 20], [10])


def test_preview_agrees_with_the_dashboard_row_for_the_same_pair(lab):
    """Предупреждение формы и статус на дашборде считаются одними правилами — расходиться не могут."""
    lab.configure(lab.src, "access", (lab.vlan(10),))
    lab.configure(lab.dst, "trunk", (lab.vlan(10), lab.vlan(30)))

    result = _preview(lab, connection_id=lab.connection_id)
    row = lab.row()

    assert (result["status"], result["diff"]) == (row["port_config_status"], row["port_config_diff"])


def test_preview_for_an_existing_connection_honours_its_approval(lab):
    lab.configure(lab.src, "trunk")
    lab.configure(lab.dst, "access")
    assert _preview(lab, connection_id=lab.connection_id)["status"] == "mismatch"

    lab.approve()

    assert _preview(lab, connection_id=lab.connection_id)["status"] == "approved"
    assert _preview(lab)["status"] == "mismatch"  # новое подключение с такой же парой одобрения не наследует


def test_preview_drops_the_approval_when_the_pair_changed_since(lab):
    lab.configure(lab.src, "trunk", (lab.vlan(10),))
    lab.configure(lab.dst, "trunk", (lab.vlan(20),))
    lab.approve()

    lab.configure(lab.dst, vlans=(lab.vlan(20), lab.vlan(30)))

    assert _preview(lab, connection_id=lab.connection_id)["status"] == "mismatch"


def test_preview_of_an_inactive_connection_is_ok_with_no_differences(lab):
    lab.configure(lab.src, "trunk")
    lab.configure(lab.dst, "access")

    result = _preview(lab, is_active="false")

    assert result["status"] == "ok" and result["diff"] == []
    assert (result["source"]["mode"], result["destination"]["mode"]) == ("trunk", "access")  # значения всё равно показываются


def test_preview_does_not_write_anything(lab, db_session):
    lab.configure(lab.src, "trunk")
    lab.configure(lab.dst, "access")

    _preview(lab, connection_id=lab.connection_id)
    db_session.expire_all()

    assert db_session.get(Connection, lab.connection_id).port_config_approved_signature is None
    entries = lab.client.get("/api/v1/resources/audit-log", params={"limit": 1000}).json()["items"]
    assert not any(e["details"].startswith("Одобрено") for e in entries)


def test_preview_with_unknown_port_or_connection_is_404(lab):
    base = {"source_interface_id": lab.src, "destination_interface_id": lab.dst}
    get = lab.client.get

    assert get("/api/v1/connections/port-config/preview", params={**base, "source_interface_id": "nope"}).status_code == 404
    assert get("/api/v1/connections/port-config/preview", params={**base, "destination_interface_id": "nope"}).status_code == 404
    assert get("/api/v1/connections/port-config/preview", params={**base, "connection_id": "nope"}).status_code == 404


def test_preview_requires_both_ports(lab):
    assert lab.client.get("/api/v1/connections/port-config/preview", params={"source_interface_id": lab.src}).status_code == 422
    assert lab.client.get("/api/v1/connections/port-config/preview").status_code == 422
