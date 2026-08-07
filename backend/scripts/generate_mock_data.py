"""Sinh event thô tất định cho raw.* — data faker, KHÔNG phải tầng transform.

Từ bước cutover (docs/dbt_migration_runbook.md bước 7), feature.* do dbt sinh:
    raw (script này) -> silver -> dbt_work -> publish_gold -> feature.*

Script này chỉ còn đúng một việc: sinh event thô kèm những "câu chuyện đã cài" mà
benchmark cần (UNDELIVERED_RATE, REVERSED_RATE, LATE_ARRIVING_RATE, khách genuine
null). Đó là chỗ Python đúng vai. Mọi quy tắc nghiệp vụ — cửa sổ, point-in-time,
buyer/owner, cross-BU — nằm trong dbt/models/ và được dbt test canh.

KHÔNG đổi `RNG = random.Random(20260723)`: mất seed là mất parity với baseline
schema `parity` vĩnh viễn (đường Python đã bị xoá, không tái tạo được).
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from scripts.seed_metadata import (
    seed as seed_metadata,
    seed_breakdown_catalog,
    seed_join_catalog,
)

RNG = random.Random(20260723)
# Qua settings (đọc .env) chứ không os.getenv: biến trong .env không được export ra
# môi trường, nên đọc thẳng env sẽ âm thầm rơi về date.today() và phá parity.
# pydantic tự validate định dạng YYYY-MM-DD.
SNAPSHOT = get_settings().snapshot_date or date.today()
UTC = timezone.utc
CUSTOMER_COUNT = 1000   
# 6 snapshot cách ~30 ngày (cũ→mới), mới nhất = SNAPSHOT. Cho time-series /
# window-compare / reporter đêm. ponytail: cách đều 30 ngày thay vì month-end
# lịch để tránh số học tháng — đủ để test dịch chuyển MoM.
SNAPSHOTS = tuple(SNAPSHOT - timedelta(days=30 * k) for k in range(5, -1, -1))
# Sự kiện phải phủ tới l12m của snapshot cũ nhất (SNAPSHOT-150 → cần ~515 ngày).
EVENT_DAYS_BACK = 550


def _timestamp(days_back: int) -> datetime:
    d = SNAPSHOT - timedelta(days=RNG.randint(0, days_back))
    return datetime.combine(d, time(RNG.randint(6, 22), RNG.randint(0, 59)), UTC)


_END_OF_TIME = datetime.combine(SNAPSHOT, time.max, UTC)
# 30% đơn xe hoàn tất CHƯA bàn giao → tồn tại khách buyer nhưng chưa phải owner.
# Không có nhóm này thì mọi test buyer-vs-owner pass giả (docs/vehicle_owner_semantics.md §2).
UNDELIVERED_RATE = 0.30
REVERSED_RATE = 0.02   # trả xe / đổi xe
LATE_ARRIVING_RATE = 0.03  # sự kiện về trễ: recorded_at >> status_at (ADR 0002)


def _recorded(event_at: datetime) -> datetime:
    """Ingest time — chỉ để audit độ trễ, KHÔNG bao giờ dùng để lọc snapshot."""
    lag = RNG.randint(10, 40) if RNG.random() < LATE_ARRIVING_RATE else RNG.randint(0, 2)
    return event_at + timedelta(days=lag)


def _status_history(order: dict, handover: dict | None = None) -> list[dict]:
    """created → processing → {completed | cancelled} → (delivered).

    `completed` và `cancelled` là hai trạng thái KẾT THÚC loại trừ nhau: một order
    chỉ có ĐÚNG MỘT (docs/vehicle_owner_semantics.md §5). Không sinh chuỗi quay lui.

    `delivered` KHÔNG phải trạng thái thứ ba song song: nó là bước giao hàng SAU khi
    đơn đã hoàn tất, và với đơn xe nó được SUY RA từ bản ghi bàn giao chứ không tự
    sinh — nếu không hai nguồn sẽ nói ngược nhau (đơn 'delivered' mà không có bàn giao).
    """
    created_at, final_at = order["created_at"], order["updated_at"]
    status, span = order["status"], order["updated_at"] - order["created_at"]
    rows = [("created", created_at)]
    if final_at > created_at and status != "created":
        rows.append(("processing", created_at + span / 2))
    if status == "cancelled":
        rows.append(("cancelled", final_at))
    elif status == "delivered":
        # Đơn phụ kiện/dịch vụ giao thẳng — vẫn phải chốt hoàn tất trước khi giao.
        rows.append(("completed", created_at + span * 3 / 4))
        rows.append(("delivered", final_at))
    elif status == "completed":
        rows.append(("completed", final_at))
    if handover and handover["handed_over_at"]:  # đơn xe: giao = lúc bàn giao
        rows.append(("delivered", handover["handed_over_at"]))
    return [
        {
            "order_id": order["order_id"], "status": status, "status_at": at,
            "recorded_at": _recorded(at), "source_system": "mock",
        }
        for status, at in rows
    ]


def _handover(order: dict) -> dict | None:
    """Bàn giao xe — nguồn DUY NHẤT của quyền sở hữu.

    Chỉ đơn `vehicle` + `completed` mới có thể có bàn giao. Bàn giao xảy ra SAU khi
    đơn hoàn tất 5–60 ngày, nên cùng một khách có thể là buyer ở snapshot này mà
    chỉ thành owner ở snapshot sau — đúng thứ Task 2.2 phải chứng minh.
    """
    if order["order_type"] != "vehicle" or order["status"] != "completed":
        return None
    if RNG.random() < UNDELIVERED_RATE:
        return None
    handed = order["updated_at"] + timedelta(days=RNG.randint(5, 60))
    row = {
        "order_id": order["order_id"], "customer_id": order["customer_id"],
        "vehicle_id": f"VF-{order['order_id']:06d}",
        "scheduled_at": order["updated_at"] + timedelta(days=RNG.randint(1, 5)),
        "handed_over_at": None, "reversed_at": None,
        "handover_status": "scheduled", "source_system": "mock",
    }
    if handed > _END_OF_TIME:  # đã hẹn nhưng chưa tới ngày giao
        row["recorded_at"] = _recorded(row["scheduled_at"])
        return row
    row.update(handover_status="completed", handed_over_at=handed)
    if RNG.random() < REVERSED_RATE:
        reversed_at = handed + timedelta(days=RNG.randint(10, 120))
        if reversed_at <= _END_OF_TIME:
            # Đảo SAU snapshot cũ ⇒ ở snapshot đó khách VẪN là owner (ADR 0002).
            row.update(handover_status="reversed", reversed_at=reversed_at)
    row["recorded_at"] = _recorded(row["handed_over_at"])
    return row


def generate_raw() -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
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
                    # Đơn xe KHÔNG tự nhận 'delivered': trạng thái đó suy ra từ bản ghi
                    # bàn giao ở dưới. Đơn phụ kiện/dịch vụ thì giao thẳng, không có handover.
                    "status": RNG.choices(
                        ["completed", "cancelled", "processing"], [80, 10, 10]
                    )[0] if order_type == "vehicle" else RNG.choices(
                        ["completed", "delivered", "cancelled", "processing"], [65, 15, 10, 10]
                    )[0],
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
    history: list[dict] = []
    handovers: list[dict] = []
    for order in orders:
        handover = _handover(order)          # dựa trên updated_at = lúc đơn hoàn tất
        history.extend(_status_history(order, handover))
        if handover:
            handovers.append(handover)
            if handover["handed_over_at"]:
                # Bàn giao là nguồn sự thật; trạng thái hiện tại của đơn theo sau nó.
                order["status"] = "delivered"
                order["updated_at"] = handover["handed_over_at"]
    return customers, dates, trips, orders, history, handovers


def _insert(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    names = ", ".join(cols)
    binds = ", ".join(f":{c}" for c in cols)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({binds})"), rows)


def seed() -> dict[str, int]:
    customers, dates, trips, orders, history, handovers = generate_raw()
    engine = get_engine()
    with engine.begin() as conn:
        # feature.* vẫn bị xoá dù script này không còn ghi vào đó: gold suy ra từ raw,
        # thay raw mà giữ gold là để agent trả lời bằng số của bộ dữ liệu cũ.
        # Nạp lại bằng run_dbt build + publish_gold (xem main()).
        # Thứ tự xóa theo chiều ngược FK: handover/history tham chiếu vinfast_orders.
        for table in ("feature.customer_cross_bu_feature",
                      "feature.vinfast_transaction", "feature.gsm_transaction",
                      "raw.vinfast_vehicle_handover", "raw.vinfast_order_status_history",
                      "raw.vinfast_orders", "raw.gsm_trips","raw.feature_snapshot", "raw.date_dim", "raw.customers"):
            conn.execute(text(f"DELETE FROM {table}"))
        _insert(conn, "raw.customers", customers)
        _insert(conn, "raw.date_dim", dates)
        _insert(conn, "raw.feature_snapshot", [{"snapshot_date": snap} for snap in SNAPSHOTS])
        _insert(conn, "raw.gsm_trips", trips)
        _insert(conn, "raw.vinfast_orders", orders)
        _insert(conn, "raw.vinfast_order_status_history", history)
        _insert(conn, "raw.vinfast_vehicle_handover", handovers)
    feature_count, synonym_count = seed_metadata()
    join_rules = seed_join_catalog()
    breakdowns = seed_breakdown_catalog()
    return {
        "customers": len(customers), "snapshots": len(SNAPSHOTS), "dates": len(dates),
        "trips": len(trips), "orders": len(orders),
        "status_history": len(history), "handovers": len(handovers),
        "catalog": feature_count, "synonyms": synonym_count,
        "join_rules": join_rules, "breakdowns": breakdowns,
    }


def main() -> None:
    print(seed())
    # feature.* vừa bị xoá cùng raw và CHƯA được nạp lại — gold suy ra từ raw, raw
    # đổi thì gold cũ sai. Để trống là hỏng ồn ào; để nguyên bản cũ là trả lời sai
    # trong im lặng. Hai lệnh dưới nạp lại nó.
    print("\nfeature.* đang RỖNG. Chạy tiếp:\n"
          "  python -m scripts.run_dbt build\n"
          "  python -m scripts.publish_gold")


if __name__ == "__main__":
    main()
