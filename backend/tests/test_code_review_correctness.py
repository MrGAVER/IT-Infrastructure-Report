"""Тесты исправлений корректности по код-ревью (пп. 6, 7, 8, 9, 11, 12).

Запуск: pytest backend/tests/test_code_review_correctness.py -v
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy.exc import IntegrityError

from app.models import Manufacturer, PhysicalDevice
from app.services.audit_export import build_audit_log_report
from app.services.crud import list_resource, validate_resource
from app.services.excel_safety import needs_text_guard
from app.services.integrity import integrity_error_response
from app.services.report_cleanup import cleanup_old_reports

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_device_type(client, name: str = "Тестовый тип для стойки") -> dict:
    categories = client.get("/api/v1/resources/device-categories").json()["items"]
    r = client.post("/api/v1/resources/device-types", json={"name": name, "category_id": categories[0]["id"]})
    assert r.status_code == 201, r.text
    return r.json()


def _rack_fixture(client) -> dict:
    building = client.post("/api/v1/resources/buildings", json={"name": "ЦОД"}).json()
    room = client.post("/api/v1/resources/rooms", json={"building_id": building["id"], "name": "Серверная"}).json()
    rack = client.post("/api/v1/resources/racks", json={"room_id": room["id"], "name": "R01"}).json()
    return {"room_id": room["id"], "rack_id": rack["id"], "device_type_id": _create_device_type(client)["id"]}


def _device(client, ctx: dict, serial: str, position: str | None, **extra):
    body = {"device_type_id": ctx["device_type_id"], "serial_number": serial, "room_id": ctx["room_id"], "rack_id": ctx["rack_id"], **extra}
    if position is not None:
        body["rack_position"] = position
    return client.post("/api/v1/resources/devices", json=body)


# ---------------------------------------------------------------------------
# п. 6. Стабильный ORDER BY
# ---------------------------------------------------------------------------
class TestStablePagination:
    def _seed_with_equal_timestamps(self, db_session, count: int = 25) -> list[str]:
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # id намеренно вставляются в порядке, обратном алфавитному: без ORDER BY SQLite вернёт их в порядке
        # вставки, то есть не отсортированными по id.
        ids = [f"m-{i:03d}" for i in range(count)][::-1]
        for item_id in ids:
            db_session.add(Manufacturer(id=item_id, name=f"Производитель {item_id}", created_at=stamp, updated_at=stamp))
        db_session.commit()
        return sorted(ids)

    def test_rows_with_equal_timestamps_come_back_in_a_deterministic_order(self, db_session):
        expected = self._seed_with_equal_timestamps(db_session)
        result = list_resource("manufacturers", db_session, offset=0, limit=100)
        assert [row["id"] for row in result["items"]] == expected

    def test_walking_all_pages_returns_every_row_exactly_once(self, db_session):
        expected = self._seed_with_equal_timestamps(db_session, 25)
        seen: list[str] = []
        for offset in range(0, 25, 7):
            seen += [row["id"] for row in list_resource("manufacturers", db_session, offset=offset, limit=7)["items"]]
        assert seen == expected

    def test_older_rows_come_first(self, db_session):
        db_session.add(Manufacturer(id="new", name="Новый", created_at=datetime(2026, 3, 1), updated_at=datetime(2026, 3, 1)))
        db_session.add(Manufacturer(id="old", name="Старый", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1)))
        db_session.commit()
        assert [r["id"] for r in list_resource("manufacturers", db_session, offset=0, limit=10)["items"]] == ["old", "new"]


# ---------------------------------------------------------------------------
# п. 12. Поиск: «%» и «_» — обычные символы
# ---------------------------------------------------------------------------
class TestSearchEscaping:
    def _names(self, db_session, q: str) -> set[str]:
        return {row["name"] for row in list_resource("manufacturers", db_session, q=q, offset=0, limit=100)["items"]}

    def test_percent_in_query_is_not_a_wildcard(self, db_session):
        db_session.add_all([Manufacturer(name="Скидка 50%"), Manufacturer(name="Скидка 500"), Manufacturer(name="Скидка 5")])
        db_session.commit()
        assert self._names(db_session, "50%") == {"Скидка 50%"}

    def test_underscore_in_query_is_not_a_single_char_wildcard(self, db_session):
        db_session.add_all([Manufacturer(name="srv_01"), Manufacturer(name="srvX01")])
        db_session.commit()
        assert self._names(db_session, "srv_01") == {"srv_01"}

    def test_plain_search_is_still_case_insensitive_substring(self, db_session):
        db_session.add_all([Manufacturer(name="Cisco Systems"), Manufacturer(name="Huawei")])
        db_session.commit()
        assert self._names(db_session, "ciSCO") == {"Cisco Systems"}


# ---------------------------------------------------------------------------
# п. 7. Слот в стойке: уникальность в БД, валидатор без побочных эффектов
# ---------------------------------------------------------------------------
class TestRackSlot:
    def test_database_refuses_two_devices_in_one_slot(self, client, db_session):
        ctx = _rack_fixture(client)
        assert _device(client, ctx, "SN-1", "10U").status_code == 201
        db_session.add(PhysicalDevice(device_type_id=ctx["device_type_id"], serial_number="SN-2", rack_id=ctx["rack_id"], rack_position="10U"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_devices_without_a_position_may_share_a_rack(self, client):
        ctx = _rack_fixture(client)
        assert _device(client, ctx, "SN-1", None).status_code == 201
        assert _device(client, ctx, "SN-2", None).status_code == 201

    def test_same_position_in_different_racks_is_fine(self, client):
        ctx = _rack_fixture(client)
        other = client.post("/api/v1/resources/racks", json={"room_id": ctx["room_id"], "name": "R02"}).json()
        assert _device(client, ctx, "SN-1", "10U").status_code == 201
        assert _device(client, {**ctx, "rack_id": other["id"]}, "SN-2", "10U").status_code == 201

    def test_confirmed_reassign_on_create_moves_the_slot_to_the_new_device(self, client, db_session):
        ctx = _rack_fixture(client)
        first = _device(client, ctx, "SN-1", "10U").json()
        second = _device(client, ctx, "SN-2", "10U", confirm_rack_position_reassign=True)
        assert second.status_code == 201, second.text
        db_session.expire_all()
        assert db_session.get(PhysicalDevice, first["id"]).rack_position is None
        assert db_session.get(PhysicalDevice, second.json()["id"]).rack_position == "10U"

    def test_confirmed_reassign_on_update_moves_the_slot_to_the_edited_device(self, client, db_session):
        ctx = _rack_fixture(client)
        first = _device(client, ctx, "SN-1", "10U").json()
        second = _device(client, ctx, "SN-2", "12U").json()
        r = client.put(f"/api/v1/resources/devices/{second['id']}", json={"rack_position": "10U", "confirm_rack_position_reassign": True})
        assert r.status_code == 200, r.text
        db_session.expire_all()
        assert db_session.get(PhysicalDevice, first["id"]).rack_position is None
        assert db_session.get(PhysicalDevice, second["id"]).rack_position == "10U"

    def test_unconfirmed_conflict_changes_nothing(self, client, db_session):
        ctx = _rack_fixture(client)
        first = _device(client, ctx, "SN-1", "10U").json()
        r = _device(client, ctx, "SN-2", "10U")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "RACK_POSITION_OCCUPIED"
        db_session.expire_all()
        assert db_session.get(PhysicalDevice, first["id"]).rack_position == "10U"

    def test_validation_has_no_side_effects(self, client, db_session):
        ctx = _rack_fixture(client)
        first = _device(client, ctx, "SN-1", "10U").json()
        data = {"device_type_id": ctx["device_type_id"], "serial_number": "SN-2", "room_id": ctx["room_id"], "rack_id": ctx["rack_id"], "rack_position": "10U"}
        validate_resource(PhysicalDevice, data, db_session, None, False, True)
        assert db_session.get(PhysicalDevice, first["id"]).rack_position == "10U"
        assert not db_session.dirty

    def test_lost_race_is_reported_as_occupied_slot_not_as_a_raw_database_error(self):
        orig = Exception("UNIQUE constraint failed: physical_devices.rack_id, physical_devices.rack_position")
        error = integrity_error_response("devices", IntegrityError("INSERT ...", {}, orig))
        assert error.status_code == 409
        assert error.detail["code"] == "RACK_POSITION_OCCUPIED"
        assert "physical_devices" not in str(error.detail)


class TestRackSlotMigration:
    PRE, TARGET = "a3e7c1d9b406", "b5d2f8a1c673"

    @pytest.fixture()
    def alembic_config(self, tmp_path, monkeypatch):
        import app.config as app_config

        db_path = tmp_path / "migration_test.db"
        monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.attributes["configure_logger"] = False
        return cfg, db_path

    def _insert_device(self, conn, device_id: str, created: str, rack: str | None, position: str | None) -> None:
        conn.execute(
            "INSERT INTO physical_devices (id, device_type_id, serial_number, rack_id, rack_position, siem_enabled, created_at, updated_at) "
            "VALUES (?, 'dt', ?, ?, ?, 0, ?, ?)",
            (device_id, f"SN-{device_id}", rack, position, created, created),
        )

    def _prepare(self, cfg, db_path):
        command.upgrade(cfg, self.PRE)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=OFF")
        self._insert_device(conn, "newer", "2026-02-01 00:00:00", "rack-1", "10U")
        self._insert_device(conn, "older", "2026-01-01 00:00:00", "rack-1", "10U")
        self._insert_device(conn, "other-slot", "2026-01-01 00:00:00", "rack-1", "12U")
        self._insert_device(conn, "no-position-a", "2026-01-01 00:00:00", "rack-1", None)
        self._insert_device(conn, "no-position-b", "2026-01-01 00:00:00", "rack-1", None)
        conn.commit()
        return conn

    def test_upgrade_clears_duplicate_slots_keeping_the_oldest_and_creates_the_index(self, alembic_config):
        cfg, db_path = alembic_config
        conn = self._prepare(cfg, db_path)
        conn.close()

        command.upgrade(cfg, self.TARGET)

        conn = sqlite3.connect(str(db_path))
        positions = dict(conn.execute("SELECT id, rack_position FROM physical_devices").fetchall())
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(physical_devices)").fetchall()}
        conn.close()
        assert positions["older"] == "10U"
        assert positions["newer"] is None  # дубль: позиция снята, само устройство и его стойка сохранены
        assert positions["other-slot"] == "12U"
        assert "uq_device_rack_slot" in indexes

    def test_downgrade_drops_the_index_and_round_trips(self, alembic_config):
        cfg, db_path = alembic_config
        command.upgrade(cfg, self.TARGET)
        command.downgrade(cfg, self.PRE)
        conn = sqlite3.connect(str(db_path))
        assert "uq_device_rack_slot" not in {row[1] for row in conn.execute("PRAGMA index_list(physical_devices)").fetchall()}
        conn.close()
        command.upgrade(cfg, self.TARGET)


# ---------------------------------------------------------------------------
# п. 8. Ошибки целостности не раскрывают внутреннее устройство БД
# ---------------------------------------------------------------------------
class TestIntegrityErrors:
    def test_helper_returns_a_generic_message_and_logs_the_details(self, caplog):
        orig = Exception('duplicate key value violates unique constraint "uq_secret_table_name_key"')
        with caplog.at_level("WARNING"):
            error = integrity_error_response("manufacturers", IntegrityError("INSERT ...", {}, orig))
        assert isinstance(error, HTTPException) and error.status_code == 409
        assert error.detail["code"] == "INTEGRITY_ERROR"
        assert "uq_secret_table_name_key" not in str(error.detail)
        assert "uq_secret_table_name_key" in caplog.text  # администратору детали доступны в логе

    def test_api_does_not_leak_table_or_constraint_names(self, client):
        assert client.post("/api/v1/resources/manufacturers", json={"name": "Дубль"}).status_code == 201
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Дубль"})
        assert r.status_code == 409
        body = r.text.lower()
        assert "manufacturers" not in body and "unique constraint" not in body
        assert r.json()["detail"]["code"] == "INTEGRITY_ERROR"


# ---------------------------------------------------------------------------
# п. 9. Роль viewer: отчёты — чтение
# ---------------------------------------------------------------------------
TEMPLATE_CONFIG = {"sheets": [{
    "title": "Лист1",
    "columns": [{"width": 25}],
    "rows": [{"height": 18, "repeat": True, "data_source": {"root_entity": "information-systems"}, "cells": [{"col": 0, "kind": "field", "path": "name"}]}],
}]}


def _create_template(client, admin_token: str) -> str:
    r = client.post("/api/v1/report-templates", json={"name": "Шаблон для viewer", "config": TEMPLATE_CONFIG}, headers=_bearer(admin_token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _admin_and_viewer_tokens(client) -> tuple[str, str]:
    assert client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"}).status_code == 201
    assert client.post("/api/v1/auth/users", json={"username": "viewer", "password": "Viewer1234", "role": "viewer"}).status_code == 201
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    tokens = []
    for username, password in (("admin", "Admin1234"), ("viewer", "Viewer1234")):
        r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, r.text
        tokens.append(r.json()["token"])
    return tokens[0], tokens[1]


class TestViewerReports:
    def test_viewer_can_generate_reports_and_preview(self, client):
        admin, viewer = _admin_and_viewer_tokens(client)
        headers = _bearer(viewer)
        assert client.post("/api/v1/reports/inventory", headers=headers).status_code == 200
        assert client.post("/api/v1/reports/audit-log", headers=headers).status_code == 200
        preview = client.post("/api/v1/report-builder/preview", json={"format": "xlsx", "config": {}}, headers=headers)
        assert preview.status_code != 403, preview.text

    def test_viewer_can_generate_from_a_template(self, client):
        admin, viewer = _admin_and_viewer_tokens(client)
        template_id = _create_template(client, admin)
        r = client.post(f"/api/v1/report-templates/{template_id}/generate", json={}, headers=_bearer(viewer))
        assert r.status_code == 200, r.text

    def test_viewer_still_cannot_change_data_or_templates(self, client):
        admin, viewer = _admin_and_viewer_tokens(client)
        headers = _bearer(viewer)
        template_id = _create_template(client, admin)
        assert client.post("/api/v1/resources/manufacturers", json={"name": "X"}, headers=headers).status_code == 403
        assert client.post("/api/v1/report-templates", json={"name": "T"}, headers=headers).status_code == 403
        assert client.put(f"/api/v1/report-templates/{template_id}", json={"name": "T"}, headers=headers).status_code == 403
        assert client.delete(f"/api/v1/report-templates/{template_id}", headers=headers).status_code == 403
        assert client.post(f"/api/v1/report-templates/{template_id}/duplicate", headers=headers).status_code == 403
        assert client.post("/api/v1/seed", headers=headers).status_code == 403

    def test_read_only_post_lookalikes_stay_forbidden(self, client):
        admin, viewer = _admin_and_viewer_tokens(client)
        headers = _bearer(viewer)
        assert client.post("/api/v1/reports/inventory/extra", headers=headers).status_code == 403
        assert client.post("/api/v1/report-templates/abc/generate/extra", headers=headers).status_code == 403
        assert client.post("/api/v1/report-templates/a/b/generate", headers=headers).status_code == 403

    def test_anonymous_still_needs_a_token_once_auth_is_enabled(self, client):
        _admin_and_viewer_tokens(client)
        assert client.post("/api/v1/reports/inventory").status_code == 401


# ---------------------------------------------------------------------------
# п. 12. Копирование и массовое назначение VLAN: без N+1 и без дублей
# ---------------------------------------------------------------------------
class TestVlanBulkOperations:
    def _devices(self, client, count: int) -> list[dict]:
        device_type = _create_device_type(client, "Тип для VLAN-операций")
        return [client.post("/api/v1/resources/devices", json={"device_type_id": device_type["id"], "serial_number": f"VB-{i}"}).json() for i in range(count)]

    def _assign_vlans(self, client, device: dict, numbers: list[int]) -> None:
        for number in numbers:
            vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": number, "name": f"vlan{number}"}).json()
            assert client.post("/api/v1/resources/device-vlans", json={"physical_device_id": device["id"], "vlan_id": vlan["id"]}).status_code == 201

    def _count_selects(self, db_session, action) -> int:
        from sqlalchemy import event

        statements: list[str] = []
        engine = db_session.get_bind()

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", record)
        try:
            action()
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(statements)

    def test_repeated_copy_does_not_create_duplicates(self, client):
        source, target = self._devices(client, 2)
        self._assign_vlans(client, source, [10, 20])
        first = client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={"source_device_id": source["id"]}).json()
        second = client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={"source_device_id": source["id"]}).json()
        assert first["created_definitions"] == 2 and first["assigned"] == 2
        assert second == {"status": "ok", "created_definitions": 0, "assigned": 0}
        assigned = client.get(f"/api/v1/resources/device-vlans?physical_device_id={target['id']}").json()["items"]
        assert len(assigned) == 2

    def test_copy_only_adds_what_the_target_lacks(self, client):
        source, target = self._devices(client, 2)
        self._assign_vlans(client, source, [10, 20])
        self._assign_vlans(client, target, [10])  # тот же номер и имя, что у источника
        result = client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={"source_device_id": source["id"]}).json()
        assert result["created_definitions"] == 1 and result["assigned"] == 1

    def test_copy_query_count_does_not_grow_with_the_number_of_vlans(self, client, db_session):
        source_small, target_small, source_big, target_big = self._devices(client, 4)
        self._assign_vlans(client, source_small, [101])
        self._assign_vlans(client, source_big, list(range(201, 213)))
        small = self._count_selects(db_session, lambda: client.post(f"/api/v1/devices/{target_small['id']}/vlan-copy", json={"source_device_id": source_small["id"]}))
        big = self._count_selects(db_session, lambda: client.post(f"/api/v1/devices/{target_big['id']}/vlan-copy", json={"source_device_id": source_big["id"]}))
        assert big == small

    def test_bulk_assign_query_count_does_not_grow_with_the_number_of_devices(self, client, db_session):
        devices = self._devices(client, 12)
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 77, "name": "bulk"}).json()
        few = self._count_selects(db_session, lambda: client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": [d["id"] for d in devices[:2]], "vlan_id": vlan["id"]}))
        many = self._count_selects(db_session, lambda: client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"]}))
        assert many == few

    def test_bulk_assign_still_reports_missing_devices(self, client):
        (device,) = self._devices(client, 1)
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 78, "name": "bulk2"}).json()
        r = client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": [device["id"], "нет-такого"], "vlan_id": vlan["id"]})
        assert r.status_code == 404 and "нет-такого" in r.text


# ---------------------------------------------------------------------------
# п. 11. Отчёты: имена, формулы, накопление файлов
# ---------------------------------------------------------------------------
class TestReportFiles:
    def test_two_exports_in_the_same_second_get_different_files(self, db_session, tmp_path):
        first = build_audit_log_report(db_session, tmp_path)
        second = build_audit_log_report(db_session, tmp_path)
        assert first != second and first.exists() and second.exists()

    def test_audit_export_neutralises_formulas_in_free_text(self, client, db_session, tmp_path):
        from app.models import AuditLog

        db_session.add(AuditLog(entity_type="devices", entity_id="x", action="UPDATE", details='=HYPERLINK("http://evil","клик")'))
        db_session.commit()
        sheet = load_workbook(build_audit_log_report(db_session, tmp_path)).active
        cells = [row[-1] for row in sheet.iter_rows(min_row=2)]
        formula = next(c for c in cells if isinstance(c.value, str) and c.value.startswith("="))
        assert formula.value == '=HYPERLINK("http://evil","клик")' and formula.data_type == "s" and formula.quotePrefix  # текст, не формула
        assert not any(c.data_type == "f" for c in cells)

    @pytest.mark.parametrize("value", ["\tcmd", "\rcmd", "=1+1", "+1", "-1+1", "@SUM(A1)"])
    def test_tab_and_carriage_return_are_formula_triggers_too(self, value):
        assert needs_text_guard(value)

    def test_ordinary_text_and_placeholder_are_untouched(self):
        assert not needs_text_guard("Обычный текст")
        assert not needs_text_guard("-")
        assert not needs_text_guard(42)

    def test_cleanup_removes_only_old_report_files(self, tmp_path):
        old_report, new_report, foreign = tmp_path / "old.xlsx", tmp_path / "new.xlsx", tmp_path / "notes.txt"
        old_docx = tmp_path / "old.docx"
        for path in (old_report, new_report, foreign, old_docx):
            path.write_bytes(b"x")
        long_ago = time.time() - 40 * 86400
        for path in (old_report, foreign, old_docx):
            os.utime(path, (long_ago, long_ago))

        removed = cleanup_old_reports(tmp_path, max_age_days=30)

        assert removed == 2
        assert not old_report.exists() and not old_docx.exists()
        assert new_report.exists() and foreign.exists()  # посторонние файлы не трогаем

    def test_cleanup_is_a_no_op_for_missing_directory_and_disabled_retention(self, tmp_path):
        assert cleanup_old_reports(tmp_path / "missing", max_age_days=30) == 0
        stale = tmp_path / "a.xlsx"
        stale.write_bytes(b"x")
        os.utime(stale, (0, 0))
        assert cleanup_old_reports(tmp_path, max_age_days=0) == 0 and stale.exists()

    def test_generating_a_report_cleans_up_stale_files(self, client, tmp_path, monkeypatch):
        from app.api import reports

        monkeypatch.setattr(reports, "REPORT_DIR", tmp_path)
        stale = tmp_path / "Старый_отчёт.xlsx"
        stale.write_bytes(b"x")
        os.utime(stale, (0, 0))
        assert client.post("/api/v1/reports/audit-log").status_code == 200
        assert not stale.exists()


# ---------------------------------------------------------------------------
# п. 12. Экспорт журнала аудита — потоковая запись
# ---------------------------------------------------------------------------
class TestStreamingAuditExport:
    def _seed(self, db_session, count: int) -> None:
        from app.models import AuditLog

        for i in range(count):
            db_session.add(AuditLog(entity_type="devices", entity_id=f"id-{i:03d}", action="UPDATE", details=f"Запись {i}",
                                    created_at=datetime(2026, 1, 1, 0, 0, i % 60) if i < 60 else datetime(2026, 1, 2, 0, 0, i % 60)))
        db_session.commit()

    def test_all_rows_survive_page_boundaries_without_duplicates(self, db_session, tmp_path, monkeypatch):
        from app.services import audit_export

        self._seed(db_session, 23)
        monkeypatch.setattr(audit_export, "EXPORT_PAGE_SIZE", 5)
        sheet = load_workbook(build_audit_log_report(db_session, tmp_path)).active
        ids = [row[4].value for row in sheet.iter_rows(min_row=2)]
        assert len(ids) == 23 and len(set(ids)) == 23

    def test_row_limit_is_still_a_ceiling(self, db_session, tmp_path, monkeypatch):
        from app.services import audit_export

        self._seed(db_session, 23)
        monkeypatch.setattr(audit_export, "EXPORT_PAGE_SIZE", 5)
        monkeypatch.setattr(audit_export, "EXPORT_ROW_LIMIT", 12)
        sheet = load_workbook(build_audit_log_report(db_session, tmp_path)).active
        assert sheet.max_row == 1 + 12

    def test_sheet_keeps_header_style_freeze_and_filter(self, db_session, tmp_path):
        self._seed(db_session, 3)
        sheet = load_workbook(build_audit_log_report(db_session, tmp_path)).active
        assert sheet.title == "Журнал аудита"
        assert sheet["A1"].font.bold and sheet["A1"].alignment.horizontal == "center"
        assert sheet.freeze_panes == "A2"
        assert sheet.auto_filter.ref == "A1:G4"
        assert sheet.column_dimensions["G"].width >= 40

    def test_empty_journal_gives_a_header_only_sheet(self, db_session, tmp_path):
        sheet = load_workbook(build_audit_log_report(db_session, tmp_path)).active
        assert sheet.max_row == 1 and sheet.auto_filter.ref is None

    def test_export_does_not_materialise_all_rows_at_once(self, db_session, tmp_path, monkeypatch):
        from app.services import audit_export

        self._seed(db_session, 30)
        monkeypatch.setattr(audit_export, "EXPORT_PAGE_SIZE", 10)
        largest: list[int] = []
        real = audit_export.list_resource

        def spy(*args, **kwargs):
            result = real(*args, **kwargs)
            largest.append(len(result["items"]))
            return result

        monkeypatch.setattr(audit_export, "list_resource", spy)
        build_audit_log_report(db_session, tmp_path)
        assert max(largest) <= 10 and len(largest) >= 3
