"""Schema khởi tạo Sprint 1 — áp file SQL canonical trong db/schema/.

Nguồn sự thật là `backend/db/schema/sprint1_feature_store_schema_postgresql.sql`
(5 schema: raw / feature / metadata / agent / eval; grain customer_id +
snapshot_date; catalog + synonyms trong DB; query/validation log; bảng eval).

Migration này CHỈ chạy trên PostgreSQL (TIMESTAMPTZ, JSONB, generated columns,
schema, role) — không có đường SQLite. Dev dùng docker Postgres 16.

Lưu ý: mục 7–8 của file SQL (CREATE ROLE / GRANT / REVOKE) cần tài khoản có
quyền CREATEROLE — user `postgres` mặc định trong docker là superuser nên ổn.

Revision ID: 0001
Revises:
Create Date: 2026-07-23
"""
from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# backend/migrations/versions/0001_...py -> parents[2] = backend/
_SQL_PATH = (
    Path(__file__).resolve().parents[2]
    / "db"
    / "schema"
    / "sprint1_feature_store_schema_postgresql.sql"
)


def _load_sql() -> str:
    sql = _SQL_PATH.read_text(encoding="utf-8")
    # Alembic tự quản lý transaction — bỏ BEGIN;/COMMIT; đứng riêng một dòng.
    sql = re.sub(r"(?im)^\s*(BEGIN|COMMIT)\s*;\s*$", "", sql)
    return sql


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError(
            "Schema Sprint 1 chỉ hỗ trợ PostgreSQL "
            f"(đang kết nối: {bind.dialect.name}). Xem README để dựng Postgres."
        )
    # psycopg3 không tham số dùng simple query protocol -> cho phép nhiều câu
    # lệnh (kể cả DO $$ ... $$) trong một lần execute.
    op.execute(_load_sql())


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS metadata.queryable_feature_view")
    for schema in ("eval", "agent", "metadata", "feature", "raw"):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    op.execute("DROP ROLE IF EXISTS feature_agent_reader")
    op.execute("DROP ROLE IF EXISTS feature_agent_logger")
