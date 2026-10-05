from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from ..config import APP_VERSION, FRONTEND_DIR, REPORT_DIR
from ..db import get_db
from ..models import (Connection, Container, DeviceInterface, DeviceStack, DeviceStackMember, InformationSystem, PhysicalDevice, SoftwareAsset, VLAN, VirtualMachine, PhysicalDeviceVLAN, VLANDomain, VLANDomainDevice)
from ..services.catalogs import seed_defaults
from ..services.serialization import enrich_connections, enrich_devices, serialize
from ..services.audit_export import build_audit_log_report
from ..services.report_cleanup import cleanup_old_reports
from ..services.crud import assign_domain_vlans_to_device, audit, sync_vm_deployed_software, sync_vm_ip_addresses, sync_vm_open_ports, validate_resource
from ..services.integrity import find_duplicate_open_port_numbers, find_orphaned_owner_references
from ..constants import AuditAction
from ..reporting import build_report

router = APIRouter(tags=['System'])

@router.get('/api/v1/health')
def health(): return {'status':'ok','service':'infra-registry','version':APP_VERSION}

@router.get('/api/v1/integrity')
def integrity_report(session: Session = Depends(get_db)):
    """Диагностика ссылочной целостности связей без настоящего FK (owner_id у OpenPort/
    DeployedSoftware/IPAddress/InformationSystemSource): находит записи, чей владелец уже не
    существует. Только чтение. ok=True и пустой orphans — всё в порядке."""
    orphans = find_orphaned_owner_references(session)
    return {'ok': not orphans, 'total': len(orphans), 'orphans': orphans}

@router.get('/api/v1/integrity/open-port-duplicates')
def open_port_duplicates_report(session: Session = Depends(get_db)):
    """Диагностика уже существующих повторов номеров открытых портов у одного владельца (ВМ, порт
    устройства, группа портов) — данные, появившиеся до правила уникальности. Только чтение; новые
    повторы API отклоняет с 422. ok=True и пустой duplicates — исправлять нечего."""
    duplicates = find_duplicate_open_port_numbers(session)
    return {'ok': not duplicates, 'total': len(duplicates), 'duplicates': duplicates}

@router.get('/api/v1/dashboard')
def dashboard(session: Session = Depends(get_db)):
    entities = {'information_systems': InformationSystem, 'physical_devices': PhysicalDevice, 'virtual_machines': VirtualMachine, 'containers': Container, 'connections': Connection, 'vlan': VLAN, 'software': SoftwareAsset}
    return {key: session.scalar(select(func.count()).select_from(model)) or 0 for key, model in entities.items()}


@router.get('/api/v1/information-systems')
def list_is(session: Session = Depends(get_db)):
    rows = session.scalars(select(InformationSystem).order_by(InformationSystem.name)).all()
    return [serialize(x) for x in rows]

@router.get('/api/v1/devices')
def list_devices(session: Session = Depends(get_db)):
    rows = session.scalars(select(PhysicalDevice).order_by(PhysicalDevice.system_name)).all()
    return {'items':enrich_devices(rows, session), 'total':len(rows)}

@router.get('/api/v1/vms')
def list_vms(session: Session = Depends(get_db)):
    rows = session.scalars(select(VirtualMachine).order_by(VirtualMachine.name)).all()
    return {'items':[serialize(x) for x in rows], 'total':len(rows)}

@router.put('/api/v1/vms/{vm_id}/open-ports')
def sync_vm_ports(vm_id: str, payload: dict, session: Session = Depends(get_db)):
    """Атомарная синхронизация открытых портов ВМ: тело {open_ports: [{id?, protocol_catalog_id,
    transport_protocol, description}]} — полный список портов ВМ, diff по id (см.
    services/crud.py:sync_vm_open_ports)."""
    return sync_vm_open_ports(vm_id, payload, session)

@router.put('/api/v1/vms/{vm_id}/ip-addresses')
def sync_vm_ips(vm_id: str, payload: dict, session: Session = Depends(get_db)):
    """Атомарная синхронизация IP-адресов ВМ: тело {ip_addresses: [{id?, ip_address, prefix_length,
    purpose, is_management}]} — полный список IP-адресов ВМ, diff по id (см.
    services/crud.py:sync_vm_ip_addresses)."""
    return sync_vm_ip_addresses(vm_id, payload, session)

@router.put('/api/v1/vms/{vm_id}/deployed-software')
def sync_vm_software(vm_id: str, payload: dict, session: Session = Depends(get_db)):
    """Атомарная синхронизация программных активов ВМ: тело {deployed_software: [{id?,
    software_asset_id, version}]} — полный список ПО ВМ, diff по id (см.
    services/crud.py:sync_vm_deployed_software)."""
    return sync_vm_deployed_software(vm_id, payload, session)


@router.get('/api/v1/vlan-dashboard')
def vlan_dashboard(session: Session = Depends(get_db)):
    """Dashboard-friendly VLAN view: same VLAN ID can have different definitions."""
    vlans = session.scalars(select(VLAN).order_by(VLAN.vlan_id, VLAN.name)).all()
    devices = session.scalars(select(PhysicalDevice)).all()
    device_names = {d.id: (d.system_name or d.serial_number or d.id) for d in devices}
    domains = {d.id: d for d in session.scalars(select(VLANDomain)).all()}
    assignments = session.scalars(select(PhysicalDeviceVLAN)).all()
    grouped = {}
    for v in vlans:
        grouped.setdefault(v.vlan_id, []).append({
            'id': v.id, 'vlan_id': v.vlan_id, 'name': v.name,
            'description': v.description or '', 'domain_id': v.domain_id,
            'domain_name': domains[v.domain_id].name if v.domain_id in domains else 'Локальный VLAN',
            'devices': []
        })
    by_vlan = {}
    for a in assignments:
        by_vlan.setdefault(a.vlan_id, []).append({
            'device_id': a.physical_device_id,
            'device_name': device_names.get(a.physical_device_id, a.physical_device_id),
            'ip_address': a.ip_address,
            'is_management': a.is_management
        })
    for defs in grouped.values():
        for item in defs:
            item['devices'] = by_vlan.get(item['id'], [])
    return {'items':[{'vlan_id': k, 'definitions': v} for k,v in sorted(grouped.items())]}

@router.post('/api/v1/vlan-domains/{domain_id}/members')
def add_vlan_domain_member(domain_id: str, payload: dict, session: Session = Depends(get_db)):
    domain = session.get(VLANDomain, domain_id)
    device = session.get(PhysicalDevice, payload.get('physical_device_id'))
    if not domain or not device: raise HTTPException(404, 'Домен или физическое устройство не найдено')
    existing=session.scalar(select(VLANDomainDevice).where(VLANDomainDevice.domain_id==domain_id,VLANDomainDevice.physical_device_id==device.id))
    if existing: return serialize(existing)
    obj=VLANDomainDevice(domain_id=domain_id,physical_device_id=device.id)
    session.add(obj); session.flush()
    # Пункт 2 правки "домен VLAN": сразу переносим на новое устройство то, что уже определено для
    # этого домена (assign_domain_vlans_to_device — общая с create_resource('vlan-domain-devices')
    # логика, см. её docstring в services/crud.py).
    assign_domain_vlans_to_device(domain_id, device.id, session)
    audit(session, 'vlan-domain-devices', obj.id, AuditAction.CREATE, f'Устройство добавлено в VLAN-домен «{domain.name}»')
    session.commit(); session.refresh(obj); return serialize(obj)

@router.post('/api/v1/vlan-domains/{domain_id}/sync')
def sync_vlan_domain(domain_id: str, payload: dict = Body(default={}), session: Session = Depends(get_db)):
    """Пункт 1 правки "домен VLAN" — payload может содержать replace=true (посылается
    VLANDomainFormModal.vue при смене устройства-источника, после подтверждения
    пользователем предупреждения о перезаписи): помимо обычного добавления недостающих VLAN
    участникам (как и раньше), ЕЩЁ убирает у них те VLAN этого домена (VLAN.domain_id==domain_id),
    которых больше нет у устройства-источника. Именно replace=true даёт то самое "все VLAN на
    устройствах домена будут перезаписаны на VLAN устройства-источника", о котором предупреждает
    форма — обычная синхронизация (кнопка "Синхронизировать" в VLANDomainsPanel.vue,
    replace не передаётся) только добавляет отсутствующее и НЕ трогает лишнее, это её штатное,
    уже используемое поведение, менять его не нужно."""
    replace = bool(payload.get('replace'))
    domain = session.get(VLANDomain, domain_id)
    if not domain: raise HTTPException(404, 'Домен VLAN не найден')
    if not domain.source_device_id: raise HTTPException(422, 'Для домена не задано устройство-источник')
    member_ids = session.scalars(select(VLANDomainDevice.physical_device_id).where(VLANDomainDevice.domain_id == domain_id)).all()
    source_ids = session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == domain.source_device_id)).all()
    source_vlans = session.scalars(select(VLAN).where(VLAN.id.in_(source_ids))).all() if source_ids else []
    created=0; updated=0
    # Domain-local VLAN definitions are shared by every member device, so each source VLAN is
    # resolved/created here once — not once per (device, source VLAN) pair as before, which was an
    # N+1 query (member devices × source VLANs) inside the loop below.
    domain_vlans_by_number = {v.vlan_id: v for v in session.scalars(select(VLAN).where(VLAN.domain_id == domain_id)).all()}
    target_by_source_id = {}
    for sv in source_vlans:
        target = domain_vlans_by_number.get(sv.vlan_id)
        if not target:
            target = VLAN(vlan_id=sv.vlan_id, name=sv.name, description=sv.description, domain_id=domain_id)
            session.add(target); session.flush(); created += 1
            domain_vlans_by_number[sv.vlan_id] = target
        target_by_source_id[sv.id] = target
    # Existing assignments for all member devices, loaded once instead of once per device.
    existing_by_device = {}
    if member_ids:
        for row in session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id.in_(member_ids))).all():
            existing_by_device.setdefault(row.physical_device_id, set()).add(row.vlan_id)
    domain_vlan_ids = {v.id for v in domain_vlans_by_number.values()}
    keep_ids = {t.id for t in target_by_source_id.values()}
    removed = 0
    for device_id in member_ids:
        if device_id == domain.source_device_id: continue
        existing_ids = existing_by_device.get(device_id, set())
        for sv in source_vlans:
            target = target_by_source_id[sv.id]
            if target.id not in existing_ids:
                session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=target.id, description=sv.description))
                updated += 1
        if replace:
            # Только VLAN ЭТОГО домена (domain_vlan_ids) — VLAN участника из ДРУГИХ доменов или
            # локальные (без domain_id вовсе) синхронизация трогать не должна ни в каком режиме.
            stale_ids = (existing_ids & domain_vlan_ids) - keep_ids
            if stale_ids:
                session.execute(delete(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == device_id, PhysicalDeviceVLAN.vlan_id.in_(stale_ids)))
                removed += len(stale_ids)
    detail = f'Синхронизация VLAN-домена: создано определений {created}, назначено {updated}'
    if replace: detail += f', убрано {removed}'
    audit(session, 'vlan-domains', domain_id, AuditAction.SYNC, detail)
    session.commit()
    return {'status':'ok','created_definitions':created,'assigned':updated,'removed':removed}

@router.post('/api/v1/devices/{device_id}/vlan-copy')
def copy_device_vlans(device_id: str, payload: dict, session: Session = Depends(get_db)):
    target = session.get(PhysicalDevice, device_id)
    source_id = payload.get('source_device_id')
    source = session.get(PhysicalDevice, source_id) if source_id else None
    if not target or not source: raise HTTPException(404, 'Исходное или целевое устройство не найдено')
    source_assignments = session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == source.id)).all()
    # Определения VLAN источника — одним запросом (раньше session.get на каждое назначение).
    source_vlan_ids = [a.vlan_id for a in source_assignments]
    source_vlans = {v.id: v for v in session.scalars(select(VLAN).where(VLAN.id.in_(source_vlan_ids)))} if source_vlan_ids else {}
    # Идемпотентность: VLAN с тем же номером и именем, что уже назначен целевому устройству, второй раз не
    # создаётся — повторный вызов раньше плодил дубли определений VLAN и назначений.
    already_on_target = {(v.vlan_id, v.name) for v in session.scalars(
        select(VLAN).join(PhysicalDeviceVLAN, PhysicalDeviceVLAN.vlan_id == VLAN.id).where(PhysicalDeviceVLAN.physical_device_id == target.id)
    )}
    created=0; assigned=0; skipped=0
    for a in source_assignments:
        sv=source_vlans.get(a.vlan_id)
        if not sv: continue
        if (sv.vlan_id, sv.name) in already_on_target:
            skipped+=1; continue
        already_on_target.add((sv.vlan_id, sv.name))
        # Copy creates a device-local definition so same ID/name can diverge later.
        v=VLAN(vlan_id=sv.vlan_id,name=sv.name,description=sv.description,domain_id=None)
        session.add(v); session.flush(); created+=1
        session.add(PhysicalDeviceVLAN(physical_device_id=target.id,vlan_id=v.id,ip_address=None,prefix_length=None,is_management=False,description=sv.description)); assigned+=1
    audit(session, 'devices', target.id, AuditAction.SYNC, f'Скопированы VLAN с устройства «{source.system_name or source.serial_number}»: определений {created}, назначено {assigned}' + (f', уже были на устройстве {skipped}' if skipped else ''))
    session.commit()
    return {'status':'ok','created_definitions':created,'assigned':assigned}

@router.post('/api/v1/device-vlans/bulk-assign')
def bulk_assign_vlan(payload: dict, session: Session = Depends(get_db)):
    """Назначает один существующий VLAN сразу нескольким устройствам — без создания формального
    VLANDomain (тот нужен для периодической синхронизации набора VLAN, см. sync_vlan_domain; это —
    разовое массовое назначение, по аналогии с bulk-редактором интерфейсов на фронтенде).
    IP-адрес в bulk-режиме не задаётся намеренно: одинаковый IP на нескольких устройствах в одном
    VLAN был бы некорректен, а различающиеся значения для каждого устройства — уже не bulk-действие;
    IP при необходимости проставляется потом по каждой записи individually."""
    device_ids = payload.get('physical_device_ids')
    vlan_id = payload.get('vlan_id')
    description = payload.get('description') or None
    if not isinstance(device_ids, list) or not device_ids:
        raise HTTPException(422, 'Укажите хотя бы одно устройство')
    if not vlan_id or not session.get(VLAN, vlan_id):
        raise HTTPException(404, 'VLAN не найден')
    found_ids = set(session.scalars(select(PhysicalDevice.id).where(PhysicalDevice.id.in_(device_ids))).all())  # одним запросом, а не session.get на каждое устройство
    missing = [d for d in device_ids if d not in found_ids]
    if missing:
        raise HTTPException(404, f'Устройства не найдены: {", ".join(missing)}')
    existing = set(session.scalars(
        select(PhysicalDeviceVLAN.physical_device_id).where(
            PhysicalDeviceVLAN.physical_device_id.in_(device_ids),
            PhysicalDeviceVLAN.vlan_id == vlan_id,
        )
    ).all())
    assigned = 0
    for device_id in dict.fromkeys(device_ids):  # dict.fromkeys: сохраняет порядок, убирает дубли
        if device_id in existing: continue
        session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan_id, description=description))
        assigned += 1
    audit(session, 'device-vlans', vlan_id, AuditAction.SYNC, f'Массовое назначение VLAN: устройств {assigned}, уже было назначено ранее {len(existing)}')
    session.commit()
    return {'status': 'ok', 'assigned': assigned, 'skipped_existing': len(existing)}

@router.post('/api/v1/seed')
def seed(session: Session = Depends(get_db)):
    # force=True: явное действие «восстановить стандартные значения» — маркер однократного
    # сидирования при запуске приложения (см. seed_defaults) здесь не применяется.
    seed_defaults(session, force=True); return {'status':'seeded','message':'Стандартные значения добавлены; пользовательские записи сохранены'}

@router.post('/api/v1/reports/inventory')
def generate_report(information_system_id: str | None = None, payload: dict | None = None, session: Session = Depends(get_db)):
    structural_unit_ids = (payload or {}).get('structural_unit_ids') or None
    cleanup_old_reports(REPORT_DIR)
    path = build_report(session, REPORT_DIR, information_system_id, structural_unit_ids)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

@router.post('/api/v1/reports/audit-log')
def generate_audit_log_report(date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None, session: Session = Depends(get_db)):
    cleanup_old_reports(REPORT_DIR)
    path = build_audit_log_report(session, REPORT_DIR, date_from, date_to, entity_type)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

REPORT_MEDIA_TYPES = {
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

@router.get('/api/v1/reports/download/{filename}')
def download_report(filename: str):
    path = (REPORT_DIR / filename).resolve()
    if path.parent != REPORT_DIR.resolve() or not path.is_file(): raise HTTPException(404, 'Файл отчета не найден')
    media_type = REPORT_MEDIA_TYPES.get(path.suffix.lower(), 'application/octet-stream')
    return FileResponse(path, media_type=media_type, filename=path.name)

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
    stack = session.get(DeviceStack, stack_id)
    if not stack: raise HTTPException(404, 'Стек не найден')

    member_rows = session.scalars(select(DeviceStackMember).where(DeviceStackMember.stack_id == stack_id).order_by(DeviceStackMember.position)).all()
    device_ids = [m.physical_device_id for m in member_rows]
    devices_by_id = {d.id: d for d in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(device_ids))).all()} if device_ids else {}
    # Порядок — по DeviceStackMember.position (физический номер участника в стеке), а не по тому,
    # в каком порядке БД вернула бы PhysicalDevice — devices_by_id используется только для
    # словарного доступа, реальный порядок задаёт member_rows.
    ordered_devices = [devices_by_id[d_id] for d_id in device_ids if d_id in devices_by_id]
    members = enrich_devices(ordered_devices, session)
    # stack_position теперь приходит из enrich_devices() само по себе (см. п.2 правки
    # "инвентаризация физических устройств" в serialization.py) — здесь довешиваем только
    # stack_member_id: id самой строки членства (не самого устройства), нужный
    # DeviceStackFormModal.vue для DELETE /device-stack-members/{id} при исключении из стека.
    member_row_id_by_device = {m.physical_device_id: m.id for m in member_rows}
    for item in members:
        item['stack_member_id'] = member_row_id_by_device.get(item['id'])

    connections = []
    if device_ids:
        interface_ids = session.scalars(select(DeviceInterface.id).where(DeviceInterface.physical_device_id.in_(device_ids))).all()
        if interface_ids:
            connections = session.scalars(
                select(Connection).where(Connection.source_interface_id.in_(interface_ids), Connection.destination_interface_id.in_(interface_ids))
            ).all()

    return {'stack': serialize(stack), 'members': members, 'connections': enrich_connections(connections, session)}


@router.post('/api/v1/device-stacks/{stack_id}/members')
def add_device_stack_member(stack_id: str, payload: dict, session: Session = Depends(get_db)):
    """Идемпотентно (как и add_vlan_domain_member выше) — повторное добавление уже состоящего в
    ЭТОМ ЖЕ стеке устройства просто возвращает существующую запись членства, не 409. Попытка
    добавить устройство, состоящее в ДРУГОМ стеке, всё равно упадёт понятной 409 —
    _validate_device_stack_member_entry (см. services/crud.py) вызывается ниже через
    validate_resource, как и для любого generic-ресурса."""
    stack = session.get(DeviceStack, stack_id)
    device = session.get(PhysicalDevice, payload.get('physical_device_id'))
    if not stack or not device: raise HTTPException(404, 'Стек или физическое устройство не найдено')
    existing = session.scalar(select(DeviceStackMember).where(DeviceStackMember.physical_device_id == device.id))
    if existing and existing.stack_id == stack_id: return serialize(existing)
    data = {'stack_id': stack_id, 'physical_device_id': device.id, 'position': payload.get('position', 1)}
    validate_resource(DeviceStackMember, data, session, item_id=None)
    obj = DeviceStackMember(**data)
    session.add(obj); session.flush()
    audit(session, 'device-stack-members', obj.id, AuditAction.CREATE, f'Устройство добавлено в стек «{stack.name}»')
    session.commit(); session.refresh(obj); return serialize(obj)


@router.get('/', include_in_schema=False)
def frontend_index():
    """Единственный UI — собранный Vue-фронтенд (frontend-vue/dist), см. config.py:FRONTEND_DIR."""
    index = FRONTEND_DIR / 'index.html'
    if not index.is_file():
        raise HTTPException(500, f'Файл интерфейса не найден: {index}. Соберите frontend-vue (npm run build).')
    return FileResponse(index, media_type='text/html; charset=utf-8')

@router.get('/icons.svg', include_in_schema=False)
def frontend_icons():
    """Спрайт иконок Vue-интерфейса (frontend-vue/public/icons.svg, копируется в dist при
    сборке) — компоненты ссылаются на него абсолютным путём '<use href="/icons.svg#i-...">'."""
    icons = FRONTEND_DIR / 'icons.svg'
    if icons.is_file(): return FileResponse(icons, media_type='image/svg+xml')
    raise HTTPException(404, 'icons.svg не найден')

@router.get('/favicon.ico', include_in_schema=False)
def favicon():
    icon = FRONTEND_DIR / 'favicon.ico'
    if icon.is_file(): return FileResponse(icon)
    raise HTTPException(404, 'favicon.ico не найден')
