"""Удаление записей: проверка ссылающихся записей, очистка полиморфных владельцев."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, func, literal, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ...models import DeployedSoftware, IPAddress, OpenPort
from ...registry import MODEL_MAP, DISPLAY_NAMES
from ...constants import ErrorCode, AuditAction, OwnerType
from ..integrity import format_referenced_message, source_reference_refs
from .audit_log import audit
from .columns import model_for
from .payload import ensure_writable
from .subinterfaces import purge_subinterfaces_of_interfaces, subinterface_references


def _find_referencing_counts(model, item_id: str, session: Session) -> list[tuple[str, int]]:
    """Для каждого другого зарегистрированного ресурса считает, сколько его записей ссылаются
    (через FK) на удаляемую запись. Используется, чтобы дать конкретное предупреждение перед
    удалением, а не полагаться только на то, что БД сама остановит операцию через FK-констрейнт.

    Код-ревью п.3.7: раньше здесь был отдельный SELECT COUNT(*) на каждую FK-колонку каждой из
    ~40 моделей реестра (MODEL_MAP) — при удалении часто ссылаемой записи (например,
    производителя устройства) это десятки последовательных round-trip'ов к БД на одно
    удаление. Теперь все подзапросы объединяются в один через UNION ALL и выполняются ОДНИМ
    запросом; каждая ветка несёт свой порядковый номер (ord) как обычную колонку данных, а не
    полагается на порядок строк, в котором сервер БД решит вернуть результат UNION ALL (для
    SQLite и PostgreSQL это на практике совпадает с порядком объявления веток, но опираться на
    недокументированное поведение не стоит) — после выполнения строки сортируются по этому
    номеру в Python, что и восстанавливает исходный, стабильный порядок вывода."""
    target_table = model.__tablename__
    resource_keys: list[str] = []
    subqueries = []
    for resource_key, other_model in MODEL_MAP.items():
        if other_model is model:
            continue
        for c in inspect(other_model).columns:
            if not c.foreign_keys:
                continue
            target = next(iter(c.foreign_keys)).target_fullname
            if target.split('.')[0] != target_table:
                continue
            subqueries.append(
                select(literal(len(resource_keys)).label('ord'), func.count().label('cnt'))
                .select_from(other_model).where(c == item_id)
            )
            resource_keys.append(resource_key)
    if not subqueries:
        return []
    combined = union_all(*subqueries) if len(subqueries) > 1 else subqueries[0]
    rows = sorted(session.execute(combined).all(), key=lambda row: row.ord)
    return [
        (DISPLAY_NAMES.get(resource_keys[row.ord], resource_keys[row.ord]), row.cnt)
        for row in rows if row.cnt
    ]


# Код-ревью (отчёт по рефакторингу и безопасности, находка 1): открытые порты (OpenPort),
# развёрнутое ПО (DeployedSoftware) и IP-адреса (IPAddress) — три модели с полиморфным владельцем
# (owner_type/owner_id без настоящего FK), поэтому _find_referencing_counts() выше их структурно
# не видит. Значение словаря — СПИСОК (модель, owner_type), не один элемент: у одного resource_key
# может быть несколько таких моделей сразу (например, у устройства — и открытые порты, и ПО).
# Если правки из отчёта по анализу БД добавят owner_type/owner_id ещё куда-то — этот словарь и
# вызывающий его delete_resource() снова первое, что нужно будет расширить.
_POLYMORPHIC_OWNER_CLEANUP: dict[str, list[tuple[type, str]]] = {
    'interfaces': [(OpenPort, OwnerType.DEVICE_INTERFACE), (IPAddress, OwnerType.DEVICE_INTERFACE)],
    'vms': [(OpenPort, OwnerType.VIRTUAL_MACHINE), (DeployedSoftware, OwnerType.VIRTUAL_MACHINE), (IPAddress, OwnerType.VIRTUAL_MACHINE)],
    'devices': [(OpenPort, OwnerType.PHYSICAL_DEVICE), (DeployedSoftware, OwnerType.PHYSICAL_DEVICE)],
    'is-sources': [(IPAddress, OwnerType.INFORMATION_SYSTEM_SOURCE)],
}


def assert_deletable(resource: str, item_id: str, session: Session) -> None:
    """Единая точка проверки «можно ли удалить запись»: настоящие FK-ссылки (reflection-based
    _find_referencing_counts) + owner_id-ссылки источников ИС на устройство/ВМ/контейнер
    (InformationSystemSource.owner_id — не FK, см. services/integrity.py). Кидает 409 в едином
    формате. Любой новый путь удаления устройства/ВМ/контейнера ОБЯЗАН вызывать эту функцию
    (delete_resource() уже вызывает); сама защита на этом не заканчивается — см. before_delete и
    триггеры БД в integrity.py — но понятное сообщение пользователю даёт только этот уровень."""
    model = model_for(resource)
    refs = _find_referencing_counts(model, item_id, session) + source_reference_refs(resource, item_id, session) + subinterface_references(resource, item_id, session)
    if refs:
        raise HTTPException(409, detail={'code': ErrorCode.REFERENCED_BY_OTHER_RECORDS, 'message': format_referenced_message(refs)})


def delete_resource(resource: str, item_id: str, session: Session):
    ensure_writable(resource)
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    assert_deletable(resource, item_id, session)
    try:
        # Подтверждено эмпирически: DELETE /resources/interfaces/{id} в обход sync_interfaces
        # удалял интерфейс, но оставлял открытые порты/IP в БД с owner_id, указывающим на уже не
        # существующую запись. Явно подчищаем перед удалением для каждой полиморфной модели,
        # зарегистрированной для этого resource_key выше.
        # У порта удаляются и его подинтерфейсы: FK ON DELETE CASCADE убрал бы только их строки, но не
        # полиморфные IP/открытые порты подинтерфейсов.
        if resource == 'interfaces': purge_subinterfaces_of_interfaces([item_id], session)
        for cleanup_model, owner_type in _POLYMORPHIC_OWNER_CLEANUP.get(resource, []):
            session.execute(delete(cleanup_model).where(cleanup_model.owner_type == owner_type, cleanup_model.owner_id == item_id))
        session.delete(obj); session.flush(); audit(session, resource, item_id, AuditAction.DELETE, 'Удаление записи'); session.commit(); return {'status': 'deleted', 'id': item_id}
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, 'Запись нельзя удалить: на неё ссылаются другие объекты') from exc
