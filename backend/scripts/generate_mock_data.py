"""Sinh mock data 3 lớp (CLAUDE.md mục 7) — SEED CỐ ĐỊNH để tái lập.

    Lớp 1: raw events   (customers, gsm_trips, vinfast_orders, loyalty_ledger)
    Lớp 2: derive feature TỪ raw events bằng AGGREGATION thật (không random cột)
    Lớp 3: cắm sẵn "câu chuyện" đã biết để kiểm thử

Vì derive từ cùng một tập sự kiện với các cửa sổ lồng nhau, dữ liệu NHẤT QUÁN nội
tại: l1m ≤ l3m ≤ l6m ≤ l12m, và ratio khớp đúng thành phần. Sinh từng cột random
độc lập sẽ mâu thuẫn (l1m > l3m, ratio lệch) và làm đánh giá vô nghĩa.

Chạy (từ thư mục backend/):
    python -m scripts.generate_mock_data

Engine-agnostic: seed qua SQLAlchemy theo DATABASE_URL — Postgres (mặc định)
hoặc SQLite. Khi SQLAlchemy chưa cài và URL là SQLite, fallback sqlite3 stdlib
để vẫn chạy được offline.
"""
from __future__ import annotations

import os
import random
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.semantic.feature_spec import PNLS, WINDOWS, all_features

# ------------------------- Tham số tái lập -------------------------
SEED = 42
N_CUSTOMERS = 500
REF_DATE = date(2026, 7, 1)          # "hôm nay" cố định để cửa sổ tất định
HISTORY_DAYS = 450                   # ~15 tháng, đủ lấp cửa sổ l12m
WINDOW_DAYS = {"l1m": 30, "l3m": 90, "l6m": 180, "l12m": 365}

GSM_SERVICES = ["taxi", "bike", "express", "food"]
VF_ITEMS = ["accessory", "vehicle", "work_order"]

rng = random.Random(SEED)


# ------------------------- Tiện ích -------------------------
def _sqlite_path_from_url(url: str) -> str:
    """Lấy đường dẫn file từ DATABASE_URL kiểu sqlite:///./data/xxx.db."""
    # sqlite:///relative  ->  relative ; sqlite:////abs -> /abs
    return url.split("///", 1)[1]


def _rand_ts(days_back_max: int, recent_bias: float = 0.0) -> date:
    """Ngày ngẫu nhiên trong quá khứ. recent_bias>0 ưu tiên gần REF_DATE hơn."""
    u = rng.random()
    if recent_bias:
        u = u ** (1.0 + recent_bias)  # kéo về 0 (gần REF_DATE)
    days = int(u * days_back_max)
    return REF_DATE - timedelta(days=days)


# ------------------------- Lớp 1: raw events -------------------------
def gen_customers() -> list[dict]:
    """Gán segment cắm sẵn câu chuyện (lớp 3)."""
    customers = []
    for i in range(1, N_CUSTOMERS + 1):
        r = rng.random()
        if r < 0.40:
            segment = "no_vinfast"        # null thật: chưa từng mua VinFast
        elif r < 0.46:
            segment = "shifter"           # dịch chuyển GSM -> VinFast (burn) trong l1m
        elif r < 0.50:
            segment = "spiker"            # tăng vọt GMV tháng gần nhất
        elif r < 0.70:
            segment = "vinfast_buyer"
        elif r < 0.90:
            segment = "gsm_heavy"
        else:
            segment = "low_activity"
        customers.append({
            "customer_id": i,
            "customer_name": f"Khách hàng {i}",   # cột NHẠY CẢM — guard sẽ chặn
            "phone": f"09{rng.randint(10**7, 10**8 - 1)}",
            "email": f"user{i}@example.com",
            "segment": segment,
            "joined_at": (REF_DATE - timedelta(days=rng.randint(200, 1200))).isoformat(),
        })
    return customers


def gen_gsm_trips(customers: list[dict]) -> list[dict]:
    trips = []
    tid = 0
    for c in customers:
        seg = c["segment"]
        base = {"gsm_heavy": 120, "shifter": 60, "spiker": 70,
                "vinfast_buyer": 40, "no_vinfast": 45, "low_activity": 10}[seg]
        n = max(0, int(rng.gauss(base, base * 0.3)))
        for _ in range(n):
            tid += 1
            svc = rng.choice(GSM_SERVICES)
            price = round(rng.uniform(30_000, 400_000), -3)
            discount = round(price * rng.uniform(0, 0.25), -3)
            dist = round(rng.uniform(1.5, 25.0), 1)
            status = "completed" if rng.random() > 0.08 else "cancelled"
            ts = _rand_ts(HISTORY_DAYS)
            trips.append({
                "id": tid, "customer_id": c["customer_id"], "service_type": svc,
                "original_price": price, "discount": discount, "distance_km": dist,
                "status": status, "ts": ts.isoformat(),
            })
    return trips


def gen_vinfast_orders(customers: list[dict]) -> list[dict]:
    orders = []
    oid = 0
    for c in customers:
        seg = c["segment"]
        if seg == "no_vinfast":
            continue  # null thật — không có đơn VinFast
        base = {"vinfast_buyer": 8, "shifter": 5, "spiker": 6,
                "gsm_heavy": 2, "low_activity": 1}.get(seg, 2)
        n = max(0, int(rng.gauss(base, base * 0.4)))
        for _ in range(n):
            oid += 1
            item = rng.choices(VF_ITEMS, weights=[6, 1, 3])[0]
            if item == "vehicle":
                price = round(rng.uniform(400_000_000, 1_500_000_000), -5)
            elif item == "work_order":
                price = round(rng.uniform(500_000, 8_000_000), -4)
            else:
                price = round(rng.uniform(200_000, 5_000_000), -4)
            discount = round(price * rng.uniform(0, 0.1), -3)
            status = "completed" if rng.random() > 0.05 else "cancelled"
            # spiker: dồn đơn vào tháng gần nhất
            recent_bias = 6.0 if seg in ("spiker", "shifter") else 0.0
            ts = _rand_ts(HISTORY_DAYS, recent_bias)
            orders.append({
                "id": oid, "customer_id": c["customer_id"], "item_type": item,
                "original_price": price, "discount": discount, "status": status,
                "processing_hours": round(rng.uniform(0.5, 72.0), 1),
                "ts": ts.isoformat(),
            })
    return orders


def gen_loyalty_ledger(customers: list[dict]) -> list[dict]:
    """Sổ điểm — CẦU NỐI liên PnL. Điểm earn ở GSM và burn ở VinFast cùng một khách."""
    ledger = []
    lid = 0
    for c in customers:
        seg = c["segment"]
        cid = c["customer_id"]

        def add(pnl, direction, n, pts_lo, pts_hi, recent_bias=0.0):
            nonlocal lid
            for _ in range(n):
                lid += 1
                ledger.append({
                    "id": lid, "customer_id": cid, "pnl": pnl, "direction": direction,
                    "points": int(rng.uniform(pts_lo, pts_hi)),
                    "status": "completed" if rng.random() > 0.05 else "pending",
                    "ts": _rand_ts(HISTORY_DAYS, recent_bias).isoformat(),
                })

        # Earn: chủ yếu ở GSM, và VinFast nếu có mua.
        add("gsm", "earn", max(0, int(rng.gauss(30, 10))), 50, 500)
        if seg != "no_vinfast":
            add("vinfast", "earn", max(0, int(rng.gauss(6, 3))), 200, 2000)
        # Earn rải rác ở vài PnL khác.
        for pnl in rng.sample([p for p in PNLS if p not in ("gsm", "vinfast")], k=rng.randint(1, 3)):
            add(pnl, "earn", rng.randint(1, 8), 50, 800)

        # Burn: ở vài PnL.
        burn_pnls = rng.sample(PNLS, k=rng.randint(1, 3))
        for pnl in burn_pnls:
            add(pnl, "burn", rng.randint(1, 6), 100, 1500)

        # Lớp 3 — câu chuyện dịch chuyển: shifter tăng mạnh BURN ở VinFast trong l1m,
        # đồng thời giảm burn GSM (ít burn gsm gần đây).
        if seg == "shifter":
            add("vinfast", "burn", rng.randint(6, 12), 800, 3000, recent_bias=8.0)

        # Lớp 3 — spike: spiker tăng vọt EARN ở GSM trong tháng gần nhất.
        if seg == "spiker":
            add("gsm", "earn", rng.randint(15, 30), 300, 1200, recent_bias=8.0)
    return ledger


# ------------------------- Lớp 2: derive features -------------------------
def _in_window(ev_iso: str, window: str) -> bool:
    ev = date.fromisoformat(ev_iso)
    return ev >= REF_DATE - timedelta(days=WINDOW_DAYS[window])


def build_customer_aggregates(customers, trips, orders, ledger) -> dict:
    """Tổng hợp trước mọi số liệu cửa sổ cho từng khách (nhất quán vì lồng nhau)."""
    agg: dict[int, dict] = {}
    for c in customers:
        agg[c["customer_id"]] = {
            "txn": {"gsm_trips": {}, "vinfast_orders": {}},
            "loy": {},       # (pnl,direction) -> window -> {"txn":.., "pts":..}
            "primary": {},   # (direction, window) -> pnl|None
        }

    def _txn_accumulate(rows, source, price_field_ok):
        for r in rows:
            if r["status"] != "completed":
                continue
            a = agg[r["customer_id"]]["txn"][source]
            for w in WINDOWS:
                if not _in_window(r["ts"], w):
                    continue
                bucket = a.setdefault(w, {"txn": 0, "gmv": 0.0, "discount": 0.0, "distance_km": 0.0})
                bucket["txn"] += 1
                bucket["gmv"] += r["original_price"]
                bucket["discount"] += r["discount"]
                if price_field_ok:
                    bucket["distance_km"] += r.get("distance_km", 0.0)

    _txn_accumulate(trips, "gsm_trips", True)
    _txn_accumulate(orders, "vinfast_orders", False)

    # Loyalty theo (pnl, direction, window).
    pts_by = {}  # (cid, direction, window) -> {pnl: pts} để tính primary
    for r in ledger:
        if r["status"] != "completed":
            continue
        key = (r["pnl"], r["direction"])
        cust = agg[r["customer_id"]]
        for w in WINDOWS:
            if not _in_window(r["ts"], w):
                continue
            b = cust["loy"].setdefault(key, {}).setdefault(w, {"txn": 0, "pts": 0})
            b["txn"] += 1
            b["pts"] += r["points"]
            pk = (r["customer_id"], r["direction"], w)
            pts_by.setdefault(pk, {}).setdefault(r["pnl"], 0)
            pts_by[pk][r["pnl"]] += r["points"]

    # primary_{earn,burn}_pnl chỉ ở l6m/l12m (ràng buộc mục 2).
    for (cid, direction, w), pnl_pts in pts_by.items():
        if w not in ("l6m", "l12m"):
            continue
        best = max(pnl_pts.items(), key=lambda kv: kv[1])[0] if pnl_pts else None
        agg[cid]["primary"][(direction, w)] = best
    return agg


def feature_value(feat, cust_agg):
    c = feat.components
    kind = c["kind"]
    if kind == "txn_base":
        b = cust_agg["txn"][c["source"]].get(c["window"])
        if not b:
            return 0.0
        return float(b[c["metric"]])
    if kind == "ratio":
        src = cust_agg["txn"][c["source"]]
        num = src.get(c["num_window"], {}).get(c["metric"], 0.0)
        den = src.get(c["den_window"], {}).get(c["metric"], 0.0)
        return round(num / den, 4) if den else None  # ratio tính sẵn; None nếu mẫu=0
    if kind == "loyalty":
        b = cust_agg["loy"].get((c["pnl"], c["direction"]), {}).get(c["window"])
        if not b:
            return 0.0
        return float(b[c["metric"]])
    if kind == "loyalty_primary":
        return cust_agg["primary"].get((c["direction"], c["window"]))  # text|None
    return None


# ------------------------- Ghi DB (engine-agnostic) -------------------------
# Đường SQLAlchemy (Postgres/SQLite) KHÔNG phát DDL — schema do Alembic quản
# (backend/migrations/). _DDL dưới đây CHỈ dùng cho fallback sqlite3 stdlib
# khi máy chưa cài dependencies (không có alembic để chạy).
def _col_type(feat) -> str:
    # TEXT / DOUBLE PRECISION hợp lệ trên cả Postgres lẫn SQLite.
    return "TEXT" if feat.dtype == "categorical" else "DOUBLE PRECISION"


_DDL = [
    "DROP TABLE IF EXISTS features",
    "DROP TABLE IF EXISTS loyalty_ledger",
    "DROP TABLE IF EXISTS vinfast_orders",
    "DROP TABLE IF EXISTS gsm_trips",
    "DROP TABLE IF EXISTS customers",
    """CREATE TABLE customers(
        customer_id INTEGER PRIMARY KEY, customer_name TEXT, phone TEXT, email TEXT,
        segment TEXT, joined_at TEXT)""",
    """CREATE TABLE gsm_trips(
        id INTEGER PRIMARY KEY, customer_id INTEGER, service_type TEXT,
        original_price DOUBLE PRECISION, discount DOUBLE PRECISION,
        distance_km DOUBLE PRECISION, status TEXT, ts TEXT)""",
    """CREATE TABLE vinfast_orders(
        id INTEGER PRIMARY KEY, customer_id INTEGER, item_type TEXT,
        original_price DOUBLE PRECISION, discount DOUBLE PRECISION,
        status TEXT, processing_hours DOUBLE PRECISION, ts TEXT)""",
    """CREATE TABLE loyalty_ledger(
        id INTEGER PRIMARY KEY, customer_id INTEGER, pnl TEXT, direction TEXT,
        points INTEGER, status TEXT, ts TEXT)""",
]

_INSERTS = {
    "customers": "INSERT INTO customers VALUES(:customer_id,:customer_name,:phone,:email,:segment,:joined_at)",
    "gsm_trips": "INSERT INTO gsm_trips VALUES(:id,:customer_id,:service_type,:original_price,:discount,:distance_km,:status,:ts)",
    "vinfast_orders": "INSERT INTO vinfast_orders VALUES(:id,:customer_id,:item_type,:original_price,:discount,:status,:processing_hours,:ts)",
    "loyalty_ledger": "INSERT INTO loyalty_ledger VALUES(:id,:customer_id,:pnl,:direction,:points,:status,:ts)",
}


def _feature_rows(customers, agg, features) -> list[dict]:
    rows = []
    for c in customers:
        cid = c["customer_id"]
        row = {"customer_id": cid}
        for i, f in enumerate(features):
            row[f"v{i}"] = feature_value(f, agg[cid])
        rows.append(row)
    return rows


def _features_ddl(features) -> str:
    cols_ddl = ", ".join(f'"{f.name}" {_col_type(f)}' for f in features)
    return f"CREATE TABLE features(customer_id INTEGER PRIMARY KEY, {cols_ddl})"


def _features_insert(features) -> str:
    quoted = ", ".join(f'"{f.name}"' for f in features)
    binds = ", ".join(f":v{i}" for i in range(len(features)))
    return f"INSERT INTO features(customer_id, {quoted}) VALUES(:customer_id, {binds})"


def write_via_sqlalchemy(url: str, customers, trips, orders, ledger, agg, features) -> None:
    """Postgres hoặc SQLite qua SQLAlchemy — schema do Alembic quản.

    KHÔNG phát DDL ở đây: chạy `alembic upgrade head` (từ backend/) trước.
    Seeder chỉ xóa dữ liệu cũ rồi insert — idempotent, chạy lại được.
    """
    from sqlalchemy import create_engine, inspect, text

    if url.startswith("sqlite"):
        path = _sqlite_path_from_url(url)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    engine = create_engine(url, future=True)

    expected = {"customers", "gsm_trips", "vinfast_orders", "loyalty_ledger", "features"}
    missing = expected - set(inspect(engine).get_table_names())
    if missing:
        engine.dispose()
        raise SystemExit(
            f"Thiếu bảng: {sorted(missing)}.\n"
            "Schema do Alembic quản — chạy trước:  cd backend && alembic upgrade head"
        )

    with engine.begin() as conn:
        # Xóa theo thứ tự con → cha (FK an toàn).
        for table in ("features", "loyalty_ledger", "vinfast_orders", "gsm_trips", "customers"):
            conn.execute(text(f"DELETE FROM {table}"))

        conn.execute(text(_INSERTS["customers"]), customers)
        conn.execute(text(_INSERTS["gsm_trips"]), trips)
        conn.execute(text(_INSERTS["vinfast_orders"]), orders)
        conn.execute(text(_INSERTS["loyalty_ledger"]), ledger)
        conn.execute(text(_features_insert(features)), _feature_rows(customers, agg, features))
    engine.dispose()


def write_sqlite_stdlib(path: str, customers, trips, orders, ledger, agg, features) -> None:
    """Fallback offline: sqlite3 stdlib khi SQLAlchemy chưa cài."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    cur = con.cursor()
    for ddl in _DDL:
        cur.execute(ddl)
    cur.execute(_features_ddl(features))
    cur.executemany(_INSERTS["customers"], customers)
    cur.executemany(_INSERTS["gsm_trips"], trips)
    cur.executemany(_INSERTS["vinfast_orders"], orders)
    cur.executemany(_INSERTS["loyalty_ledger"], ledger)
    cur.executemany(_features_insert(features), _feature_rows(customers, agg, features))
    con.commit()
    con.close()


def main() -> None:
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/feature_store",
    )

    customers = gen_customers()
    trips = gen_gsm_trips(customers)
    orders = gen_vinfast_orders(customers)
    ledger = gen_loyalty_ledger(customers)
    agg = build_customer_aggregates(customers, trips, orders, ledger)
    features = all_features()

    try:
        write_via_sqlalchemy(db_url, customers, trips, orders, ledger, agg, features)
        target = db_url
    except ModuleNotFoundError:
        if not db_url.startswith("sqlite"):
            raise SystemExit(
                "Chưa cài SQLAlchemy/psycopg — không seed được Postgres.\n"
                "Chạy: pip install -r requirements.txt, hoặc tạm đặt "
                "DATABASE_URL=sqlite:///./data/feature_store.db"
            )
        path = _sqlite_path_from_url(db_url)
        write_sqlite_stdlib(path, customers, trips, orders, ledger, agg, features)
        target = path

    print(f"✓ Mock data → {target}")
    print(f"  customers={len(customers)} gsm_trips={len(trips)} "
          f"vinfast_orders={len(orders)} loyalty_ledger={len(ledger)}")
    print(f"  features table: {len(features)} cột (khớp semantic layer)")


if __name__ == "__main__":
    main()
