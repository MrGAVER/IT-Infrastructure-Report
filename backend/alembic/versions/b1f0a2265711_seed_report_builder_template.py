"""seed default report-builder template from the fixed compliance report

Revision ID: b1f0a2265711
Revises: 8e6f16398be8

Data-миграция (не меняет схему): добавляет в report_templates одну строку — шаблон конструктора
отчётов, точно воспроизводящий вывод регламентированного 4-листового отчёта
(backend/app/reporting.py) на момент формирования, но открытый для дальнейшей правки в визуальном
редакторе. Точность 1:1 (не приближение) достигается через "виртуальные" сущности
services/report_registry_rows.py, переиспользующие ту же логику, что и сам reporting.py — подробнее
см. комментарий в начале services/report_seed_templates.py (общий источник конфигурации с тестами
test_report_seed_templates.py и test_report_registry_rows.py, чтобы миграция и тесты не расходились).

Идемпотентно: не вставляет строку повторно, если шаблон с таким именем уже существует (например,
после отката до этой ревизии и повторного применения, либо если строка была создана вручную ранее
с тем же именем). Откат (downgrade) удаляет строку по имени — только если её содержимое (config)
не изменилось с момента вставки этой миграцией, чтобы не потерять правки, которые пользователь мог
внести в этот шаблон через конструктор после обновления.
"""
import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'b1f0a2265711'
down_revision = '8e6f16398be8'
branch_labels = None
depends_on = None

# Ревизии alembic должны быть воспроизводимы независимо от будущих изменений models.py/services/*,
# поэтому таблица описана здесь локально (как и в остальных миграциях проекта), а не через импорт
# ORM-модели. Текст шаблона (имя/описание/config) переиспользуется из services/report_seed_templates.py
# — это не схема, а данные уровня приложения, и дублировать здесь без необходимости их вслепую
# рискованнее, чем сохранить один источник правды с тестом на этот источник.
_report_templates = sa.table(
    'report_templates',
    sa.column('id', sa.String),
    sa.column('created_at', sa.DateTime),
    sa.column('updated_at', sa.DateTime),
    sa.column('name', sa.String),
    sa.column('description', sa.Text),
    sa.column('format', sa.String),
    sa.column('config', sa.Text),
)


def upgrade():
    from app.services.report_seed_templates import (
        TEMPLATE_DESCRIPTION, TEMPLATE_NAME, default_registry_template_config,
    )

    bind = op.get_bind()
    exists = bind.execute(
        sa.select(_report_templates.c.id).where(_report_templates.c.name == TEMPLATE_NAME)
    ).first()
    if exists:
        return

    now = datetime.now(timezone.utc)
    op.bulk_insert(_report_templates, [{
        'id': str(uuid.uuid4()),
        'created_at': now,
        'updated_at': now,
        'name': TEMPLATE_NAME,
        'description': TEMPLATE_DESCRIPTION,
        'format': 'xlsx',
        'config': json.dumps(default_registry_template_config(), ensure_ascii=False),
    }])


def downgrade():
    from app.services.report_seed_templates import TEMPLATE_NAME, default_registry_template_config

    bind = op.get_bind()
    row = bind.execute(
        sa.select(_report_templates.c.id, _report_templates.c.config)
        .where(_report_templates.c.name == TEMPLATE_NAME)
    ).first()
    if not row:
        return
    # Не трогаем шаблон, если пользователь его отредактировал через конструктор после апгрейда —
    # откат схемы не должен молча уничтожать ручную работу пользователя.
    if json.loads(row.config) != default_registry_template_config():
        return
    op.execute(_report_templates.delete().where(_report_templates.c.id == row.id))
