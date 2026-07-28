"""Sprint 2 — cho phép business_unit = 'CROSS_BU' trong metadata.feature_catalog.

Schema Sprint 1 khóa `business_unit IN ('GSM','VINFAST')`. Bảng
`feature.customer_cross_bu_feature` (Task 2.3) không thuộc đơn vị nào trong hai —
nó là tầng tổng hợp xuyên đơn vị, và retriever cần định tuyến theo đúng nhãn đó
(Task 2.6 sẽ gọi `retrieve(..., business_unit="CROSS_BU")`).

Trước migration này, `generate_semantic_layer` hard-code "không phải GSM ⇒ VINFAST"
nên seed vẫn chạy được — nhưng 9 feature cross-BU bị gắn sai nhãn và không định
tuyến được. Sửa nhãn mà không nới CHECK thì seed sẽ fail.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_CONSTRAINT = "chk_feature_catalog_bu"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Feature catalog constraint change requires PostgreSQL.")
    op.execute(f"ALTER TABLE metadata.feature_catalog DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"""
        ALTER TABLE metadata.feature_catalog
        ADD CONSTRAINT {_CONSTRAINT}
        CHECK (business_unit IN ('GSM', 'VINFAST', 'CROSS_BU'))
    """)


def downgrade() -> None:
    # Chỉ chạy được khi không còn dòng CROSS_BU nào — nếu còn, ALTER sẽ fail và đó là
    # hành vi đúng: hạ constraint mà vẫn còn dữ liệu vi phạm nghĩa là mất dữ liệu.
    op.execute(f"ALTER TABLE metadata.feature_catalog DROP CONSTRAINT IF EXISTS {_CONSTRAINT}")
    op.execute(f"""
        ALTER TABLE metadata.feature_catalog
        ADD CONSTRAINT {_CONSTRAINT}
        CHECK (business_unit IN ('GSM', 'VINFAST'))
    """)
