"""Стеки устройств: сводная карточка и добавление участника (код-ревью п. 10).

Обработчики только разбирают запрос и вызывают services/device_stacks.py — вся логика там.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import DeviceStackMemberRequest
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
