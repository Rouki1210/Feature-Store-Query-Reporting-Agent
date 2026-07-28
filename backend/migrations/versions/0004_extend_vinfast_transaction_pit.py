"""Sprint 2 — 7 cột buyer/owner point-in-time cho feature.vinfast_transaction.

Tách hẳn "đã mua xe" (từ status history) khỏi "đã nhận xe" (từ handover). Hai
con số này ĐƯỢC PHÉP khác nhau — đó là điểm chính của Task 2.2.

Ngữ nghĩa: docs/vehicle_owner_semantics.md
Cột không có hậu tố window = trạng thái TẠI snapshot, không phải tổng hợp cửa sổ.

Migration cố ý đóng băng bản danh sách riêng (không import app code) để replay ổn
định — test `test_migration_inventory_matches_feature_spec` canh hai bản không drift.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


_PIT_COLUMNS: dict[str, str] = {
    "vehicle_purchase_completed_count_l1m": "INTEGER",
    "vehicle_delivered_count_l1m": "INTEGER",
    "is_vehicle_buyer": "BOOLEAN",
    "is_vehicle_owner": "BOOLEAN",
    "first_vehicle_purchase_date": "DATE",
    "first_vehicle_handover_date": "DATE",
    "days_since_last_vehicle_handover": "INTEGER",
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("VinFast point-in-time features require PostgreSQL.")
    for name, dtype in _PIT_COLUMNS.items():
        op.execute(
            f'ALTER TABLE feature."vinfast_transaction" '
            f'ADD COLUMN IF NOT EXISTS "{name}" {dtype}'
        )
    op.execute("""
        COMMENT ON COLUMN feature.vinfast_transaction.is_vehicle_owner IS
        'TRUE when the customer had a completed, non-reversed vehicle handover as of snapshot_date. Never derive this from order status.'
    """)
    op.execute("""
        COMMENT ON COLUMN feature.vinfast_transaction.is_vehicle_buyer IS
        'TRUE when a vehicle order reached completed in the status history as of snapshot_date. Buying is not receiving.'
    """)


def downgrade() -> None:
    # Khác 0002: 7 cột này do Sprint 2 tạo, chưa có nguồn dữ liệu nào ngoài mock
    # generator nên drop được mà không mất dữ liệu thật.
    for name in _PIT_COLUMNS:
        op.execute(f'ALTER TABLE feature."vinfast_transaction" DROP COLUMN IF EXISTS "{name}"')
