"""Drop unused organizations table

Revision ID: e519c184f3ae
Revises: 5b5ea0e81d32
Create Date: 2026-09-08 00:00:00.000000

Фикс п.4 ("непонятно зачем используется справочник 'Организация'. Если он не используется, то
нужно его удалить"): на таблицу organizations нигде не было ни одной FK-ссылки — ни от одной
другой таблицы (в отличие от support_organizations, на которую ссылается
physical_devices... то есть, если точнее, support_organization_id есть у InformationSystem —
см. backend/app/models.py). services/catalogs.py:_seed_singleton_records при пустой БД всегда
создавал ровно одну запись-заглушку ("Организация" / "ООО «Организация»") — единственное, что
вообще появлялось в этом справочнике на практике, и ничего в приложении на неё не опиралось.

Не путать с client-side настройкой "название организации в шапке сайдбара"
(frontend-vue/src/stores/organization.ts) — это два не связанных друг с другом "organization":
клиентская настройка отображения хранится в localStorage и не имеет отношения к таблице БД,
удаляемой здесь.

ВНИМАНИЕ: если в реальной установке в этот справочник вручную добавляли записи (не просто
дефолтную заглушку), downgrade восстановит структуру таблицы, но не сами данные — они удаляются
безвозвратно вместе с DROP TABLE и не сохраняются нигде.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e519c184f3ae"
down_revision = "5b5ea0e81d32"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("organizations")


def downgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=500), nullable=False, unique=True),
        sa.Column("short_name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
