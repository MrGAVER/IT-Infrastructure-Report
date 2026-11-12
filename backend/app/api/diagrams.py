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
import logging
import threading
from contextlib import contextmanager
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..db import get_db
from ..models import DiagramGroupState, DiagramLayout, SavedDiagram
from ..services.crud import audit
from ..services.diagram_export import export_drawio, export_svg, export_vsdx
from ..services.export_cache import export_cache, graph_fingerprint
from ..services.timeutil import iso_utc
from ..services.diagram_graph import MAX_LAYOUT_KEY_LENGTH, build_graph, clean_positions_lenient, parse_scope_filter
from .diagram_schemas import (
    MAX_DIAGRAM_NAME_LENGTH,
    DiagramCreate,
    DiagramGroupStateUpdate,
    DiagramLayoutUpdate,
    DiagramRename,
    checked_viewport,
    clean_name,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/diagrams", tags=["Diagrams"])

# Раздел 9 ТЗ: три формата экспорта. Значение — (media_type, сериализатор графа в str|bytes).
EXPORT_FORMATS = {
    "svg": ("image/svg+xml", lambda graph: export_svg(graph).encode("utf-8")),
    "drawio": ("application/xml", lambda graph: export_drawio(graph).encode("utf-8")),
    "vsdx": ("application/vnd.ms-visio.drawing", export_vsdx),
}

# Тяжёлые для процессора форматы экспорта (A-06 код-ревью r3). Замер на 120 устройствах: .svg — единицы мс, .drawio — до 0,2 с, .vsdx — от 0,5 до
# 2,5 с (с засечками портов). Раньше .vsdx занимал десятки секунд: библиотека vsdx при каждом копировании шаблонной фигуры обходила все фигуры
# страницы (copy_shape → set_max_ids), рост квадратичный; теперь копирование без повторного обхода (diagram_export/vsdx.py:_ShapeTemplate), но
# .vsdx по-прежнему самый тяжёлый формат.
# Эндпоинт синхронный и работает в пуле потоков (по умолчанию ~40): десяток параллельных запросов .vsdx занял бы весь пул, и API перестало бы
# отвечать всем, включая вход. Поэтому одновременно выполняется не больше HEAVY_EXPORT_MAX_CONCURRENT таких экспортов; лишний запрос сразу
# получает 503 с Retry-After (как проверка паролей на входе, services/auth/login._password_hash_slot), а не ждёт в очереди и не держит поток.
# Новый формат с заметным временем работы добавляют сюда же; тест контракта проверяет, что имена в этом наборе — настоящие форматы экспорта.
HEAVY_EXPORT_FORMATS = frozenset({"vsdx"})
HEAVY_EXPORT_MAX_CONCURRENT = 2
# Потолок размера для .vsdx (ИА-01 код-ревью r3). Замер на синтетической цепочке из коммутаторов с 24 засечками портов, один процессорный
# поток, после ускорения копирования (_ShapeTemplate): 120 узлов — 2,3 с, 300 — 7,3 с, 600 — 13,4 с, 1000 — 19 с (рост линейный, ≈19 мс на
# узел). Тысяча узлов с запасом укладывается в таймаут рендера (services/vsdx_process.py, 60 с) даже на машине втрое медленнее замерной;
# диаграмма больше — чаще ошибка в фильтре, чем осознанный выбор: она получает понятный 422 ДО захвата слота и не держит его.
# (В отчёте ревью стояло 300 — число считалось по квадратичному росту, которого после A-06 уже нет.)
MAX_VSDX_NODES = 1000
HEAVY_EXPORT_RETRY_AFTER_SECONDS = 10  # с запасом (экспорт .vsdx занимал десятки секунд, теперь — секунды); при желании можно уменьшить
_HEAVY_EXPORT_SLOTS = threading.BoundedSemaphore(HEAVY_EXPORT_MAX_CONCURRENT)


@contextmanager
def _heavy_export_slot(export_format: str):
    """Занимает слот тяжёлого экспорта на время сериализации; свободных нет — 503 с Retry-After.

    Лёгкие форматы слот не занимают. Слот освобождается всегда, в том числе при исключении внутри блока.
    Пример: `with _heavy_export_slot("vsdx"): data = export_vsdx(graph)`."""
    if export_format not in HEAVY_EXPORT_FORMATS:
        yield
        return
    slots = _HEAVY_EXPORT_SLOTS  # тот же объект и на release, даже если модульное имя подменили посреди запроса
    if not slots.acquire(blocking=False):
        raise HTTPException(
            503,
            f"Сервер занят формированием других тяжёлых экспортов диаграмм, повторите через {HEAVY_EXPORT_RETRY_AFTER_SECONDS} с.",
            headers={"Retry-After": str(HEAVY_EXPORT_RETRY_AFTER_SECONDS)},
        )
    try:
        yield
    finally:
        slots.release()


def _diagram_out(d: SavedDiagram) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "description": d.description,
        "scope_filter": parse_scope_filter(d.scope_filter),
        "group_by": d.group_by,
        "collapse_threshold": d.collapse_threshold,
        "last_export_format": d.last_export_format,
        "created_at": iso_utc(d.created_at),
        "updated_at": iso_utc(d.updated_at),
    }


def _get_diagram_or_404(session: Session, diagram_id: str) -> SavedDiagram:
    diagram = session.get(SavedDiagram, diagram_id)
    if not diagram:
        raise HTTPException(404, "Диаграмма не найдена")
    return diagram


COPY_SUFFIX = " (копия)"


def _unique_diagram_name(session: Session, base_name: str) -> str:
    """Свободное название: base_name, затем «base_name 2», «base_name 3»… Результат не длиннее колонки: при необходимости
    укорачивается основа, а не номер."""
    name = base_name[:MAX_DIAGRAM_NAME_LENGTH]
    n = 2
    while session.scalar(select(SavedDiagram).where(SavedDiagram.name == name)):
        suffix = f" {n}"
        name = f"{base_name[: MAX_DIAGRAM_NAME_LENGTH - len(suffix)]}{suffix}"
        n += 1
    return name


def _parse_viewport(text: str | None) -> dict | None:
    """Уже сохранённый viewport: повреждённое значение читается как «нет сохранённого» вместо ошибки."""
    if not text:
        return None
    try:
        return checked_viewport(json.loads(text))
    except ValueError:
        return None


def _load_layout(session: Session, diagram_id: str) -> tuple[DiagramLayout | None, dict]:
    layout = session.scalar(select(DiagramLayout).where(DiagramLayout.saved_diagram_id == diagram_id))
    if layout is None:
        return None, {}
    try:
        positions = json.loads(layout.node_positions or "{}")
    except json.JSONDecodeError:
        positions = {}
    return layout, clean_positions_lenient(positions)


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
    merged = {**computed, **clean_positions_lenient(current)}
    existing.node_positions = json.dumps(merged, ensure_ascii=False)


@router.get("")
def list_diagrams(session: Session = Depends(get_db)):
    rows = session.scalars(select(SavedDiagram).order_by(SavedDiagram.name)).all()
    return [_diagram_out(d) for d in rows]


@router.post("", status_code=201)
def create_diagram(body: DiagramCreate, session: Session = Depends(get_db)):
    if session.scalar(select(SavedDiagram).where(SavedDiagram.name == body.name)):
        raise HTTPException(409, "Диаграмма с таким названием уже существует")
    diagram = SavedDiagram(
        name=body.name,
        description=body.description,
        scope_filter=json.dumps(body.scope_filter, ensure_ascii=False),
        group_by=body.group_by,
        collapse_threshold=body.collapse_threshold,
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
    # GET ничего не пишет: состояние групп выше порога считается в памяти (persist=False), его сохраняют создание и
    # regenerate. Иначе просмотр менял данные от имени viewer и при параллельных запросах давал 500 (uq_diagram_group_state).
    graph = build_graph(session, diagram, node_positions=positions, persist=False)
    viewport = _parse_viewport(layout.viewport) if layout else None
    return {**_diagram_out(diagram), "nodes": graph["nodes"], "edges": graph["edges"], "viewport": viewport}


@router.put("/{diagram_id}/rename")
def rename_diagram(diagram_id: str, body: DiagramRename, session: Session = Depends(get_db)):
    """Только name — узко специализированный эндпоинт под конкретную операцию (тот же принцип,
    что и у PUT .../layout и PUT .../groups/{group_key} выше: отдельный узкий эндпоинт под
    операцию, а не один "общий" PUT на весь SavedDiagram). Изменение group_by/scope_filter уже
    требует пересборки графа (см. POST /regenerate) — смешивать это с переименованием было бы
    двумя разными по цене и последствиям операциями под одной ручкой."""
    diagram = _get_diagram_or_404(session, diagram_id)
    name = body.name
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
def update_layout(diagram_id: str, body: DiagramLayoutUpdate, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    node_positions, viewport = body.node_positions, body.viewport
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
def update_group_state(diagram_id: str, group_key: str, body: DiagramGroupStateUpdate, session: Session = Depends(get_db)):
    diagram = _get_diagram_or_404(session, diagram_id)
    if len(group_key) > MAX_LAYOUT_KEY_LENGTH:
        raise HTTPException(422, f"group_key не должен быть длиннее {MAX_LAYOUT_KEY_LENGTH} символов")
    state = session.scalar(select(DiagramGroupState).where(DiagramGroupState.saved_diagram_id == diagram_id, DiagramGroupState.group_key == group_key))
    if state is None:
        state = DiagramGroupState(saved_diagram_id=diagram.id, group_key=group_key, device_count=0)
        session.add(state)
    # Применяется только присланное: отсутствующее поле состояние не трогает, а custom_threshold: null сбрасывает порог.
    if "is_collapsed" in body.model_fields_set:
        state.is_collapsed = body.is_collapsed
    if "custom_threshold" in body.model_fields_set:
        state.custom_threshold = body.custom_threshold
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
    # Имя источника могло быть сохранено до очистки (с управляющими символами) или быть максимальной длины: копия не должна
    # их наследовать и обязана помещаться в колонку вместе с суффиксом.
    base = clean_name(src.name)[: MAX_DIAGRAM_NAME_LENGTH - len(COPY_SUFFIX)] or "Диаграмма"
    name = _unique_diagram_name(session, f"{base}{COPY_SUFFIX}")
    dup = SavedDiagram(
        name=name,
        description=src.description,
        scope_filter=src.scope_filter,
        group_by=src.group_by,
        collapse_threshold=src.collapse_threshold,
    )
    session.add(dup)
    session.flush()

    src_layout = session.scalar(select(DiagramLayout).where(DiagramLayout.saved_diagram_id == src.id))
    if src_layout:
        session.add(
            DiagramLayout(
                saved_diagram_id=dup.id,
                node_positions=src_layout.node_positions,
                viewport=src_layout.viewport,
                auto_layout_algorithm=src_layout.auto_layout_algorithm,
            )
        )
    for state in session.scalars(select(DiagramGroupState).where(DiagramGroupState.saved_diagram_id == src.id)).all():
        session.add(
            DiagramGroupState(
                saved_diagram_id=dup.id,
                group_key=state.group_key,
                is_collapsed=state.is_collapsed,
                device_count=state.device_count,
                custom_threshold=state.custom_threshold,
            )
        )
    audit(session, "diagrams", dup.id, AuditAction.CREATE, f"Дублирована из диаграммы «{src.name}»")
    session.commit()
    session.refresh(dup)
    return _diagram_out(dup)


def _check_export_size(export_format: str, graph: dict) -> None:
    """422 для диаграммы, которая не поместится в .vsdx (MAX_VSDX_NODES); остальные форматы размер не ограничивает."""
    nodes = len(graph["nodes"])
    if export_format == "vsdx" and nodes > MAX_VSDX_NODES:
        raise HTTPException(
            422,
            f"Диаграмма слишком велика для .vsdx ({nodes} узлов, максимум {MAX_VSDX_NODES}). Скачайте .svg или .drawio либо сузьте фильтр диаграммы.",
        )


def _serialize_graph(export_format: str, serialize, graph: dict, diagram_id: str) -> bytes:
    """Готовый файл: у тяжёлых форматов — из кэша (services/export_cache.py; без слота и рендера), иначе сериализация внутри слота.

    Любой сбой сериализации — понятный 500 и полный traceback в лог сервера; сбойный результат в кэш не попадает."""
    cache_key = graph_fingerprint(export_format, graph) if export_format in HEAVY_EXPORT_FORMATS else None
    if cache_key is not None:
        cached = export_cache.get(cache_key)
        if cached is not None:
            return cached
    with _heavy_export_slot(export_format):
        try:
            data = serialize(graph)
        except Exception:
            # Пункт 7 правки "диаграмма топологии сети": реальная причина 500 в проде оказалась
            # окружением (EXE-сборка, PyInstaller не паковал файлы данных vsdx/drawpyo — см. фикс в
            # infra_registry.spec), а не данными диаграммы — но раз голый traceback долетал прямо до
            # пользователя без единого diagnostика, на будущее (любая другая непредвиденная причина)
            # заворачиваем в понятную ошибку и полный traceback в лог сервера, а не только код 500.
            logger.exception("Не удалось сформировать экспорт диаграммы %s в формате %s", diagram_id, export_format)
            raise HTTPException(500, f"Не удалось сформировать файл .{export_format} — подробности в логе сервера") from None
    if cache_key is not None:
        export_cache.put(cache_key, data)
    return data


@router.get("/{diagram_id}/export")
def export_diagram(
    diagram_id: str,
    format: str = Query(..., alias="format"),
    persist_export: bool = Query(False, description="Запомнить формат в last_export_format; без параметра экспорт ничего не пишет в БД"),
    session: Session = Depends(get_db),
):
    diagram = _get_diagram_or_404(session, diagram_id)
    if format not in EXPORT_FORMATS:
        raise HTTPException(422, f"format должен быть одним из: {', '.join(EXPORT_FORMATS)}")
    media_type, serialize = EXPORT_FORMATS[format]
    _, positions = _load_layout(session, diagram_id)
    graph = build_graph(session, diagram, node_positions=positions, persist=False)
    _check_export_size(format, graph)  # до слота: слишком большая диаграмма не занимает его и не ждёт таймаута
    data = _serialize_graph(format, serialize, graph, diagram_id)
    if persist_export:  # безопасный метод GET по умолчанию не пишет: запись — только по явной просьбе клиента
        diagram.last_export_format = format
        session.commit()
    filename = f"{diagram.name}.{format}"
    # HTTP-заголовки должны быть latin-1-совместимы (RFC 7230) — название диаграммы, как и
    # почти все данные в этом проекте, обычно на русском, поэтому ASCII-safe filename идёт как
    # запасной вариант, а настоящее имя — RFC 6266 filename* с percent-encoded UTF-8.
    # isprintable() отсекает CR/LF и прочие управляющие символы: имя, сохранённое до очистки названий, не должно ломать заголовок.
    ascii_fallback = "".join(c if c.isascii() and c.isprintable() and c not in '"\\;/' else "_" for c in filename) or f"diagram.{format}"
    content_disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
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
