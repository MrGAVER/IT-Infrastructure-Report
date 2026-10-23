"""Доменная валидация записей generic CRUD: реестр валидаторов по моделям, слот в стойке."""
from __future__ import annotations

from typing import Any, Callable
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...models import Connection, Container, DeviceCategory, DeviceInterface, DeviceModel, DeviceStack, DeviceStackMember, DeviceType, DiagramIcon, IPAddress, InformationSystem, InterfaceVLAN, PhysicalDevice, VirtualMachine, PhysicalDeviceVLAN, VLAN, VLANDomainDevice
from ...constants import ErrorCode
from ..diagram_icons import SHAPE_GLYPHS, is_hex_color, validate_svg_markup
from ..port_config import DEFAULT_VLAN_MODE, VLAN_MODE_ACCESS, VLAN_MODE_TRUNK
from .stack_vlan_settings import assert_device_vlan_editable, locked_vlan_ids, normalize_ip
from ..validation import duplicate_system_name, validate_connection, validate_container_host, validate_device_location_hierarchy, validate_device_model_relation, validate_hypervisor, validate_ipv4_field, validate_operating_system, validate_prefix_length_field, validate_vm_host, validate_embedded_os, validate_support_method_organization


def _validate_physical_device(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_device_model_relation(data, session, item_id); validate_operating_system(data, session); validate_embedded_os(data, session); validate_device_location_hierarchy(data, session)
    if data.get('system_name') and duplicate_system_name(session, data['system_name'], item_id) and not confirm_duplicate:
        raise HTTPException(409, detail={'code': ErrorCode.DUPLICATE_SYSTEM_NAME, 'message': 'Системное имя уже используется другим устройством. Сохранить дубликат?'})
    occupant = _find_rack_slot_occupant(data, session, item_id)
    if occupant and not confirm_rack_reassign:
        raise HTTPException(409, detail={'code': ErrorCode.RACK_POSITION_OCCUPIED, 'message': f'Позиция "{data.get("rack_position")}" в этой стойке уже занята устройством "{occupant.system_name or occupant.serial_number}". Переназначить позицию на текущее устройство?'})


def _find_rack_slot_occupant(data: dict[str, Any], session: Session, item_id: str | None) -> PhysicalDevice | None:
    """Устройство, уже занимающее слот (стойка + позиция) из data, не считая редактируемого item_id."""
    rack_id = data.get('rack_id'); rack_position = data.get('rack_position')
    if not (rack_id and rack_position): return None
    stmt = select(PhysicalDevice).where(PhysicalDevice.rack_id == rack_id, PhysicalDevice.rack_position == rack_position)
    if item_id: stmt = stmt.where(PhysicalDevice.id != item_id)
    return session.scalar(stmt)


def _release_rack_slot(model: type, data: dict[str, Any], session: Session, item_id: str | None = None) -> None:
    """Освобождает слот в стойке, который пользователь подтвердил переназначить (confirm_rack_position_reassign).

    Раньше позицию прежнего занятого обнуляла сама функция валидации — проверка с побочным эффектом, а при
    уникальном индексе слота ещё и неработоспособная: SQLAlchemy выполняет INSERT нового устройства раньше
    UPDATE прежнего, и индекс отвергал бы запись. Поэтому освобождение вынесено сюда и идёт отдельным flush()
    ДО сохранения нового устройства. Вызывается только после validate_resource(): без подтверждения тот уже
    бросил 409, так что занятый слот здесь означает «подтверждено»."""
    if model is not PhysicalDevice: return
    occupant = _find_rack_slot_occupant(data, session, item_id)
    if occupant is None: return
    occupant.rack_position = None
    session.flush()


def _validate_physical_device_vlan(data: dict[str, Any], session: Session) -> None:
    device=session.get(PhysicalDevice, data.get('physical_device_id')) if data.get('physical_device_id') else None
    vlan=session.get(VLAN, data.get('vlan_id')) if data.get('vlan_id') else None
    if not device or not vlan: raise HTTPException(422, 'Необходимо указать физическое устройство и VLAN')
    # A device may define a local VLAN, or use a VLAN from a shared domain.
    # The old device-type VLAN catalog remains compatible, but is no longer
    # required for a newly created device-local VLAN.
    if vlan.domain_id:
        member=session.scalar(select(VLANDomainDevice.id).where(
            VLANDomainDevice.domain_id==vlan.domain_id,
            VLANDomainDevice.physical_device_id==device.id))
        if not member:
            raise HTTPException(422, 'Устройство не включено в домен этого VLAN')


def _validate_device_model(data: dict[str, Any], session: Session, item_id: str | None) -> None:
    if not data.get('manufacturer_id') or not data.get('device_type_id'): raise HTTPException(422, 'Для модели необходимо указать производителя и тип устройства')
    if data.get('model'):
        stmt = select(DeviceModel).where(DeviceModel.manufacturer_id == data['manufacturer_id'], DeviceModel.device_type_id == data['device_type_id'], DeviceModel.model == data['model'])
        if item_id: stmt = stmt.where(DeviceModel.id != item_id)
        if session.scalar(stmt): raise HTTPException(409, 'Такая модель уже существует для выбранных производителя и типа устройства')


def _validate_virtual_machine_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_operating_system(data, session); validate_hypervisor(data, session); validate_vm_host(data, session)


def _validate_container_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_container_host(data)


def _validate_physical_device_vlan_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    _validate_physical_device_vlan(data, session)
    # Значения VLAN, заданные общей настройкой стека, не меняются и этим путём (data — запись целиком, в том числе при правке).
    device_id, vlan_id = data.get('physical_device_id'), data.get('vlan_id')
    if device_id and vlan_id and vlan_id in locked_vlan_ids(session, device_id):
        prefix = data.get('prefix_length')
        try: prefix = None if prefix in (None, '') else int(prefix)
        except (TypeError, ValueError): pass  # нечисловое значение заведомо не равно настройке — получит понятный 409
        assert_device_vlan_editable(session, device_id, {vlan_id: (normalize_ip(data.get('ip_address')), prefix, bool(data.get('is_management')))}, set())


def _validate_device_model_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    _validate_device_model(data, session, item_id)


def _validate_connection_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_connection(data, session, item_id)


def _validate_device_type_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    # Интеграционный фикс (слияние feature/network-topology-diagram + fix/usability-batch4):
    # DeviceType.category_id стал обязательным NOT NULL FK в рамках фичи диаграммы топологии
    # сети (models.py, миграция 38e9b2624a53), но ни generic-валидатор здесь, ни
    # quickAdd/schema.ts не были обновлены под это требование — POST /resources/device-types
    # без category_id падал сырым 409 "NOT NULL constraint failed" вместо понятной ошибки.
    # Саму ссылочную целостность (существует ли такая категория) отдельно не проверяем —
    # некорректный category_id всё равно упадёт на FK при commit() и обработается уже
    # существующим общим обработчиком IntegrityError в create_resource/update_resource.
    if not data.get('category_id'):
        raise HTTPException(422, 'Поле category_id обязательно для типа устройства')


def _validate_diagram_icon_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    # Код-ревью п.3.1: без этой проверки svg_markup сохранялся бы в БД как есть и затем
    # выполнялся бы в браузере через v-html (фронтенд) и при экспорте .svg (бэкенд).
    validate_svg_markup(data.get('svg_markup'))


def _validate_device_category_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    """Цвет и форма категории попадают в разметку экспорта диаграммы (.svg, .drawio, .vsdx): без проверки строка вроде
    `x" onload="alert(1)` внедрялась бы в атрибут. Пустое значение допустимо — стиль наследуется от родителя или берётся
    по умолчанию (services/diagram_icons.resolve_category_style)."""
    color = data.get('diagram_color')
    if color not in (None, '') and not is_hex_color(color):
        raise HTTPException(422, 'diagram_color должен быть HEX-цветом вида #4f7cff или #4cf')
    shape = data.get('diagram_shape')
    if shape not in (None, '') and not (isinstance(shape, str) and shape in SHAPE_GLYPHS):
        raise HTTPException(422, f'diagram_shape должен быть одним из значений: {", ".join(sorted(SHAPE_GLYPHS))}')


def _validate_device_interface_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    """Порт через generic-ресурс `interfaces`: те же инварианты режима и «Все VLAN», что держит sync_interfaces.

    «Все VLAN» (all_vlans) — булев признак порта, допустимый только в trunk; у порта с признаком нет выбранных VLAN
    (набор вычисляется из VLAN устройства, services/port_vlans.py). Без проверок generic-запись могла создать то, чего
    sync_interfaces не допускает: access-порт с признаком, признак не-булева типа (500 из драйвера БД), порт с
    признаком и со связями (после снятия признака связи «воскресли» бы). `data` — payload при создании и payload,
    дополненный текущими значениями, при правке, поэтому переключение режима у порта с признаком без снятия
    признака тоже отклоняется (в sync_interfaces признак и режим приходят вместе)."""
    all_vlans = data.get('all_vlans', False)
    if not isinstance(all_vlans, bool): raise HTTPException(422, 'Поле all_vlans интерфейса должно быть true или false')
    mode = data.get('vlan_mode')
    if mode not in (None, '', VLAN_MODE_ACCESS, VLAN_MODE_TRUNK): raise HTTPException(422, "Поле vlan_mode интерфейса должно быть 'access' или 'trunk'")
    if not all_vlans: return
    if (mode or DEFAULT_VLAN_MODE) != VLAN_MODE_TRUNK:
        raise HTTPException(422, "«Все VLAN» возможно только в режиме trunk: снимите all_vlans, если порт переводится в access")
    if item_id and session.scalar(select(InterfaceVLAN.id).where(InterfaceVLAN.interface_id == item_id).limit(1)) is not None:
        raise HTTPException(422, "У порта есть выбранные VLAN: «Все VLAN» хранится без них — задайте признак через форму устройства (PUT /devices/{id}/interfaces)")


def _validate_interface_vlan_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    """Связь «порт — VLAN» через generic-ресурс `interface-vlans`: у порта с «Все VLAN» связей нет, его набор — это VLAN
    устройства (см. _validate_device_interface_entry), поэтому добавить такому порту связь нельзя."""
    port = session.get(DeviceInterface, data['interface_id']) if data.get('interface_id') else None
    if port is not None and port.all_vlans:
        raise HTTPException(422, "У порта включено «Все VLAN»: его набор берётся из VLAN устройства и в связях не хранится — снимите признак, чтобы выбрать VLAN вручную")


def _validate_ip_address_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    # Код-ревью п.3.4 + объединение InterfaceIP/VMIP в IPAddress (owner_type/owner_id, миграция
    # d8e35a1c7f60): владение интерфейсом синхронизируется отдельной функцией
    # (_sync_interface_ips, свой вызов validate_ipv4_field ниже по файлу), владение источником ИС —
    # тоже отдельной (_sync_information_system_sources). Этот валидатор покрывает оставшийся путь —
    # ПОЛНОСТЬЮ generic create_resource/update_resource (владение виртуальной машиной, как и было
    # у VMIP до объединения).
    validate_ipv4_field(data.get('ip_address'), 'IP-адрес')
    validate_prefix_length_field(data.get('prefix_length'), 'Префикс IP-адреса')


def _validate_information_system_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_support_method_organization(data, session)


# Реестр валидаторов по модели (код-ревью п.3.5): раньше это была цепочка if/elif внутри
# validate_resource() — каждая новая модель, которой требуется своя проверка, была обязана
# трогать тело диспетчера (нарушение OCP; интеграция feature/network-topology-diagram и
# fix/usability-batch4 уже доказала риск на примере DeviceType). Теперь новая модель
# добавляется одной строкой сюда, без изменения самой функции validate_resource(). Все
# значения — вызываемые с единой сигнатурой (data, session, item_id, confirm_duplicate,
# confirm_rack_reassign) — там, где исходный валидатор её не использует, параметры просто
# игнорируются тонкой обёрткой-адаптером выше.
def _validate_device_stack_member_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    """Пункт 5 правки "создание физического устройства": устройство может состоять максимум в
    ОДНОМ стеке одновременно (см. UniqueConstraint('physical_device_id') на DeviceStackMember) —
    без этой проверки повторная попытка добавить уже состоящее в другом стеке устройство падала
    бы сырым 409 IntegrityError вместо понятного сообщения с названием стека, где оно уже состоит."""
    if not data.get('stack_id') or not data.get('physical_device_id'):
        raise HTTPException(422, 'Необходимо указать стек и устройство')
    existing = session.scalar(select(DeviceStackMember).where(DeviceStackMember.physical_device_id == data['physical_device_id']))
    if existing and existing.id != item_id:
        stack = session.get(DeviceStack, existing.stack_id)
        raise HTTPException(409, f'Устройство уже состоит в стеке «{stack.name if stack else existing.stack_id}»')


_RESOURCE_VALIDATORS: dict[type, Callable[[dict[str, Any], Session, str | None, bool, bool], None]] = {
    PhysicalDevice: _validate_physical_device,
    VirtualMachine: _validate_virtual_machine_entry,
    Container: _validate_container_entry,
    PhysicalDeviceVLAN: _validate_physical_device_vlan_entry,
    DeviceModel: _validate_device_model_entry,
    Connection: _validate_connection_entry,
    DeviceType: _validate_device_type_entry,
    DiagramIcon: _validate_diagram_icon_entry,
    DeviceCategory: _validate_device_category_entry,
    IPAddress: _validate_ip_address_entry,
    DeviceInterface: _validate_device_interface_entry,
    InterfaceVLAN: _validate_interface_vlan_entry,
    InformationSystem: _validate_information_system_entry,
    DeviceStackMember: _validate_device_stack_member_entry,
}


def validate_resource(model, data: dict[str, Any], session: Session, item_id: str | None = None, confirm_duplicate: bool = False, confirm_rack_reassign: bool = False) -> None:
    """Диспетчеризация по типу модели на per-модель валидаторы в _RESOURCE_VALIDATORS.
    Модели без зарегистрированного валидатора (большинство ~40 ресурсов реестра) проходят без
    дополнительных проверок — как и раньше, это не бага, а осознанный дизайн: не для каждого
    ресурса нужна валидация сверх generic CRUD/FK-констрейнтов БД."""
    validator = _RESOURCE_VALIDATORS.get(model)
    if validator is not None:
        validator(data, session, item_id, confirm_duplicate, confirm_rack_reassign)
