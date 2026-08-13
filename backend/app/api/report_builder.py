from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import REPORT_DIR
from ..db import get_db
from ..models import ReportTemplate
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
        raise HTTPException(422, str(e))
    return name, config, fmt, payload.get("description")


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
        raise HTTPException(422, str(e))


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
    session.add(t); session.commit(); session.refresh(t)
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
    t.name = name; t.description = description; t.format = fmt; t.config = json.dumps(config, ensure_ascii=False)
    session.commit(); session.refresh(t)
    return _template_out(t)


@router.delete("/report-templates/{template_id}")
def delete_template(template_id: str, session: Session = Depends(get_db)):
    t = session.get(ReportTemplate, template_id)
    if not t:
        raise HTTPException(404, "Шаблон отчёта не найден")
    session.delete(t); session.commit()
    return {"status": "ok"}


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
    session.add(t); session.commit(); session.refresh(t)
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
        raise HTTPException(422, str(e))
    return {"file_name": path.name, "download_url": f"/api/v1/reports/download/{path.name}"}
