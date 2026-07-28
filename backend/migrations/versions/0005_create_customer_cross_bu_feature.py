"""Sprint 2 — feature.customer_cross_bu_feature (bảng tính sẵn cho câu hỏi xuyên BU).

Agent đọc bảng này thay vì tự join hai bảng feature. Lý do: join thiếu vế
`snapshot_date` biến 1:1 thành 1:N với N = số snapshot, mọi tổng bị nhân lên mà
kết quả vẫn trông hợp lý — dạng lỗi tệ nhất với BI agent (ADR 0001).

Grain: 1 dòng / customer_id / snapshot_date, GIỐNG hai bảng nguồn.
Null semantics: docs/join_policy.md §5 — NULL nghĩa "chưa từng có dữ liệu ở BU đó",
0 nghĩa "có dữ liệu, kỳ này bằng 0". Trộn hai thứ này làm mọi số trung bình sai.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


_TABLE = """
CREATE TABLE IF NOT EXISTS feature.customer_cross_bu_feature (
    customer_id                    BIGINT NOT NULL
                                   REFERENCES raw.customers(customer_id),
    snapshot_date                  DATE NOT NULL,

    is_active_gsm_l1m              BOOLEAN NOT NULL,
    is_active_vinfast_l1m          BOOLEAN NOT NULL,
    is_cross_bu_active_l1m         BOOLEAN NOT NULL,

    gsm_spend_l1m                  NUMERIC(20,4),
    vinfast_spend_l1m              NUMERIC(20,4),
    combined_spend_l1m             NUMERIC(20,4),

    dominant_business_unit_l1m     VARCHAR(10),
    cross_bu_engagement_score      NUMERIC(5,4),
    gsm_active_vehicle_owner_flag  BOOLEAN NOT NULL,

    feature_build_at               TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (customer_id, snapshot_date),

    CONSTRAINT chk_cross_bu_dominant_unit
        CHECK (dominant_business_unit_l1m IS NULL
               OR dominant_business_unit_l1m IN ('GSM', 'VINFAST', 'TIE')),

    -- Cờ tổng hợp phải khớp hai cờ thành phần: lệch nghĩa là pipeline sai.
    CONSTRAINT chk_cross_bu_active_matches_parts
        CHECK (is_cross_bu_active_l1m = (is_active_gsm_l1m AND is_active_vinfast_l1m)),

    CONSTRAINT chk_cross_bu_score_range
        CHECK (cross_bu_engagement_score IS NULL
               OR cross_bu_engagement_score BETWEEN 0 AND 1),

    CONSTRAINT chk_cross_bu_spend_non_negative
        CHECK ((gsm_spend_l1m IS NULL OR gsm_spend_l1m >= 0)
               AND (vinfast_spend_l1m IS NULL OR vinfast_spend_l1m >= 0)
               AND (combined_spend_l1m IS NULL OR combined_spend_l1m >= 0))
);

COMMENT ON TABLE feature.customer_cross_bu_feature IS
'Pre-computed cross-BU view, one row per customer_id + snapshot_date. Answer cross-BU questions from this table instead of joining gsm_transaction with vinfast_transaction.';

COMMENT ON COLUMN feature.customer_cross_bu_feature.vinfast_spend_l1m IS
'NULL means the customer has never had a VinFast order as of the snapshot (no data); 0 means they had orders but spent nothing in the window.';

COMMENT ON COLUMN feature.customer_cross_bu_feature.dominant_business_unit_l1m IS
'GSM | VINFAST | TIE. NULL when combined spend is 0 or unknown - never silently defaults to GSM.';

COMMENT ON COLUMN feature.customer_cross_bu_feature.cross_bu_engagement_score IS
'min(spend)/max(spend) over the two units: 0 = one-sided, 1 = perfectly balanced. NULL when there is nothing to compare.';

CREATE INDEX IF NOT EXISTS idx_cross_bu_snapshot
    ON feature.customer_cross_bu_feature (snapshot_date);

CREATE INDEX IF NOT EXISTS idx_cross_bu_active
    ON feature.customer_cross_bu_feature (snapshot_date, is_cross_bu_active_l1m);
"""

# Bảng mới phải nằm trong tầm đọc của agent, giống hai bảng feature kia.
# ALTER DEFAULT PRIVILEGES ở schema `feature` đã cấp SELECT cho bảng tương lai, nhưng
# chỉ với bảng do CHÍNH owner của migration tạo — GRANT tường minh cho chắc.
_GRANT = "GRANT SELECT ON feature.customer_cross_bu_feature TO feature_agent_reader"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Cross-BU feature table requires PostgreSQL.")
    op.execute(_TABLE)
    op.execute(_GRANT)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.customer_cross_bu_feature")
