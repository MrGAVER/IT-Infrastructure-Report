"""Недостающие индексы внешних ключей: схема из миграций догоняет models.py

Revision ID: c5d2e8a4b713
Revises: b3f7a1d95c24
Create Date: 2026-10-28 00:00:00.000000

Тест `tests/test_migrations_match_models.py` сравнил схему «после `alembic upgrade head`» с моделями и нашёл индексы,
которые модели объявляют (`index=True` у внешних ключей), а в базах из миграций их нет. Эта миграция создаёт ровно их:

  • containers.physical_device_id, vlan_domain_devices.domain_id, vlan_domain_devices.physical_device_id,
    vlan_domains.source_device_id — индексов не было ни на одной СУБД (таблицы создавались без них);
  • information_systems.support_method_id / crypto_protection_description_id / support_organization_id — их создавали
    миграции d3f9a1c6b750, e7a2c9f4d813 и др., но на SQLite последующая пересборка таблицы (`batch_alter_table`) их
    теряла; на PostgreSQL они на месте.

Идемпотентность: состояние определяется по схеме, а не по диалекту. Индекс не создаётся, если на таблице уже есть индекс
с таким именем **или** по тому же набору колонок под другим именем (иначе вышли бы дубли). Данные не меняются; на больших
таблицах `CREATE INDEX` кратковременно блокирует запись — для реестра такого размера это секунды.

downgrade() удаляет только индексы, появившиеся впервые здесь (первые четыре). Индексы information_systems принадлежат
более ранним миграциям (их downgrade удаляет сам), поэтому откат этой ревизии их не трогает.

Намеренно НЕ входит (решения владельца продукта, см. whitelist в тесте-страже): выравнивание NOT NULL у created_at /
updated_at, уникальные ограничения, дублирующие индексы. NOT NULL у connection_type_id / device_type_id и удаление
устаревших колонок os_name / os_version / virtualization_platform_id с таблицей virtualization_platforms выполнены позже —
миграциями d7a3f1c8b254 и e9b4c2a7d136.
"""
import sqlalchemy as sa
from alembic import op

revision = 'c5d2e8a4b713'
down_revision = 'b3f7a1d95c24'
branch_labels = None
depends_on = None

# (имя индекса, таблица, колонка, создан ли впервые этой миграцией)
INDEXES = (
    ('ix_containers_physical_device_id', 'containers', 'physical_device_id', True),
    ('ix_vlan_domain_devices_domain_id', 'vlan_domain_devices', 'domain_id', True),
    ('ix_vlan_domain_devices_physical_device_id', 'vlan_domain_devices', 'physical_device_id', True),
    ('ix_vlan_domains_source_device_id', 'vlan_domains', 'source_device_id', True),
    ('ix_information_systems_support_method_id', 'information_systems', 'support_method_id', False),
    ('ix_information_systems_crypto_protection_description_id', 'information_systems', 'crypto_protection_description_id', False),
    ('ix_information_systems_support_organization_id', 'information_systems', 'support_organization_id', False),
)


def _covered(inspector, table: str, name: str, column: str) -> bool:
    """Есть ли на таблице индекс с этим именем или индекс ровно по этой колонке (под другим именем)."""
    return any(
        index['name'] == name or list(index['column_names']) == [column]
        for index in inspector.get_indexes(table)
    )


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, column, _first_time in INDEXES:
        if table not in tables or _covered(inspector, table, name, column):
            continue
        op.create_index(name, table, [column])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name, table, _column, first_time in INDEXES:
        if first_time and table in tables and any(index['name'] == name for index in inspector.get_indexes(table)):
            op.drop_index(name, table_name=table)
