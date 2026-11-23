"""Код-ревью С-1, Н-1, Н-4: пределы, определённые в двух местах, не должны разойтись.

`constants.py` (владелец — П1) задаёт MAX_SEARCH_LENGTH и MAX_CUSTOM_ICON_SVG_LENGTH для эндпоинтов и валидатора SVG. Те же числа остались в
`services/audit_query.py`, `services/connection_query.py` и `services/diagram_export/_common.py`: эти файлы принадлежат Исполнителю 2
(форматирование), и общий источник там появится в его пачке. До тех пор тест не даёт значениям тихо разойтись.

Запуск: pytest backend/tests/test_review_p1_constants_sync.py -v
"""

from __future__ import annotations

from app import constants
from app.services import audit_query, connection_query
from app.services.diagram_export import _common as export_common


def test_search_length_limit_is_the_same_everywhere():
    assert constants.MAX_SEARCH_LENGTH == audit_query.MAX_SEARCH_LENGTH == connection_query.MAX_SEARCH_LENGTH


def test_custom_icon_length_limit_is_the_same_for_validation_and_export():
    assert constants.MAX_CUSTOM_ICON_SVG_LENGTH == export_common.MAX_CUSTOM_ICON_SVG_LENGTH
