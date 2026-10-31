"""Реестр хуков generic CRUD (services/crud/hooks.py): таблица особого поведения, значения по умолчанию, порядок вызова.

generic.py не должен знать о конкретных моделях (принцип открытости/закрытости): особое поведение ресурса живёт в
`HOOKS`, а общий путь записи только вызывает хуки. Часть тестов — критерии приёмки этого требования в виде проверок
исходника generic.py, чтобы ветви `model is X` не вернулись.
Запуск: pytest backend/tests/test_crud_hooks.py -v
"""
from __future__ import annotations

import ast
from functools import cache
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest
from sqlalchemy import select

import app.services.crud.generic as generic
from app.models import AuditLog, Connection, DeviceInterface, DeviceStackMember, InformationSystem, ISProtocol, Manufacturer, OpenPort, PhysicalDevice, VirtualMachine, VLAN, VLANDomainDevice
from app.registry import MODEL_MAP
from app.services.crud.hooks import HOOKS, ResourceHooks, hooks_for
from app.services.serialization import serialize

API = "/api/v1/resources"
HOOK_NAMES = {f.name for f in fields(ResourceHooks)}

# Какие хуки переопределены у каких моделей. Тест намеренно дублирует таблицу: новая запись в HOOKS — осознанное
# решение, и список ниже правится вместе с ней.
EXPECTED_OVERRIDES: dict[type, set[str]] = {
    AuditLog: {"ordering"},
    DeviceInterface: {"ordering", "enrich_rows"},
    PhysicalDevice: {"enrich_rows"},
    Connection: {"enrich_rows"},
    InformationSystem: {"enrich_rows"},
    OpenPort: {"enrich_rows", "validate_create", "validate_update", "to_dict"},
    ISProtocol: {"validate_create", "validate_update"},
    VirtualMachine: {"prepare", "apply_derived"},
    VLAN: {"after_create", "after_update"},
    VLANDomainDevice: {"after_create"},
    DeviceStackMember: {"after_create"},
}


@cache
def _generic_tree() -> ast.Module:
    return ast.parse(Path(generic.__file__).read_text(encoding="utf-8"))


def _order_by_sql(model: type, columns: tuple) -> str:
    """Хвост `ORDER BY ...` запроса к модели — так порядок сравнивается независимо от вида элементов (атрибут, desc())."""
    sql = str(select(model).order_by(*columns))
    return sql[sql.index("ORDER BY"):]


def _overridden(hooks: ResourceHooks) -> set[str]:
    default = ResourceHooks()
    return {name for name in HOOK_NAMES if getattr(hooks, name) is not getattr(default, name)}


class TestHooksTable:
    def test_registry_lists_exactly_the_models_with_special_behaviour(self):
        assert {model: _overridden(hooks) for model, hooks in HOOKS.items()} == EXPECTED_OVERRIDES

    def test_every_registered_model_is_a_real_resource(self):
        # Запись для модели, которой нет в MODEL_MAP, — мёртвый код: её хуки никогда не вызовутся.
        assert set(HOOKS) <= set(MODEL_MAP.values())

    @pytest.mark.parametrize("model", list(EXPECTED_OVERRIDES), ids=lambda m: m.__name__)
    def test_hooks_for_returns_the_registered_entry(self, model):
        assert hooks_for(model) is HOOKS[model]


class TestDefaults:
    def test_model_without_special_behaviour_gets_the_default_hooks(self):
        assert Manufacturer not in HOOKS
        assert hooks_for(Manufacturer) == ResourceHooks()
        assert hooks_for(Manufacturer) is hooks_for(object)  # один общий экземпляр, а не новый на каждый вызов

    def test_default_hooks_do_nothing(self, db_session):
        hooks = ResourceHooks()
        data = {"name": "Dell"}
        obj = Manufacturer(name="Dell")
        assert hooks.prepare(data, db_session) is None and data == {"name": "Dell"}
        assert hooks.validate_create(data, db_session) is None
        assert hooks.validate_update(data, {"name": "HP"}, db_session, "id-1") is None
        assert hooks.apply_derived(obj, data) is None
        assert hooks.after_create(obj, db_session) is None
        assert hooks.after_update(obj, data, {"name": "HP"}, db_session) == []

    def test_default_ordering_is_creation_time_then_id(self):
        assert _order_by_sql(Manufacturer, ResourceHooks().ordering(Manufacturer)) == "ORDER BY manufacturers.created_at, manufacturers.id"

    def test_default_serialization_is_plain_serialize(self, client, db_session):
        created = client.post(f"{API}/manufacturers", json={"name": "Plain"}).json()
        obj = db_session.get(Manufacturer, created["id"])
        hooks = ResourceHooks()
        assert hooks.to_dict(obj, db_session) == serialize(obj) == created
        assert hooks.enrich_rows([obj], db_session) == [created]

    def test_hooks_are_immutable(self):
        with pytest.raises(FrozenInstanceError):
            ResourceHooks().prepare = lambda data, session: None  # type: ignore[misc]


class TestSpecialOrdering:
    def test_audit_log_is_newest_first_with_id_tiebreak(self):
        assert _order_by_sql(AuditLog, hooks_for(AuditLog).ordering(AuditLog)) == "ORDER BY audit_log.created_at DESC, audit_log.id DESC"

    def test_interfaces_follow_the_user_defined_port_order(self):
        sql = _order_by_sql(DeviceInterface, hooks_for(DeviceInterface).ordering(DeviceInterface))
        assert [part.split(".")[-1] for part in sql.removeprefix("ORDER BY ").split(", ")] == ["sort_order", "created_at", "id"]


class TestGenericIsModelAgnostic:
    """Критерии приёмки П-7: в generic.py нет ветвлений по модели и почти нет импортов моделей."""

    def test_no_identity_comparison_with_a_class(self):
        offenders = [
            node.lineno
            for node in ast.walk(_generic_tree())
            if isinstance(node, ast.Compare)
            and any(isinstance(op, (ast.Is, ast.IsNot)) for op in node.ops)
            and any(isinstance(operand, ast.Name) and operand.id[:1].isupper() for operand in [node.left, *node.comparators])
        ]
        assert not offenders, f"в generic.py появилось ветвление по классу модели (строки {offenders}) — вынесите его в crud/hooks.py"

    def test_models_imported_at_most_five(self):
        imported = [alias.name for node in ast.walk(_generic_tree()) if isinstance(node, ast.ImportFrom) and node.module == "models" and node.level == 3 for alias in node.names]
        assert len(imported) <= 5, f"generic.py импортирует {len(imported)} моделей: {imported}"


class _Recorder:
    """Подменяет Manufacturer особыми хуками и пишет порядок вызовов (вместе с вызовами audit из generic)."""

    def __init__(self, monkeypatch, *, notes: list[str] | None = None):
        self.calls: list[str] = []
        self.args: dict[str, tuple] = {}
        self.audits: list[str] = []
        real_audit = generic.audit

        def audit(session, entity_type, entity_id, action, details="", actor=None):
            self.calls.append("audit")
            self.audits.append(details)
            real_audit(session, entity_type, entity_id, action, details, actor)

        def step(name: str, result=None):
            def hook(*args):
                self.calls.append(name)
                self.args[name] = args
                return result

            return hook

        monkeypatch.setattr(generic, "audit", audit)
        hooks = ResourceHooks(
            prepare=step("prepare"),
            validate_create=step("validate_create"),
            validate_update=step("validate_update"),
            apply_derived=step("apply_derived"),
            after_create=step("after_create"),
            after_update=step("after_update", notes or []),
            to_dict=lambda obj, session: self.calls.append("to_dict") or {"id": obj.id, "from_hook": True},
        )
        monkeypatch.setitem(HOOKS, Manufacturer, hooks)


class TestHooksAreCalledByGenericCrud:
    """Доказывает расширяемость: поведение ресурса меняется записью в HOOKS, без правки generic.py."""

    def test_create_calls_hooks_in_documented_order_and_returns_to_dict(self, client, monkeypatch):
        recorder = _Recorder(monkeypatch)
        response = client.post(f"{API}/manufacturers", json={"name": "Создан с хуками"})
        assert response.status_code == 201, response.text
        assert recorder.calls == ["prepare", "validate_create", "after_create", "audit", "to_dict"]
        assert response.json()["from_hook"] is True
        assert recorder.args["prepare"][0] == {"name": "Создан с хуками"}  # prepare получает данные новой записи

    def test_update_calls_hooks_in_documented_order(self, client, monkeypatch):
        created = client.post(f"{API}/manufacturers", json={"name": "До правки"}).json()
        recorder = _Recorder(monkeypatch)
        response = client.put(f"{API}/manufacturers/{created['id']}", json={"name": "После правки"})
        assert response.status_code == 200, response.text
        assert recorder.calls == ["prepare", "validate_update", "apply_derived", "after_update", "audit", "to_dict"]
        proposed, before, _session, item_id = recorder.args["validate_update"]
        assert proposed["name"] == "После правки" and before["name"] == "До правки" and item_id == created["id"]
        assert recorder.args["after_update"][1] == {"name": "После правки"}  # payload запроса
        assert recorder.args["after_update"][2]["name"] == "До правки"  # значения до правки

    def test_after_update_notes_are_audited_right_after_the_main_record(self, client, monkeypatch):
        created = client.post(f"{API}/manufacturers", json={"name": "Для заметок"}).json()
        recorder = _Recorder(monkeypatch, notes=["заметка 1", "заметка 2"])
        assert client.put(f"{API}/manufacturers/{created['id']}", json={"name": "Для заметок 2"}).status_code == 200
        assert len(recorder.audits) == 3
        assert recorder.audits[1:] == ["заметка 1", "заметка 2"]
        assert "заметка" not in recorder.audits[0]
