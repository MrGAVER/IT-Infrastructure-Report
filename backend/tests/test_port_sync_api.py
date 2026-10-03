"""API правил согласования портов: список, создание, правка (в том числе стандартных), удаление,
сброс к стандартному, порядок проверки, стартовое заполнение и журнал аудита.

Запуск: pytest backend/tests/test_port_sync_api.py -v
"""
from __future__ import annotations

import pytest

from app.models import AuditLog, PortSyncRule
from app.services.port_sync_rules import DEFAULT_RULES, DEFAULT_RULES_BY_CODE, EMPTY_TRUNK_RULE, ROLE_MATCH_RULE
from app.services.port_sync_store import ensure_default_rules

BASE = "/api/v1/port-sync/rules"


def _rules(client) -> list[dict]:
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _by_code(client, code: str) -> dict:
    return next(r for r in _rules(client) if r["code"] == code)


def _custom(**overrides) -> dict:
    body = {"name": "Мой trunk", "action": "auto", "target": {"mode": "trunk", "vlans": "none"}, "apply": {"vlans": "copy"}}
    body.update(overrides)
    return body


def _audit(db_session, *needles: str) -> list[str]:
    db_session.expire_all()
    return [e.details for e in db_session.query(AuditLog).order_by(AuditLog.created_at).all() if all(n in (e.details or "") for n in needles)]


# --- стандартные правила ------------------------------------------------------------------------

def test_standard_rules_are_seeded_at_startup_in_priority_order(client):
    rules = _rules(client)

    assert [r["code"] for r in rules] == [r.code for r in sorted(DEFAULT_RULES, key=lambda r: r.priority)]
    assert all(r["builtin"] and not r["modified"] and r["enabled"] for r in rules)
    assert [r["priority"] for r in rules] == sorted(r["priority"] for r in rules)


def test_new_standard_rule_is_exposed_exactly_as_requested(client):
    rule = _by_code(client, EMPTY_TRUNK_RULE)

    assert rule["action"] == "auto"
    assert rule["target"] == {"role": "any", "mode": "trunk", "vlans": "none"}
    assert rule["source"] == {"role": "any", "mode": "trunk", "vlans": "set"}
    assert rule["apply"] == {"role": False, "mode": True, "vlans": "copy"}


def test_seeding_is_idempotent_and_never_overwrites_an_edited_standard_rule(client, db_session):
    rule = _by_code(client, ROLE_MATCH_RULE)
    client.put(f"{BASE}/{rule['id']}", json={"action": "auto", "enabled": False, "name": "Моё название"})

    assert ensure_default_rules(db_session) == 0
    assert ensure_default_rules(db_session) == 0

    edited = _by_code(client, ROLE_MATCH_RULE)
    assert (edited["action"], edited["enabled"], edited["name"]) == ("auto", False, "Моё название")
    assert len(_rules(client)) == len(DEFAULT_RULES)


def test_seeding_restores_a_missing_standard_rule_without_touching_the_others(client, db_session):
    db_session.query(PortSyncRule).filter_by(code=ROLE_MATCH_RULE).delete()
    db_session.commit()

    assert ensure_default_rules(db_session) == 1

    assert {r["code"] for r in _rules(client)} == set(DEFAULT_RULES_BY_CODE)


def test_seeding_survives_a_user_rule_that_took_a_standard_name(client, db_session):
    db_session.query(PortSyncRule).filter_by(code=ROLE_MATCH_RULE).delete()
    db_session.add(PortSyncRule(name=DEFAULT_RULES_BY_CODE[ROLE_MATCH_RULE].name, action="manual"))
    db_session.commit()

    assert ensure_default_rules(db_session) == 1

    names = [r["name"] for r in _rules(client)]
    assert len(set(names)) == len(names) and any(n.endswith("(стандартное)") for n in names)


# --- создание ----------------------------------------------------------------------------------

def test_create_rule_returns_it_and_puts_it_last_when_no_priority_is_given(client, db_session):
    response = client.post(BASE, json=_custom())

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["builtin"] is False and created["code"] is None and created["enabled"] is True
    assert created["priority"] == max(r["priority"] for r in _rules(client) if r["id"] != created["id"]) + 10
    assert _rules(client)[-1]["id"] == created["id"]
    assert _audit(db_session, "Создано правило", "Мой trunk")


def test_create_rule_honours_an_explicit_priority(client):
    created = client.post(BASE, json=_custom(priority=1)).json()

    assert _rules(client)[0]["id"] == created["id"]


def test_create_rule_rejects_duplicate_names_ignoring_case(client):
    client.post(BASE, json=_custom(name="Правило А"))

    response = client.post(BASE, json=_custom(name="  правило а "))

    assert response.status_code == 409 and "уже есть" in response.json()["detail"]


def test_create_rule_cannot_pose_as_a_standard_one(client):
    created = client.post(BASE, json=_custom(code=ROLE_MATCH_RULE, builtin=True)).json()

    assert created["code"] is None and created["builtin"] is False
    assert len([r for r in _rules(client) if r["code"] == ROLE_MATCH_RULE]) == 1


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"name": ""}, "Название"),
        ({"action": "x"}, "Действие"),
        ({"target": {"mode": "bridge"}}, "mode"),
        ({"apply": {"vlans": "keep"}}, "что-то менять"),
        ({"apply": {"vlans": "adapt"}}, "по режиму"),
        ({"priority": "high"}, "Приоритет"),
    ],
)
def test_create_rule_validates_input(client, body, fragment):
    response = client.post(BASE, json=_custom(**body))

    assert response.status_code == 422 and fragment in response.json()["detail"]
    assert len(_rules(client)) == len(DEFAULT_RULES)  # ничего не создано


def test_create_rule_requires_a_json_object(client):
    assert client.post(BASE, json=[1, 2]).status_code == 422


# --- правка ------------------------------------------------------------------------------------

def test_update_changes_only_the_given_fields_of_a_custom_rule(client, db_session):
    created = client.post(BASE, json=_custom(description="первое")).json()

    response = client.put(f"{BASE}/{created['id']}", json={"enabled": False, "source": {"vlans": "all"}})

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["enabled"] is False and updated["source"]["vlans"] == "all"
    assert updated["description"] == "первое" and updated["target"] == created["target"]
    assert _audit(db_session, "Изменено правило", "включено", "условия порта-источника")


def test_standard_rules_can_be_edited_and_are_marked_modified(client):
    rule = _by_code(client, EMPTY_TRUNK_RULE)

    response = client.put(f"{BASE}/{rule['id']}", json={"source": {"vlans": "all"}, "apply": {"role": True}})

    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["builtin"] is True and edited["code"] == EMPTY_TRUNK_RULE and edited["modified"] is True
    assert edited["source"]["vlans"] == "all" and edited["apply"] == {"role": True, "mode": True, "vlans": "copy"}


def test_switching_a_standard_rule_off_or_reordering_it_is_not_a_modification(client):
    rule = _by_code(client, EMPTY_TRUNK_RULE)

    edited = client.put(f"{BASE}/{rule['id']}", json={"enabled": False, "priority": 999}).json()

    assert edited["modified"] is False and edited["enabled"] is False and edited["priority"] == 999


def test_update_without_real_changes_writes_no_audit_entry(client, db_session):
    rule = _by_code(client, ROLE_MATCH_RULE)

    client.put(f"{BASE}/{rule['id']}", json={"name": rule["name"], "enabled": True})

    assert _audit(db_session, "Изменено правило") == []


def test_service_fields_cannot_be_changed_by_update(client):
    rule = _by_code(client, ROLE_MATCH_RULE)

    edited = client.put(f"{BASE}/{rule['id']}", json={"code": "hacked", "builtin": False, "id": "x"}).json()

    assert edited["code"] == ROLE_MATCH_RULE and edited["builtin"] is True and edited["id"] == rule["id"]


def test_update_rejects_taking_another_rules_name_and_invalid_values(client):
    first = client.post(BASE, json=_custom(name="Один")).json()
    client.post(BASE, json=_custom(name="Два"))

    assert client.put(f"{BASE}/{first['id']}", json={"name": "два"}).status_code == 409
    assert client.put(f"{BASE}/{first['id']}", json={"action": "bad"}).status_code == 422
    assert client.get(BASE).json()["items"][-2]["name"] == "Один"  # неудачная правка ничего не записала


def test_update_of_unknown_rule_is_404(client):
    assert client.put(f"{BASE}/nope", json={"enabled": False}).status_code == 404


# --- удаление и сброс --------------------------------------------------------------------------

def test_custom_rule_can_be_deleted(client, db_session):
    created = client.post(BASE, json=_custom()).json()

    response = client.delete(f"{BASE}/{created['id']}")

    assert response.status_code == 204
    assert created["id"] not in [r["id"] for r in _rules(client)]
    assert _audit(db_session, "Удалено правило", "Мой trunk")


def test_standard_rule_cannot_be_deleted_only_disabled(client):
    rule = _by_code(client, ROLE_MATCH_RULE)

    response = client.delete(f"{BASE}/{rule['id']}")

    assert response.status_code == 409 and "отключите" in response.json()["detail"]
    assert _by_code(client, ROLE_MATCH_RULE)["id"] == rule["id"]


def test_delete_of_unknown_rule_is_404(client):
    assert client.delete(f"{BASE}/nope").status_code == 404


def test_reset_returns_a_standard_rule_to_its_original_form(client, db_session):
    rule = _by_code(client, EMPTY_TRUNK_RULE)
    client.put(f"{BASE}/{rule['id']}", json={"name": "Иначе", "action": "manual", "enabled": False, "priority": 5, "source": {"vlans": "any"}})
    assert _by_code(client, EMPTY_TRUNK_RULE)["modified"] is True

    response = client.post(f"{BASE}/{rule['id']}/reset")

    assert response.status_code == 200, response.text
    restored = response.json()
    default = DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]
    assert (restored["name"], restored["action"], restored["enabled"], restored["priority"]) == (default.name, "auto", True, default.priority)
    assert restored["modified"] is False and restored["source"]["vlans"] == "set"
    assert _audit(db_session, "сброшено к исходному виду")


def test_reset_is_only_for_standard_rules(client):
    created = client.post(BASE, json=_custom()).json()

    assert client.post(f"{BASE}/{created['id']}/reset").status_code == 409
    assert client.post(f"{BASE}/nope/reset").status_code == 404


def test_reset_fails_cleanly_when_the_original_name_is_taken(client):
    rule = _by_code(client, ROLE_MATCH_RULE)
    original = rule["name"]
    client.put(f"{BASE}/{rule['id']}", json={"name": "Переименовано"})
    client.post(BASE, json=_custom(name=original))

    response = client.post(f"{BASE}/{rule['id']}/reset")

    assert response.status_code == 409
    assert _by_code(client, ROLE_MATCH_RULE)["name"] == "Переименовано"


# --- порядок -----------------------------------------------------------------------------------

def test_reorder_rewrites_priorities_in_steps_of_ten(client, db_session):
    ids = [r["id"] for r in _rules(client)]

    response = client.post(f"{BASE}/reorder", json={"ids": list(reversed(ids))})

    assert response.status_code == 200, response.text
    result = response.json()["items"]
    assert [r["id"] for r in result] == list(reversed(ids))
    assert [r["priority"] for r in result] == [10 * n for n in range(1, len(ids) + 1)]
    assert _audit(db_session, "порядок проверки")


def test_reorder_without_changes_writes_no_audit_entry(client, db_session):
    ids = [r["id"] for r in _rules(client)]
    client.post(f"{BASE}/reorder", json={"ids": ids})
    before = len(_audit(db_session, "порядок проверки"))

    client.post(f"{BASE}/reorder", json={"ids": ids})

    assert len(_audit(db_session, "порядок проверки")) == before


@pytest.mark.parametrize("mutate", [lambda ids: ids[:-1], lambda ids: ids + ["nope"], lambda ids: ids + ids[:1], lambda ids: []])
def test_reorder_requires_every_rule_exactly_once(client, mutate):
    ids = [r["id"] for r in _rules(client)]

    response = client.post(f"{BASE}/reorder", json={"ids": mutate(ids)})

    assert response.status_code == 422
    assert [r["id"] for r in _rules(client)] == ids


def test_reorder_rejects_a_malformed_body(client):
    assert client.post(f"{BASE}/reorder", json={"ids": "abc"}).status_code == 422
    assert client.post(f"{BASE}/reorder", json={}).status_code == 422
    assert client.post(f"{BASE}/reorder", json=[]).status_code == 422
