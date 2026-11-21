"""R1-07 п. 3 код-ревью: ключи `DISPLAY_NAMES` и `MODEL_MAP`.

Отчёт посчитал ключ `diagrams` мёртвой записью (его нет в `MODEL_MAP`) и предложил удалить его. Проверка показала обратное: сохранённые диаграммы
не ресурс универсального CRUD, но `api/diagrams.py` пишет в журнал аудита `entity_type="diagrams"`, а журнал и его выгрузка берут подпись
сущности из `DISPLAY_NAMES`; без ключа в журнале стояло бы сырое «diagrams». Поэтому ключ остаётся, а инвариант записан тестом: подпись без
ресурса допустима только для перечисленных типов сущностей аудита, и каждый из них действительно пишется в журнал.

Запуск: pytest backend/tests/test_registry_display_names.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

from app.registry import DISPLAY_NAMES, MODEL_MAP

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Типы сущностей, которые пишутся в журнал аудита без одноимённого ресурса generic CRUD. Новый такой тип — сюда, с пояснением.
AUDIT_ONLY_ENTITY_TYPES = {"diagrams": "api/diagrams.py: сохранённые диаграммы топологии"}


def test_every_resource_has_a_display_name():
    assert set(MODEL_MAP) <= set(DISPLAY_NAMES), sorted(set(MODEL_MAP) - set(DISPLAY_NAMES))


def test_display_names_without_a_resource_are_only_the_known_audit_entity_types():
    assert set(DISPLAY_NAMES) - set(MODEL_MAP) == set(AUDIT_ONLY_ENTITY_TYPES)


def test_each_audit_only_entity_type_is_really_written_to_the_audit_log():
    """Исключение не должно пережить код, ради которого сделано: если никто больше не пишет в журнал этот тип, ключ можно удалить."""
    sources = "\n".join(path.read_text(encoding="utf-8") for path in APP_DIR.rglob("*.py"))
    for entity_type in AUDIT_ONLY_ENTITY_TYPES:
        assert re.search(rf"audit\(\s*session\s*,\s*[\"']{re.escape(entity_type)}[\"']", sources), f"{entity_type}: в журнал не пишется — удалите ключ из DISPLAY_NAMES и из исключений"


# --- ИА-04 код-ревью r3: подпись — для людей, пояснение для разработчика — в комментарии --------------------------------------------------
DEVELOPER_NOTE_MARKERS = re.compile(r"[a-z]+_[a-z]+|models\.|\bсм\.\s")  # snake_case-идентификаторы, ссылки на модели, «см. …»


def test_display_names_are_labels_for_people_not_developer_notes():
    """Подписи возвращает `GET /resources`, их видно в колонке «Раздел» журнала аудита и в сообщениях «используется в: …»."""
    notes = {key: name for key, name in DISPLAY_NAMES.items() if DEVELOPER_NOTE_MARKERS.search(name)}
    assert notes == {}, f"в подписях заметки для разработчика (вынесите их в комментарий): {notes}"


def test_the_two_polymorphic_resources_have_short_labels():
    assert DISPLAY_NAMES["ip-addresses"] == "IP-адреса"
    assert DISPLAY_NAMES["deployed-software"] == "ПО, развёрнутое на устройствах и ВМ"
