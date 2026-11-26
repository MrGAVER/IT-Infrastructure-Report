"""Версия записи-родителя при правке её вложенных коллекций (защита от потерянных обновлений).

`expected_updated_at` (generic.update_resource) сверяется с `updated_at` самой записи. Формы устройства, ВМ и ИС сохраняют вложенные данные
(порты, VLAN, ПО, IP, открытые порты, источники) отдельными PUT с семантикой полной замены, и такие запросы версию родителя не двигали:
вкладка, открытая до чужой правки портов, проходила проверку токена и затирала эту правку. Колонка `onupdate` здесь не помогает — она
срабатывает, только когда меняется строка самого родителя. Правило одно: изменилось вложенное — изменилась версия родителя.

Версию двигает только реальная правка: повторное сохранение формы без изменений (клиент шлёт полное желаемое состояние при каждом
«Сохранить») не должно давать другой вкладке ложный конфликт. Функции, которые сами считают созданное, изменённое и удалённое, решают
это по счётчикам; функции без счётчиков (порты устройства, детали ИС) — через `track_nested_changes`."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import Any, Iterator

from sqlalchemy import event
from sqlalchemy.orm import Session

from ..timeutil import utcnow_naive

# Проверка токена сравнивает время с точностью до миллисекунды (generic._to_millis): сдвиг меньше миллисекунды клиент бы не заметил.
_MILLISECOND = timedelta(milliseconds=1)


def touch_parent(parent: Any) -> None:
    """Сдвигает `updated_at` родителя вперёд — не меньше чем на миллисекунду, даже если правка уложилась в ту же миллисекунду, что и
    предыдущая версия, или часы ушли назад: иначе токен, выданный клиенту до правки, остался бы «свежим». Коммит — на вызывающем."""
    current = getattr(parent, "updated_at", None)
    now = utcnow_naive()
    if current is not None and now < current + _MILLISECOND:
        now = current + _MILLISECOND
    parent.updated_at = now


class _NestedChanges:
    """Результат `track_nested_changes`: `changed` — записала ли транзакция хоть одну вложенную строку (новую, изменённую, удалённую)."""

    changed = False


@contextmanager
def track_nested_changes(session: Session, *, ignore: Any = None) -> Iterator[_NestedChanges]:
    """Отслеживает реальные изменения ORM-объектов сессии внутри блока (кроме `ignore` — самого родителя).

    Изменением считается созданная или удалённая строка либо объект с отличающимся от сохранённого значением колонки: присвоение того же
    значения изменением не является. На выходе из блока незаписанные правки сбрасываются (`flush`), поэтому проверять `changed` можно сразу
    после `with`. При исключении внутри блока сброса нет — вызывающий откатывает транзакцию.

        with track_nested_changes(session, ignore=device) as nested:
            ...  # правки вложенных строк
        if nested.changed:
            touch_parent(device)"""
    result = _NestedChanges()

    def on_flush(flushed: Session, _context: Any) -> None:
        # В after_flush списки new/dirty/deleted ещё показывают состояние ДО сброса, а история атрибутов не очищена.
        if result.changed:
            return
        result.changed = bool(flushed.new or flushed.deleted) or any(
            obj is not ignore and flushed.is_modified(obj, include_collections=False) for obj in flushed.dirty
        )

    event.listen(session, "after_flush", on_flush)
    try:
        yield result
        session.flush()
    finally:
        event.remove(session, "after_flush", on_flush)
