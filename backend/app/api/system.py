from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..config import APP_VERSION, ENABLE_TEST_DATA_ENDPOINT, FRONTEND_DIR, REPORT_DIR
from ..db import get_db
from ..models import (Connection, Container, InformationSystem, PhysicalDevice, SoftwareAsset, VLAN, VirtualMachine, DeviceInterface, InterfaceIP, PhysicalDeviceVLAN, Department, Building, Room, Rack, DeviceCategory, DeviceType, Manufacturer, DeviceModel, OperatingSystemCategory, OperatingSystem, EmbeddedOperatingSystem, InterfaceType, InterfaceSpeed, ConnectionType, ProtocolPortCatalog, VLANDomain, VLANDomainDevice, ISDepartment, ISIP, ISProtocol, ISDevice, ISVM, VMIP, InterfaceVLAN, SupportMethod)
from ..services.catalogs import seed_defaults
from ..services.serialization import enrich_devices, serialize
from ..services.audit_export import build_audit_log_report
from ..services.crud import audit
from ..constants import AuditAction
from ..reporting import build_report

router = APIRouter(tags=['System'])

@router.get('/api/v1/health')
def health(): return {'status':'ok','service':'infra-registry','version':APP_VERSION}

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
    audit(session, 'vlan-domain-devices', obj.id, AuditAction.CREATE, f'Устройство добавлено в VLAN-домен «{domain.name}»')
    session.commit(); session.refresh(obj); return serialize(obj)

@router.post('/api/v1/vlan-domains/{domain_id}/sync')
def sync_vlan_domain(domain_id: str, session: Session = Depends(get_db)):
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
    for device_id in member_ids:
        if device_id == domain.source_device_id: continue
        existing_ids = existing_by_device.get(device_id, set())
        for sv in source_vlans:
            target = target_by_source_id[sv.id]
            if target.id not in existing_ids:
                session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=target.id, description=sv.description))
                updated += 1
    audit(session, 'vlan-domains', domain_id, AuditAction.SYNC, f'Синхронизация VLAN-домена: создано определений {created}, назначено {updated}')
    session.commit()
    return {'status':'ok','created_definitions':created,'assigned':updated}

@router.post('/api/v1/devices/{device_id}/vlan-copy')
def copy_device_vlans(device_id: str, payload: dict, session: Session = Depends(get_db)):
    target = session.get(PhysicalDevice, device_id)
    source_id = payload.get('source_device_id')
    source = session.get(PhysicalDevice, source_id) if source_id else None
    if not target or not source: raise HTTPException(404, 'Исходное или целевое устройство не найдено')
    source_assignments = session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == source.id)).all()
    created=0; assigned=0
    for a in source_assignments:
        sv=session.get(VLAN,a.vlan_id)
        if not sv: continue
        # Copy creates a device-local definition so same ID/name can diverge later.
        v=VLAN(vlan_id=sv.vlan_id,name=sv.name,description=sv.description,domain_id=None)
        session.add(v); session.flush(); created+=1
        session.add(PhysicalDeviceVLAN(physical_device_id=target.id,vlan_id=v.id,ip_address=None,prefix_length=None,is_management=False,description=sv.description)); assigned+=1
    audit(session, 'devices', target.id, AuditAction.SYNC, f'Скопированы VLAN с устройства «{source.system_name or source.serial_number}»: определений {created}, назначено {assigned}')
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
    missing = [d for d in device_ids if not session.get(PhysicalDevice, d)]
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
    seed_defaults(session); return {'status':'seeded','message':'Стандартные значения добавлены; пользовательские записи сохранены'}


@router.post('/api/v1/seed/test')
def seed_test_data(session: Session = Depends(get_db)):
    """Temporary demo-data generator. Creates a coherent test dataset without deleting user data.

    Enabled by default (INFRA_REGISTRY_ENABLE_TEST_DATA=1) — it backs the visible
    "Заполнить тестовыми данными" button on the Dashboard for the single-user local/EXE
    deployment. For a shared multi-user server deployment where this button shouldn't be
    exposed, set INFRA_REGISTRY_ENABLE_TEST_DATA=0 to disable the endpoint."""
    if not ENABLE_TEST_DATA_ENDPOINT:
        raise HTTPException(404, 'Эндпоинт отключен. Установите переменную окружения INFRA_REGISTRY_ENABLE_TEST_DATA=1, чтобы включить')
    from datetime import datetime
    from uuid import uuid4

    # Локальное время сервера намеренно: это человекочитаемый тег тестового набора для
    # администратора, который его сгенерировал (см. computed.local_timestamp_suffix для той же
    # логики в именах файлов отчётов), а не хранимая/сравниваемая метка времени.
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tag = f"TEST-{stamp}-{uuid4().hex[:4]}"

    def add(cls, **kwargs):
        obj = cls(**kwargs)
        session.add(obj)
        session.flush()
        return obj

    # Catalogs / location
    dept = add(Department, name=f"{tag} ИТ")
    building = add(Building, name=f"{tag} ЦОД-1", address="Тестовый адрес")
    room = add(Room, building_id=building.id, name="Серверная")
    rack = add(Rack, room_id=room.id, name="Стойка R01", height_u=42)
    # category_id обязателен (см. app/models.py:DeviceType, ТЗ диаграммы топологии сети) — категории
    # "Серверы и СХД"/"Коммутаторы" уже засеяны services/catalogs.seed_defaults() на старте приложения.
    server_category = session.scalar(select(DeviceCategory).where(DeviceCategory.name == "Серверы и СХД"))
    switch_category = session.scalar(select(DeviceCategory).where(DeviceCategory.name == "Коммутаторы"))
    server_type = add(DeviceType, name=f"{tag} Сервер", category_id=server_category.id)
    switch_type = add(DeviceType, name=f"{tag} Коммутатор", category_id=switch_category.id)
    manufacturer = add(Manufacturer, name=f"{tag} Manufacturer")
    server_model = add(DeviceModel, manufacturer_id=manufacturer.id, device_type_id=server_type.id, model="TEST-SERVER-01")
    switch_model = add(DeviceModel, manufacturer_id=manufacturer.id, device_type_id=switch_type.id, model="TEST-SWITCH-01")
    os_cat = add(OperatingSystemCategory, name=f"{tag} Серверная ОС")
    server_os = add(OperatingSystem, category_id=os_cat.id, name="Windows Server", version="2022", vendor="Microsoft")
    embedded = add(EmbeddedOperatingSystem, name=f"{tag}-NetworkOS", version="1.0", vendor=tag)
    eth = add(InterfaceType, name=f"{tag} Ethernet")
    speed = add(InterfaceSpeed, name=f"{tag} 1 Gbps")
    conn_type = add(ConnectionType, name=f"{tag} Витая пара")
    # 443/TCP-HTTPS — реальная запись справочника портов, а не тестовые данные конкретного
    # прогона (в отличие от остальных сущностей здесь), поэтому не тегируем её именем/номером,
    # а переиспользуем, если уже создана предыдущим вызовом (иначе второй вызов /seed/test
    # падал на UNIQUE(port, protocol_type) — см. регрессионный тест test_seed_test_is_additive_and_repeatable).
    proto = session.execute(
        select(ProtocolPortCatalog).where(
            ProtocolPortCatalog.port == 443, ProtocolPortCatalog.protocol_type == "TCP/HTTPS"
        )
    ).scalar_one_or_none()
    if proto is None:
        proto = add(ProtocolPortCatalog, port=443, protocol_type="TCP/HTTPS", description="Web")
    vlan = add(VLAN, vlan_id=900, name=f"{tag} TEST-MGMT", description="Тестовый VLAN")
    support_method = add(SupportMethod, name=f"{tag} Внутренняя поддержка")

    # Devices and interfaces
    server = add(PhysicalDevice, device_type_id=server_type.id, manufacturer_id=manufacturer.id, model_id=server_model.id, serial_number=f"{tag}-SRV-SN", system_name=f"{tag}-SRV", operating_system_id=server_os.id, embedded_os_id=None, siem_enabled=True, building_id=building.id, room_id=room.id, rack_id=rack.id, rack_position="10U", description="Тестовый сервер")
    switch = add(PhysicalDevice, device_type_id=switch_type.id, manufacturer_id=manufacturer.id, model_id=switch_model.id, serial_number=f"{tag}-SW-SN", system_name=f"{tag}-SW", embedded_os_id=embedded.id, siem_enabled=True, building_id=building.id, room_id=room.id, rack_id=rack.id, rack_position="20U", description="Тестовый коммутатор")
    srv_if = add(DeviceInterface, physical_device_id=server.id, name="eth0", interface_type_id=eth.id, speed_id=speed.id, is_management=True)
    sw_if = add(DeviceInterface, physical_device_id=switch.id, name="Gi1/0/1", interface_type_id=eth.id, speed_id=speed.id, is_management=False)
    add(InterfaceIP, interface_id=srv_if.id, ip_address="10.255.90.10", prefix_length=24, purpose="Management", is_management=True)
    add(InterfaceIP, interface_id=sw_if.id, ip_address="10.255.90.1", prefix_length=24, purpose="Test network", is_management=False)
    add(PhysicalDeviceVLAN, physical_device_id=switch.id, vlan_id=vlan.id, ip_address="10.255.90.1", prefix_length=24, is_management=True, description="Management VLAN")
    add(InterfaceVLAN, interface_id=sw_if.id, vlan_id=vlan.id, mode="access")
    add(Connection, source_interface_id=srv_if.id, destination_interface_id=sw_if.id, connection_type_id=conn_type.id, purpose="Тестовое подключение", is_active=True)

    # VM + container + software
    vm = add(VirtualMachine, name=f"{tag}-APP01", operating_system_id=server_os.id, physical_device_id=server.id, purpose="Тестовое приложение", status="active")
    add(VMIP, virtual_machine_id=vm.id, ip_address="10.255.90.20", prefix_length=24, purpose="Application", is_management=True)
    add(Container, name=f"{tag}-WEB", virtual_machine_id=vm.id, purpose="Тестовый web-контейнер", management_ip="10.255.90.21")
    add(SoftwareAsset, name=f"{tag} Web Server", category="Web-server", vendor="Test", version="1.0")

    # Information system
    info = add(InformationSystem, number=None, name=f"{tag} Информационная система", description="Тестовая ИС для проверки интерфейса и Excel", purpose="Демонстрация связей реестра", localization="ЦОД-1", support_method_id=support_method.id, process_description="Тестовый процесс функционирования", crypto_protection_enabled=False, siem_enabled=True, status="active")
    add(ISDepartment, information_system_id=info.id, department_id=dept.id)
    add(ISIP, information_system_id=info.id, ip_address="10.255.90.20", purpose="Взаимодействие с приложением", protocol="HTTPS", external_interaction=False, virtual_machine_id=vm.id)
    add(ISProtocol, information_system_id=info.id, protocol="TCP/HTTPS", port=443, protocol_catalog_id=proto.id, description="Web-доступ")
    add(ISDevice, information_system_id=info.id, physical_device_id=server.id, role="Физический сервер")
    add(ISVM, information_system_id=info.id, virtual_machine_id=vm.id, role="Сервер приложения")
    add(ISVM, information_system_id=info.id, virtual_machine_id=vm.id, role="Web")

    session.commit()
    return {'status':'ok','message':'Тестовые данные добавлены','tag':tag,'created':{'devices':2,'interfaces':2,'connections':1,'vms':1,'containers':1,'information_systems':1,'vlans':1}}

@router.post('/api/v1/reports/inventory')
def generate_report(information_system_id: str | None = None, payload: dict | None = None, session: Session = Depends(get_db)):
    structural_unit_ids = (payload or {}).get('structural_unit_ids') or None
    path = build_report(session, REPORT_DIR, information_system_id, structural_unit_ids)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

@router.post('/api/v1/reports/audit-log')
def generate_audit_log_report(date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None, session: Session = Depends(get_db)):
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
