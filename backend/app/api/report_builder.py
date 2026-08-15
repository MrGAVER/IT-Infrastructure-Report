from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import REPORT_DIR
from ..constants import AuditAction
from ..db import get_db
from ..models import ReportTemplate, ReportTemplateVersion
from ..services.crud import audit
from ..services.report_engine import ReportBuilderError, validate_config
from ..services.report_meta import build_entity_metadata, entity_metadata_public
from ..services.report_render import build_report_from_template, preview_rows

router = APIRouter(prefix="/api/v1", tags=["Report builder"])


def _template_out(t: ReportTemplate) -> dict:
    try:
        config = json.loads(t.config or "{}")
    except json.JSONDecodeError:
        config = {}
    return {
        "id": t.id, "name": t.name, "description": t.description, "format": t.format,
        "config": config, "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _load_and_validate(payload: dict) -> tuple[str, dict, str, str | None]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Укажите название шаблона")
    fmt = payload.get("format", "xlsx")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise HTTPException(422, "Поле config должно быть объектом с описанием листов/блоков")
    try:
        validate_config(build_entity_metadata(), fmt, config)
    except ReportBuilderError as e:
        raise HTTPException(422, str(e)) from e
    return name, config, fmt, payload.get("description")


def _snapshot_version(t: ReportTemplate, session: Session) -> None:
    """Сохраняет ТЕКУЩЕЕ (ещё не изменённое) состояние шаблона как запись истории версий —
    вызывается непосредственно перед тем, как t будет перезаписан (обновление или восстановление
    другой версии), чтобы это состояние можно было потом вернуть."""
    next_number = (session.scalar(
        select(func.max(ReportTemplateVersion.version_number)).where(ReportTemplateVersion.report_template_id == t.id)
    ) or 0) + 1
    session.add(ReportTemplateVersion(
        report_template_id=t.id, version_number=next_number,
        name=t.name, description=t.description, format=t.format, config=t.config,
    ))


@router.get("/report-builder/entities")
def list_entities():
    """Список сущностей с полями и связями — для построения списка доступных полей в UI конструктора."""
    return entity_metadata_public()


@router.post("/report-builder/preview")
def preview(payload: dict, session: Session = Depends(get_db)):
    """Быстрый предпросмотр (первые строки каждого листа/таблицы) без сохранения шаблона и файла."""
    fmt = payload.get("format", "xlsx")
    config = payload.get("config") or {}
    try:
        validate_config(build_entity_metadata(), fmt, config)
        return preview_rows(session, config, limit=int(payload.get("limit", 20)))
    except ReportBuilderError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/report-templates")
def list_templates(session: Session = Depends(get_db)):
    rows = session.scalars(select(ReportTemplate).order_by(ReportTemplate.name)).all()
    return [_template_out(t) for t in rows]


@router.get("/report-templates/{template_id}")
def get_template(template_id: str, session: Session = Depends(get_db)):
    t = session.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон отчёта не найден")
    return _template_out(t)


@router.post("/report-templates", status_code=201)
def create_template(payload: dict, session: Session = Depends(get_db)):
    name, config, fmt, description = _load_and_validate(payload)
    if session.scalar(select(ReportTemplate).where(ReportTemplate.name == name)):
        raise HTTPException(409, "Шаблон с таким названием уже существует")
    t = ReportTemplate(name=name, description=description, format=fmt, config=json.dumps(config, ensure_ascii=False))
    session.add(t); session.flush()
    audit(session, "report-templates", t.id, AuditAction.CREATE, f"Создан шаблон «{t.name}»")
    session.commit(); session.refresh(t)
    return _template_out(t)


@router.put("/report-templates/{template_id}")
def update_template(template_id: str, payload: dict, session: Session = Depends(get_db)):
    t = session.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон отчёта не найден")
    name, config, fmt, description = _load_and_validate(payload)
    dup = session.scalar(select(ReportTemplate).where(ReportTemplate.name == name, ReportTemplate.id != template_id))
    if dup:
        raise HTTPException(409, "Шаблон с таким названием уже существует")
    _snapshot_version(t, session)
    t.name = name; t.description = description; t.format = fmt; t.config = json.dumps(config, ensure_ascii=False)
    session.flush()
    audit(session, "report-templates", t.id, AuditAction.UPDATE, f"Изменён шаблон «{t.name}»")
    session.commit(); session.refresh(t)
    return _template_out(t)


@router.delete("/report-templates/{template_id}")
def delete_template(template_id: str, session: Session = Depends(get_db)):
    t = session.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон отчёта не найден")
    name = t.name
    session.execute(delete(ReportTemplateVersion).where(ReportTemplateVersion.report_template_id == template_id))
    session.delete(t); session.flush()
    audit(session, "report-templates", template_id, AuditAction.DELETE, f"Удалён шаблон «{name}»")
    session.commit()
    return {"status": "ok"}


@router.get("/report-templates/{template_id}/versions")
def list_template_versions(template_id: str, session: Session = Depends(get_db)):
    """История версий шаблона (последняя сверху). Возвращает только метаданные — сам config
    версии наружу не отдаётся: восстановление выполняется целиком на сервере (см. ниже),
    отдельный просмотр содержимого прошлой версии не нужен для этого сценария."""
    if not session.get(ReportTemplate, template_id):
        raise HTTPException(404, "Шаблон отчёта не найден")
    rows = session.scalars(
        select(ReportTemplateVersion)
        .where(ReportTemplateVersion.report_template_id == template_id)
        .order_by(ReportTemplateVersion.version_number.desc())
    ).all()
    return [
        {
            "id": v.id, "version_number": v.version_number, "name": v.name,
            "description": v.description, "format": v.format,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in rows
    ]


@router.post("/report-templates/{template_id}/versions/{version_id}/restore")
def restore_template_version(template_id: str, version_id: str, session: Session = Depends(get_db)):
    t = session.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон отчёта не найден")
    v = session.get(ReportTemplateVersion, version_id)
    if not v or v.report_template_id != template_id:
        raise HTTPException(404, "Версия шаблона не найдена")
    dup = session.scalar(select(ReportTemplate).where(ReportTemplate.name == v.name, ReportTemplate.id != template_id))
    if dup:
        raise HTTPException(409, f"Нельзя восстановить: название «{v.name}» уже занято другим шаблоном")
    # Текущее состояние тоже сохраняется как версия перед восстановлением — откат обратим.
    _snapshot_version(t, session)
    t.name = v.name; t.description = v.description; t.format = v.format; t.config = v.config
    session.flush()
    audit(session, "report-templates", t.id, AuditAction.UPDATE, f"Восстановлена версия №{v.version_number} («{v.name}»)")
    session.commit(); session.refresh(t)
    return _template_out(t)


@router.post("/report-templates/{template_id}/duplicate", status_code=201)
def duplicate_template(template_id: str, session: Session = Depends(get_db)):
    src = session.get(ReportTemplate, template_id)
    if not src:
        raise HTTPException(404, "Шаблон отчёта не найден")
    base_name = f"{src.name} (копия)"
    name = base_name; n = 2
    while session.scalar(select(ReportTemplate).where(ReportTemplate.name == name)):
        name = f"{base_name} {n}"; n += 1
    t = ReportTemplate(name=name, description=src.description, format=src.format, config=src.config)
    session.add(t); session.flush()
    audit(session, "report-templates", t.id, AuditAction.CREATE, f"Дублирован из шаблона «{src.name}»")
    session.commit(); session.refresh(t)
    return _template_out(t)


@router.post("/report-templates/{template_id}/generate")
def generate_template_report(template_id: str, payload: dict | None = None, session: Session = Depends(get_db)):
    t = session.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон отчёта не найден")
    params = (payload or {}).get("params") or {}
    try:
        path = build_report_from_template(session, t, REPORT_DIR, params=params)
    except ReportBuilderError as e:
        raise HTTPException(422, str(e)) from e
    return {"file_name": path.name, "download_url": f"/api/v1/reports/download/{path.name}"}
