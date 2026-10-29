"""NOT NULL у connections.connection_type_id и device_models.device_type_id

Revision ID: d7a3f1c8b254
Revises: c5d2e8a4b713
Create Date: 2026-10-29 00:00:00.000000

A-14, часть 2 (решение владельца продукта). Модели объявляют обе колонки обязательными (`Mapped[str]`, без `Optional`),
API и интерфейс не дают создать связь без типа и модель без типа устройства, но в базах из миграций колонки остались
необязательными: они появились поздними миграциями как nullable (нужно было заполнить уже существующие строки). Обе
колонки — внешние ключи на справочники; запись без значения сломала бы отчёты и диаграмму (связь без типа, модель, не
попадающая ни в один тип устройства).

Порядок работы:
  1. Предпроверка: если в какой-либо из таблиц есть строки с NULL, миграция останавливается с понятным сообщением ДО
     любых изменений (данные сама не правит — какой тип назначить, решает владелец данных). На PostgreSQL DDL
     транзакционный, на SQLite изменений до этого момента нет вовсе.
  2. PostgreSQL — `ALTER COLUMN … SET NOT NULL` (полный просмотр таблицы под коротким эксклюзивным замком).
     SQLite — пересборка таблицы через `batch_alter_table`: она сохраняет именованные FK/UNIQUE и индексы (проверено
     тестом), триггеров на этих таблицах нет. Внешние ключи на время пересборки выключаются (`device_models` — родитель
     для `physical_devices.model_id`).

Идемпотентность: состояние определяется по схеме (колонка уже NOT NULL — ничего не делаем). Данные не меняются.
downgrade() возвращает колонкам необязательность (снятие NOT NULL ничего не теряет).
"""
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision = 'd7a3f1c8b254'
down_revision = 'c5d2e8a4b713'
branch_labels = None
depends_on = None

# (таблица, колонка)
COLUMNS = (
    ('connections', 'connection_type_id'),
    ('device_models', 'device_type_id'),
)


def _is_nullable(inspector, table: str, column: str) -> bool:
    return next(c['nullable'] for c in inspector.get_columns(table) if c['name'] == column)


def _assert_no_nulls(bind, columns) -> None:
    """Останавливает миграцию, если в обязательной колонке есть пустые значения (данные не правим)."""
    problems = []
    for table, column in columns:
        count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NULL')).scalar()
        if count:
            problems.append(f'{table}.{column}: {count}')
    if problems:
        raise RuntimeError(
            'Миграция d7a3f1c8b254 остановлена: в обязательных колонках есть строки без значения (' + '; '.join(problems) + '). '
            'Назначьте этим строкам тип (UPDATE … SET <колонка> = <id из справочника> WHERE <колонка> IS NULL) и повторите '
            '`alembic upgrade head`. Данные миграция не меняет.'
        )


@contextmanager
def _foreign_keys_off(bind):
    """Выключает проверку внешних ключей SQLite на время пересборки таблицы и возвращает прежнее значение."""
    previous = bind.execute(sa.text('PRAGMA foreign_keys')).scalar()
    bind.execute(sa.text('PRAGMA foreign_keys=OFF'))
    try:
        yield
    finally:
        bind.execute(sa.text(f'PRAGMA foreign_keys={1 if previous else 0}'))


def _set_nullable(nullable: bool) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    todo = [(t, c) for t, c in COLUMNS if _is_nullable(inspector, t, c) != nullable]
    if not todo:
        return
    if not nullable:
        _assert_no_nulls(bind, todo)
    if bind.dialect.name == 'sqlite':
        with _foreign_keys_off(bind):
            for table, column in todo:
                with op.batch_alter_table(table, recreate='always') as batch:
                    batch.alter_column(column, existing_type=sa.String(36), nullable=nullable)
    else:
        for table, column in todo:
            op.alter_column(table, column, existing_type=sa.String(36), nullable=nullable)


def upgrade():
    _set_nullable(False)


def downgrade():
    _set_nullable(True)
