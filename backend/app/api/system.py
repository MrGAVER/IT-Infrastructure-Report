"""Служебные эндпоинты: health, диагностика целостности, счётчики, восстановление стандартных значений."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Connection, Container, InformationSystem, PhysicalDevice, SoftwareAsset, VLAN, VirtualMachine
from ..services.catalogs import seed_defaults
from ..services.integrity import find_duplicate_open_port_numbers, find_off_port_subinterfaces, find_orphaned_owner_references, find_stale_group_subinterfaces, find_stale_subinterfaces

router = APIRouter(tags=['System'])

@router.get('/api/v1/health')
def health():
    """Проверка живости для Docker, CI и балансировщиков. Путь публичный (до входа), поэтому версию приложения не отдаёт: по ней
    посторонний подбирает известные уязвимости. Версия — в CHANGELOG.md и, если включён ENABLE_DOCS, в /openapi.json."""
    return {'status': 'ok', 'service': 'infra-registry'}

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

@router.get('/api/v1/integrity/stale-subinterfaces')
def stale_subinterfaces_report(session: Session = Depends(get_db)):
    """Диагностика подинтерфейсов на недоступном VLAN. В `subinterfaces` — подинтерфейсы портов с причиной `reason`:
    `device` — VLAN больше не разрешён устройству (сняли с устройства, убрали из его типа или перенесли в другой домен);
    `port` — VLAN разрешён устройству, но не выбран на самом порту (VLAN подинтерфейса обязан быть одним из VLAN порта). В
    `group_subinterfaces` — шаблоны подинтерфейсов групп портов на VLAN, которого у группы больше нет. Такие записи система
    не удаляет сама — на них IP-адреса и открытые порты; форма устройства покажет их с предупреждением и потребует выбрать
    другой VLAN, вернуть VLAN порту/группе или удалить подинтерфейс. Только чтение. ok=True и пустые списки — исправлять
    нечего; total — число записей в обоих списках."""
    ports = sorted(
        [{**item, 'reason': 'device'} for item in find_stale_subinterfaces(session)] + [{**item, 'reason': 'port'} for item in find_off_port_subinterfaces(session)],
        key=lambda d: (d['device_name'], d['port_name'], d['subinterface_name']),
    )
    groups = find_stale_group_subinterfaces(session)
    total = len(ports) + len(groups)
    return {'ok': total == 0, 'total': total, 'subinterfaces': ports, 'group_subinterfaces': groups}

_DASHBOARD_ENTITIES = {
    'information_systems': InformationSystem,
    'physical_devices': PhysicalDevice,
    'virtual_machines': VirtualMachine,
    'containers': Container,
    'connections': Connection,
    'vlan': VLAN,
    'software': SoftwareAsset,
}

@router.get('/api/v1/dashboard')
def dashboard(session: Session = Depends(get_db)):
    """Счётчики главной страницы одним запросом: SELECT (SELECT count(*) FROM …) AS …, … — вместо отдельного COUNT на каждую сущность
    — одно обращение к БД, а не по одному на сущность, на каждом открытии главной страницы."""
    counters = [
        select(func.count()).select_from(model).scalar_subquery().label(key)
        for key, model in _DASHBOARD_ENTITIES.items()
    ]
    row = session.execute(select(*counters)).one()
    return {key: row._mapping[key] or 0 for key in _DASHBOARD_ENTITIES}

@router.post('/api/v1/seed')
def seed(session: Session = Depends(get_db)):
    # force=True: явное действие «восстановить стандартные значения» — маркер однократного
    # сидирования при запуске приложения (см. seed_defaults) здесь не применяется.
    seed_defaults(session, force=True); return {'status':'seeded','message':'Стандартные значения добавлены; пользовательские записи сохранены'}
