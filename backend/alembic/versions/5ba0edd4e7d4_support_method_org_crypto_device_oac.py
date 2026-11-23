"""Support method <-> organization link; crypto means <-> device link; device OAC certificate

Revision ID: 5ba0edd4e7d4
Revises: 1e7441f45639
Create Date: 2026-09-16 00:00:00.000000

Полностью аддитивная миграция для трёх независимых доработок формы "Информационная система" /
"Физическое устройство":

1) support_methods.support_organization_id — способ оказания техподдержки теперь можно
   привязать к конкретной организации техподдержки (SupportOrganization). Nullable: запись без
   организации считается универсальной (подходит любой), включая все уже существующие записи
   справочника на момент миграции — им не назначается никакая организация автоматически.
2) crypto_protection_means.physical_device_id — средство криптографической защиты привязывается
   к конкретному физическому устройству реестра. Тоже nullable по той же причине.
3) physical_devices.oac_certificate_number / oac_certificate_registry_date — необязательный
   блок "Сертификат ОАЦ" на карточке устройства, оба поля независимы и nullable.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "5ba0edd4e7d4"
down_revision = "1e7441f45639"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("support_methods") as batch:
        batch.add_column(sa.Column("support_organization_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_support_methods_support_organization", "support_organizations", ["support_organization_id"], ["id"]
        )
        batch.create_index("ix_support_methods_support_organization_id", ["support_organization_id"])

    with op.batch_alter_table("crypto_protection_means") as batch:
        batch.add_column(sa.Column("physical_device_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_crypto_protection_means_physical_device", "physical_devices", ["physical_device_id"], ["id"]
        )
        batch.create_index("ix_crypto_protection_means_physical_device_id", ["physical_device_id"])

    with op.batch_alter_table("physical_devices") as batch:
        batch.add_column(sa.Column("oac_certificate_number", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("oac_certificate_registry_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("physical_devices") as batch:
        batch.drop_column("oac_certificate_registry_date")
        batch.drop_column("oac_certificate_number")

    with op.batch_alter_table("crypto_protection_means") as batch:
        batch.drop_index("ix_crypto_protection_means_physical_device_id")
        batch.drop_constraint("fk_crypto_protection_means_physical_device", type_="foreignkey")
        batch.drop_column("physical_device_id")

    with op.batch_alter_table("support_methods") as batch:
        batch.drop_index("ix_support_methods_support_organization_id")
        batch.drop_constraint("fk_support_methods_support_organization", type_="foreignkey")
        batch.drop_column("support_organization_id")
