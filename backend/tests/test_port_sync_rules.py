"""Юнит-тесты чистого движка правил согласования данных порта (app/services/port_sync_rules.py).

Запуск: pytest backend/tests/test_port_sync_rules.py -v
"""
from __future__ import annotations

from dataclasses import replace
from itertools import product

import pytest

from app.services.port_config import PortConfig, PortRole, config_differences
from app.services.port_sync_rules import (
    DEFAULT_RULES,
    DEFAULT_RULES_BY_CODE,
    EMPTY_TRUNK_RULE,
    MODE_MATCH_RULE,
    ROLE_MATCH_RULE,
    VLANS_MATCH_RULE,
    APPLY_TO_DESTINATION,
    APPLY_TO_SOURCE,
    Changes,
    Outcome,
    PortFacts,
    RuleSpec,
    RuleValidationError,
    Side,
    active_rules,
    compute_changes,
    decide,
    flags_from_role,
    rule_from_payload,
    rule_matches,
    rules_equal_ignoring_state,
    sort_rules,
)


def facts(role: PortRole = PortRole.DATA, mode: str = "trunk", vlans: tuple[int, ...] = (), *, all_vlans: bool = False) -> PortFacts:
    return PortFacts(role, mode, frozenset(vlans), all_vlans)


RULES = active_rules(DEFAULT_RULES)


# --- состояние VLAN и условия ------------------------------------------------------------------

def test_vlan_state_distinguishes_none_set_and_all():
    assert facts().vlan_state == "none"
    assert facts(vlans=(10,)).vlan_state == "set"
    assert facts(vlans=(10, 20), all_vlans=True).vlan_state == "all"
    assert facts(all_vlans=True).vlan_state == "none"  # «все» без единого VLAN — всё равно «не назначены»


@pytest.mark.parametrize(
    ("condition", "port", "expected"),
    [
        (Side(), facts(), True),
        (Side(role="data"), facts(PortRole.DATA), True),
        (Side(role="data"), facts(PortRole.MANAGEMENT), False),
        (Side(mode="trunk"), facts(mode="access"), False),
        (Side(vlans="none"), facts(), True),
        (Side(vlans="none"), facts(vlans=(10,)), False),
        (Side(vlans="set"), facts(vlans=(10,)), True),
        (Side(vlans="set"), facts(vlans=(10, 20), all_vlans=True), True),  # «все VLAN» — тоже «назначены»
        (Side(vlans="set"), facts(), False),
        (Side(vlans="all"), facts(vlans=(10, 20), all_vlans=True), True),
        (Side(vlans="all"), facts(vlans=(10,)), False),
    ],
)
def test_side_conditions(condition, port, expected):
    rule = RuleSpec(name="r", target=condition)
    assert rule_matches(rule, port, facts()) is expected


@pytest.mark.parametrize(
    ("relation", "a", "b", "expected"),
    [
        (Side(role="same"), facts(PortRole.DATA), facts(PortRole.DATA), True),
        (Side(role="same"), facts(PortRole.DATA), facts(PortRole.MANAGEMENT), False),
        (Side(role="differs"), facts(PortRole.DATA), facts(PortRole.MANAGEMENT), True),
        (Side(mode="differs"), facts(mode="trunk"), facts(mode="access"), True),
        (Side(vlans="differs"), facts(vlans=(10,)), facts(vlans=(10,)), False),
        (Side(vlans="same"), facts(vlans=(10, 20)), facts(vlans=(20, 10)), True),
        (Side(role="differs", mode="differs"), facts(PortRole.DATA, "trunk"), facts(PortRole.MANAGEMENT, "trunk"), False),  # все отношения должны выполняться
    ],
)
def test_relations(relation, a, b, expected):
    assert rule_matches(RuleSpec(name="r", relation=relation), a, b) is expected


# --- главное требование: trunk без VLAN получает VLAN соседа -------------------------------------

def test_empty_trunk_takes_the_vlans_of_a_trunk_neighbor():
    empty, filled = facts(vlans=()), facts(vlans=(10, 20))

    forward = decide(RULES, empty, filled)  # empty — порт-источник подключения
    backward = decide(RULES, filled, empty)  # empty — порт назначения

    assert forward.outcome is Outcome.AUTO and forward.rule.code == EMPTY_TRUNK_RULE
    assert [o.apply_to for o in forward.options] == [APPLY_TO_SOURCE]
    assert forward.options[0].changes == Changes(vlans=frozenset({10, 20}))
    assert backward.outcome is Outcome.AUTO
    assert [o.apply_to for o in backward.options] == [APPLY_TO_DESTINATION]


def test_empty_trunk_also_takes_all_vlans_of_the_neighbor():
    decision = decide(RULES, facts(), facts(vlans=(10, 20, 30), all_vlans=True))

    assert decision.outcome is Outcome.AUTO
    assert decision.options[0].changes.vlans == frozenset({10, 20, 30})


@pytest.mark.parametrize(
    ("port", "neighbor"),
    [
        (facts(vlans=(5,)), facts(vlans=(10,))),       # у порта уже есть VLAN — это обычное расхождение VLAN, не «пустой trunk»
        (facts(), facts()),                            # у соседа тоже пусто — брать нечего
        (facts(mode="access"), facts(vlans=(10,))),    # порт не trunk
        (facts(), facts(mode="access", vlans=(10,))),  # сосед не trunk
    ],
)
def test_empty_trunk_rule_does_not_apply_outside_its_conditions(port, neighbor):
    decision = decide([DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]], port, neighbor)

    assert decision.outcome is Outcome.NONE


def test_empty_trunk_rule_keeps_role_and_mode_when_they_already_match():
    changes = decide(RULES, facts(PortRole.MANAGEMENT), facts(PortRole.DATA, vlans=(10,))).options[0].changes

    assert changes.role is None and changes.mode is None  # роль правило не трогает


def test_empty_trunk_rule_wins_over_the_manual_rules_below_and_leaves_the_rest_for_them():
    """Пара: у порта пустой trunk и другая роль. Сначала автоматически согласуются VLAN, роль остаётся
    следующему проходу — первое подходящее правило решает."""
    port, neighbor = facts(PortRole.MANAGEMENT, vlans=()), facts(PortRole.DATA, vlans=(10,))

    first = decide(RULES, port, neighbor)
    after = decide(RULES, replace(port, vlans=frozenset({10})), neighbor)

    assert first.outcome is Outcome.AUTO and first.rule.code == EMPTY_TRUNK_RULE
    assert after.outcome is Outcome.MANUAL and after.rule.code == ROLE_MATCH_RULE


# --- «все текущие правила»: стандартные правила повторяют сверку дашборда ---------------------------

def test_default_rules_cover_exactly_the_discrepancies_found_by_the_dashboard_check():
    """Для каждой пары конфигураций: расхождение по роли / режиму / VLAN (services/port_config.py) есть
    ровно тогда, когда стандартные правила дают решение (auto или manual). Нет расхождения — решения нет."""
    roles, modes, vlan_sets = tuple(PortRole), ("access", "trunk"), ((), (10,), (10, 20))
    singles = [facts(r, m, v, all_vlans=len(v) == 2) for r, m, v in product(roles, modes, vlan_sets)]
    checked = 0
    for a, b in product(singles, repeat=2):
        differs = bool(config_differences(PortConfig(a.role, a.mode, a.vlans), PortConfig(b.role, b.mode, b.vlans)))
        decision = decide(RULES, a, b)
        assert (decision.outcome is not Outcome.NONE) == differs, (a, b, decision)
        checked += 1
    assert checked == (4 * 2 * 3) ** 2


def test_each_manual_default_names_one_kind_of_discrepancy():
    base = facts(PortRole.DATA, "trunk", (10,))

    assert decide(RULES, replace(base, role=PortRole.MANAGEMENT), base).rule.code == ROLE_MATCH_RULE
    assert decide(RULES, replace(base, mode="access"), base).rule.code == MODE_MATCH_RULE
    assert decide(RULES, replace(base, vlans=frozenset({20})), base).rule.code == VLANS_MATCH_RULE


def test_manual_rule_offers_both_directions_with_the_changes_of_each():
    decision = decide(RULES, facts(PortRole.MANAGEMENT, vlans=(10,)), facts(PortRole.DATA, vlans=(10,)))

    assert decision.outcome is Outcome.MANUAL
    by_target = {o.apply_to: o.changes for o in decision.options}
    assert by_target[APPLY_TO_SOURCE] == Changes(role=PortRole.DATA)
    assert by_target[APPLY_TO_DESTINATION] == Changes(role=PortRole.MANAGEMENT)


def test_mode_rule_adapts_vlans_when_the_target_becomes_access():
    decision = decide(RULES, facts(mode="trunk", vlans=(30, 10, 20)), facts(mode="access", vlans=(30, 10, 20)))
    to_access = next(o for o in decision.options if o.apply_to == APPLY_TO_SOURCE).changes

    assert to_access.mode == "access"
    assert to_access.vlans == frozenset({10})  # остаётся VLAN с наименьшим номером


def test_mode_rule_keeps_assigned_vlans_when_the_target_becomes_trunk():
    decision = decide(RULES, facts(mode="trunk", vlans=(10,)), facts(mode="access", vlans=(10,)))
    to_trunk = next(o for o in decision.options if o.apply_to == APPLY_TO_DESTINATION).changes

    assert to_trunk.mode == "trunk" and to_trunk.vlans is None  # VLAN не придумываются


# --- проверка приоритета, действий и пустых изменений -------------------------------------------

def test_rules_are_checked_by_priority_not_by_list_order():
    wide = RuleSpec(name="wide", action="manual", priority=50)
    narrow = RuleSpec(name="narrow", action="manual", priority=5)

    assert decide(sort_rules([wide, narrow]), facts(), facts()).rule.name == "narrow"


def test_disabled_rules_do_not_take_part():
    disabled = replace(DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE], enabled=False)
    rules = active_rules([disabled, *[r for r in DEFAULT_RULES if r.code != EMPTY_TRUNK_RULE]])

    decision = decide(rules, facts(vlans=()), facts(vlans=(10,)))

    assert decision.rule.code == VLANS_MATCH_RULE  # без правила про пустой trunk работает обычное расхождение VLAN


def test_ignore_rule_stops_the_check_for_matching_pairs():
    ignore = RuleSpec(name="серверы не трогаем", action="ignore", priority=1, target=Side(role="management"))

    decision = decide(active_rules([ignore, *DEFAULT_RULES]), facts(PortRole.MANAGEMENT, vlans=()), facts(vlans=(10,)))

    assert decision.outcome is Outcome.IGNORED and decision.rule.name == "серверы не трогаем"


def test_auto_rule_that_would_change_nothing_is_skipped_in_favour_of_the_next_rule():
    noop = RuleSpec(name="роль уже совпадает", action="auto", priority=1, apply_role=True)  # меняет только роль
    rules = active_rules([noop, DEFAULT_RULES_BY_CODE[VLANS_MATCH_RULE]])

    decision = decide(rules, facts(PortRole.DATA, vlans=(10,)), facts(PortRole.DATA, vlans=(20,)))

    assert decision.rule.code == VLANS_MATCH_RULE


def test_auto_rule_applicable_in_both_directions_falls_back_to_manual():
    symmetric = RuleSpec(name="симметричное", action="auto", relation=Side(role="differs"), apply_role=True)

    decision = decide([symmetric], facts(PortRole.MANAGEMENT), facts(PortRole.DATA))

    assert decision.outcome is Outcome.MANUAL
    assert "обе стороны" in decision.note
    assert len(decision.options) == 2


def test_decision_for_matching_ports_is_none():
    assert decide(RULES, facts(vlans=(10,)), facts(vlans=(10,))).outcome is Outcome.NONE


# --- расчёт изменений ---------------------------------------------------------------------------

def test_compute_changes_reports_only_real_differences():
    rule = RuleSpec(name="r", apply_role=True, apply_mode=True, vlan_policy="copy")

    same = compute_changes(rule, facts(PortRole.DATA, "trunk", (10,)), facts(PortRole.DATA, "trunk", (10,)))
    different = compute_changes(rule, facts(PortRole.NONE, "access", (5,)), facts(PortRole.DATA, "trunk", (10, 20)))

    assert same.is_empty
    assert different == Changes(PortRole.DATA, "trunk", frozenset({10, 20}))


def test_copying_several_vlans_into_an_access_port_is_a_violation():
    rule = RuleSpec(name="r", vlan_policy="copy")

    changes = compute_changes(rule, facts(mode="access", vlans=(5,)), facts(mode="trunk", vlans=(10, 20)))

    assert changes.violation and "access" in changes.violation


def test_switching_to_access_with_a_trunk_vlan_list_copied_is_a_violation_but_one_vlan_is_fine():
    rule = RuleSpec(name="r", apply_mode=True, vlan_policy="copy")

    assert compute_changes(rule, facts(mode="trunk"), facts(mode="access", vlans=(10,))).violation is None
    assert compute_changes(rule, facts(mode="trunk"), facts(mode="access", vlans=(10, 20))).violation


def test_flags_from_role_round_trips_every_role():
    from app.services.port_config import role_from_flags

    for role in PortRole:
        assert role_from_flags(*flags_from_role(role)) is role


# --- проверка введённого правила ----------------------------------------------------------------

def _payload(**overrides):
    base = {"name": "Новое", "action": "auto", "apply": {"vlans": "copy"}}
    base.update(overrides)
    return base


def test_valid_payload_builds_a_rule_with_defaults_for_the_missing_parts():
    rule = rule_from_payload(_payload(target={"mode": "trunk", "vlans": "none"}, description="  описание "))

    assert rule.name == "Новое" and rule.description == "  описание "
    assert rule.target == Side(mode="trunk", vlans="none") and rule.source == Side()
    assert rule.vlan_policy == "copy" and rule.apply_role is False and rule.enabled is True


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (_payload(name="  "), "Название"),
        (_payload(name="x" * 201), "не длиннее"),
        (_payload(action="sometimes"), "Действие"),
        (_payload(target={"role": "boss"}), "Условия целевого порта.role"),
        (_payload(source={"vlans": "many"}), "Условия порта-источника.vlans"),
        (_payload(relation={"mode": "any_of"}), "Отношение портов.mode"),
        (_payload(target={"colour": "red"}), "неизвестные поля"),
        (_payload(target="trunk"), "должно быть объектом"),
        (_payload(apply={"vlans": "merge"}), "apply.vlans"),
        (_payload(apply={"role": "yes"}), "apply.role"),
        (_payload(apply={"speed": True}), "неизвестные поля"),
        (_payload(enabled="да"), "enabled"),
        (_payload(priority="1"), "Приоритет"),
        (_payload(priority=True), "Приоритет"),
        (_payload(priority=10**9), "Приоритет"),
        (_payload(description=5), "Описание"),
        (_payload(apply={"vlans": "adapt"}), "по режиму"),
        (_payload(apply={"vlans": "keep"}), "что-то менять"),
        ([], "объектом"),
    ],
)
def test_invalid_payloads_are_rejected_with_a_user_facing_message(payload, message):
    with pytest.raises(RuleValidationError) as error:
        rule_from_payload(payload)

    assert message in str(error.value)


def test_manual_and_ignore_rules_may_change_nothing():
    assert rule_from_payload(_payload(action="manual", apply={"vlans": "keep"})).action == "manual"
    assert rule_from_payload(_payload(action="ignore", apply={"vlans": "keep"})).action == "ignore"


def test_partial_update_changes_only_the_given_fields():
    base = DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]

    updated = rule_from_payload({"enabled": False, "source": {"vlans": "all"}}, base=base)

    assert updated.enabled is False and updated.source == Side(mode="trunk", vlans="all")  # mode источника сохранился
    assert updated.target == base.target and updated.apply_mode is True and updated.vlan_policy == "copy"
    assert updated.code == EMPTY_TRUNK_RULE


def test_service_fields_in_the_payload_are_ignored():
    base = DEFAULT_RULES_BY_CODE[ROLE_MATCH_RULE]

    updated = rule_from_payload({"code": "hacked", "builtin": False, "id": "x", "name": "Переименовано"}, base=base)

    assert updated.code == ROLE_MATCH_RULE and updated.id == base.id and updated.name == "Переименовано"
    assert rule_from_payload({"code": "hacked", **_payload()}).code is None  # пользовательское правило не выдать за стандартное


# --- стандартные правила ------------------------------------------------------------------------

def test_default_rules_have_unique_codes_names_and_priorities():
    assert len({r.code for r in DEFAULT_RULES}) == len(DEFAULT_RULES) == 4
    assert len({r.name for r in DEFAULT_RULES}) == len(DEFAULT_RULES)
    assert len({r.priority for r in DEFAULT_RULES}) == len(DEFAULT_RULES)
    assert all(r.code and r.enabled and r.description for r in DEFAULT_RULES)


def test_every_default_rule_passes_the_same_validation_as_a_user_rule():
    for rule in DEFAULT_RULES:
        payload = {
            "name": rule.name, "description": rule.description, "action": rule.action, "priority": rule.priority,
            "target": vars(rule.target), "source": vars(rule.source), "relation": vars(rule.relation),
            "apply": {"role": rule.apply_role, "mode": rule.apply_mode, "vlans": rule.vlan_policy},
        }
        assert rules_equal_ignoring_state(rule_from_payload(payload), rule)


def test_new_standard_rule_matches_the_requested_definition():
    rule = DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]

    assert rule.action == "auto"
    assert (rule.target.mode, rule.target.vlans) == ("trunk", "none")      # на порту trunk совсем без VLAN
    assert (rule.source.mode, rule.source.vlans) == ("trunk", "set")       # у соседа trunk с VLAN (или «все VLAN»)
    assert rule.apply_mode and rule.vlan_policy == "copy" and not rule.apply_role
    assert rule.priority == min(r.priority for r in DEFAULT_RULES)         # конкретное правило проверяется раньше общих


def test_rules_equal_ignoring_state_ignores_priority_and_enabled_only():
    base = DEFAULT_RULES_BY_CODE[ROLE_MATCH_RULE]

    assert rules_equal_ignoring_state(base, replace(base, enabled=False, priority=999))
    assert not rules_equal_ignoring_state(base, replace(base, action="auto"))
    assert not rules_equal_ignoring_state(base, replace(base, description="иначе"))
