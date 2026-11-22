"""Согласование VLAN устройств с VLAN-доменами при создании и изменении ресурсов."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ..integrity import find_stale_group_subinterfaces, find_stale_subinterfaces
from ...models import (
    DeviceInterface,
    PhysicalDevice,
    DeviceTypeVLAN,
    PhysicalDeviceVLAN,
    InterfaceVLAN,
    VLAN,
    VLANDomain,
    VLANDomainDevice,
    InterfaceGroup,
    InterfaceGroupVLAN,
)


def _domain_device_ids(domain_id: str, session: Session) -> set[str]:
    """Все устройства домена VLAN: участники (VLANDomainDevice) и устройство-источник, который может
    не числиться участником."""
    device_ids = set(session.scalars(select(VLANDomainDevice.physical_device_id).where(VLANDomainDevice.domain_id == domain_id)).all())
    source_device_id = session.scalar(select(VLANDomain.source_device_id).where(VLANDomain.id == domain_id))
    if source_device_id:
        device_ids.add(source_device_id)
    return device_ids


def _unassign_moved_vlan_from_former_domain_devices(vlan: "VLAN", old_domain_id: str | None, session: Session) -> int:
    """VLAN, перенесённый из одного домена в другой, снимается с устройств прежнего домена, которых нет
    в новом (ни участник, ни источник): VLAN чужого для них домена нельзя оставить в «VLAN устройства» —
    _validate_physical_device_vlan отклонял бы следующее же сохранение такого устройства (422 «Устройство
    не включено в домен этого VLAN»), а порты и группы портов с этим VLAN не проходили бы проверку
    разрешённых VLAN в sync_interfaces.

    Вместе с назначением на устройстве убираются и связи этого VLAN с портами и группами портов того же
    устройства — кроме устройств, чей тип разрешает VLAN каталогом типа (DeviceTypeVLAN): там порт вправе
    использовать VLAN и без назначения на устройстве. Устройства, оставшиеся в новом домене, и все
    остальные VLAN не затрагиваются. Перенос в «без домена» (локальный VLAN) и из «без домена» в домен
    сюда не относится: у прежних локальных назначений нет «прежнего домена».

    Возвращает число устройств, с которых VLAN снят. Все запросы — по наборам устройств, не по одному."""
    if not old_domain_id or not vlan.domain_id or old_domain_id == vlan.domain_id:
        return 0
    left_behind = _domain_device_ids(old_domain_id, session) - _domain_device_ids(vlan.domain_id, session)
    if not left_behind:
        return 0
    assigned = set(
        session.scalars(
            select(PhysicalDeviceVLAN.physical_device_id).where(PhysicalDeviceVLAN.vlan_id == vlan.id, PhysicalDeviceVLAN.physical_device_id.in_(left_behind))
        ).all()
    )
    if not assigned:
        return 0
    type_allowed = set(session.scalars(select(DeviceTypeVLAN.device_type_id).where(DeviceTypeVLAN.vlan_id == vlan.id)).all())
    strip_ports_of = {
        device_id
        for device_id, type_id in session.execute(select(PhysicalDevice.id, PhysicalDevice.device_type_id).where(PhysicalDevice.id.in_(assigned))).all()
        if type_id not in type_allowed
    }
    session.execute(delete(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.vlan_id == vlan.id, PhysicalDeviceVLAN.physical_device_id.in_(assigned)))
    if strip_ports_of:
        port_ids = select(DeviceInterface.id).where(DeviceInterface.physical_device_id.in_(strip_ports_of))
        session.execute(delete(InterfaceVLAN).where(InterfaceVLAN.vlan_id == vlan.id, InterfaceVLAN.interface_id.in_(port_ids)))
        group_ids = select(InterfaceGroup.id).where(InterfaceGroup.physical_device_id.in_(strip_ports_of))
        session.execute(delete(InterfaceGroupVLAN).where(InterfaceGroupVLAN.vlan_id == vlan.id, InterfaceGroupVLAN.group_id.in_(group_ids)))
    return len(assigned)


def _stale_subinterfaces_on_vlan(vlan_id: str, session: Session) -> list[str]:
    """Подписи «устройство / порт / подинтерфейс» подинтерфейсов на этом VLAN, который их устройству больше не разрешён.

    Подинтерфейсы при снятии VLAN с устройства не удаляются и не переносятся сами (в отличие от связей VLAN с
    портами и группами): подинтерфейс — самостоятельная запись со своими IP и открытыми портами, молча удалять её
    нельзя. Остаётся «устаревший» подинтерфейс; форма устройства покажет его с предупреждением, а следующее
    сохранение потребует выбрать другой VLAN или удалить подинтерфейс. Эта функция нужна, чтобы такие подинтерфейсы
    не остались незамеченными — перечень уходит в журнал аудита при переносе VLAN в другой домен. Поиск — общий с
    диагностикой по всему реестру (services/integrity.py:find_stale_subinterfaces)."""
    return [f"{r['device_name']} / {r['port_name']} / {r['subinterface_name']}" for r in find_stale_subinterfaces(session, vlan_id=vlan_id)]


def _stale_group_subinterfaces_on_vlan(vlan_id: str, session: Session) -> list[str]:
    """Подписи «устройство / группа» шаблонов подинтерфейсов ГРУПП портов на этом VLAN, которого у группы больше нет.

    При переносе VLAN в другой домен связи VLAN с группами портов устройств прежнего домена снимаются сами, а шаблон
    подинтерфейса группы — запись со своими IP и открытыми портами — остаётся, как и подинтерфейсы портов: молча удалять
    её нельзя. Перечень уходит в журнал аудита рядом с перечнем подинтерфейсов портов; поиск общий с диагностикой по всему
    реестру (services/integrity.py:find_stale_group_subinterfaces)."""
    return [f"{r['device_name']} / {r['group_name']}" for r in find_stale_group_subinterfaces(session, vlan_id=vlan_id)]


def _auto_assign_new_domain_vlan_to_domain_devices(vlan: "VLAN", session: Session) -> None:
    """Правка "VLAN домена": VLAN, заведённый в «справочник VLAN» (VLANFormModal.vue) сразу с
    привязкой к домену — или привязанный к домену позже обновлением domain_id — должен появиться в
    блоке «VLAN устройства» ВСЕХ физических устройств этого домена (участников VLANDomainDevice и
    устройства-источника) без ручного шага «Синхронизировать».

    Раньше (п.2 правки "создание физического устройства") VLAN назначался только устройству-
    источнику, а остальные участники получали его лишь при ручной синхронизации (sync_vlan_domain
    реплицирует набор VLAN источника на участников), из-за чего новый VLAN не появлялся на
    устройствах домена. Источник учитывается отдельно от участников: он может не числиться в
    VLANDomainDevice.

    Уже назначенное не дублируется (uq_physical_device_vlan), поэтому вызов безопасно повторять.
    Если VLAN не привязан к домену или у домена нет ни участников, ни источника — тихо выходим:
    это не ошибка, а обычный локальный или пока пустой домен. Два запроса на весь домен, а не по
    запросу на устройство."""
    if not vlan.domain_id:
        return
    domain = session.get(VLANDomain, vlan.domain_id)
    if not domain:
        return
    device_ids = _domain_device_ids(domain.id, session)
    if not device_ids:
        return
    already_assigned = set(
        session.scalars(
            select(PhysicalDeviceVLAN.physical_device_id).where(
                PhysicalDeviceVLAN.vlan_id == vlan.id,
                PhysicalDeviceVLAN.physical_device_id.in_(device_ids),
            )
        ).all()
    )
    for device_id in sorted(device_ids - already_assigned):
        session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan.id, description=vlan.description))


def assign_domain_vlans_to_device(domain_id: str | None, physical_device_id: str | None, session: Session) -> None:
    """Пункт 2 правки "домен VLAN": устройство, добавленное в домен, должно СРАЗУ получить набор
    VLAN, уже определённых для этого домена (VLAN.domain_id == domain_id) — до этой правки это
    происходило только при следующем ручном "Синхронизировать" (sync_vlan_domain), не при самом
    добавлении. Публичная (без "_", в отличие от большинства helper'ов рядом) — вызывается не
    только отсюда (хук ниже, для VLANDomainDevice, созданного через generic-ресурс — этим путём
    идёт, например, DeviceFormModal.vue:persistPendingDomainMemberships), но и напрямую из
    api/system.py:add_vlan_domain_member (тот строит VLANDomainDevice сам, в обход
    create_resource, ради собственной идемпотентности — см. её комментарий).

    Если у домена ещё нет ни одного своего VLAN (устройство-источник не задано или домен ни разу
    не синхронизировался) — присваивать нечего, это не ошибка, а обычное новое устройство в ещё
    пустом домене."""
    if not domain_id or not physical_device_id:
        return
    domain_vlans = session.scalars(select(VLAN).where(VLAN.domain_id == domain_id)).all()
    if not domain_vlans:
        return
    existing_ids = set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == physical_device_id)).all())
    for v in domain_vlans:
        if v.id not in existing_ids:
            session.add(PhysicalDeviceVLAN(physical_device_id=physical_device_id, vlan_id=v.id, description=v.description))
