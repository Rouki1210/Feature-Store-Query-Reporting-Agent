"""Task 2.3 — RETRIEVAL cho feature.customer_cross_bu_feature.

Phần kiểm cách bảng này được TÍNH đã chuyển sang dbt ở bước 7
(docs/dbt_migration_runbook.md) — hàm build_cross_bu() không còn tồn tại:

    dbt/models/int/unit_tests.yml               NULL≠0 · TIE · khách một-BU · cửa sổ `all`
    dbt/tests/assert_candidate_cross_bu_rules.sql   bất biến trên toàn bộ dữ liệu
    dbt/tests/assert_candidate_grain.sql            không nhân dòng
    dbt/tests/assert_mock_dataset_covers_edge_cases.sql

Còn lại ở đây là tầng RETRIEVAL: câu hỏi tiếng Việt phải chọn đúng cột. Tầng đó
không đụng dbt và không đụng DB.
"""
from __future__ import annotations

import pytest


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

    delivered = layer.retrieve("Đã có bao nhiêu khách nhận xe trong tháng trước", business_unit="VINFAST", top_k=1)
    assert delivered[0].name == "vehicle_delivered_count_l1m"


def test_narrow_features_lose_to_the_general_one():
    """Cột hẹp hơn câu hỏi phải bị phạt điểm.

    "Số đơn VinFast hoàn thành" = MỌI đơn, không riêng đơn mua xe / phụ kiện / có
    giảm giá. Không phạt thì cột hẹp thắng nhờ trùng token và agent trả lời một tập
    con mà người hỏi không hề biết — đúng hai case E09/M11 từng đỏ trong eval.
    """
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    hits = layer.retrieve(
        "Số đơn VinFast hoàn thành trong 12 tháng gần nhất của mọi khách",
        business_unit="VINFAST", top_k=5)
    # Cột đúng phải đứng NHẤT. Cột hẹp chỉ bị giảm điểm chứ không bị loại — retrieval
    # hiểu sai câu hỏi vẫn còn đường cứu ở top-k.
    assert hits[0].name == "txn_completed_count_l12m"
    narrow = next(f for f in hits if f.name == "vehicle_purchase_completed_count_l12m")
    assert hits[0].score > narrow.score + 2


def test_narrowing_penalty_lifts_only_when_the_question_asks_for_it():
    """Hỏi đúng phạm vi hẹp thì cột hẹp phải quay lại top."""
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    accessories = [f.name for f in layer.retrieve(
        "Số đơn phụ kiện VinFast hoàn thành trong 12 tháng gần nhất",
        business_unit="VINFAST", top_k=3)]
    assert any("accessories" in name for name in accessories)

    vehicles = [f.name for f in layer.retrieve(
        "Bao nhiêu khách đã mua xe VinFast", business_unit="VINFAST", top_k=3)]
    assert any("vehicle" in name for name in vehicles)


@pytest.mark.parametrize(("question", "business_unit", "expected"), [
    ("Khách nào đã nhận bàn giao xe VinFast", "VINFAST", {"is_vehicle_owner"}),
    (
        "So sánh số khách có đơn xe hoàn tất với số khách đã nhận xe",
        "VINFAST",
        {"is_vehicle_buyer", "is_vehicle_owner"},
    ),
    (
        "Chi tiêu VinFast trung bình của khách hoạt động GSM trong 1 tháng gần nhất",
        "CROSS_BU",
        {"vinfast_spend_l1m", "is_active_gsm_l1m"},
    ),
])
def test_sprint2_golden_retrieval_keeps_required_population_features(
    question, business_unit, expected
):
    from app.semantic.retriever import SemanticLayer

    names = {
        feature.name
        for feature in SemanticLayer.load("data/semantic_layer.yaml").retrieve(
            question, business_unit=business_unit, top_k=5
        )
    }
    assert expected <= names


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


def test_cross_bu_routing_does_not_need_keyword_hint():
    """Router đã gán CROSS_BU thì retrieval không được đòi thêm từ khóa 'cả hai'.

    Hai điều kiện cộng dồn từng làm UC2-03 ("Khách GSM nào đang là chủ xe VinFast")
    trả về 0 feature, rồi agent báo "câu hỏi chưa đủ rõ" — trong khi câu hỏi rất rõ.
    """
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    for question in (
        "Khách GSM nào đang là chủ xe VinFast",
        "So sánh chi tiêu GSM và VinFast của từng khách trong 1 tháng",
        "Chi tiêu GSM của nhóm chủ xe VinFast 1 tháng",
    ):
        hits = layer.retrieve(question, business_unit="CROSS_BU")
        assert hits, question
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
