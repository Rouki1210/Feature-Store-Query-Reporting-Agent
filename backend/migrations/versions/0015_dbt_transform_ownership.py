"""Nền cho tầng transform dbt: schema silver/dbt_work, role dbt_transformer, feature_snapshot.

Ranh giới sở hữu (ADR 0004):
  - Alembic sở hữu DDL của raw/feature/metadata/agent/eval. Đây là nơi DUY NHẤT
    được đổi cấu trúc feature.*.
  - dbt sở hữu hoàn toàn silver/ (view) và dbt_work/ (bảng candidate) — hai schema
    của riêng nó, tạo/xoá thoải mái, không đụng gì của Alembic.
  - dbt/publish chỉ có DML trên feature.*. KHÔNG cấp CREATE trên schema feature,
    nên dù model cấu hình sai hay ai đó chạy --full-refresh thì cũng không thể
    DROP/ALTER bảng gold — constraint, comment và GRANT không mất được.

`raw.feature_snapshot` gỡ một coupling ngầm: danh sách ngày snapshot trước đây chỉ
tồn tại như hằng số Python trong scripts/generate_mock_data.py, dbt không có cách
nào biết. Giờ generator ghi xuống đây, dbt đọc lên.

Mật khẩu của dbt_transformer lấy từ biến môi trường DBT_TRANSFORMER_PASSWORD
(CLAUDE.md mục 5: không hardcode credential). Thiếu biến ⇒ migration dừng.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-06
"""
from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

DBT_ROLE = "dbt_transformer"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Tầng transform dbt yêu cầu PostgreSQL.")

    # Cùng thứ tự với migrations/env.py: app.config (đọc .env) trước, env thô sau.
    try:
        from app.config import get_settings

        password = get_settings().dbt_transformer_password
    except Exception:  # noqa: BLE001 — chạy alembic ngoài context app
        password = ""
    password = password or os.getenv("DBT_TRANSFORMER_PASSWORD", "")
    if not password:
        raise RuntimeError(
            "Thiếu DBT_TRANSFORMER_PASSWORD. Đặt trong backend/.env (hoặc export) "
            "rồi chạy lại `alembic upgrade head`. Migration không hardcode credential."
        )

    # ---- 1. Danh sách ngày snapshot (nguồn sự thật dùng chung Python <-> dbt) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.feature_snapshot (
            snapshot_date DATE PRIMARY KEY REFERENCES raw.date_dim(date_id)
        )
    """)
    op.execute("""
        COMMENT ON TABLE raw.feature_snapshot IS
        'Cac ngay snapshot ma feature.* duoc tinh. Generator ghi, dbt doc. '
        'Truoc day chi la hang so Python nen dbt khong thay duoc.'
    """)

    # ---- 2. Hai schema của riêng dbt ----
    op.execute("CREATE SCHEMA IF NOT EXISTS silver")
    op.execute("CREATE SCHEMA IF NOT EXISTS dbt_work")
    op.execute("COMMENT ON SCHEMA silver IS 'dbt so huu. View chuan hoa event + quy tac PIT.'")
    op.execute("COMMENT ON SCHEMA dbt_work IS 'dbt so huu. Bang candidate, duoc test truoc khi publish sang feature.*'")

    # ---- 3. Role transform, least privilege ----
    # Mật khẩu đi qua set_config (bind param) rồi format(%L) — không bao giờ được nối
    # vào chuỗi SQL. Trong DO $$...$$ thì `:pw` chỉ là ký tự thường, không phải tham số.
    op.execute(text("SELECT set_config('dbt.role_password', :pw, false)").bindparams(pw=password))
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{DBT_ROLE}') THEN
                EXECUTE format('ALTER ROLE {DBT_ROLE} LOGIN PASSWORD %L',
                               current_setting('dbt.role_password'));
            ELSE
                EXECUTE format('CREATE ROLE {DBT_ROLE} LOGIN PASSWORD %L',
                               current_setting('dbt.role_password'));
            END IF;
        END $$;
    """)
    op.execute("SELECT set_config('dbt.role_password', '', false)")

    # Đọc raw (nguồn), toàn quyền trên hai schema của mình.
    op.execute(f"GRANT USAGE ON SCHEMA raw TO {DBT_ROLE}")
    op.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA raw TO {DBT_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT SELECT ON TABLES TO {DBT_ROLE}")
    op.execute(f"GRANT ALL ON SCHEMA silver, dbt_work TO {DBT_ROLE}")

    # feature.*: CHỈ DML. Không GRANT CREATE trên schema ⇒ không tạo/xoá/sửa bảng được.
    op.execute(f"GRANT USAGE ON SCHEMA feature TO {DBT_ROLE}")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA feature TO {DBT_ROLE}"
    )

    # ---- 4. Agent tuyệt đối không đọc silver/dbt_work ----
    # Dữ liệu trung gian chưa qua tầng guard; cùng lý do raw bị REVOKE ALL.
    op.execute("REVOKE ALL ON SCHEMA silver, dbt_work FROM feature_agent_reader")

    # ---- 5. Sửa hai comment đã lệch thực tế (doc/database_structure.md sinh từ đây) ----
    # Sprint 2 đã thêm is_vehicle_owner / first_vehicle_handover_date /
    # vehicle_delivered_count_*, nhưng comment vẫn là bản Sprint 1 nói "chưa hỗ trợ
    # ownership" — người port logic sang dbt sẽ bỏ sót nguyên nhóm feature này.
    op.execute("""
        COMMENT ON TABLE feature.vinfast_transaction IS
        'VinFast feature table. One row per customer and snapshot date. '
        'Covers both order/buyer analysis and confirmed vehicle ownership: '
        'is_vehicle_buyer comes from order status history, is_vehicle_owner ONLY from '
        'raw.vinfast_vehicle_handover. Buying is not receiving - never derive ownership '
        'from order status. See docs/vehicle_owner_semantics.md.'
    """)
    # Nó là BẢNG (có PK, FK, CHECK, index), không phải view. Gọi sai làm người đọc
    # tưởng nó tự cập nhật theo hai bảng kia.
    op.execute("""
        COMMENT ON TABLE feature.customer_cross_bu_feature IS
        'Pre-computed cross-BU feature TABLE, one row per customer_id + snapshot_date. '
        'Answer cross-BU questions from this table instead of joining gsm_transaction '
        'with vinfast_transaction. Refreshed by the transform pipeline, not a view. '
        'See docs/adr/0001-cross-bu-precomputed-table.md.'
    """)


def downgrade() -> None:
    op.execute("""
        COMMENT ON TABLE feature.customer_cross_bu_feature IS
        'Pre-computed cross-BU view, one row per customer_id + snapshot_date. '
        'Answer cross-BU questions from this table instead of joining gsm_transaction '
        'with vinfast_transaction.'
    """)
    op.execute("""
        COMMENT ON TABLE feature.vinfast_transaction IS
        'VinFast feature table. One row per customer and snapshot date. '
        'Sprint 1 supports buyer/order analysis only, not confirmed vehicle ownership.'
    """)
    op.execute("DROP SCHEMA IF EXISTS dbt_work CASCADE")
    op.execute("DROP SCHEMA IF EXISTS silver CASCADE")
    op.execute("DROP TABLE IF EXISTS raw.feature_snapshot")
    # Phải thu hồi hết quyền trước khi DROP ROLE.
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA raw, feature FROM {DBT_ROLE}")
    op.execute(f"REVOKE ALL ON SCHEMA raw, feature FROM {DBT_ROLE}")
    op.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA raw REVOKE SELECT ON TABLES FROM {DBT_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {DBT_ROLE}")
