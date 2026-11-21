"""Код-ревью С-4: защита от потерянных обновлений при одновременной правке записи.

update_resource читал запись, применял изменения и коммитил без всякой проверки версии: два пользователя правят одну запись —
выигрывает последний, молча. Теперь клиент может прислать expected_updated_at (значение updated_at, полученное при чтении); если
запись с тех пор изменили, ответ 409 STALE_RECORD. Поле необязательное: старый клиент без него работает как прежде.

Запуск: pytest backend/tests/test_review_p1_update_stale_record.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.constants import ErrorCode

API = "/api/v1/resources"


def _create(client, resource: str, body: dict) -> dict:
    response = client.post(f"{API}/{resource}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _put(client, resource: str, item_id: str, body: dict):
    return client.put(f"{API}/{resource}/{item_id}", json=body)


def _stored(client, resource: str, item_id: str) -> dict:
    response = client.get(f"{API}/{resource}/{item_id}")
    assert response.status_code == 200
    return response.json()


def _audit_updates(client, entity_type: str) -> list[dict]:
    rows = client.get(f"{API}/audit-log", params={"entity_type": entity_type, "limit": 300}).json()["items"]
    return [row for row in rows if row["action"] == "UPDATE"]


@pytest.fixture()
def manufacturer(client) -> dict:
    return _create(client, "manufacturers", {"name": "Версия-1"})


# --- обратная совместимость ---------------------------------------------------------------------------------------------------


def test_update_without_the_field_works_as_before(client, manufacturer):
    response = _put(client, "manufacturers", manufacturer["id"], {"name": "Версия-2"})
    assert response.status_code == 200 and response.json()["name"] == "Версия-2"


def test_a_null_value_means_no_check(client, manufacturer):
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "Версия-2", "expected_updated_at": None}).status_code == 200


# --- основной сценарий ---------------------------------------------------------------------------------------------------------


def test_matching_version_is_accepted_and_the_version_moves_on(client, manufacturer):
    first = _put(client, "manufacturers", manufacturer["id"], {"name": "Версия-2", "expected_updated_at": manufacturer["updated_at"]})
    assert first.status_code == 200, first.text
    new_version = first.json()["updated_at"]
    assert new_version != manufacturer["updated_at"], "после правки отметка времени сдвигается"

    # ответ на правку годится как основа следующей: цепочка «прочитал → правлю → правлю ещё раз» без перечитывания
    second = _put(client, "manufacturers", manufacturer["id"], {"name": "Версия-3", "expected_updated_at": new_version})
    assert second.status_code == 200 and second.json()["name"] == "Версия-3"


def test_two_editors_the_second_one_gets_409_and_nothing_is_overwritten(client, manufacturer):
    """Оба открыли форму с одной и той же версией; первый сохранил, второй — нет."""
    snapshot = manufacturer["updated_at"]
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "Правка Анны", "expected_updated_at": snapshot}).status_code == 200
    updates_before = len(_audit_updates(client, "manufacturers"))

    late = _put(client, "manufacturers", manufacturer["id"], {"name": "Правка Бориса", "expected_updated_at": snapshot})

    assert late.status_code == 409
    detail = late.json()["detail"]
    assert detail["code"] == ErrorCode.STALE_RECORD == "STALE_RECORD"
    assert "изменена другим пользователем" in detail["message"]
    assert _stored(client, "manufacturers", manufacturer["id"])["name"] == "Правка Анны", "чужая правка не затёрта"
    assert len(_audit_updates(client, "manufacturers")) == updates_before, "отклонённая правка в журнал не попадает"


def test_a_conflict_is_resolved_by_rereading_the_record(client, manufacturer):
    snapshot = manufacturer["updated_at"]
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "Чужая", "expected_updated_at": snapshot}).status_code == 200
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "Моя", "expected_updated_at": snapshot}).status_code == 409

    fresh = _stored(client, "manufacturers", manufacturer["id"])  # «обновите форму и повторите правку»
    retry = _put(client, "manufacturers", manufacturer["id"], {"name": "Моя", "expected_updated_at": fresh["updated_at"]})
    assert retry.status_code == 200 and retry.json()["name"] == "Моя"


def test_the_stale_check_runs_before_any_other_validation(client, manufacturer):
    """Устаревшая форма получает 409, а не ошибку о полях, которые уже могли поменяться."""
    snapshot = manufacturer["updated_at"]
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "Чужая", "expected_updated_at": snapshot}).status_code == 200
    response = _put(client, "manufacturers", manufacturer["id"], {"name": "", "expected_updated_at": snapshot})
    assert response.status_code == 409


# --- формат значения -----------------------------------------------------------------------------------------------------------


def _truncate_to_millis(stamp: datetime) -> str:
    return stamp.replace(microsecond=stamp.microsecond // 1000 * 1000).isoformat()


def _in_utc_plus_3(stamp: datetime) -> str:
    return stamp.astimezone(timezone(timedelta(hours=3))).isoformat()


@pytest.mark.parametrize("render", [_truncate_to_millis, _in_utc_plus_3], ids=["millis", "utc+3"])
def test_millisecond_precision_and_other_utc_offsets_are_equivalent(client, manufacturer, render):
    """JavaScript (Date.toISOString) отбрасывает микросекунды; клиент может прислать и то же время со своим смещением."""
    value = render(datetime.fromisoformat(manufacturer["updated_at"]))
    response = _put(client, "manufacturers", manufacturer["id"], {"description": "правка", "expected_updated_at": value})
    assert response.status_code == 200, f"{value} → {response.status_code}"


def test_a_different_instant_is_a_conflict_even_when_it_is_close(client, manufacturer):
    stamp = datetime.fromisoformat(manufacturer["updated_at"])
    off_by_a_second = (stamp - timedelta(seconds=1)).isoformat()
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "x", "expected_updated_at": off_by_a_second}).status_code == 409


@pytest.mark.parametrize("value", ["вчера", "2026-13-45T00:00:00", "0001-01-01T00:00:00+14:00", ""])
def test_an_unparseable_value_is_422_not_a_silent_skip(client, manufacturer, value):
    response = _put(client, "manufacturers", manufacturer["id"], {"name": "x", "expected_updated_at": value})
    assert response.status_code == 422, f"{value!r} → {response.status_code}"
    assert _stored(client, "manufacturers", manufacturer["id"])["name"] == "Версия-1"


@pytest.mark.parametrize("value", [12345, True, ["2026-01-01"], {"a": 1}])
def test_a_value_of_the_wrong_type_is_422(client, manufacturer, value):
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "x", "expected_updated_at": value}).status_code == 422


# --- ресурсы со схемой Pydantic -------------------------------------------------------------------------------------------------


def test_resources_with_a_schema_accept_the_field(client):
    """devices, information-systems и vlans проверяют неизвестные ключи (422): служебный ключ среди известных."""
    category = client.get(f"{API}/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = _create(client, "device-types", {"name": "Тип для версии", "category_id": category})
    device = _create(client, "devices", {"device_type_id": device_type["id"], "serial_number": "SN-STALE-1"})

    ok = _put(client, "devices", device["id"], {"description": "первая", "expected_updated_at": device["updated_at"]})
    assert ok.status_code == 200, ok.text
    stale = _put(client, "devices", device["id"], {"description": "вторая", "expected_updated_at": device["updated_at"]})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == ErrorCode.STALE_RECORD


def test_a_misspelled_field_is_still_rejected_on_schema_resources(client):
    """Служебный ключ не ослабил проверку опечаток: «expected_update_at» по-прежнему неизвестное поле."""
    category = client.get(f"{API}/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = _create(client, "device-types", {"name": "Тип для опечатки", "category_id": category})
    device = _create(client, "devices", {"device_type_id": device_type["id"], "serial_number": "SN-STALE-2"})
    response = _put(client, "devices", device["id"], {"description": "x", "expected_update_at": device["updated_at"]})
    assert response.status_code == 422 and "expected_updated_at" in response.json()["detail"]


# --- блокировка строки ----------------------------------------------------------------------------------------------------------


def test_the_row_is_read_with_for_update(client, manufacturer, monkeypatch):
    """На PostgreSQL проверка версии и запись неделимы только если строка заблокирована при чтении; на SQLite параметр безвреден."""
    from sqlalchemy.orm import Session

    original = Session.get
    seen: list[object] = []

    def spy(self, entity, ident, **kwargs):
        seen.append(kwargs.get("with_for_update"))
        return original(self, entity, ident, **kwargs)

    monkeypatch.setattr(Session, "get", spy)
    assert _put(client, "manufacturers", manufacturer["id"], {"name": "Версия-2"}).status_code == 200
    assert True in seen, "update_resource обязан читать запись с with_for_update=True"


def test_the_error_code_is_a_stable_part_of_the_api_contract():
    # ключ строки, который фронтенд (Исполнитель 2) добавляет в свой ErrorCode после слияния этой ветки
    assert ErrorCode.STALE_RECORD == "STALE_RECORD"
