"""Защита от потерянных обновлений на PostgreSQL: реальные одновременные PUT с одним и тем же `expected_updated_at`.

`test_review_p1_update_stale_record.py::test_the_row_is_read_with_for_update` проверяет лишь, что строка читается с `FOR UPDATE`
(через monkeypatch), но не то, что из этого выходит. Здесь восемь потоков бьют в одну запись одновременно, у каждого запроса своя
сессия и своё соединение, как под несколькими воркерами uvicorn: блокировка строки выстраивает правки в очередь, победитель один,
остальные видят уже новый `updated_at` и получают 409 `STALE_RECORD`. Если строку начнут читать без блокировки (или иначе, чем
`session.get(..., with_for_update=True)`), все восемь пройдут проверку по старому снимку и результат перестанет быть `[200] + [409] * 7`.

Тест выполняется только на PostgreSQL (SQLite сериализует записи сам и блокировок строк не знает):
    INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/infra_test \\
        pytest backend/tests/test_review_p1_update_stale_record_pg.py -v
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.constants import ErrorCode
from app.models import AuditLog

pytestmark = pytest.mark.postgres_only

API = "/api/v1/resources"
WORKERS = 8


@pytest.fixture()
def pg_client_factory(client_factory, db_session):
    """Фабрика клиентов, у которых КАЖДЫЙ запрос работает в своей сессии (своя транзакция и соединение из пула движка).

    Общая фикстурная сессия `client_factory` для конкурентности не годится: все потоки делили бы одну транзакцию, и блокировки
    строки не было бы вовсе. Клиенты создаются без `with`: lifespan (стартовый seed справочников) уже отработал в `client_factory`,
    а запускать его в каждом из восьми потоков значило бы гонять между собой сам seed, а не проверяемую правку.
    """
    from fastapi.testclient import TestClient

    from app import main as app_main
    from app.db import get_db

    session_factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)

    def _own_session():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app_main.app.dependency_overrides[get_db] = _own_session  # снимет сама `client_factory` при завершении
    return lambda: TestClient(app_main.app, client=("127.0.0.1", 50000))


@pytest.fixture()
def manufacturer(client_factory) -> dict:
    response = client_factory().post(f"{API}/manufacturers", json={"name": "Гонка-0"})
    assert response.status_code == 201, response.text
    return response.json()


def _run_concurrently(pg_client_factory, requests: list[tuple[str, dict]]) -> list:
    """Отправляет все PUT одновременно (барьер перед самой отправкой) и возвращает ответы в порядке `requests`.

    Исключение в потоке пробрасывается через `Future.result()`, а не теряется; барьер с тайм-аутом не даёт тесту повиснуть, если
    один из потоков упал до него.
    """
    barrier = threading.Barrier(len(requests), timeout=30)

    def worker(url_and_body: tuple[str, dict]):
        url, body = url_and_body
        with pg_client_factory() as client:
            barrier.wait()
            return client.put(url, json=body)

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return [future.result(timeout=60) for future in [pool.submit(worker, item) for item in requests]]


def test_concurrent_puts_with_the_same_token_only_one_wins(pg_client_factory, manufacturer, db_session):
    url = f"{API}/manufacturers/{manufacturer['id']}"
    token = manufacturer["updated_at"]
    time.sleep(0.01)  # токен сверяется с точностью до миллисекунды: победитель обязан сдвинуть версию хотя бы на неё

    responses = _run_concurrently(
        pg_client_factory, [(url, {"name": f"Гонка-{i + 1}", "expected_updated_at": token}) for i in range(WORKERS)]
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200] + [409] * (WORKERS - 1), [response.text for response in responses]
    for loser in (response for response in responses if response.status_code == 409):
        assert loser.json()["detail"]["code"] == ErrorCode.STALE_RECORD

    winner = next(response for response in responses if response.status_code == 200).json()
    db_session.expire_all()
    stored = (
        db_session.execute(select(AuditLog).where(AuditLog.entity_type == "manufacturers", AuditLog.action == "UPDATE")).scalars().all()
    )
    assert len(stored) == 1, "в журнал попадает только принятая правка"
    assert winner["name"].startswith("Гонка-") and winner["name"] != "Гонка-0", "ответ победителя несёт его правку"


def test_the_stored_row_is_exactly_the_winners_change(pg_client_factory, manufacturer, client_factory):
    """Итоговое состояние — ровно правка победителя (имя и версия из его ответа): проигравшие ничего не записали."""
    url = f"{API}/manufacturers/{manufacturer['id']}"
    time.sleep(0.01)

    responses = _run_concurrently(
        pg_client_factory, [(url, {"name": f"Гонка-{i + 1}", "expected_updated_at": manufacturer["updated_at"]}) for i in range(WORKERS)]
    )

    winner = next(response for response in responses if response.status_code == 200).json()
    stored = client_factory().get(url).json()
    assert (stored["name"], stored["updated_at"]) == (winner["name"], winner["updated_at"])


def test_concurrent_puts_without_a_token_all_succeed(pg_client_factory, manufacturer):
    """Контракт «без токена побеждает последний» сохраняется и под нагрузкой: блокировка выстраивает правки в очередь, но не отклоняет."""
    url = f"{API}/manufacturers/{manufacturer['id']}"

    responses = _run_concurrently(pg_client_factory, [(url, {"name": f"Гонка-{i + 1}"}) for i in range(WORKERS)])

    assert [response.status_code for response in responses] == [200] * WORKERS, [response.text for response in responses]
