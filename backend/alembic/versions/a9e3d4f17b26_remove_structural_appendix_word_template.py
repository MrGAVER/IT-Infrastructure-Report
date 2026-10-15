"""Удаление шаблона конструктора «Приложение к структурной схеме (по образцу)»

Revision ID: a9e3d4f17b26
Revises: c5d2a8e1f730
Create Date: 2026-10-15 00:00:00.000000

Data-миграция (схему не меняет). Шаблон добавила миграция b44cd42f9fa0 как плоскую заготовку «по мотивам» образца: блочный
редактор Word не умеет группировать строки и объединять ячейки, поэтому VLAN шли одной таблицей с колонкой «Устройство», линия
связи занимала три колонки, а назначение повторялось в каждой строке. Документ по образцу теперь формирует отдельный отчёт
(`POST /api/v1/reports/structural-appendix`, страница «Отчёты», services/structural_appendix*.py), и заготовка в списке
шаблонов дублирует его хуже.

Что удаляется. Только шаблон с именем «Приложение к структурной схеме (по образцу)», конфигурация которого совпадает с
заготовкой из services/report_seed_word_template.py, — вместе с записями его истории версий (они ссылаются на шаблон по
внешнему ключу; у нетронутого шаблона их обычно нет, но возможно «восстановление» версии, равной заготовке). Шаблон, который
пользователь отредактировал, не трогается: в нём его работа, удалить его можно на экране «Шаблоны отчётов». Копии шаблона («… (копия)»)
имеют другое имя и тоже не затрагиваются. Повторный запуск безопасен: нет шаблона — ничего не происходит.

downgrade() работает: возвращает заготовку (если шаблона с таким именем нет), как это делала b44cd42f9fa0. Удалённые версии
истории не восстанавливаются — это были снимки той же самой заготовки.

Модуль services/report_seed_word_template.py остаётся: он нужен этой миграции и b44cd42f9fa0, чтобы обе работали с одним и тем
же эталоном конфигурации.
"""
import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'a9e3d4f17b26'
down_revision = 'c5d2a8e1f730'
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

_report_template_versions = sa.table(
    'report_template_versions',
    sa.column('report_template_id', sa.String),
)


def _is_untouched(config_text: str | None, default_config: dict) -> bool:
    """Конфигурация совпадает с заготовкой. Нечитаемый JSON — это не заготовка: такой шаблон оставляем."""
    try:
        return json.loads(config_text or '') == default_config
    except ValueError:
        return False


def upgrade():
    from app.services.report_seed_word_template import TEMPLATE_NAME, default_structural_appendix_config

    bind = op.get_bind()
    row = bind.execute(
        sa.select(_report_templates.c.id, _report_templates.c.config)
        .where(_report_templates.c.name == TEMPLATE_NAME)
    ).first()
    if not row or not _is_untouched(row.config, default_structural_appendix_config()):
        return
    bind.execute(_report_template_versions.delete().where(_report_template_versions.c.report_template_id == row.id))
    bind.execute(_report_templates.delete().where(_report_templates.c.id == row.id))


def downgrade():
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
