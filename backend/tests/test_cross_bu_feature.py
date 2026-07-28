"""Task 2.3 — feature.customer_cross_bu_feature.

Thuần hàm, không chạm DB. Ba thứ phải đúng, mỗi thứ là một cách hỏng riêng:

  1. **Không nhân dòng** — lỗi nguy hiểm nhất của Sprint 2: số vẫn "hợp lý" khi sai.
  2. **Không nuốt khách một-BU** — INNER JOIN sẽ làm câu hỏi overlap trả lời sai chiều.
  3. **NULL ≠ 0** — trung bình chi tiêu tính cả khách chưa từng mua là số sai mà SQL đúng.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from scripts.generate_mock_data import build_cross_bu, cross_bu_errors

UTC = timezone.utc
D = date(2026, 6, 30)


def _gsm(cid: int, spend=None, count=0, **extra) -> dict:
    return {
        "customer_id": cid, "snapshot_date": D,
        "completed_original_price_sum_l1m": spend, "completed_txn_count_l1m": count, **extra,
    }


def _vf(cid: int, spend=None, count=0, owner=False) -> dict:
    return {
        "customer_id": cid, "snapshot_date": D,
        "txn_completed_amount_sum_l1m": spend, "txn_completed_count_l1m": count,
        "is_vehicle_owner": owner,
    }


def _trip(cid: int, fare: float = 0.0, status: str = "completed") -> dict:
    # `status`/`total_fare` cần cho cửa sổ `all` — nó tính thẳng từ raw vì hai bảng BU
    # chỉ có cột tới l12m.
    return {
        "customer_id": cid, "trip_start_time": datetime(2026, 6, 1, tzinfo=UTC),
        "status": status, "total_fare": fare,
    }


def _order(cid: int, paid: float = 0.0, status: str = "completed") -> dict:
    at = datetime(2026, 6, 1, tzinfo=UTC)
    return {
        "customer_id": cid, "created_at": at, "updated_at": at,
        "status": status, "paid_amount": paid,
    }


def _build(gsm, vf, trips, orders):
    return {r["customer_id"]: r for r in build_cross_bu(gsm, vf, trips, orders, D)}


# ---------------------------------------------------------------- 1. grain

def test_one_row_per_customer_snapshot():
    rows = build_cross_bu(
        [_gsm(1, 100, 2), _gsm(2, 50, 1)], [_vf(1, 200, 1), _vf(2)],
        [_trip(1), _trip(1), _trip(2)],           # khách 1 có nhiều chuyến
        [_order(1), _order(1), _order(2)], D,     # và nhiều đơn
    )
    keys = [(r["customer_id"], r["snapshot_date"]) for r in rows]
    assert len(keys) == len(set(keys)) == 2, "nhiều sự kiện không được nhân thành nhiều dòng"


def test_single_bu_customer_still_gets_a_row():
    """Khách chỉ dùng GSM phải có mặt — đó chính là nhóm câu hỏi overlap cần đếm (UC2-16)."""
    rows = _build([_gsm(1, 100, 3)], [_vf(1)], [_trip(1)], [])
    assert 1 in rows
    assert rows[1]["is_active_gsm_l1m"] is True
    assert rows[1]["is_active_vinfast_l1m"] is False
    assert rows[1]["is_cross_bu_active_l1m"] is False


def test_vinfast_only_customer_is_not_dropped():
    """Không có dòng GSM nào ⇒ vẫn phải ra dòng cross-BU.

    Duyệt theo `gsm_rows` là INNER JOIN trá hình: mock hiện sinh đủ dòng GSM cho mọi
    khách nên lỗi không lộ, nhưng contract của bảng là FULL OUTER.
    """
    rows = _build([], [_vf(7, 300, 2, owner=True)], [], [_order(7)])
    assert set(rows) == {7}
    assert rows[7]["is_active_gsm_l1m"] is False
    assert rows[7]["gsm_spend_l1m"] is None       # chưa từng đi GSM
    assert rows[7]["vinfast_spend_l1m"] == 300
    assert rows[7]["dominant_business_unit_l1m"] == "VINFAST"
    assert rows[7]["gsm_active_vehicle_owner_flag"] is False
    assert rows[7]["snapshot_date"] == D


def test_row_set_is_the_union_of_both_sources():
    rows = _build(
        [_gsm(1, 100, 2), _gsm(2, 50, 1)],
        [_vf(2, 80, 1), _vf(3, 90, 1)],
        [_trip(1), _trip(2)], [_order(2), _order(3)],
    )
    assert set(rows) == {1, 2, 3}


def test_gate_catches_dropped_vinfast_only_customer():
    """Gate phải so với HỢP hai nguồn, không so với riêng GSM."""
    gsm_rows, vf_rows = [_gsm(1, 100, 2)], [_vf(1, 50, 1), _vf(3, 70, 1)]
    incomplete = [r for r in build_cross_bu(gsm_rows, vf_rows, [_trip(1)], [_order(1), _order(3)], D)
                  if r["customer_id"] != 3]
    assert any("sai tập khách" in e for e in cross_bu_errors(incomplete, gsm_rows, vf_rows))


# ---------------------------------------------------------------- 2. NULL vs 0

def test_never_bought_vinfast_is_null_not_zero():
    rows = _build([_gsm(1, 100, 3)], [_vf(1)], [_trip(1)], [])
    assert rows[1]["vinfast_spend_l1m"] is None, "chưa từng mua ⇒ NULL (không có dữ liệu)"


def test_had_orders_but_none_this_window_is_zero():
    """Có lịch sử đơn nhưng kỳ này không chi ⇒ 0, KHÁC với chưa từng mua."""
    rows = _build([_gsm(1, 100, 3)], [_vf(1, spend=0, count=0)], [_trip(1)], [_order(1)])
    assert rows[1]["vinfast_spend_l1m"] == 0


def test_combined_spend_treats_null_as_absent():
    rows = _build([_gsm(1, 100, 3)], [_vf(1)], [_trip(1)], [])
    assert rows[1]["combined_spend_l1m"] == 100  # không phải None, không phải 0


def test_combined_is_null_only_when_both_sides_unknown():
    rows = _build([_gsm(1)], [_vf(1)], [], [])
    assert rows[1]["combined_spend_l1m"] is None


# ---------------------------------------------------------------- 3. dominant / score

def test_dominant_unit_is_the_bigger_spender():
    rows = _build([_gsm(1, 100, 1)], [_vf(1, 300, 1)], [_trip(1)], [_order(1)])
    assert rows[1]["dominant_business_unit_l1m"] == "VINFAST"
    assert rows[1]["cross_bu_engagement_score"] == round(100 / 300, 4)


def test_equal_spend_is_tie_not_gsm():
    """Bằng nhau phải nói rõ là TIE — im lặng chọn GSM là bịa."""
    rows = _build([_gsm(1, 200, 1)], [_vf(1, 200, 1)], [_trip(1)], [_order(1)])
    assert rows[1]["dominant_business_unit_l1m"] == "TIE"
    assert rows[1]["cross_bu_engagement_score"] == 1.0


def test_no_spend_has_no_dominant_unit():
    rows = _build([_gsm(1, 0, 0)], [_vf(1, 0, 0)], [_trip(1)], [_order(1)])
    assert rows[1]["dominant_business_unit_l1m"] is None
    assert rows[1]["cross_bu_engagement_score"] is None


def test_one_sided_spend_scores_zero():
    rows = _build([_gsm(1, 500, 2)], [_vf(1, 0, 0)], [_trip(1)], [_order(1)])
    assert rows[1]["cross_bu_engagement_score"] == 0.0
    assert rows[1]["dominant_business_unit_l1m"] == "GSM"


# ---------------------------------------------------------------- 4. owner flag

def test_owner_flag_requires_gsm_activity():
    """UC2-03: 'chủ xe VinFast đang hoạt động GSM' — thiếu vế GSM thì không bật cờ."""
    inactive = _build([_gsm(1, 0, 0)], [_vf(1, 100, 1, owner=True)], [_trip(1)], [_order(1)])
    active = _build([_gsm(2, 90, 4)], [_vf(2, 100, 1, owner=True)], [_trip(2)], [_order(2)])
    assert inactive[1]["gsm_active_vehicle_owner_flag"] is False
    assert active[2]["gsm_active_vehicle_owner_flag"] is True


# ---------------------------------------------------------------- 5. gate

def test_gate_catches_duplicate_rows():
    row = build_cross_bu([_gsm(1)], [_vf(1)], [], [], D)[0]
    errors = cross_bu_errors([row, dict(row)], [_gsm(1)], [_vf(1)])
    assert any("duplicate" in e for e in errors)


def test_gate_catches_spend_drift_from_source():
    rows = build_cross_bu([_gsm(1, 100, 1)], [_vf(1, 50, 1)], [_trip(1)], [_order(1)], D)
    rows[0]["gsm_spend_l1m"] = 999
    assert any("gsm_spend" in e for e in cross_bu_errors(rows, [_gsm(1, 100, 1)], [_vf(1, 50, 1)]))


# ---------------------------------------------------------------- 5b. cửa sổ luỹ kế

def test_all_window_comes_from_raw_not_from_l12m():
    """`all` = luỹ kế tới snapshot. Hai bảng BU dừng ở l12m nên `all` tính từ raw.

    Chuyến ở ngoài mọi cửa sổ (l12m) vẫn phải vào `_all` — nếu ai đó lấy tạm l12m
    làm `all` thì test này đỏ.
    """
    old_trip = dict(_trip(1, fare=500), trip_start_time=datetime(2024, 1, 1, tzinfo=UTC))
    rows = _build([_gsm(1, spend=0, count=0)], [_vf(1)], [old_trip], [])
    assert rows[1]["gsm_spend_all"] == 500
    assert rows[1]["gsm_spend_l1m"] == 0
    assert rows[1]["is_active_gsm_all"] is True
    assert rows[1]["is_active_gsm_l1m"] is False


def test_gate_catches_window_wider_than_all():
    rows = build_cross_bu([_gsm(1, 100, 2)], [_vf(1)], [_trip(1, 100)], [], D)
    rows[0]["is_active_gsm_all"] = False   # l1m bật mà luỹ kế tắt ⇒ vô lý
    assert any("_all tắt" in e for e in cross_bu_errors(rows, [_gsm(1, 100, 2)], [_vf(1)]))


# ---------------------------------------------------------------- 6. retrieval

def test_cross_bu_question_retrieves_cross_bu_table():
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    hits = layer.retrieve("Bao nhiêu khách hoạt động GSM và đồng thời có đơn VinFast hoàn tất", top_k=5)
    assert any("cross_bu" in h.table for h in hits)


def test_owner_question_ranks_owner_above_buyer():
    """"Chủ xe" phải ra `is_vehicle_owner`, KHÔNG ra cột buyer.

    Trước khi miễn cờ boolean khỏi bộ filter theo tên, câu "bao nhiêu khách đang là
    chủ xe" trả về `vehicle_purchase_completed_count_l1m` — đúng cái nhầm buyer/owner
    mà cả Sprint 2 dựng ra để tránh.
    """
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    hits = [f.name for f in layer.retrieve("Bao nhiêu khách đang là chủ xe VinFast", top_k=3)]
    assert hits[0] == "is_vehicle_owner"


def test_money_question_does_not_return_boolean_flags():
    """Cờ boolean không phải câu trả lời cho câu hỏi về tiền."""
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    hits = layer.retrieve(
        "VinFast completed order amount in the last 12 months", business_unit="VINFAST")
    assert all(h.dtype != "boolean" for h in hits)


def test_cross_bu_business_unit_routes_to_cross_bu_table():
    """`business_unit="CROSS_BU"` phải lọc ra đúng bảng cross-BU và KHÁC RỖNG.

    Trước khi sửa, catalog gắn nhãn 9 feature này là VINFAST và filter so theo tiền tố
    tên bảng ⇒ gọi với CROSS_BU trả về 0 feature, Task 2.6 không định tuyến được.
    """
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    hits = layer.retrieve("khách dùng cả hai đơn vị chi tiêu bao nhiêu", business_unit="CROSS_BU")
    assert hits
    assert all("cross_bu" in h.table for h in hits)


def test_vinfast_unit_excludes_cross_bu_features():
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    hits = layer.retrieve("chi tiêu VinFast 1 tháng gần nhất", business_unit="VINFAST", top_k=10)
    assert hits and all("cross_bu" not in h.table for h in hits)


def test_cross_bu_null_semantics_are_documented():
    """Mô tả trong catalog phải nói NULL ≠ 0 — LLM chỉ đọc mô tả để chọn cột."""
    import yaml

    features = {f["name"]: f for f in yaml.safe_load(
        open("data/semantic_layer.yaml", encoding="utf-8"))["features"]}

    spend = features["vinfast_spend_l1m"]
    assert spend["business_unit"] == "CROSS_BU"
    assert spend["null_meaning"] == "no_history_in_unit"
    assert "chưa từng" in spend["description_vi"].lower()

    score = features["cross_bu_engagement_score"]
    assert "min" in score["description_vi"] and "max" in score["description_vi"]
    assert score["null_meaning"] == "no_spend_to_compare"


def test_single_bu_question_does_not_retrieve_cross_bu_table():
    """Cột cross-BU được miễn bộ filter theo tên — bù lại phải có từ khóa 'cả hai'.

    Không có chốt này thì mọi câu GSM/VinFast đơn lẻ đều lôi thêm cột cross-BU vào
    context, và retrieval Sprint 1 tụt.
    """
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    for question in (
        "Số chuyến GSM hoàn thành trong 1 tháng gần nhất",
        "Tổng chi tiêu VinFast 3 tháng gần nhất",
    ):
        assert not any("cross_bu" in h.table for h in layer.retrieve(question, top_k=8))


# ---------------------------------------------------------------- 7. dữ liệu mock thật

def test_generated_mock_cross_bu_is_consistent():
    import scripts.generate_mock_data as g

    customers, _d, trips, orders, history, handovers = g.generate_raw()
    snap = g.SNAPSHOTS[-1]
    gsm, vf = g.build_features(customers, trips, orders, snap, history, handovers)
    cross = g.build_cross_bu(gsm, vf, trips, orders, snap)

    assert g.cross_bu_errors(cross, gsm, vf) == []
    assert len(cross) == len(customers)
    # Bốn nhóm khách phải cùng tồn tại, nếu không benchmark cross-BU vô nghĩa.
    both = [r for r in cross if r["is_cross_bu_active_l1m"]]
    gsm_only = [r for r in cross if r["is_active_gsm_l1m"] and not r["is_active_vinfast_l1m"]]
    vf_only = [r for r in cross if r["is_active_vinfast_l1m"] and not r["is_active_gsm_l1m"]]
    never_vf = [r for r in cross if r["vinfast_spend_l1m"] is None]
    assert both and gsm_only and vf_only and never_vf

    # Tổng khớp nguồn — chốt chặn nhân dòng. Gộp vào đây thay vì một test riêng:
    # `generate_raw()` mất vài giây, chạy hai lần cho cùng bộ dữ liệu là lãng phí.
    assert sum(r["gsm_spend_l1m"] or 0 for r in cross) == sum(
        r.get("completed_original_price_sum_l1m") or 0 for r in gsm)
    assert sum(r["vinfast_spend_l1m"] or 0 for r in cross) == sum(
        r.get("txn_completed_amount_sum_l1m") or 0 for r in vf)
