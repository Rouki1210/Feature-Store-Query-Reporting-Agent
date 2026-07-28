"""Task 2.1 — integrity của raw.vinfast_order_status_history + vinfast_vehicle_handover.

Ba tầng kiểm, tầng sau cần quyền cao hơn tầng trước:
  1. Cấu trúc + quyền — đọc catalog `pg_*`, chạy được bằng MỌI user (kể cả user
     runtime `agent`, vốn không có USAGE trên schema raw).
  2. Bất biến dữ liệu — cần SELECT trên raw → skip với user runtime.
  3. Hành vi constraint — cần INSERT trên raw → chỉ admin/CI.

Vì `agent` không được đọc raw (đúng thiết kế), mọi query ở đây tra catalog bằng
**oid** thay vì tên có schema: giải tên `raw.x` cần USAGE, tra oid thì không.

Bất biến "một order chỉ có MỘT trạng thái kết thúc" không CHECK nào ép được
(ràng buộc liên-dòng) nên kiểm bằng query trên dữ liệu — rỗng ở 2.1, có nghĩa sau 2.2.
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import get_engine

HISTORY = "vinfast_order_status_history"
HANDOVER = "vinfast_vehicle_handover"


@pytest.fixture(scope="module")
def db():
    """(conn, {tên bảng: oid}) — skip nếu chưa chạy migration 0003."""
    with get_engine().connect() as conn:
        if conn.dialect.name != "postgresql":
            pytest.skip("Sprint 2 event history chỉ hỗ trợ PostgreSQL.")
        oids = dict(conn.execute(text("""
            SELECT c.relname, c.oid
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'raw' AND c.relname IN (:h, :v)
        """), {"h": HISTORY, "v": HANDOVER}).fetchall())
        if len(oids) != 2:
            pytest.skip("Chưa chạy migration 0003 (cần tài khoản admin).")
        yield conn, oids


def _require_priv(db, table: str, priv: str):
    conn, oids = db
    ok = conn.execute(text("SELECT has_table_privilege(current_user, :oid, :p)"),
                      {"oid": oids[table], "p": priv}).scalar()
    if not ok:
        pytest.skip(f"User runtime không có {priv} trên raw (đúng thiết kế); chạy bằng admin.")
    return conn


# ---------------------------------------------------------------- 1. cấu trúc

def test_tables_exist_with_expected_grain(db):
    """Grain phải là (order_id, status, status_at) và (order_id, vehicle_id)."""
    conn, oids = db
    rows = conn.execute(text("""
        SELECT c.conrelid, array_agg(a.attname ORDER BY a.attname)
        FROM pg_constraint c
        JOIN unnest(c.conkey) k(attnum) ON TRUE
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
        WHERE c.contype = 'u' AND c.conrelid = ANY(:oids)
        GROUP BY c.conrelid, c.conname
    """), {"oids": list(oids.values())}).fetchall()
    grain = {oid: set(cols) for oid, cols in rows}
    assert grain[oids[HISTORY]] == {"order_id", "status", "status_at"}
    assert grain[oids[HANDOVER]] == {"order_id", "vehicle_id"}


def test_handover_constraints_declared(db):
    """Thiếu 3 CHECK này thì owner tại snapshot không xác định được."""
    conn, oids = db
    names = {r[0] for r in conn.execute(text(
        "SELECT conname FROM pg_constraint WHERE conrelid = :oid AND contype = 'c'"
    ), {"oid": oids[HANDOVER]})}
    assert {
        "chk_vinfast_handover_completed_needs_time",
        "chk_vinfast_handover_reversed_needs_time",
        "chk_vinfast_handover_reversed_after_handover",
    } <= names


def test_status_history_uses_event_time_not_ingest_time(db):
    """`recorded_at >= status_at` — ADR 0002: PIT lọc theo status_at."""
    conn, oids = db
    checks = " ".join(r[0] for r in conn.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conrelid = :oid AND contype = 'c'"
    ), {"oid": oids[HISTORY]}))
    assert "recorded_at" in checks and "status_at" in checks


# ---------------------------------------------------------------- 2. quyền

def test_agent_reader_cannot_touch_event_tables(db):
    """Hai bảng nằm trong schema raw ⇒ agent tuyệt đối không chạm được."""
    conn, oids = db
    for table, oid in oids.items():
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not conn.execute(text(
                "SELECT has_table_privilege('feature_agent_reader', :oid, :p)"
            ), {"oid": oid, "p": priv}).scalar(), f"raw.{table} lộ quyền {priv} cho agent"


# ---------------------------------------------------------------- 3. bất biến dữ liệu

def test_no_order_has_two_terminal_statuses(db):
    """`completed` và `cancelled` đều là trạng thái CUỐI — một order chỉ được có một.

    docs/vehicle_owner_semantics.md mục 5. Trả hàng sau khi hoàn tất biểu diễn bằng
    handover `reversed`, không phải bằng cách quay lại `cancelled`.
    """
    conn = _require_priv(db, HISTORY, "SELECT")
    bad = conn.execute(text(f"""
        SELECT order_id FROM raw.{HISTORY}
        WHERE status IN ('completed', 'cancelled')
        GROUP BY order_id HAVING COUNT(DISTINCT status) > 1
        LIMIT 5
    """)).fetchall()
    assert not bad, f"order có 2 trạng thái kết thúc: {bad}"


# ---------------------------------------------------------------- 4. hành vi constraint

@pytest.fixture
def writable(db):
    """Ghi thử rồi rollback — không để lại rác trong raw."""
    conn = _require_priv(db, HANDOVER, "INSERT")
    trans = conn.begin_nested()
    yield conn
    trans.rollback()


def _an_order(conn):
    row = conn.execute(text(
        "SELECT order_id, customer_id FROM raw.vinfast_orders LIMIT 1")).first()
    if row is None:
        pytest.skip("Chưa có mock order để tham chiếu.")
    return {"o": row[0], "c": row[1]}


def test_completed_handover_without_time_is_rejected(writable):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        writable.execute(text(f"""
            INSERT INTO raw.{HANDOVER} (order_id, customer_id, vehicle_id, handover_status)
            VALUES (:o, :c, 'VF-TEST-1', 'completed')
        """), _an_order(writable))


def test_duplicate_vehicle_per_order_is_rejected(writable):
    from sqlalchemy.exc import IntegrityError

    params = _an_order(writable)
    stmt = text(f"""
        INSERT INTO raw.{HANDOVER}
          (order_id, customer_id, vehicle_id, handover_status, handed_over_at)
        VALUES (:o, :c, 'VF-TEST-2', 'completed', CURRENT_TIMESTAMP)
    """)
    writable.execute(stmt, params)
    with pytest.raises(IntegrityError):
        writable.execute(stmt, params)
