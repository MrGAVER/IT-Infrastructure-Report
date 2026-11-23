"""Устаревшие списки без пагинации: информационные системы, устройства, ВМ.

Остались для совместимости; новые экраны используют /api/v1/resources/{resource} с пагинацией.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import InformationSystem, PhysicalDevice, VirtualMachine
from ..services.serialization import enrich_devices, enrich_information_systems, serialize

router = APIRouter(tags=["Lists"])


@router.get("/api/v1/information-systems")
def list_information_systems(session: Session = Depends(get_db)):
    # Обогащённые записи (как в /resources/information-systems): к полям ИС добавлены читаемые сводки и IP-адреса
    # (ip_addresses) для столбца «IP-адреса» экрана «Информационные системы».
    rows = session.scalars(select(InformationSystem).order_by(InformationSystem.name)).all()
    return enrich_information_systems(rows, session)


@router.get("/api/v1/devices")
def list_devices(session: Session = Depends(get_db)):
    rows = session.scalars(select(PhysicalDevice).order_by(PhysicalDevice.system_name.is_(None).desc(), PhysicalDevice.system_name)).all()
    return {"items": enrich_devices(rows, session), "total": len(rows)}


@router.get("/api/v1/vms")
def list_vms(session: Session = Depends(get_db)):
    rows = session.scalars(select(VirtualMachine).order_by(VirtualMachine.name)).all()
    return {"items": [serialize(x) for x in rows], "total": len(rows)}
