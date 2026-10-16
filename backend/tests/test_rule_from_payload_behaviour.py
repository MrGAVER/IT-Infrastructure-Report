"""Проверка и сборка правила согласования портов из тела запроса (services/port_sync_rules.py: rule_from_payload).

Фиксирует поведение до снижения сложности функции (код-ревью, п. 10; сложность 19) и дополняет
tests/test_port_sync_rules.py: там нарушения проверяются по одному и по подстроке сообщения, здесь —
точные тексты, порядок проверок (при нескольких нарушениях пользователь видит первое), значения
`null`, частичное обновление поверх `base`. Тесты написаны на прежнем коде и проходят без правок
после рефакторинга. Запуск: pytest backend/tests/test_rule_from_payload_behaviour.py -v
"""
from __future__ import annotations

from types import MappingProxyType

import pytest

from app.services.port_sync_rules import (
    DEFAULT_RULES_BY_CODE,
    EMPTY_TRUNK_RULE,
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    PRIORITY_LIMIT,
    RuleSpec,
    RuleValidationError,
    Side,
    rule_from_payload,
)


def _payload(**overrides):
    body = {"name": "Новое", "action": "auto", "apply": {"vlans": "copy"}}
    body.update(overrides)
    return body


def _rejected(payload, *, base: RuleSpec | None = None) -> str:
    with pytest.raises(RuleValidationError) as error:
        rule_from_payload(payload, base=base)
    return str(error.value)


@pytest.fixture()
def base() -> RuleSpec:
    return RuleSpec(
        name="Базовое", action="manual", description="было", enabled=False, priority=7,
        target=Side(mode="trunk", vlans="set"), source=Side(mode="access"), relation=Side(vlans="differs"),
        apply_role=True, apply_mode=False, vlan_policy="copy", code="custom_code", id="rule-1",
    )


class TestBody:
    @pytest.mark.parametrize("payload", [[], "правило", None, 5])
    def test_body_must_be_a_mapping(self, payload):
        assert _rejected(payload) == "Тело запроса должно быть объектом"

    def test_any_mapping_is_accepted(self):
        assert rule_from_payload(MappingProxyType(_payload())).name == "Новое"


class TestNameAndDescription:
    @pytest.mark.parametrize("name", [None, "", "   ", 5, ["Новое"]])
    def test_name_is_required(self, name):
        assert _rejected(_payload(name=name)) == "Название правила обязательно"

    def test_missing_name_is_required_without_base_and_kept_with_it(self, base):
        assert _rejected({"action": "manual"}) == "Название правила обязательно"
        assert rule_from_payload({"enabled": True}, base=base).name == "Базовое"

    def test_name_is_stripped_and_limited(self):
        assert rule_from_payload(_payload(name="  " + "н" * MAX_NAME_LENGTH + "  ")).name == "н" * MAX_NAME_LENGTH
        assert _rejected(_payload(name="н" * (MAX_NAME_LENGTH + 1))) == f"Название правила не длиннее {MAX_NAME_LENGTH} символов"

    def test_null_description_clears_it_and_text_is_kept_as_is(self, base):
        assert rule_from_payload(_payload(description=None)).description == ""
        assert rule_from_payload({"description": None}, base=base).description == ""
        assert rule_from_payload(_payload(description="  текст  ")).description == "  текст  "
        assert rule_from_payload({"enabled": True}, base=base).description == "было"

    @pytest.mark.parametrize("description", [5, ["x"], "д" * (MAX_DESCRIPTION_LENGTH + 1)])
    def test_description_must_be_a_short_string(self, description):
        assert _rejected(_payload(description=description)) == f"Описание должно быть строкой не длиннее {MAX_DESCRIPTION_LENGTH} символов"

    def test_description_at_the_limit_is_accepted(self):
        assert len(rule_from_payload(_payload(description="д" * MAX_DESCRIPTION_LENGTH)).description) == MAX_DESCRIPTION_LENGTH


class TestEnabledPriorityAction:
    @pytest.mark.parametrize("enabled", ["да", 1, 0, None, []])
    def test_enabled_must_be_a_boolean(self, enabled):
        assert _rejected(_payload(enabled=enabled)) == "Поле enabled должно быть true или false"

    @pytest.mark.parametrize("priority", [True, False, "1", 1.5, None, [1]])
    def test_priority_must_be_an_integer(self, priority):
        assert _rejected(_payload(priority=priority)) == f"Приоритет — целое число не больше {PRIORITY_LIMIT} по модулю"

    @pytest.mark.parametrize("priority", [PRIORITY_LIMIT + 1, -PRIORITY_LIMIT - 1])
    def test_priority_is_limited_by_absolute_value(self, priority):
        assert _rejected(_payload(priority=priority)) == f"Приоритет — целое число не больше {PRIORITY_LIMIT} по модулю"

    @pytest.mark.parametrize("priority", [PRIORITY_LIMIT, -PRIORITY_LIMIT, 0])
    def test_priority_boundaries_are_accepted(self, priority):
        assert rule_from_payload(_payload(priority=priority)).priority == priority

    @pytest.mark.parametrize("action", ["sometimes", None, 5, ["auto"], "AUTO"])
    def test_action_must_be_one_of_the_known_values(self, action):
        assert _rejected(_payload(action=action)) == "Действие: допустимые значения — auto, manual, ignore"

    def test_defaults_without_base_and_values_kept_with_it(self, base):
        rule = rule_from_payload({"name": "Н", "apply": {"role": True}})
        assert (rule.enabled, rule.priority, rule.action, rule.description) == (True, 100, "auto", "")
        kept = rule_from_payload({"name": "Новое имя"}, base=base)
        assert (kept.enabled, kept.priority, kept.action) == (False, 7, "manual")


class TestSides:
    def test_each_side_defaults_to_any_and_keeps_the_base_when_absent_or_null(self, base):
        fresh = rule_from_payload(_payload())
        assert (fresh.target, fresh.source, fresh.relation) == (Side(), Side(), Side())
        for payload in ({"enabled": True}, {"target": None, "source": None, "relation": None}):
            kept = rule_from_payload(payload, base=base)
            assert (kept.target, kept.source, kept.relation) == (base.target, base.source, base.relation)

    def test_object_is_merged_over_the_existing_side_field_by_field(self, base):
        updated = rule_from_payload({"target": {"vlans": "all"}, "source": {"role": "any"}, "relation": {"mode": "same"}}, base=base)
        assert updated.target == Side(mode="trunk", vlans="all")
        assert updated.source == Side(mode="access")
        assert updated.relation == Side(mode="same", vlans="differs")

    @pytest.mark.parametrize(("key", "label"), [("target", "Условия целевого порта"), ("source", "Условия порта-источника"), ("relation", "Отношение портов")])
    @pytest.mark.parametrize("raw", ["trunk", 5, ["role"], True])
    def test_side_must_be_an_object(self, key, label, raw):
        assert _rejected(_payload(**{key: raw})) == f"{label} должно быть объектом"

    @pytest.mark.parametrize(("key", "label"), [("target", "Условия целевого порта"), ("source", "Условия порта-источника"), ("relation", "Отношение портов")])
    def test_unknown_fields_are_listed_sorted(self, key, label):
        assert _rejected(_payload(**{key: {"size": 1, "colour": "red", "mode": "any"}})) == f"{label}: неизвестные поля — colour, size"

    def test_values_are_checked_against_the_vocabulary_of_the_side(self):
        assert _rejected(_payload(target={"role": "boss"})).startswith("Условия целевого порта.role: допустимые значения — any, ")
        assert _rejected(_payload(source={"mode": "hybrid"})) == "Условия порта-источника.mode: допустимые значения — any, access, trunk"
        assert _rejected(_payload(source={"vlans": "many"})) == "Условия порта-источника.vlans: допустимые значения — any, none, set, all"
        # у отношения словарь другой: any / same / differs — и «same» недопустимо в условии на порт
        assert _rejected(_payload(target={"mode": "same"})) == "Условия целевого порта.mode: допустимые значения — any, access, trunk"
        assert _rejected(_payload(relation={"role": "set"})) == "Отношение портов.role: допустимые значения — any, same, differs"
        assert rule_from_payload(_payload(relation={"role": "same", "mode": "differs", "vlans": "same"})).relation == Side("same", "differs", "same")

    def test_non_string_values_are_rejected_as_not_allowed(self):
        assert _rejected(_payload(target={"role": 5})).startswith("Условия целевого порта.role: допустимые значения")
        assert _rejected(_payload(target={"vlans": None})) == "Условия целевого порта.vlans: допустимые значения — any, none, set, all"


class TestApply:
    @pytest.mark.parametrize("apply", ["role", [], 5, False, 0, ""])
    def test_apply_must_be_an_object_when_present(self, apply):
        assert _rejected(_payload(apply=apply)) == "Поле apply должно быть объектом"

    def test_unknown_apply_fields_are_listed_sorted(self):
        assert _rejected(_payload(apply={"speed": True, "colour": 1, "vlans": "copy"})) == "apply: неизвестные поля — colour, speed"

    @pytest.mark.parametrize("flag", ["yes", 1, 0, None, []])
    def test_role_and_mode_flags_must_be_booleans(self, flag):
        assert _rejected(_payload(apply={"role": flag})) == "apply.role должно быть true или false"
        assert _rejected(_payload(apply={"mode": flag})) == "apply.mode должно быть true или false"

    def test_policy_must_be_a_known_value(self):
        assert _rejected(_payload(apply={"vlans": "merge"})) == "apply.vlans: допустимые значения — keep, copy, adapt, union, all"
        assert _rejected(_payload(apply={"vlans": None})) == "apply.vlans: допустимые значения — keep, copy, adapt, union, all"

    def test_null_or_missing_apply_keeps_the_base_values(self, base):
        for payload in ({"enabled": True}, {"apply": None}, {"apply": {}}):
            kept = rule_from_payload(payload, base=base)
            assert (kept.apply_role, kept.apply_mode, kept.vlan_policy) == (True, False, "copy")

    def test_apply_is_merged_over_the_base_field_by_field(self, base):
        updated = rule_from_payload({"apply": {"mode": True}}, base=base)
        assert (updated.apply_role, updated.apply_mode, updated.vlan_policy) == (True, True, "copy")
        updated = rule_from_payload({"apply": {"vlans": "all"}}, base=base)
        assert (updated.apply_role, updated.apply_mode, updated.vlan_policy) == (True, False, "all")

    def test_without_base_flags_default_to_false_and_policy_to_keep(self):
        rule = rule_from_payload({"name": "Н", "apply": {"role": True}})
        assert (rule.apply_role, rule.apply_mode, rule.vlan_policy) == (True, False, "keep")


class TestCrossFieldRules:
    def test_adapt_needs_mode_change(self):
        message = "Политика VLAN «по режиму» имеет смысл только вместе со сменой режима (apply.mode)"
        assert _rejected(_payload(apply={"vlans": "adapt"})) == message
        assert _rejected(_payload(apply={"vlans": "adapt", "role": True})) == message
        assert rule_from_payload(_payload(apply={"vlans": "adapt", "mode": True})).vlan_policy == "adapt"

    @pytest.mark.parametrize("apply", [{"role": True}, {"mode": True}, {"role": True, "mode": True}])
    def test_union_does_not_combine_with_role_or_mode_change(self, apply):
        message = "Политика VLAN «объединить» меняет оба порта сразу и не сочетается со сменой роли или режима: их порт берёт у соседа, а не оба сразу"
        assert _rejected(_payload(apply={"vlans": "union", **apply})) == message

    def test_union_alone_is_fine(self):
        assert rule_from_payload(_payload(apply={"vlans": "union"})).symmetric is True

    def test_auto_must_change_something(self):
        message = "Правило с действием «автоматически» должно что-то менять: роль, режим или VLAN"
        assert _rejected(_payload(apply={"vlans": "keep"})) == message
        assert _rejected({"name": "Н", "action": "auto"}) == message
        for apply in ({"role": True}, {"mode": True}, {"vlans": "copy"}, {"vlans": "all"}):
            assert rule_from_payload(_payload(apply=apply)).action == "auto"

    @pytest.mark.parametrize("action", ["manual", "ignore"])
    def test_manual_and_ignore_may_change_nothing(self, action):
        assert rule_from_payload({"name": "Н", "action": action}).action == action

    def test_cross_checks_use_the_values_merged_with_the_base(self, base):
        # у base apply_role=True: политика «объединить» поверх него недопустима, хотя в теле роль не упомянута
        assert "не сочетается" in _rejected({"apply": {"vlans": "union"}}, base=base)
        # а смена режима у base не включена — «по режиму» поверх него недопустима
        assert "по режиму" in _rejected({"apply": {"vlans": "adapt"}}, base=base)


class TestCheckOrder:
    """При нескольких нарушениях сообщение берётся у первого по порядку проверок."""

    @pytest.mark.parametrize(("payload", "fragment"), [
        ({"name": "", "description": 5, "enabled": "да", "priority": "1", "action": "x"}, "Название правила обязательно"),
        ({"name": "Н", "description": 5, "enabled": "да", "priority": "1", "action": "x"}, "Описание должно быть строкой"),
        ({"name": "Н", "enabled": "да", "priority": "1", "action": "x"}, "Поле enabled"),
        ({"name": "Н", "priority": "1", "action": "x", "target": "t"}, "Приоритет"),
        ({"name": "Н", "action": "x", "target": "t", "apply": "a"}, "Действие"),
        ({"name": "Н", "target": "t", "source": "s", "relation": "r", "apply": "a"}, "Условия целевого порта должно быть объектом"),
        ({"name": "Н", "target": {"role": "boss"}, "source": "s", "apply": "a"}, "Условия целевого порта.role"),
        ({"name": "Н", "source": "s", "relation": "r", "apply": "a"}, "Условия порта-источника должно быть объектом"),
        ({"name": "Н", "relation": "r", "apply": "a"}, "Отношение портов должно быть объектом"),
        ({"name": "Н", "relation": {"mode": "x"}, "apply": "a"}, "Отношение портов.mode"),
        ({"name": "Н", "apply": "a"}, "Поле apply должно быть объектом"),
        ({"name": "Н", "apply": {"speed": 1, "role": "x", "mode": "x", "vlans": "x"}}, "apply: неизвестные поля"),
        ({"name": "Н", "apply": {"role": "x", "mode": "x", "vlans": "x"}}, "apply.role"),
        ({"name": "Н", "apply": {"mode": "x", "vlans": "x"}}, "apply.mode"),
        ({"name": "Н", "apply": {"vlans": "x"}}, "apply.vlans"),
        ({"name": "Н", "apply": {"vlans": "adapt"}}, "по режиму"),
        ({"name": "Н", "apply": {"vlans": "union", "role": True}}, "не сочетается"),
    ])
    def test_first_violated_rule_wins(self, payload, fragment):
        assert fragment in _rejected(payload)

    def test_adapt_check_precedes_union_and_auto_checks(self):
        assert "по режиму" in _rejected(_payload(apply={"vlans": "adapt", "role": True}))
        assert "что-то менять" in _rejected(_payload(apply={"vlans": "keep"}, action="auto"))


class TestResult:
    def test_base_is_not_modified_and_service_fields_survive(self):
        original = DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]
        updated = rule_from_payload({"name": "Другое имя", "priority": 5, "code": "x", "builtin": False, "id": "y"}, base=original)
        assert updated is not original and original.name != "Другое имя"
        assert (updated.code, updated.id) == (original.code, original.id) and updated.priority == 5
        assert updated.target == original.target and updated.apply_mode == original.apply_mode

    def test_full_payload_is_assembled_into_every_field(self):
        rule = rule_from_payload({
            "name": " Полное ", "description": "д", "enabled": False, "priority": -3, "action": "auto",
            "target": {"role": "any", "mode": "trunk", "vlans": "none"}, "source": {"mode": "access", "vlans": "set"},
            "relation": {"role": "same", "mode": "differs", "vlans": "any"}, "apply": {"role": True, "mode": True, "vlans": "adapt"},
        })
        assert rule == RuleSpec(
            name="Полное", description="д", enabled=False, priority=-3, action="auto",
            target=Side(mode="trunk", vlans="none"), source=Side(mode="access", vlans="set"), relation=Side("same", "differs", "any"),
            apply_role=True, apply_mode=True, vlan_policy="adapt",
        )
