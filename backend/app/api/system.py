from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..config import APP_VERSION, FRONTEND_DIR, REPORT_DIR
from ..db import get_db
from ..models import (Connection, Container, InformationSystem, PhysicalDevice, SoftwareAsset, VLAN, VirtualMachine, DeviceInterface, InterfaceIP, PhysicalDeviceVLAN, Organization, Department, Building, Room, Rack, DeviceType, Manufacturer, DeviceModel, OperatingSystemCategory, OperatingSystem, EmbeddedOperatingSystem, InterfaceType, InterfaceSpeed, ConnectionType, ProtocolPortCatalog, VLANDomain, VLANDomainDevice, ISDepartment, ISIP, ISProtocol, ISDevice, ISVM, VMIP, InterfaceVLAN)
from ..services.catalogs import seed_defaults
from ..services.serialization import enrich_devices, serialize
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
    session.add(obj); session.commit(); session.refresh(obj); return serialize(obj)

@router.post('/api/v1/vlan-domains/{domain_id}/sync')
def sync_vlan_domain(domain_id: str, session: Session = Depends(get_db)):
    domain = session.get(VLANDomain, domain_id)
    if not domain: raise HTTPException(404, 'Домен VLAN не найден')
    if not domain.source_device_id: raise HTTPException(422, 'Для домена не задано устройство-источник')
    member_ids = session.scalars(select(VLANDomainDevice.physical_device_id).where(VLANDomainDevice.domain_id == domain_id)).all()
    source_ids = session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == domain.source_device_id)).all()
    source_vlans = session.scalars(select(VLAN).where(VLAN.id.in_(source_ids))).all() if source_ids else []
    created=0; updated=0
    for device_id in member_ids:
        if device_id == domain.source_device_id: continue
        existing_ids = set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == device_id)).all())
        for sv in source_vlans:
            target = session.scalar(select(VLAN).where(VLAN.domain_id == domain_id, VLAN.vlan_id == sv.vlan_id))
            if not target:
                target = VLAN(vlan_id=sv.vlan_id, name=sv.name, description=sv.description, domain_id=domain_id)
                session.add(target); session.flush(); created += 1
            if target.id not in existing_ids:
                session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=target.id, description=sv.description))
                updated += 1
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
    session.commit()
    return {'status':'ok','created_definitions':created,'assigned':assigned}

@router.post('/api/v1/seed')
def seed(session: Session = Depends(get_db)):
    seed_defaults(session); return {'status':'seeded','message':'Стандартные значения добавлены; пользовательские записи сохранены'}


@router.post('/api/v1/seed/test')
def seed_test_data(session: Session = Depends(get_db)):
    """Temporary demo-data generator. Creates a coherent test dataset without deleting user data."""
    from datetime import datetime
    from uuid import uuid4

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    tag = f"TEST-{stamp}-{uuid4().hex[:4]}"

    def add(cls, **kwargs):
        obj = cls(**kwargs)
        session.add(obj)
        session.flush()
        return obj

    # Catalogs / location
    org = add(Organization, name=f"{tag} Организация", short_name="TEST")
    dept = add(Department, name=f"{tag} ИТ")
    building = add(Building, name=f"{tag} ЦОД-1", address="Тестовый адрес")
    room = add(Room, building_id=building.id, name="Серверная")
    rack = add(Rack, room_id=room.id, name="Стойка R01", height_u=42)
    server_type = add(DeviceType, name=f"{tag} Сервер")
    switch_type = add(DeviceType, name=f"{tag} Коммутатор")
    manufacturer = add(Manufacturer, name=f"{tag} Manufacturer")
    server_model = add(DeviceModel, manufacturer_id=manufacturer.id, device_type_id=server_type.id, model="TEST-SERVER-01")
    switch_model = add(DeviceModel, manufacturer_id=manufacturer.id, device_type_id=switch_type.id, model="TEST-SWITCH-01")
    os_cat = add(OperatingSystemCategory, name=f"{tag} Серверная ОС")
    server_os = add(OperatingSystem, category_id=os_cat.id, name="Windows Server", version="2022", vendor="Microsoft")
    embedded = add(EmbeddedOperatingSystem, name="TEST-NetworkOS", version="1.0", vendor=tag)
    eth = add(InterfaceType, name=f"{tag} Ethernet")
    speed = add(InterfaceSpeed, name=f"{tag} 1 Gbps")
    conn_type = add(ConnectionType, name=f"{tag} Витая пара")
    proto = add(ProtocolPortCatalog, port=443, protocol_type="TCP/HTTPS", description="Web")
    vlan = add(VLAN, vlan_id=900, name=f"{tag} TEST-MGMT", description="Тестовый VLAN")

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
    container = add(Container, name=f"{tag}-WEB", virtual_machine_id=vm.id, purpose="Тестовый web-контейнер", management_ip="10.255.90.21")
    software = add(SoftwareAsset, name=f"{tag} Web Server", category="Web-server", vendor="Test", version="1.0")

    # Information system
    info = add(InformationSystem, number=None, name=f"{tag} Информационная система", description="Тестовая ИС для проверки интерфейса и Excel", purpose="Демонстрация связей реестра", localization="ЦОД-1", support_method="Внутренняя поддержка", process_description="Тестовый процесс функционирования", crypto_protection_enabled=False, siem_enabled=True, status="active")
    add(ISDepartment, information_system_id=info.id, department_id=dept.id)
    add(ISIP, information_system_id=info.id, ip_address="10.255.90.20", purpose="Взаимодействие с приложением", protocol="HTTPS", external_interaction=False, virtual_machine_id=vm.id)
    add(ISProtocol, information_system_id=info.id, protocol="TCP/HTTPS", port=443, protocol_catalog_id=proto.id, description="Web-доступ")
    add(ISDevice, information_system_id=info.id, physical_device_id=server.id, role="Физический сервер")
    add(ISVM, information_system_id=info.id, virtual_machine_id=vm.id, role="Сервер приложения")
    add(ISVM, information_system_id=info.id, virtual_machine_id=vm.id, role="Web")

    session.commit()
    return {'status':'ok','message':'Тестовые данные добавлены','tag':tag,'created':{'devices':2,'interfaces':2,'connections':1,'vms':1,'containers':1,'information_systems':1,'vlans':1}}

@router.post('/api/v1/reports/inventory')
def generate_report(information_system_id: str | None = None, session: Session = Depends(get_db)):
    path = build_report(session, REPORT_DIR, information_system_id)
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
    index = FRONTEND_DIR / 'index.html'
    if not index.is_file(): raise HTTPException(500, f'Файл интерфейса не найден: {index}')
    return FileResponse(index, media_type='text/html; charset=utf-8')

@router.get('/favicon.ico', include_in_schema=False)
def favicon():
    icon = FRONTEND_DIR / 'favicon.ico'
    if icon.is_file(): return FileResponse(icon)
    raise HTTPException(404, 'favicon.ico не найден')
