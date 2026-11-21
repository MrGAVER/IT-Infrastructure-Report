"""R1-07 п. 1 код-ревью: разбор заголовка `Authorization: Bearer` — один и нечувствительный к регистру.

Разбор был записан дважды (шлюз `services/auth/gate.py` и `api/auth.py`), оба раза по точному `Bearer `. Схема аутентификации в RFC 7235
нечувствительна к регистру, и клиент с `bearer <токен>` получал 401. Теперь разбор — `extract_bearer` из `services/auth/_common.py`.

Запуск: pytest backend/tests/test_auth_bearer_header.py -v
"""

from __future__ import annotations

import pytest
from test_resources_access import _enable_auth_with_viewer

from app.services.auth import extract_bearer

PROTECTED = "/api/v1/resources/manufacturers"


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Bearer x", "x"),
        ("bearer x", "x"),
        ("BEARER x", "x"),
        ("BeArEr x", "x"),
        ("Bearer   x  ", "x"),  # лишние пробелы вокруг токена
        ("Bearer a.b-c_d~e", "a.b-c_d~e"),
        ("Bearer ", None),  # токена нет
        ("Bearer", None),
        ("Bearer    ", None),
        ("", None),
        (None, None),
        ("Basic x", None),
        ("Bearerx", None),
        ("Token Bearer x", None),
        ("x Bearer y", None),
    ],
)
def test_extract_bearer(header, expected):
    assert extract_bearer(header) == expected


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_gate_accepts_any_case_of_the_scheme(client, scheme):
    admin_token, _ = _enable_auth_with_viewer(client)
    assert client.get(PROTECTED, headers={"Authorization": f"{scheme} {admin_token}"}).status_code == 200


@pytest.mark.parametrize("header", ["Basic abc", "Bearer ", "Bearer", "bearer wrong-token", "Token abc"])
def test_gate_still_rejects_other_schemes_and_bad_tokens(client, header):
    _enable_auth_with_viewer(client)
    assert client.get(PROTECTED, headers={"Authorization": header}).status_code == 401


def test_logout_reads_the_token_the_same_way(client):
    """api/auth.py разбирает заголовок тем же `extract_bearer`: сессия, закрытая через `bearer <токен>`, действительно закрывается."""
    admin_token, _ = _enable_auth_with_viewer(client)
    assert client.post("/api/v1/auth/logout", headers={"Authorization": f"bearer {admin_token}"}).status_code == 200
    assert client.get(PROTECTED, headers={"Authorization": f"Bearer {admin_token}"}).status_code == 401
