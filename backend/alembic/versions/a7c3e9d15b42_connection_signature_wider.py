"""Connections: port_config_approved_signature VARCHAR(64) -> VARCHAR(255)

Сверка конфигурации портов-соседей теперь учитывает не только роль, но и режим порта (trunk /
access) и набор VLAN, поэтому подпись одобренного расхождения стала длиннее: роль («источник>
назначение», до 31 символа) + режим (`|mode:trunk>access`) + отпечатки наборов VLAN
(`|vlan:<число>><число>`) — вместе до ~95 символов, а колонка была на 64 (PostgreSQL отверг бы
вставку; SQLite длину не проверяет, поэтому тесты этого не ловят).

Данные не меняются. Ранее записанные подписи вида `management>data` остаются валидными: новая
подпись содержит только различающиеся грани, и для пары, у которой различается одна лишь роль,
совпадает с прежней (services/port_config.py). Пара, у которой теперь расходятся ещё и режим или
VLAN, сама вернётся в «расхождение» — одобрение покрывало только роли, а новое различие
пользователь не видел.

downgrade() сужает колонку обратно. Подписи нового формата (содержат `|` или длиннее 64 символов)
перед этим обнуляются: прежний код не умеет их сверять, а PostgreSQL не дал бы сузить колонку при
слишком длинных значениях. Затронутые подключения вернутся в «расхождение» и потребуют повторного
одобрения.

Revision ID: a7c3e9d15b42
Revises: b8e4d2a7c91f
Create Date: 2026-10-02 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "a7c3e9d15b42"
down_revision = "b8e4d2a7c91f"
branch_labels = None
depends_on = None

_OLD_LENGTH = 64
_NEW_LENGTH = 255


def upgrade() -> None:
    with op.batch_alter_table("connections") as batch:
        batch.alter_column(
            "port_config_approved_signature",
            existing_type=sa.String(_OLD_LENGTH),
            type_=sa.String(_NEW_LENGTH),
            existing_nullable=True,
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE connections SET port_config_approved_signature = NULL "
            "WHERE port_config_approved_signature LIKE '%|%' OR LENGTH(port_config_approved_signature) > :n"
        ).bindparams(n=_OLD_LENGTH)
    )
    with op.batch_alter_table("connections") as batch:
        batch.alter_column(
            "port_config_approved_signature",
            existing_type=sa.String(_NEW_LENGTH),
            type_=sa.String(_OLD_LENGTH),
            existing_nullable=True,
        )
