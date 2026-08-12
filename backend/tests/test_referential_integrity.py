"""
Тесты на backend/app/services/crud.py: _find_referencing_counts / delete_resource.

Проверяют конкретный сценарий из отчёта: должна быть невозможность молча удалить справочную
запись (например, тип устройства), на которую ссылаются другие записи (физические устройства).

Запуск: python3 -m unittest discover -s backend/tests -v
Требует установленных fastapi/sqlalchemy (в отличие от test_reporting.py, здесь тестируется
реальная работа с ORM-метаданными через inspect(), которую сложно достоверно замокать).
Если зависимости недоступны, модуль импортирует их лениво и тест будет пропущен (skip), а не упадёт.
"""
from __future__ import annotations

import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

try:
    import sys
    sys.path.insert(0, str(APP_DIR.parent))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models import Base, DeviceType, PhysicalDevice
    from app.services.crud import _find_referencing_counts, delete_resource
    from fastapi import HTTPException
    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "fastapi/sqlalchemy не установлены в этом окружении")
class ReferentialIntegrityTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def tearDown(self):
        self.session.close()

    def test_referenced_device_type_cannot_be_deleted(self):
        dt = DeviceType(name="Сервер")
        self.session.add(dt); self.session.flush()
        dev = PhysicalDevice(device_type_id=dt.id, serial_number="SN1")
        self.session.add(dev); self.session.commit()

        refs = _find_referencing_counts(DeviceType, dt.id, self.session)
        names = dict(refs)
        self.assertIn("Физические устройства", names)
        self.assertEqual(names["Физические устройства"], 1)

        with self.assertRaises(HTTPException) as ctx:
            delete_resource("device-types", dt.id, self.session)
        self.assertEqual(ctx.exception.status_code, 409)

        # Запись должна остаться на месте.
        self.assertIsNotNone(self.session.get(DeviceType, dt.id))

    def test_unreferenced_device_type_can_be_deleted(self):
        dt = DeviceType(name="Неиспользуемый тип")
        self.session.add(dt); self.session.commit()

        refs = _find_referencing_counts(DeviceType, dt.id, self.session)
        self.assertEqual(refs, [])

        result = delete_resource("device-types", dt.id, self.session)
        self.assertEqual(result["status"], "deleted")
        self.assertIsNone(self.session.get(DeviceType, dt.id))


if __name__ == "__main__":
    unittest.main()
