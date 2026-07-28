"""Sprint 2 — metadata.join_catalog + mở rộng agent.query_log.

Join catalog là danh sách TRẮNG các cặp bảng được phép ghép, kèm khóa join bắt buộc.
Validator (Task 2.8) so mọi JOIN trong SQL sinh ra với bảng này; không khớp ⇒ reject.
Không có bản YAML song song — hai nguồn cho cùng một sự thật sẽ trôi lệch
(docs/join_policy.md §6).

`agent.query_log` thêm 5 cột để audit được đường đi của Sprint 2: join plan nào đã
dùng, state chuyển thế nào, có phải trả lời một phần không.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


_CATALOG = """
CREATE TABLE IF NOT EXISTS metadata.join_catalog (
    join_id                 SERIAL PRIMARY KEY,
    left_table              TEXT NOT NULL,
    right_table             TEXT NOT NULL,
    join_keys               TEXT[] NOT NULL,
    join_type               TEXT NOT NULL,
    cardinality             TEXT NOT NULL,
    requires_snapshot_key   BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_intents         TEXT[] NOT NULL DEFAULT '{}',
    explanation_vi          TEXT NOT NULL,
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_join_catalog_pair UNIQUE (left_table, right_table),

    CONSTRAINT chk_join_catalog_type
        CHECK (join_type IN ('inner', 'left', 'full')),

    CONSTRAINT chk_join_catalog_cardinality
        CHECK (cardinality IN ('1:1', '1:n', 'n:1')),

    -- Không cho đăng ký join thiếu khóa snapshot khi cờ yêu cầu bật: đây chính là
    -- lỗi nhân dòng mà cả Sprint 2 đang phòng.
    CONSTRAINT chk_join_catalog_snapshot_key
        CHECK (NOT requires_snapshot_key OR 'snapshot_date' = ANY(join_keys)),

    CONSTRAINT chk_join_catalog_has_keys
        CHECK (array_length(join_keys, 1) >= 1)
);

COMMENT ON TABLE metadata.join_catalog IS
'Allow-list of table pairs the agent may join, with the mandatory join keys. Any join not matching an active row here is rejected at validation time.';

GRANT SELECT ON metadata.join_catalog TO feature_agent_reader;
"""

_QUERY_LOG = """
ALTER TABLE agent.query_log
    ADD COLUMN IF NOT EXISTS join_plan JSONB,
    ADD COLUMN IF NOT EXISTS state_transition JSONB,
    ADD COLUMN IF NOT EXISTS visualization_spec JSONB,
    ADD COLUMN IF NOT EXISTS partial_answer BOOLEAN,
    ADD COLUMN IF NOT EXISTS coverage_warning JSONB;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Join catalog requires PostgreSQL.")
    op.execute(_CATALOG)
    op.execute(_QUERY_LOG)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metadata.join_catalog")
    for column in ("join_plan", "state_transition", "visualization_spec",
                   "partial_answer", "coverage_warning"):
        op.execute(f"ALTER TABLE agent.query_log DROP COLUMN IF EXISTS {column}")
