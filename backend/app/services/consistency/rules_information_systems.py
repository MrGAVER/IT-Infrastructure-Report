"""Правила информационных систем (лист 1 отчёта): размещение, описание, поддержка, криптозащита."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import InformationSystem, InformationSystemSource, ISProtocol
from ._support import is_blank
from .engine import RuleSpec, rule
from .model import Category, Finding, Severity

ENTITY = "information_system"

# Текстовые столбцы листа 1, которые должны быть заполнены: (поле модели, как назвать в сообщении).
_REQUIRED_TEXT = (
    ("description", "общее описание"),
    ("purpose", "назначение"),
    ("localization", "локализация"),
    ("process_description", "описание процесса функционирования"),
)


def _systems(session: Session) -> list:
    return list(session.execute(select(InformationSystem)).scalars())


@rule("is_without_placement", "У ИС не указано размещение", Severity.WARNING, Category.COMPLETENESS, sheet=1)
def check_without_placement(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    placed = set(session.scalars(select(InformationSystemSource.information_system_id).distinct()))
    for system in _systems(session):
        if system.id not in placed:
            yield spec.finding(
                ENTITY, system.id, system.name, f"{system.name}: не указано ни одного оборудования, ВМ, контейнера или адреса размещения."
            )


@rule("is_without_protocols", "У ИС не указаны протоколы передачи данных", Severity.INFO, Category.COMPLETENESS, sheet=1)
def check_without_protocols(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    with_protocols = set(session.scalars(select(ISProtocol.information_system_id).distinct()))
    for system in _systems(session):
        if system.id not in with_protocols:
            yield spec.finding(ENTITY, system.id, system.name, f"{system.name}: не указан ни один протокол передачи данных.")


@rule("is_text_incomplete", "В описании ИС не хватает данных", Severity.WARNING, Category.COMPLETENESS, sheet=1)
def check_text_incomplete(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    for system in _systems(session):
        missing = [label for field_name, label in _REQUIRED_TEXT if is_blank(getattr(system, field_name))]
        if missing:
            yield spec.finding(ENTITY, system.id, system.name, f"{system.name}: не заполнено — {', '.join(missing)}.", missing=missing)


@rule(
    "is_without_support", "У ИС не указана организация или способ технической поддержки", Severity.WARNING, Category.COMPLETENESS, sheet=1
)
def check_without_support(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    for system in _systems(session):
        missing = [
            label
            for label, filled in (("организация поддержки", system.support_organization_id), ("способ поддержки", system.support_method_id))
            if is_blank(filled)
        ]
        if missing:
            yield spec.finding(ENTITY, system.id, system.name, f"{system.name}: не указано — {', '.join(missing)}.", missing=missing)


@rule("is_crypto_mismatch", "Признак криптозащиты ИС противоречит выбранному средству", Severity.ERROR, Category.CONSISTENCY, sheet=1)
def check_crypto_mismatch(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Криптозащита отмечена, а средство не выбрано (ошибка), или средство выбрано, а признак снят (предупреждение)."""
    for system in _systems(session):
        has_means = not is_blank(system.crypto_protection_description_id)
        if system.crypto_protection_enabled and not has_means:
            yield spec.finding(ENTITY, system.id, system.name, f"{system.name}: криптозащита отмечена, но средство защиты не выбрано.")
        elif has_means and not system.crypto_protection_enabled:
            yield spec.finding(
                ENTITY,
                system.id,
                system.name,
                f"{system.name}: выбрано средство криптозащиты, но признак применения не отмечен.",
                severity=Severity.WARNING,
            )


@rule(
    "is_external_without_crypto",
    "ИС взаимодействует с внешними системами без криптозащиты",
    Severity.WARNING,
    Category.CONSISTENCY,
    sheet=1,
)
def check_external_without_crypto(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Лист 1 требует указать СКЗИ при внешнем взаимодействии: у ИС с внешним источником признак криптозащиты должен быть отмечен."""
    external = {
        row.information_system_id: row.sources
        for row in session.execute(
            select(InformationSystemSource.information_system_id, func.count().label("sources"))
            .where(InformationSystemSource.external_interaction.is_(True))
            .group_by(InformationSystemSource.information_system_id)
        )
    }
    for system in _systems(session):
        if system.id in external and not system.crypto_protection_enabled:
            yield spec.finding(
                ENTITY,
                system.id,
                system.name,
                f"{system.name}: есть внешнее взаимодействие ({external[system.id]}), но применение криптозащиты не отмечено.",
                external_sources=external[system.id],
            )
