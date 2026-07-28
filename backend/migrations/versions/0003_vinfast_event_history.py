"""Sprint 2 — VinFast order status history + vehicle handover (raw event layer).

Sprint 1 chỉ có `raw.vinfast_orders.status` + `updated_at` = trạng thái HIỆN TẠI.
Dùng nó cho snapshot cũ là rò dữ liệu tương lai, nên Sprint 1 chặn hẳn câu hỏi về
chủ xe. Hai bảng ở đây cấp event time thật để dựng lại trạng thái tại thời điểm
bất kỳ (point-in-time), và tách hẳn "đơn hoàn tất" khỏi "đã bàn giao xe".

Hợp đồng ngữ nghĩa: docs/vehicle_owner_semantics.md
Quyết định event time vs ingest time: docs/adr/0002-event-time-not-ingest-time.md

Quyền: schema `raw` đã REVOKE ALL khỏi `feature_agent_reader` và có
ALTER DEFAULT PRIVILEGES REVOKE cho bảng tương lai (db/schema/*.sql mục 7-8),
nên hai bảng này tự động nằm ngoài tầm với của agent. Không thêm GRANT nào.

Chạy bằng tài khoản admin (user runtime `agent` không có CREATE trên schema raw):
    DATABASE_URL=postgresql+psycopg://postgres:...@localhost:5432/feature_store \
        alembic upgrade head

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


# Trạng thái kết thúc: một order chỉ được có ĐÚNG MỘT trong hai.
# Không có CHECK nào ép được ràng buộc liên-dòng này — kiểm ở pipeline + test
# (tests/test_vinfast_event_history.py::test_no_order_has_two_terminal_statuses).
# ponytail: kiểm ở tầng app thay vì trigger DB — thêm trigger nếu warehouse thật vi phạm.
_STATUS_HISTORY = """
CREATE TABLE IF NOT EXISTS raw.vinfast_order_status_history (
    status_history_id   BIGSERIAL PRIMARY KEY,
    order_id            BIGINT NOT NULL
                        REFERENCES raw.vinfast_orders(order_id),

    status              VARCHAR(30) NOT NULL,
    status_at           TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    source_system       VARCHAR(50),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_vinfast_status_history
        UNIQUE (order_id, status, status_at),

    CONSTRAINT chk_vinfast_status_history_status
        CHECK (status IN ('created', 'processing', 'completed', 'cancelled', 'delivered')),

    CONSTRAINT chk_vinfast_status_history_recorded
        CHECK (recorded_at >= status_at)
);

COMMENT ON TABLE raw.vinfast_order_status_history IS
'One row per (order_id, status, status_at). Point-in-time source for order state: use status_at (event time), never recorded_at and never vinfast_orders.updated_at. completed and cancelled are terminal; an order must not have both.';

COMMENT ON COLUMN raw.vinfast_order_status_history.status_at IS
'When the transition happened. This is the only column allowed in point-in-time cutoffs.';

COMMENT ON COLUMN raw.vinfast_order_status_history.recorded_at IS
'When the warehouse learned about it. Kept for pipeline-lag audits; never used to filter snapshots.';

CREATE INDEX IF NOT EXISTS idx_vinfast_status_history_order_time
    ON raw.vinfast_order_status_history (order_id, status_at);

CREATE INDEX IF NOT EXISTS idx_vinfast_status_history_status_time
    ON raw.vinfast_order_status_history (status, status_at);
"""


# Grain: một xe được bàn giao theo một đơn -> (order_id, vehicle_id).
# customer_id lưu lại (không join qua order) vì bàn giao có thể cho người khác
# với đơn mua hộ; Sprint 2 không mô hình hóa sang tên, nhưng cột phải sẵn.
_HANDOVER = """
CREATE TABLE IF NOT EXISTS raw.vinfast_vehicle_handover (
    handover_id         BIGSERIAL PRIMARY KEY,
    order_id            BIGINT NOT NULL
                        REFERENCES raw.vinfast_orders(order_id),
    customer_id         BIGINT NOT NULL
                        REFERENCES raw.customers(customer_id),
    vehicle_id          VARCHAR(50) NOT NULL,

    handover_status     VARCHAR(20) NOT NULL,
    scheduled_at        TIMESTAMPTZ,
    handed_over_at      TIMESTAMPTZ,
    reversed_at         TIMESTAMPTZ,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    source_system       VARCHAR(50),
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_vinfast_handover_order_vehicle
        UNIQUE (order_id, vehicle_id),

    CONSTRAINT chk_vinfast_handover_status
        CHECK (handover_status IN ('scheduled', 'completed', 'reversed')),

    -- Bàn giao completed BẮT BUỘC có thời điểm bàn giao: thiếu nó thì không thể
    -- xác định owner tại một snapshot, tức là dòng dữ liệu vô dụng và nguy hiểm.
    CONSTRAINT chk_vinfast_handover_completed_needs_time
        CHECK (handover_status <> 'completed' OR handed_over_at IS NOT NULL),

    -- Đảo bàn giao (trả xe/đổi xe) phải có mốc thời gian để biết mất owner từ lúc nào.
    CONSTRAINT chk_vinfast_handover_reversed_needs_time
        CHECK (
            handover_status <> 'reversed'
            OR (handed_over_at IS NOT NULL AND reversed_at IS NOT NULL)
        ),

    CONSTRAINT chk_vinfast_handover_reversed_after_handover
        CHECK (reversed_at IS NULL OR reversed_at >= handed_over_at)
);

COMMENT ON TABLE raw.vinfast_vehicle_handover IS
'One row per (order_id, vehicle_id). The ONLY source of vehicle ownership. Owner at snapshot D = handover_status completed AND handed_over_at <= D AND (reversed_at IS NULL OR reversed_at > D). Ownership must never be inferred from vinfast_orders.status.';

COMMENT ON COLUMN raw.vinfast_vehicle_handover.reversed_at IS
'Vehicle returned or swapped. Not split by reason in Sprint 2: both drop ownership of this vehicle_id.';

CREATE INDEX IF NOT EXISTS idx_vinfast_handover_customer_time
    ON raw.vinfast_vehicle_handover (customer_id, handed_over_at);

CREATE INDEX IF NOT EXISTS idx_vinfast_handover_order
    ON raw.vinfast_vehicle_handover (order_id);
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("VinFast event history requires PostgreSQL.")
    op.execute(_STATUS_HISTORY)
    op.execute(_HANDOVER)


def downgrade() -> None:
    # An toàn để drop: hai bảng này do Sprint 2 tạo, chưa có nguồn dữ liệu nào
    # ngoài mock generator (khác 0002 — nơi cột có thể đã chứa dữ liệu thật).
    op.execute("DROP TABLE IF EXISTS raw.vinfast_vehicle_handover")
    op.execute("DROP TABLE IF EXISTS raw.vinfast_order_status_history")
