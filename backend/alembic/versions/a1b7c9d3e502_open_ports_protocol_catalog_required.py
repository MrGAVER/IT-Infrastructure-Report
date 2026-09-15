"""open_ports.protocol_catalog_id становится обязательным (backfill + NOT NULL)

Revision ID: a1b7c9d3e502
Revises: 1e7441f45639
Create Date: 2026-09-16 00:00:00.000000

Правка "убрать текстовые поля Порт/Протокол" (см. backend/app/services/crud.py:
_apply_open_port_catalog) сделала protocol_catalog_id обязательным только на уровне приложения —
строки, заведённые ДО этой правки (или созданные напрямую через ORM в обход API, как в тестах),
могли остаться без ссылки на справочник; порт/протокол таких строк при этом никогда не
пересчитывался и не проверялся на соответствие справочнику. Эта миграция закрывает разрыв на
уровне схемы, а не только в API:

1. Бэкфиллит protocol_catalog_id для всех open_ports, где он ещё NULL — находит подходящую запись
   protocol_port_catalogs по (port, COALESCE(protocol, transport_protocol)) или заводит новую, если
   такой комбинации в справочнике ещё нет. Тот же приём бэкфилла, что и в 8c5d1f7a2b40, которая
   изначально ввела эту колонку как nullable ("сначала подстелить соломку — потом ужесточать").
2. Переводит protocol_catalog_id в NOT NULL. На SQLite — полной пересборкой таблицы с ИМЕНОВАННЫМИ
   ограничениями (тот же приём, что 38e9b2624a53/f4a29c7e1d60: batch_alter_table на SQLite не
   гарантированно переносит существующие FK/индексы через reflection). На PostgreSQL — обычный
   ALTER COLUMN SET NOT NULL, он не теряет уже существующие ограничения.

Downgrade возвращает колонку в nullable той же пересборкой; заполненные миграцией ссылки
намеренно НЕ стираются обратно в NULL — они не мешают работе более старой версии кода (та их
просто не читала), а откатывать реальные, уже нужные кому-то данные ради чистоты отката смысла
нет.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "a1b7c9d3e502"
down_revision = "1e7441f45639"
branch_labels = None
depends_on = None


def _backfill_protocol_catalog_id(bind) -> None:
    now = datetime.now(timezone.utc)
    rows = bind.execute(
        sa.text("SELECT id, port, protocol, transport_protocol FROM open_ports WHERE protocol_catalog_id IS NULL")
    ).fetchall()
    for open_port_id, port, protocol, transport_protocol in rows:
        # Тот же fallback-порядок, что и в 8c5d1f7a2b40: сперва прикладной протокол строки, потом
        # транспортный (у него есть server_default='TCP', так что практически всегда есть чем
        # заполнить), и только если оба пусты (в реальных данных не встречалось, но port был
        # обязателен всегда, а протокол — нет) — явная техническая пометка, не пустая строка,
        # чтобы не конфликтовать с NOT NULL protocol_type у protocol_port_catalogs молча.
        protocol_type = protocol or transport_protocol or "Не указан"
        catalog_id = bind.execute(
            sa.text("SELECT id FROM protocol_port_catalogs WHERE port=:p AND protocol_type=:t"),
            {"p": port, "t": protocol_type},
        ).scalar()
        if not catalog_id:
            catalog_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO protocol_port_catalogs (id, port, protocol_type, created_at, updated_at) "
                    "VALUES (:id, :p, :t, :c, :c)"
                ),
                {"id": catalog_id, "p": port, "t": protocol_type, "c": now},
            )
        bind.execute(sa.text("UPDATE open_ports SET protocol_catalog_id=:c WHERE id=:i"), {"c": catalog_id, "i": open_port_id})


def _rebuild_open_ports_sqlite(bind, *, not_null: bool) -> None:
    """SQLite `batch_alter_table` не гарантированно переносит FK/индекс через reflection (см.
    38e9b2624a53/f4a29c7e1d60) — как и там, пересобираем таблицу вручную с явным DDL. Параметр
    not_null переиспользуется upgrade()/downgrade() — единственное отличие между ними."""
    null_clause = "NOT NULL" if not_null else ""
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(
        sa.text(
            f"""CREATE TABLE open_ports_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        owner_type VARCHAR(50) NOT NULL,
        owner_id VARCHAR(36) NOT NULL,
        transport_protocol VARCHAR(10) NOT NULL DEFAULT 'TCP',
        port INTEGER NOT NULL,
        protocol VARCHAR(100),
        protocol_catalog_id VARCHAR(36) {null_clause},
        ip_address VARCHAR(64),
        description TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT fk_open_ports_protocol_catalog FOREIGN KEY(protocol_catalog_id) REFERENCES protocol_port_catalogs (id)
    )"""
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO open_ports_new (id, owner_type, owner_id, transport_protocol, port, protocol, "
            "protocol_catalog_id, ip_address, description, created_at, updated_at) "
            "SELECT id, owner_type, owner_id, transport_protocol, port, protocol, protocol_catalog_id, "
            "ip_address, description, created_at, updated_at FROM open_ports"
        )
    )
    bind.execute(sa.text("DROP TABLE open_ports"))
    bind.execute(sa.text("ALTER TABLE open_ports_new RENAME TO open_ports"))
    bind.execute(sa.text("CREATE INDEX ix_open_ports_protocol_catalog_id ON open_ports (protocol_catalog_id)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    bind = op.get_bind()
    _backfill_protocol_catalog_id(bind)
    if bind.dialect.name == "sqlite":
        _rebuild_open_ports_sqlite(bind, not_null=True)
    else:
        op.alter_column("open_ports", "protocol_catalog_id", existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_open_ports_sqlite(bind, not_null=False)
    else:
        op.alter_column("open_ports", "protocol_catalog_id", existing_type=sa.String(length=36), nullable=True)
