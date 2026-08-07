"""So sánh DỮ LIỆU trong feature.* với một bản chụp đã lưu ở schema `parity`.

Cổng chất lượng của việc chuyển tầng transform từ Python sang dbt: chụp lại kết
quả của đường Python hiện tại, sau đó bắt đường dbt tái tạo y hệt. Lệch một dòng
là port sai, không phải "sai số chấp nhận được".

`feature_build_at` bị loại khỏi so sánh — nó là thời điểm chạy, luôn khác.
Cấu trúc bảng (cột, constraint, quyền) do scripts/contract_check.py lo.

Cách chạy (từ thư mục backend/):
    python -m scripts.parity_check --snapshot   # chụp baseline (đường Python)
    python -m scripts.parity_check --verify     # so bản hiện tại với baseline
    python -m scripts.parity_check --verify --source dbt_work   # so candidate khi chưa publish
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db import get_engine

GOLD_TABLES = ("gsm_transaction", "vinfast_transaction", "customer_cross_bu_feature")
SNAPSHOT_SCHEMA = "parity"
# Thời điểm chạy pipeline, không phải dữ liệu nghiệp vụ.
IGNORE_COLUMNS = {"feature_build_at"}
SAMPLE_ROWS = 5

# Ngoại lệ DUY NHẤT được tha, và chỉ khi thoả cả ba điều kiện dưới đây.
#
# Cột tỷ lệ `{stem}_{A}_vs_{B}` = A/B làm tròn 4 chữ số. Bản Python chia bằng float64 rồi
# round() theo half-to-even, nên khi thương chính xác rơi ĐÚNG điểm hoà mà điểm hoà đó
# không biểu diễn được trong nhị phân, kết quả phụ thuộc hướng sai số của float64 —
# thông tin mà Postgres không có cách nào lấy lại (float8::numeric trả biểu diễn ngắn
# nhất, mất luôn sai số). Xem docs/eval/parity_buoc5_lech.md.
#
# Đo được: 2 ô trên ~2 triệu giá trị. Tha là quyết định có chủ đích, KHÔNG phải nới lỏng:
# chênh lệch phải đúng 1 đơn vị ở chữ số thứ 4, trên cột tỷ lệ, và số ô phải nằm trong
# trần. Ô thứ ba, hay bất kỳ chênh lệch nào khác, đều làm cổng đỏ.
RATIO_MARKER = "_vs_"
RATIO_EPSILON = Decimal("0.0001")
RATIO_MAX_CELLS = 2


def _columns(conn, schema: str, table: str) -> list[str]:
    rows = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"
        ),
        {"s": schema, "t": table},
    ).scalars().all()
    return [c for c in rows if c not in IGNORE_COLUMNS]


def _col_list(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


def _target_types(conn, table: str) -> dict[str, str]:
    """Kiểu đã khai của từng cột trong feature.<table>."""
    rows = conn.execute(
        text(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod) "
            "FROM pg_attribute a "
            "WHERE a.attrelid = ('feature.' || :t)::regclass "
            "  AND a.attnum > 0 AND NOT a.attisdropped"
        ),
        {"t": table},
    ).all()
    return {name: typ for name, typ in rows}


def _cast_list(cols: list[str], types: dict[str, str]) -> str:
    """Ép nguồn về ĐÚNG kiểu của cột đích trước khi so.

    Không phải nới lỏng — đây mới là phép so đúng. `INSERT INTO feature.x SELECT ...`
    ép kiểu theo cột đích, nên giá trị thực sự được lưu là giá trị SAU khi ép. So thô
    sẽ báo lệch ở những chỗ mà bảng nháp giữ nhiều chữ số hơn cột đích cho phép:
    numeric(20,4) biến 2346.9999999833333333 thành 2347.0000, và chênh lệch đó không
    bao giờ tồn tại trong feature.*.
    """
    return ", ".join(f'"{c}"::{types[c]}' if c in types else f'"{c}"' for c in cols)


def _report_cells(conn, table: str, cols: list[str], source_schema: str) -> bool:
    """Khoanh lệch xuống từng cột, quyết định tha hay đỏ. Trả True nếu chấp nhận được."""
    types = _target_types(conn, table)
    key = ("customer_id", "snapshot_date")
    data = [c for c in cols if c not in key]
    sel = ", ".join(
        f'count(*) filter (where a."{c}"::{types.get(c, "text")} '
        f'is distinct from b."{c}") as "{c}"'
        for c in data
    )
    row = conn.execute(
        text(f"SELECT {sel} FROM {source_schema}.{table} a "
             f"JOIN {SNAPSHOT_SCHEMA}.{table} b USING (customer_id, snapshot_date)")
    ).one()
    lech = [(c, v) for c, v in zip(data, row) if v]

    that_bai = [c for c, _ in lech if RATIO_MARKER not in c]
    if that_bai:
        print(f"  LỆCH {source_schema}.{table:34} {len(that_bai)} cột KHÔNG phải tỷ lệ")
        for c, v in lech:
            if RATIO_MARKER not in c:
                print(f"         {v:>5} ô  {c}")
        return False

    # Chỉ còn cột tỷ lệ: kiểm từng ô, chỉ tha nếu lệch đúng 1 đơn vị chữ số thứ 4.
    tong, qua_lon = 0, []
    for c, _ in lech:
        for cid, snap, av, bv in conn.execute(
            text(f'SELECT customer_id, snapshot_date, a."{c}"::{types[c]}, b."{c}" '
                 f"FROM {source_schema}.{table} a "
                 f"JOIN {SNAPSHOT_SCHEMA}.{table} b USING (customer_id, snapshot_date) "
                 f'WHERE a."{c}"::{types[c]} IS DISTINCT FROM b."{c}"')
        ).all():
            tong += 1
            if av is None or bv is None or abs(Decimal(av) - Decimal(bv)) != RATIO_EPSILON:
                qua_lon.append((c, cid, snap, av, bv))
            else:
                print(f"         tha  {c}  cid={cid} {snap}  nguồn={av} baseline={bv}")

    if qua_lon:
        print(f"  LỆCH {source_schema}.{table:34} {len(qua_lon)} ô tỷ lệ lệch QUÁ 0.0001")
        for c, cid, snap, av, bv in qua_lon[:SAMPLE_ROWS]:
            print(f"         {c}  cid={cid} {snap}  nguồn={av} baseline={bv}")
        return False
    if tong > RATIO_MAX_CELLS:
        print(f"  LỆCH {source_schema}.{table:34} {tong} ô tỷ lệ, vượt trần "
              f"{RATIO_MAX_CELLS} — có lỗi mới lẫn vào, không chỉ là làm tròn float.")
        return False

    print(f"  OK   {source_schema}.{table:34} 0 dòng lệch "
          f"({tong} ô tỷ lệ được tha, xem docs/eval/parity_buoc5_lech.md)")
    return True


def snapshot() -> int:
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SNAPSHOT_SCHEMA}"))
        for table in GOLD_TABLES:
            cols = _columns(conn, "feature", table)
            if not cols:
                print(f"LỖI: feature.{table} không tồn tại hoặc không có cột.")
                return 1
            conn.execute(text(f"DROP TABLE IF EXISTS {SNAPSHOT_SCHEMA}.{table}"))
            conn.execute(
                text(
                    f"CREATE TABLE {SNAPSHOT_SCHEMA}.{table} AS "
                    f"SELECT {_col_list(cols)} FROM feature.{table}"
                )
            )
            n = conn.execute(text(f"SELECT count(*) FROM {SNAPSHOT_SCHEMA}.{table}")).scalar_one()
            print(f"  chụp {SNAPSHOT_SCHEMA}.{table:34} {n:>7} dòng, {len(cols)} cột")
    print(f"Đã chụp baseline vào schema `{SNAPSHOT_SCHEMA}`.")
    return 0


def verify(source_schema: str) -> int:
    engine = get_engine()
    failed = False
    with engine.connect() as conn:
        for table in GOLD_TABLES:
            base_cols = _columns(conn, SNAPSHOT_SCHEMA, table)
            if not base_cols:
                print(f"LỖI: chưa có baseline {SNAPSHOT_SCHEMA}.{table} — chạy --snapshot trước.")
                return 1
            cur_cols = _columns(conn, source_schema, table)

            missing = [c for c in base_cols if c not in cur_cols]
            extra = [c for c in cur_cols if c not in base_cols]
            if extra:
                print(f"LỆCH CỘT {source_schema}.{table}: thừa={extra}")
                failed = True
                continue

            # Cột vắng mặt ở nguồn được bỏ qua CHỈ KHI baseline của nó toàn giá trị
            # DEFAULT — nghĩa là pipeline chưa bao giờ ghi vào đó, và INSERT ... SELECT
            # thiếu cột sẽ tự cho ra đúng giá trị ấy. Cột nào có dữ liệu thật mà nguồn
            # không sinh ra thì vẫn là lệch, không được tha.
            bo_qua = []
            for col in missing:
                default = conn.execute(
                    text(
                        "SELECT column_default FROM information_schema.columns "
                        "WHERE table_schema = 'feature' AND table_name = :t AND column_name = :c"
                    ),
                    {"t": table, "c": col},
                ).scalar()
                khac = conn.execute(
                    text(
                        f'SELECT count(*) FROM {SNAPSHOT_SCHEMA}.{table} '
                        f'WHERE "{col}" IS DISTINCT FROM {default or "NULL"}'
                    )
                ).scalar_one()
                if khac:
                    print(f"  LỆCH {source_schema}.{table}: thiếu cột `{col}` mà baseline "
                          f"có {khac} dòng khác DEFAULT — nguồn phải sinh ra cột này.")
                    failed = True
                else:
                    bo_qua.append(col)
            if bo_qua:
                print(f"  bỏ qua {len(bo_qua)} cột toàn DEFAULT ở {table} "
                      f"(publish sẽ để DB tự điền): {bo_qua[0]}, ...")

            compare_cols = [c for c in base_cols if c in cur_cols]
            base_cols = compare_cols
            cols = _col_list(compare_cols)
            # Nguồn được ép về kiểu của cột đích — xem _cast_list. Baseline đã đúng kiểu
            # sẵn vì nó là bản chụp của chính feature.*.
            src = _cast_list(compare_cols, _target_types(conn, table))
            # EXCEPT hai chiều: bắt cả dòng mất lẫn dòng sai giá trị.
            diff_sql = (
                f"(SELECT {src} FROM {source_schema}.{table} "
                f" EXCEPT SELECT {cols} FROM {SNAPSHOT_SCHEMA}.{table}) "
                f"UNION ALL "
                f"(SELECT {cols} FROM {SNAPSHOT_SCHEMA}.{table} "
                f" EXCEPT SELECT {src} FROM {source_schema}.{table})"
            )
            n = conn.execute(text(f"SELECT count(*) FROM ({diff_sql}) d")).scalar_one()
            if n == 0:
                print(f"  OK   {source_schema}.{table:34} 0 dòng lệch")
                continue

            # Có lệch ⇒ khoanh xuống TỪNG CỘT. Chỉ biết "12 dòng lệch" thì vô dụng khi
            # bảng có 234 cột; biết cột nào là đi thẳng tới nguyên nhân.
            if not _report_cells(conn, table, compare_cols, source_schema):
                failed = True

    if failed:
        print("\nPARITY FAIL — dừng lại và diff, KHÔNG sửa golden set cho khớp.")
        return 1
    print("\nPARITY OK — 0 dòng lệch trên cả 3 bảng.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true", help="chụp feature.* làm baseline")
    g.add_argument("--verify", action="store_true", help="so với baseline đã chụp")
    ap.add_argument(
        "--source",
        default="feature",
        help="schema đem đi so (mặc định `feature`; dùng `dbt_work` để kiểm candidate "
             "trước khi publish)",
    )
    args = ap.parse_args()
    return snapshot() if args.snapshot else verify(args.source)


if __name__ == "__main__":
    raise SystemExit(main())
