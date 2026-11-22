"""Разбор одного варианта решения auto — services/port_sync_reconcile.py: _plan_target.

Фиксирует поведение до снижения сложности функции (код-ревью, п. 10; сложность 13) и дополняет
tests/test_port_sync_reconcile.py, который проверяет согласование целиком через HTTP: часть ветвей
(«Изменений нет», «Все VLAN» без VLAN у устройства, повторная проверка access) движок до `_plan_target`
не пропускает, поэтому здесь функция вызывается напрямую на объектах в памяти, без БД. Тесты написаны на
прежнем коде и проходят без правок после рефакторинга.

Запуск: pytest backend/tests/test_plan_target_behaviour.py -v
"""

from __future__ import annotations

import pytest

from app.models import Connection, DeviceInterface, InterfaceGroup, VLAN
from app.services.port_config import PORT_ROLE_LABELS, PortRole
from app.services.port_sync_reconcile import _plan_target, _Port, _TargetPlan
from app.services.port_sync_rules import APPLY_TO_DESTINATION, APPLY_TO_SOURCE, Changes, Option, PortFacts, RuleSpec

VLANS = {f"v{n}": VLAN(id=f"v{n}", vlan_id=n, name=f"vlan{n}") for n in (10, 20, 30)}
RULE = RuleSpec(name="Правило для проверки")


def _role(before: PortRole, after: PortRole) -> str:
    return f"роль {PORT_ROLE_LABELS[before]} → {PORT_ROLE_LABELS[after]}"


def _port(
    port_id: str,
    *,
    mode: str = "trunk",
    role: PortRole = PortRole.DATA,
    numbers: tuple[int, ...] = (),
    allowed: tuple[int | str, ...] = (),
    all_vlans: bool = False,
    group: InterfaceGroup | None = None,
    vlan_ids: set[str] | None = None,
) -> _Port:
    """allowed — VLAN устройства порта: номера из VLANS или произвольные id (например, записи вне справочника)."""
    assigned = {f"v{n}" for n in numbers} if vlan_ids is None else vlan_ids
    allowed_ids = {f"v{a}" if isinstance(a, int) else a for a in allowed}
    facts = PortFacts(role=role, mode=mode, vlans=frozenset(numbers), all_vlans=all_vlans)
    return _Port(iface=DeviceInterface(id=port_id, name=f"Gi0/{port_id}"), device=None, group=group, vlan_ids=assigned, allowed_ids=allowed_ids, facts=facts)


def _plan(changes: Changes, target: _Port, source: _Port, *, apply_to: str = APPLY_TO_SOURCE, claimed: set[str] | None = None) -> _TargetPlan:
    """Подключение a (источник) — b (назначение); apply_to выбирает, какой из них целевой порт."""
    a, b = (target, source) if apply_to == APPLY_TO_SOURCE else (source, target)
    connection = Connection(id="c1", source_interface_id=a.iface.id, destination_interface_id=b.iface.id)
    return _plan_with(connection, apply_to, changes, {a.iface.id: a, b.iface.id: b}, claimed)


def _plan_with(connection: Connection, apply_to: str, changes: Changes, ports: dict[str, _Port], claimed: set[str] | None) -> _TargetPlan:
    return _plan_target(Option(apply_to, changes), RULE, connection, ports, VLANS, set() if claimed is None else claimed)


def _group(name: str = "Магистраль", vlan_mode: str | None = "trunk") -> InterfaceGroup:
    return InterfaceGroup(id="g1", name=name, vlan_mode=vlan_mode)


class TestTargetSelection:
    def test_source_option_changes_the_connection_source_port(self):
        target, other = _port("a", allowed=(10,)), _port("b", numbers=(10,))
        plan = _plan(Changes(vlans=frozenset({10})), target, other, apply_to=APPLY_TO_SOURCE)
        assert plan.apply_to == APPLY_TO_SOURCE and plan.port is target
        assert plan.planned is not None and plan.planned.port is target

    def test_destination_option_changes_the_connection_destination_port(self):
        other, target = _port("a", numbers=(10,)), _port("b", allowed=(10,))
        plan = _plan(Changes(vlans=frozenset({10})), target, other, apply_to=APPLY_TO_DESTINATION)
        assert plan.apply_to == APPLY_TO_DESTINATION and plan.port is target
        assert plan.planned is not None and plan.planned.port is target

    def test_planned_record_carries_the_connection_rule_and_what_to_write(self):
        target, other = _port("a", mode="trunk", role=PortRole.NONE, allowed=(10, 20)), _port("b", numbers=(10, 20))
        connection = Connection(id="c1", source_interface_id="a", destination_interface_id="b")
        plan = _plan_with(connection, APPLY_TO_SOURCE, Changes(role=PortRole.DATA, mode="access", vlans=frozenset({10})), {"a": target, "b": other}, None)
        planned = plan.planned
        assert planned is not None
        assert (planned.connection, planned.rule, planned.role, planned.mode, planned.vlan_ids, planned.all_vlans) == (
            connection,
            RULE,
            PortRole.DATA,
            "access",
            ["v10"],
            False,
        )
        assert planned.description == f"{_role(PortRole.NONE, PortRole.DATA)}; режим trunk → access; VLAN нет → 10"


class TestVlanSet:
    def test_wanted_vlans_are_resolved_to_the_target_devices_records_in_number_order(self):
        plan = _plan(Changes(vlans=frozenset({20, 10})), _port("a", allowed=(10, 20, 30)), _port("b", numbers=(10, 20)))
        assert plan.blocked is None and plan.warnings == [] and plan.diverges is False
        assert plan.planned is not None and plan.planned.vlan_ids == ["v10", "v20"]
        assert plan.changes == {"role": None, "mode": None, "vlans": {"from": [], "to": [10, 20], "skipped": []}}
        assert plan.planned.description == "VLAN нет → 10, 20"

    def test_vlans_the_device_does_not_have_are_skipped_with_a_warning(self):
        plan = _plan(Changes(vlans=frozenset({10, 20})), _port("a", allowed=(10,)), _port("b", numbers=(10, 20)))
        assert plan.blocked is None
        assert plan.planned is not None and plan.planned.vlan_ids == ["v10"]
        assert plan.changes["vlans"] == {"from": [], "to": [10], "skipped": [20]}
        assert plan.warnings == ["Не назначены VLAN, которых нет у устройства порта: 20"]

    def test_when_no_vlan_is_available_the_change_is_blocked_and_shows_what_was_skipped(self):
        plan = _plan(Changes(vlans=frozenset({10, 20})), _port("a", allowed=(30,)), _port("b", numbers=(10, 20)))
        assert plan.blocked == "Ни один из VLAN соседнего порта не доступен устройству этого порта — добавьте их в «VLAN устройства»"
        assert plan.planned is None and plan.warnings == []  # при блокировке предупреждений нет
        assert plan.changes == {"role": None, "mode": None, "vlans": {"from": [], "to": [], "skipped": [10, 20]}}

    def test_same_set_means_nothing_to_change(self):
        plan = _plan(Changes(vlans=frozenset({10})), _port("a", numbers=(10,), allowed=(10, 20)), _port("b", numbers=(10,)))
        assert plan.blocked == "Изменений нет" and plan.planned is None
        assert plan.changes == {"role": None, "mode": None, "vlans": None}

    def test_unchanged_set_does_not_block_when_role_or_mode_changes_too(self):
        target = _port("a", numbers=(10,), allowed=(10,), role=PortRole.NONE)
        plan = _plan(Changes(role=PortRole.DATA, vlans=frozenset({10})), target, _port("b", numbers=(10,)))
        assert plan.blocked is None and plan.planned is not None
        assert plan.planned.vlan_ids is None and plan.planned.role is PortRole.DATA
        assert plan.changes == {"role": {"from": "none", "to": "data"}, "mode": None, "vlans": None}
        plan = _plan(Changes(mode="access", vlans=frozenset({10})), _port("a", numbers=(10,), allowed=(10,)), _port("b", numbers=(10,)))
        assert plan.blocked is None and plan.planned is not None and plan.planned.vlan_ids is None and plan.planned.mode == "access"

    def test_skipped_vlans_are_shown_even_when_nothing_else_changes_for_the_port(self):
        target = _port("a", numbers=(10,), allowed=(10,), role=PortRole.NONE)
        plan = _plan(Changes(role=PortRole.DATA, vlans=frozenset({10, 20})), target, _port("b", numbers=(10, 20)))
        assert plan.blocked is None
        assert plan.changes["vlans"] == {"from": [10], "to": [10], "skipped": [20]}
        assert plan.warnings == ["Не назначены VLAN, которых нет у устройства порта: 20"]

    def test_clearing_the_set_is_a_change(self):
        plan = _plan(Changes(vlans=frozenset()), _port("a", numbers=(10,), allowed=(10,)), _port("b"))
        assert plan.blocked is None and plan.planned is not None and plan.planned.vlan_ids == []
        assert plan.changes["vlans"] == {"from": [10], "to": [], "skipped": []}
        assert plan.planned.description == "VLAN 10 → нет"

    def test_already_assigned_record_is_preferred_among_records_with_the_same_number(self):
        twin = VLAN(id="v10-twin", vlan_id=10, name="двойник")
        VLANS["v10-twin"] = twin
        try:
            target = _port("a", allowed=(10, "v10-twin"), vlan_ids={"v10-twin"}, numbers=())
            plan = _plan(Changes(vlans=frozenset({10, 20})), target, _port("b", numbers=(10, 20)))
        finally:
            del VLANS["v10-twin"]
        assert plan.planned is not None and plan.planned.vlan_ids == ["v10-twin"]


class TestAllVlans:
    def test_target_gets_the_flag_and_all_vlans_of_its_device(self):
        plan = _plan(Changes(all_vlans=True), _port("a", allowed=(10, 20)), _port("b", numbers=(10, 20), all_vlans=True))
        assert plan.blocked is None and plan.warnings == [] and plan.diverges is False
        assert plan.planned is not None and plan.planned.all_vlans is True and plan.planned.vlan_ids == ["v10", "v20"]
        assert plan.changes["vlans"] == {"from": [], "to": [10, 20], "skipped": []}
        assert plan.planned.description == "VLAN нет → все VLAN устройства: 10, 20"

    def test_the_flag_is_written_even_when_the_same_vlans_are_already_chosen_by_hand(self):
        target = _port("a", numbers=(10, 20), allowed=(10, 20))
        plan = _plan(Changes(all_vlans=True), target, _port("b", numbers=(10, 20), all_vlans=True))
        assert plan.blocked is None and plan.planned is not None and plan.planned.vlan_ids == ["v10", "v20"]
        assert plan.changes["vlans"] == {"from": [10, 20], "to": [10, 20], "skipped": []}

    def test_nothing_is_written_when_the_flag_and_the_whole_set_are_already_there(self):
        # Текст в этом случае общий для «нет VLAN, которые можно назначить» — закреплено как есть.
        target = _port("a", numbers=(10, 20), allowed=(10, 20), all_vlans=True)
        plan = _plan(Changes(all_vlans=True), target, _port("b", numbers=(10, 20), all_vlans=True))
        assert plan.blocked == "У устройства этого порта нет VLAN, которые можно назначить, — добавьте их в «VLAN устройства»"
        assert plan.planned is None and plan.changes["vlans"] is None

    def test_device_without_vlans_and_neighbor_without_vlans_has_nothing_to_assign(self):
        plan = _plan(Changes(all_vlans=True), _port("a"), _port("b", all_vlans=True))
        assert plan.blocked == "У устройства этого порта нет VLAN, которые можно назначить, — добавьте их в «VLAN устройства»"

    def test_device_without_vlans_but_neighbor_has_some_names_the_skipped_ones(self):
        plan = _plan(Changes(all_vlans=True), _port("a"), _port("b", numbers=(10, 20), all_vlans=True))
        assert plan.blocked == "Ни один из VLAN соседнего порта не доступен устройству этого порта — добавьте их в «VLAN устройства»"
        assert plan.changes["vlans"] == {"from": [], "to": [], "skipped": [10, 20]}

    def test_neighbor_vlans_missing_on_the_device_are_skipped_and_the_sets_diverge(self):
        plan = _plan(Changes(all_vlans=True), _port("a", allowed=(10, 20)), _port("b", numbers=(10, 20, 30), all_vlans=True))
        assert plan.blocked is None and plan.diverges is True
        assert plan.changes["vlans"] == {"from": [], "to": [10, 20], "skipped": [30]}
        assert plan.warnings == ["Не назначены VLAN, которых нет у устройства порта: 30"]

    def test_vlans_the_neighbor_lacks_are_listed_in_a_warning_and_the_sets_diverge(self):
        plan = _plan(Changes(all_vlans=True), _port("a", allowed=(10, 20, 30)), _port("b", numbers=(10,), all_vlans=True))
        assert plan.blocked is None and plan.diverges is True
        assert plan.warnings == ["Порту назначаются все VLAN его устройства; у соседнего порта нет VLAN: 20, 30"]
        assert plan.changes["vlans"] == {"from": [], "to": [10, 20, 30], "skipped": []}

    def test_both_warnings_come_in_a_fixed_order(self):
        plan = _plan(Changes(all_vlans=True), _port("a", allowed=(10, 20)), _port("b", numbers=(10, 30), all_vlans=True))
        assert plan.warnings == [
            "Не назначены VLAN, которых нет у устройства порта: 30",
            "Порту назначаются все VLAN его устройства; у соседнего порта нет VLAN: 20",
        ]

    def test_records_missing_from_the_catalog_are_written_but_not_counted_as_numbers(self):
        plan = _plan(Changes(all_vlans=True), _port("a", allowed=(10, "призрак")), _port("b", numbers=(10,), all_vlans=True))
        assert plan.planned is not None and plan.planned.vlan_ids == ["v10", "призрак"]
        assert plan.changes["vlans"] == {"from": [], "to": [10], "skipped": []} and plan.diverges is False

    def test_role_change_goes_ahead_when_there_is_nothing_to_assign(self):
        plan = _plan(Changes(role=PortRole.DATA, all_vlans=True), _port("a", role=PortRole.NONE), _port("b", all_vlans=True))
        assert plan.blocked is None and plan.planned is not None and plan.planned.vlan_ids is None and plan.planned.all_vlans is True


class TestBlocking:
    def test_violation_found_by_the_rules_comes_first(self):
        target = _port("a", allowed=(10,), group=_group())
        plan = _plan(Changes(vlans=frozenset({10}), violation="Нарушение правила"), target, _port("b", numbers=(10,)), claimed={"a"})
        assert plan.blocked == "Нарушение правила" and plan.planned is None

    @pytest.mark.parametrize("changes", [Changes(mode="access"), Changes(vlans=frozenset({10})), Changes(all_vlans=True)])
    def test_group_that_sets_mode_and_vlans_blocks_individual_changes(self, changes):
        plan = _plan(changes, _port("a", allowed=(10,), group=_group("Магистраль")), _port("b", numbers=(10,), all_vlans=True), claimed={"a"})
        assert plan.blocked == "Порт входит в группу «Магистраль», которая задаёт режим и VLAN, — измените группу"
        assert plan.planned is None

    @pytest.mark.parametrize("group", [None, _group(vlan_mode=None), _group(vlan_mode="")])
    def test_group_without_a_mode_does_not_block(self, group):
        plan = _plan(Changes(vlans=frozenset({10})), _port("a", allowed=(10,), group=group), _port("b", numbers=(10,)))
        assert plan.blocked is None

    def test_role_only_change_is_not_blocked_by_the_group(self):
        plan = _plan(Changes(role=PortRole.DATA), _port("a", role=PortRole.NONE, group=_group()), _port("b"))
        assert plan.blocked is None and plan.planned is not None

    def test_access_port_cannot_receive_several_vlans(self):
        message = "В режиме access у порта может быть не более одного VLAN"
        assert _plan(Changes(vlans=frozenset({10, 20})), _port("a", mode="access", allowed=(10, 20)), _port("b", numbers=(10, 20))).blocked == message
        assert (
            _plan(Changes(mode="access", vlans=frozenset({10, 20})), _port("a", mode="trunk", allowed=(10, 20)), _port("b", numbers=(10, 20))).blocked
            == message
        )

    def test_access_port_may_receive_one_vlan_and_a_trunk_may_receive_several(self):
        assert _plan(Changes(vlans=frozenset({10})), _port("a", mode="access", allowed=(10, 20)), _port("b", numbers=(10,))).blocked is None
        assert (
            _plan(Changes(mode="trunk", vlans=frozenset({10, 20})), _port("a", mode="access", allowed=(10, 20)), _port("b", numbers=(10, 20))).blocked is None
        )

    def test_access_check_counts_vlans_left_after_skipping(self):
        plan = _plan(Changes(vlans=frozenset({10, 20})), _port("a", mode="access", allowed=(10,)), _port("b", numbers=(10, 20)))
        assert plan.blocked is None and plan.planned is not None and plan.planned.vlan_ids == ["v10"]

    def test_port_taken_by_another_connection_of_the_plan_is_blocked(self):
        claimed = {"a"}
        plan = _plan(Changes(vlans=frozenset({10})), _port("a", allowed=(10,)), _port("b", numbers=(10,)), claimed=claimed)
        assert plan.blocked == "Порт уже изменяется другим подключением этого же плана" and plan.planned is None
        assert claimed == {"a"}  # `claimed` функция только читает

    def test_other_ports_claimed_do_not_matter(self):
        assert _plan(Changes(vlans=frozenset({10})), _port("a", allowed=(10,)), _port("b", numbers=(10,)), claimed={"b", "x"}).blocked is None

    def test_reasons_are_checked_in_a_fixed_order(self):
        grouped = _port("a", allowed=(10, 20), mode="access", group=_group("Г"))
        assert "Порт входит в группу" in (_plan(Changes(vlans=frozenset({10, 20})), grouped, _port("b", numbers=(10, 20)), claimed={"a"}).blocked or "")
        plain = _port("a", allowed=(10, 20), mode="access")
        assert (
            _plan(Changes(vlans=frozenset({10, 20})), plain, _port("b", numbers=(10, 20)), claimed={"a"}).blocked
            == "В режиме access у порта может быть не более одного VLAN"
        )
        assert (
            _plan(Changes(vlans=frozenset({10})), _port("a", allowed=(10,), numbers=(10,)), _port("b", numbers=(10,)), claimed={"a"}).blocked == "Изменений нет"
        )
        assert (
            _plan(Changes(vlans=frozenset({20})), _port("a", allowed=(20,)), _port("b", numbers=(20,)), claimed={"a"}).blocked
            == "Порт уже изменяется другим подключением этого же плана"
        )


class TestChangesView:
    def test_role_and_mode_are_described_as_from_to_pairs(self):
        plan = _plan(Changes(role=PortRole.MANAGEMENT_DATA, mode="access"), _port("a", mode="trunk", role=PortRole.NONE), _port("b"))
        assert plan.changes == {"role": {"from": "none", "to": "management_data"}, "mode": {"from": "trunk", "to": "access"}, "vlans": None}
        assert plan.planned is not None
        assert plan.planned.description == f"{_role(PortRole.NONE, PortRole.MANAGEMENT_DATA)}; режим trunk → access"

    def test_unchanged_facets_are_none_and_an_empty_change_has_no_description(self):
        plan = _plan(Changes(), _port("a"), _port("b"))
        assert plan.blocked is None and plan.changes == {"role": None, "mode": None, "vlans": None}
        assert plan.planned is not None and plan.planned.description == "" and plan.planned.vlan_ids is None

    def test_description_lists_role_mode_and_vlans_in_that_order(self):
        plan = _plan(
            Changes(role=PortRole.DATA, mode="access", vlans=frozenset({10})),
            _port("a", role=PortRole.NONE, mode="trunk", allowed=(10,)),
            _port("b", numbers=(10,)),
        )
        assert plan.planned is not None
        assert plan.planned.description == f"{_role(PortRole.NONE, PortRole.DATA)}; режим trunk → access; VLAN нет → 10"

    def test_blocked_plan_still_describes_the_changes_but_has_no_planned_record(self):
        plan = _plan(Changes(mode="access", role=PortRole.DATA), _port("a", role=PortRole.NONE, group=_group()), _port("b"))
        # роль и режим меняются только вместе с VLAN/режимом — группа блокирует именно режим
        assert plan.blocked is not None and plan.planned is None
        assert plan.changes["role"] == {"from": "none", "to": "data"} and plan.changes["mode"] == {"from": "trunk", "to": "access"}
