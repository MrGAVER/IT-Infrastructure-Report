"""Правка порта с дашборда «Подключения»: PUT /api/v1/interfaces/{id}/port-config — роль и набор VLAN
одной операцией (app/services/port_edit.py).

Запуск: pytest backend/tests/test_port_edit_api.py -v
"""

from __future__ import annotations

import pytest

from app.models import AuditLog, DeviceInterface, InterfaceGroup, InterfaceVLAN, IPAddress, PhysicalDeviceVLAN, VLAN


class Lab:
    """Устройство с портом, VLAN устройства и обращения к эндпоинту."""

    def __init__(self, client, db_session) -> None:
        self.client, self.db = client, db_session
        category = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        self.device_type = client.post("/api/v1/resources/device-types", json={"name": "Тип для правки порта", "category_id": category}).json()["id"]
        self.vlans: dict[int, VLAN] = {}

    def vlan(self, number: int) -> VLAN:
        if number not in self.vlans:
            row = VLAN(vlan_id=number, name=f"vlan{number}")
            self.db.add(row)
            self.db.flush()
            self.vlans[number] = row
        return self.vlans[number]

    def port(self, serial: str = "EDIT-1", *, allowed: tuple[int, ...] = (10, 20, 30), mode: str = "trunk", role: tuple[bool, bool] = (False, True), ip: str | None = None) -> str:
        device = self.client.post("/api/v1/resources/devices", json={"device_type_id": self.device_type, "serial_number": serial}).json()
        for number in allowed:
            self.db.add(PhysicalDeviceVLAN(physical_device_id=device["id"], vlan_id=self.vlan(number).id))
        self.db.commit()
        item: dict = {"name": "Gi0/1", "is_management": role[0], "is_data_transfer": role[1], "vlan_mode": mode}
        if ip:
            item["ips"] = [{"ip_address": ip}]
        response = self.client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfaces": [item]})
        assert response.status_code == 200, response.text
        return response.json()["items"][0]["id"]

    def edit(self, interface_id: str, body: dict):
        return self.client.put(f"/api/v1/interfaces/{interface_id}/port-config", json=body)

    def state(self, interface_id: str) -> dict:
        self.db.expire_all()
        iface = self.db.get(DeviceInterface, interface_id)
        links = self.db.query(InterfaceVLAN).filter_by(interface_id=interface_id).all()
        return {
            "role": (iface.is_management, iface.is_data_transfer),
            "mode": iface.vlan_mode,
            "vlans": sorted(self.db.get(VLAN, link.vlan_id).vlan_id for link in links),
            "link_modes": {link.mode for link in links},
        }

    def audit(self, *needles: str) -> list[str]:
        self.db.expire_all()
        return [e.details for e in self.db.query(AuditLog).all() if all(n in (e.details or "") for n in needles)]


@pytest.fixture()
def lab(client, db_session) -> Lab:
    return Lab(client, db_session)


def test_changes_role_and_vlans_in_one_request(lab):
    port = lab.port()

    response = lab.edit(port, {"role": "management_data", "vlan_ids": [lab.vlan(10).id, lab.vlan(20).id], "mode": "trunk"})

    assert response.status_code == 200, response.text
    assert response.json()["id"] == port and response.json()["is_management"] is True and response.json()["is_data_transfer"] is True
    assert lab.state(port) == {"role": (True, True), "mode": "trunk", "vlans": [10, 20], "link_modes": {"trunk"}}
    (entry,) = lab.audit("Правка порта", "Gi0/1")
    assert "роль Передача данных → Передача данных и управление активами" in entry and "VLAN нет → 10, 20" in entry


def test_vlans_replace_the_whole_set_and_keep_the_mode(lab):
    port = lab.port(mode="trunk")
    assert lab.edit(port, {"vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]}).status_code == 200

    assert lab.edit(port, {"vlan_ids": [lab.vlan(20).id, lab.vlan(30).id]}).status_code == 200

    assert lab.state(port)["vlans"] == [20, 30] and lab.state(port)["mode"] == "trunk"
    assert lab.edit(port, {"vlan_ids": []}).status_code == 200 and lab.state(port)["vlans"] == []  # снять все VLAN можно


def test_role_only_does_not_touch_vlans_and_mirrors_the_flag_to_ips(lab):
    port = lab.port(ip="10.0.0.5")
    assert lab.edit(port, {"vlan_ids": [lab.vlan(10).id]}).status_code == 200

    assert lab.edit(port, {"role": "management"}).status_code == 200

    assert lab.state(port)["role"] == (True, False) and lab.state(port)["vlans"] == [10]
    lab.db.expire_all()
    assert lab.db.query(IPAddress).filter_by(owner_id=port).one().is_management is True


def test_access_port_takes_at_most_one_vlan(lab):
    port = lab.port(mode="access")

    too_many = lab.edit(port, {"vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]})
    one = lab.edit(port, {"vlan_ids": [lab.vlan(10).id]})

    assert too_many.status_code == 422 and "access" in too_many.json()["detail"]
    assert one.status_code == 200 and lab.state(port) == {"role": (False, True), "mode": "access", "vlans": [10], "link_modes": {"access"}}


def test_a_vlan_the_device_does_not_have_is_rejected_and_nothing_is_written(lab):
    port = lab.port(allowed=(10,))

    response = lab.edit(port, {"role": "management", "vlan_ids": [lab.vlan(10).id, lab.vlan(99).id]})

    assert response.status_code == 422 and "не разрешены" in response.json()["detail"]
    assert lab.state(port) == {"role": (False, True), "mode": "trunk", "vlans": [], "link_modes": set()}  # роль тоже не записана
    assert lab.audit("Правка порта") == []


def test_a_port_in_a_group_that_sets_mode_and_vlans_keeps_its_vlans_but_may_change_role(lab):
    port = lab.port()
    iface = lab.db.get(DeviceInterface, port)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Магистрали", vlan_mode="trunk")
    lab.db.add(group)
    lab.db.flush()
    iface.group_id = group.id
    lab.db.commit()

    blocked = lab.edit(port, {"vlan_ids": [lab.vlan(10).id]})
    role = lab.edit(port, {"role": "management"})

    assert blocked.status_code == 409 and "Магистрали" in blocked.json()["detail"] and "группу" in blocked.json()["detail"]
    assert role.status_code == 200 and lab.state(port)["role"] == (True, False)


def test_an_unchanged_set_in_a_group_port_is_not_an_error(lab):
    port = lab.port()
    iface = lab.db.get(DeviceInterface, port)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Только режим", vlan_mode="trunk")
    lab.db.add(group)
    lab.db.flush()
    iface.group_id = group.id
    lab.db.commit()

    assert lab.edit(port, {"vlan_ids": []}).status_code == 200  # набор тот же — править нечего


def test_mode_in_the_request_is_a_check_not_a_command(lab):
    port = lab.port(mode="access")

    response = lab.edit(port, {"mode": "trunk", "vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]})

    assert response.status_code == 409 and "изменился" in response.json()["detail"]
    assert lab.state(port)["mode"] == "access" and lab.state(port)["vlans"] == []


def test_nothing_changed_writes_nothing_and_leaves_no_audit_entry(lab):
    port = lab.port()

    response = lab.edit(port, {"role": "data", "vlan_ids": []})

    assert response.status_code == 200 and lab.audit("Правка порта") == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({}, "role, vlan_ids и/или all_vlans"),
        ({"role": "boss"}, "role"),
        ({"role": 5}, "role"),
        ({"vlan_ids": "10"}, "vlan_ids"),
        ({"vlan_ids": [1]}, "vlan_ids"),
        ({"vlan_ids": [""]}, "vlan_ids"),
        ({"mode": "hybrid", "role": "data"}, "mode"),
        ({"role": "data", "extra": 1}, "Неизвестные поля"),
    ],
)
def test_malformed_requests_are_rejected(lab, body, fragment):
    port = lab.port()

    response = lab.edit(port, body)

    assert response.status_code == 422 and fragment in response.json()["detail"]


def test_unknown_port_is_404_and_a_non_object_body_is_422(lab, client):
    assert lab.edit("no-such-port", {"role": "data"}).status_code == 404
    assert client.put("/api/v1/interfaces/x/port-config", json=[1]).status_code == 422


def test_duplicate_vlan_ids_are_collapsed(lab):
    port = lab.port()
    vlan = lab.vlan(10).id

    assert lab.edit(port, {"vlan_ids": [vlan, vlan]}).status_code == 200

    assert lab.state(port)["vlans"] == [10]


# --- режим + роль + VLAN одной транзакцией (каскад с полем port) ---------------------------------


def _cascade_url(port: str, step: str = "") -> str:
    return f"/api/v1/interfaces/{port}/vlan-mode-cascade{step}"


def _preview(lab, port: str, mode: str, change: dict | None = None):
    body: dict = {"mode": mode}
    if change is not None:
        body["port"] = change
    return lab.client.post(_cascade_url(port, "/preview"), json=body)


def _apply(lab, port: str, mode: str, change: dict | None, plan_hash: str):
    body: dict = {"mode": mode, "plan_hash": plan_hash, "confirm": True}
    if change is not None:
        body["port"] = change
    return lab.client.post(_cascade_url(port), json=body)


def _with_vlans(lab, port: str, *numbers: int) -> None:
    """Назначает VLAN порту напрямую в БД — без записей аудита, чтобы тесты могли проверять аудит операции."""
    mode = lab.db.get(DeviceInterface, port).vlan_mode
    lab.db.add_all(InterfaceVLAN(interface_id=port, vlan_id=lab.vlan(n).id, mode=mode) for n in numbers)
    lab.db.commit()


def test_mode_role_and_vlans_are_written_by_one_request(lab):
    port = lab.port(mode="trunk")
    _with_vlans(lab, port, 10, 20)
    change = {"role": "management", "vlan_ids": [lab.vlan(10).id]}
    plan = _preview(lab, port, "access", change).json()

    response = _apply(lab, port, "access", change, plan["hash"])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["port_written"] is True and body["applied"]["ports"] == 1
    assert lab.state(port) == {"role": (True, False), "mode": "access", "vlans": [10], "link_modes": {"access"}}
    written = next(i for i in body["interfaces"] if i["id"] == port)
    assert written["vlan_mode"] == "access" and written["is_management"] is True and written["is_data_transfer"] is False
    (entry,) = lab.audit("Правка порта", "вместе со сменой режима → access")
    assert "роль Передача данных → Управление активами" in entry and "VLAN 10, 20 → 10" in entry
    assert len(lab.audit("Каскадная смена режима порта")) == 1  # аудит самого каскада остаётся отдельной записью


def test_a_cascade_request_without_port_behaves_as_before(lab):
    port = lab.port(mode="trunk")
    _with_vlans(lab, port, 10)
    plan = _preview(lab, port, "access").json()

    body = _apply(lab, port, "access", None, plan["hash"]).json()

    assert body["port_written"] is False and lab.state(port)["mode"] == "access" and lab.state(port)["role"] == (False, True)
    assert lab.audit("Правка порта") == []


def test_an_invalid_vlan_is_rejected_at_preview_and_at_apply_and_nothing_is_written(lab):
    port = lab.port(mode="trunk", allowed=(10,))
    _with_vlans(lab, port, 10)
    plan = _preview(lab, port, "access").json()
    bad = {"role": "management", "vlan_ids": [lab.vlan(99).id]}

    at_preview = _preview(lab, port, "access", bad)
    at_apply = _apply(lab, port, "access", bad, plan["hash"])

    assert at_preview.status_code == 422 and "не разрешены" in at_preview.json()["detail"]
    assert at_apply.status_code == 422
    assert lab.state(port) == {"role": (False, True), "mode": "trunk", "vlans": [10], "link_modes": {"trunk"}}  # даже режим не сменился
    assert lab.audit("Каскадная смена") == [] and lab.audit("Правка порта") == []


def test_several_vlans_are_rejected_under_the_target_access_mode_but_fine_for_trunk(lab):
    port = lab.port(mode="access")
    _with_vlans(lab, port, 10)
    two = {"vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]}

    rejected = _preview(lab, port, "access", two)  # режим уже access и останется им
    to_trunk = _preview(lab, port, "trunk", two)

    assert rejected.status_code == 422 and "access" in rejected.json()["detail"]
    assert to_trunk.status_code == 200
    assert _apply(lab, port, "trunk", two, to_trunk.json()["hash"]).status_code == 200
    assert lab.state(port) == {"role": (False, True), "mode": "trunk", "vlans": [10, 20], "link_modes": {"trunk"}}


def test_a_stale_plan_hash_is_rejected_and_neither_mode_nor_role_is_written(lab):
    port = lab.port(mode="trunk")

    response = _apply(lab, port, "access", {"role": "management"}, "stale-hash")

    assert response.status_code == 409
    assert lab.state(port)["mode"] == "trunk" and lab.state(port)["role"] == (False, True)


def test_when_the_mode_is_already_the_target_role_and_vlans_are_still_written(lab):
    port = lab.port(mode="access")
    change = {"role": "management", "vlan_ids": [lab.vlan(20).id]}
    plan = _preview(lab, port, "access", change).json()
    assert plan["empty"] is True

    body = _apply(lab, port, "access", change, plan["hash"]).json()

    assert body["port_written"] is True and body["applied"] == {"ports": 0, "groups": 0, "devices": 0}
    assert lab.state(port) == {"role": (True, False), "mode": "access", "vlans": [20], "link_modes": {"access"}}


def test_a_group_port_changes_mode_and_role_together_but_its_vlans_stay_locked(lab):
    port = lab.port(mode="trunk")
    iface = lab.db.get(DeviceInterface, port)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Магистрали", vlan_mode="trunk")
    lab.db.add(group)
    lab.db.flush()
    iface.group_id = group.id
    lab.db.commit()
    locked = {"vlan_ids": [lab.vlan(10).id]}
    plan = _preview(lab, port, "access", {"role": "management"}).json()

    blocked = _apply(lab, port, "access", locked, plan["hash"])
    allowed = _apply(lab, port, "access", {"role": "management"}, plan["hash"])

    assert blocked.status_code == 409 and "Магистрали" in blocked.json()["detail"]
    assert allowed.status_code == 200, allowed.text
    lab.db.expire_all()
    assert lab.db.get(InterfaceGroup, group.id).vlan_mode == "access"  # режим сменился у всей группы
    assert lab.state(port)["role"] == (True, False) and lab.state(port)["mode"] == "access"


def test_port_does_not_combine_with_an_open_device_form(lab):
    port = lab.port(mode="trunk")
    device_id = lab.db.get(DeviceInterface, port).physical_device_id

    response = lab.client.post(_cascade_url(port, "/preview"), json={"mode": "access", "edited": {"device_id": device_id, "ports": {}, "groups": {}}, "port": {"role": "data"}})

    assert response.status_code == 422 and "edited" in response.json()["detail"]


@pytest.mark.parametrize("bad", [{}, {"role": "boss"}, {"vlan_ids": "10"}, {"role": "data", "mode": "trunk"}, [], "data"])
def test_a_malformed_port_is_rejected(lab, bad):
    port = lab.port(mode="trunk")

    response = _preview(lab, port, "access", bad)

    assert response.status_code == 422


def test_a_failure_while_writing_the_port_rolls_back_the_whole_cascade(lab, monkeypatch):
    port = lab.port(mode="trunk")
    _with_vlans(lab, port, 10)
    change = {"role": "management", "vlan_ids": [lab.vlan(10).id]}
    plan = _preview(lab, port, "access", change).json()
    from app.services import vlan_mode_cascade as module

    def broken(*_args, **_kwargs):
        raise RuntimeError("сбой записи роли и VLAN")

    monkeypatch.setattr(module, "write_port_change", broken)
    with pytest.raises(RuntimeError):
        _apply(lab, port, "access", change, plan["hash"])
    lab.db.rollback()

    assert lab.state(port) == {"role": (False, True), "mode": "trunk", "vlans": [10], "link_modes": {"trunk"}}  # режим тоже откатился


# --- Тело разбирается один раз (код-ревью, BE-04) ---------------------------------------------------------------------------
# Раньше модель PortConfigUpdate разбирала тело, а set_port_config разбирал тот же словарь (model_dump) второй раз: двойная работа и два
# места, где приведение типов Pydantic и ручной разбор могли разойтись. Теперь модель отдаёт разобранное тело (`body.request`), а
# обработчик зовёт apply_port_config.


@pytest.fixture()
def parse_calls(monkeypatch) -> list[dict]:
    """Тела, которые разобрал parse_port_change — по одной записи на вызов, откуда бы его ни звали.

    Подменяются обе точки вызова: сам сервис (services/port_edit) и имя, импортированное в модуль моделей запросов (раньше модель
    звала его напрямую; сейчас этого имени там нет — `raising=False`). Иначе тест не заметил бы вызова из модели."""
    from app.api import port_config_schemas
    from app.services import port_edit

    calls: list[dict] = []
    original = port_edit.parse_port_change

    def counting(raw, **kwargs):
        calls.append(raw)
        return original(raw, **kwargs)

    monkeypatch.setattr(port_edit, "parse_port_change", counting)
    monkeypatch.setattr(port_config_schemas, "parse_port_change", counting, raising=False)
    return calls


def test_the_body_is_parsed_exactly_once_per_request(lab, parse_calls):
    port = lab.port()

    response = lab.edit(port, {"role": "data", "vlan_ids": [lab.vlan(10).id], "mode": "trunk"})

    assert response.status_code == 200, response.text
    assert len(parse_calls) == 1  # раньше — 2: в модели и в сервисе


def test_a_rejected_body_is_parsed_once_and_keeps_its_message(lab, parse_calls):
    port = lab.port()

    response = lab.edit(port, {"role": "data", "лишнее": 1})

    assert response.status_code == 422
    assert response.json() == {"detail": "Неизвестные поля: лишнее"}
    assert len(parse_calls) == 1


def test_body_checks_still_come_before_the_port_lookup(lab):
    # Порядок прежний: неверное тело — 422 даже у несуществующего порта, верное тело у несуществующего порта — 404.
    assert lab.edit("нет-такого", {}).status_code == 422
    missing = lab.edit("нет-такого", {"role": "data"})
    assert (missing.status_code, missing.json()) == (404, {"detail": "Порт не найден"})


def test_the_model_exposes_the_parsed_request_and_keeps_it_on_revalidation():
    from app.api.port_config_schemas import PortConfigUpdate

    model = PortConfigUpdate.model_validate({"role": "data", "mode": "trunk"})

    assert model.request.expected_mode == "trunk"
    assert model.request.change.vlan_ids is None and model.request.change.all_vlans is None
    assert PortConfigUpdate.model_validate(model).request is model.request  # готовый экземпляр заново не разбирается


def test_apply_port_config_works_from_a_parsed_request_without_parsing(lab, monkeypatch):
    from app.services import port_edit

    port = lab.port()
    request = port_edit.parse_port_config_request({"role": "management"})

    def forbidden(*args, **kwargs):
        raise AssertionError("apply_port_config не должен разбирать тело")

    monkeypatch.setattr(port_edit, "parse_port_change", forbidden)
    result = port_edit.apply_port_config(port, request, lab.db)

    assert (result["is_management"], result["is_data_transfer"]) == (True, False)
    assert lab.state(port)["role"] == (True, False)


def test_set_port_config_still_accepts_a_raw_body_and_parses_it_once(lab, parse_calls):
    from app.services.port_edit import set_port_config

    port = lab.port()

    result = set_port_config(port, {"role": "management"}, lab.db)

    assert (result["is_management"], result["is_data_transfer"]) == (True, False)
    assert len(parse_calls) == 1
