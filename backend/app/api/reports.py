"""Формирование и скачивание отчётов: инвентаризация, журнал аудита (код-ревью п. 10)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import REPORT_DIR
from ..db import get_db
from ..reporting import build_report
from ..services.audit_export import build_audit_log_report
from ..services.report_cleanup import cleanup_before_new_report
from ..services.report_params import parse_structural_unit_ids
from ..services.structural_appendix_docx import DEFAULT_IS_NAME, StructuralAppendixError, build_structural_appendix

router = APIRouter(tags=['Reports'])

@router.post('/api/v1/reports/inventory')
def generate_report(information_system_id: str | None = None, payload: dict | None = None, session: Session = Depends(get_db)):
    structural_unit_ids = parse_structural_unit_ids((payload or {}).get('structural_unit_ids'))
    cleanup_before_new_report(REPORT_DIR)
    path = build_report(session, REPORT_DIR, information_system_id, structural_unit_ids)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

@router.post('/api/v1/reports/audit-log')
def generate_audit_log_report(date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None, session: Session = Depends(get_db)):
    cleanup_before_new_report(REPORT_DIR)
    path = build_audit_log_report(session, REPORT_DIR, date_from, date_to, entity_type)
    return {'file_name':path.name,'download_url':f'/api/v1/reports/download/{path.name}'}

@router.post('/api/v1/reports/structural-appendix')
def generate_structural_appendix(payload: dict | None = None, session: Session = Depends(get_db)):
    """Word-документ «Приложение к структурной схеме» (3 таблицы: линии связи, VLAN, оборудование).

    Тело (необязательное): is_name — короткое имя ИС для заголовков (по умолчанию «ЕАИС ТО»; ведущее «ЕАИС»/«ИС» в заголовках не дублируется),
    structural_unit_ids — ограничение оборудованием выбранных структурных единиц, как у регламентированного отчёта."""
    payload = payload or {}
    is_name = payload.get('is_name', DEFAULT_IS_NAME)
    if not isinstance(is_name, str):
        raise HTTPException(422, 'Короткое имя ИС должно быть строкой')
    unit_ids = parse_structural_unit_ids(payload.get('structural_unit_ids'))
    cleanup_before_new_report(REPORT_DIR)
    try:
        path = build_structural_appendix(session, REPORT_DIR, is_name=is_name, structural_unit_ids=unit_ids)
    except StructuralAppendixError as e:
        raise HTTPException(422, str(e)) from e
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
