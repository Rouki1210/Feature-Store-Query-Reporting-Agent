"""Task 2.2 — point-in-time buyer/owner.

Thuần hàm, không chạm DB: dựng vài sự kiện rồi gọi `build_features` ở nhiều snapshot.
Bốn thứ phải đúng, mỗi thứ là một cách hỏng khác nhau:

  1. future leak     — snapshot cũ nhìn thấy sự kiện tương lai;
  2. late arriving   — lọc nhầm theo `recorded_at` thay vì event time (ADR 0002);
  3. reversed        — trả xe sau snapshot lại xóa quyền sở hữu ở snapshot đó;
  4. buyer ≠ owner   — suy owner từ `status='completed'`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from scripts.generate_mock_data import build_features, data_quality_errors

UTC = timezone.utc
D = date(2026, 6, 30)          # snapshot "hiện tại"
D_PREV = date(2026, 5, 31)     # snapshot trước đó


def _at(day: int, month: int = 6) -> datetime:
    return datetime(2026, month, day, 10, 0, tzinfo=UTC)


CUSTOMER = {"customer_id": 1}
ORDER = {
    "order_id": 10, "customer_id": 1, "created_at": _at(1, 5), "updated_at": _at(10, 5),
    "status": "completed", "order_type": "vehicle", "list_price": 900_000_000,
    "paid_amount": 900_000_000, "battery_kwh": 60.0, "vehicle_model": "VF 8",
    "source_system": "mock",
}
PURCHASED = {  # đơn xe chạm completed ngày 10/5
    "order_id": 10, "status": "completed", "status_at": _at(10, 5),
    "recorded_at": _at(11, 5), "source_system": "mock",
}


def _vf(snapshot: date, history: list[dict], handovers: list[dict]) -> dict:
    _gsm, vf = build_features([CUSTOMER], [], [ORDER], snapshot, history, handovers)
    return vf[0]


def _handover(handed: datetime | None, reversed_at: datetime | None = None,
              recorded: datetime | None = None) -> dict:
    return {
        "order_id": 10, "customer_id": 1, "vehicle_id": "VF-000010",
        "scheduled_at": _at(12, 5), "handed_over_at": handed, "reversed_at": reversed_at,
        "handover_status": "reversed" if reversed_at else ("completed" if handed else "scheduled"),
        "recorded_at": recorded or (handed or _at(12, 5)), "source_system": "mock",
    }


# ---------------------------------------------------------------- 1. future leak

def test_handover_after_snapshot_is_invisible():
    """Bàn giao 15/6 ⇒ ở snapshot 31/5 khách CHƯA phải chủ xe."""
    handovers = [_handover(_at(15))]
    assert _vf(D_PREV, [PURCHASED], handovers)["is_vehicle_owner"] is False
    assert _vf(D, [PURCHASED], handovers)["is_vehicle_owner"] is True


def test_purchase_after_snapshot_is_invisible():
    late_purchase = dict(PURCHASED, status_at=_at(20), recorded_at=_at(20))
    assert _vf(D_PREV, [late_purchase], [])["is_vehicle_buyer"] is False
    assert _vf(D, [late_purchase], [])["is_vehicle_buyer"] is True


# ---------------------------------------------------------------- 2. late arriving

def test_late_arriving_event_still_counts():
    """`status_at` <= D nhưng `recorded_at` > D ⇒ VẪN tính (ADR 0002).

    Lọc theo recorded_at sẽ làm báo cáo tháng 5 nói khách chưa nhận xe, trong khi
    thực tế họ đã nhận — sai với cái business tự đếm được.
    """
    handovers = [_handover(_at(20, 5), recorded=_at(25))]  # xảy ra 20/5, ghi nhận 25/6
    row = _vf(D_PREV, [PURCHASED], handovers)
    assert row["is_vehicle_owner"] is True
    assert row["first_vehicle_handover_date"] == date(2026, 5, 20)


# ---------------------------------------------------------------- 3. reversed

def test_reversal_after_snapshot_keeps_ownership():
    """Trả xe 15/6 ⇒ snapshot 31/5 vẫn là chủ xe, snapshot 30/6 thì không."""
    handovers = [_handover(_at(20, 5), reversed_at=_at(15))]
    assert _vf(D_PREV, [PURCHASED], handovers)["is_vehicle_owner"] is True
    assert _vf(D, [PURCHASED], handovers)["is_vehicle_owner"] is False


def test_reversal_keeps_historical_handover_date():
    """Đã từng nhận xe là sự kiện lịch sử — trả xe không xóa ngày nhận đầu tiên."""
    row = _vf(D, [PURCHASED], [_handover(_at(20, 5), reversed_at=_at(15))])
    assert row["first_vehicle_handover_date"] == date(2026, 5, 20)
    assert row["is_vehicle_owner"] is False


# ---------------------------------------------------------------- 4. buyer ≠ owner

def test_buyer_without_handover_is_not_owner():
    """Điểm chính của Sprint 2: đơn hoàn tất KHÔNG đồng nghĩa đã nhận xe."""
    row = _vf(D, [PURCHASED], [])
    assert row["is_vehicle_buyer"] is True
    assert row["is_vehicle_owner"] is False
    assert row["first_vehicle_handover_date"] is None
    assert row["days_since_last_vehicle_handover"] is None


def test_scheduled_handover_is_not_ownership():
    """Đã hẹn giao nhưng chưa giao (handed_over_at NULL) ⇒ chưa phải chủ xe."""
    row = _vf(D, [PURCHASED], [_handover(None)])
    assert row["is_vehicle_owner"] is False
    assert row["is_vehicle_handover_scheduled"] is True   # UC2-09


def test_scheduled_flag_clears_after_handover():
    """Đã nhận xe rồi thì không còn là 'đang chờ giao'."""
    row = _vf(D, [PURCHASED], [_handover(_at(20, 5))])
    assert row["is_vehicle_handover_scheduled"] is False
    assert row["is_vehicle_owner"] is True


def test_buyer_without_any_handover_record_is_not_scheduled():
    """UC2-09 khác UC2-11: 'đã hẹn giao' không được gộp với 'mua nhưng chưa hẹn'."""
    row = _vf(D, [PURCHASED], [])
    assert row["is_vehicle_buyer"] is True
    assert row["is_vehicle_handover_scheduled"] is False


def test_cumulative_window_counts_everything_up_to_snapshot():
    """UC2-10: 'tổng cộng bao nhiêu xe đã bàn giao' phải dùng `_all`, không phải `_l1m`."""
    row = _vf(D, [PURCHASED], [_handover(_at(20, 5))])   # bàn giao 20/5, snapshot 30/6
    assert row["vehicle_delivered_count_all"] == 1
    assert row["vehicle_delivered_count_l1m"] == 0       # ngoài cửa sổ 30 ngày
    assert row["vehicle_delivered_count_l3m"] == 1


def test_ownership_never_derived_from_order_status():
    """Order `completed` nhưng KHÔNG có status history ⇒ không buyer, không owner.

    Nếu ai đó lén đọc `vinfast_orders.status`, test này đỏ.
    """
    row = _vf(D, [], [])
    assert row["is_vehicle_buyer"] is False
    assert row["is_vehicle_owner"] is False


def test_days_since_last_handover_is_measured_from_snapshot():
    row = _vf(D, [PURCHASED], [_handover(_at(20, 5))])
    assert row["days_since_last_vehicle_handover"] == (D - date(2026, 5, 20)).days


# ---------------------------------------------------------------- gate dữ liệu

def test_quality_gate_rejects_owner_without_buyer():
    bad = [{"customer_id": 1, "is_vehicle_owner": True, "is_vehicle_buyer": False}]
    assert any("owner without buyer" in e for e in data_quality_errors([], [], [], [], bad))


def test_quality_gate_rejects_handover_before_purchase():
    bad = [{
        "customer_id": 1, "is_vehicle_buyer": True, "is_vehicle_owner": True,
        "first_vehicle_purchase_date": date(2026, 5, 10),
        "first_vehicle_handover_date": date(2026, 5, 1),
    }]
    assert any("handover before purchase" in e for e in data_quality_errors([], [], [], [], bad))


def test_quality_gate_requires_buyer_not_owner_group():
    """Không có nhóm 'đã mua, chưa nhận xe' thì benchmark buyer-vs-owner vô nghĩa."""
    everyone_owns = [{
        "customer_id": 1, "is_vehicle_buyer": True, "is_vehicle_owner": True,
    }]
    errors = data_quality_errors([], [], [], [], everyone_owns)
    assert any("buyer-not-owner" in e for e in errors)


def test_delivered_order_status_agrees_with_handover():
    """Trạng thái đơn `delivered` và bản ghi bàn giao không được nói ngược nhau.

    `delivered` của đơn xe được SUY RA từ handover; nếu ai đó sinh nó ngẫu nhiên
    trở lại, sẽ có đơn 'đã giao' mà không có xe nào được bàn giao.
    """
    import scripts.generate_mock_data as g

    _c, _d, _t, orders, history, handovers = g.generate_raw()
    handed = {h["order_id"] for h in handovers if h["handed_over_at"]}
    for order in orders:
        if order["order_type"] == "vehicle":
            assert (order["status"] == "delivered") == (order["order_id"] in handed)
    # Mọi đơn từng `delivered` đều phải đi qua `completed` trước.
    by_order: dict[int, set[str]] = {}
    for row in history:
        by_order.setdefault(row["order_id"], set()).add(row["status"])
    assert all("completed" in s for s in by_order.values() if "delivered" in s)


def test_generated_mock_has_both_buyers_and_owners():
    """Trên dữ liệu mock thật (seed cố định), cả hai nhóm phải tồn tại."""
    import scripts.generate_mock_data as g

    customers, _dates, trips, orders, history, handovers = g.generate_raw()
    _gsm, vf = g.build_features(customers, trips, orders, g.SNAPSHOTS[-1], history, handovers)
    buyers = [r for r in vf if r["is_vehicle_buyer"]]
    owners = [r for r in vf if r["is_vehicle_owner"]]
    waiting = [r for r in vf if r["is_vehicle_buyer"] and not r["is_vehicle_owner"]]
    assert buyers and owners and waiting
    assert len(owners) < len(buyers), "owner phải là tập con thật sự của buyer"
