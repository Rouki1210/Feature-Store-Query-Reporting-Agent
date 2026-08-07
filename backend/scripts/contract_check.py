"""So sánh CẤU TRÚC của feature.* với contract đã chốt (backend/db/gold_contract.json).

Parity dữ liệu không bắt được contract drift: một cột đổi kiểu, mất một CHECK,
mất một GRANT — `EXCEPT` vẫn trả 0 dòng lệch trong khi agent đã hỏng. Alembic sở
hữu DDL của feature.*; script này là bằng chứng dbt/publish không đụng vào đó.

Chụp gồm: cột (tên, thứ tự, kiểu, độ dài/precision, nullable, default),
constraint, index, ACL bảng + schema, comment bảng + cột.

LƯU Ý: file contract gắn với PHIÊN BẢN PostgreSQL, không chỉ với schema. Đổi major
version sẽ báo lệch mà schema không hề đổi:
  * PG 17+ đưa NOT NULL vào pg_constraint như constraint thật; PG 16 thì không.
  * PG 17+ thêm quyền MAINTAIN nên ACL chủ sở hữu là `arwdDxtm` thay vì `arwdDxt`.
Gặp đúng hai kiểu lệch đó và `columns` vẫn khớp thì là artefact phiên bản — chụp lại.
Lệch ở `columns`, `indexes`, comment, hay ở quyền của `dbt_transformer` thì là thật.

Cách chạy (từ thư mục backend/):
    python -m scripts.contract_check --snapshot   # chốt contract, ghi ra JSON (commit file này)
    python -m scripts.contract_check --verify     # so DB hiện tại với contract đã chốt
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from app.db import get_engine

GOLD_TABLES = ("gsm_transaction", "vinfast_transaction", "customer_cross_bu_feature")
CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "gold_contract.json"
)

QUERIES = {
    "columns": """
        SELECT table_name, ordinal_position, column_name, data_type,
               coalesce(character_maximum_length, -1),
               coalesce(numeric_precision, -1), coalesce(numeric_scale, -1),
               is_nullable, coalesce(column_default, ''),
               coalesce(is_generated, ''), coalesce(generation_expression, '')
          FROM information_schema.columns
         WHERE table_schema = 'feature' AND table_name = ANY(:tables)
         ORDER BY table_name, ordinal_position
    """,
    "constraints": """
        SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
          FROM pg_constraint c
         WHERE c.conrelid IN (
                   SELECT oid FROM pg_class
                    WHERE relnamespace = 'feature'::regnamespace AND relname = ANY(:tables)
               )
         ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef
          FROM pg_indexes
         WHERE schemaname = 'feature' AND tablename = ANY(:tables)
         ORDER BY 1, 2
    """,
    # relacl/nspacl thay cho information_schema.table_privileges: chính xác và đủ,
    # không phụ thuộc vai của người đang chạy script.
    "table_acl": """
        SELECT relname, coalesce(array_to_string(relacl, ' | '), '(default)')
          FROM pg_class
         WHERE relnamespace = 'feature'::regnamespace AND relname = ANY(:tables)
         ORDER BY 1
    """,
    "schema_acl": """
        SELECT nspname, coalesce(array_to_string(nspacl, ' | '), '(default)')
          FROM pg_namespace
         WHERE nspname IN ('raw', 'feature', 'metadata', 'agent', 'eval')
         ORDER BY 1
    """,
    "table_comments": """
        SELECT relname, coalesce(obj_description(oid, 'pg_class'), '')
          FROM pg_class
         WHERE relnamespace = 'feature'::regnamespace AND relname = ANY(:tables)
         ORDER BY 1
    """,
    "column_comments": """
        SELECT c.relname, a.attname, coalesce(col_description(c.oid, a.attnum), '')
          FROM pg_class c
          JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
         WHERE c.relnamespace = 'feature'::regnamespace AND c.relname = ANY(:tables)
           AND col_description(c.oid, a.attnum) IS NOT NULL
         ORDER BY 1, 2
    """,
}


def collect() -> dict[str, list[list]]:
    engine = get_engine()
    with engine.connect() as conn:
        params = {"tables": list(GOLD_TABLES)}
        found = conn.execute(
            text(
                "SELECT relname FROM pg_class "
                "WHERE relnamespace = 'feature'::regnamespace AND relname = ANY(:tables)"
            ),
            params,
        ).scalars().all()
        missing = set(GOLD_TABLES) - set(found)
        if missing:
            raise SystemExit(f"LỖI: thiếu bảng trong schema feature: {sorted(missing)}")
        return {
            name: [[str(v) for v in row] for row in conn.execute(text(sql), params).all()]
            for name, sql in QUERIES.items()
        }


def snapshot() -> int:
    data = collect()
    os.makedirs(os.path.dirname(CONTRACT_PATH), exist_ok=True)
    with open(CONTRACT_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.write("\n")
    for name, rows in data.items():
        print(f"  {name:18} {len(rows)} mục")
    print(f"Đã chốt contract -> {CONTRACT_PATH} (commit file này)")
    return 0


def verify() -> int:
    if not os.path.exists(CONTRACT_PATH):
        print(f"LỖI: chưa có {CONTRACT_PATH} — chạy --snapshot trước.")
        return 1
    with open(CONTRACT_PATH, encoding="utf-8") as fh:
        want = json.load(fh)
    got = collect()

    failed = False
    for name in QUERIES:
        w = {tuple(r) for r in want.get(name, [])}
        g = {tuple(r) for r in got[name]}
        if w == g:
            print(f"  OK   {name:18} {len(g)} mục khớp")
            continue
        failed = True
        print(f"  LỆCH {name}")
        for row in sorted(w - g):
            print(f"         MẤT  {' | '.join(row)}")
        for row in sorted(g - w):
            print(f"         THÊM {' | '.join(row)}")

    if failed:
        print("\nCONTRACT FAIL — DDL của feature.* đã bị đổi. Alembic là nơi duy nhất "
              "được phép đổi nó; kiểm tra xem dbt/publish có ghi vượt quyền không.")
        return 1
    print("\nCONTRACT OK — cấu trúc, quyền và comment khớp hoàn toàn.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--snapshot", action="store_true", help="chốt contract hiện tại ra JSON")
    g.add_argument("--verify", action="store_true", help="so DB hiện tại với contract đã chốt")
    args = ap.parse_args()
    return snapshot() if args.snapshot else verify()


if __name__ == "__main__":
    raise SystemExit(main())
