"""Серверная выборка журнала аудита (GET /api/v1/audit-log): порядок, пагинация, поиск, фильтры,
счётчики и список разделов.

Запуск: pytest backend/tests/test_audit_log_query.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models import AuditLog

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _entry(index: int, *, action: str = "UPDATE", entity_type: str = "devices", details: str | None = None, entity_id: str | None = None, minutes: int | None = None) -> AuditLog:
    return AuditLog(
        id=f"id-{index:05d}",
        entity_type=entity_type,
        entity_id=entity_id or f"entity-{index:05d}",
        action=action,
        details=details if details is not None else f"Запись {index}",
        created_at=BASE + timedelta(minutes=index if minutes is None else minutes),
    )


@pytest.fixture()
def seed(db_session):
    def _seed(*entries: AuditLog) -> None:
        db_session.add_all(entries)
        db_session.commit()

    return _seed


def _page(client, **params) -> dict:
    response = client.get("/api/v1/audit-log", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(page: dict) -> list[str]:
    return [item["id"] for item in page["items"]]


def test_items_are_newest_first_and_carry_the_audit_fields(client, seed):
    seed(_entry(1), _entry(3), _entry(2))

    page = _page(client)

    assert _ids(page) == ["id-00003", "id-00002", "id-00001"]
    assert set(page["items"][0]) >= {"id", "entity_type", "entity_id", "action", "details", "created_at"}
    assert (page["total"], page["offset"], page["limit"]) == (3, 0, 24)


def test_pagination_slices_cover_every_entry_exactly_once(client, seed):
    seed(*[_entry(i) for i in range(1, 31)])

    seen: list[str] = []
    for offset in range(0, 30, 12):
        page = _page(client, offset=offset, limit=12)
        assert page["total"] == 30
        seen += _ids(page)

    assert seen == [f"id-{i:05d}" for i in range(30, 0, -1)]


def test_entries_with_equal_timestamps_keep_a_stable_order_across_pages(client, seed):
    """Без второго ключа сортировки записи с одним временем могли бы дублироваться или пропадать на стыке страниц."""
    seed(*[_entry(i, minutes=0) for i in range(1, 26)])

    first, second, third = (_ids(_page(client, offset=o, limit=10)) for o in (0, 10, 20))

    assert len(set(first + second + third)) == 25
    assert first + second + third == sorted(first + second + third, reverse=True)


def test_page_query_orders_by_time_then_id(client, seed, sql_log):
    """Порядок страницы задан явно двумя ключами. Поведение при равных временах зависит от плана
    запроса и индексов СУБД, поэтому проверяем сам запрос, а не только результат на SQLite."""
    seed(_entry(1), _entry(2))
    sql_log.clear()

    _page(client)

    page_sql = next(s for s in sql_log if "FROM audit_log" in s and "LIMIT" in s)
    assert "ORDER BY audit_log.created_at DESC, audit_log.id DESC" in page_sql


def test_page_beyond_the_end_is_empty_but_reports_total(client, seed):
    seed(_entry(1), _entry(2))

    page = _page(client, offset=100)

    assert page["items"] == [] and page["total"] == 2


def test_search_is_case_insensitive_for_cyrillic_and_matches_details_and_entity_id(client, seed):
    seed(
        _entry(1, details="Изменено описание коммутатора"),
        _entry(2, details="Создана запись", entity_id="abc-DEF-123"),
        _entry(3, details="Другое"),
    )

    assert _ids(_page(client, q="КОММУТАТОРА")) == ["id-00001"]
    assert _ids(_page(client, q="коммутатор")) == ["id-00001"]
    assert _ids(_page(client, q="def-1")) == ["id-00002"]
    assert _page(client, q="нет такого")["items"] == []


def test_search_treats_percent_and_underscore_literally(client, seed):
    seed(_entry(1, details="скидка 50% на всё"), _entry(2, details="port_1"), _entry(3, details="portX1"))

    assert _ids(_page(client, q="50%")) == ["id-00001"]
    assert _ids(_page(client, q="port_1")) == ["id-00002"]   # «_» не «любой символ»
    assert _page(client, q="%")["total"] == 1                # «%» ищется как символ, а не «всё»


def test_search_ignores_entries_without_details(client, seed):
    entry = _entry(1)
    entry.details = None
    seed(entry, _entry(2, details="нашлось"))

    assert _ids(_page(client, q="нашлось")) == ["id-00002"]


def test_filters_by_action_and_entity_type_combine_with_search(client, seed):
    seed(
        _entry(1, action="CREATE", entity_type="devices", details="alpha"),
        _entry(2, action="DELETE", entity_type="devices", details="alpha"),
        _entry(3, action="CREATE", entity_type="vms", details="alpha"),
        _entry(4, action="CREATE", entity_type="devices", details="beta"),
    )

    assert _ids(_page(client, action="CREATE")) == ["id-00004", "id-00003", "id-00001"]
    assert _ids(_page(client, entity_type="vms")) == ["id-00003"]
    assert _ids(_page(client, action="CREATE", entity_type="devices", q="alpha")) == ["id-00001"]


def test_total_reflects_filters_but_summary_and_entity_types_do_not(client, seed):
    seed(
        *[_entry(i, action="CREATE", entity_type="devices") for i in range(1, 4)],
        *[_entry(i, action="UPDATE", entity_type="vms") for i in range(4, 6)],
        _entry(6, action="DELETE", entity_type="connections"),
        _entry(7, action="LOGIN", entity_type="auth"),
    )

    page = _page(client, action="CREATE", limit=2)

    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["summary"] == {"total": 7, "by_action": {"CREATE": 3, "UPDATE": 2, "DELETE": 1, "LOGIN": 1}}
    assert page["entity_types"] == ["auth", "connections", "devices", "vms"]


def test_empty_journal(client):
    page = _page(client)

    assert page["items"] == [] and page["total"] == 0
    assert page["summary"] == {"total": 0, "by_action": {}}
    assert page["entity_types"] == []


def test_entries_older_than_the_first_thousand_are_reachable(client, seed):
    """Раньше экран читал последние 1000 записей — всё старше было недоступно ни в таблице, ни в поиске."""
    seed(*[_entry(i, details=f"Запись №{i:05d}") for i in range(1, 1206)])

    last_page = _page(client, offset=1200, limit=24)
    assert _ids(last_page) == [f"id-{i:05d}" for i in range(5, 0, -1)]
    assert last_page["total"] == 1205 and last_page["summary"]["total"] == 1205
    assert _ids(_page(client, q="№00001")) == ["id-00001"]  # самая старая запись находится поиском


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": "x" * 201}, {"action": "x" * 51}, {"entity_type": "x" * 101}, {"limit": "abc"}],
)
def test_invalid_parameters_are_rejected(client, params):
    assert client.get("/api/v1/audit-log", params=params).status_code == 422


def test_query_count_does_not_grow_with_page_size(client, seed, sql_log):
    seed(*[_entry(i) for i in range(1, 60)])

    def statements_for(limit: int) -> int:
        sql_log.clear()
        _page(client, limit=limit)
        # Чтение настроек аутентификации в middleware не относится к эндпоинту журнала: оно кэшируется (П-5), и первый запрос
        # теста, в отличие от следующих, делает его на самом деле.
        return len([statement for statement in sql_log if "FROM auth_settings" not in statement])

    assert statements_for(2) == statements_for(50)


def test_generic_resource_list_uses_the_same_stable_order(client, seed):
    seed(*[_entry(i, minutes=0) for i in range(1, 6)])

    items = client.get("/api/v1/resources/audit-log", params={"limit": 10}).json()["items"]

    assert [item["id"] for item in items] == [f"id-{i:05d}" for i in range(5, 0, -1)]
