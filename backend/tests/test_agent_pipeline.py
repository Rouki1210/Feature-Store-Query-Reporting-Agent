from __future__ import annotations

from app.agent.generator import SQLGenerator
from app.agent.llm_client import StaticJSONClient, parse_json_object
from app.agent.narrator import OptionalLLMNarrator
from app.agent.contracts import NarrationInput
from app.models.schemas import QueryResult
from app.agent.pipeline import AgentPipeline
from app.agent.router import RuleRouter, normalize_question


def _pipeline(payload):
    return AgentPipeline(SQLGenerator(StaticJSONClient(payload)))


def test_normalize_rejects_empty_and_preserves_text():
    original, normalized = normalize_question("  GSM   trips  ")
    assert original == "GSM   trips"
    assert normalized == "gsm trips"


def test_router_refuses_owner_without_llm():
    router = RuleRouter()
    _, decision = router.route("Khách nào là chủ sở hữu xe?")
    assert decision.intent.value == "out_of_scope"
    assert decision.refusal_code.value == "vehicle_owner"


def test_router_refuses_raw_without_llm():
    router = RuleRouter()
    _, decision = router.route("Cho tôi raw customers")
    assert decision.intent.value == "out_of_scope"


def test_pipeline_runs_valid_feature_query():
    client = StaticJSONClient({
        "sql": "SELECT customer_id, completed_txn_count_l1m FROM feature.gsm_transaction ORDER BY customer_id",
        "selected_features": ["completed_txn_count_l1m"],
        "intent": "single_bu",
        "confidence": 0.95,
    })
    response = _pipeline(client.payload).ask("GSM số chuyến tháng gần nhất")
    assert response.status == "ok"
    assert response.result is not None
    assert response.sql and "feature.gsm_transaction" in response.sql


def test_pipeline_refusal_does_not_call_llm():
    client = StaticJSONClient({
        "sql": "SELECT customer_id FROM feature.gsm_transaction",
        "selected_features": ["completed_txn_count_l1m"],
        "intent": "single_bu",
    })
    response = _pipeline(client.payload).ask("Khách nào là owner xe VinFast?")
    assert response.status == "out_of_scope"
    assert client.calls == []


def test_pipeline_clarifies_on_ambiguous_question_without_calling_llm():
    # Câu mơ hồ (điểm retrieval dưới ngưỡng) → hỏi lại, KHÔNG gọi LLM, không "gọi tất cả".
    client = StaticJSONClient({
        "sql": "SELECT customer_id, completed_txn_count_l1m FROM feature.gsm_transaction",
        "selected_features": ["completed_txn_count_l1m"],
        "intent": "single_bu",
    })
    response = _pipeline(client.payload).ask("cho tôi xem dữ liệu khách hàng")
    assert response.status == "clarify"
    assert response.sql is None
    assert client.calls == []


def test_pipeline_rejects_generated_raw_sql():
    client = StaticJSONClient({
        "sql": "SELECT customer_id FROM raw.customers",
        "selected_features": [],
        "intent": "single_bu",
        "confidence": 0.9,
    })
    response = _pipeline(client.payload).ask("GSM customers")
    assert response.status == "error"
    assert "raw" in (response.error or "").lower()


def test_pipeline_rejects_projected_snapshot_date():
    client = StaticJSONClient({
        "sql": "SELECT customer_id, snapshot_date, completed_txn_count_l1m FROM feature.gsm_transaction",
        "selected_features": ["completed_txn_count_l1m"],
        "intent": "single_bu",
    })
    response = _pipeline(client.payload).ask("GSM sá»‘ chuyáº¿n thĂ¡ng gáº§n nháº¥t")
    assert response.status == "error"
    assert "snapshot_date" in (response.error or "")


def test_optional_narrator_returns_validated_text():
    client = StaticJSONClient({"answer_vi": "Tổng hợp đã được kiểm tra."})
    answer = OptionalLLMNarrator(client)(NarrationInput(
        question="GSM", sql="SELECT x FROM feature.gsm_transaction",
        result=QueryResult(columns=["x"], rows=[[1]], row_count=1),
        confidence=0.9,
    ))
    assert answer == "Tổng hợp đã được kiểm tra."


def test_generator_normalizes_string_assumptions_from_llm():
    client = StaticJSONClient({
        "sql": "SELECT completed_txn_count_l1m FROM feature.gsm_transaction",
        "selected_features": "completed_txn_count_l1m",
        "intent": "single_bu",
        "assumptions": "Dùng snapshot mới nhất.",
        "confidence": "0.9",
    })
    from app.agent.contracts import GenerationRequest, RouteDecision, IntentType

    output = SQLGenerator(client).generate(GenerationRequest(
        question="Số chuyến GSM tháng gần nhất",
        route=RouteDecision(intent=IntentType.single_bu, business_unit="GSM", confidence=.8),
        feature_context="completed_txn_count_l1m | feature.gsm_transaction",
    ))
    assert output.selected_features == ["completed_txn_count_l1m"]
    assert output.assumptions == ["Dùng snapshot mới nhất."]
    assert output.confidence == .9


def test_generation_contract_also_coerces_string_lists():
    from app.agent.contracts import GenerationResponse, IntentType

    output = GenerationResponse(
        sql="SELECT x FROM feature.gsm_transaction",
        selected_features="x",
        assumptions="latest snapshot",
        intent=IntentType.single_bu,
    )
    assert output.selected_features == ["x"]
    assert output.assumptions == ["latest snapshot"]


def test_json_parser_accepts_code_fence_and_trailing_text():
    parsed = parse_json_object(
        '```json\n{"sql":"SELECT 1","assumptions":"latest"}\n``` trailing explanation'
    )
    assert parsed["sql"] == "SELECT 1"


def test_retriever_narrows_count_query_to_window_and_count_features():
    import yaml
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    results = layer.retrieve("GSM số chuyến tháng gần nhất")
    assert len(results) <= 8
    assert all("_l1m" in item.name for item in results)
    assert all("count" in item.name or "active_days" in item.name for item in results)


def test_canonical_inventory_has_exact_retained_counts():
    from app.semantic.feature_spec import all_features

    features = all_features()
    assert len(features) == 353
    assert sum(f.table.endswith("gsm_transaction") for f in features) == 167
    assert sum(f.table.endswith("vinfast_transaction") for f in features) == 186


def test_retriever_supports_focused_english_context():
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    results = layer.retrieve(
        "VinFast completed order amount in the last 12 months",
        business_unit="VINFAST",
    )
    assert [item.name for item in results] == ["txn_completed_amount_sum_l12m"]


def test_retriever_keeps_hard_business_aliases_in_top_five():
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    cases = {
        "Top 10 khách GSM lâu nhất chưa quay lại sử dụng dịch vụ trong 12 tháng gần nhất": "days_since_last_txn_l12m",
        "Top 10 khách bắt đầu sử dụng GSM từ lâu nhất trong 12 tháng gần nhất": "days_since_first_txn_l12m",
        "Top 10 khách hoạt động thường xuyên nhất trên GSM trong tháng gần nhất": "completed_txn_active_day_count_l1m",
        "Top 10 khách có nhiều giao dịch VinFast hoàn thành được áp dụng giảm giá nhất trong 12 tháng": "txn_discount_completed_count_l12m",
        "Liệt kê khách có giao dịch VinFast hoàn thành đầu tiên trong vòng 30 ngày gần nhất": "days_since_first_completed_txn_days_l12m",
    }
    for question, expected in cases.items():
        assert expected in {f.name for f in layer.retrieve(question, top_k=5)}


def test_needs_review_features_excluded_from_retrieval():
    from app.semantic.retriever import SemanticLayer

    layer = SemanticLayer.load("data/semantic_layer.yaml")
    # NVSO/WO là needs_review → không được lọt vào retrieval surface, kể cả
    # với câu hỏi chung không nhắc tên (chỉ router mới refuse khi nhắc trực tiếp).
    assert all("nvso" not in f["name"] and "_wo_" not in f["name"] for f in layer.features)
    hits = layer.retrieve("VinFast completed transaction amount last 12 months", business_unit="VINFAST")
    assert all("nvso" not in h.name and "_wo_" not in h.name for h in hits)


def test_yaml_is_queryable_matches_support_status():
    import yaml

    data = yaml.safe_load(open("data/semantic_layer.yaml", encoding="utf-8"))
    for f in data["features"]:
        assert f["is_queryable"] == (f["support_status"] == "queryable"), f["name"]


def test_mock_canceled_features_are_populated():
    # Guard bug spelling: feature "canceled" (1 L) phải map raw "cancelled" (2 L),
    # nếu không mọi canceled_* = 0. Seed cố định nên deterministic.
    import scripts.generate_mock_data as g

    customers, _dates, trips, orders = g.generate_raw()
    gsm, vf = g.build_features(customers, trips, orders)
    assert sum(1 for r in gsm if r.get("canceled_txn_count_l12m")) > 0
    assert sum(1 for r in vf if r.get("txn_canceled_count_l12m")) > 0


def test_mock_multi_snapshot_as_of():
    # Multi-snapshot: mỗi snapshot chỉ tính sự kiện <= ngày đó (as-of). Nếu quên
    # pre-filter, days_since sẽ âm (snapshot - sự kiện tương lai). + genuine null.
    import scripts.generate_mock_data as g

    assert len(g.SNAPSHOTS) >= 2 and g.SNAPSHOTS[-1] == g.SNAPSHOT
    cs, _d, tr, od = g.generate_raw()
    gsm, vf = g.build_features(cs, tr, od, g.SNAPSHOTS[0])  # snapshot cũ nhất
    assert all(r["snapshot_date"] == g.SNAPSHOTS[0] for r in gsm)
    assert all(v is None or v >= 0 for v in (r.get("days_since_last_txn_l12m") for r in gsm))
    null_cust = next(r for r in vf if r["customer_id"] == 8)  # cid%8==0 → không có đơn VF
    assert null_cust.get("completed_order_count_l1m") in (0, None)


def test_migration_0002_inventory_matches_feature_spec():
    # Inventory 353 định nghĩa 2 nơi: feature_spec (→YAML→catalog) và migration
    # 0002 (→cột vật lý). Migration cố ý đóng băng bản riêng (không import app code
    # để replay ổn định), nên test này canh hai bản không drift tên/window.
    import importlib.util
    import pathlib

    from app.semantic.feature_spec import feature_names

    path = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0002_align_retained_feature_inventory.py"
    spec = importlib.util.spec_from_file_location("mig0002", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    migration_cols = set(mod._GSM_FEATURES) | set(mod._VINFAST_FEATURES)
    assert migration_cols == feature_names(), migration_cols ^ feature_names()


def test_db_layer_matches_yaml_projection():
    # Đường runtime (load_from_db) phải chiếu YAML authoritative không lệch field.
    # Bắt lỗi map cột SQL mà test-YAML và test-pipeline (LLM stub) không thấy.
    from app.semantic.retriever import SemanticLayer

    yaml_layer = {f["name"]: f for f in SemanticLayer.load("data/semantic_layer.yaml").features}
    db_features = SemanticLayer.load_from_db().features
    assert {f["name"] for f in db_features} == set(yaml_layer)  # cùng tập queryable
    for f in db_features:
        y = yaml_layer[f["name"]]
        for k in ("table", "group", "window", "aggregation", "dtype", "unit", "description_en"):
            assert f[k] == y[k], (f["name"], k, f[k], y[k])


def test_validator_rejects_legacy_physical_feature():
    from app.agent.contracts import GenerationResponse, IntentType
    from app.agent.validator import PipelineValidator

    result = PipelineValidator().validate(
        GenerationResponse(
            sql="SELECT customer_id, is_vinfast_buyer FROM feature.vinfast_transaction",
            selected_features=["is_vinfast_buyer"],
            intent=IntentType.single_bu,
        ),
        {"is_vinfast_buyer"},
    )
    assert not result.valid
    assert any("canonical" in error.lower() or "legacy" in error.lower() for error in result.errors)


def test_validator_rejects_feature_not_declared_as_selected():
    from app.agent.contracts import GenerationResponse, IntentType
    from app.agent.validator import PipelineValidator

    result = PipelineValidator().validate(
        GenerationResponse(
            sql=("SELECT customer_id, completed_txn_count_l1m, finished_txn_count_l1m "
                 "FROM feature.gsm_transaction ORDER BY customer_id"),
            selected_features=["completed_txn_count_l1m"],
            intent=IntentType.single_bu,
        ),
        {"completed_txn_count_l1m", "finished_txn_count_l1m"},
    )
    assert not result.valid
    assert any("unselected" in error.lower() for error in result.errors)
