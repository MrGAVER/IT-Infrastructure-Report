"""Служебные эндпоинты: health, диагностика целостности, счётчики, восстановление стандартных значений."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import APP_VERSION
from ..db import get_db
from ..models import Connection, Container, InformationSystem, PhysicalDevice, SoftwareAsset, VLAN, VirtualMachine
from ..services.catalogs import seed_defaults
from ..services.integrity import find_duplicate_open_port_numbers, find_orphaned_owner_references

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
    устройства, группа портов, протоколы информационной системы) — данные, появившиеся до правила уникальности. Только чтение; новые
    повторы API отклоняет с 422. ok=True и пустой duplicates — исправлять нечего."""
    duplicates = find_duplicate_open_port_numbers(session)
    return {'ok': not duplicates, 'total': len(duplicates), 'duplicates': duplicates}

@router.get('/api/v1/dashboard')
def dashboard(session: Session = Depends(get_db)):
    entities = {'information_systems': InformationSystem, 'physical_devices': PhysicalDevice, 'virtual_machines': VirtualMachine, 'containers': Container, 'connections': Connection, 'vlan': VLAN, 'software': SoftwareAsset}
    return {key: session.scalar(select(func.count()).select_from(model)) or 0 for key, model in entities.items()}

@router.post('/api/v1/seed')
def seed(session: Session = Depends(get_db)):
    # force=True: явное действие «восстановить стандартные значения» — маркер однократного
    # сидирования при запуске приложения (см. seed_defaults) здесь не применяется.
    seed_defaults(session, force=True); return {'status':'seeded','message':'Стандартные значения добавлены; пользовательские записи сохранены'}
