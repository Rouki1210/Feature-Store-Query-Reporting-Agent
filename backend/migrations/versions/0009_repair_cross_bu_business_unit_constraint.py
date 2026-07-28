"""Repair the Sprint 2 business-unit constraint left behind by migration 0007."""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Feature catalog constraint change requires PostgreSQL.")
    # 0007 used the wrong name and therefore left the Sprint 1 constraint active.
    op.execute(
        "ALTER TABLE metadata.feature_catalog "
        "DROP CONSTRAINT IF EXISTS chk_feature_catalog_business_unit"
    )
    op.execute(
        "ALTER TABLE metadata.feature_catalog "
        "DROP CONSTRAINT IF EXISTS chk_feature_catalog_bu"
    )
    op.execute(
        "ALTER TABLE metadata.feature_catalog "
        "ADD CONSTRAINT chk_feature_catalog_bu "
        "CHECK (business_unit IN ('GSM', 'VINFAST', 'CROSS_BU'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE metadata.feature_catalog "
        "DROP CONSTRAINT IF EXISTS chk_feature_catalog_bu"
    )
    op.execute(
        "ALTER TABLE metadata.feature_catalog "
        "ADD CONSTRAINT chk_feature_catalog_bu "
        "CHECK (business_unit IN ('GSM', 'VINFAST'))"
    )
