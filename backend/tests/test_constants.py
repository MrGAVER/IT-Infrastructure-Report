"""
Тесты на backend/app/constants.py.

Эти константы пересекают границу backend/frontend: backend возвращает их как значения полей
JSON-ответа (detail.code, action, source_type), а frontend (app.js) сверяется с теми же строками
как с литералами (единой Python/JS-константы быть не может). Тест фиксирует сами значения как
контракт — если кто-то в будущем случайно переименует константу, не заметив, что frontend всё ещё
ждёт старое значение, эти проверки не поймают рассинхронизацию сами по себе, но явно документируют,
какие строки должны совпадать между сторонами (см. соответствующие константы в app.js).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.constants import ErrorCode, AuditAction, SourceType, OwnerType


class ConstantsContractTestCase(unittest.TestCase):
    def test_error_codes_match_frontend_contract(self):
        # Значения, с которыми сверяется parseApiError()/saveForm() в app.js.
        self.assertEqual(ErrorCode.DUPLICATE_SYSTEM_NAME, "DUPLICATE_SYSTEM_NAME")
        self.assertEqual(ErrorCode.RACK_POSITION_OCCUPIED, "RACK_POSITION_OCCUPIED")
        self.assertEqual(ErrorCode.REFERENCED_BY_OTHER_RECORDS, "REFERENCED_BY_OTHER_RECORDS")

    def test_audit_actions_match_frontend_action_labels(self):
        # Значения, с которыми сверяется actionLabels в renderAuditLog() в app.js.
        self.assertEqual(AuditAction.CREATE, "CREATE")
        self.assertEqual(AuditAction.UPDATE, "UPDATE")
        self.assertEqual(AuditAction.DELETE, "DELETE")
        self.assertEqual(AuditAction.SYNC, "SYNC")

    def test_source_type_all_contains_exactly_the_four_values(self):
        self.assertEqual(SourceType.ALL, {"manual", "device", "vm", "container"})

    def test_owner_type_values(self):
        self.assertEqual(OwnerType.PHYSICAL_DEVICE, "physical_device")
        self.assertEqual(OwnerType.VIRTUAL_MACHINE, "virtual_machine")


if __name__ == "__main__":
    unittest.main()
