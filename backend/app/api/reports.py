"""Формирование и скачивание отчётов: инвентаризация, журнал аудита (код-ревью п. 10)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import REPORT_DIR
from ..db import get_db
from ..reporting import build_report
from ..services.audit_export import build_audit_log_report, is_audit_report_name
from ..services.auth import require_admin_if_auth_enabled
from ..services.report_cleanup import cleanup_before_new_report
from ..services.structural_appendix_docx import StructuralAppendixError, build_structural_appendix
from .report_schemas import InventoryReportRequest, StructuralAppendixRequest

router = APIRouter(tags=['Reports'])

@router.post('/api/v1/reports/inventory')
def generate_report(information_system_id: str | None = None, body: InventoryReportRequest | None = None, session: Session = Depends(get_db)):
    """Excel-отчёт «Регламентный отчёт». Тело (необязательное): structural_unit_ids — ограничение оборудованием выбранных структурных единиц."""
    structural_unit_ids = (body or InventoryReportRequest()).structural_unit_ids
    cleanup_before_new_report(REPORT_DIR)
    path = build_report(session, REPORT_DIR, information_system_id, structural_unit_ids)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

@router.post('/api/v1/reports/audit-log', dependencies=[Depends(require_admin_if_auth_enabled)])
def generate_audit_log_report(date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None, session: Session = Depends(get_db)):
    cleanup_before_new_report(REPORT_DIR)
    path = build_audit_log_report(session, REPORT_DIR, date_from, date_to, entity_type)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

@router.post('/api/v1/reports/structural-appendix')
def generate_structural_appendix(body: StructuralAppendixRequest | None = None, session: Session = Depends(get_db)):
    """Word-документ «Приложение к структурной схеме» (3 таблицы: линии связи, VLAN, оборудование).

    Тело (необязательное): is_name — короткое имя ИС для заголовков (по умолчанию «ЕАИС ТО»; ведущее «ЕАИС»/«ИС» в заголовках не дублируется),
    structural_unit_ids — ограничение оборудованием выбранных структурных единиц, как у регламентированного отчёта."""
    body = body or StructuralAppendixRequest()
    cleanup_before_new_report(REPORT_DIR)
    try:
        path = build_structural_appendix(session, REPORT_DIR, is_name=body.is_name, structural_unit_ids=body.structural_unit_ids)
    except StructuralAppendixError as e:
        raise HTTPException(422, str(e)) from e
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

REPORT_MEDIA_TYPES = {
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

@router.get('/api/v1/reports/download/{filename}')
def download_report(filename: str, request: Request):
    # Отчёт журнала аудита (логины, IP-адреса, неудачные входы) — только администратору, как и его формирование: иначе имя файла из журнала
    # прокси, истории браузера или чата открыло бы данные роли viewer. Проверка идёт ДО поиска файла и по имени без учёта регистра и формы
    # Unicode (в Windows и macOS файл находится при любом регистре), а после resolve() — ещё раз по реальному имени файла.
    if is_audit_report_name(filename):
        require_admin_if_auth_enabled(request)
    path = (REPORT_DIR / filename).resolve()
    if path.parent != REPORT_DIR.resolve() or not path.is_file(): raise HTTPException(404, 'Файл отчета не найден')
    if is_audit_report_name(path.name):
        require_admin_if_auth_enabled(request)
    media_type = REPORT_MEDIA_TYPES.get(path.suffix.lower(), 'application/octet-stream')
    return FileResponse(path, media_type=media_type, filename=path.name)
