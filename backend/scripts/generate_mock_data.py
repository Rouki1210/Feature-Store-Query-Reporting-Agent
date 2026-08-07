"""Generate deterministic Sprint 1 raw data and customer snapshot features."""
from __future__ import annotations

import random
import os
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.semantic.feature_spec import ALL_TIME, SPRINT2_WINDOWS, WINDOW_DAYS, all_features
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


def _cutoff(snapshot: date) -> datetime:
    """Point-in-time: sự kiện phải xảy ra <= hết ngày snapshot."""
    return datetime.combine(snapshot, time.max, UTC)


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


def _within(ts: datetime, window: str, snapshot: date) -> bool:
    if window == ALL_TIME:  # luỹ kế: mọi sự kiện đã xảy ra tính tới snapshot
        return ts.date() <= snapshot
    days = WINDOW_DAYS[window]
    return snapshot - timedelta(days=days - 1) <= ts.date() <= snapshot


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 4) if a is not None and b else None


def _vehicle_pit(
    cid: int, snapshot: date,
    purchases_by: dict[int, list[datetime]], handovers_by: dict[int, list[dict]],
) -> dict[str, Any]:
    """Feature buyer/owner tại snapshot — lọc theo EVENT TIME (ADR 0002).

    Không dùng `recorded_at`: sự kiện về trễ vẫn thuộc snapshot mà nó xảy ra.
    Không dùng `vinfast_orders.status`: đó là trạng thái hiện tại, dùng nó ở
    snapshot cũ là rò dữ liệu tương lai.
    """
    cutoff = _cutoff(snapshot)
    purchases = [at for at in purchases_by[cid] if at <= cutoff]
    handed = [h for h in handovers_by[cid]
              if h["handed_over_at"] and h["handed_over_at"] <= cutoff]
    # Đảo bàn giao SAU cutoff không ảnh hưởng snapshot này — vẫn là chủ xe lúc đó.
    owned = [h for h in handed
             if not (h["reversed_at"] and h["reversed_at"] <= cutoff)]
    # Đã hẹn lịch nhưng chưa giao tính tới cutoff. Bao gồm cả bản ghi ĐÃ giao sau
    # cutoff: tại thời điểm đó nó vẫn đang là lịch hẹn.
    scheduled = [
        h for h in handovers_by[cid]
        if h.get("scheduled_at") and h["scheduled_at"] <= cutoff
        and not (h["handed_over_at"] and h["handed_over_at"] <= cutoff)
    ]
    last_handover = max((h["handed_over_at"] for h in handed), default=None)
    windowed: dict[str, Any] = {}
    for w in SPRINT2_WINDOWS:
        windowed[f"vehicle_purchase_completed_count_{w}"] = sum(
            _within(at, w, snapshot) for at in purchases)
        windowed[f"vehicle_delivered_count_{w}"] = len({
            h["vehicle_id"] for h in handed if _within(h["handed_over_at"], w, snapshot)})
    return {
        **windowed,
        "is_vehicle_handover_scheduled": bool(scheduled),
        "is_vehicle_buyer": bool(purchases),
        "is_vehicle_owner": bool(owned),
        "first_vehicle_purchase_date": min(purchases).date() if purchases else None,
        # Sự kiện lịch sử: đã từng nhận xe thì ngày đó không mất đi khi trả xe.
        "first_vehicle_handover_date": last_handover and min(
            h["handed_over_at"] for h in handed).date(),
        "days_since_last_vehicle_handover": (
            (snapshot - last_handover.date()).days if last_handover else None),
    }


def build_features(
    customers: list[dict], trips: list[dict], orders: list[dict],
    snapshot: date = SNAPSHOT,
    history: list[dict] | None = None, handovers: list[dict] | None = None,
) -> tuple[list[dict], list[dict]]:
    trips_by: dict[int, list[dict]] = defaultdict(list)
    orders_by: dict[int, list[dict]] = defaultdict(list)
    for row in trips:
        trips_by[row["customer_id"]].append(row)
    for row in orders:
        orders_by[row["customer_id"]].append(row)

    # Buyer = đơn `vehicle` chạm `completed` trong status history (không đọc
    # vinfast_orders.status). Owner = bàn giao completed chưa bị đảo.
    vehicle_orders = {o["order_id"]: o for o in orders if o["order_type"] == "vehicle"}
    purchases_by: dict[int, list[datetime]] = defaultdict(list)
    for row in history or ():
        order = vehicle_orders.get(row["order_id"])
        if order and row["status"] == "completed":
            purchases_by[order["customer_id"]].append(row["status_at"])
    handovers_by: dict[int, list[dict]] = defaultdict(list)
    for row in handovers or ():
        handovers_by[row["customer_id"]].append(row)
    gsm_rows, vf_rows = [], []
    features = [
        feat for feat in all_features()
        if feat.table in {"feature.gsm_transaction", "feature.vinfast_transaction"}
    ]
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

        pit = _vehicle_pit(cid, snapshot, purchases_by, handovers_by)
        for feat in features:
            stem = feat.metric
            if feat.name in pit:  # buyer/owner: tính riêng, không qua vf_metric
                vf[feat.name] = pit[feat.name]
                continue
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


def build_cross_bu(
    gsm_rows: list[dict], vf_rows: list[dict],
    trips: list[dict], orders: list[dict], snapshot: date,
) -> list[dict]:
    """Bảng cross-BU tính sẵn — 1 dòng / customer / snapshot (ADR 0001).

    Dựng bằng FULL OUTER trên `customer_id`: khách chỉ có MỘT đơn vị vẫn phải có dòng,
    vì đó chính là nhóm mà câu hỏi overlap cần đếm. INNER JOIN sẽ nuốt mất họ.

    NULL vs 0 (docs/join_policy.md §5): NULL = chưa từng có dữ liệu ở đơn vị đó;
    0 = có dữ liệu nhưng kỳ này bằng 0. Trộn hai thứ này làm mọi trung bình sai.
    """
    ever_gsm = {r["customer_id"] for r in trips if r["trip_start_time"].date() <= snapshot}
    ever_vf = {r["customer_id"] for r in orders if r["created_at"].date() <= snapshot}
    gsm_by = {r["customer_id"]: r for r in gsm_rows}
    vf_by = {r["customer_id"]: r for r in vf_rows}
    # Cửa sổ `all` không có cột nguồn ở hai bảng BU (chúng dừng ở l12m), nên tính
    # thẳng từ raw — mirror ĐÚNG bộ lọc của gsm_metric/vf_metric để không lệch nguồn.
    all_gsm: dict[int, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in trips:
        if r["status"] == "completed" and r["trip_start_time"].date() <= snapshot:
            acc = all_gsm[r["customer_id"]]
            acc[0] += r["total_fare"]
            acc[1] += 1
    all_vf: dict[int, list[float]] = defaultdict(lambda: [0.0, 0])
    for r in orders:
        if (r["status"] == "completed" and r["created_at"].date() <= snapshot
                and r["updated_at"].date() <= snapshot):
            acc = all_vf[r["customer_id"]]
            acc[0] += r["paid_amount"]
            acc[1] += 1

    rows = []
    # HỢP hai phía, không duyệt theo một bên: duyệt theo gsm_rows là INNER JOIN trá hình
    # và làm mất sạch khách chỉ có VinFast — đúng nhóm mà UC2-16 cần đếm.
    for cid in sorted(set(gsm_by) | set(vf_by)):
        gsm, vf = gsm_by.get(cid, {}), vf_by.get(cid, {})
        row: dict[str, Any] = {"customer_id": cid, "snapshot_date": snapshot}
        base: tuple[float, float] = (0.0, 0.0)
        for w in SPRINT2_WINDOWS:
            if w == ALL_TIME:
                gsm_spend = all_gsm[cid][0] if cid in ever_gsm else None
                vf_spend = all_vf[cid][0] if cid in ever_vf else None
                active_gsm, active_vf = bool(all_gsm[cid][1]), bool(all_vf[cid][1])
            else:
                gsm_spend = gsm.get(f"completed_original_price_sum_{w}") if cid in ever_gsm else None
                vf_spend = vf.get(f"txn_completed_amount_sum_{w}") if cid in ever_vf else None
                active_gsm = bool(gsm.get(f"completed_txn_count_{w}"))
                active_vf = bool(vf.get(f"txn_completed_count_{w}"))
            combined = (
                None if gsm_spend is None and vf_spend is None
                else (gsm_spend or 0) + (vf_spend or 0)
            )
            pair = (gsm_spend or 0, vf_spend or 0)
            if not combined:  # 0 hoặc None ⇒ không có gì để so sánh, KHÔNG mặc định GSM
                dominant = None
            elif pair[0] == pair[1]:
                dominant = "TIE"
            else:
                dominant = "GSM" if pair[0] > pair[1] else "VINFAST"
            if w == "l1m":
                base = pair
                row["_active_gsm_l1m"] = active_gsm
            row.update({
                f"is_active_gsm_{w}": active_gsm,
                f"is_active_vinfast_{w}": active_vf,
                f"is_cross_bu_active_{w}": active_gsm and active_vf,
                f"gsm_spend_{w}": gsm_spend,
                f"vinfast_spend_{w}": vf_spend,
                f"combined_spend_{w}": combined,
                f"dominant_business_unit_{w}": dominant,
            })
        # Score không gắn cửa sổ — chốt trên l1m (kỳ gần nhất) để đọc là "đang cân bằng
        # hay đang dồn một phía", không phải trung bình cả năm.
        active_gsm_l1m = row.pop("_active_gsm_l1m", False)
        row["cross_bu_engagement_score"] = (
            None if not sum(base) else
            1.0 if base[0] == base[1] else round(min(base) / max(base), 4)
        )
        row["gsm_active_vehicle_owner_flag"] = active_gsm_l1m and bool(vf.get("is_vehicle_owner"))
        rows.append(row)
    return rows


def cross_bu_errors(cross_rows: list[dict], gsm_rows: list[dict], vf_rows: list[dict]) -> list[str]:
    """Gate riêng cho bảng cross-BU: khớp nguồn, không nhân dòng, null/zero đúng nghĩa."""
    errors: list[str] = []
    keys = [(r["customer_id"], r["snapshot_date"]) for r in cross_rows]
    if len(keys) != len(set(keys)):
        errors.append("cross-BU duplicate (customer_id, snapshot_date)")
    gsm_by = {r["customer_id"]: r for r in gsm_rows}
    vf_by = {r["customer_id"]: r for r in vf_rows}
    # So với HỢP hai nguồn, không so với riêng GSM: so với GSM thì một hàm bỏ sót
    # khách chỉ-có-VinFast vẫn qua gate.
    expected = set(gsm_by) | set(vf_by)
    actual = {r["customer_id"] for r in cross_rows}
    if actual != expected:
        errors.append(
            f"cross-BU sai tập khách: thiếu {sorted(expected - actual)[:3]}, "
            f"thừa {sorted(actual - expected)[:3]}"
        )

    windows = [w for w in SPRINT2_WINDOWS if w != ALL_TIME]  # `all` không có cột nguồn
    for row in cross_rows:
        cid = row["customer_id"]
        for w in windows:
            if row[f"gsm_spend_{w}"] is not None and (
                row[f"gsm_spend_{w}"] != gsm_by[cid].get(f"completed_original_price_sum_{w}")
            ):
                errors.append(f"cross-BU gsm_spend_{w} không khớp nguồn")
            if row[f"vinfast_spend_{w}"] is not None and (
                row[f"vinfast_spend_{w}"] != vf_by[cid].get(f"txn_completed_amount_sum_{w}")
            ):
                errors.append(f"cross-BU vinfast_spend_{w} không khớp nguồn")
        for w in SPRINT2_WINDOWS:
            if row[f"is_cross_bu_active_{w}"] != (
                row[f"is_active_gsm_{w}"] and row[f"is_active_vinfast_{w}"]
            ):
                errors.append(f"cross-BU active flag {w} không khớp hai cờ thành phần")
            if row[f"dominant_business_unit_{w}"] is None and row[f"combined_spend_{w}"]:
                errors.append(f"cross-BU thiếu dominant {w} khi có chi tiêu")
            # Luỹ kế phải bao hàm cửa sổ hẹp hơn: nếu l1m hoạt động mà `all` không thì
            # một trong hai nguồn tính sai.
            if w != ALL_TIME and row[f"is_active_gsm_{w}"] and not row["is_active_gsm_all"]:
                errors.append(f"cross-BU is_active_gsm_{w} bật nhưng _all tắt")
        if row["gsm_active_vehicle_owner_flag"] and not row["is_active_gsm_l1m"]:
            errors.append("cross-BU owner-flag bật khi không hoạt động GSM")
    if cross_rows and not any(r["vinfast_spend_l1m"] is None for r in cross_rows):
        # Không có khách genuine-null thì test phân biệt NULL vs 0 là vô nghĩa.
        errors.append("cross-BU thiếu khách chưa từng mua VinFast (NULL semantics)")
    return errors


def data_quality_errors(
    customers: list[dict], trips: list[dict], orders: list[dict],
    gsm_rows: list[dict], vf_rows: list[dict],
    handovers: list[dict] | None = None,
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

    # Buyer/owner (Task 2.2) — docs/vehicle_owner_semantics.md §2.
    for row in vf_rows:
        if row.get("is_vehicle_owner") and not row.get("is_vehicle_buyer"):
            errors.append("owner without buyer")
        bought = row.get("first_vehicle_purchase_date")
        handed = row.get("first_vehicle_handover_date")
        if bought and handed and handed < bought:
            errors.append("handover before purchase")
        if row.get("is_vehicle_buyer") is None or row.get("is_vehicle_owner") is None:
            errors.append("buyer/owner flag must never be NULL")
        # Luỹ kế bao hàm cửa sổ hẹp: đếm _l1m không thể lớn hơn _all.
        for w in ("l1m", "l3m", "l6m", "l12m"):
            for stem in ("vehicle_purchase_completed_count", "vehicle_delivered_count"):
                if (row.get(f"{stem}_{w}") or 0) > (row.get(f"{stem}_all") or 0):
                    errors.append(f"{stem}_{w} lớn hơn {stem}_all")
    # Hai nguồn không được nói ngược nhau: đơn xe `delivered` phải có bản ghi bàn giao,
    # và ngược lại. Mâu thuẫn ở đây làm mọi so sánh buyer/owner vô nghĩa.
    if handovers is not None:
        handed_orders = {h["order_id"] for h in handovers if h["handed_over_at"]}
        for order in orders:
            if order["order_type"] != "vehicle":
                continue
            delivered = order["status"] == "delivered"
            if delivered != (order["order_id"] in handed_orders):
                errors.append("vehicle order status contradicts handover record")
                break

    if vf_rows and not any(
        row.get("is_vehicle_buyer") and not row.get("is_vehicle_owner") for row in vf_rows
    ):
        # Không có nhóm "đã mua, chưa nhận xe" thì mọi test buyer-vs-owner pass giả.
        errors.append("no buyer-not-owner customer: buyer/owner tests would be vacuous")
    return errors


def _insert(conn, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    names = ", ".join(cols)
    binds = ", ".join(f":{c}" for c in cols)
    conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({binds})"), rows)


def seed() -> dict[str, int]:
    customers, dates, trips, orders, history, handovers = generate_raw()
    gsm, vf, cross = [], [], []
    for snap in SNAPSHOTS:  # 1 dòng feature / khách / snapshot (PK = customer_id + snapshot_date)
        g_rows, v_rows = build_features(customers, trips, orders, snap, history, handovers)
        c_rows = build_cross_bu(g_rows, v_rows, trips, orders, snap)
        errors = cross_bu_errors(c_rows, g_rows, v_rows)
        if errors:
            raise RuntimeError(f"Cross-BU quality failed @{snap}: " + "; ".join(sorted(set(errors))[:5]))
        gsm += g_rows
        vf += v_rows
        cross += c_rows
    errors = data_quality_errors(customers, trips, orders, gsm, vf, handovers)
    if errors:
        raise RuntimeError("Mock data quality failed: " + "; ".join(sorted(set(errors))[:5]))
    engine = get_engine()
    with engine.begin() as conn:
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
        _insert(conn, "feature.gsm_transaction", gsm)
        _insert(conn, "feature.vinfast_transaction", vf)
        _insert(conn, "feature.customer_cross_bu_feature", cross)
    feature_count, synonym_count = seed_metadata()
    join_rules = seed_join_catalog()
    breakdowns = seed_breakdown_catalog()
    return {
        "customers": len(customers), "snapshots": len(SNAPSHOTS), "dates": len(dates),
        "trips": len(trips), "orders": len(orders),
        "status_history": len(history), "handovers": len(handovers),
        "gsm_rows": len(gsm), "vinfast_rows": len(vf), "cross_bu_rows": len(cross),
        "catalog": feature_count, "synonyms": synonym_count,
        "join_rules": join_rules, "breakdowns": breakdowns,
    }


def main() -> None:
    print(seed())


if __name__ == "__main__":
    main()
