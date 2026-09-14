"""Код-ревью п.3.5: validate_resource() был диспетчером if/elif по типу модели — переведён на
dict-реестр _RESOURCE_VALIDATORS, чтобы добавление валидации для новой модели не требовало
правки тела самой функции (OCP). Эти тесты фиксируют контракт диспетчера на уровне юнит-теста
(остальное поведение конкретных валидаторов по-прежнему покрыто интеграционными тестами API)."""
import pytest
from fastapi import HTTPException

from app.models import Connection, DeviceType, PhysicalDevice
from app.services.crud import _RESOURCE_VALIDATORS, validate_resource


def test_unregistered_model_is_a_no_op(db_session):
    """Модель без записи в реестре (подавляющее большинство ~40 ресурсов) не должна ничего
    проверять — это осознанный дизайн, а не пропуск. Falcon-тест: раньше отсутствие ветки в
    if/elif давало тот же эффект молча "проваливаясь" мимо всех условий."""
    validate_resource(object, {}, db_session)  # не должно бросить исключение


def test_registered_model_dispatches_to_its_validator(db_session):
    """DeviceType зарегистрирован и обязан требовать category_id — регрессия того самого
    интеграционного бага, который и стал поводом для рефакторинга диспетчера."""
    with pytest.raises(HTTPException) as exc_info:
        validate_resource(DeviceType, {}, db_session)
    assert exc_info.value.status_code == 422


def test_registry_covers_all_previously_hardcoded_models():
    """Гарантирует, что рефакторинг не потерял ни одной из ранее захардкоженных в if/elif
    моделей при переносе в словарь."""
    assert set(_RESOURCE_VALIDATORS.keys()) >= {
        PhysicalDevice, Connection, DeviceType,
    }
    assert all(callable(v) for v in _RESOURCE_VALIDATORS.values())
