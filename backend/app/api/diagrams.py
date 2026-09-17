"""
Роутер диаграммы топологии сети (ТЗ, раздел 7), prefix='/api/v1/diagrams'. DeviceCategory и
DiagramIcon — обычные ресурсы generic CRUD (registry.py, /api/v1/resources/{resource}) и в этом
файле не участвуют, как того требует раздел 7 ТЗ.

Решение по глубине копирования POST /diagrams/{id}/duplicate (ТЗ, раздел 7, ссылается на
report_builder.py:duplicate_template, но не уточняет для диаграмм, копируется ли только
конфигурация охвата/группировки или ещё и текущая раскладка/состояния групп): копируется ВСЁ —
scope_filter/group_by/collapse_threshold, DiagramLayout и все DiagramGroupState — то есть
duplicate создаёт полный снимок диаграммы на момент вызова, а не пустую диаграмму с той же
конфигурацией фильтра. report_builder.py копирует только config шаблона, т.к. версии шаблона —
отдельная история, а у диаграммы раскладка и состояния групп своей истории версий не имеют.
"""
from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..db import get_db
from ..models import DiagramGroupState, DiagramLayout, SavedDiagram
from ..services.crud import audit
from ..services.diagram_export import export_drawio, export_svg, export_vsdx
from ..services.diagram_graph import GROUP_DIMENSIONS, build_graph, parse_scope_filter

router = APIRouter(prefix="/api/v1/diagrams", tags=["Diagrams"])

DEFAULT_COLLAPSE_THRESHOLD = 20
# Раздел 9 ТЗ: три формата экспорта. Значение — (media_type, сериализатор графа в str|bytes).
EXPORT_FORMATS = {
    "svg": ("image/svg+xml", lambda graph: export_svg(graph).encode("utf-8")),
    "drawio": ("application/xml", lambda graph: export_drawio(graph).encode("utf-8")),
    "vsdx": ("application/vnd.ms-visio.drawing", export_vsdx),
}


def _diagram_out(d: SavedDiagram) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "scope_filter": parse_scope_filter(d.scope_filter),
        "group_by": d.group_by,
        "collapse_threshold": d.collapse_threshold,
        "last_export_format": d.last_export_format,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _get_diagram_or_404(session: Session, diagram_id: str) -> SavedDiagram:
    diagram = session.get(SavedDiagram, diagram_id)
    if not diagram:
        raise HTTPException(404, "Диаграмма не найдена")
    return diagram


def _validate_diagram_payload(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Укажите название диаграммы")
    group_by = payload.get("group_by", "structural_unit")
    if group_by not in GROUP_DIMENSIONS:
        raise HTTPException(422, f"group_by должен быть одним из: {', '.join(GROUP_DIMENSIONS)}")
    scope_filter = payload.get("scope_filter") or {}
    if not isinstance(scope_filter, dict):
        raise HTTPException(422, "scope_filter должен быть объектом-фильтром охвата")
    collapse_threshold = payload.get("collapse_threshold", DEFAULT_COLLAPSE_THRESHOLD)
    if isinstance(collapse_threshold, bool) or not isinstance(collapse_threshold, int) or collapse_threshold < 1:
        raise HTTPException(422, "collapse_threshold должен быть положительным целым числом")
    return {
        "name": name,
        "group_by": group_by,
        "scope_filter": scope_filter,
        "description": payload.get("description"),
        "collapse_threshold": collapse_threshold,
    }


def _unique_diagram_name(session: Session, base_name: str) -> str:
    name = base_name
    n = 2
    while session.scalar(select(SavedDiagram).where(SavedDiagram.name == name)):
        name = f"{base_name} {n}"
        n += 1
    return name


def _load_layout(session: Session, diagram_id: str) -> tuple[DiagramLayout | None, dict]:
    layout = session.scalar(select(DiagramLayout).where(DiagramLayout.saved_diagram_id == diagram_id))
    if layout is None:
        return None, {}
    try:
        positions = json.loads(layout.node_positions or "{}")
    except json.JSONDecodeError:
        positions = {}
    return layout, positions if isinstance(positions, dict) else {}


def _save_layout(session: Session, diagram_id: str, graph: dict, existing: DiagramLayout | None) -> None:
    """Раздел 4.6 ТЗ: раскладка сохраняется при первой генерации; при повторной генерации
    (regenerate) уже известные позиции (в т.ч. отредактированные вручную через PUT /layout) не
    перезаписываются — только НОВЫЕ узлы (появившиеся в графе впервые) получают вычисленную
    сеточную позицию из build_graph."""
    computed = {n["id"]: {"x": n["x"], "y": n["y"]} for n in graph["nodes"]}
    if existing is None:
        session.add(DiagramLayout(saved_diagram_id=diagram_id, node_positions=json.dumps(computed, ensure_ascii=False)))
        return
    try:
        current = json.loads(existing.node_positions or "{}")
    except json.JSONDecodeError:
        current = {}
    merged = {**computed, **(current if isinstance(current, dict) else {})}
    existing.node_positions = json.dumps(merged, ensure_ascii=False)


@router.get("")
def list_diagrams(session: Session = Depends(get_db)):
    rows = session.scalars(select(SavedDiagram).order_by(SavedDiagram.name)).all()
    return [_diagram_out(d) for d in rows]


@router.post("", status_code=201)
def create_diagram(payload: dict, session: Session = Depends(get_db)):
    data = _validate_diagram_payload(payload)
    if session.scalar(select(SavedDiagram).where(SavedDiagram.name == data["name"])):
        raise HTTPException(409, "Диаграмма с таким названием уже существует")
    diagram = SavedDiagram(
        name=data["name"],
        description=data["description"],
        scope_filter=json.dumps(data["scope_filter"], ensure_ascii=False),
        group_by=data["group_by"],
        collapse_threshold=data["collapse_threshold"],
    )
    session.add(diagram)
    session.flush()
    graph = build_graph(session, diagram)
    _save_layout(session, diagram.id, graph, existing=None)
    audit(session, "diagrams", diagram.id, AuditAction.CREATE, f"Создана диаграмма «{diagram.name}»")
    session.commit()
    session.refresh(diagram)
    return _diagram_out(diagram)


@router.get("/{diagram_id}")
def get_diagram(diagram_id: str, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    layout, positions = _load_layout(session, diagram_id)
    graph = build_graph(session, diagram, node_positions=positions)
    session.commit()  # build_graph могла создать новые DiagramGroupState по достижении порога
    viewport = None
    if layout and layout.viewport:
        try:
            viewport = json.loads(layout.viewport)
        except json.JSONDecodeError:
            viewport = None
    return {**_diagram_out(diagram), "nodes": graph["nodes"], "edges": graph["edges"], "viewport": viewport}


@router.put("/{diagram_id}/rename")
def rename_diagram(diagram_id: str, payload: dict, session: Session = Depends(get_db)):
    """Только name — узко специализированный эндпоинт под конкретную операцию (тот же принцип,
    что и у PUT .../layout и PUT .../groups/{group_key} выше: отдельный узкий эндпоинт под
    операцию, а не один "общий" PUT на весь SavedDiagram). Изменение group_by/scope_filter уже
    требует пересборки графа (см. POST /regenerate) — смешивать это с переименованием было бы
    двумя разными по цене и последствиям операциями под одной ручкой."""
    diagram = _get_diagram_or_404(session, diagram_id)
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "Укажите название диаграммы")
    dup = session.scalar(select(SavedDiagram).where(SavedDiagram.name == name, SavedDiagram.id != diagram_id))
    if dup:
        raise HTTPException(409, "Диаграмма с таким названием уже существует")
    old_name = diagram.name
    diagram.name = name
    session.flush()
    audit(session, "diagrams", diagram.id, AuditAction.UPDATE, f"Диаграмма «{old_name}» переименована в «{name}»")
    session.commit()
    session.refresh(diagram)
    return _diagram_out(diagram)


@router.put("/{diagram_id}/layout")
def update_layout(diagram_id: str, payload: dict, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    node_positions = payload.get("node_positions")
    if not isinstance(node_positions, dict):
        raise HTTPException(422, "node_positions должен быть объектом вида {id: {x, y}}")
    viewport = payload.get("viewport")
    layout = session.scalar(select(DiagramLayout).where(DiagramLayout.saved_diagram_id == diagram_id))
    positions_json = json.dumps(node_positions, ensure_ascii=False)
    if layout is None:
        layout = DiagramLayout(
            saved_diagram_id=diagram.id,
            node_positions=positions_json,
            viewport=json.dumps(viewport, ensure_ascii=False) if viewport is not None else None,
        )
        session.add(layout)
    else:
        layout.node_positions = positions_json
        if viewport is not None:
            layout.viewport = json.dumps(viewport, ensure_ascii=False)
    session.commit()
    return {"status": "ok"}


@router.put("/{diagram_id}/groups/{group_key}")
def update_group_state(diagram_id: str, group_key: str, payload: dict, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    state = session.scalar(
        select(DiagramGroupState).where(DiagramGroupState.saved_diagram_id == diagram_id, DiagramGroupState.group_key == group_key)
    )
    if state is None:
        state = DiagramGroupState(saved_diagram_id=diagram.id, group_key=group_key, device_count=0)
        session.add(state)
    if "is_collapsed" in payload:
        state.is_collapsed = bool(payload["is_collapsed"])
    if "custom_threshold" in payload:
        threshold = payload["custom_threshold"]
        if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1):
            raise HTTPException(422, "custom_threshold должен быть положительным целым числом или null")
        state.custom_threshold = threshold
    session.commit()
    session.refresh(state)
    return {
        "group_key": state.group_key,
        "is_collapsed": state.is_collapsed,
        "device_count": state.device_count,
        "custom_threshold": state.custom_threshold,
    }


@router.post("/{diagram_id}/regenerate")
def regenerate_diagram(diagram_id: str, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    layout, positions = _load_layout(session, diagram_id)
    graph = build_graph(session, diagram, node_positions=positions)
    _save_layout(session, diagram_id, graph, existing=layout)
    audit(session, "diagrams", diagram.id, AuditAction.UPDATE, f"Пересобрана диаграмма «{diagram.name}»")
    session.commit()
    return {**_diagram_out(diagram), "nodes": graph["nodes"], "edges": graph["edges"]}


@router.post("/{diagram_id}/duplicate", status_code=201)
def duplicate_diagram(diagram_id: str, session: Session = Depends(get_db)):
    src = _get_diagram_or_404(session, diagram_id)
    name = _unique_diagram_name(session, f"{src.name} (копия)")
    dup = SavedDiagram(
        name=name, description=src.description, scope_filter=src.scope_filter,
        group_by=src.group_by, collapse_threshold=src.collapse_threshold,
    )
    session.add(dup)
    session.flush()

    src_layout = session.scalar(select(DiagramLayout).where(DiagramLayout.saved_diagram_id == src.id))
    if src_layout:
        session.add(DiagramLayout(
            saved_diagram_id=dup.id, node_positions=src_layout.node_positions,
            viewport=src_layout.viewport, auto_layout_algorithm=src_layout.auto_layout_algorithm,
        ))
    for state in session.scalars(select(DiagramGroupState).where(DiagramGroupState.saved_diagram_id == src.id)).all():
        session.add(DiagramGroupState(
            saved_diagram_id=dup.id, group_key=state.group_key, is_collapsed=state.is_collapsed,
            device_count=state.device_count, custom_threshold=state.custom_threshold,
        ))
    audit(session, "diagrams", dup.id, AuditAction.CREATE, f"Дублирована из диаграммы «{src.name}»")
    session.commit()
    session.refresh(dup)
    return _diagram_out(dup)


@router.get("/{diagram_id}/export")
def export_diagram(diagram_id: str, format: str = Query(..., alias="format"), session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    if format not in EXPORT_FORMATS:
        raise HTTPException(422, f"format должен быть одним из: {', '.join(EXPORT_FORMATS)}")
    _, positions = _load_layout(session, diagram_id)
    graph = build_graph(session, diagram, node_positions=positions)
    media_type, serialize = EXPORT_FORMATS[format]
    data = serialize(graph)
    diagram.last_export_format = format
    session.commit()
    filename = f"{diagram.name}.{format}"
    # HTTP-заголовки должны быть latin-1-совместимы (RFC 7230) — название диаграммы, как и
    # почти все данные в этом проекте, обычно на русском, поэтому ASCII-safe filename идёт как
    # запасной вариант, а настоящее имя — RFC 6266 filename* с percent-encoded UTF-8.
    ascii_fallback = "".join(c if c.isascii() and c not in '"\\' else "_" for c in filename) or f"diagram.{format}"
    content_disposition = f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": content_disposition})


@router.delete("/{diagram_id}")
def delete_diagram(diagram_id: str, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    name = diagram.name
    session.delete(diagram)  # ON DELETE CASCADE (миграция 4) удаляет layout/group_states в БД
    session.flush()
    audit(session, "diagrams", diagram_id, AuditAction.DELETE, f"Удалена диаграмма «{name}»")
    session.commit()
    return {"status": "ok"}
