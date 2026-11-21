"""Код-ревью Н-8: счётчики главной страницы считаются одним запросом, а не отдельным COUNT на каждую сущность.

Запуск: pytest backend/tests/test_review_p1_dashboard_single_query.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.api.system import _DASHBOARD_ENTITIES

API = "/api/v1"


@pytest.fixture()
def statements(db_session):
    """Тексты всех SQL-запросов, выполненных движком тестовой БД, пока фикстура жива."""
    engine = db_session.get_bind()
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


def test_dashboard_keys_are_unchanged(client):
    body = client.get(f"{API}/dashboard").json()
    assert (
        set(body)
        == set(_DASHBOARD_ENTITIES)
        == {
            "information_systems",
            "physical_devices",
            "virtual_machines",
            "containers",
            "connections",
            "vlan",
            "software",
        }
    )
    assert all(isinstance(value, int) for value in body.values())


def test_dashboard_counts_follow_the_data(client):
    before = client.get(f"{API}/dashboard").json()
    assert client.post(f"{API}/resources/vlans", json={"vlan_id": 2901, "name": "Дашборд-1"}).status_code == 201
    assert client.post(f"{API}/resources/vlans", json={"vlan_id": 2902, "name": "Дашборд-2"}).status_code == 201
    after = client.get(f"{API}/dashboard").json()
    assert after["vlan"] == before["vlan"] + 2
    assert {k: v for k, v in after.items() if k != "vlan"} == {k: v for k, v in before.items() if k != "vlan"}


def test_dashboard_reads_the_database_with_one_counting_query(client, statements):
    client.get(f"{API}/dashboard")  # прогрев: кэш флага аутентификации живёт 2 с и сам делает свой запрос
    statements.clear()

    assert client.get(f"{API}/dashboard").status_code == 200

    counting = [s for s in statements if "count(" in s.lower()]
    assert len(counting) == 1, f"ожидался один запрос со счётчиками, выполнено {len(counting)}:\n" + "\n".join(counting)
    tables = ("physical_devices", "virtual_machines", "containers", "connections", "vlans")
    assert all(table in counting[0] for table in tables), counting[0]
