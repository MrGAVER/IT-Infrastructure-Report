"""Одобрение проблем проверки данных: POST/DELETE /api/v1/integrity/consistency/approvals и отбор по одобрению в отчёте.

Что защищают тесты: одобрение привязано к отпечатку проблемы и теряет силу, когда проблема меняется (но не от переименования);
одобрить можно только проблему, которая есть сейчас; повтор безопасен; отзыв возвращает проблему; всё попадает в журнал аудита.
Запуск: pytest backend/tests/test_consistency_approvals.py -v
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.constants import AuditAction, OwnerType
from app.models import AuditLog, ConsistencyApproval, IPAddress
from app.services.actor_context import Actor, current_actor
from app.services.consistency import run_checks
from app.services.consistency import approvals as approvals_module
from app.services.consistency.approvals import MAX_BATCH, MAX_COMMENT_LENGTH, approve_finding, approve_findings, stale_approvals
from test_consistency_checks import _device, _ip, _port

URL = "/api/v1/integrity/consistency"
APPROVALS = f"{URL}/approvals"
BATCH = f"{APPROVALS}/batch"
REVOKE_BATCH = f"{APPROVALS}/revoke"
STALE = f"{APPROVALS}/stale"


def _duplicate_ip(session, address="10.0.0.5", names=("srv-1", "srv-2")):
    """Два устройства с одним IP — находка duplicate_ip. Возвращает устройства."""
    devices = [_device(session, system_name=name) for name in names]
    for device in devices:
        _ip(session, OwnerType.DEVICE_INTERFACE, _port(session, device).id, address)
    return devices


def _port_of(session, device):
    """Единственный порт устройства, созданного через _duplicate_ip."""
    from app.models import DeviceInterface

    return session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device.id)).one()


def _report(client, **params) -> dict:
    response = client.get(URL, params={"limit": 5000, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _duplicate_finding(client, **params) -> dict:
    (found,) = [item for item in _report(client, rule="duplicate_ip", **params)["findings"]]
    return found


class TestFingerprint:
    def test_is_64_hex_characters_and_the_report_exposes_it(self, client, db_session):
        _duplicate_ip(db_session)

        assert re.fullmatch(r"[0-9a-f]{64}", _duplicate_finding(client)["fingerprint"])

    def test_survives_renaming_and_port_changes_but_not_a_new_holder(self, client, db_session):
        first, second = _duplicate_ip(db_session)
        before = _duplicate_finding(client)["fingerprint"]

        first.system_name = "srv-renamed"  # имя — подпись, а не суть проблемы
        db_session.commit()
        assert _duplicate_finding(client)["fingerprint"] == before

        third = _device(db_session, system_name="srv-3")
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, third).id, "10.0.0.5")
        assert _duplicate_finding(client)["fingerprint"] != before

    def test_differs_between_problems(self, client, db_session):
        _duplicate_ip(db_session, "10.0.0.5", ("a-1", "a-2"))
        _duplicate_ip(db_session, "10.0.0.6", ("b-1", "b-2"))

        fingerprints = {item["fingerprint"] for item in _report(client)["findings"]}

        assert len(fingerprints) == len(_report(client)["findings"])


class TestApprove:
    def test_approved_problem_is_marked_with_who_why_and_leaves_the_active_list(self, client, db_session):
        _duplicate_ip(db_session)
        fingerprint = _duplicate_finding(client)["fingerprint"]

        response = client.post(APPROVALS, json={"fingerprint": fingerprint, "comment": "  общий адрес VRRP  "})

        assert response.status_code == 200 and response.json()["created"] is True
        found = _duplicate_finding(client)
        assert found["approved"] is True
        assert found["approval"]["comment"] == "общий адрес VRRP" and found["approval"]["approved_at"]
        assert _report(client, rule="duplicate_ip", approval="active")["findings"] == []
        assert [item["rule"] for item in _report(client, approval="approved")["findings"]] == ["duplicate_ip"]

    def test_summary_counts_both_groups_and_ok_means_nothing_needs_attention(self, client, db_session):
        _duplicate_ip(db_session)
        body = _report(client, rule="duplicate_ip")
        assert body["ok"] is False and body["summary"]["by_approval"] == {"active": 1, "approved": 0}

        client.post(APPROVALS, json={"fingerprint": body["findings"][0]["fingerprint"]})

        for approval in ("all", "active", "approved"):
            body = _report(client, rule="duplicate_ip", approval=approval)
            assert body["summary"]["by_approval"] == {"active": 0, "approved": 1}, approval  # оба числа видны при любом отборе
        assert _report(client, rule="duplicate_ip")["ok"] is True

    def test_repeating_the_approval_changes_nothing(self, client, db_session):
        _duplicate_ip(db_session)
        fingerprint = _duplicate_finding(client)["fingerprint"]

        first = client.post(APPROVALS, json={"fingerprint": fingerprint, "comment": "первый"}).json()
        second = client.post(APPROVALS, json={"fingerprint": fingerprint, "comment": "второй"}).json()

        assert second["created"] is False and second["approval"] == first["approval"]
        assert second["approval"]["comment"] == "первый"
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 1

    def test_blank_comment_is_stored_as_no_comment(self, client, db_session):
        _duplicate_ip(db_session)
        fingerprint = _duplicate_finding(client)["fingerprint"]

        body = client.post(APPROVALS, json={"fingerprint": fingerprint, "comment": "   "}).json()

        assert body["approval"]["comment"] is None

    def test_a_problem_that_does_not_exist_cannot_be_approved_and_nothing_is_saved(self, client, db_session):
        response = client.post(APPROVALS, json={"fingerprint": "a" * 64})

        assert response.status_code == 404
        assert db_session.scalars(select(ConsistencyApproval)).all() == []

    @pytest.mark.parametrize(
        "body",
        [
            {"fingerprint": "abc"},
            {"fingerprint": "A" * 64},
            {"fingerprint": "g" * 64},
            {"comment": "без отпечатка"},
            {"fingerprint": "a" * 64, "comment": "x" * (MAX_COMMENT_LENGTH + 1)},
            {"fingerprint": "a" * 64, "comment": 5},
        ],
    )
    def test_malformed_requests_are_rejected_with_422(self, client, body):
        assert client.post(APPROVALS, json=body).status_code == 422

    def test_the_approval_records_the_author_and_goes_to_the_audit_log(self, db_session):
        _duplicate_ip(db_session)
        fingerprint = run_checks(db_session, rules=["duplicate_ip"])[0].fingerprint
        token = current_actor.set(Actor(user_id="u-1", username="anna"))
        try:
            result = approve_finding(db_session, fingerprint, "VRRP")
        finally:
            current_actor.reset(token)

        assert result["approval"]["approved_by"] == "anna"
        (entry,) = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "consistency-approvals")).all()
        assert entry.action == AuditAction.CREATE and entry.actor_username == "anna"
        assert "VRRP" in entry.details and "10.0.0.5" in entry.details

    def test_simultaneous_approval_of_the_same_problem_returns_the_saved_one(self, db_session, monkeypatch):
        _duplicate_ip(db_session)
        fingerprint = run_checks(db_session, rules=["duplicate_ip"])[0].fingerprint
        approve_finding(db_session, fingerprint, "первое")

        # Проверка «уже одобрено» не увидела запись (её создал параллельный запрос) — вставку остановит уникальный отпечаток.
        real_scalar = db_session.scalar
        calls = {"count": 0}

        def blind_first_lookup(statement, *args, **kwargs):
            calls["count"] += 1
            return None if calls["count"] == 1 else real_scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db_session, "scalar", blind_first_lookup)

        result = approve_finding(db_session, fingerprint, "второе")

        assert result["created"] is False and result["approval"]["comment"] == "первое"
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 1


class TestApprovalLosesForceWhenTheProblemChanges:
    def test_a_new_holder_of_the_address_is_a_new_problem(self, client, db_session):
        _duplicate_ip(db_session)
        client.post(APPROVALS, json={"fingerprint": _duplicate_finding(client)["fingerprint"]})

        third = _device(db_session, system_name="srv-3")
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, third).id, "10.0.0.5")

        found = _duplicate_finding(client)
        assert found["approved"] is False and found["approval"] is None

    def test_renaming_a_holder_keeps_the_approval(self, client, db_session):
        first, _ = _duplicate_ip(db_session)
        client.post(APPROVALS, json={"fingerprint": _duplicate_finding(client)["fingerprint"]})

        first.system_name = "srv-renamed"
        db_session.commit()

        assert _duplicate_finding(client)["approved"] is True


class TestRevoke:
    def test_revoking_returns_the_problem_to_the_active_list_and_is_audited(self, client, db_session):
        _duplicate_ip(db_session)
        approval_id = client.post(APPROVALS, json={"fingerprint": _duplicate_finding(client)["fingerprint"]}).json()["approval"]["id"]

        response = client.delete(f"{APPROVALS}/{approval_id}")

        assert response.status_code == 204 and response.content == b""
        assert _duplicate_finding(client)["approved"] is False
        assert db_session.scalars(select(ConsistencyApproval)).all() == []
        actions = db_session.scalars(select(AuditLog.action).where(AuditLog.entity_type == "consistency-approvals")).all()
        assert sorted(actions) == [AuditAction.CREATE, AuditAction.DELETE]

    def test_revoking_an_unknown_or_already_revoked_approval_is_404(self, client, db_session):
        _duplicate_ip(db_session)
        approval_id = client.post(APPROVALS, json={"fingerprint": _duplicate_finding(client)["fingerprint"]}).json()["approval"]["id"]
        client.delete(f"{APPROVALS}/{approval_id}")

        assert client.delete(f"{APPROVALS}/{approval_id}").status_code == 404
        assert client.delete(f"{APPROVALS}/no-such-id").status_code == 404


class TestBatch:
    def _three_problems(self, session):
        for number in range(3):
            _duplicate_ip(session, f"10.0.{number}.5", (f"a-{number}", f"b-{number}"))
        return [item.fingerprint for item in run_checks(session, rules=["duplicate_ip"])]

    def test_approves_all_listed_problems_with_one_comment_and_returns_the_approvals(self, client, db_session):
        wanted = self._three_problems(db_session)

        response = client.post(BATCH, json={"fingerprints": wanted, "comment": "  VRRP во всех сетях  "})

        body = response.json()
        assert response.status_code == 200 and body["approved"] == 3 and body["already"] == 0 and body["missing"] == []
        assert set(body["approvals"]) == set(wanted)
        assert {item["comment"] for item in body["approvals"].values()} == {"VRRP во всех сетях"}
        assert _report(client, rule="duplicate_ip", approval="active")["findings"] == []
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 3

    def test_every_approval_gets_its_own_audit_entry_marked_as_batch(self, client, db_session):
        wanted = self._three_problems(db_session)

        client.post(BATCH, json={"fingerprints": wanted, "comment": "VRRP"})

        entries = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "consistency-approvals")).all()
        assert len(entries) == 3 and all(item.action == AuditAction.CREATE for item in entries)
        assert all("пакетное одобрение" in item.details and "VRRP" in item.details for item in entries)

    def test_already_approved_are_counted_not_duplicated_and_keep_their_comment(self, client, db_session):
        wanted = self._three_problems(db_session)
        client.post(APPROVALS, json={"fingerprint": wanted[0], "comment": "первое"})

        body = client.post(BATCH, json={"fingerprints": wanted, "comment": "пакетное"}).json()

        assert body["approved"] == 2 and body["already"] == 1
        assert body["approvals"][wanted[0]]["comment"] == "первое"  # прежнее одобрение не перезаписано
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 3

    def test_changed_or_fixed_problems_are_reported_as_missing_and_do_not_cancel_the_rest(self, client, db_session):
        wanted = self._three_problems(db_session)
        gone = "f" * 64

        body = client.post(BATCH, json={"fingerprints": [wanted[0], gone, wanted[1]]}).json()

        assert body["approved"] == 2 and body["missing"] == [gone]
        assert gone not in body["approvals"]
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 2

    def test_repeats_in_the_request_are_collapsed(self, client, db_session):
        wanted = self._three_problems(db_session)

        body = client.post(BATCH, json={"fingerprints": [wanted[0], wanted[0], wanted[0]]}).json()

        assert body["approved"] == 1 and len(db_session.scalars(select(ConsistencyApproval)).all()) == 1

    @pytest.mark.parametrize(
        "body",
        [
            {"fingerprints": []},
            {"fingerprints": ["abc"]},
            {"fingerprints": ["A" * 64]},
            {"fingerprints": ["a" * 64] * (MAX_BATCH + 1)},
            {"fingerprints": "a" * 64},
            {"fingerprints": [5]},
            {"comment": "без списка"},
            {"fingerprints": ["a" * 64], "comment": "x" * (MAX_COMMENT_LENGTH + 1)},
        ],
    )
    def test_malformed_requests_are_rejected_with_422_and_save_nothing(self, client, db_session, body):
        assert client.post(BATCH, json=body).status_code == 422
        assert db_session.scalars(select(ConsistencyApproval)).all() == []

    def test_a_concurrent_approval_of_part_of_the_list_is_absorbed(self, db_session, monkeypatch):
        _duplicate_ip(db_session, "10.0.0.5", ("a", "b"))
        _duplicate_ip(db_session, "10.0.1.5", ("c", "d"))
        wanted = [item.fingerprint for item in run_checks(db_session, rules=["duplicate_ip"])]
        approve_finding(db_session, wanted[0], "параллельное")

        # Чтение «уже одобренных» в первой попытке не видит параллельную запись — вставку остановит уникальный отпечаток.
        real = approvals_module.load_approvals
        calls = {"count": 0}

        def blind_first_time(session):
            calls["count"] += 1
            return {} if calls["count"] == 1 else real(session)

        monkeypatch.setattr(approvals_module, "load_approvals", blind_first_time)

        result = approve_findings(db_session, wanted, "пакетное")

        assert result["approved"] == 1 and result["already"] == 1
        assert result["approvals"][wanted[0]]["comment"] == "параллельное"
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 2

    def test_the_whole_list_is_one_check_run_not_one_per_problem(self, db_session, monkeypatch):
        wanted = self._three_problems(db_session)
        runs = {"count": 0}
        real = approvals_module.run_checks

        def counting(*args, **kwargs):
            runs["count"] += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(approvals_module, "run_checks", counting)

        approve_findings(db_session, wanted)

        assert runs["count"] == 1  # а не по запуску на каждую из трёх проблем


class TestStale:
    """Одобрение, которому не соответствует ни одна текущая проблема (её исправили или она изменилась), — устаревшее."""

    def _approved_duplicate(self, client, db_session):
        devices = _duplicate_ip(db_session)
        fingerprint = _duplicate_finding(client)["fingerprint"]
        approval = client.post(APPROVALS, json={"fingerprint": fingerprint, "comment": "VRRP"}).json()["approval"]
        return devices, approval

    def test_matching_approvals_are_not_stale(self, client, db_session):
        self._approved_duplicate(client, db_session)

        assert _report(client)["stale_approvals"] == 0
        assert client.delete(STALE).json() == {"removed": 0}
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 1

    def test_once_the_problem_is_fixed_its_approval_becomes_stale_and_can_be_removed_with_an_audit_entry(self, client, db_session):
        (first, second), approval = self._approved_duplicate(client, db_session)
        db_session.query(IPAddress).filter(
            IPAddress.owner_id == _port_of(db_session, second).id
        ).delete()  # адрес второго убрали: повтора нет
        db_session.commit()

        assert _report(client)["stale_approvals"] == 1

        assert client.delete(STALE).json() == {"removed": 1}
        assert db_session.scalars(select(ConsistencyApproval)).all() == []
        entries = db_session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "consistency-approvals", AuditLog.action == AuditAction.DELETE)
        ).all()
        assert len(entries) == 1 and "устаревшее" in entries[0].details and entries[0].entity_id == approval["id"]
        assert _report(client)["stale_approvals"] == 0

    def test_a_changed_problem_leaves_the_old_approval_stale_while_the_new_problem_stays_active(self, client, db_session):
        self._approved_duplicate(client, db_session)
        third = _device(db_session, system_name="srv-3")
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, third).id, "10.0.0.5")  # у адреса появился третий владелец

        body = _report(client, rule="duplicate_ip", approval="all")
        assert body["stale_approvals"] is None  # при отборе по правилу устаревшие не определяются
        full = _report(client)
        assert full["stale_approvals"] == 1
        assert [item["approved"] for item in full["findings"] if item["rule"] == "duplicate_ip"] == [False]

        client.delete(STALE)

        assert [item["approved"] for item in _report(client)["findings"] if item["rule"] == "duplicate_ip"] == [False]

    def test_only_stale_approvals_are_removed_the_matching_ones_stay(self, client, db_session):
        (_, second), _ = self._approved_duplicate(client, db_session)
        _duplicate_ip(db_session, "10.0.9.5", ("keep-1", "keep-2"))
        keep = next(item for item in _report(client)["findings"] if item["rule"] == "duplicate_ip" and not item["approved"])
        client.post(APPROVALS, json={"fingerprint": keep["fingerprint"]})
        db_session.query(IPAddress).filter(IPAddress.owner_id == _port_of(db_session, second).id).delete()
        db_session.commit()

        assert client.delete(STALE).json() == {"removed": 1}

        remaining = db_session.scalars(select(ConsistencyApproval)).all()
        assert [row.fingerprint for row in remaining] == [keep["fingerprint"]]

    def test_stale_helper_needs_the_full_set_of_findings(self, db_session):
        _duplicate_ip(db_session)
        problem = run_checks(db_session, rules=["duplicate_ip"])[0]
        approve_finding(db_session, problem.fingerprint)

        assert stale_approvals(db_session) == []
        # По набору, из которого правило «выпало», одобрение выглядело бы устаревшим — поэтому полный набор обязателен.
        assert len(stale_approvals(db_session, run_checks(db_session, rules=["invalid_ip"]))) == 1

    def test_the_stale_route_is_not_taken_for_an_approval_id(self, client):
        response = client.delete(STALE)

        assert response.status_code == 200  # а не 404 «Одобрение не найдено» от маршрута /approvals/{approval_id}


class TestRevokeBatch:
    def _approved(self, client, db_session, count=3):
        for number in range(count):
            _duplicate_ip(db_session, f"10.0.{number}.5", (f"a-{number}", f"b-{number}"))
        fingerprints = [item["fingerprint"] for item in _report(client)["findings"] if item["rule"] == "duplicate_ip"]
        result = client.post(BATCH, json={"fingerprints": fingerprints}).json()
        return [approval["id"] for approval in result["approvals"].values()]

    def test_revokes_all_listed_approvals_and_the_problems_return_to_the_active_list(self, client, db_session):
        ids = self._approved(client, db_session)
        assert _report(client, rule="duplicate_ip", approval="active")["findings"] == []

        body = client.post(REVOKE_BATCH, json={"ids": ids}).json()

        assert body == {"revoked": 3, "missing": []}
        assert len(_report(client, rule="duplicate_ip", approval="active")["findings"]) == 3
        assert db_session.scalars(select(ConsistencyApproval)).all() == []

    def test_every_revocation_gets_its_own_audit_entry_marked_as_batch(self, client, db_session):
        ids = self._approved(client, db_session)

        client.post(REVOKE_BATCH, json={"ids": ids})

        entries = db_session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "consistency-approvals", AuditLog.action == AuditAction.DELETE)
        ).all()
        assert len(entries) == 3 and all("пакетный отзыв" in item.details for item in entries)

    def test_already_missing_ids_are_reported_and_do_not_cancel_the_rest(self, client, db_session):
        ids = self._approved(client, db_session)

        body = client.post(REVOKE_BATCH, json={"ids": [ids[0], "no-such-id", ids[1]]}).json()

        assert body["revoked"] == 2 and body["missing"] == ["no-such-id"]
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 1

    def test_repeats_in_the_request_are_collapsed(self, client, db_session):
        ids = self._approved(client, db_session)

        body = client.post(REVOKE_BATCH, json={"ids": [ids[0], ids[0]]}).json()

        assert body == {"revoked": 1, "missing": []}
        entries = db_session.scalars(
            select(AuditLog).where(AuditLog.entity_type == "consistency-approvals", AuditLog.action == AuditAction.DELETE)
        ).all()
        assert len(entries) == 1  # повтор в запросе не даёт второй записи аудита

    @pytest.mark.parametrize(
        "body",
        [{"ids": []}, {"ids": ["x"] * (MAX_BATCH + 1)}, {"ids": [5]}, {"ids": ["  "]}, {"ids": ["x" * 37]}, {"ids": "abc"}, {}],
    )
    def test_malformed_requests_are_rejected_with_422_and_delete_nothing(self, client, db_session, body):
        self._approved(client, db_session, count=1)

        assert client.post(REVOKE_BATCH, json=body).status_code == 422
        assert len(db_session.scalars(select(ConsistencyApproval)).all()) == 1


def test_unknown_approval_filter_is_rejected(client):
    assert client.get(URL, params={"approval": "maybe"}).status_code == 422


def test_service_rejects_a_bad_filter_value_even_without_the_api_layer(db_session):
    from app.services.consistency.report import build_consistency_report

    with pytest.raises(Exception, match="422|неизвестный отбор"):
        build_consistency_report(db_session, approval="maybe")


def test_approvals_module_exposes_the_documented_limits():
    assert approvals_module.MAX_COMMENT_LENGTH == 1000
