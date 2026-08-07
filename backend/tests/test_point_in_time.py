"""Bất biến của EVENT THÔ — thứ duy nhất Python còn sinh ra sau cutover.

Bốn ca point-in-time (future leak · late arriving · reversed · buyer ≠ owner) trước
đây test hàm `build_features`/`_vehicle_pit` của generate_mock_data.py. Hàm đó đã bị
xoá ở bước 7 (docs/dbt_migration_runbook.md); quy tắc giờ nằm trong dbt và được
canh bằng dữ liệu dựng sẵn, tương đương 1-1:

    dbt/models/silver/unit_tests.yml
        quyen_so_huu_xe_theo_moc_thoi_gian        4 ca trên, 4 bản ghi bàn giao
        tu_cach_nguoi_mua_khong_phu_thuoc_ngay_giao
    dbt/tests/assert_vehicle_ownership_rules.sql
    dbt/tests/assert_no_future_events_in_snapshot.sql
    dbt/tests/assert_mock_dataset_covers_edge_cases.sql   (bộ mock không rỗng nghĩa)

Chạy: python -m scripts.run_dbt build

Còn lại ở đây là bất biến của chính bộ sinh event — dbt không kiểm được vì nó chỉ
thấy kết quả, không thấy ý định.
"""
from __future__ import annotations


def test_delivered_order_status_agrees_with_handover():
    """Trạng thái đơn `delivered` và bản ghi bàn giao không được nói ngược nhau.

    `delivered` của đơn xe được SUY RA từ handover; nếu ai đó sinh nó ngẫu nhiên
    trở lại, sẽ có đơn 'đã giao' mà không có xe nào được bàn giao — và mọi so sánh
    buyer/owner phía dưới đều mất nghĩa.
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


def test_raw_events_cover_the_edge_cases_dbt_tests_rely_on():
    """Bộ sinh phải thực sự tạo ra ba nhóm mà tầng dbt dựng test lên trên.

    Kiểm ở tầng RAW chứ không phải tầng feature: nếu generate_raw() ngừng sinh
    handover bị đảo hay sự kiện về trễ, test này đỏ ngay tại nguồn thay vì để
    assert_mock_dataset_covers_edge_cases.sql đỏ sau cả một lần build.
    """
    import scripts.generate_mock_data as g

    _c, _d, _t, orders, history, handovers = g.generate_raw()

    # 1. đơn xe hoàn tất nhưng chưa bàn giao ⇒ buyer mà chưa phải owner
    vehicle_completed = {
        o["order_id"] for o in orders
        if o["order_type"] == "vehicle" and o["status"] in ("completed", "delivered")
    }
    handed = {h["order_id"] for h in handovers if h["handed_over_at"]}
    assert vehicle_completed - handed

    # 2. bàn giao bị đảo ⇒ ca "đảo sau snapshot thì vẫn là chủ"
    assert any(h["reversed_at"] for h in handovers)

    # 3. sự kiện về trễ ⇒ recorded_at không bao giờ được dùng để lọc (ADR 0002)
    assert any((r["recorded_at"] - r["status_at"]).days > 7 for r in history)
