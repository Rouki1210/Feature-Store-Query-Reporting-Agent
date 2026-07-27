"""Generate deterministic Sprint 1 raw data and customer snapshot features."""
from __future__ import annotations

import random
import os
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.db import get_engine
from app.semantic.feature_spec import WINDOW_DAYS, all_features
from scripts.seed_metadata import seed as seed_metadata

RNG = random.Random(20260723)
_snapshot_text = os.getenv("SNAPSHOT_DATE")
try:
    SNAPSHOT = date.fromisoformat(_snapshot_text) if _snapshot_text else date.today()
except ValueError as exc:
    raise ValueError("SNAPSHOT_DATE must use YYYY-MM-DD format") from exc
UTC = timezone.utc
CUSTOMER_COUNT = 600
# 6 snapshot cách ~30 ngày (cũ→mới), mới nhất = SNAPSHOT. Cho time-series /
# window-compare / reporter đêm. ponytail: cách đều 30 ngày thay vì month-end
# lịch để tránh số học tháng — đủ để test dịch chuyển MoM.
SNAPSHOTS = tuple(SNAPSHOT - timedelta(days=30 * k) for k in range(5, -1, -1))
# Sự kiện phải phủ tới l12m của snapshot cũ nhất (SNAPSHOT-150 → cần ~515 ngày).
EVENT_DAYS_BACK = 550


def _timestamp(days_back: int) -> datetime:
    d = SNAPSHOT - timedelta(days=RNG.randint(0, days_back))
    return datetime.combine(d, time(RNG.randint(6, 22), RNG.randint(0, 59)), UTC)


def generate_raw() -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    RNG.seed(20260723)
    customers, trips, orders = [], [], []
    for cid in range(1, CUSTOMER_COUNT + 1):
        inactive = cid % 20 == 0
        vinfast_only = cid % 20 == 3
        created = _timestamp(900)
        customers.append({
            "customer_id": cid, "created_at": created, "updated_at": created,
            "gender": RNG.choice(["male", "female", "other", "unknown"]),
            "birth_date": date(RNG.randint(1970, 2003), RNG.randint(1, 12), RNG.randint(1, 28)),
            "register_channel": RNG.choice(["app", "web", "dealer"]),
            "residence_province": RNG.choice(["Hà Nội", "TP Hồ Chí Minh", "Đà Nẵng"]),
            "is_active": True, "source_system": "mock",
        })
        if not inactive and not vinfast_only:
            for _ in range(RNG.randint(3, 55)):
                start = _timestamp(EVENT_DAYS_BACK)
                duration = RNG.randint(8, 120)
                fare = RNG.randint(25, 600) * 1000
                discount = RNG.choice([0, 0, 0, RNG.randint(5, 80) * 1000])
                status = RNG.choices(
                    ["completed", "cancelled", "created", "in_progress"],
                    weights=[82, 10, 4, 4],
                )[0]
                trips.append({
                    "trip_id": len(trips) + 1, "customer_id": cid,
                    "trip_start_time": start, "trip_end_time": start + timedelta(minutes=duration),
                    "service_type": RNG.choice(["taxi", "bike", "express", "food"]),
                    "distance_km": round(RNG.uniform(1, 45), 2), "duration_min": duration,
                    "total_fare": fare, "discount_amount": min(discount, fare),
                    "paid_amount": max(fare - discount, 0), "payment_method": RNG.choice(["cash", "card", "wallet"]),
                    "status": status, "created_at": start, "updated_at": start + timedelta(minutes=duration),
                })
        # Giữ ~12% khách KHÔNG có đơn VF (genuine null — CLAUDE.md mục 7) để test
        # câu hỏi "chưa mua VinFast"; 88% còn lại nhiều đơn để feature VF hết mỏng.
        if not inactive and cid % 8:
            for _ in range(RNG.randint(2, 14)):
                created_at = _timestamp(EVENT_DAYS_BACK)
                order_type = RNG.choice(["vehicle", "accessories", "work_order", "nvso"])
                list_price = (
                    RNG.randint(4000, 15000) * 100_000 if order_type == "vehicle"
                    else RNG.randint(5, 600) * 10_000
                )
                paid = int(list_price * RNG.uniform(.88, 1.0))
                orders.append({
                    "order_id": len(orders) + 1, "customer_id": cid,
                    "created_at": created_at,
                    "updated_at": min(
                        created_at + timedelta(days=RNG.randint(0, 10)),
                        datetime.combine(SNAPSHOT, time.max, UTC),
                    ),
                    "status": RNG.choices(["completed", "delivered", "cancelled", "processing"], [65, 15, 10, 10])[0],
                    "order_type": order_type, "list_price": list_price, "paid_amount": paid,
                    "battery_kwh": round(RNG.uniform(30, 100), 2) if order_type == "vehicle" else None,
                    "vehicle_model": RNG.choice(["VF 3", "VF 6", "VF 8"]) if order_type == "vehicle" else None,
                    "source_system": "mock",
                })
    dates = []
    for offset in range(0, 731):
        d = SNAPSHOT - timedelta(days=offset)
        iso = d.isocalendar()
        dates.append({
            "date_id": d, "day_of_week": d.isoweekday(), "day_name": d.strftime("%A"),
            "day_of_month": d.day, "week_of_month": (d.day - 1) // 7 + 1,
            "week_of_year": iso.week, "month_number": d.month, "month_name": d.strftime("%B"),
            "quarter_number": (d.month - 1) // 3 + 1, "year_number": d.year,
            "is_weekend": d.isoweekday() >= 6, "is_holiday": False, "holiday_name": None,
        })
    return customers, dates, trips, orders


def _within(ts: datetime, window: str, snapshot: date) -> bool:
    days = WINDOW_DAYS[window]
    return snapshot - timedelta(days=days - 1) <= ts.date() <= snapshot


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if a is not None and b else None


def build_features(
    customers: list[dict], trips: list[dict], orders: list[dict],
    snapshot: date = SNAPSHOT,
) -> tuple[list[dict], list[dict]]:
    trips_by: dict[int, list[dict]] = defaultdict(list)
    orders_by: dict[int, list[dict]] = defaultdict(list)
    for row in trips:
        trips_by[row["customer_id"]].append(row)
    for row in orders:
        orders_by[row["customer_id"]].append(row)
    gsm_rows, vf_rows = [], []
    features = all_features()
    for customer in customers:
        cid = customer["customer_id"]
        # As-of: chỉ sự kiện <= snapshot (feature tính đúng tại từng mốc thời gian).
        tr = [r for r in trips_by[cid] if r["trip_start_time"].date() <= snapshot]
        od = [
            r for r in orders_by[cid]
            if r["created_at"].date() <= snapshot and r["updated_at"].date() <= snapshot
        ]
        gsm: dict[str, Any] = {"customer_id": cid, "snapshot_date": snapshot}
        vf: dict[str, Any] = {"customer_id": cid, "snapshot_date": snapshot}

        def window_rows(rows: list[dict], window: str, ts_key: str) -> list[dict]:
            if "_vs_" in window:
                window = window.split("_vs_", 1)[0]
            return [r for r in rows if window in WINDOW_DAYS and _within(r[ts_key], window, snapshot)]

        def gsm_metric(stem: str, window: str) -> Any:
            rows = window_rows(tr, window, "trip_start_time")
            # Tên feature dùng "canceled" (1 L, theo workbook) nhưng raw status là
            # "cancelled" (2 L, theo CHECK constraint schema) — phải map, nếu không
            # mọi feature canceled_* = 0. "finished" không có trong raw → coi = completed (mock).
            status = "cancelled" if stem.startswith("canceled_") else (
                "completed" if stem.startswith("completed_") else (
                    "completed" if stem.startswith("finished_") else None
                )
            )
            if status:
                rows = [r for r in rows if r["status"] == status]
            if "weekday_" in stem:
                rows = [r for r in rows if r["trip_start_time"].isoweekday() < 6]
            if "time_daytime_" in stem:
                rows = [r for r in rows if 6 <= r["trip_start_time"].hour < 18]
            if "_type_" in stem:
                service = stem.split("_type_", 1)[1].split("_txn_", 1)[0]
                rows = [r for r in rows if r["service_type"] == service]
            if "days_since_first_txn" in stem:
                dates = [r["trip_start_time"].date() for r in tr]
                return (snapshot - min(dates)).days if dates else None
            if "days_since_last_txn" in stem:
                dates = [r["trip_start_time"].date() for r in tr]
                return (snapshot - max(dates)).days if dates else None
            if stem.endswith("_active_day_count"):
                return len({r["trip_start_time"].date() for r in rows})
            if stem.endswith("_txn_count"):
                return len(rows)
            if stem.endswith("_original_price_sum"):
                return sum(r["total_fare"] for r in rows)
            if stem.endswith("_original_price_max"):
                return max((r["total_fare"] for r in rows), default=None)
            if stem.endswith("_discount_amount_sum"):
                return sum(r["discount_amount"] for r in rows)
            if stem.endswith("_trip_distance_km_sum"):
                return round(sum(r["distance_km"] for r in rows), 2)
            return None

        def vf_metric(stem: str, window: str) -> Any:
            rows = window_rows(od, window, "created_at")
            status = None
            for candidate in ("canceled", "completed", "delivered"):
                if f"_{candidate}_" in stem:
                    # feature "canceled" (1 L) ↔ raw "cancelled" (2 L) — xem note ở gsm_metric.
                    status = "cancelled" if candidate == "canceled" else candidate
                    break
            if status:
                rows = [r for r in rows if r["status"] == status]
            if "accessories" in stem:
                rows = [r for r in rows if r["order_type"] == "accessories"]
            elif "_wo_" in stem:
                rows = [r for r in rows if r["order_type"] == "work_order"]
            elif "_nvso_" in stem:
                rows = [r for r in rows if r["order_type"] == "nvso"]
            if "days_since_first_completed_txn_days" in stem:
                dates = [r["updated_at"].date() for r in od if r["status"] == "completed"]
                return (snapshot - min(dates)).days if dates else None
            if "days_since_last_completed_txn_days" in stem:
                dates = [r["updated_at"].date() for r in od if r["status"] == "completed"]
                return (snapshot - max(dates)).days if dates else None
            if stem.startswith("txn_first_completed_updated_date_min"):
                return min((r["updated_at"].date() for r in rows), default=None)
            if stem.startswith("txn_last_completed_updated_date_max"):
                return max((r["updated_at"].date() for r in rows), default=None)
            if stem.endswith("_active_day_count"):
                return len({r["created_at"].date() for r in rows})
            if stem.endswith("_count"):
                if stem.startswith("txn_discount_"):
                    return sum(r["list_price"] > r["paid_amount"] for r in rows)
                return len(rows)
            if stem.endswith("_amount_sum"):
                return sum(r["paid_amount"] for r in rows)
            if stem.endswith("_price_sum"):
                return sum(r["list_price"] for r in rows)
            if stem.endswith("_processing_time_max"):
                return max(((r["updated_at"] - r["created_at"]).total_seconds() / 60 for r in rows), default=None)
            if stem.endswith("_processing_time_min"):
                return min(((r["updated_at"] - r["created_at"]).total_seconds() / 60 for r in rows), default=None)
            if stem.endswith("_battery_sum"):
                values = [r["battery_kwh"] for r in rows if r["battery_kwh"] is not None]
                return round(sum(values), 2) if values else None
            return None

        for feat in features:
            stem = feat.metric
            window = feat.window or "l1m"
            if "_vs_" in window:
                left, right = window.split("_vs_", 1)
                metric = gsm_metric if feat.table.endswith("gsm_transaction") else vf_metric
                value = _ratio(metric(stem, left), metric(stem, right))
            else:
                value = gsm_metric(stem, window) if feat.table.endswith("gsm_transaction") else vf_metric(stem, window)
            (gsm if feat.table.endswith("gsm_transaction") else vf)[feat.name] = value
        gsm_rows.append(gsm)
        vf_rows.append(vf)
    return gsm_rows, vf_rows


def data_quality_errors(
    customers: list[dict], trips: list[dict], orders: list[dict],
    gsm_rows: list[dict], vf_rows: list[dict],
) -> list[str]:
    """Small deterministic gate for the mock-store invariants used in Sprint 1."""
    errors: list[str] = []
    trip_customers = {row["customer_id"] for row in trips}
    order_customers = {row["customer_id"] for row in orders}
    groups = {
        (cid in trip_customers, cid in order_customers)
        for cid in (customer["customer_id"] for customer in customers)
    }
    if groups != {(False, False), (False, True), (True, False), (True, True)}:
        errors.append("missing customer activity group")

    for row in gsm_rows + vf_rows:
        for name, value in row.items():
            if name.endswith("_l1m") and any(token in name for token in ("_count_", "_sum_", "_max_")):
                prefix = name.removesuffix("l1m")
                wider = [row.get(prefix + window) for window in ("l3m", "l12m")]
                if value is not None and any(other is not None and value > other for other in wider):
                    errors.append(f"window invariant failed: {name}")
            match = re.match(r"(.+)_(l\d+[wm])_vs_(l\d+[wm])$", name)
            if match and value is not None:
                base, left, right = match.groups()
                left_name, right_name = f"{base}_{left}", f"{base}_{right}"
                if left_name in row and right_name in row:
                    expected = _ratio(row[left_name], row[right_name])
                    if expected != value:
                        errors.append(f"ratio invariant failed: {name}")
            if "days_since" in name and value is not None and value < 0:
                errors.append(f"negative recency: {name}")
        first = [value for name, value in row.items() if "first_completed_updated_date" in name and value]
        last = [value for name, value in row.items() if "last_completed_updated_date" in name and value]
        if first and last and min(first) > max(last):
            errors.append("first completed date after last completed date")
    return errors


def _insert(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    names = ", ".join(cols)
    binds = ", ".join(f":{c}" for c in cols)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({binds})"), rows)


def seed() -> dict[str, int]:
    customers, dates, trips, orders = generate_raw()
    gsm, vf = [], []
    for snap in SNAPSHOTS:  # 1 dòng feature / khách / snapshot (PK = customer_id + snapshot_date)
        g_rows, v_rows = build_features(customers, trips, orders, snap)
        gsm += g_rows
        vf += v_rows
    errors = data_quality_errors(customers, trips, orders, gsm, vf)
    if errors:
        raise RuntimeError("Mock data quality failed: " + "; ".join(sorted(set(errors))[:5]))
    engine = get_engine()
    with engine.begin() as conn:
        for table in ("feature.vinfast_transaction", "feature.gsm_transaction", "raw.vinfast_orders",
                      "raw.gsm_trips", "raw.date_dim", "raw.customers"):
            conn.execute(text(f"DELETE FROM {table}"))
        _insert(conn, "raw.customers", customers)
        _insert(conn, "raw.date_dim", dates)
        _insert(conn, "raw.gsm_trips", trips)
        _insert(conn, "raw.vinfast_orders", orders)
        _insert(conn, "feature.gsm_transaction", gsm)
        _insert(conn, "feature.vinfast_transaction", vf)
    feature_count, synonym_count = seed_metadata()
    return {
        "customers": len(customers), "snapshots": len(SNAPSHOTS), "dates": len(dates),
        "trips": len(trips), "orders": len(orders),
        "gsm_rows": len(gsm), "vinfast_rows": len(vf),
        "catalog": feature_count, "synonyms": synonym_count,
    }


def main() -> None:
    print(seed())


if __name__ == "__main__":
    main()
