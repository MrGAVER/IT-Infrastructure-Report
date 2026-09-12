"""
Тесты на backend/app/services/catalogs.py: иерархия DeviceCategory и обязательный
DeviceType.category_id, заведённые для диаграммы топологии сети (ТЗ, раздел 4.1/4.2).

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_diagram_catalogs.py -v
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import DeviceCategory, DeviceType
from app.services.catalogs import (
    DEVICE_CATEGORY_HIERARCHY,
    DEVICE_TYPE_CATEGORY,
    FALLBACK_DEVICE_CATEGORY_NAME,
    seed_defaults,
)


def test_seed_defaults_creates_full_category_hierarchy(db_session):
    seed_defaults(db_session)
    categories = {c.name: c for c in db_session.scalars(select(DeviceCategory)).all()}
    assert len(categories) == len(DEVICE_CATEGORY_HIERARCHY)
    # Подкатегория "Коммутаторы" ссылается на родителя "Сетевая инфраструктура" и имеет
    # собственный shape, а собственного цвета не задаёт — наследует от родителя (раздел 4.1 ТЗ).
    switches = categories["Коммутаторы"]
    assert switches.parent_id == categories["Сетевая инфраструктура"].id
    assert switches.diagram_shape == "switch"
    assert switches.diagram_color is None
    # Верхнеуровневая категория задаёт полный стиль.
    servers = categories["Серверы и СХД"]
    assert servers.parent_id is None
    assert servers.diagram_shape == "server"
    assert servers.diagram_color == "#4f7cff"


def test_seed_defaults_creates_all_device_types_with_category(db_session):
    seed_defaults(db_session)
    types = {t.name: t for t in db_session.scalars(select(DeviceType)).all()}
    categories = {c.id: c for c in db_session.scalars(select(DeviceCategory)).all()}
    assert set(types.keys()) == set(DEVICE_TYPE_CATEGORY.keys())
    for name, expected_category_name in DEVICE_TYPE_CATEGORY.items():
        device_type = types[name]
        assert device_type.category_id is not None
        assert categories[device_type.category_id].name == expected_category_name
    # Устаревшие обобщённые типы больше не входят в стандартный набор (раздел 4.2 ТЗ).
    assert "Сетевое оборудование" not in types
    assert "Средство защиты информации" not in types


def test_seed_defaults_is_idempotent_for_categories_and_types(db_session):
    seed_defaults(db_session)
    category_count_1 = len(db_session.scalars(select(DeviceCategory)).all())
    type_count_1 = len(db_session.scalars(select(DeviceType)).all())

    seed_defaults(db_session)
    category_count_2 = len(db_session.scalars(select(DeviceCategory)).all())
    type_count_2 = len(db_session.scalars(select(DeviceType)).all())

    assert category_count_1 == category_count_2
    assert type_count_1 == type_count_2


def test_seed_defaults_does_not_overwrite_manually_edited_category(db_session):
    """Повторный запуск seed_defaults() не должен затирать поля, отредактированные администратором
    через обычный CRUD (тот же принцип, что уже действует для DEFAULT_NAMES, см. docstring
    _seed_name_only_catalogs)."""
    seed_defaults(db_session)
    servers = db_session.scalar(select(DeviceCategory).where(DeviceCategory.name == "Серверы и СХД"))
    servers.diagram_color = "#000000"
    db_session.commit()

    seed_defaults(db_session)
    db_session.refresh(servers)
    assert servers.diagram_color == "#000000"


def test_device_type_category_id_is_not_null_at_db_level(db_session):
    """DeviceType.category_id — обязательное поле (раздел 4.1 ТЗ): вставка без категории должна
    падать на уровне БД, а не только по соглашению на уровне приложения."""
    device_type = DeviceType(name="Без категории")
    db_session.add(device_type)
    try:
        db_session.flush()
        assert False, "ожидалась IntegrityError из-за NOT NULL category_id"
    except IntegrityError:
        db_session.rollback()


def test_fallback_category_exists_for_custom_device_types(db_session):
    """FALLBACK_DEVICE_CATEGORY_NAME должен существовать после сидирования — на него опирается
    _seed_device_types() для любых будущих кастомных типов устройств вне DEVICE_TYPE_CATEGORY."""
    seed_defaults(db_session)
    fallback = db_session.scalar(select(DeviceCategory).where(DeviceCategory.name == FALLBACK_DEVICE_CATEGORY_NAME))
    assert fallback is not None
