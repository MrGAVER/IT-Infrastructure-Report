"""
Интеграционные тесты HTTP-слоя (см. conftest.py) на три доработки формы "Информационная
система" / "Физическое устройство":

1) SupportMethod.support_organization_id — способ оказания техподдержки можно привязать к
   организации техподдержки; сохранение ИС с несовместимой парой организация/способ отклоняется
   (validate_support_method_organization в services/validation.py), способ без организации
   считается универсальным и подходит любой организации.
2) CryptoProtectionMeans.physical_device_id — средство криптографической защиты можно (но не
   обязательно) привязать к конкретному физическому устройству реестра.
3) PhysicalDevice.oac_certificate_number / oac_certificate_registry_date — необязательный блок
   "Сертификат ОАЦ" на карточке устройства, с валидацией формата даты через Pydantic-схему.

Запуск:  pip install -r backend/requirements-dev.txt && pytest backend/tests/test_support_crypto_device_links.py -v
"""
from __future__ import annotations


def _create_device_type(client, name: str, **extra):
    """Создаёт тип устройства с первой попавшейся существующей категорией — см. одноимённый
    хелпер в test_api.py, здесь продублирован намеренно (тот же принцип, что и локальные
    хелперы в других файлах tests/ — не создавать общий conftest-хелпер ради одного файла)."""
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    return client.post("/api/v1/resources/device-types", json={"name": name, "category_id": category_id, **extra}).json()


def _create_device(client, serial_number: str, **extra):
    device_type = _create_device_type(client, f"Тип для {serial_number}")
    payload = {"device_type_id": device_type["id"], "serial_number": serial_number, **extra}
    r = client.post("/api/v1/resources/devices", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


class TestSupportMethodOrganizationLink:
    def test_support_method_can_be_linked_to_organization_and_persists(self, client):
        org = client.post("/api/v1/resources/support-organizations", json={"name": "ООО Техподдержка"}).json()

        method = client.post(
            "/api/v1/resources/support-methods",
            json={"name": "Выездное обслуживание", "support_organization_id": org["id"]},
        )
        assert method.status_code == 201, method.text
        assert method.json()["support_organization_id"] == org["id"]

        # Запись без организации по-прежнему сохраняется (обратная совместимость с уже
        # заведёнными "универсальными" способами) — organization_id остаётся null.
        universal = client.post("/api/v1/resources/support-methods", json={"name": "Удалённо"}).json()
        assert universal["support_organization_id"] is None

    def test_information_system_rejects_support_method_from_other_organization(self, client):
        org_a = client.post("/api/v1/resources/support-organizations", json={"name": "Организация А"}).json()
        org_b = client.post("/api/v1/resources/support-organizations", json={"name": "Организация Б"}).json()
        method_a = client.post(
            "/api/v1/resources/support-methods",
            json={"name": "Способ организации А", "support_organization_id": org_a["id"]},
        ).json()

        r = client.post(
            "/api/v1/resources/information-systems",
            json={"name": "ИС с несовместимой парой", "support_organization_id": org_b["id"], "support_method_id": method_a["id"]},
        )
        assert r.status_code == 422
        assert "техническ" in r.json()["detail"].lower()

        # Та же пара, но с ПРАВИЛЬНОЙ (совпадающей) организацией — должна пройти.
        ok = client.post(
            "/api/v1/resources/information-systems",
            json={"name": "ИС с совместимой парой", "support_organization_id": org_a["id"], "support_method_id": method_a["id"]},
        )
        assert ok.status_code == 201, ok.text

    def test_information_system_accepts_universal_support_method_with_any_organization(self, client):
        org = client.post("/api/v1/resources/support-organizations", json={"name": "Любая организация"}).json()
        universal_method = client.post("/api/v1/resources/support-methods", json={"name": "Универсальный способ"}).json()

        r = client.post(
            "/api/v1/resources/information-systems",
            json={"name": "ИС с универсальным способом", "support_organization_id": org["id"], "support_method_id": universal_method["id"]},
        )
        assert r.status_code == 201, r.text


class TestCryptoProtectionMeansDeviceLink:
    def test_physical_device_link_is_optional_and_round_trips(self, client):
        device = _create_device(client, "SKZI-DEV-1")

        linked = client.post(
            "/api/v1/resources/crypto-protection-means",
            json={"name": "VipNet Coordinator", "physical_device_id": device["id"]},
        )
        assert linked.status_code == 201, linked.text
        assert linked.json()["physical_device_id"] == device["id"]

        unlinked = client.post("/api/v1/resources/crypto-protection-means", json={"name": "КриптоПро CSP"})
        assert unlinked.status_code == 201, unlinked.text
        assert unlinked.json()["physical_device_id"] is None


class TestPhysicalDeviceOacCertificate:
    def test_oac_certificate_fields_are_optional_and_round_trip(self, client):
        with_cert = _create_device(
            client,
            "OAC-DEV-1",
            oac_certificate_number="RU.НН01.Н12345",
            oac_certificate_registry_date="2026-03-01",
        )
        assert with_cert["oac_certificate_number"] == "RU.НН01.Н12345"
        assert with_cert["oac_certificate_registry_date"] == "2026-03-01"

        without_cert = _create_device(client, "OAC-DEV-2")
        assert without_cert["oac_certificate_number"] is None
        assert without_cert["oac_certificate_registry_date"] is None

    def test_invalid_oac_certificate_date_is_rejected_with_422(self, client):
        device_type = _create_device_type(client, "Тип для невалидной даты")
        r = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": device_type["id"], "serial_number": "OAC-DEV-BAD", "oac_certificate_registry_date": "не дата"},
        )
        assert r.status_code == 422
