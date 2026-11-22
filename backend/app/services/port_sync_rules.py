"""Правила автоматического согласования данных порта с портом на другом конце подключения.

Что решает модуль. Два порта, соединённые активным подключением, должны быть настроены согласованно:
одинаковые роль (управление / передача данных), режим (access / trunk) и набор VLAN. Когда это не так,
правило отвечает на два вопроса: КАКОЙ порт менять (направление) и ЧТО в нём менять (роль, режим,
VLAN). Правила редактируются пользователем (в том числе стандартные), поэтому живут в БД
(services/port_sync_store.py); этот модуль — чистая логика без обращения к БД: условия, выбор
правила, расчёт изменений, проверка введённого правила и перечень стандартных правил.

Правило — шаблон над УПОРЯДОЧЕННОЙ парой «целевой порт ← порт-источник»:
  * условия на целевой порт и на порт-источник (роль, режим, состояние VLAN);
  * отношение между ними (роль / режим / набор VLAN: «совпадают», «различаются», «любое»);
  * действие: `auto` (направление определяет сама пара условий, применяется после предпросмотра и
    подтверждения), `manual` (расхождение известного вида, но направление выбирает человек) или
    `ignore` (пару не трогать — останавливает проверку правил ниже);
  * что целевой порт берёт у источника: роль, режим, VLAN (`vlan_policy`).

Политика VLAN `union` («объединить») особая: она симметрична. Оба порта линии должны нести один и
тот же набор VLAN, и ни один VLAN при этом не снимается, поэтому направление выбирать не нужно —
каждый порт получает объединение наборов обоих. Так автоматически решаются расхождения VLAN на
trunk-портах (стандартное правило `trunk_vlans_union`). Роль и режим направленные (их «берёт»
один порт у другого), поэтому с `union` в одном правиле не сочетаются.

Политика VLAN `all` («все VLAN») — состояние, а не набор номеров: целевой порт получает ВСЕ VLAN,
доступные его устройству (как галочка «Все VLAN» в форме устройства), независимо от того, какие номера у
порта-источника. Так автоматически решается «если на порту „Все VLAN“, то и у соседа „Все VLAN“»
(стандартное правило `all_vlans_to_neighbor`). Что именно запишется, зависит от VLAN устройства целевого
порта, поэтому это считает слой согласования (services/port_sync_reconcile.py); здесь правило лишь
отвечает, нужно ли порту «Все VLAN» (`Changes.all_vlans`): порту ставится признак «Все VLAN», а набор — все VLAN его устройства.

Правила проверяются по возрастанию `priority`; решает первое подходящее. Для каждой пары
проверяются обе ориентации (A ← B и B ← A). `auto` подходит, только если подходит ровно одна
ориентация, — иначе направление неоднозначно и решение остаётся за человеком. Исключение —
симметричное правило (`union`): подходят обе ориентации, и применяется каждая, где есть что менять. `auto`-правило, которое
для этой пары ничего бы не изменило, считается неприменимым и проверка идёт дальше.

Состояние VLAN порта: `none` — VLAN не назначены совсем; `set` — назначен хотя бы один (в том числе
когда назначены ВСЕ); `all` — назначены все VLAN, доступные устройству («Все VLAN» в форме
устройства — не флаг, а именно это состояние, см. DeviceInterfacesEditor.vue).

Всегда действующие ограничения (не настраиваются, это целостность данных, а не политика):
  * в режиме access у порта не более одного VLAN;
  * порт, режим и VLAN которого задаёт группа портов, по режиму и VLAN не меняется (группа —
    источник истины), роль группы не задают;
  * сверяются только активные подключения с расхождением, которое не одобрено.

Пример:
    rules = [spec for spec in DEFAULT_RULES]
    empty = PortFacts(PortRole.DATA, "trunk", frozenset())
    full = PortFacts(PortRole.DATA, "trunk", frozenset({10, 20}))
    decide(rules, empty, full).outcome   # -> Outcome.AUTO, пустому trunk будут применены VLAN соседа
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from .port_config import DEFAULT_VLAN_MODE, VLAN_MODE_ACCESS, VLAN_MODE_TRUNK, PortRole

# --- перечни допустимых значений ----------------------------------------------------------------

ACTIONS = ("auto", "manual", "ignore")
ROLE_CONDITIONS = ("any", *(r.value for r in PortRole))
MODE_CONDITIONS = ("any", VLAN_MODE_ACCESS, VLAN_MODE_TRUNK)
VLAN_CONDITIONS = ("any", "none", "set", "all")
RELATIONS = ("any", "same", "differs")
VLAN_POLICIES = ("keep", "copy", "adapt", "union", "all")

MAX_NAME_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
PRIORITY_LIMIT = 1_000_000

ROLE_FLAGS: dict[PortRole, tuple[bool, bool]] = {
    PortRole.NONE: (False, False),
    PortRole.MANAGEMENT: (True, False),
    PortRole.DATA: (False, True),
    PortRole.MANAGEMENT_DATA: (True, True),
}


def flags_from_role(role: PortRole) -> tuple[bool, bool]:
    """(is_management, is_data_transfer) для роли — обратное к port_config.role_from_flags."""
    return ROLE_FLAGS[role]


# --- данные порта и правила --------------------------------------------------------------------


@dataclass(frozen=True)
class PortFacts:
    """Данные порта, по которым проверяются условия правил. VLAN — номера (802.1Q-теги), как и в
    сверке подключений (services/port_config.py). all_vlans — сохраняемый признак порта «Все VLAN»
    (models.DeviceInterface.all_vlans), а не вывод из набора VLAN."""

    role: PortRole = PortRole.NONE
    mode: str = DEFAULT_VLAN_MODE
    vlans: frozenset[int] = frozenset()
    all_vlans: bool = False

    @property
    def vlan_state(self) -> str:
        if not self.vlans:
            return "none"
        return "all" if self.all_vlans else "set"


@dataclass(frozen=True)
class Side:
    """Условия на один порт пары."""

    role: str = "any"
    mode: str = "any"
    vlans: str = "any"


@dataclass(frozen=True)
class RuleSpec:
    """Правило в виде, пригодном для проверки: без привязки к БД (строки и флаги)."""

    name: str
    action: str = "auto"
    target: Side = field(default_factory=Side)
    source: Side = field(default_factory=Side)
    relation: Side = field(default_factory=Side)  # role / mode / vlans: any | same | differs
    apply_role: bool = False
    apply_mode: bool = False
    vlan_policy: str = "keep"
    description: str = ""
    code: str | None = None  # у стандартных правил — устойчивый идентификатор
    enabled: bool = True
    priority: int = 100
    id: str | None = None

    @property
    def symmetric(self) -> bool:
        """Применяется к ОБОИМ портам пары, а не к одному из них (политика VLAN `union`)."""
        return self.vlan_policy == "union"


class Outcome(str, Enum):
    AUTO = "auto"  # направление определено, изменения можно применить после подтверждения
    MANUAL = "manual"  # расхождение известного вида, направление выбирает человек
    IGNORED = "ignored"  # правилом исключено из согласования
    NONE = "none"  # ни одно правило не подошло


# Ориентации: к какому порту СОЕДИНЕНИЯ применяется правило. «source» — порт-источник подключения
# (Connection.source_interface_id), «destination» — порт назначения. Не путать с «источником»
# значений внутри правила (RuleSpec.source) — это порт на другом конце.
APPLY_TO_SOURCE = "source"
APPLY_TO_DESTINATION = "destination"


@dataclass(frozen=True)
class Changes:
    """Что целевой порт получит по правилу (на уровне номеров VLAN). None — грань не меняется."""

    role: PortRole | None = None
    mode: str | None = None
    vlans: frozenset[int] | None = None
    # Нарушенное инвариантом ограничение (например, access с несколькими VLAN) — применять нельзя.
    violation: str | None = None
    # Целевому порту нужно «Все VLAN»: все VLAN его устройства (политика `all`). Номера не заданы —
    # их определяет устройство порта; `vlans` при этом остаётся None.
    all_vlans: bool = False

    @property
    def is_empty(self) -> bool:
        return self.role is None and self.mode is None and self.vlans is None and not self.all_vlans


@dataclass(frozen=True)
class Option:
    """Одно возможное применение правила: какой порт соединения менять и что ему применить."""

    apply_to: str
    changes: Changes


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    rule: RuleSpec | None = None
    # auto — ровно одна, а у симметричного правила — по одной на каждый порт, которому есть что менять;
    # manual — по одной на подходящую ориентацию
    options: tuple[Option, ...] = ()
    note: str | None = None


# --- условия -----------------------------------------------------------------------------------


def _side_matches(side: Side, facts: PortFacts) -> bool:
    if side.role != "any" and side.role != facts.role.value:
        return False
    if side.mode != "any" and side.mode != facts.mode:
        return False
    state = facts.vlan_state
    if side.vlans == "none":
        return state == "none"
    if side.vlans == "set":
        return state in ("set", "all")
    if side.vlans == "all":
        return state == "all"
    return True


def _relation_matches(relation: Side, target: PortFacts, source: PortFacts) -> bool:
    for wanted, same in (
        (relation.role, target.role == source.role),
        (relation.mode, target.mode == source.mode),
        (relation.vlans, target.vlans == source.vlans),
    ):
        if wanted == "same" and not same:
            return False
        if wanted == "differs" and same:
            return False
    return True


def rule_matches(rule: RuleSpec, target: PortFacts, source: PortFacts) -> bool:
    """Подходит ли правило ориентации «target ← source» (только условия, без учёта действия)."""
    return _side_matches(rule.target, target) and _side_matches(rule.source, source) and _relation_matches(rule.relation, target, source)


def compute_changes(rule: RuleSpec, target: PortFacts, source: PortFacts) -> Changes:
    """Изменения целевого порта по правилу — только то, что реально отличается от текущего.

    VLAN-политика: `copy` — целевой порт получает набор VLAN источника; `adapt` — после смены режима
    приводит свои VLAN к режиму (в access остаётся один VLAN с наименьшим номером, в trunk —
    назначенные сохраняются), как при переключении режима в форме устройства и в каскаде смены режима;
    `union` — целевой порт получает объединение своих VLAN и VLAN источника (свои не снимаются);
    `all` — целевой порт получает «Все VLAN» (все VLAN своего устройства), если у него их ещё нет."""
    role = source.role if rule.apply_role and target.role != source.role else None
    mode = source.mode if rule.apply_mode and target.mode != source.mode else None
    new_mode = mode or target.mode
    vlans: frozenset[int] | None = None
    all_vlans = False
    if rule.vlan_policy == "copy" and target.vlans != source.vlans:
        vlans = source.vlans
    elif rule.vlan_policy == "union" and not source.vlans <= target.vlans:
        vlans = target.vlans | source.vlans
    elif rule.vlan_policy == "adapt" and mode == VLAN_MODE_ACCESS and len(target.vlans) > 1:
        vlans = frozenset({min(target.vlans)})
    elif rule.vlan_policy == "all" and target.vlan_state != "all":
        all_vlans = True
    final_vlans = vlans if vlans is not None else target.vlans
    violation = None
    if new_mode == VLAN_MODE_ACCESS and (len(final_vlans) > 1 or all_vlans):
        violation = "В режиме access у порта может быть не более одного VLAN"
    return Changes(role, mode, vlans, violation, all_vlans)


def decide(rules: Iterable[RuleSpec], a: PortFacts, b: PortFacts) -> Decision:
    """Решение для пары портов подключения: `a` — порт-источник подключения, `b` — порт назначения.

    `rules` — включённые правила в порядке проверки (по возрастанию приоритета)."""
    for rule in rules:
        forward = rule_matches(rule, a, b)  # правило применяется к a, значения берутся у b
        backward = rule_matches(rule, b, a)  # правило применяется к b, значения берутся у a
        if not (forward or backward):
            continue
        if rule.action == "ignore":
            return Decision(Outcome.IGNORED, rule)
        options = tuple(
            Option(apply_to, compute_changes(rule, target, source))
            for matched, apply_to, target, source in (
                (forward, APPLY_TO_SOURCE, a, b),
                (backward, APPLY_TO_DESTINATION, b, a),
            )
            if matched
        )
        if rule.action == "manual":
            return Decision(Outcome.MANUAL, rule, options)
        effective = tuple(o for o in options if not o.changes.is_empty)
        if not effective:
            continue  # правило подошло, но менять нечего — для этой пары оно ничего не решает
        if len(options) > 1 and not rule.symmetric:
            return Decision(Outcome.MANUAL, rule, effective, "Правило применимо в обе стороны — направление выберите вручную")
        return Decision(Outcome.AUTO, rule, effective)
    return Decision(Outcome.NONE)


def sort_rules(rules: Iterable[RuleSpec]) -> list[RuleSpec]:
    """Порядок проверки: по возрастанию приоритета, при равенстве — стабильно по id."""
    return sorted(rules, key=lambda r: (r.priority, r.id or ""))


def active_rules(rules: Iterable[RuleSpec]) -> list[RuleSpec]:
    """Включённые правила в порядке проверки — то, что передаётся в decide()."""
    return sort_rules(r for r in rules if r.enabled)


# --- проверка введённого правила ----------------------------------------------------------------


class RuleValidationError(ValueError):
    """Введённое правило некорректно; текст предназначен пользователю."""


def _choice(value: Any, allowed: Sequence[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise RuleValidationError(f"{label}: допустимые значения — {', '.join(allowed)}")
    return value


def _side_from_payload(raw: Any, label: str, *, roles: Sequence[str], modes: Sequence[str], vlans: Sequence[str]) -> Side:
    if raw is None:
        return Side()
    if not isinstance(raw, Mapping):
        raise RuleValidationError(f"{label} должно быть объектом")
    unknown = set(raw) - {"role", "mode", "vlans"}
    if unknown:
        raise RuleValidationError(f"{label}: неизвестные поля — {', '.join(sorted(unknown))}")
    return Side(
        _choice(raw.get("role", "any"), roles, f"{label}.role"),
        _choice(raw.get("mode", "any"), modes, f"{label}.mode"),
        _choice(raw.get("vlans", "any"), vlans, f"{label}.vlans"),
    )


def _name_from_payload(payload: Mapping[str, Any], current: RuleSpec) -> str:
    name = payload.get("name", current.name)
    if not isinstance(name, str) or not name.strip():
        raise RuleValidationError("Название правила обязательно")
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH:
        raise RuleValidationError(f"Название правила не длиннее {MAX_NAME_LENGTH} символов")
    return name


def _description_from_payload(payload: Mapping[str, Any], current: RuleSpec) -> str:
    description = payload.get("description", current.description)
    if description is None:
        description = ""
    if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH:
        raise RuleValidationError(f"Описание должно быть строкой не длиннее {MAX_DESCRIPTION_LENGTH} символов")
    return description


def _enabled_from_payload(payload: Mapping[str, Any], current: RuleSpec) -> bool:
    enabled = payload.get("enabled", current.enabled)
    if not isinstance(enabled, bool):
        raise RuleValidationError("Поле enabled должно быть true или false")
    return enabled


def _priority_from_payload(payload: Mapping[str, Any], current: RuleSpec) -> int:
    priority = payload.get("priority", current.priority)
    if isinstance(priority, bool) or not isinstance(priority, int) or abs(priority) > PRIORITY_LIMIT:
        raise RuleValidationError(f"Приоритет — целое число не больше {PRIORITY_LIMIT} по модулю")
    return priority


def _merged_side(
    payload: Mapping[str, Any],
    key: str,
    existing: Side,
    label: str,
    *,
    roles: Sequence[str] = ROLE_CONDITIONS,
    modes: Sequence[str] = MODE_CONDITIONS,
    vlans: Sequence[str] = VLAN_CONDITIONS,
) -> Side:
    """Условие на порт из тела: нет ключа или `null` — прежнее значение, объект — поверх прежнего по полям."""
    if key not in payload:
        return existing
    merged = {"role": existing.role, "mode": existing.mode, "vlans": existing.vlans}
    raw = payload[key]
    if isinstance(raw, Mapping):
        merged.update(raw)
    elif raw is not None:
        raise RuleValidationError(f"{label} должно быть объектом")
    return _side_from_payload(merged, label, roles=roles, modes=modes, vlans=vlans)


def _apply_from_payload(payload: Mapping[str, Any], current: RuleSpec) -> tuple[bool, bool, str]:
    """(менять роль, менять режим, политика VLAN) из `apply`; отсутствующие поля берутся из прежнего правила."""
    apply = payload.get("apply")
    if apply is not None and not isinstance(apply, Mapping):
        raise RuleValidationError("Поле apply должно быть объектом")
    apply = apply or {}
    unknown = set(apply) - {"role", "mode", "vlans"}
    if unknown:
        raise RuleValidationError(f"apply: неизвестные поля — {', '.join(sorted(unknown))}")
    apply_role = apply.get("role", current.apply_role)
    apply_mode = apply.get("mode", current.apply_mode)
    for flag, label in ((apply_role, "apply.role"), (apply_mode, "apply.mode")):
        if not isinstance(flag, bool):
            raise RuleValidationError(f"{label} должно быть true или false")
    vlan_policy = _choice(apply.get("vlans", current.vlan_policy), VLAN_POLICIES, "apply.vlans")
    return apply_role, apply_mode, vlan_policy


def _check_apply_consistency(action: str, apply_role: bool, apply_mode: bool, vlan_policy: str) -> None:
    """Взаимосвязи действия и изменений: проверяются после того, как каждое поле в отдельности корректно."""
    if vlan_policy == "adapt" and not apply_mode:
        raise RuleValidationError("Политика VLAN «по режиму» имеет смысл только вместе со сменой режима (apply.mode)")
    if vlan_policy == "union" and (apply_role or apply_mode):
        raise RuleValidationError(
            "Политика VLAN «объединить» меняет оба порта сразу и не сочетается со сменой роли или режима: их "
            "порт берёт у соседа, а не оба сразу"
        )
    if action == "auto" and not (apply_role or apply_mode or vlan_policy != "keep"):
        raise RuleValidationError("Правило с действием «автоматически» должно что-то менять: роль, режим или VLAN")


def rule_from_payload(payload: Mapping[str, Any], *, base: RuleSpec | None = None) -> RuleSpec:
    """Собирает и проверяет правило из тела запроса. С `base` — частичное обновление: переданные поля
    заменяют поля базового правила, остальные сохраняются (так работает и переключатель «включено»).

    Служебные поля (`code`, `builtin`, `id`) из тела игнорируются: стандартное правило остаётся
    стандартным, а пользователь не может выдать своё правило за стандартное.

    Порядок проверок — часть поведения: при нескольких нарушениях пользователь видит первое (имя, описание,
    включено, приоритет, действие, условия целевого порта, порта-источника, отношение, apply, взаимосвязи);
    закреплён tests/test_rule_from_payload_behaviour.py."""
    if not isinstance(payload, Mapping):
        raise RuleValidationError("Тело запроса должно быть объектом")
    current = base or RuleSpec(name="")

    name = _name_from_payload(payload, current)
    description = _description_from_payload(payload, current)
    enabled = _enabled_from_payload(payload, current)
    priority = _priority_from_payload(payload, current)
    action = _choice(payload.get("action", current.action), ACTIONS, "Действие")
    target = _merged_side(payload, "target", current.target, "Условия целевого порта")
    source = _merged_side(payload, "source", current.source, "Условия порта-источника")
    relation = _merged_side(payload, "relation", current.relation, "Отношение портов", roles=RELATIONS, modes=RELATIONS, vlans=RELATIONS)
    apply_role, apply_mode, vlan_policy = _apply_from_payload(payload, current)
    _check_apply_consistency(action, apply_role, apply_mode, vlan_policy)

    return replace(
        current,
        name=name,
        description=description,
        enabled=enabled,
        priority=priority,
        action=action,
        target=target,
        source=source,
        relation=relation,
        apply_role=apply_role,
        apply_mode=apply_mode,
        vlan_policy=vlan_policy,
    )


# --- стандартные правила -----------------------------------------------------------------------

ALL_VLANS_RULE = "all_vlans_to_neighbor"
ALL_VLANS_BOTH_RULE = "all_vlans_both_sides_ignore"
EMPTY_TRUNK_RULE = "empty_trunk_takes_neighbor_vlans"
ROLE_MATCH_RULE = "role_match"
MODE_MATCH_RULE = "mode_match"
VLANS_MATCH_RULE = "vlans_match"
TRUNK_VLANS_UNION_RULE = "trunk_vlans_union"

DEFAULT_RULES: tuple[RuleSpec, ...] = (
    RuleSpec(
        code=ALL_VLANS_RULE,
        name="«Все VLAN» на порту — «Все VLAN» у соседа",
        description=(
            "Если на порту trunk с «Все VLAN» (назначены все VLAN его устройства), а соседний порт тоже в режиме "
            "trunk, но «Все VLAN» у него нет, соседнему порту назначаются все VLAN его устройства — уже назначенные "
            "VLAN не снимаются. Номера VLAN соседа не переносятся: у разных устройств наборы доступных VLAN могут "
            "отличаться, а если у порта-источника есть VLAN, которых нет у устройства соседа, это показывается в "
            "плане предупреждением. Проверяется раньше правил «пустой trunk» и «объединение наборов VLAN». "
            "Применяется автоматически — после предпросмотра и подтверждения."
        ),
        action="auto",
        # 5, а не 5-в-цепочке 10, 20…: правило конкретнее «пустого trunk» (источник — именно «Все VLAN») и должно
        # проверяться раньше него, иначе пустой trunk получил бы только номера VLAN соседа, а не «Все VLAN».
        priority=5,
        target=Side(mode=VLAN_MODE_TRUNK),
        source=Side(mode=VLAN_MODE_TRUNK, vlans="all"),
        vlan_policy="all",
    ),
    RuleSpec(
        code=ALL_VLANS_BOTH_RULE,
        name="«Все VLAN» на обоих портах — не трогать",
        description=(
            "Если на обоих портах подключения trunk с «Все VLAN» (назначены все VLAN их устройств), роли совпадают, а "
            "номера VLAN различаются, пара не согласовывается: у устройств разные наборы доступных VLAN, и ни «объединить», "
            "ни «взять набор соседа» это не исправит — для этого нужно изменить VLAN самих устройств. Пара показывается в плане "
            "как «Исключено правилом», а не как «Нельзя применить». В сверке на дашборде «Подключения» расхождение остаётся — "
            "его можно одобрить. Если роли различаются, правило не срабатывает, и расхождение роли решается правилом ниже. "
            "Проверяется сразу после правила «Все VLAN → Все VLAN»."
        ),
        action="ignore",
        priority=6,
        target=Side(mode=VLAN_MODE_TRUNK, vlans="all"),
        source=Side(mode=VLAN_MODE_TRUNK, vlans="all"),
        relation=Side(role="same", vlans="differs"),
    ),
    RuleSpec(
        code=EMPTY_TRUNK_RULE,
        name="Пустой trunk получает VLAN соседа",
        description=(
            "Если на порту режим trunk и VLAN не назначены совсем, а на соседнем порту trunk с назначенными VLAN (или с "
            "«Все VLAN»), порту применяется trunk с VLAN соседнего порта. Применяется автоматически — после предпросмотра "
            "и подтверждения."
        ),
        action="auto",
        priority=10,
        target=Side(mode=VLAN_MODE_TRUNK, vlans="none"),
        source=Side(mode=VLAN_MODE_TRUNK, vlans="set"),
        apply_role=False,
        apply_mode=True,
        vlan_policy="copy",
    ),
    RuleSpec(
        code=TRUNK_VLANS_UNION_RULE,
        name="Trunk: наборы VLAN на концах линии объединяются",
        description=(
            "Если оба порта подключения в режиме trunk, у обоих назначены VLAN, но наборы различаются, каждый "
            "порт получает объединение VLAN обоих портов: ни один VLAN не снимается, и линия начинает нести "
            "одинаковый набор с обеих сторон. VLAN, которых нет у устройства порта, ему не назначаются — это "
            "показывается в плане предупреждением. Применяется автоматически — после предпросмотра и "
            "подтверждения. Приоритет 15 — сразу после правила для пустого trunk."
        ),
        action="auto",
        # 15, а не 20: у уже работающих установок стандартные правила занимают 10, 20, 30, 40 (а после
        # перестановки — 10, 20, 30, 40, 50…), и совпавший приоритет сделал бы порядок проверки
        # зависимым от id. Между 10 и 20 всегда есть свободное место.
        priority=15,
        target=Side(mode=VLAN_MODE_TRUNK, vlans="set"),
        source=Side(mode=VLAN_MODE_TRUNK, vlans="set"),
        relation=Side(vlans="differs"),
        vlan_policy="union",
    ),
    RuleSpec(
        code=ROLE_MATCH_RULE,
        name="Роль порта совпадает с ролью соседа",
        description=(
            "Роль («Управление» / «Передача данных») порта должна совпадать с ролью порта на другом конце подключения. "
            "Какой порт менять — решает человек: порту применяется роль соседа."
        ),
        action="manual",
        priority=20,
        relation=Side(role="differs"),
        apply_role=True,
    ),
    RuleSpec(
        code=MODE_MATCH_RULE,
        name="Режим порта совпадает с режимом соседа",
        description=(
            "Режим порта (access / trunk) должен совпадать с режимом порта на другом конце подключения. Какой порт менять "
            "— решает человек: порту применяется режим соседа; в access остаётся один VLAN (с наименьшим номером), в trunk "
            "назначенные VLAN сохраняются."
        ),
        action="manual",
        priority=30,
        relation=Side(mode="differs"),
        apply_mode=True,
        vlan_policy="adapt",
    ),
    RuleSpec(
        code=VLANS_MATCH_RULE,
        name="Наборы VLAN на концах линии совпадают",
        description=(
            "Набор VLAN порта должен совпадать с набором VLAN порта на другом конце подключения (по номерам VLAN). Какой "
            "порт менять — решает человек: порту применяются VLAN соседа."
        ),
        action="manual",
        priority=40,
        relation=Side(vlans="differs"),
        vlan_policy="copy",
    ),
)

DEFAULT_RULES_BY_CODE: Mapping[str, RuleSpec] = {rule.code: rule for rule in DEFAULT_RULES if rule.code}


def rules_equal_ignoring_state(a: RuleSpec, b: RuleSpec) -> bool:
    """Совпадает ли ЛОГИКА правил: название, описание, условия, действие и применяемое. Приоритет и
    «включено» не сравниваются — это порядок и переключатель, а не содержание правила."""
    return replace(a, enabled=True, priority=0, id=None, code=None) == replace(b, enabled=True, priority=0, id=None, code=None)
