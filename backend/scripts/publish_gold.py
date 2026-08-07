"""Ghi bảng candidate của dbt (dbt_work.*) sang bảng gold (feature.*).

Vì sao là script riêng chứ không phải một model dbt ghi thẳng: `delete+insert` của dbt
tạo relation tạm `__dbt_tmp` NGAY TRONG schema đích, nên nó bắt buộc phải có quyền CREATE
trên `feature` — mâu thuẫn với least-privilege, và một lần `--full-refresh` sơ ý là mất
constraint, comment lẫn GRANT do Alembic tạo. Tách ra thì dbt toàn quyền trên schema của
riêng nó (silver, dbt_work) và chỉ có DML trên feature.*. Xem ADR 0004.

Chạy bằng role `dbt_transformer`, KHÔNG phải superuser của app — đó là chỗ ranh giới
quyền thực sự có hiệu lực. Migration 0015 cố ý không cấp CREATE trên schema `feature`.

Cả ba bảng nằm trong MỘT transaction: hoặc gold mới nguyên vẹn, hoặc gold cũ nguyên vẹn.
Không có trạng thái nửa vời để agent đọc phải.

Cách chạy (từ thư mục backend/):
    python -m scripts.publish_gold --dry-run   # chỉ báo cáo, không ghi
    python -m scripts.publish_gold
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

from scripts.run_dbt import build_env

SOURCE_SCHEMA = "dbt_work"
TARGET_SCHEMA = "feature"
TABLES = ("gsm_transaction", "vinfast_transaction", "customer_cross_bu_feature")


def _engine():
    """Engine chạy bằng dbt_transformer, suy từ cùng DATABASE_URL với app."""
    env = build_env()
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username=env["DBT_USER"], password=env["DBT_PASSWORD"],
            host=env["DBT_HOST"], port=int(env["DBT_PORT"]), database=env["DBT_DBNAME"],
        ),
        future=True,
    )


def _columns(conn, schema: str, table: str) -> list[str]:
    return conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t "
            # Cột GENERATED không được phép nằm trong INSERT.
            "  AND is_generated = 'NEVER' "
            "ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    ).scalars().all()


def _plan(conn) -> list[tuple[str, list[str], int, int, list[str]]]:
    """Dựng kế hoạch và CHẶN TRƯỚC mọi thứ có thể làm hỏng gold."""
    plan = []
    for table in TABLES:
        src = _columns(conn, SOURCE_SCHEMA, table)
        dst = _columns(conn, TARGET_SCHEMA, table)
        if not src:
            raise SystemExit(
                f"DỪNG: {SOURCE_SCHEMA}.{table} không tồn tại. Chạy `run_dbt build` trước."
            )
        thua = [c for c in src if c not in dst]
        if thua:
            raise SystemExit(
                f"DỪNG: {SOURCE_SCHEMA}.{table} có cột không có ở gold: {thua}. "
                "Cột mới phải đi qua migration Alembic trước."
            )

        n_src = conn.execute(text(f"SELECT count(*) FROM {SOURCE_SCHEMA}.{table}")).scalar_one()
        if n_src == 0:
            # Nếu không chặn, một lần dbt lỗi để lại bảng rỗng sẽ XOÁ SẠCH gold mà
            # không báo gì — transaction vẫn commit thành công.
            raise SystemExit(
                f"DỪNG: {SOURCE_SCHEMA}.{table} rỗng. Publish sẽ xoá sạch gold. "
                "Kiểm tra `run_dbt build` có chạy xong không."
            )
        n_dst = conn.execute(text(f"SELECT count(*) FROM {TARGET_SCHEMA}.{table}")).scalar_one()
        # Cột chỉ có ở gold: INSERT bỏ qua, DB tự điền DEFAULT. Đó là 49 cột lõi mà
        # pipeline chưa bao giờ ghi vào (xem docs/dbt_migration_runbook.md bước 5).
        thieu = [c for c in dst if c not in src]
        plan.append((table, src, n_src, n_dst, thieu))
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="chỉ in kế hoạch và kiểm tra an toàn, không ghi")
    args = ap.parse_args()

    engine = _engine()
    with engine.connect() as conn:
        plan = _plan(conn)

    for table, cols, n_src, n_dst, thieu in plan:
        print(f"  {table:28} {n_dst:>6} -> {n_src:>6} dòng | {len(cols)} cột "
              f"{f'(+{len(thieu)} cột để DB tự điền DEFAULT)' if thieu else ''}")

    if args.dry_run:
        print("\n--dry-run: chưa ghi gì.")
        return 0

    with engine.begin() as conn:
        for table, cols, _, _, _ in plan:
            names = ", ".join(f'"{c}"' for c in cols)
            conn.execute(text(f"DELETE FROM {TARGET_SCHEMA}.{table}"))
            conn.execute(
                text(f"INSERT INTO {TARGET_SCHEMA}.{table} ({names}) "
                     f"SELECT {names} FROM {SOURCE_SCHEMA}.{table}")
            )
    print("\nĐã publish trong MỘT transaction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
