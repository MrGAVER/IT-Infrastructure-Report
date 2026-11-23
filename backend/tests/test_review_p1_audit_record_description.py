"""Код-ревью С-2: журнал аудита называет создаваемую и удаляемую запись, а не только «Создание записи» и UUID.

Раньше после цепочки «создать → переименовать → удалить» в журнале оставалось «Удаление записи» и идентификатор: ответить, какое
устройство удалили вчера, было нельзя. Теперь к CREATE и DELETE дописывается краткое описание (имя, серийный номер …), а для удаления
оно снимается до самого удаления. Заодно проверяется Н-8: отказ БД при удалении отвечает тем же ответом, что создание и изменение.

Запуск: pytest backend/tests/test_review_p1_audit_record_description.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.constants import ErrorCode
from app.services.crud import describe_record
from app.services import crud


API = "/api/v1/resources"


def _audit_rows(client, entity_type: str, action: str) -> list[dict]:
    response = client.get(f"{API}/audit-log", params={"entity_type": entity_type, "limit": 300})
    assert response.status_code == 200
    return [row for row in response.json()["items"] if row["action"] == action]


def _create(client, resource: str, body: dict) -> dict:
    response = client.post(f"{API}/{resource}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# --- журнал при создании и удалении ---------------------------------------------------------------------------------------------


def test_create_and_delete_name_the_record(client):
    manufacturer = _create(client, "manufacturers", {"name": "АудитТест-Вендор"})
    (created,) = _audit_rows(client, "manufacturers", "CREATE")
    assert created["entity_id"] == manufacturer["id"]
    assert "АудитТест-Вендор" in created["details"]

    assert client.delete(f"{API}/manufacturers/{manufacturer['id']}").status_code == 200
    (deleted,) = _audit_rows(client, "manufacturers", "DELETE")
    assert deleted["entity_id"] == manufacturer["id"]
    assert deleted["details"].startswith("Удаление записи:")
    assert "АудитТест-Вендор" in deleted["details"], "имя удалённой записи должно остаться в журнале"


def test_device_is_recognisable_by_serial_number_and_system_name(client):
    category = client.get(f"{API}/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = _create(client, "device-types", {"name": "Тип для аудита", "category_id": category})
    device = _create(client, "devices", {"device_type_id": device_type["id"], "serial_number": "SN-AUDIT-1", "system_name": "srv-audit"})
    assert client.delete(f"{API}/devices/{device['id']}").status_code == 200

    for action in ("CREATE", "DELETE"):
        (row,) = _audit_rows(client, "devices", action)
        assert "SN-AUDIT-1" in row["details"] and "srv-audit" in row["details"], f"{action}: {row['details']}"


def test_update_still_reports_the_diff(client):
    # изменение не трогаем: оно и раньше описывало «поле: было → стало»
    manufacturer = _create(client, "manufacturers", {"name": "Старое"})
    assert client.put(f"{API}/manufacturers/{manufacturer['id']}", json={"name": "Новое"}).status_code == 200
    (updated,) = _audit_rows(client, "manufacturers", "UPDATE")
    assert updated["details"] == "name: Старое → Новое"


# --- describe_record: правила описания ------------------------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _Probe(_Base):
    """Модель-пробник вне реестра: колонки с «секретными» именами и без «имени» — без базы данных."""

    __tablename__ = "probe"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="1")
    name: Mapped[str | None] = mapped_column(String(300))
    note: Mapped[str | None] = mapped_column(String(300))
    api_token: Mapped[str | None] = mapped_column(String(300))
    snmp_community: Mapped[str | None] = mapped_column(String(300))


class _NamelessProbe(_Base):
    __tablename__ = "nameless_probe"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default="1")
    left_port: Mapped[str | None] = mapped_column(String(50))
    right_port: Mapped[str | None] = mapped_column(String(50))
    cable: Mapped[str | None] = mapped_column(String(50))
    comment: Mapped[str | None] = mapped_column(String(50))


def test_secret_looking_columns_never_reach_the_journal():
    text = describe_record(_Probe(name="узел", note="заметка", api_token="s3cr3t-token", snmp_community="public-community"))
    assert "узел" in text
    assert "s3cr3t-token" not in text and "public-community" not in text
    assert "api_token" not in text and "snmp_community" not in text


def test_a_record_without_a_name_falls_back_to_its_first_filled_columns():
    text = describe_record(_NamelessProbe(left_port="Gi0/1", right_port="", cable="UTP", comment="x"))
    # пустая колонка пропускается, берутся первые три заполненные в порядке колонок модели
    assert text == "left_port: Gi0/1; cable: UTP; comment: x"


def test_newlines_collapse_and_length_is_capped():
    assert describe_record(_Probe(name="строка\n\nс переносами")) == "name: строка с переносами"
    capped = describe_record(_Probe(name="я" * 500, note="ы" * 500), max_len=40)
    assert len(capped) == 40 and capped.endswith("…")


def test_an_empty_record_and_a_bad_limit_are_handled():
    assert describe_record(_Probe()) == "без заполненных полей"
    with pytest.raises(ValueError):
        describe_record(_Probe(name="x"), max_len=1)


# --- Н-8: отказ БД при удалении — тот же ответ, что при создании и изменении --------------------------------------------------------


def test_database_refusal_on_delete_uses_the_common_409(client, monkeypatch):
    manufacturer = _create(client, "manufacturers", {"name": "Производитель со ссылкой"})
    category = client.get(f"{API}/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = _create(client, "device-types", {"name": "Тип для ссылки", "category_id": category})
    _create(client, "device-models", {"model": "Модель", "manufacturer_id": manufacturer["id"], "device_type_id": device_type["id"]})
    # защиту уровня приложения (понятное сообщение со списком ссылающихся записей) обходим: проверяется запасной путь — отказ самой БД
    monkeypatch.setattr("app.services.crud.deletion.assert_deletable", lambda *args, **kwargs: None)

    response = client.delete(f"{API}/manufacturers/{manufacturer['id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == ErrorCode.INTEGRITY_ERROR
    assert "SQL" not in response.text and "constraint" not in response.text.lower(), "текст драйвера БД клиенту не отдаётся"
    assert _audit_rows(client, "manufacturers", "DELETE") == [], "неудавшееся удаление в журнал не пишется"
    assert client.get(f"{API}/manufacturers/{manufacturer['id']}").status_code == 200


def test_describe_record_is_part_of_the_crud_facade():
    assert crud.describe_record is describe_record
