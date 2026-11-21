"""Юнит-тесты чистого движка правил согласования данных порта (app/services/port_sync_rules.py).

Запуск: pytest backend/tests/test_port_sync_rules.py -v
"""

from __future__ import annotations

from dataclasses import replace
from itertools import product

import pytest

from app.services.port_config import PortConfig, PortRole, config_differences
from app.services.port_sync_rules import (
    ALL_VLANS_BOTH_RULE,
    ALL_VLANS_RULE,
    DEFAULT_RULES,
    DEFAULT_RULES_BY_CODE,
    EMPTY_TRUNK_RULE,
    MODE_MATCH_RULE,
    ROLE_MATCH_RULE,
    TRUNK_VLANS_UNION_RULE,
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
    # само правило «пустой trunk»: «Все VLAN» соседа для него — просто назначенные VLAN, берутся их номера
    decision = decide([DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]], facts(), facts(vlans=(10, 20, 30), all_vlans=True))

    assert decision.outcome is Outcome.AUTO
    assert decision.options[0].changes.vlans == frozenset({10, 20, 30})
    # а в общей цепочке пустой trunk рядом с «Все VLAN» получает «Все VLAN» (правило проверяется раньше)
    chain = decide(RULES, facts(), facts(vlans=(10, 20, 30), all_vlans=True))
    assert chain.outcome is Outcome.AUTO and chain.rule.code == ALL_VLANS_RULE


@pytest.mark.parametrize(
    ("port", "neighbor"),
    [
        (facts(vlans=(5,)), facts(vlans=(10,))),  # у порта уже есть VLAN — это обычное расхождение VLAN, не «пустой trunk»
        (facts(), facts()),  # у соседа тоже пусто — брать нечего
        (facts(mode="access"), facts(vlans=(10,))),  # порт не trunk
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
    # Наборы VLAN у trunk-пары различаются автоматически решаемым правилом, у access-пары — человеком.
    assert decide(RULES, replace(base, vlans=frozenset({20})), base).rule.code == TRUNK_VLANS_UNION_RULE
    access = facts(PortRole.DATA, "access", (10,))
    manual = decide(RULES, replace(access, vlans=frozenset({20})), access)
    assert (manual.rule.code, manual.outcome) == (VLANS_MATCH_RULE, Outcome.MANUAL)


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
    assert len({r.code for r in DEFAULT_RULES}) == len(DEFAULT_RULES) == 7
    assert len({r.name for r in DEFAULT_RULES}) == len(DEFAULT_RULES)
    assert len({r.priority for r in DEFAULT_RULES}) == len(DEFAULT_RULES)
    assert all(r.code and r.enabled and r.description for r in DEFAULT_RULES)


def test_every_default_rule_passes_the_same_validation_as_a_user_rule():
    for rule in DEFAULT_RULES:
        payload = {
            "name": rule.name,
            "description": rule.description,
            "action": rule.action,
            "priority": rule.priority,
            "target": vars(rule.target),
            "source": vars(rule.source),
            "relation": vars(rule.relation),
            "apply": {"role": rule.apply_role, "mode": rule.apply_mode, "vlans": rule.vlan_policy},
        }
        assert rules_equal_ignoring_state(rule_from_payload(payload), rule)


def test_new_standard_rule_matches_the_requested_definition():
    rule = DEFAULT_RULES_BY_CODE[EMPTY_TRUNK_RULE]

    assert rule.action == "auto"
    assert (rule.target.mode, rule.target.vlans) == ("trunk", "none")  # на порту trunk совсем без VLAN
    assert (rule.source.mode, rule.source.vlans) == ("trunk", "set")  # у соседа trunk с VLAN (или «все VLAN»)
    assert rule.apply_mode and rule.vlan_policy == "copy" and not rule.apply_role
    others = [r for r in DEFAULT_RULES if r.code not in (EMPTY_TRUNK_RULE, ALL_VLANS_RULE, ALL_VLANS_BOTH_RULE)]
    assert rule.priority < min(r.priority for r in others)  # конкретное правило проверяется раньше общих


def test_rules_equal_ignoring_state_ignores_priority_and_enabled_only():
    base = DEFAULT_RULES_BY_CODE[ROLE_MATCH_RULE]

    assert rules_equal_ignoring_state(base, replace(base, enabled=False, priority=999))
    assert not rules_equal_ignoring_state(base, replace(base, action="auto"))
    assert not rules_equal_ignoring_state(base, replace(base, description="иначе"))


# --- политика VLAN «объединить» (trunk с разными наборами VLAN) ---------------------------------


def _union(decision):
    """Что получает каждый порт пары: {apply_to: итоговый набор VLAN или None}."""
    return {o.apply_to: o.changes.vlans for o in decision.options}


def test_trunk_ports_with_different_vlan_sets_are_merged_automatically_on_both_ports():
    decision = decide(RULES, facts(vlans=(10, 20)), facts(vlans=(20, 30)))

    assert decision.outcome is Outcome.AUTO and decision.rule.code == TRUNK_VLANS_UNION_RULE
    assert _union(decision) == {APPLY_TO_SOURCE: frozenset({10, 20, 30}), APPLY_TO_DESTINATION: frozenset({10, 20, 30})}
    assert all(o.changes.role is None and o.changes.mode is None and o.changes.violation is None for o in decision.options)


def test_merge_changes_only_the_port_that_lacks_vlans_when_one_set_contains_the_other():
    decision = decide(RULES, facts(vlans=(10, 20, 30)), facts(vlans=(10,)))

    assert decision.outcome is Outcome.AUTO
    assert _union(decision) == {APPLY_TO_DESTINATION: frozenset({10, 20, 30})}  # порт-источник уже несёт всё


def test_merge_never_removes_a_vlan():
    rule = DEFAULT_RULES_BY_CODE[TRUNK_VLANS_UNION_RULE]

    changes = compute_changes(rule, facts(vlans=(10, 20)), facts(vlans=(20, 30)))

    assert changes.vlans == frozenset({10, 20, 30}) and changes.vlans >= frozenset({10, 20})
    assert compute_changes(rule, facts(vlans=(10, 20, 30)), facts(vlans=(20,))).is_empty


def test_merge_treats_all_vlans_state_as_assigned():
    only_merge = [DEFAULT_RULES_BY_CODE[TRUNK_VLANS_UNION_RULE]]

    decision = decide(only_merge, facts(vlans=(10, 20), all_vlans=True), facts(vlans=(30,)))

    assert decision.outcome is Outcome.AUTO and decision.rule.code == TRUNK_VLANS_UNION_RULE


def test_merge_does_not_apply_to_equal_sets_access_ports_or_empty_trunk():
    assert decide(RULES, facts(vlans=(10, 20)), facts(vlans=(10, 20))).outcome is Outcome.NONE
    assert decide(RULES, facts(PortRole.DATA, "access", (10,)), facts(PortRole.DATA, "access", (20,))).rule.code == VLANS_MATCH_RULE
    assert decide(RULES, facts(vlans=()), facts(vlans=(10,))).rule.code == EMPTY_TRUNK_RULE  # пустой trunk — своё правило, оно раньше


def test_merge_rule_comes_after_empty_trunk_and_before_the_manual_rules():
    order = [r.code for r in RULES]

    assert order.index(EMPTY_TRUNK_RULE) < order.index(TRUNK_VLANS_UNION_RULE) < order.index(ROLE_MATCH_RULE)
    assert len({r.priority for r in DEFAULT_RULES}) == len(DEFAULT_RULES)  # без совпадений — порядок не зависит от id


def test_merge_policy_is_symmetric_and_validated():
    assert RuleSpec(name="r", vlan_policy="union").symmetric and not RuleSpec(name="r", vlan_policy="copy").symmetric
    rule = rule_from_payload({"name": "Объединять", "action": "auto", "apply": {"vlans": "union"}})
    assert rule.vlan_policy == "union" and not rule.apply_role and not rule.apply_mode
    for apply in ({"vlans": "union", "mode": True}, {"vlans": "union", "role": True}):
        with pytest.raises(RuleValidationError, match="объединить"):
            rule_from_payload({"name": "Плохое", "action": "auto", "apply": apply})


def test_user_merge_rule_applies_to_both_ports_without_manual_direction():
    rule = rule_from_payload({"name": "Объединять любые", "action": "auto", "relation": {"vlans": "differs"}, "apply": {"vlans": "union"}})

    decision = decide([rule], facts(PortRole.DATA, "access", (10,)), facts(PortRole.DATA, "access", (20,)))

    assert decision.outcome is Outcome.AUTO and len(decision.options) == 2
    assert all(o.changes.violation for o in decision.options)  # в access по-прежнему не более одного VLAN — применить нельзя


# --- «Все VLAN» на порту → «Все VLAN» у соседа ----------------------------------------------------


def all_port(*vlans: int, mode: str = "trunk") -> PortFacts:
    return facts(PortRole.DATA, mode, vlans, all_vlans=True)


def test_all_vlans_standard_rule_matches_the_requested_definition():
    rule = DEFAULT_RULES_BY_CODE[ALL_VLANS_RULE]

    assert rule.action == "auto" and rule.vlan_policy == "all"
    assert (rule.source.mode, rule.source.vlans) == ("trunk", "all")  # на порту установлено «Все VLAN»
    assert (rule.target.mode, rule.target.vlans) == ("trunk", "any")  # сосед тоже trunk; уже «все» — менять нечего
    assert not rule.apply_role and not rule.apply_mode and not rule.symmetric
    assert rule.priority == min(r.priority for r in DEFAULT_RULES)  # конкретнее «пустого trunk» и «объединения» — проверяется первым


@pytest.mark.parametrize("neighbor", [facts(vlans=(10,)), facts(vlans=()), facts(vlans=(10, 20), all_vlans=False)])
def test_all_vlans_port_makes_the_neighbor_all_vlans(neighbor):
    decision = decide(RULES, neighbor, all_port(10, 20, 30))  # a — сосед, b — порт с «Все VLAN»

    assert decision.outcome is Outcome.AUTO and decision.rule.code == ALL_VLANS_RULE
    (option,) = decision.options
    assert option.apply_to == APPLY_TO_SOURCE  # меняется a, у b берётся состояние «Все VLAN»
    assert option.changes.all_vlans and option.changes.vlans is None
    assert option.changes.role is None and option.changes.mode is None and option.changes.violation is None


def test_all_vlans_rule_works_in_both_orientations():
    decision = decide(RULES, all_port(10, 20), facts(vlans=(10,)))

    assert decision.rule.code == ALL_VLANS_RULE
    assert [o.apply_to for o in decision.options] == [APPLY_TO_DESTINATION]


def test_all_vlans_rule_does_nothing_when_both_ports_are_already_all_vlans():
    decision = decide(RULES, all_port(10, 20), all_port(10, 20))

    assert decision.outcome is Outcome.NONE  # менять нечего — правило неприменимо, расхождения нет
    assert compute_changes(DEFAULT_RULES_BY_CODE[ALL_VLANS_RULE], all_port(10, 20), all_port(10, 20, 30)).is_empty


def test_all_vlans_rule_does_not_touch_access_ports_or_ports_without_all_vlans():
    # сосед в access: «Все VLAN» в access невозможно — расхождение режимов остаётся за ручным правилом
    assert decide(RULES, facts(PortRole.DATA, "access", (10,)), all_port(10, 20)).rule.code == MODE_MATCH_RULE
    # у источника просто набор VLAN, не «все» — как раньше, наборы объединяются
    assert decide(RULES, facts(vlans=(10,)), facts(vlans=(20, 30))).rule.code == TRUNK_VLANS_UNION_RULE
    # access-источник с единственным VLAN, даже если он «все» устройства, правило не запускает
    assert decide([DEFAULT_RULES_BY_CODE[ALL_VLANS_RULE]], facts(vlans=(10,)), all_port(10, mode="access")).outcome is Outcome.NONE


def test_all_vlans_rule_takes_precedence_over_empty_trunk_and_merge_rules():
    assert decide(RULES, facts(vlans=()), all_port(10, 20)).rule.code == ALL_VLANS_RULE  # не «пустой trunk получает VLAN соседа»
    assert decide(RULES, facts(vlans=(30,)), all_port(10, 20)).rule.code == ALL_VLANS_RULE  # не «объединение наборов»
    # а у соседа без «Все VLAN» поведение прежнее
    assert decide(RULES, facts(vlans=()), facts(vlans=(10, 20))).rule.code == EMPTY_TRUNK_RULE


def test_all_vlans_policy_is_never_valid_for_an_access_result():
    rule = rule_from_payload({"name": "Все VLAN везде", "action": "auto", "apply": {"vlans": "all"}})

    changes = compute_changes(rule, facts(PortRole.DATA, "access", (10,)), all_port(10, 20))

    assert changes.all_vlans and changes.violation  # в access не более одного VLAN — применить нельзя
    assert compute_changes(replace(rule, apply_mode=True), facts(PortRole.DATA, "trunk", (10,)), all_port(10, 20, mode="access")).violation


def test_all_vlans_policy_is_accepted_by_validation_and_unknown_policy_is_not():
    rule = rule_from_payload({"name": "Все VLAN соседу", "action": "auto", "apply": {"vlans": "all"}})

    assert rule.vlan_policy == "all" and not rule.symmetric
    with pytest.raises(RuleValidationError, match="apply.vlans"):
        rule_from_payload({"name": "Плохое", "action": "auto", "apply": {"vlans": "everything"}})


# --- «Все VLAN» на обоих портах, но номера различаются: пару не трогаем ------------------------------


def test_all_vlans_on_both_ports_standard_rule_matches_the_requested_definition():
    rule = DEFAULT_RULES_BY_CODE[ALL_VLANS_BOTH_RULE]

    assert rule.action == "ignore"
    assert (rule.target.mode, rule.target.vlans) == ("trunk", "all") and (rule.source.mode, rule.source.vlans) == ("trunk", "all")
    # Роль и режим не затрагиваются: правило не должно скрывать расхождение роли — оно решается правилом ниже.
    assert (rule.relation.role, rule.relation.vlans) == ("same", "differs")
    all_rule = DEFAULT_RULES_BY_CODE[ALL_VLANS_RULE]
    others = [r for r in DEFAULT_RULES if r.code not in (ALL_VLANS_RULE, ALL_VLANS_BOTH_RULE)]
    assert all_rule.priority < rule.priority < min(r.priority for r in others)  # после «Все VLAN → Все VLAN», раньше остальных


@pytest.mark.parametrize(
    "a, b",
    [
        (all_port(10, 20, 30), all_port(10, 20)),  # у устройства соседа нет VLAN 30
        (all_port(10, 20), all_port(10, 20, 30)),  # то же в другую сторону
        (all_port(10, 20), all_port(30, 40)),  # наборы вообще не пересекаются
    ],
)
def test_all_vlans_on_both_ports_with_different_numbers_is_left_alone(a, b):
    decision = decide(RULES, a, b)

    assert decision.outcome is Outcome.IGNORED and decision.rule.code == ALL_VLANS_BOTH_RULE
    assert decision.options == ()  # без попыток «объединить» или «взять набор» — менять нечего: это разные VLAN устройств


def test_all_vlans_on_both_ports_does_not_hide_a_role_difference_or_other_cases():
    management = facts(PortRole.MANAGEMENT, "trunk", (10, 20, 30), all_vlans=True)

    assert decide(RULES, all_port(10, 20), management).rule.code != ALL_VLANS_BOTH_RULE  # роль различается — не «не трогать»
    assert decide(RULES, facts(vlans=(10,)), all_port(10, 20)).rule.code == ALL_VLANS_RULE  # у соседа не «все» — как прежде
    assert decide(RULES, all_port(10, 20), all_port(10, 20)).outcome is Outcome.NONE  # одинаковые наборы — расхождения нет
    assert decide(RULES, all_port(10, 20), all_port(10, 20, mode="access")).rule.code != ALL_VLANS_BOTH_RULE  # не trunk
