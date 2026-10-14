"""Стеки устройств: сводная карточка и добавление участника (код-ревью п. 10).

Обработчики только разбирают запрос и вызывают services/device_stacks.py — вся логика там.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import DeviceStackMemberRequest, DeviceStackVlanIpRequest
from ..services.device_stack_vlans import apply_stack_vlan, preview_member_addition, remove_stack_vlan, stack_vlans
from ..services.device_stacks import add_stack_member, stack_detail

router = APIRouter(tags=['Device stacks'])

@router.get('/api/v1/device-stacks/{stack_id}/detail')
def device_stack_detail(stack_id: str, session: Session = Depends(get_db)):
    """Пункт 5 правки "создание физического устройства" — "просмотр каждого устройства в стеке по
    отдельности, а также вместе": отдельность уже обеспечена тем, что участник стека — обычное
    PhysicalDevice (открывается тем же DeviceFormModal.vue, что и любое другое устройство, без
    специального кода). Этот эндпоинт — про "вместе": участники стека (полными карточками, как на
    списке устройств, — enrich_devices) плюс связывающие их подключения.

    "Связывающее" (внутристековое) подключение вычисляется на лету по членству — Connection, у
    которого ОБА конца (source/destination interface) принадлежат устройствам ИЗ ЭТОГО стека, —
    а не хранится отдельным флагом на самом Connection (см. docstring класса DeviceStack в
    models.py, почему: иначе флаг рассинхронизировался бы при добавлении/удалении обычных
    Connection в обход стека, например когда участника переносят в другой стек)."""
    return stack_detail(session, stack_id)

@router.post('/api/v1/device-stacks/{stack_id}/members')
def add_device_stack_member(stack_id: str, payload: DeviceStackMemberRequest, session: Session = Depends(get_db)):
    """Идемпотентно (как и add_vlan_domain_member выше) — повторное добавление уже состоящего в
    ЭТОМ ЖЕ стеке устройства просто возвращает существующую запись членства, не 409. Попытка
    добавить устройство, состоящее в ДРУГОМ стеке, всё равно упадёт понятной 409 —
    _validate_device_stack_member_entry (см. services/crud/) вызывается ниже через
    validate_resource, как и для любого generic-ресурса."""
    return add_stack_member(session, stack_id, payload.physical_device_id, payload.position)


@router.get('/api/v1/device-stacks/{stack_id}/members/preview')
def preview_device_stack_member(stack_id: str, physical_device_id: str = Query(...), position: int = Query(1, ge=1), session: Session = Depends(get_db)):
    """Что произойдёт с данными устройства при добавлении в стек: какие VLAN общих настроек будут назначены ему
    ('add') и у каких заменятся значения ('update', before → after). Ничего не записывает — для окна подтверждения."""
    return preview_member_addition(session, stack_id, physical_device_id, position)


@router.get('/api/v1/device-stacks/{stack_id}/vlans')
def device_stack_vlans(stack_id: str, session: Session = Depends(get_db)):
    """Общие настройки VLAN стека (кластера): items — заданные настройки и состояние применения к участникам
    (is_uniform, счётчики, значения каждого участника); available — VLAN, добавленные хотя бы одному устройству стека,
    которые можно сделать общими, с подсказкой значений (адрес, на котором сошлись участники; «Управление», если оно
    включено хотя бы у одного)."""
    return stack_vlans(session, stack_id)


@router.put('/api/v1/device-stacks/{stack_id}/vlans/{vlan_id}')
def set_device_stack_vlan(stack_id: str, vlan_id: str, payload: DeviceStackVlanIpRequest, session: Session = Depends(get_db)):
    """Задаёт общую настройку VLAN (IP-адрес, префикс, «Управление») и записывает её всем устройствам стека одной
    транзакцией, идемпотентно. Недостающие назначения VLAN создаются; описание существующих не меняется. Пока
    настройка задана, эти значения у участников по отдельности не редактируются (409). Ответ — как GET .../vlans.

    Пример: PUT /api/v1/device-stacks/{id}/vlans/{vlan_uuid}  {"ip_address": "10.0.10.5", "prefix_length": 24, "is_management": true}"""
    return apply_stack_vlan(session, stack_id, vlan_id, payload.ip_address, payload.prefix_length, payload.is_management)


@router.delete('/api/v1/device-stacks/{stack_id}/vlans/{vlan_id}')
def delete_device_stack_vlan(stack_id: str, vlan_id: str, remove_from_devices: bool = Query(False), session: Session = Depends(get_db)):
    """Снимает общую настройку VLAN со стека. По умолчанию значения на устройствах остаются (поля снова редактируются);
    remove_from_devices=true убирает VLAN и у всех участников — 409, если он используется на их портах, группах
    портов или подинтерфейсах. Ответ — как GET .../vlans."""
    return remove_stack_vlan(session, stack_id, vlan_id, remove_from_devices)
