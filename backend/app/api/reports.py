"""Формирование и скачивание отчётов: инвентаризация, журнал аудита."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import REPORT_DIR
from ..db import get_db
from ..reporting import build_report
from ..services.audit_export import audit_report_dir, build_audit_log_report, is_audit_report_name
from ..services.auth import require_admin_if_auth_enabled
from ..services.report_cleanup import cleanup_before_new_report
from ..services.structural_appendix_docx import StructuralAppendixError, build_structural_appendix
from .report_schemas import InventoryReportRequest, StructuralAppendixRequest

router = APIRouter(tags=["Reports"])


@router.post("/api/v1/reports/inventory")
def generate_report(
    information_system_id: str | None = None, body: InventoryReportRequest | None = None, session: Session = Depends(get_db)
):
    """Excel-отчёт «Регламентный отчёт». Тело (необязательное): structural_unit_ids — ограничение оборудованием выбранных
    структурных единиц."""
    structural_unit_ids = (body or InventoryReportRequest()).structural_unit_ids
    cleanup_before_new_report(REPORT_DIR)
    path = build_report(session, REPORT_DIR, information_system_id, structural_unit_ids)
    return {"file_name": path.name, "download_url": f"/api/v1/reports/download/{path.name}"}


@router.post("/api/v1/reports/audit-log", dependencies=[Depends(require_admin_if_auth_enabled)])
def generate_audit_log_report(
    date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None, session: Session = Depends(get_db)
):
    cleanup_before_new_report(REPORT_DIR)
    path = build_audit_log_report(session, REPORT_DIR, date_from, date_to, entity_type)
    # Отчёт лежит в подкаталоге audit/ и скачивается отдельным эндпоинтом (только администратору); общий до него не дотягивается.
    return {"file_name": path.name, "download_url": f"/api/v1/reports/audit-log/download/{path.name}"}


@router.post("/api/v1/reports/structural-appendix")
def generate_structural_appendix(body: StructuralAppendixRequest | None = None, session: Session = Depends(get_db)):
    """Word-документ «Приложение к структурной схеме» (3 таблицы: линии связи, VLAN, оборудование).

    Тело (необязательное): is_name — короткое имя ИС для заголовков (по умолчанию «ЕАИС ТО»; ведущее «ЕАИС»/«ИС» в заголовках не
    дублируется), structural_unit_ids — ограничение оборудованием выбранных структурных единиц, как у регламентированного
    отчёта."""
    body = body or StructuralAppendixRequest()
    cleanup_before_new_report(REPORT_DIR)
    try:
        path = build_structural_appendix(session, REPORT_DIR, is_name=body.is_name, structural_unit_ids=body.structural_unit_ids)
    except StructuralAppendixError as e:
        raise HTTPException(422, str(e)) from e
    return {"file_name": path.name, "download_url": f"/api/v1/reports/download/{path.name}"}


REPORT_MEDIA_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _report_file_response(directory: Path, filename: str) -> FileResponse:
    """Файл отчёта строго из `directory` (не из его подкаталогов и не выше): после resolve() родитель должен совпасть с каталогом."""
    path = (directory / filename).resolve()
    if path.parent != directory.resolve() or not path.is_file():
        raise HTTPException(404, "Файл отчета не найден")
    return FileResponse(path, media_type=REPORT_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream"), filename=path.name)


@router.get("/api/v1/reports/audit-log/download/{filename}", dependencies=[Depends(require_admin_if_auth_enabled)])
def download_audit_log_report(filename: str):
    """Скачивание отчёта журнала аудита (логины, IP-адреса, неудачные входы) — только администратору. Роль проверяет зависимость самого
    маршрута, а файл ищется только в audit/: общий эндпоинт ниже туда не заглядывает, поэтому защита не зависит от имени файла."""
    return _report_file_response(audit_report_dir(REPORT_DIR), filename)


@router.get("/api/v1/reports/download/{filename}")
def download_report(filename: str, request: Request):
    # Отчёты аудита лежат в подкаталоге и отсюда недоступны (ищется файл только в корне). Проверка по имени — второй слой, для файлов,
    # оставшихся в корне от прежних версий: отчёт журнала аудита (логины, IP-адреса, неудачные входы) — только администратору, иначе
    # имя файла из журнала прокси, истории браузера или чата открыло бы данные роли viewer. Идёт ДО поиска файла и по имени без учёта
    # регистра и формы Unicode (в Windows и macOS файл находится при любом регистре), а после resolve() — ещё раз по реальному имени файла.
    if is_audit_report_name(filename):
        require_admin_if_auth_enabled(request)
    response = _report_file_response(REPORT_DIR, filename)
    if is_audit_report_name(Path(response.path).name):
        require_admin_if_auth_enabled(request)
    return response
