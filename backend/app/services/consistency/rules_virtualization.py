"""Правила виртуализации (лист 4 отчёта): виртуальные машины и контейнеры."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...constants import OwnerType
from ...models import Container, IPAddress, VirtualMachine
from ._support import is_blank
from .engine import RuleSpec, rule
from .model import Category, Finding, Severity


@rule("vm_without_host", "Виртуальная машина не привязана к физическому устройству", Severity.WARNING, Category.COMPLETENESS, sheet=4)
def check_vm_without_host(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    for vm in session.execute(select(VirtualMachine.id, VirtualMachine.name).where(VirtualMachine.physical_device_id.is_(None))):
        yield spec.finding("virtual_machine", vm.id, vm.name, f"{vm.name}: не указано физическое устройство, на котором работает машина.")


@rule("vm_incomplete", "В карточке виртуальной машины не хватает данных", Severity.WARNING, Category.COMPLETENESS, sheet=4)
def check_vm_incomplete(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Операционная система, назначение и IP-адрес — столбцы листа 4."""
    with_ip = set(session.scalars(select(IPAddress.owner_id).where(IPAddress.owner_type == OwnerType.VIRTUAL_MACHINE)))
    for vm in session.execute(select(VirtualMachine.id, VirtualMachine.name, VirtualMachine.operating_system_id, VirtualMachine.purpose)):
        missing = [
            label
            for label, filled in (
                ("операционная система", vm.operating_system_id),
                ("назначение", vm.purpose),
                ("IP-адрес", vm.id if vm.id in with_ip else None),
            )
            if is_blank(filled)
        ]
        if missing:
            yield spec.finding("virtual_machine", vm.id, vm.name, f"{vm.name}: не указано — {', '.join(missing)}.", missing=missing)


@rule("container_without_host", "Контейнер не привязан ни к ВМ, ни к устройству", Severity.WARNING, Category.COMPLETENESS, sheet=4)
def check_container_without_host(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    query = select(Container.id, Container.name).where(Container.virtual_machine_id.is_(None), Container.physical_device_id.is_(None))
    for container in session.execute(query):
        yield spec.finding(
            "container", container.id, container.name, f"{container.name}: не указано, где работает контейнер (ВМ или устройство)."
        )
