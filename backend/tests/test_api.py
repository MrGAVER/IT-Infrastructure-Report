"""
Интеграционные тесты HTTP-слоя: fastapi.testclient.TestClient поверх реальной SQLAlchemy-сессии
на in-memory SQLite (см. conftest.py). Раньше этот слой (api/*.py + services/crud/) не был
покрыт тестами вовсе — существовавшие тесты проверяли только форматирование Excel-отчёта на
облегчённом моке ORM (mock_sqlalchemy.py), без реальных запросов, FK-констрейнтов, конфликтов
409 и т.п.

Запуск:  pip install -r backend/requirements-dev.txt && pytest backend/tests/test_api.py -v
"""

from __future__ import annotations

import pytest

from app.config import REPORT_DIR


def _create_device_type(client, name: str, **extra):
    """Создаёт тип устройства с первой попавшейся существующей категорией. category_id обязателен
    с тех пор, как DeviceType обзавёлся DeviceCategory (диаграмма топологии сети, см.
    app/models.py) — большинству тестов в этом файле конкретная категория безразлична, им нужен
    только синтаксически валидный тип устройства для последующего создания физических устройств."""
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    return client.post("/api/v1/resources/device-types", json={"name": name, "category_id": category_id, **extra}).json()


def _create_protocol_catalog_entry(client, port: int, protocol_type: str):
    """Возвращает запись справочника «Протоколы и порты» с данными port+protocol_type — с тех пор,
    как OpenPort.port/protocol выводятся сервером только из неё (правка "убрать текстовые поля
    Порт/Протокол"), тестам открытых портов нужна реальная запись справочника вместо произвольного
    port в payload.

    Идемпотентно (находит существующую, а не только создаёт): большинство "хрестоматийных" портов,
    использованных в этих тестах (22/SSH, 80/HTTP, 443/HTTPS и т.п.), уже засеяны по умолчанию
    (см. PROTOCOL_DEFAULTS в app/services/catalogs.py) — наивный POST здесь падал бы 409
    (UNIQUE constraint failed) на уже существующей паре port+protocol_type."""
    existing = client.get("/api/v1/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    if match:
        return match
    return client.post("/api/v1/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type}).json()


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard_counts_are_zero_on_empty_db(client):
    r = client.get("/api/v1/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["physical_devices"] == 0
    assert data["information_systems"] == 0


def test_resources_list_excludes_audit_log(client):
    r = client.get("/api/v1/resources")
    assert r.status_code == 200
    keys = {item["key"] for item in r.json()}
    assert "audit-log" not in keys
    assert "devices" in keys
    assert "information-systems" in keys


class TestInformationSystemNameUniqueness:
    """Регрессия: information_systems.name объявлено unique=True в модели, но миграция
    d3f9a1c6b750 (batch_alter_table на SQLite, добавление support_method_id) молча
    потеряла безымянный UniqueConstraint при пересборке таблицы — тот же класс
    проблемы, что уже был пойман и исправлен для physical_devices.system_name в
    c4e8a7d91b20, но не был замечен здесь, т.к. ни один тест этого не проверял.
    См. alembic/versions/f4a29c7e1d60_restore_information_system_name_uniqueness.py.

    ВАЖНО: этот тест проверяет только бизнес-правило через ORM-модель (см.
    tests/conftest.py: Base.metadata.create_all(), который строит схему из текущих
    определений моделей, а не через реальную цепочку alembic-миграций) — он не мог
    бы поймать саму историческую поломку миграции, только её отсутствие в модели.
    Проверка того, что реальная цепочка миграций восстанавливает constraint (включая
    сценарий с уже существующими дубликатами на старой БД), сделана вручную отдельно
    от pytest-набора."""

    def test_duplicate_name_rejected(self, client):
        first = client.post("/api/v1/resources/information-systems", json={"name": "ИС Уникальная"})
        assert first.status_code == 201

        second = client.post("/api/v1/resources/information-systems", json={"name": "ИС Уникальная"})
        assert second.status_code == 409

    def test_editing_to_a_taken_name_is_also_rejected(self, client):
        a = client.post("/api/v1/resources/information-systems", json={"name": "ИС А"}).json()
        client.post("/api/v1/resources/information-systems", json={"name": "ИС Б"})

        r = client.put(f"/api/v1/resources/information-systems/{a['id']}", json={"name": "ИС Б"})
        assert r.status_code == 409


class TestCrudBasics:
    def test_create_get_update_delete_manufacturer(self, client):
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Тест-Производитель"})
        assert r.status_code == 201, r.text
        obj = r.json()
        assert obj["name"] == "Тест-Производитель"
        item_id = obj["id"]

        r = client.get(f"/api/v1/resources/manufacturers/{item_id}")
        assert r.status_code == 200
        assert r.json()["id"] == item_id

        r = client.put(f"/api/v1/resources/manufacturers/{item_id}", json={"name": "Переименовано"})
        assert r.status_code == 200
        assert r.json()["name"] == "Переименовано"

        r = client.delete(f"/api/v1/resources/manufacturers/{item_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

        r = client.get(f"/api/v1/resources/manufacturers/{item_id}")
        assert r.status_code == 404

    def test_get_missing_resource_returns_404(self, client):
        r = client.get("/api/v1/resources/manufacturers/does-not-exist")
        assert r.status_code == 404

    def test_unknown_resource_key_returns_404(self, client):
        r = client.get("/api/v1/resources/not-a-real-resource")
        assert r.status_code == 404

    def test_list_pagination_fields_present(self, client):
        before = client.get("/api/v1/resources/manufacturers").json()["total"]
        client.post("/api/v1/resources/manufacturers", json={"name": "Тестовый производитель A"})
        client.post("/api/v1/resources/manufacturers", json={"name": "Тестовый производитель B"})
        r = client.get("/api/v1/resources/manufacturers?limit=1&offset=0")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == before + 2
        assert len(data["items"]) == 1
        assert data["limit"] == 1 and data["offset"] == 0


class TestSchemaValidation:
    """Код-ревью п.2 (High, SOLID): для devices/information-systems/vlans payload теперь
    проходит через Pydantic-схему (schemas.RESOURCE_SCHEMAS) до попадания в SQLAlchemy. Раньше
    некорректный тип (например, список вместо строки) всплывал только на INSERT как
    малопонятный IntegrityError/500, а не как явный 422 на входе."""

    def test_wrong_type_rejected_with_clean_422_not_integrity_error(self, client):
        dt = _create_device_type(client, "Тип для схемы")
        r = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SCHEMA-1", "rack_position": ["10U", "11U"]},
        )
        assert r.status_code == 422
        assert "rack_position" in r.json()["detail"]

    def test_missing_required_field_rejected_before_hitting_db(self, client):
        r = client.post("/api/v1/resources/devices", json={"serial_number": "SCHEMA-2"})
        assert r.status_code == 422
        assert "device_type_id" in r.json()["detail"]

    def test_vlan_id_out_of_range_rejected(self, client):
        r = client.post("/api/v1/resources/vlans", json={"vlan_id": 5000, "name": "Вне диапазона"})
        assert r.status_code == 422

    def test_numeric_string_is_coerced_for_vlan_id(self, client):
        """Pydantic по умолчанию мягко приводит типы (lax mode): "77" -> 77 — это сохраняет
        сегодняшнюю терпимость API к строковым числам с фронтенда, меняется только то, что
        совсем некорректные типы (списки, объекты) теперь отклоняются явно."""
        r = client.post("/api/v1/resources/vlans", json={"vlan_id": "77", "name": "Строкой"})
        assert r.status_code == 201, r.text
        assert r.json()["vlan_id"] == 77

    def test_unschematized_resource_still_accepts_raw_dict(self, client):
        """Ресурсы вне RESOURCE_SCHEMAS (пока большинство) не должны были затронуться —
        generic CRUD продолжает работать как раньше."""
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Без схемы"})
        assert r.status_code == 201, r.text

    def test_update_schema_validation_keeps_partial_semantics(self, client):
        dt = _create_device_type(client, "Тип для апдейта")
        dev = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SCHEMA-3", "description": "Исходное"},
        ).json()

        r = client.put(f"/api/v1/resources/devices/{dev['id']}", json={"rack_position": ["oops"]})
        assert r.status_code == 422

        r = client.put(f"/api/v1/resources/devices/{dev['id']}", json={"rack_position": "12U"})
        assert r.status_code == 200, r.text
        assert r.json()["rack_position"] == "12U"
        # Поля, отсутствующие в payload частичного обновления, не затронуты схемой.
        assert r.json()["description"] == "Исходное"


class TestHypervisorAndVmHostFlags:
    """Код-ревью п.4 (Medium, SOLID/архитектура): validate_hypervisor()/validate_vm_host()
    раньше сравнивали строки с именем справочной записи ('гипервизор', 'сервер'/'storage'),
    поэтому переименование категории/типа устройства в справочнике молча ломало валидацию.
    Теперь правило зависит только от явных булевых полей is_hypervisor/allows_vm_hosting —
    ниже это доказывается на категории/типе устройства с намеренно НЕ канонич­ными именами:
    если бы код всё ещё сравнивал строки, эти тесты бы падали."""

    def test_hypervisor_rule_follows_flag_not_category_name(self, client):
        category = client.post(
            "/api/v1/resources/os-categories",
            json={"name": "Совершенно другое имя", "is_hypervisor": True},
        )
        assert category.status_code == 201, category.text
        hypervisor_os = client.post(
            "/api/v1/resources/operating-systems",
            json={"category_id": category.json()["id"], "name": "Custom Hypervisor", "version": "1"},
        ).json()
        server_type = _create_device_type(client, "Тестовый хост-сервер", allows_vm_hosting=True)
        host = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": server_type["id"],
                "serial_number": "SN-HYP-1",
                "operating_system_id": hypervisor_os["id"],
            },
        ).json()

        vm = client.post(
            "/api/v1/resources/vms",
            json={"name": "vm-flag-test", "physical_device_id": host["id"]},
        )
        assert vm.status_code == 201, vm.text
        # hypervisor_os_id проставляется автоматически из ОС хоста (см. crud.create_resource).
        assert vm.json()["hypervisor_os_id"] == hypervisor_os["id"]

    def test_hypervisor_rule_rejects_category_without_flag_even_if_named_hypervisor(self, client):
        """Обратная сторона того же правила: имя записи больше ни на что не влияет — без
        is_hypervisor=True (значение по умолчанию — False) в поле гипервизора эту ОС выбрать
        нельзя, даже если категория выглядит как гипервизорная."""
        category = client.post("/api/v1/resources/os-categories", json={"name": "Гипервизор (не настоящий)"}).json()
        assert category["is_hypervisor"] is False
        hypervisor_os = client.post(
            "/api/v1/resources/operating-systems",
            json={"category_id": category["id"], "name": "Fake Hypervisor", "version": "1"},
        ).json()
        server_type = _create_device_type(client, "Тестовый хост-сервер 2", allows_vm_hosting=True)
        host = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": server_type["id"],
                "serial_number": "SN-HYP-2",
                "operating_system_id": hypervisor_os["id"],
            },
        ).json()

        vm = client.post(
            "/api/v1/resources/vms",
            json={"name": "vm-flag-reject", "physical_device_id": host["id"]},
        )
        assert vm.status_code == 422

    def test_vm_host_rule_follows_flag_not_device_type_name(self, client):
        device_type = _create_device_type(client, "Необычное имя типа", allows_vm_hosting=True)
        host = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": device_type["id"], "serial_number": "SN-HOST-1"},
        ).json()

        vm = client.post(
            "/api/v1/resources/vms",
            json={"name": "vm-host-flag-test", "physical_device_id": host["id"]},
        )
        assert vm.status_code == 201, vm.text

    def test_vm_host_rule_rejects_device_type_without_flag(self, client):
        device_type = _create_device_type(client, "Рабочая станция без флага")
        assert device_type["allows_vm_hosting"] is False
        host = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": device_type["id"], "serial_number": "SN-HOST-2"},
        ).json()

        vm = client.post(
            "/api/v1/resources/vms",
            json={"name": "vm-host-flag-reject", "physical_device_id": host["id"]},
        )
        assert vm.status_code == 422


class TestDeviceTypeCategoryRequired:
    """Интеграционный фикс (слияние feature/network-topology-diagram + fix/usability-batch4,
    находка №1 код-ревью): DeviceType.category_id стал обязательным NOT NULL FK в рамках фичи
    диаграммы топологии сети, но ни validate_resource, ни quickAdd/schema.ts не были обновлены
    под это требование — POST без category_id падал сырым 409 "NOT NULL constraint failed"
    вместо понятной ошибки 422. См. backend/app/services/crud/validators.py:validate_resource."""

    def test_create_device_type_without_category_id_returns_422_not_raw_409(self, client):
        r = client.post("/api/v1/resources/device-types", json={"name": "Тип без категории"})
        assert r.status_code == 422
        assert "category_id" in r.json()["detail"]

    def test_create_device_type_with_category_id_succeeds(self, client):
        category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        r = client.post("/api/v1/resources/device-types", json={"name": "Тип с категорией", "category_id": category_id})
        assert r.status_code == 201, r.text
        assert r.json()["category_id"] == category_id

    def test_update_device_type_cannot_null_out_category_id(self, client):
        dt = _create_device_type(client, "Тип для проверки обновления")
        r = client.put(f"/api/v1/resources/device-types/{dt['id']}", json={"category_id": None})
        assert r.status_code == 422


class TestReferentialIntegrity:
    def test_cannot_delete_device_type_referenced_by_device(self, client):
        dt = _create_device_type(client, "Тестовый сервер А")
        dev = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SN-001"},
        )
        assert dev.status_code == 201, dev.text

        r = client.delete(f"/api/v1/resources/device-types/{dt['id']}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"

    def test_unreferenced_device_type_can_be_deleted(self, client):
        dt = _create_device_type(client, "Неиспользуемый тип")
        r = client.delete(f"/api/v1/resources/device-types/{dt['id']}")
        assert r.status_code == 200

    def test_duplicate_system_name_requires_confirmation(self, client):
        dt = _create_device_type(client, "Тестовый сервер А")
        first = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SN-100", "system_name": "srv-01"},
        )
        assert first.status_code == 201

        conflict = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SN-101", "system_name": "srv-01"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "DUPLICATE_SYSTEM_NAME"

        confirmed = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": dt["id"],
                "serial_number": "SN-101",
                "system_name": "srv-01",
                "confirm_system_name_duplicate": True,
            },
        )
        assert confirmed.status_code == 201, confirmed.text

    def test_rack_position_conflict_requires_confirmation(self, client):
        dt = _create_device_type(client, "Тестовый сервер А")
        building = client.post("/api/v1/resources/buildings", json={"name": "Тестовый ЦОД"}).json()
        room = client.post("/api/v1/resources/rooms", json={"building_id": building["id"], "name": "Серверная"}).json()
        rack = client.post("/api/v1/resources/racks", json={"room_id": room["id"], "name": "R01"}).json()

        first = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": dt["id"],
                "serial_number": "SN-200",
                "room_id": room["id"],
                "rack_id": rack["id"],
                "rack_position": "10U",
            },
        )
        assert first.status_code == 201, first.text

        conflict = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": dt["id"],
                "serial_number": "SN-201",
                "room_id": room["id"],
                "rack_id": rack["id"],
                "rack_position": "10U",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "RACK_POSITION_OCCUPIED"


class TestInterfacesSync:
    def test_sync_interfaces_creates_and_lists_ips(self, client):
        dt = _create_device_type(client, "Коммутатор")
        dev = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SW-01"},
        ).json()

        payload = {
            "interfaces": [
                {
                    "name": "Gi0/1",
                    "is_management": True,
                    "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}],
                }
            ]
        }
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Gi0/1"
        assert items[0]["ips"][0]["ip_address"] == "10.0.0.1"

    def test_sync_interfaces_rejects_malformed_ip_address(self, client):
        """Код-ревью п.3.4: формат IP проверялся только на фронтенде (ipValidation.ts) —
        прямой запрос к API мог записать в InterfaceIP произвольную строку."""
        dt = _create_device_type(client, "Коммутатор с плохим IP")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-BADIP"}).json()
        payload = {"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": "999.999.999.999"}]}]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 422

    def test_sync_interfaces_rejects_out_of_range_prefix_length(self, client):
        dt = _create_device_type(client, "Коммутатор с плохим префиксом")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-BADPREFIX"}).json()
        payload = {"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 99}]}]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 422

    def test_sync_interfaces_unknown_device_returns_404(self, client):
        r = client.put("/api/v1/devices/does-not-exist/interfaces", json={"interfaces": []})
        assert r.status_code == 404

    def test_sync_interfaces_defaults_vlan_mode_to_trunk(self, client):
        """Ни vlan_mode, ни vlan_ids не присланы — интерфейс должен получить дефолт колонки
        ('trunk'), а не упасть на NOT NULL или молча остаться неопределённым."""
        dt = _create_device_type(client, "Коммутатор без режима")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-DEFAULT"}).json()

        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json={"interfaces": [{"name": "Gi0/1"}]})
        assert r.status_code == 200, r.text
        assert r.json()["items"][0]["vlan_mode"] == "trunk"

    def test_sync_interfaces_persists_access_mode_with_zero_vlans(self, client):
        """Фикс п.1.3.9: access-режим без единого VLAN на порту должен пережить сохранение и
        последующую перезагрузку — раньше, при отсутствии связей interface_vlans, режим было
        неоткуда восстановить, и порт молча становился trunk."""
        dt = _create_device_type(client, "Коммутатор access без vlan")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-ACCESS-EMPTY"}).json()

        payload = {"interfaces": [{"name": "Fa0/1", "vlan_mode": "access", "vlan_ids": []}]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["items"][0]["vlan_mode"] == "access"

        # "Следующая загрузка формы" — повторный PUT того же набора интерфейсов, полученного из GET,
        # это и есть то, что делает DeviceInterfacesEditor.vue при повторном открытии формы.
        r = client.get(f"/api/v1/resources/interfaces?physical_device_id={dev['id']}")
        assert r.status_code == 200
        assert r.json()["items"][0]["vlan_mode"] == "access"

    def test_sync_interfaces_rejects_access_mode_with_multiple_vlans(self, client):
        dt = _create_device_type(client, "Коммутатор access-конфликт")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-ACCESS-MULTI"}).json()
        v1 = client.post("/api/v1/resources/vlans", json={"vlan_id": 10, "name": "vlan-10"}).json()
        v2 = client.post("/api/v1/resources/vlans", json={"vlan_id": 20, "name": "vlan-20"}).json()
        client.post("/api/v1/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v1["id"]})
        client.post("/api/v1/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v2["id"]})

        payload = {"interfaces": [{"name": "Fa0/1", "vlan_mode": "access", "vlan_ids": [v1["id"], v2["id"]]}]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 422

    def test_sync_interfaces_rejects_unknown_vlan_mode(self, client):
        dt = _create_device_type(client, "Коммутатор невалидный режим")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-BAD-MODE"}).json()

        payload = {"interfaces": [{"name": "Fa0/1", "vlan_mode": "half-duplex"}]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 422

    def test_sync_interfaces_creates_access_mode_ports_without_extra_update(self, client, sql_log):
        """Аудит fix/usability-batch4 (находка №2): для НОВОГО интерфейса obj.vlan_mode
        присваивался ПОСЛЕ session.flush() — колонка сначала уходила в БД со значением по
        умолчанию ('trunk') через INSERT, а затем, если запрошенный режим отличался от дефолта
        (например 'access'), правилось отдельным UPDATE device_interfaces. При создании
        устройства с N access-портами это N лишних write-запросов на один PUT.

        'access' выбран намеренно как значение, ОТЛИЧНОЕ от дефолта колонки ('trunk') — иначе
        SQLAlchemy не отправит UPDATE вовсе, даже при ошибочном порядке присваивания (значение
        не изменилось бы относительно уже вставленного дефолта), и тест не поймал бы регрессию."""
        dt = _create_device_type(client, "Тип для подсчёта UPDATE")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "QC-UPDATE"}).json()

        sql_log.clear()
        payload = {"interfaces": [{"name": f"eth{i}", "vlan_mode": "access", "vlan_ids": []} for i in range(5)]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text
        assert all(item["vlan_mode"] == "access" for item in r.json()["items"])

        update_queries = [s for s in sql_log if s.strip().upper().startswith("UPDATE") and "DEVICE_INTERFACES" in s.upper()]
        assert not update_queries, f"Создание новых интерфейсов не должно требовать UPDATE device_interfaces (vlan_mode должен уходить в исходный INSERT), получено {len(update_queries)}: {update_queries}"

    def test_sync_interfaces_creates_and_lists_open_ports(self, client):
        """п.1.4 (батч4): открытые порты теперь свойство интерфейса — переживают сохранение и
        возвращаются вложенными в свой интерфейс, а не общим списком на устройство.

        Правка "убрать текстовые поля Порт/Протокол": port/protocol в payload не отправляются
        вовсе — сервер сам выводит их из protocol_catalog_id (см. _apply_open_port_catalog)."""
        dt = _create_device_type(client, "Коммутатор с портами")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-PORTS-01"}).json()
        https_entry = _create_protocol_catalog_entry(client, 443, "HTTPS")
        snmp_entry = _create_protocol_catalog_entry(client, 161, "SNMP")

        payload = {
            "interfaces": [
                {
                    "name": "Gi0/1",
                    "open_ports": [
                        {"protocol_catalog_id": https_entry["id"], "transport_protocol": "TCP", "description": "Веб-интерфейс"},
                        {"protocol_catalog_id": snmp_entry["id"], "transport_protocol": "UDP"},
                    ],
                },
                {"name": "Gi0/2", "open_ports": []},
            ]
        }
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text
        items = {item["name"]: item for item in r.json()["items"]}
        assert [p["port"] for p in items["Gi0/1"]["open_ports"]] == [161, 443]  # order_by(OpenPort.port)
        assert items["Gi0/1"]["open_ports"][1]["protocol"] == "HTTPS"
        assert items["Gi0/2"]["open_ports"] == []

        # Повторная загрузка (как делает форма при повторном открытии) должна вернуть то же самое.
        r2 = client.get(f"/api/v1/resources/open-ports?owner_type=device_interface&owner_id={items['Gi0/1']['id']}")
        assert r2.status_code == 200
        assert len(r2.json()["items"]) == 2

    def test_sync_interfaces_updates_and_removes_open_ports(self, client):
        dt = _create_device_type(client, "Коммутатор обновление портов")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-PORTS-02"}).json()
        ssh_entry = _create_protocol_catalog_entry(client, 22, "SSH")
        http_entry = _create_protocol_catalog_entry(client, 80, "HTTP")
        https_alt_entry = _create_protocol_catalog_entry(client, 8443, "HTTPS-alt")
        first = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={
                "interfaces": [
                    {
                        "name": "Gi0/1",
                        "open_ports": [
                            {"protocol_catalog_id": ssh_entry["id"]},
                            {"protocol_catalog_id": http_entry["id"]},
                        ],
                    }
                ]
            },
        ).json()
        iface = first["items"][0]
        port_to_keep = next(p for p in iface["open_ports"] if p["port"] == 22)

        # Оставляем один порт (с id — обновляем, меняем описание), убираем второй, добавляем
        # третий новый. Смена protocol_catalog_id на уже существующей строке — self-healing:
        # port/protocol пересчитываются заново из новой ссылки, а не остаются от старой.
        second = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={
                "interfaces": [
                    {
                        "id": iface["id"],
                        "name": "Gi0/1",
                        "open_ports": [
                            {"id": port_to_keep["id"], "protocol_catalog_id": ssh_entry["id"], "description": "обновлено"},
                            {"protocol_catalog_id": https_alt_entry["id"]},
                        ],
                    }
                ]
            },
        )
        assert second.status_code == 200, second.text
        ports = sorted(second.json()["items"][0]["open_ports"], key=lambda p: p["port"])
        assert [p["port"] for p in ports] == [22, 8443]
        assert ports[0]["protocol"] == "SSH"
        assert ports[0]["description"] == "обновлено"

    def test_sync_interfaces_open_port_with_foreign_id_rejected(self, client):
        """Порт, принадлежащий ДРУГОМУ интерфейсу, нельзя переприсвоить простой передачей его id в
        payload другого интерфейса — это защита от подмены владельца, симметричная той же проверке
        для IP интерфейса чуть выше по файлу."""
        dt = _create_device_type(client, "Коммутатор чужой порт")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-PORTS-03"}).json()
        ssh_entry = _create_protocol_catalog_entry(client, 22, "SSH")
        created = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={"interfaces": [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": ssh_entry["id"]}]}, {"name": "Gi0/2", "open_ports": []}]},
        ).json()
        by_name = {i["name"]: i for i in created["items"]}
        foreign_port_id = by_name["Gi0/1"]["open_ports"][0]["id"]

        r = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={
                "interfaces": [
                    {"id": by_name["Gi0/1"]["id"], "name": "Gi0/1", "open_ports": []},
                    {"id": by_name["Gi0/2"]["id"], "name": "Gi0/2", "open_ports": [{"id": foreign_port_id, "protocol_catalog_id": ssh_entry["id"]}]},
                ]
            },
        )
        assert r.status_code == 422

    def test_sync_interfaces_rejects_unknown_protocol_catalog_id(self, client):
        """Замена test_sync_interfaces_rejects_non_numeric_open_port из версии до правки "убрать
        текстовые поля Порт/Протокол": номер порта больше не приходит от клиента как свободный
        текст, поэтому нечего валидировать на "число ли это" — вместо этого проверяем, что
        несуществующая (или отсутствующая) ссылка на справочник отклоняется 422, а не тихо, и не
        падением в 409 на уровне БД."""
        dt = _create_device_type(client, "Коммутатор невалидный порт")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-PORTS-04"}).json()
        r = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={"interfaces": [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": "не-существует"}]}]},
        )
        assert r.status_code == 422

    def test_sync_interfaces_deleting_interface_deletes_its_open_ports(self, client):
        dt = _create_device_type(client, "Коммутатор удаление порта")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-PORTS-05"}).json()
        ssh_entry = _create_protocol_catalog_entry(client, 22, "SSH")
        created = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={"interfaces": [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": ssh_entry["id"]}]}]},
        ).json()
        iface_id = created["items"][0]["id"]

        # Пустой список interfaces — интерфейс удаляется; его открытые порты не должны осиротеть.
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json={"interfaces": []})
        assert r.status_code == 200, r.text
        remaining = client.get(f"/api/v1/resources/open-ports?owner_type=device_interface&owner_id={iface_id}")
        assert remaining.json()["items"] == []


class TestInformationSystemDetails:
    def test_get_details_for_missing_is_returns_404(self, client):
        r = client.get("/api/v1/resources/information-systems/does-not-exist/details")
        assert r.status_code == 404

    def test_sync_and_read_back_departments(self, client):
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС 1"}).json()
        dept = client.post("/api/v1/resources/departments", json={"name": "ИТ-отдел"}).json()

        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"departments": [{"department_id": dept["id"]}]},
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["departments"]) == 1

        r = client.get(f"/api/v1/resources/information-systems/{info['id']}/details")
        assert r.status_code == 200
        assert r.json()["departments"][0]["department_id"] == dept["id"]

    def test_sync_details_writes_audit_entry(self, client):
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС для аудита деталей"}).json()
        dept = client.post("/api/v1/resources/departments", json={"name": "Отдел для аудита деталей"}).json()

        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"departments": [{"department_id": dept["id"]}]},
        )
        assert r.status_code == 200, r.text

        r = client.get("/api/v1/resources/audit-log?entity_type=information-systems&limit=300")
        assert r.status_code == 200
        assert any(x["entity_id"] == info["id"] and x["action"] == "UPDATE" for x in r.json()["items"])

    def test_sync_details_rejects_malformed_ip_in_sources(self, client):
        """information_system_ips (legacy) удалена вместе с остальными устаревшими таблицами-
        связками ИС (см. models.py, миграция b7f2c1e5a904) — IP теперь вводится через вложенный
        список ips на строке sources (InformationSystemSource), по одному адресу на отдельное
        поле (миграция d8e35a1c7f60), и валидация формата — там же (_sync_source_ip_addresses)."""
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС с плохим IP"}).json()
        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"sources": [{"source_type": "manual", "ips": [{"ip_address": "999.999.999.999"}]}]},
        )
        assert r.status_code == 422

    def test_sync_details_rejects_non_string_ip_in_sources(self, client):
        """Код-ревью (отчёт по рефакторингу и безопасности, находка 2): нестроковое значение
        ip_address (валидный JSON: число, список) должно давать аккуратную 422, а не
        необработанное исключение — validate_ipv4_field() сама проверяет isinstance(value, str)."""
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС с IP не строкой"}).json()
        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"sources": [{"source_type": "manual", "ips": [{"ip_address": 12345}]}]},
        )
        assert r.status_code == 422
        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"sources": [{"source_type": "manual", "ips": [{"ip_address": ["10.0.0.1"]}]}]},
        )
        assert r.status_code == 422

    def test_sync_details_rejects_non_list_ips_field(self, client):
        """Поле ips источника должно быть массивом (см. _sync_source_ip_addresses) — тот же класс
        защиты, что и у поля sources самой ИС."""
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС с ips не массивом"}).json()
        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"sources": [{"source_type": "manual", "ips": "10.0.0.1"}]},
        )
        assert r.status_code == 422


class TestInformationSystemSourceDuplicates:
    """Серверная страховка к UI (ISSourcesListEditor скрывает уже добавленные ВМ и контейнеры): одна и та же
    ВМ или контейнер не могут стоять в двух строках sources одной ИС. Без миграции и без удаления данных —
    уже существующие дубли не мешают сохранению ИС, запрещено только добавлять новые."""

    def _make_is(self, client, name="ИС для дублей источников"):
        return client.post("/api/v1/resources/information-systems", json={"name": name}).json()

    def _details_url(self, info):
        return f"/api/v1/resources/information-systems/{info['id']}/details"

    def _vm(self, client, name):
        return client.post("/api/v1/resources/vms", json={"name": name}).json()

    def _container(self, client, name):
        return client.post("/api/v1/resources/containers", json={"name": name}).json()

    def test_rejects_same_vm_in_two_rows(self, client):
        info = self._make_is(client)
        vm = self._vm(client, "ВМ-дубль")

        r = client.put(
            self._details_url(info),
            json={"sources": [{"source_type": "vm", "owner_id": vm["id"]}, {"source_type": "vm", "owner_id": vm["id"]}]},
        )

        assert r.status_code == 422
        assert "ВМ-дубль" in r.json()["detail"]
        # Откат целиком: ни одна из двух строк не сохранилась.
        assert client.get(self._details_url(info)).json()["sources"] == []

    def test_rejects_same_container_in_two_rows(self, client):
        info = self._make_is(client)
        ct = self._container(client, "контейнер-дубль")

        r = client.put(
            self._details_url(info),
            json={"sources": [{"source_type": "container", "owner_id": ct["id"]}, {"source_type": "container", "owner_id": ct["id"]}]},
        )

        assert r.status_code == 422
        assert "контейнер-дубль" in r.json()["detail"]

    def test_allows_different_vms_and_repeated_manual_and_device_rows(self, client):
        """Ограничение — только для ВМ и контейнеров: ручные строки и (пока) серверы могут повторяться."""
        info = self._make_is(client)
        vm1 = self._vm(client, "ВМ-1 без дубля")
        vm2 = self._vm(client, "ВМ-2 без дубля")
        sources = [
            {"source_type": "vm", "owner_id": vm1["id"]},
            {"source_type": "vm", "owner_id": vm2["id"]},
            {"source_type": "manual", "owner_id": "", "ips": [{"ip_address": "10.0.0.1"}]},
            {"source_type": "manual", "owner_id": "", "ips": [{"ip_address": "10.0.0.2"}]},
        ]

        r = client.put(self._details_url(info), json={"sources": sources})

        assert r.status_code == 200, r.text
        assert len(r.json()["sources"]) == 4

    def test_rejects_adding_duplicate_of_already_saved_vm(self, client):
        info = self._make_is(client)
        vm = self._vm(client, "ВМ-уже-в-ИС")
        saved = client.put(self._details_url(info), json={"sources": [{"source_type": "vm", "owner_id": vm["id"]}]})
        assert saved.status_code == 200, saved.text
        existing = saved.json()["sources"][0]

        r = client.put(
            self._details_url(info),
            json={"sources": [{"id": existing["id"], "source_type": "vm", "owner_id": vm["id"], "external_interaction": False}, {"source_type": "vm", "owner_id": vm["id"]}]},
        )

        assert r.status_code == 422
        assert len(client.get(self._details_url(info)).json()["sources"]) == 1

    def test_pre_existing_duplicates_do_not_block_saving(self, client):
        """Старые данные с повтором (до появления проверки) нельзя превращать в блокировку сохранения ИС:
        их можно сохранять без изменений и можно убирать, но нельзя наращивать."""
        info = self._make_is(client)
        vm = self._vm(client, "ВМ-старый-дубль")
        for _ in range(2):  # generic-ресурс не проходит через проверку — так появляются «старые» дубли
            created = client.post(
                "/api/v1/resources/is-sources",
                json={"information_system_id": info["id"], "source_type": "vm", "owner_id": vm["id"]},
            )
            assert created.status_code in (200, 201), created.text
        legacy = client.get(self._details_url(info)).json()["sources"]
        assert len(legacy) == 2
        # external_interaction шлёт и форма: у существующей строки отсутствие поля записало бы NULL в NOT NULL-колонку.
        unchanged = [{"id": x["id"], "source_type": "vm", "owner_id": vm["id"], "external_interaction": False} for x in legacy]

        same = client.put(self._details_url(info), json={"sources": unchanged})
        assert same.status_code == 200, same.text
        assert len(same.json()["sources"]) == 2

        grown = client.put(self._details_url(info), json={"sources": [*unchanged, {"source_type": "vm", "owner_id": vm["id"]}]})
        assert grown.status_code == 422

        reduced = client.put(self._details_url(info), json={"sources": unchanged[:1]})
        assert reduced.status_code == 200, reduced.text
        assert len(reduced.json()["sources"]) == 1


class TestVmIpValidation:
    def test_create_vm_ip_rejects_malformed_ip_address(self, client):
        """Код-ревью п.3.4: IPAddress (владение виртуальной машиной) — единственный путь этой
        модели, идущий через полностью generic create_resource (без выделенной sync-функции, в
        отличие от владения интерфейсом и источником ИС, см. _validate_ip_address_entry)."""
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для теста IP"}).json()
        r = client.post("/api/v1/resources/ip-addresses", json={"owner_type": "virtual_machine", "owner_id": vm["id"], "ip_address": "не IP"})
        assert r.status_code == 422

    def test_create_vm_ip_rejects_out_of_range_prefix_length(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для теста префикса"}).json()
        r = client.post(
            "/api/v1/resources/ip-addresses",
            json={"owner_type": "virtual_machine", "owner_id": vm["id"], "ip_address": "10.0.0.5", "prefix_length": -1},
        )
        assert r.status_code == 422

    def test_create_vm_ip_accepts_valid_ip_and_prefix(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ с корректным IP"}).json()
        r = client.post(
            "/api/v1/resources/ip-addresses",
            json={"owner_type": "virtual_machine", "owner_id": vm["id"], "ip_address": "10.0.0.5", "prefix_length": 24},
        )
        assert r.status_code == 201, r.text


class TestContainerHostExclusivity:
    """Код-ревью (отчёт по анализу БД, вопрос 6): Container.physical_device_id/
    virtual_machine_id — альтернативы по смыслу («размещается либо на ВМ, либо на физическом
    устройстве, либо нигде конкретно»), но модель и БД допускали заполнение обоих одновременно —
    это соблюдалось только на уровне формы (ContainerFormModal.vue). Прямой вызов API в обход
    формы мог записать оба FK сразу."""

    def test_create_rejects_both_host_fields_at_once(self, client):
        dt = _create_device_type(client, "Хост для контейнера")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRV-CONTAINER"}).json()
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для контейнера"}).json()
        r = client.post(
            "/api/v1/resources/containers",
            json={"name": "container-both-hosts", "physical_device_id": dev["id"], "virtual_machine_id": vm["id"]},
        )
        assert r.status_code == 422

    def test_create_accepts_single_host_field(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для контейнера 2"}).json()
        r = client.post(
            "/api/v1/resources/containers",
            json={"name": "container-on-vm", "virtual_machine_id": vm["id"]},
        )
        assert r.status_code == 201, r.text

    def test_create_accepts_neither_host_field(self, client):
        r = client.post("/api/v1/resources/containers", json={"name": "container-no-host"})
        assert r.status_code == 201, r.text

    def test_update_rejects_setting_both_host_fields(self, client):
        dt = _create_device_type(client, "Хост для контейнера 2")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRV-CONTAINER-2"}).json()
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для контейнера 3"}).json()
        container = client.post("/api/v1/resources/containers", json={"name": "container-update", "virtual_machine_id": vm["id"]}).json()
        r = client.put(f"/api/v1/resources/containers/{container['id']}", json={"physical_device_id": dev["id"]})
        assert r.status_code == 422


class TestDeployedSoftwareOwnerType:
    """Код-ревью (отчёт по анализу БД, вопрос 2, подтверждено заказчиком: "в обеих может быть
    одинаковое ПО"): device_software/vm_software объединены в deployed_software с owner_type/
    owner_id — тот же паттерн, что уже применён к OpenPort. Проверяет, что генерик-ресурс
    'deployed-software' действительно фильтруется по владельцу так, как ожидает фронтенд
    (DeviceFormModal.vue/VMFormModal.vue: list_resource с owner_type+owner_id в filters)."""

    def test_create_and_filter_by_device_owner(self, client):
        dt = _create_device_type(client, "Хост для ПО")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRV-SOFTWARE"}).json()
        asset = client.post("/api/v1/resources/software-assets", json={"name": "1С:Предприятие"}).json()
        r = client.post(
            "/api/v1/resources/deployed-software",
            json={"owner_type": "physical_device", "owner_id": dev["id"], "software_asset_id": asset["id"], "version": "8.3"},
        )
        assert r.status_code == 201, r.text

        listing = client.get(f"/api/v1/resources/deployed-software?owner_type=physical_device&owner_id={dev['id']}").json()
        assert len(listing["items"]) == 1
        assert listing["items"][0]["software_asset_id"] == asset["id"]
        assert listing["items"][0]["version"] == "8.3"

    def test_create_and_filter_by_vm_owner(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для ПО"}).json()
        asset = client.post("/api/v1/resources/software-assets", json={"name": "Nginx"}).json()
        r = client.post(
            "/api/v1/resources/deployed-software",
            json={"owner_type": "virtual_machine", "owner_id": vm["id"], "software_asset_id": asset["id"]},
        )
        assert r.status_code == 201, r.text

        listing = client.get(f"/api/v1/resources/deployed-software?owner_type=virtual_machine&owner_id={vm['id']}").json()
        assert len(listing["items"]) == 1
        assert listing["items"][0]["software_asset_id"] == asset["id"]

    def test_device_and_vm_software_do_not_leak_into_each_others_filter(self, client):
        """Один и тот же software_asset_id может быть развёрнут и на устройстве, и на ВМ (это и
        было основанием для объединения) — но список для устройства не должен включать запись ВМ,
        и наоборот."""
        dt = _create_device_type(client, "Хост для ПО 2")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRV-SOFTWARE-2"}).json()
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для ПО 2"}).json()
        asset = client.post("/api/v1/resources/software-assets", json={"name": "Общее ПО"}).json()
        client.post("/api/v1/resources/deployed-software", json={"owner_type": "physical_device", "owner_id": dev["id"], "software_asset_id": asset["id"]})
        client.post("/api/v1/resources/deployed-software", json={"owner_type": "virtual_machine", "owner_id": vm["id"], "software_asset_id": asset["id"]})

        device_listing = client.get(f"/api/v1/resources/deployed-software?owner_type=physical_device&owner_id={dev['id']}").json()
        assert len(device_listing["items"]) == 1
        vm_listing = client.get(f"/api/v1/resources/deployed-software?owner_type=virtual_machine&owner_id={vm['id']}").json()
        assert len(vm_listing["items"]) == 1


class TestNPlusOneRegressions:
    """Закрепляет количество SQL-запросов к конкретным таблицам там, где раньше был N+1 (см.
    историю коммита e068add) — если кто-то случайно вернёт запрос внутрь цикла, эти тесты упадут
    сразу на маленьком наборе данных, а не когда это станет заметно на реальном объёме."""

    def test_sync_interfaces_allowed_vlan_lookup_does_not_scale_with_port_count(self, client, sql_log):
        dt = _create_device_type(client, "Тип для подсчёта запросов")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "QC-1"}).json()

        sql_log.clear()
        payload = {"interfaces": [{"name": f"eth{i}"} for i in range(10)]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text

        vlan_lookup_queries = [s for s in sql_log if "device_type_vlans" in s or "physical_device_vlans" in s]
        # Раньше — 2 запроса НА КАЖДЫЙ интерфейс (было бы 20 для 10 портов); теперь — 2 на весь вызов.
        assert len(vlan_lookup_queries) <= 2, f"Ожидалось <=2 запроса к allowed-VLAN, получено {len(vlan_lookup_queries)}"

    def test_delete_reference_check_uses_a_single_query_across_all_referencing_models(self, client, sql_log):
        """Код-ревью п.3.7: _find_referencing_counts раньше делала отдельный SELECT COUNT(*) на
        каждую FK-колонку каждой из ~40 моделей реестра — теперь один запрос через UNION ALL,
        независимо от того, сколько РАЗНЫХ моделей и записей реально ссылаются на удаляемую."""
        dt = _create_device_type(client, "Тип для подсчёта ссылок")
        manufacturer = client.post("/api/v1/resources/manufacturers", json={"name": "Производитель для подсчёта"}).json()
        for i in range(2):
            r = client.post(
                "/api/v1/resources/device-models",
                json={"manufacturer_id": manufacturer["id"], "device_type_id": dt["id"], "model": f"Модель {i}"},
            )
            assert r.status_code == 201, r.text

        sql_log.clear()
        r = client.delete(f"/api/v1/resources/manufacturers/{manufacturer['id']}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"
        assert "2" in r.json()["detail"]["message"]  # обе модели учтены одним запросом

        count_queries = [s for s in sql_log if "count(" in s.lower()]
        assert len(count_queries) == 1, f"Ожидался 1 запрос на подсчёт ссылок, получено {len(count_queries)}:\n" + "\n".join(count_queries)

    def test_sync_vlan_domain_does_not_query_per_device_per_vlan_pair(self, client, sql_log):
        dt = _create_device_type(client, "Тип для домена подсчёта")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "QC-SRC"}).json()
        members = [client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": f"QC-M{i}"}).json() for i in range(5)]
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен подсчёта", "source_device_id": source["id"]}).json()
        for dev in [source, *members]:
            r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": dev["id"]})
            assert r.status_code == 200, r.text
        vlans = [client.post("/api/v1/resources/vlans", json={"vlan_id": 900 + i, "name": f"Домен-{i}"}).json() for i in range(3)]
        for vlan in vlans:
            r = client.post("/api/v1/resources/device-vlans", json={"physical_device_id": source["id"], "vlan_id": vlan["id"]})
            assert r.status_code == 201, r.text

        sql_log.clear()
        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync")
        assert r.status_code == 200, r.text

        vlan_select_queries = [s for s in sql_log if s.strip().upper().startswith("SELECT") and "vlans" in s.lower()]
        # 5 участников x 3 VLAN = 15 пар устройство/VLAN; раньше на каждую пару был отдельный
        # SELECT (было бы >=15). Теперь домен-локальные VLAN и назначения участников загружаются
        # пакетно один раз каждое — независимо от числа пар.
        assert len(vlan_select_queries) < 15, f"Ожидалось < 15 SELECT к VLAN-таблицам, получено {len(vlan_select_queries)}"

    def test_sync_linked_table_flushes_once_not_per_item(self, client, sql_log):
        """Код-ревью п.6 (Low, производительность): _sync_linked_table/
        _sync_information_system_sources делали session.flush() на КАЖДЫЙ элемент списка — N
        лишних round-trip'ов к БД на большом списке связанных записей. obj.id для новых строк
        внутри этих функций не используется (нужен только у уже существующих, которые и так
        приходят с id из первого SELECT), поэтому один flush() после цикла достаточен."""
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС для батчинга flush"}).json()
        departments = [client.post("/api/v1/resources/departments", json={"name": f"Отдел батч {i}"}).json() for i in range(8)]

        sql_log.clear()
        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"departments": [{"department_id": d["id"]} for d in departments]},
        )
        assert r.status_code == 200, r.text

        insert_calls = [s for s in sql_log if "INSERT INTO information_system_departments" in s]
        # Раньше — 8 отдельных execute (flush() внутри цикла на каждый из 8 отделов). Теперь —
        # один execute на весь список (SQLAlchemy собирает INSERT-ы одного flush() в batch).
        assert len(insert_calls) == 1, f"Ожидался один batched INSERT, получено {len(insert_calls)}: {insert_calls}"


class TestBulkVlanAssign:
    def _setup(self, client, n_devices=3):
        dt = _create_device_type(client, "Тип для bulk-VLAN")
        devices = [client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": f"BULK-{i}"}).json() for i in range(n_devices)]
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 88, "name": "Bulk"}).json()
        return devices, vlan

    def test_assigns_vlan_to_every_listed_device(self, client):
        devices, vlan = self._setup(client)
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"], "description": "Тест"},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "assigned": 3, "skipped_existing": 0}
        for d in devices:
            r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={d['id']}")
            assert any(x["vlan_id"] == vlan["id"] for x in r.json()["items"])

    def test_skips_devices_already_assigned_and_is_idempotent(self, client):
        devices, vlan = self._setup(client, n_devices=2)
        client.post(
            "/api/v1/resources/device-vlans",
            json={"physical_device_id": devices[0]["id"], "vlan_id": vlan["id"]},
        )
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"]},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "assigned": 1, "skipped_existing": 1}

        # Повторный вызов с теми же устройствами больше ничего не добавляет.
        r2 = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"]},
        )
        assert r2.json() == {"status": "ok", "assigned": 0, "skipped_existing": 2}

    def test_rejects_empty_device_list(self, client):
        _, vlan = self._setup(client, n_devices=0)
        r = client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": [], "vlan_id": vlan["id"]})
        assert r.status_code == 422

    def test_rejects_unknown_vlan(self, client):
        devices, _ = self._setup(client, n_devices=1)
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [devices[0]["id"]], "vlan_id": "не-существует"},
        )
        assert r.status_code == 404

    def test_rejects_unknown_device(self, client):
        _, vlan = self._setup(client, n_devices=0)
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": ["не-существует"], "vlan_id": vlan["id"]},
        )
        assert r.status_code == 404

    def test_bulk_assign_writes_audit_entry(self, client):
        devices, vlan = self._setup(client, n_devices=2)
        client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"]},
        )
        r = client.get("/api/v1/resources/audit-log?entity_type=device-vlans&limit=300")
        assert r.status_code == 200
        assert any(x["entity_id"] == vlan["id"] and x["action"] == "SYNC" for x in r.json()["items"])


class TestVlanDomainMemberAudit:
    def test_add_member_writes_audit_entry(self, client):
        dt = _create_device_type(client, "Тип для аудита членства")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUD-SRC"}).json()
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUD-M"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен для аудита", "source_device_id": source["id"]}).json()

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})
        assert r.status_code == 200, r.text
        membership_id = r.json()["id"]

        r = client.get("/api/v1/resources/audit-log?entity_type=vlan-domain-devices&limit=300")
        assert r.status_code == 200
        assert any(x["entity_id"] == membership_id and x["action"] == "CREATE" for x in r.json()["items"])

    def test_add_member_twice_is_idempotent_and_audits_once(self, client):
        dt = _create_device_type(client, "Тип идемпотентности членства")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "IDM-SRC"}).json()
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "IDM-M"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен идемпотентности", "source_device_id": source["id"]}).json()

        r1 = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})
        r2 = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["id"] == r2.json()["id"]

        r = client.get("/api/v1/resources/audit-log?entity_type=vlan-domain-devices&limit=300")
        entries = [x for x in r.json()["items"] if x["entity_id"] == r1.json()["id"]]
        assert len(entries) == 1  # повторное добавление — no-op, второй audit-записи быть не должно


class TestCopyDeviceVlans:
    def test_copies_vlans_from_source_and_writes_audit_entry(self, client):
        dt = _create_device_type(client, "Тип для копирования VLAN")
        source = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "CP-SRC", "system_name": "src-sw"},
        ).json()
        target = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "CP-DST"}).json()
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 55, "name": "Копия"}).json()
        r = client.post("/api/v1/resources/device-vlans", json={"physical_device_id": source["id"], "vlan_id": vlan["id"]})
        assert r.status_code == 201, r.text

        r = client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={"source_device_id": source["id"]})
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "created_definitions": 1, "assigned": 1}

        r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={target['id']}")
        assert r.status_code == 200
        assert len(r.json()["items"]) == 1

        r = client.get("/api/v1/resources/audit-log?entity_type=devices&limit=300")
        assert r.status_code == 200
        assert any(x["entity_id"] == target["id"] and x["action"] == "SYNC" for x in r.json()["items"])

    def test_rejects_missing_source_or_target(self, client):
        dt = _create_device_type(client, "Тип для проверки ошибок копирования")
        target = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "CP-ERR"}).json()
        r = client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={"source_device_id": "не-существует"})
        assert r.status_code == 404


class TestVlanDomainMemberGetsDomainVlansImmediately:
    """Пункт 2 правки "домен VLAN": устройство, добавленное в домен, должно СРАЗУ получить набор
    VLAN этого домена — без отдельного ручного "Синхронизировать" (см. assign_domain_vlans_to_device
    в services/crud/, вызывается и из add_vlan_domain_member, и из create_resource — оба пути
    добавления участника, см. docstring функции)."""

    def _domain_with_synced_vlans(self, client):
        """Домен с двумя своими VLAN (10, 20) — как будто уже был синхронизирован с
        устройством-источником хотя бы раз."""
        dt = _create_device_type(client, "Коммутатор для готового домена")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "MVI-SRC"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен с VLAN", "source_device_id": source["id"]}).json()
        for vlan_id in (10, 20):
            client.post("/api/v1/resources/vlans", json={"vlan_id": vlan_id, "name": f"VLAN {vlan_id}", "domain_id": domain["id"]})
        return dt, domain

    def test_add_member_via_dedicated_endpoint_gets_domain_vlans_without_manual_sync(self, client):
        dt, domain = self._domain_with_synced_vlans(client)
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "MVI-M1"}).json()

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})
        assert r.status_code == 200, r.text

        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        assigned_numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in assigned)
        assert assigned_numbers == [10, 20]

    def test_add_member_via_generic_resource_also_gets_domain_vlans(self, client):
        """Тот же эффект через generic-ресурс (POST /resources/vlan-domain-devices) — этим путём
        идёт, например, DeviceFormModal.vue:persistPendingDomainMemberships."""
        dt, domain = self._domain_with_synced_vlans(client)
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "MVI-M2"}).json()

        r = client.post("/api/v1/resources/vlan-domain-devices", json={"domain_id": domain["id"], "physical_device_id": member["id"]})
        assert r.status_code == 201, r.text

        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        assigned_numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in assigned)
        assert assigned_numbers == [10, 20]

    def test_add_member_to_domain_without_any_vlans_yet_does_not_fail(self, client):
        dt = _create_device_type(client, "Коммутатор для пустого домена")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Пустой домен"}).json()
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "MVI-M3"}).json()

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})
        assert r.status_code == 200, r.text
        assert client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"] == []

    def test_add_member_does_not_duplicate_vlan_already_manually_assigned(self, client):
        dt, domain = self._domain_with_synced_vlans(client)
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "MVI-M4"}).json()
        vlan10 = client.get("/api/v1/resources/vlans", params={"domain_id": domain["id"]}).json()["items"]
        vlan10_id = next(v["id"] for v in vlan10 if v["vlan_id"] == 10)
        client.post("/api/v1/resources/device-vlans", json={"physical_device_id": member["id"], "vlan_id": vlan10_id})

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})
        assert r.status_code == 200, r.text

        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        assert len(assigned) == 2  # VLAN 10 (уже был) + VLAN 20 (добавлен) — без дублей VLAN 10


class TestVlanDomainSync:
    def test_sync_creates_definitions_and_assigns_to_members(self, client):
        """POST /vlan-domains/{id}/sync must propagate every source-device VLAN to every other
        member device exactly once — regression test for the N+1 refactor in api/system.py."""
        dt = _create_device_type(client, "Коммутатор VLAN-домена")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "VD-SRC"}).json()
        member1 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "VD-M1"}).json()
        member2 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "VD-M2"}).json()

        domain = client.post(
            "/api/v1/resources/vlan-domains",
            json={"name": "Домен-тест", "source_device_id": source["id"]},
        ).json()
        for dev in (source, member1, member2):
            r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": dev["id"]})
            assert r.status_code == 200, r.text

        vlan10 = client.post("/api/v1/resources/vlans", json={"vlan_id": 10, "name": "Данные"}).json()
        vlan20 = client.post("/api/v1/resources/vlans", json={"vlan_id": 20, "name": "Управление"}).json()
        for vlan in (vlan10, vlan20):
            r = client.post(
                "/api/v1/resources/device-vlans",
                json={"physical_device_id": source["id"], "vlan_id": vlan["id"]},
            )
            assert r.status_code == 201, r.text

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created_definitions"] == 2  # два домен-локальных определения (VLAN 10 и 20)
        assert body["assigned"] == 4  # 2 участника (member1, member2) × 2 VLAN

        for member in (member1, member2):
            r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}")
            assert r.status_code == 200
            assigned_numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in r.json()["items"])
            assert assigned_numbers == [10, 20]

        # Re-running sync must not create duplicate definitions or duplicate assignments.
        r2 = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync")
        assert r2.status_code == 200
        assert r2.json() == {"status": "ok", "created_definitions": 0, "assigned": 0, "removed": 0}

        r = client.get("/api/v1/resources/audit-log?entity_type=vlan-domains&limit=300")
        assert r.status_code == 200
        assert any(x["entity_id"] == domain["id"] and x["action"] == "SYNC" for x in r.json()["items"])


class TestVlanDomainReplaceSync:
    """Пункт 1 правки "домен VLAN": смена устройства-источника должна иметь возможность
    ПЕРЕЗАПИСАТЬ VLAN участников под новый источник (не только добавить недостающее, как обычная
    синхронизация) — см. docstring sync_vlan_domain в api/system.py про replace=true."""

    def _domain_with_stale_member_vlan(self, client):
        """Источник и участник — сначала обычная (не replace) синхронизация раскладывает
        domain-VLAN 10 и 20 штатным путём (та же цепочка, что в реальности). Затем источник
        «теряет» VLAN 20 (например, снят на реальном оборудовании) — участник по-прежнему хранит
        VLAN 20 как устаревший остаток прошлой синхронизации. VLAN 10 у источника остаётся —
        должен пережить любой режим синхронизации."""
        dt = _create_device_type(client, "Коммутатор replace-синхронизации")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "RSY-SRC"}).json()
        member = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "RSY-M"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен replace", "source_device_id": source["id"]}).json()
        client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": source["id"]})
        client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": member["id"]})

        vlan10 = client.post("/api/v1/resources/vlans", json={"vlan_id": 10, "name": "Данные"}).json()
        vlan20 = client.post("/api/v1/resources/vlans", json={"vlan_id": 20, "name": "Управление"}).json()
        client.post("/api/v1/resources/device-vlans", json={"physical_device_id": source["id"], "vlan_id": vlan10["id"]})
        client.post("/api/v1/resources/device-vlans", json={"physical_device_id": source["id"], "vlan_id": vlan20["id"]})

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={})
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "created_definitions": 2, "assigned": 2, "removed": 0}

        source_vlan20_link = next(row for row in client.get(f"/api/v1/resources/device-vlans?physical_device_id={source['id']}").json()["items"] if client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] == 20)
        client.delete(f"/api/v1/resources/device-vlans/{source_vlan20_link['id']}")
        return domain, member

    def test_sync_without_replace_keeps_stale_vlan_no_longer_on_source(self, client):
        domain, member = self._domain_with_stale_member_vlan(client)

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={})
        assert r.status_code == 200, r.text
        assert r.json()["removed"] == 0

        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in assigned)
        assert numbers == [10, 20]  # VLAN 20 остался, хотя источник его больше не имеет

    def test_sync_with_replace_removes_stale_vlan_but_keeps_current_one(self, client):
        domain, member = self._domain_with_stale_member_vlan(client)

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={"replace": True})
        assert r.status_code == 200, r.text
        assert r.json()["removed"] == 1

        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in assigned)
        assert numbers == [10]  # VLAN 20 (устаревший) убран, VLAN 10 (есть у источника) остался

    def test_sync_with_replace_does_not_touch_vlans_outside_this_domain(self, client):
        """VLAN участника из ДРУГОГО домена (или вовсе локальный, без domain_id) — вне области
        действия replace, даже если формально это «лишний» с точки зрения текущего источника."""
        domain, member = self._domain_with_stale_member_vlan(client)
        other_domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Другой домен"}).json()
        # Устройству нельзя назначить VLAN чужого домена, не будучи его участником (отдельная
        # валидация _validate_physical_device_vlan_entry) — добавляем member и туда тоже.
        client.post(f"/api/v1/vlan-domains/{other_domain['id']}/members", json={"physical_device_id": member["id"]})
        foreign_vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 99, "name": "Чужой домен", "domain_id": other_domain["id"]}).json()
        local_vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 100, "name": "Локальный, без домена"}).json()
        # VLAN другого домена уже назначен устройству-участнику этого домена автоматически (см.
        # _auto_assign_new_domain_vlan_to_domain_devices в services/crud/), вручную — только локальный.
        before = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        assert foreign_vlan["id"] in {row["vlan_id"] for row in before}
        r2 = client.post("/api/v1/resources/device-vlans", json={"physical_device_id": member["id"], "vlan_id": local_vlan["id"]})
        assert r2.status_code == 201, r2.text

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={"replace": True})
        assert r.status_code == 200, r.text

        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}").json()["items"]
        numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in assigned)
        assert numbers == [10, 99, 100]  # 20 (устаревший, этого домена) убран, чужой/локальный — нет


class TestOpenPortCatalogIsSourceOfTruth:
    """Правка "убрать текстовые поля Порт/Протокол — эта информация уже есть в справочнике
    портов": generic-ресурс open-ports (используется ВМ-формой, в отличие от интерфейсов
    устройства со своим _sync_interface_open_ports, покрытым TestInterfacesSync выше)."""

    def test_create_without_catalog_reference_rejected(self, client):
        r = client.post("/api/v1/resources/open-ports", json={"owner_type": "virtual_machine", "owner_id": "vm-1"})
        assert r.status_code == 422
        assert "справочник" in r.json()["detail"].lower()

    def test_create_with_unknown_catalog_id_rejected(self, client):
        r = client.post(
            "/api/v1/resources/open-ports",
            json={"owner_type": "virtual_machine", "owner_id": "vm-1", "protocol_catalog_id": "нет-такого-id"},
        )
        assert r.status_code == 422

    def test_create_ignores_client_supplied_port_and_protocol(self, client):
        """Даже если клиент в обход UI пришлёт свои port/protocol вместе с protocol_catalog_id,
        сервер должен использовать значения САМОЙ записи справочника, а не то, что прислал клиент —
        иначе OpenPort мог бы разойтись со справочником, ради единственного источника истины в
        котором эти два текстовых поля и были убраны из формы."""
        entry = _create_protocol_catalog_entry(client, 3389, "RDP")
        r = client.post(
            "/api/v1/resources/open-ports",
            json={
                "owner_type": "virtual_machine",
                "owner_id": "vm-1",
                "protocol_catalog_id": entry["id"],
                "port": 9999,
                "protocol": "ПОДДЕЛЬНЫЙ",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["port"] == 3389
        assert body["protocol"] == "RDP"

    def test_update_resyncs_port_and_protocol_when_catalog_reference_changes(self, client):
        old_entry = _create_protocol_catalog_entry(client, 22, "SSH")
        new_entry = _create_protocol_catalog_entry(client, 443, "HTTPS")
        created = client.post(
            "/api/v1/resources/open-ports",
            json={"owner_type": "virtual_machine", "owner_id": "vm-1", "protocol_catalog_id": old_entry["id"]},
        ).json()

        r = client.put(f"/api/v1/resources/open-ports/{created['id']}", json={"protocol_catalog_id": new_entry["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["port"] == 443
        assert r.json()["protocol"] == "HTTPS"

    def test_protocol_catalog_id_is_not_null_at_db_level(self, client, db_session):
        """Выполнено «Возможное улучшение 1» из прошлой правки: миграция a1b7c9d3e502 забэкфиллила
        старые строки без protocol_catalog_id и перевела колонку в NOT NULL — до неё этот же вызов
        создавал бы «повисшую» запись без ссылки на справочник (см. удалённый тест
        test_update_unrelated_field_on_legacy_row_without_catalog_reference_still_works в истории).
        Теперь такую строку нельзя завести даже в обход API, напрямую через ORM — IntegrityError
        летит уже на commit(), до всякой прикладной валидации."""
        from app.models import OpenPort
        from sqlalchemy.exc import IntegrityError

        legacy = OpenPort(owner_type="virtual_machine", owner_id="vm-legacy")
        db_session.add(legacy)
        with pytest.raises(IntegrityError):
            db_session.commit()


class TestPolymorphicOwnerCleanupOnDelete:
    """Код-ревью (отчёт по рефакторингу и безопасности, находка 1): open_ports.owner_id/
    owner_type — полиморфная связь БЕЗ настоящего ForeignKey в БД (см. docstring models.OpenPort),
    поэтому обычная проверка ссылок (_find_referencing_counts) её не видит. До правки
    DELETE /resources/{interfaces,vms,devices}/{id} в обход sync_interfaces оставлял такие
    open_ports в базе осиротевшими (owner_id указывал на уже не существующую запись). После
    объединения DeployedSoftware/IPAddress в тот же паттерн (owner_type/owner_id) — тот же риск и
    для них, поэтому _POLYMORPHIC_OWNER_CLEANUP покрывает обе модели тоже (см. crud/)."""

    def test_deleting_interface_removes_its_open_ports(self, client):
        dt = _create_device_type(client, "Коммутатор для удаления порта")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-DEL-IF"}).json()
        ssh_entry = _create_protocol_catalog_entry(client, 22, "SSH")
        r = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={"interfaces": [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": ssh_entry["id"]}]}]},
        )
        iface = r.json()["items"][0]
        port_id = iface["open_ports"][0]["id"]

        r = client.delete(f"/api/v1/resources/interfaces/{iface['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/open-ports/{port_id}").status_code == 404

    def test_deleting_vm_removes_its_open_ports(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для удаления порта"}).json()
        rdp_entry = _create_protocol_catalog_entry(client, 3389, "RDP")
        port = client.post(
            "/api/v1/resources/open-ports",
            json={"owner_type": "virtual_machine", "owner_id": vm["id"], "protocol_catalog_id": rdp_entry["id"]},
        ).json()

        r = client.delete(f"/api/v1/resources/vms/{vm['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/open-ports/{port['id']}").status_code == 404

    def test_deleting_device_removes_its_legacy_open_ports(self, client):
        """owner_type='physical_device' — устаревший паттерн (порт привязан к устройству
        напрямую, без интерфейса, см. constants.OwnerType); устройство без интерфейсов не имеет
        настоящих FK-ссылок, блокирующих удаление, поэтому такой порт осиротевал бы точно так же,
        как и в двух тестах выше."""
        dt = _create_device_type(client, "Коммутатор с портом на уровне устройства")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-DEL-DEV"}).json()
        snmp_entry = _create_protocol_catalog_entry(client, 161, "SNMP")
        port = client.post(
            "/api/v1/resources/open-ports",
            json={"owner_type": "physical_device", "owner_id": dev["id"], "protocol_catalog_id": snmp_entry["id"]},
        ).json()

        r = client.delete(f"/api/v1/resources/devices/{dev['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/open-ports/{port['id']}").status_code == 404

    def test_deleting_interface_removes_its_ip_addresses(self, client):
        dt = _create_device_type(client, "Коммутатор для удаления IP")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-DEL-IP"}).json()
        r = client.put(
            f"/api/v1/devices/{dev['id']}/interfaces",
            json={"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}]}]},
        )
        iface = r.json()["items"][0]
        ip_id = iface["ips"][0]["id"]

        r = client.delete(f"/api/v1/resources/interfaces/{iface['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/ip-addresses/{ip_id}").status_code == 404

    def test_deleting_vm_removes_its_ip_addresses_and_software(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для удаления IP и ПО"}).json()
        ip = client.post("/api/v1/resources/ip-addresses", json={"owner_type": "virtual_machine", "owner_id": vm["id"], "ip_address": "10.0.0.9"}).json()
        asset = client.post("/api/v1/resources/software-assets", json={"name": "ПО для удаления ВМ"}).json()
        software = client.post("/api/v1/resources/deployed-software", json={"owner_type": "virtual_machine", "owner_id": vm["id"], "software_asset_id": asset["id"]}).json()

        r = client.delete(f"/api/v1/resources/vms/{vm['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/ip-addresses/{ip['id']}").status_code == 404
        assert client.get(f"/api/v1/resources/deployed-software/{software['id']}").status_code == 404

    def test_deleting_device_removes_its_deployed_software(self, client):
        dt = _create_device_type(client, "Устройство для удаления ПО")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-DEL-SOFT"}).json()
        asset = client.post("/api/v1/resources/software-assets", json={"name": "ПО для удаления устройства"}).json()
        software = client.post("/api/v1/resources/deployed-software", json={"owner_type": "physical_device", "owner_id": dev["id"], "software_asset_id": asset["id"]}).json()

        r = client.delete(f"/api/v1/resources/devices/{dev['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/deployed-software/{software['id']}").status_code == 404

    def test_deleting_is_source_removes_its_ip_addresses(self, client):
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС для удаления источника"}).json()
        source = client.post("/api/v1/resources/is-sources", json={"information_system_id": is_["id"], "source_type": "manual"}).json()
        ip = client.post("/api/v1/resources/ip-addresses", json={"owner_type": "information_system_source", "owner_id": source["id"], "ip_address": "10.5.5.5"}).json()

        r = client.delete(f"/api/v1/resources/is-sources/{source['id']}")
        assert r.status_code == 200, r.text

        assert client.get(f"/api/v1/resources/ip-addresses/{ip['id']}").status_code == 404


class TestInformationSystemSourceBlocksOwnerDeletion:
    """Правка "переработка структуры БД", п.5 отчёта по анализу БД: information_system_sources.
    owner_id ссылается на устройство/ВМ/контейнер, но НЕ является настоящим FK (миграция
    944bd490d967, см. docstring models.InformationSystemSource) — в отличие от
    TestPolymorphicOwnerCleanupOnDelete выше, здесь семантика владения ОБРАТНАЯ (ИС ссылается на
    оборудование, не владеет им), поэтому вместо тихой зачистки нужна блокировка удаления —
    воссоздана вручную: crud.assert_deletable() + services/integrity.py (before_delete, триггеры БД)."""

    def test_cannot_delete_device_referenced_by_is_source(self, client):
        dt = _create_device_type(client, "Сервер для блокировки удаления по источнику ИС")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-IS-SRC-DEV"}).json()
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС на устройстве"}).json()
        client.post("/api/v1/resources/is-sources", json={"information_system_id": is_["id"], "source_type": "device", "owner_id": dev["id"]})

        r = client.delete(f"/api/v1/resources/devices/{dev['id']}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"

    def test_cannot_delete_vm_referenced_by_is_source(self, client):
        vm = client.post("/api/v1/resources/vms", json={"name": "ВМ для блокировки удаления по источнику ИС"}).json()
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС на ВМ"}).json()
        client.post("/api/v1/resources/is-sources", json={"information_system_id": is_["id"], "source_type": "vm", "owner_id": vm["id"]})

        r = client.delete(f"/api/v1/resources/vms/{vm['id']}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"

    def test_cannot_delete_container_referenced_by_is_source(self, client):
        container = client.post("/api/v1/resources/containers", json={"name": "container-is-src"}).json()
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС на контейнере"}).json()
        client.post("/api/v1/resources/is-sources", json={"information_system_id": is_["id"], "source_type": "container", "owner_id": container["id"]})

        r = client.delete(f"/api/v1/resources/containers/{container['id']}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"

    def test_device_deletable_again_after_referencing_source_removed(self, client):
        dt = _create_device_type(client, "Сервер, источник ИС на котором потом удалили")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-IS-SRC-FREED"}).json()
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС, источник которой удалили"}).json()
        source = client.post("/api/v1/resources/is-sources", json={"information_system_id": is_["id"], "source_type": "device", "owner_id": dev["id"]}).json()

        assert client.delete(f"/api/v1/resources/devices/{dev['id']}").status_code == 409
        assert client.delete(f"/api/v1/resources/is-sources/{source['id']}").status_code == 200

        r = client.delete(f"/api/v1/resources/devices/{dev['id']}")
        assert r.status_code == 200, r.text

    def test_manual_source_never_blocks_any_owner_deletion(self, client):
        """source_type='manual' не задействует блокировку ни для одного resource — owner_id у
        такой строки всегда NULL, поэтому нет и не может быть записи, для удаления которой она
        стала бы препятствием; тест лишь фиксирует это явно, а не проверяет отсутствие побочного
        эффекта на всех resource-типах разом."""
        dt = _create_device_type(client, "Сервер, не связанный ни с одним источником ИС")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SW-IS-SRC-MANUAL"}).json()
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС с ручным источником"}).json()
        client.post("/api/v1/resources/is-sources", json={"information_system_id": is_["id"], "source_type": "manual"})

        r = client.delete(f"/api/v1/resources/devices/{dev['id']}")
        assert r.status_code == 200, r.text


class TestNewDomainVlanAutoAssignedToSourceDevice:
    """Пункт 2 правки "создание физического устройства": VLAN, заведённый в справочник (POST
    /resources/vlans) сразу с domain_id, должен появиться в «VLAN устройства» устройства-источника
    домена без отдельного ручного шага — до этой правки sync_vlan_domain не помогал (см. docstring
    _auto_assign_new_domain_vlan_to_source_device в services/crud/): он реплицирует то, что УЖЕ
    назначено источнику, а только что созданный VLAN там ещё не значится."""

    def test_create_with_domain_that_has_source_device_auto_assigns(self, client):
        dt = _create_device_type(client, "Коммутатор авто-VLAN")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUTO-SRC-1"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен с источником", "source_device_id": source["id"]}).json()

        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 77, "name": "Гости", "domain_id": domain["id"]}).json()

        r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={source['id']}")
        assert r.status_code == 200
        assert [row["vlan_id"] for row in r.json()["items"]] == [vlan["id"]]

    def test_create_with_domain_without_source_device_does_not_fail(self, client):
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен без источника"}).json()
        r = client.post("/api/v1/resources/vlans", json={"vlan_id": 78, "name": "Без источника", "domain_id": domain["id"]})
        assert r.status_code == 201, r.text

    def test_create_without_domain_does_not_auto_assign_anywhere(self, client):
        dt = _create_device_type(client, "Коммутатор для локального VLAN")
        device = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUTO-SRC-2"}).json()
        client.post("/api/v1/resources/vlans", json={"vlan_id": 79, "name": "Локальный"})
        r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={device['id']}")
        assert r.json()["items"] == []

    def test_assigning_domain_via_update_also_auto_assigns(self, client):
        """Тот же эффект, если domain_id проставлен не сразу при создании VLAN, а последующим
        PUT — VLANFormModal.vue допускает и такое (редактирование существующего локального VLAN,
        привязка его к домену задним числом)."""
        dt = _create_device_type(client, "Коммутатор для отложенной привязки")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUTO-SRC-3"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен для PUT", "source_device_id": source["id"]}).json()
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 80, "name": "Позже в домене"}).json()

        r = client.put(f"/api/v1/resources/vlans/{vlan['id']}", json={"domain_id": domain["id"]})
        assert r.status_code == 200, r.text

        r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={source['id']}")
        assert [row["vlan_id"] for row in r.json()["items"]] == [vlan["id"]]

    def test_editing_unrelated_field_does_not_duplicate_or_touch_assignment(self, client):
        """domain_id НЕ пришёл в payload этого PUT — авто-назначение не должно срабатывать повторно
        (условие 'domain_id' in payload в update_resource); подтверждаем через отсутствие
        дублирования записи device-vlans."""
        dt = _create_device_type(client, "Коммутатор без повторного назначения")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUTO-SRC-4"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен без дублей", "source_device_id": source["id"]}).json()
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 81, "name": "Без дублей", "domain_id": domain["id"]}).json()

        r = client.put(f"/api/v1/resources/vlans/{vlan['id']}", json={"description": "просто описание"})
        assert r.status_code == 200, r.text

        r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={source['id']}")
        assert len(r.json()["items"]) == 1

    def test_does_not_duplicate_if_source_device_already_has_this_vlan(self, client):
        """Устройство-источник могло уже иметь этот VLAN назначенным вручную ДО того, как VLAN
        привязали к домену (или до повторного PUT domain_id на том же значении) — уникальный
        constraint uq_physical_device_vlan не должен превратиться в 409 на ровном месте."""
        dt = _create_device_type(client, "Коммутатор ручного назначения")
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "AUTO-SRC-5"}).json()
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен ручного назначения", "source_device_id": source["id"]}).json()
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 82, "name": "Уже назначен"}).json()
        client.post("/api/v1/resources/device-vlans", json={"physical_device_id": source["id"], "vlan_id": vlan["id"]})

        r = client.put(f"/api/v1/resources/vlans/{vlan['id']}", json={"domain_id": domain["id"]})
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={source['id']}")
        assert len(r.json()["items"]) == 1


class TestNewDomainVlanAssignedToAllDomainDevices:
    """Правка "VLAN домена": новый VLAN домена появляется в «VLAN устройства» ВСЕХ устройств этого
    домена (участников и источника), а не только у источника — без ручного «Синхронизировать»
    (см. _auto_assign_new_domain_vlan_to_domain_devices в services/crud/)."""

    def _device(self, client, dt, serial):
        return client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()

    def _join(self, client, domain, device):
        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": device["id"]})
        assert r.status_code == 200, r.text

    def _assigned(self, client, device):
        return [row["vlan_id"] for row in client.get(f"/api/v1/resources/device-vlans?physical_device_id={device['id']}").json()["items"]]

    def test_new_vlan_reaches_source_and_every_member(self, client):
        dt = _create_device_type(client, "Коммутатор домена")
        source = self._device(client, dt, "DOM-ALL-SRC")
        member1, member2 = self._device(client, dt, "DOM-ALL-M1"), self._device(client, dt, "DOM-ALL-M2")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен для всех", "source_device_id": source["id"]}).json()
        self._join(client, domain, member1)
        self._join(client, domain, member2)

        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 201, "name": "Для всех", "domain_id": domain["id"]}).json()

        for device in (source, member1, member2):
            assert self._assigned(client, device) == [vlan["id"]], device["serial_number"]

    def test_domain_without_source_device_still_assigns_to_members(self, client):
        dt = _create_device_type(client, "Коммутатор домена без источника")
        member = self._device(client, dt, "DOM-NOSRC-M1")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен без источника, с участником"}).json()
        self._join(client, domain, member)

        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 202, "name": "Без источника", "domain_id": domain["id"]}).json()

        assert self._assigned(client, member) == [vlan["id"]]

    def test_devices_outside_the_domain_are_not_touched(self, client):
        dt = _create_device_type(client, "Коммутатор вне домена")
        member, outsider = self._device(client, dt, "DOM-OUT-M1"), self._device(client, dt, "DOM-OUT-X1")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен без посторонних"}).json()
        self._join(client, domain, member)

        client.post("/api/v1/resources/vlans", json={"vlan_id": 203, "name": "Только домену", "domain_id": domain["id"]})

        assert self._assigned(client, outsider) == []

    def test_assigning_domain_via_update_reaches_every_member(self, client):
        dt = _create_device_type(client, "Коммутатор отложенной привязки к домену")
        member1, member2 = self._device(client, dt, "DOM-UPD-M1"), self._device(client, dt, "DOM-UPD-M2")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен для PUT всем"}).json()
        self._join(client, domain, member1)
        self._join(client, domain, member2)
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 204, "name": "Позже в домене всем"}).json()

        r = client.put(f"/api/v1/resources/vlans/{vlan['id']}", json={"domain_id": domain["id"]})

        assert r.status_code == 200, r.text
        assert self._assigned(client, member1) == [vlan["id"]]
        assert self._assigned(client, member2) == [vlan["id"]]

    def test_member_that_already_has_the_vlan_is_not_duplicated(self, client):
        dt = _create_device_type(client, "Коммутатор с уже назначенным VLAN")
        member, other = self._device(client, dt, "DOM-DUP-M1"), self._device(client, dt, "DOM-DUP-M2")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен без дублей у участников"}).json()
        self._join(client, domain, member)
        self._join(client, domain, other)
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 205, "name": "Уже у участника"}).json()
        client.post("/api/v1/resources/device-vlans", json={"physical_device_id": member["id"], "vlan_id": vlan["id"]})

        r = client.put(f"/api/v1/resources/vlans/{vlan['id']}", json={"domain_id": domain["id"]})

        assert r.status_code == 200, r.text  # не 409 на uq_physical_device_vlan
        assert self._assigned(client, member) == [vlan["id"]]
        assert self._assigned(client, other) == [vlan["id"]]

    def test_assignment_cost_does_not_grow_with_number_of_domain_devices(self, client, sql_log):
        dt = _create_device_type(client, "Коммутатор для подсчёта запросов домена")
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен для подсчёта запросов"}).json()
        for i in range(6):
            self._join(client, domain, self._device(client, dt, f"DOM-N1-{i}"))
        sql_log.clear()

        client.post("/api/v1/resources/vlans", json={"vlan_id": 206, "name": "Подсчёт", "domain_id": domain["id"]})

        selects = [s for s in sql_log if s.lstrip().upper().startswith("SELECT") and "physical_device_vlans" in s]
        assert len(selects) <= 2, selects  # один запрос на уже назначенное, не по запросу на устройство


class TestDeviceStacks:
    """Пункт 5 правки "создание физического устройства": стек физических устройств, соединённых
    на основании указанных портов (см. DeviceStack/DeviceStackMember в models.py — межстековые
    соединения переиспользуют обычный Connection, отдельной сущности под кабель между членами
    стека нет)."""

    def test_detail_returns_members_ordered_by_position_with_stack_membership_ids(self, client):
        dt = _create_device_type(client, "Коммутатор для стека")
        dev1 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-01"}).json()
        dev2 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-02"}).json()
        stack = client.post("/api/v1/resources/device-stacks", json={"name": "Стек ядра", "description": "2 коммутатора"}).json()

        # Добавляем в обратном порядке позиций — ответ детали должен быть отсортирован по
        # position, а не по порядку добавления/id.
        client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": dev2["id"], "position": 2})
        client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": dev1["id"], "position": 1})

        r = client.get(f"/api/v1/device-stacks/{stack['id']}/detail")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stack"]["name"] == "Стек ядра"
        assert [m["id"] for m in body["members"]] == [dev1["id"], dev2["id"]]
        assert [m["stack_position"] for m in body["members"]] == [1, 2]
        assert all(m["stack_member_id"] for m in body["members"])
        assert body["connections"] == []

    def test_detail_404_for_unknown_stack(self, client):
        r = client.get("/api/v1/device-stacks/нет-такого/detail")
        assert r.status_code == 404

    def test_adding_device_already_in_another_stack_rejected_with_stack_name(self, client):
        dt = _create_device_type(client, "Коммутатор занят другим стеком")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-03"}).json()
        stack_a = client.post("/api/v1/resources/device-stacks", json={"name": "Стек А"}).json()
        stack_b = client.post("/api/v1/resources/device-stacks", json={"name": "Стек Б"}).json()
        client.post(f"/api/v1/device-stacks/{stack_a['id']}/members", json={"physical_device_id": dev["id"]})

        r = client.post(f"/api/v1/device-stacks/{stack_b['id']}/members", json={"physical_device_id": dev["id"]})
        assert r.status_code == 409
        assert "Стек А" in r.json()["detail"]

    def test_adding_same_device_to_same_stack_twice_is_idempotent(self, client):
        dt = _create_device_type(client, "Коммутатор повторное добавление")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-04"}).json()
        stack = client.post("/api/v1/resources/device-stacks", json={"name": "Стек идемпотентный"}).json()

        first = client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": dev["id"]})
        second = client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": dev["id"]})
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["id"] == second.json()["id"]

        members = client.get(f"/api/v1/resources/device-stack-members?stack_id={stack['id']}").json()["items"]
        assert len(members) == 1

    def test_detail_includes_connections_between_members_only(self, client):
        """Подключение между двумя УЧАСТНИКАМИ стека — попадает в детали. Подключение от участника
        к устройству СНАРУЖИ стека — нет, даже если оно есть в БД (это обычный аплинк, не
        межстековый кабель)."""
        dt = _create_device_type(client, "Коммутатор с портами для стека")
        stack_dev1 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-05"}).json()
        stack_dev2 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-06"}).json()
        outside_dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-07-outside"}).json()

        def _iface(device_id, name):
            r = client.put(f"/api/v1/devices/{device_id}/interfaces", json={"interfaces": [{"name": name}]})
            return r.json()["items"][0]["id"]

        iface1 = _iface(stack_dev1["id"], "stack-link")
        iface2 = _iface(stack_dev2["id"], "stack-link")
        iface_outside = _iface(outside_dev["id"], "uplink")
        ct = client.post("/api/v1/resources/connection-types", json={"name": "Стековый кабель (тест)"}).json()

        stack_conn = client.post(
            "/api/v1/resources/connections",
            json={"source_interface_id": iface1, "destination_interface_id": iface2, "connection_type_id": ct["id"]},
        ).json()
        client.post(
            "/api/v1/resources/connections",
            json={"source_interface_id": iface2, "destination_interface_id": iface_outside, "connection_type_id": ct["id"]},
        )

        stack = client.post("/api/v1/resources/device-stacks", json={"name": "Стек с топологией"}).json()
        client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": stack_dev1["id"], "position": 1})
        client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": stack_dev2["id"], "position": 2})

        r = client.get(f"/api/v1/device-stacks/{stack['id']}/detail")
        conns = r.json()["connections"]
        assert [c["id"] for c in conns] == [stack_conn["id"]]
        assert conns[0]["source_device_name"] == "STACK-05"
        assert conns[0]["destination_device_name"] == "STACK-06"

    def test_deleting_stack_with_members_is_blocked(self, client):
        dt = _create_device_type(client, "Коммутатор для удаления стека")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "STACK-08"}).json()
        stack = client.post("/api/v1/resources/device-stacks", json={"name": "Стек на удаление"}).json()
        client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": dev["id"]})

        r = client.delete(f"/api/v1/resources/device-stacks/{stack['id']}")
        assert r.status_code == 409


class TestGlobalSearchTextIndex:
    """globalSearch() во фронтенде опирается на то, что q= находит IP-адрес в этих 3 таблицах
    (ip-addresses/device-vlans/open-ports) — до этого сквозной поиск их не покрывал вовсе,
    IP из этих таблиц приходилось искать вручную по разделам. is-sources была в этом списке до
    объединения IP интерфейса/ВМ/источника ИС в единую ip-addresses (миграция d8e35a1c7f60,
    owner_type/owner_id) — теперь IP-адрес источника ИС лежит там же, где и IP интерфейса/ВМ, см.
    test_ip_address_searchable_by_address ниже."""

    def test_ip_address_searchable_by_address(self, client):
        """Один тест на все три owner_type сразу — IPAddress теперь единая таблица независимо от
        владельца (интерфейс/ВМ/источник ИС), поэтому нет смысла дублировать тест на каждый."""
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС-источник для поиска"}).json()
        source = client.post(
            "/api/v1/resources/is-sources",
            json={"information_system_id": is_["id"], "source_type": "manual"},
        ).json()
        r = client.post(
            "/api/v1/resources/ip-addresses",
            json={"owner_type": "information_system_source", "owner_id": source["id"], "ip_address": "10.20.30.41"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/ip-addresses?q=10.20.30.41")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.41" for x in r.json()["items"])

    def test_device_vlan_ip_searchable_by_address(self, client):
        dt = _create_device_type(client, "Тип для поиска VLAN-IP")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRCH-1"}).json()
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 77, "name": "Поиск"}).json()
        r = client.post(
            "/api/v1/resources/device-vlans",
            json={"physical_device_id": dev["id"], "vlan_id": vlan["id"], "ip_address": "10.20.30.42"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/device-vlans?q=10.20.30.42")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.42" for x in r.json()["items"])

    def test_open_port_ip_searchable_by_address(self, client):
        dt = _create_device_type(client, "Тип для поиска порта")
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRCH-2"}).json()
        https_entry = _create_protocol_catalog_entry(client, 443, "HTTPS")
        r = client.post(
            "/api/v1/resources/open-ports",
            json={"owner_type": "physical_device", "owner_id": dev["id"], "protocol_catalog_id": https_entry["id"], "ip_address": "10.20.30.43"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/open-ports?q=10.20.30.43")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.43" for x in r.json()["items"])


class TestAuditLog:
    def test_audit_log_lists_most_recent_action_first(self, client):
        """GET /resources/audit-log?limit=N must return the N most recent entries (newest
        first), not the first N by insertion order — see services/crud.list_resource."""
        ids = []
        for name in ("Аудит-А", "Аудит-Б", "Аудит-В"):
            r = client.post("/api/v1/resources/manufacturers", json={"name": name})
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])

        r = client.get("/api/v1/resources/audit-log?limit=300")
        assert r.status_code == 200
        rows = r.json()["items"]
        positions = {x["entity_id"]: i for i, x in enumerate(rows) if x["entity_id"] in ids}
        assert len(positions) == 3
        # Most recently created manufacturer (last id) must appear before the earliest one.
        assert positions[ids[-1]] < positions[ids[0]]

    def test_audit_log_filters_by_entity_type_and_date_range(self, client):
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Фильтр-тест"})
        assert r.status_code == 201, r.text

        # entity_type — уже работающий generic equality-фильтр (не новый код), но здесь
        # это регрессия для комбинации с date_from/date_to.
        r = client.get("/api/v1/resources/audit-log?entity_type=manufacturers&limit=300")
        assert r.status_code == 200
        assert all(x["entity_type"] == "manufacturers" for x in r.json()["items"])

        far_future = "2999-01-01"
        r = client.get(f"/api/v1/resources/audit-log?date_from={far_future}")
        assert r.status_code == 200
        assert r.json()["items"] == []

        far_past = "1970-01-01"
        r = client.get(f"/api/v1/resources/audit-log?date_from={far_past}&date_to={far_future}")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1

        # date_to без времени должен включать весь день (до 23:59:59), а не исключать его целиком.
        today = client.get("/api/v1/resources/audit-log?limit=1").json()["items"][0]["created_at"][:10]
        r = client.get(f"/api/v1/resources/audit-log?date_from={today}&date_to={today}")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1

    def test_audit_log_rejects_invalid_date(self, client):
        r = client.get("/api/v1/resources/audit-log?date_from=не-дата")
        assert r.status_code == 422

    def test_audit_log_is_read_only_via_generic_crud(self, client):
        """Регрессия (код-ревью, п.1, High): generic-эндпоинты POST/PUT/DELETE
        /api/v1/resources/{resource} не проверяли READONLY_RESOURCES и одинаково работали с
        любым ключом из MODEL_MAP, включая audit-log — то есть любой клиент мог подделать или
        стереть записи журнала аудита напрямую через API, в обход audit(), которая уже
        запрещала это из кода приложения. Проверяем все три write-операции и то, что
        существующая запись аудита (созданная штатным путём) переживает попытку удаления."""
        # Штатное действие создаёт настоящую запись в audit-log, на которую опираемся ниже.
        created = client.post("/api/v1/resources/manufacturers", json={"name": "Аудит-RO-тест"})
        assert created.status_code == 201, created.text
        existing_entry = client.get("/api/v1/resources/audit-log", params={"entity_id": created.json()["id"], "limit": 10}).json()["items"][0]

        forged = client.post(
            "/api/v1/resources/audit-log",
            json={"entity_type": "devices", "action": "DELETE", "details": "подделка"},
        )
        assert forged.status_code == 403

        updated = client.put(f"/api/v1/resources/audit-log/{existing_entry['id']}", json={"details": "подмена"})
        assert updated.status_code == 403

        deleted = client.delete(f"/api/v1/resources/audit-log/{existing_entry['id']}")
        assert deleted.status_code == 403

        # Запись действительно не пострадала.
        still_there = client.get(f"/api/v1/resources/audit-log/{existing_entry['id']}")
        assert still_there.status_code == 200
        assert still_there.json()["details"] == existing_entry["details"]

    def test_update_writes_field_level_diff_not_generic_message(self, client):
        """Регрессия: update_resource раньше писал в audit-log одну и ту же строку
        'Изменение записи' на ЛЮБОЕ изменение любой из ~40 сущностей реестра — колонка
        "Детали" в журнале аудита дублировала колонку "Действие" (там уже бейдж "Изменено"),
        не показывая, что именно изменилось. Теперь details содержит конкретное
        'поле: старое → новое' (services/crud/audit_log.py:_describe_update)."""
        created = client.post("/api/v1/resources/manufacturers", json={"name": "До правки"})
        assert created.status_code == 201, created.text
        item_id = created.json()["id"]

        updated = client.put(f"/api/v1/resources/manufacturers/{item_id}", json={"name": "После правки"})
        assert updated.status_code == 200, updated.text

        entry = client.get(
            "/api/v1/resources/audit-log",
            params={"entity_id": item_id, "action": "UPDATE", "limit": 10},
        ).json()["items"][0]
        assert entry["details"] != "Изменение записи"
        assert entry["details"] == "name: До правки → После правки"

    def test_update_with_several_changed_fields_lists_all_of_them(self, client):
        """Несколько изменённых полей за один PUT должны попасть в details все разом, через
        '; ', а не только последнее/первое. Заодно проверяет форматирование None → значение
        (поле address не заполнено при создании) как '— → ...', а не 'None → ...'."""
        building = client.post("/api/v1/resources/buildings", json={"name": "Здание А"}).json()

        updated = client.put(
            f"/api/v1/resources/buildings/{building['id']}",
            json={"name": "Здание Б", "address": "ул. Тестовая, 1"},
        )
        assert updated.status_code == 200, updated.text

        entry = client.get(
            "/api/v1/resources/audit-log",
            params={"entity_id": building["id"], "action": "UPDATE", "limit": 10},
        ).json()["items"][0]
        assert "name: Здание А → Здание Б" in entry["details"]
        assert "address: — → ул. Тестовая, 1" in entry["details"]
        assert "; " in entry["details"]  # оба изменения в одной строке, не потеряно ни одно

    def test_update_without_actual_value_change_does_not_fabricate_a_diff(self, client):
        """PUT с тем же значением, что уже стоит в записи (типичный сценарий — форма
        отправляет все поля целиком, даже нетронутые) не должен придумывать несуществующий
        diff вида 'name: Х → Х'."""
        created = client.post("/api/v1/resources/manufacturers", json={"name": "Без изменений"}).json()

        updated = client.put(f"/api/v1/resources/manufacturers/{created['id']}", json={"name": "Без изменений"})
        assert updated.status_code == 200, updated.text

        entry = client.get(
            "/api/v1/resources/audit-log",
            params={"entity_id": created["id"], "action": "UPDATE", "limit": 10},
        ).json()["items"][0]
        assert "→" not in entry["details"]
        assert entry["details"] == "Изменение записи (переданные значения совпадают с текущими)"


class TestReportTemplateVersions:
    VALID_CONFIG = {
        "sheets": [
            {
                "title": "Лист1",
                "columns": [{"width": 25}],
                "rows": [
                    {
                        "height": 18,
                        "repeat": True,
                        "data_source": {"root_entity": "information-systems"},
                        "cells": [{"col": 0, "kind": "field", "path": "name"}],
                    }
                ],
            }
        ]
    }

    def _create(self, client, name="Шаблон версий"):
        r = client.post("/api/v1/report-templates", json={"name": name, "config": self.VALID_CONFIG})
        assert r.status_code == 201, r.text
        return r.json()

    def test_new_template_has_no_version_history(self, client):
        t = self._create(client)
        r = client.get(f"/api/v1/report-templates/{t['id']}/versions")
        assert r.status_code == 200
        assert r.json() == []

    def test_update_snapshots_previous_state_before_overwriting(self, client):
        t = self._create(client, "Шаблон А")
        r = client.put(
            f"/api/v1/report-templates/{t['id']}",
            json={"name": "Шаблон А (переименован)", "config": self.VALID_CONFIG},
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Шаблон А (переименован)"

        r = client.get(f"/api/v1/report-templates/{t['id']}/versions")
        assert r.status_code == 200
        versions = r.json()
        assert len(versions) == 1
        assert versions[0]["version_number"] == 1
        assert versions[0]["name"] == "Шаблон А"  # снимок ДО переименования, не после

    def test_multiple_updates_number_versions_sequentially(self, client):
        t = self._create(client, "Версия 0")
        for name in ("Версия 1", "Версия 2", "Версия 3"):
            r = client.put(f"/api/v1/report-templates/{t['id']}", json={"name": name, "config": self.VALID_CONFIG})
            assert r.status_code == 200, r.text
        versions = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()
        assert [v["version_number"] for v in versions] == [3, 2, 1]  # новые сверху
        assert [v["name"] for v in versions] == ["Версия 2", "Версия 1", "Версия 0"]

    def test_restore_reverts_config_and_is_itself_reversible(self, client):
        t = self._create(client, "Оригинал")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "Изменено", "config": self.VALID_CONFIG})
        versions = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()
        original_version_id = versions[0]["id"]  # снимок "Оригинал"

        r = client.post(f"/api/v1/report-templates/{t['id']}/versions/{original_version_id}/restore")
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Оригинал"

        # Восстановление тоже создаёт снимок — состояние "Изменено" не потеряно безвозвратно.
        versions_after = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()
        assert len(versions_after) == 2
        assert versions_after[0]["name"] == "Изменено"

    def test_restore_rejects_name_collision_with_another_template(self, client):
        t = self._create(client, "Шаблон Б исходное имя")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "Шаблон Б", "config": self.VALID_CONFIG})
        version_id = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()[0]["id"]
        self._create(client, "Шаблон Б исходное имя")  # занимает старое имя другим шаблоном

        r = client.post(f"/api/v1/report-templates/{t['id']}/versions/{version_id}/restore")
        assert r.status_code == 409

    def test_delete_template_cascades_version_history(self, client):
        t = self._create(client, "На удаление")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "На удаление v2", "config": self.VALID_CONFIG})
        assert len(client.get(f"/api/v1/report-templates/{t['id']}/versions").json()) == 1

        r = client.delete(f"/api/v1/report-templates/{t['id']}")
        assert r.status_code == 200, r.text
        assert client.get(f"/api/v1/report-templates/{t['id']}/versions").status_code == 404

    def test_template_lifecycle_writes_audit_entries(self, client):
        """Создание/изменение/восстановление/удаление шаблона должны попадать в журнал аудита —
        как и любая другая мутация в этом комплаенс-приложении (см. crud.audit())."""
        t = self._create(client, "Шаблон для аудита")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "Шаблон для аудита v2", "config": self.VALID_CONFIG})
        version_id = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()[0]["id"]
        client.post(f"/api/v1/report-templates/{t['id']}/versions/{version_id}/restore")
        client.delete(f"/api/v1/report-templates/{t['id']}")

        r = client.get("/api/v1/resources/audit-log?entity_type=report-templates&limit=300")
        assert r.status_code == 200
        actions = [x["action"] for x in r.json()["items"] if x["entity_id"] == t["id"]]
        assert actions.count("CREATE") == 1
        assert actions.count("UPDATE") == 2  # изменение + восстановление версии
        assert actions.count("DELETE") == 1


class TestReports:
    def test_seed_endpoint_populates_catalogs(self, client):
        r = client.post("/api/v1/seed")
        assert r.status_code == 200
        assert r.json()["status"] == "seeded"

    def test_generate_and_download_inventory_report(self, client):
        r = client.post("/api/v1/reports/inventory")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_name"].endswith(".xlsx")

        r2 = client.get(body["download_url"])
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_download_report_rejects_path_traversal(self, client):
        r = client.get("/api/v1/reports/download/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (404, 400)

    def test_generate_and_download_audit_log_report(self, client):
        client.post("/api/v1/resources/manufacturers", json={"name": "Для экспорта аудита"})

        r = client.post("/api/v1/reports/audit-log")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_name"].endswith(".xlsx")

        r2 = client.get(body["download_url"])
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    def test_audit_log_report_respects_filters(self, client):
        client.post("/api/v1/resources/manufacturers", json={"name": "Останется за пределами фильтра"})

        r = client.post("/api/v1/reports/audit-log", params={"date_from": "2999-01-01"})
        assert r.status_code == 200, r.text

        import openpyxl

        path = REPORT_DIR / "audit" / r.json()["file_name"]  # отчёты аудита лежат в подкаталоге (A-05)
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        # Только заголовок — ни одна запись не попадает в диапазон дат из будущего.
        assert ws.max_row == 1

    def test_inventory_report_filters_by_structural_unit(self, client):
        """POST /reports/inventory принимает structural_unit_ids в теле запроса и сужает отчёт
        до оборудования, размещённого в выбранной структурной единице — см. reporting.build_report."""
        unit = client.post("/api/v1/resources/structural-units", json={"name": "Филиал А"})
        assert unit.status_code == 201, unit.text
        unit = unit.json()
        other_unit = client.post("/api/v1/resources/structural-units", json={"name": "Филиал Б"}).json()
        building_in = client.post("/api/v1/resources/buildings", json={"name": "Здание А", "structural_unit_id": unit["id"]})
        assert building_in.status_code == 201, building_in.text
        building_in = building_in.json()
        building_out = client.post("/api/v1/resources/buildings", json={"name": "Здание Б", "structural_unit_id": other_unit["id"]}).json()
        dt = _create_device_type(client, "Тип для фильтра по структурной единице")
        client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SU-IN", "building_id": building_in["id"]})
        client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SU-OUT", "building_id": building_out["id"]})

        r = client.post("/api/v1/reports/inventory", json={"structural_unit_ids": [unit["id"]]})
        assert r.status_code == 200, r.text

        import openpyxl

        path = REPORT_DIR / r.json()["file_name"]
        wb = openpyxl.load_workbook(path)
        rows = list(wb["Инвентаризац. физ. устройств ИС"].iter_rows(min_row=2, values_only=True))
        serials = [row[3] for row in rows]
        assert serials == ["SU-IN"]

    def test_template_report_filters_by_structural_unit(self, client):
        """То же для конструктора отчётов (виртуальная сущность registry-device-rows) — фильтр
        должен работать одинаково на обоих движках, см. test_report_registry_rows.py:
        ExactParityTestCase.test_exact_parity_with_structural_unit_filter."""
        unit = client.post("/api/v1/resources/structural-units", json={"name": "Филиал А"}).json()
        building_in = client.post("/api/v1/resources/buildings", json={"name": "Здание А", "structural_unit_id": unit["id"]}).json()
        building_out = client.post("/api/v1/resources/buildings", json={"name": "Здание Б"}).json()
        dt = _create_device_type(client, "Тип для фильтра шаблона по единице")
        client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SU-IN", "building_id": building_in["id"]})
        client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SU-OUT", "building_id": building_out["id"]})

        config = {
            "sheets": [
                {
                    "title": "Устройства",
                    "columns": [{"width": 20}],
                    "rows": [{"height": 18, "repeat": True, "data_source": {"root_entity": "registry-device-rows"}, "cells": [{"col": 0, "kind": "field", "path": "serial_number"}]}],
                }
            ]
        }
        t = client.post("/api/v1/report-templates", json={"name": "Тест устройств", "format": "xlsx", "config": config}).json()

        r = client.post(f"/api/v1/report-templates/{t['id']}/generate", json={"structural_unit_ids": [unit["id"]]})
        assert r.status_code == 200, r.text

        import openpyxl

        path = REPORT_DIR / r.json()["file_name"]
        wb = openpyxl.load_workbook(path)
        values = [row[0] for row in wb["Устройства"].iter_rows(min_row=1, values_only=True) if row[0]]
        assert values == ["SU-IN"]
