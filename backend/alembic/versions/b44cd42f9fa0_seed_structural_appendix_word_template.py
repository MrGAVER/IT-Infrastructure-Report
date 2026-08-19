"""seed structural-appendix Word template into report_templates

Revision ID: b44cd42f9fa0
Revises: b1f0a2265711

Data-миграция (не меняет схему): добавляет в report_templates шаблон-заготовку Word-документа
"Приложение к структурной схеме" — по образцу файла, приложенного пользователем к задаче (3
таблицы: назначение линий связи / перечень VLAN / перечень телекоммуникационного оборудования).
Конфигурация и текст описания — в services/report_seed_word_template.py (общий источник с тестом
test_report_seed_word_template.py, чтобы миграция и тест не расходились) — см. подробный комментарий
в начале того модуля о том, чем этот шаблон отличается от структуры исходного документа и почему.

Идемпотентно (не дублирует строку при повторном upgrade head) и не удаляет шаблон при откате, если
пользователь успел отредактировать его конфигурацию через конструктор после апгрейда — тот же
паттерн, что и в миграции b1f0a2265711 (шаблон регламентированного отчёта)."""
import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'b44cd42f9fa0'
down_revision = 'b1f0a2265711'
branch_labels = None
depends_on = None

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
    from app.services.report_seed_word_template import (
        TEMPLATE_DESCRIPTION, TEMPLATE_NAME, default_structural_appendix_config,
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
        'format': 'docx',
        'config': json.dumps(default_structural_appendix_config(), ensure_ascii=False),
    }])


def downgrade():
    from app.services.report_seed_word_template import TEMPLATE_NAME, default_structural_appendix_config

    bind = op.get_bind()
    row = bind.execute(
        sa.select(_report_templates.c.id, _report_templates.c.config)
        .where(_report_templates.c.name == TEMPLATE_NAME)
    ).first()
    if not row:
        return
    if json.loads(row.config) != default_structural_appendix_config():
        return
    op.execute(_report_templates.delete().where(_report_templates.c.id == row.id))
