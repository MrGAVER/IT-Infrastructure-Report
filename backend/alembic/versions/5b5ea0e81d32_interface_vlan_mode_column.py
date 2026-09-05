"""Store vlan_mode on device_interfaces itself, not only inferred from links

Revision ID: 5b5ea0e81d32
Revises: 0fcebbb67ac0
Create Date: 2026-09-05 00:00:00.000000

Фикс п.1.3.9: режим порта (access/trunk) хранился только косвенно, через
interface_vlans.mode на каждой связи интерфейс-VLAN. Фронтенд восстанавливал режим при загрузке
по формуле "есть хотя бы одна связь и все её mode == 'access' -> access, иначе trunk"
(api/deviceInterfaces.ts:loadDeviceInterfaceDraftRows). При 0 VLAN на порту связей нет вовсе, и
режим неоткуда восстановить — access-порт без выбранного VLAN после сохранения и следующей
загрузки формы молча превращался в trunk.

Явная колонка на самом интерфейсе снимает эту двусмысленность. Бэкфилл ниже воспроизводит ту же
формулу, что и старый фронтенд-инференс, — у существующих интерфейсов отображаемый режим не
меняется при обновлении на эту миграцию.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "5b5ea0e81d32"
down_revision = "0fcebbb67ac0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_interfaces",
        sa.Column("vlan_mode", sa.String(length=10), nullable=False, server_default="trunk"),
    )
    # Воспроизводит формулу старого фронтенд-инференса: интерфейс переходит в 'access' только
    # если у него есть хотя бы одна связь interface_vlans И mode на ВСЕХ его связях — 'access'.
    # COUNT(*) = SUM(mode == 'access') одновременно даёт оба условия (группа существует только
    # при COUNT(*) >= 1, а равенство сумм означает отсутствие немного 'access' строк).
    op.execute(
        """
        UPDATE device_interfaces
        SET vlan_mode = 'access'
        WHERE id IN (
            SELECT iv.interface_id FROM interface_vlans iv
            GROUP BY iv.interface_id
            HAVING COUNT(*) = SUM(CASE WHEN iv.mode = 'access' THEN 1 ELSE 0 END)
        )
        """
    )


def downgrade() -> None:
    op.drop_column("device_interfaces", "vlan_mode")
