"""Удаление устаревших os_name / os_version / virtualization_platform_id и таблицы virtualization_platforms

Revision ID: e9b4c2a7d136
Revises: d7a3f1c8b254
Create Date: 2026-10-29 00:00:00.000000

Приведение схемы из миграций к моделям, часть 3 (решение владельца продукта). Миграция c4e8a7d91b20 перенесла справочник гипервизоров и свободный текст ОС в
каталог `operating_systems` (категории «Гипервизор» и «Другое») и оставила старые объекты «для обратной совместимости»:

  • physical_devices.os_name, physical_devices.os_version;
  • virtual_machines.os_name, virtual_machines.os_version, virtual_machines.virtualization_platform_id (внешний ключ);
  • таблицу virtualization_platforms.

Модели, API, отчёты и интерфейс их не используют (проверено поиском по коду и тестам), ORM их не заполняет, а владелец
продукта подтвердил запросом по своей базе, что значений в них нет. Остатки только путают (две «правды» об ОС и
гипервизоре) и тянут расхождение «схема из миграций ↔ модели» (тест test_migrations_match_models.py).

Порядок работы:
  1. Предпроверка потери данных — ДО любых изменений. Миграция останавливается с понятным сообщением, если
       • у устройства/ВМ есть значение os_name/os_version, а замены в каталоге нет (operating_system_id пуст; у устройства —
         ещё и embedded_os_id);
       • у ВМ задана virtualization_platform_id, а hypervisor_os_id пуст;
       • в virtualization_platforms есть строка, которой нет в `operating_systems` (по имени и версии).
     Значения, которые уже перенесены в каталог, не считаются потерей: c4e8a7d91b20 копировал их, не очищая исходные
     колонки, поэтому в старых базах они остаются заполненными.
  2. PostgreSQL — `DROP COLUMN` (внешний ключ исчезает вместе с колонкой) и `DROP TABLE`; DDL транзакционный.
     SQLite — требуется версия ≥ 3.35 (проверяется заранее): у `physical_devices` колонки удаляются штатным
     `ALTER TABLE … DROP COLUMN`, без пересборки (таблица — родитель десятков внешних ключей, на ней частичный уникальный
     индекс `uq_device_rack_slot` и триггер защиты). У `virtual_machines` колонка с внешним ключом штатно не удаляется —
     таблица пересобирается через `batch_alter_table`; индексы и именованные ограничения при этом сохраняются, а триггер
     `trg_is_source_guard_virtual_machines` (его пересборка уничтожает) пересоздаётся из сохранённого SQL.
  3. `virtualization_platforms` удаляется последней: если на неё всё ещё что-то ссылается, `DROP TABLE` упадёт, а не потеряет
     ссылку молча.

Идемпотентность: каждый объект удаляется только если он есть. Данные других колонок не меняются.

downgrade() возвращает ПУСТЫЕ объекты (колонки без значений, пустую таблицу и внешний ключ): удалённые данные
восстановить нельзя — после upgrade в них нет ничего, что не перенесено в каталог (предпроверка). Повторный upgrade после
такого отката проходит.
"""
from contextlib import contextmanager
import sqlite3

import sqlalchemy as sa
from alembic import op

revision = 'e9b4c2a7d136'
down_revision = 'd7a3f1c8b254'
branch_labels = None
depends_on = None

PLATFORMS = 'virtualization_platforms'
LEGACY_COLUMNS = {
    'physical_devices': ('os_name', 'os_version'),
    'virtual_machines': ('os_name', 'os_version', 'virtualization_platform_id'),
}
VM_PLATFORM_FK = 'fk_virtual_machines_virtualization_platform'
MIN_SQLITE = (3, 35, 0)  # ALTER TABLE … DROP COLUMN


def _columns(inspector, table: str) -> set:
    return {column['name'] for column in inspector.get_columns(table)}


@contextmanager
def _foreign_keys_off(bind):
    """Выключает проверку внешних ключей SQLite на время пересборки таблицы и возвращает прежнее значение."""
    previous = bind.execute(sa.text('PRAGMA foreign_keys')).scalar()
    bind.execute(sa.text('PRAGMA foreign_keys=OFF'))
    try:
        yield
    finally:
        bind.execute(sa.text(f'PRAGMA foreign_keys={1 if previous else 0}'))


@contextmanager
def _keep_triggers(bind, table: str):
    """Пересборка таблицы SQLite удаляет её триггеры — сохраняем их SQL и создаём заново."""
    triggers = bind.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = :table AND sql IS NOT NULL"),
        {'table': table},
    ).scalars().all()
    yield
    for sql in triggers:
        bind.exec_driver_sql(sql)


# ---------------------------------------------------------------------------------------------------------------------
# Предпроверка
# ---------------------------------------------------------------------------------------------------------------------
def _loss_checks(inspector):
    """(описание, SQL подсчёта) для тех проверок, чьи колонки и таблицы ещё существуют."""
    tables = set(inspector.get_table_names())
    checks = []
    if 'physical_devices' in tables:
        have = _columns(inspector, 'physical_devices')
        if {'os_name', 'os_version'} & have:
            text = ' OR '.join(f'{c} IS NOT NULL' for c in ('os_name', 'os_version') if c in have)
            checks.append((
                'physical_devices: os_name/os_version без operating_system_id и embedded_os_id',
                f'SELECT COUNT(*) FROM physical_devices WHERE ({text}) AND operating_system_id IS NULL AND embedded_os_id IS NULL',
            ))
    if 'virtual_machines' in tables:
        have = _columns(inspector, 'virtual_machines')
        if {'os_name', 'os_version'} & have:
            text = ' OR '.join(f'{c} IS NOT NULL' for c in ('os_name', 'os_version') if c in have)
            checks.append((
                'virtual_machines: os_name/os_version без operating_system_id',
                f'SELECT COUNT(*) FROM virtual_machines WHERE ({text}) AND operating_system_id IS NULL',
            ))
        if 'virtualization_platform_id' in have:
            checks.append((
                'virtual_machines: virtualization_platform_id без hypervisor_os_id',
                'SELECT COUNT(*) FROM virtual_machines WHERE virtualization_platform_id IS NOT NULL AND hypervisor_os_id IS NULL',
            ))
    if PLATFORMS in tables:
        checks.append((
            'virtualization_platforms: строки без пары в operating_systems (имя + версия)',
            f'SELECT COUNT(*) FROM {PLATFORMS} p WHERE NOT EXISTS (SELECT 1 FROM operating_systems o WHERE o.name = p.name '
            'AND (o.version = p.version OR (o.version IS NULL AND p.version IS NULL)))',
        ))
    return checks


def _assert_nothing_is_lost(bind, inspector) -> None:
    problems = []
    for title, query in _loss_checks(inspector):
        count = bind.execute(sa.text(query)).scalar()
        if count:
            problems.append(f'{title}: {count}')
    if problems:
        raise RuntimeError(
            'Миграция e9b4c2a7d136 остановлена: удаление устаревших колонок и таблицы потеряло бы данные, которых нет в '
            'каталоге операционных систем (' + '; '.join(problems) + '). Перенесите значения в справочники '
            '(operating_system_id / hypervisor_os_id) или очистите их осознанно и повторите `alembic upgrade head`. '
            'Данные миграция не меняет.'
        )


# ---------------------------------------------------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------------------------------------------------
def _upgrade_sqlite(bind) -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        raise RuntimeError(
            f'Миграция e9b4c2a7d136 требует SQLite не ниже 3.35 (ALTER TABLE … DROP COLUMN), установлена {sqlite3.sqlite_version}. '
            'Обновите Python/SQLite и повторите `alembic upgrade head`; данные не изменены.'
        )
    inspector = sa.inspect(bind)
    for column in LEGACY_COLUMNS['physical_devices']:
        if column in _columns(inspector, 'physical_devices'):
            op.drop_column('physical_devices', column)

    vm_columns = [c for c in LEGACY_COLUMNS['virtual_machines'] if c in _columns(inspector, 'virtual_machines')]
    if vm_columns:
        with _foreign_keys_off(bind), _keep_triggers(bind, 'virtual_machines'):
            with op.batch_alter_table('virtual_machines', recreate='always') as batch:
                for column in vm_columns:
                    batch.drop_column(column)


def _upgrade_postgresql() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in LEGACY_COLUMNS.items():
        for column in columns:
            if column in _columns(inspector, table):
                op.drop_column(table, column)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _assert_nothing_is_lost(bind, inspector)
    if bind.dialect.name == 'sqlite':
        _upgrade_sqlite(bind)
    else:
        _upgrade_postgresql()
    if PLATFORMS in sa.inspect(bind).get_table_names():
        op.drop_table(PLATFORMS)


# ---------------------------------------------------------------------------------------------------------------------
# downgrade: пустые объекты
# ---------------------------------------------------------------------------------------------------------------------
def _create_platforms_table() -> None:
    op.create_table(
        PLATFORMS,
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('vendor', sa.String(length=255), nullable=True),
        sa.Column('version', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    bind = op.get_bind()
    if PLATFORMS not in sa.inspect(bind).get_table_names():
        _create_platforms_table()
    inspector = sa.inspect(bind)

    for column in LEGACY_COLUMNS['physical_devices']:
        if column not in _columns(inspector, 'physical_devices'):
            op.add_column('physical_devices', sa.Column(column, sa.String(length=255), nullable=True))

    missing = [c for c in LEGACY_COLUMNS['virtual_machines'] if c not in _columns(inspector, 'virtual_machines')]
    if not missing:
        return

    def add_columns(batch) -> None:
        for column in missing:
            if column == 'virtualization_platform_id':
                batch.add_column(sa.Column(column, sa.String(length=36), nullable=True))
                batch.create_foreign_key(VM_PLATFORM_FK, PLATFORMS, [column], ['id'])
            else:
                batch.add_column(sa.Column(column, sa.String(length=255), nullable=True))

    if bind.dialect.name == 'sqlite':
        with _foreign_keys_off(bind), _keep_triggers(bind, 'virtual_machines'):
            with op.batch_alter_table('virtual_machines', recreate='always') as batch:
                add_columns(batch)
    else:
        with op.batch_alter_table('virtual_machines') as batch:
            add_columns(batch)
