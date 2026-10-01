"""Маркеры однократного сидирования справочников: catalog_seed_markers

Revision ID: e4c8a1d7b350
Revises: d9a4f2c8b516
Create Date: 2026-10-01 00:00:00.000000

Баг: стандартные значения справочников (скорости/типы интерфейсов, типы подключений, ОС,
производители, протоколы и т.д.) восстанавливались при каждом перезапуске приложения —
services/catalogs.py:seed_defaults() на старте добавлял любую отсутствующую по имени запись, в том
числе удалённую или переименованную администратором. Теперь стартовое сидирование выполняется один
раз: факт выполнения хранится в таблице catalog_seed_markers (см. models.CatalogSeedMarker).

Для уже работающих баз маркер проставляется здесь же: если в БД есть следы прошлого запуска
приложения, значит, сидирование уже выполнялось, и повторять его нельзя — иначе ровно те записи,
которые администратор удалил, вернулись бы ещё раз при первом старте после обновления. Следы —
только в таблицах, которые заполняет ИСКЛЮЧИТЕЛЬНО приложение при запуске (производители,
встроенные ОС, здание/организация поддержки/подразделение по умолчанию, запись auth_settings).
Скорости/типы интерфейсов, ОС и протоколы для этого признака не годятся: часть их стандартных
значений вставляют сами миграции (f2a9c7d1e530 и др.), поэтому они непусты и на свежей базе.
Свежая база маркера не получает — первый запуск приложения заведёт стартовые значения как раньше.

downgrade() работает: удаляет таблицу маркеров (данные справочников не затрагиваются; после отката
старая версия приложения снова будет добавлять недостающие стандартные записи на каждом старте).
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "e4c8a1d7b350"
down_revision = "d9a4f2c8b516"
branch_labels = None
depends_on = None

# Должно совпадать с services/catalogs.py:DEFAULT_CATALOGS_SEED_MARKER (проверяет тест).
DEFAULT_CATALOGS_SEED_MARKER = "default_catalogs.v1"

# Таблицы, которые наполняет только seed_defaults()/старт приложения (миграции их не трогают), и
# auth_settings — запись создаётся при первом же запуске. Список имён — константа миграции, а не
# пользовательский ввод (поэтому подстановка в SQL ниже безопасна).
_USED_DB_SENTINEL_TABLES = (
    "manufacturers",
    "embedded_operating_systems",
    "buildings",
    "support_organizations",
    "departments",
    "auth_settings",
)


def _database_was_used(bind: sa.engine.Connection) -> bool:
    inspector = sa.inspect(bind)
    for table in _USED_DB_SENTINEL_TABLES:
        if not inspector.has_table(table):
            continue
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            return True
    return False


def upgrade() -> None:
    markers = op.create_table(
        "catalog_seed_markers",
        sa.Column("name", sa.String(length=100), primary_key=True),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
    )
    if _database_was_used(op.get_bind()):
        op.bulk_insert(markers, [{"name": DEFAULT_CATALOGS_SEED_MARKER, "applied_at": datetime.now(timezone.utc).replace(tzinfo=None)}])


def downgrade() -> None:
    op.drop_table("catalog_seed_markers")
