"""Sprint 2 — mở rộng cửa sổ cho feature PIT/cross-BU + cột handover scheduled.

Bản đầu của Task 2.2/2.3 chỉ có cửa sổ `l1m`, nên:
  - "Tổng cộng bao nhiêu xe đã bàn giao?" (UC2-10) trả lời bằng số của tháng gần nhất;
  - "So sánh GSM 1 tháng với VinFast 3 tháng" (UC2-18) không có cột để so;
  - "Hành vi GSM của nhóm chủ xe" (UC2-06) chỉ nhìn được một tháng.

Thêm `l3m`, `l6m`, `l12m` và `all` (luỹ kế tới ngày snapshot) cho mọi feature Sprint 2
trước đây chỉ có `l1m`. Cột luỹ kế (`is_vehicle_buyer`, `first_*`, `days_since_*`,
`cross_bu_engagement_score`, `gsm_active_vehicle_owner_flag`) giữ nguyên không cửa sổ.

Thêm `is_vehicle_handover_scheduled` cho UC2-09 (đã hẹn giao, chưa nhận xe) — không có
cột này thì nhóm "đã hẹn" bị gộp chung với "mua nhưng chưa hẹn".

UC2-08 (đã trả xe / handover reversed) CỐ Ý không có cột: đã đưa ra ngoài phạm vi
Sprint 2, xem docs/sprint2_definition_of_done.md §3.7.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_EXTRA_WINDOWS = ("l3m", "l6m", "l12m", "all")

# feature.vinfast_transaction
_VF_COLUMNS: dict[str, str] = {
    **{f"vehicle_purchase_completed_count_{w}": "INTEGER" for w in _EXTRA_WINDOWS},
    **{f"vehicle_delivered_count_{w}": "INTEGER" for w in _EXTRA_WINDOWS},
    "is_vehicle_handover_scheduled": "BOOLEAN",
}

# feature.customer_cross_bu_feature — cờ NOT NULL DEFAULT FALSE vì bảng đã có dữ liệu;
# seed ghi đè ngay sau đó.
_CROSS_COLUMNS: dict[str, str] = {
    **{f"is_active_gsm_{w}": "BOOLEAN NOT NULL DEFAULT FALSE" for w in _EXTRA_WINDOWS},
    **{f"is_active_vinfast_{w}": "BOOLEAN NOT NULL DEFAULT FALSE" for w in _EXTRA_WINDOWS},
    **{f"is_cross_bu_active_{w}": "BOOLEAN NOT NULL DEFAULT FALSE" for w in _EXTRA_WINDOWS},
    **{f"gsm_spend_{w}": "NUMERIC(20,4)" for w in _EXTRA_WINDOWS},
    **{f"vinfast_spend_{w}": "NUMERIC(20,4)" for w in _EXTRA_WINDOWS},
    **{f"combined_spend_{w}": "NUMERIC(20,4)" for w in _EXTRA_WINDOWS},
    **{f"dominant_business_unit_{w}": "VARCHAR(10)" for w in _EXTRA_WINDOWS},
}


def _add(table: str, columns: dict[str, str]) -> None:
    for name, dtype in columns.items():
        op.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{name}" {dtype}')


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Sprint 2 window expansion requires PostgreSQL.")
    _add("feature.vinfast_transaction", _VF_COLUMNS)
    _add("feature.customer_cross_bu_feature", _CROSS_COLUMNS)

    # CHECK của 0005 chỉ phủ l1m — mỗi cửa sổ mới cần ràng buộc riêng, nếu không
    # cờ tổng hợp có thể lệch hai cờ thành phần mà không ai biết.
    for w in _EXTRA_WINDOWS:
        op.execute(f"""
            ALTER TABLE feature.customer_cross_bu_feature
            DROP CONSTRAINT IF EXISTS chk_cross_bu_active_matches_parts_{w}
        """)
        op.execute(f"""
            ALTER TABLE feature.customer_cross_bu_feature
            ADD CONSTRAINT chk_cross_bu_active_matches_parts_{w}
            CHECK (is_cross_bu_active_{w} = (is_active_gsm_{w} AND is_active_vinfast_{w}))
        """)
        op.execute(f"""
            ALTER TABLE feature.customer_cross_bu_feature
            DROP CONSTRAINT IF EXISTS chk_cross_bu_dominant_unit_{w}
        """)
        op.execute(f"""
            ALTER TABLE feature.customer_cross_bu_feature
            ADD CONSTRAINT chk_cross_bu_dominant_unit_{w}
            CHECK (dominant_business_unit_{w} IS NULL
                   OR dominant_business_unit_{w} IN ('GSM', 'VINFAST', 'TIE'))
        """)

    op.execute("""
        COMMENT ON COLUMN feature.customer_cross_bu_feature.gsm_spend_all IS
        'Cumulative GSM spend up to snapshot_date (no rolling window). Use this for "total / to date" questions; l1m answers a different question.'
    """)
    op.execute("""
        COMMENT ON COLUMN feature.vinfast_transaction.is_vehicle_handover_scheduled IS
        'TRUE when a handover was scheduled on or before the snapshot but not yet completed. Scheduled is not ownership.'
    """)


def downgrade() -> None:
    for w in _EXTRA_WINDOWS:
        for prefix in ("chk_cross_bu_active_matches_parts", "chk_cross_bu_dominant_unit"):
            op.execute(f"""
                ALTER TABLE feature.customer_cross_bu_feature
                DROP CONSTRAINT IF EXISTS {prefix}_{w}
            """)
    for name in _CROSS_COLUMNS:
        op.execute(
            f'ALTER TABLE feature.customer_cross_bu_feature DROP COLUMN IF EXISTS "{name}"')
    for name in _VF_COLUMNS:
        op.execute(f'ALTER TABLE feature.vinfast_transaction DROP COLUMN IF EXISTS "{name}"')
