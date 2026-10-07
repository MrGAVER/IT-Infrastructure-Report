"""Формирование и скачивание отчётов: инвентаризация, журнал аудита (код-ревью п. 10)."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import REPORT_DIR
from ..db import get_db
from ..reporting import build_report
from ..services.audit_export import build_audit_log_report
from ..services.report_cleanup import cleanup_old_reports

router = APIRouter(tags=['Reports'])

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
