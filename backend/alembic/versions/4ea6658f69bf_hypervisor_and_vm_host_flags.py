"""Explicit is_hypervisor / allows_vm_hosting flags instead of string-name business rules.

Код-ревью (High/Medium, п.4): validate_hypervisor()/validate_vm_host() определяли бизнес-
правило сравнением строк с именем справочной записи (category.name.casefold()=='гипервизор';
'сервер'/'система хранения'/'storage' в имени типа устройства). Переименование записи в
справочнике (обычная операция через generic CRUD) молча ломало валидацию без единого
сообщения об ошибке. Бэкофилл ниже воспроизводит СТАРУЮ логику один раз при апгрейде, чтобы
поведение существующих БД не изменилось; дальше признак — обычное редактируемое поле.

Revision ID: 4ea6658f69bf
Revises: f4a29c7e1d60
"""
from alembic import op
import sqlalchemy as sa

revision = "4ea6658f69bf"
down_revision = "f4a29c7e1d60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "operating_system_categories",
        sa.Column("is_hypervisor", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "device_types",
        sa.Column("allows_vm_hosting", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Бэкофилл делается в Python, а не через SQL lower()/LIKE: SQLite lower() приводит
    # регистр только для ASCII и молча не трогает кириллицу, поэтому
    # lower(name)='гипервизор' в SQLite не находит 'Гипервизор' (проверено на реальных
    # данных при подготовке миграции). name.casefold() в Python воспроизводит СТАРУЮ логику
    # (validate_hypervisor/validate_vm_host до этой миграции) одинаково на SQLite и PostgreSQL.
    bind = op.get_bind()
    categories = bind.execute(sa.text("SELECT id, name FROM operating_system_categories")).fetchall()
    hypervisor_ids = [row.id for row in categories if row.name.casefold() == "гипервизор"]
    if hypervisor_ids:
        bind.execute(
            sa.text("UPDATE operating_system_categories SET is_hypervisor = true WHERE id = :id"),
            [{"id": i} for i in hypervisor_ids],
        )

    device_types = bind.execute(sa.text("SELECT id, name FROM device_types")).fetchall()
    vm_host_markers = ("сервер", "система хранения", "storage")
    vm_host_ids = [
        row.id for row in device_types
        if any(marker in row.name.casefold() for marker in vm_host_markers)
    ]
    if vm_host_ids:
        bind.execute(
            sa.text("UPDATE device_types SET allows_vm_hosting = true WHERE id = :id"),
            [{"id": i} for i in vm_host_ids],
        )


def downgrade():
    op.drop_column("device_types", "allows_vm_hosting")
    op.drop_column("operating_system_categories", "is_hypervisor")
