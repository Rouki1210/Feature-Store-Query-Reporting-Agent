from __future__ import annotations

from app.agent.generator import SQLGenerator
from app.agent.llm_client import StaticJSONClient, parse_json_object
from app.agent.narrator import OptionalLLMNarrator
from app.agent.contracts import NarrationInput
from app.models.schemas import QueryResult
from app.agent.pipeline import AgentPipeline
from app.agent.join_planner import JoinPlanner
from app.agent.router import RuleRouter, normalize_question


def _pipeline(payload):
    return AgentPipeline(SQLGenerator(StaticJSONClient(payload)))


def test_normalize_rejects_empty_and_preserves_text():
    original, normalized = normalize_question("  GSM   trips  ")
    assert original == "GSM   trips"
    assert normalized == "gsm trips"


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


def test_pipeline_allows_owner_feature_query():
    client = StaticJSONClient({
        "sql": (
            "SELECT customer_id, is_vehicle_owner FROM feature.vinfast_transaction "
            "WHERE is_vehicle_owner ORDER BY customer_id"
        ),
        "selected_features": ["is_vehicle_owner"],
        "intent": "single_bu",
    })
    response = AgentPipeline(SQLGenerator(client)).ask("Khách nào là owner xe VinFast?")
    assert response.status == "ok"
    assert client.calls


def test_pipeline_runs_cross_bu_from_precomputed_table():
    client = StaticJSONClient({
        "sql": (
            "SELECT COUNT(is_cross_bu_active_l1m) AS customer_count "
            "FROM feature.customer_cross_bu_feature"
        ),
        "selected_features": ["is_cross_bu_active_l1m"],
        "intent": "cross_bu",
    })
    pipeline = AgentPipeline(SQLGenerator(client), join_planner=JoinPlanner())
    response = pipeline.ask("Bao nhiêu khách hoạt động GSM và đồng thời có đơn VinFast l1m?")
    assert response.status == "ok"
    assert response.join_explanation and "tính sẵn" in response.join_explanation
    assert "feature.customer_cross_bu_feature" in (response.sql or "")


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


def test_pipeline_executes_catalog_backed_runtime_join():
    from app.agent.contracts import IntentType, RouteDecision
    from app.semantic.retriever import ScoredFeature

    class CrossRouter:
        def route(self, question, _max_chars):
            return question, RouteDecision(intent=IntentType.cross_bu, business_unit="CROSS_BU", confidence=1)

    class RuntimeJoinLayer:
        def retrieve(self, _question, business_unit=None):
            assert business_unit == "CROSS_BU"
            return [
                ScoredFeature("completed_txn_count_l1m", "feature.gsm_transaction", "usage", "", "", [], 5),
                ScoredFeature("txn_completed_count_l1m", "feature.vinfast_transaction", "usage", "", "", [], 5),
            ]

    client = StaticJSONClient({
        "sql": "SELECT g.customer_id, g.completed_txn_count_l1m, v.txn_completed_count_l1m "
               "FROM feature.gsm_transaction g INNER JOIN feature.vinfast_transaction v "
               "ON g.customer_id = v.customer_id AND g.snapshot_date = v.snapshot_date ORDER BY g.customer_id",
        "selected_features": ["completed_txn_count_l1m", "txn_completed_count_l1m"],
        "intent": "cross_bu", "confidence": .9,
    })
    response = AgentPipeline(
        SQLGenerator(client), router=CrossRouter(), semantic_layer=RuntimeJoinLayer(), join_planner=JoinPlanner(),
    ).ask("compare GSM and VinFast")
    assert response.status == "ok"
    assert "INNER JOIN" in (response.sql or "").upper()


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
    assert len(features) == 406  # 353 Sprint 1 + 16 buyer/owner PIT + 37 cross-BU
    assert sum(f.table.endswith("gsm_transaction") for f in features) == 167
    assert sum(f.table.endswith("vinfast_transaction") for f in features) == 202
    assert sum(f.table.endswith("customer_cross_bu_feature") for f in features) == 37


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

    customers, _dates, trips, orders, *_events = g.generate_raw()
    gsm, vf = g.build_features(customers, trips, orders)
    assert sum(1 for r in gsm if r.get("canceled_txn_count_l12m")) > 0
    assert sum(1 for r in vf if r.get("txn_canceled_count_l12m")) > 0


def test_mock_multi_snapshot_as_of():
    # Multi-snapshot: mỗi snapshot chỉ tính sự kiện <= ngày đó (as-of). Nếu quên
    # pre-filter, days_since sẽ âm (snapshot - sự kiện tương lai). + genuine null.
    import scripts.generate_mock_data as g

    assert len(g.SNAPSHOTS) >= 2 and g.SNAPSHOTS[-1] == g.SNAPSHOT
    cs, _d, tr, od, hist, hand = g.generate_raw()
    gsm, vf = g.build_features(cs, tr, od, g.SNAPSHOTS[0], hist, hand)  # snapshot cũ nhất
    assert all(r["snapshot_date"] == g.SNAPSHOTS[0] for r in gsm)
    assert all(v is None or v >= 0 for v in (r.get("days_since_last_txn_l12m") for r in gsm))
    null_cust = next(r for r in vf if r["customer_id"] == 8)  # cid%8==0 → không có đơn VF
    assert null_cust.get("completed_order_count_l1m") in (0, None)


def test_migration_inventory_matches_feature_spec():
    # Inventory định nghĩa 2 nơi: feature_spec (→YAML→catalog) và migration (→cột
    # vật lý). Migration cố ý đóng băng bản riêng (không import app code để replay
    # ổn định), nên test này canh hai bản không drift tên/window.
    # 0002 = 353 feature Sprint 1; 0004 = buyer/owner PIT; 0005 = bảng cross-BU (DDL
    # nguyên khối); 0008 = mở rộng cửa sổ l3m/l6m/l12m/all + handover scheduled.
    import importlib.util
    import pathlib

    from app.semantic.feature_spec import feature_names

    versions = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"

    def load(name):
        spec = importlib.util.spec_from_file_location(name, versions / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    sprint1 = load("0002_align_retained_feature_inventory")
    pit = load("0004_extend_vinfast_transaction_pit")
    windows = load("0008_expand_sprint2_feature_windows")
    # 0005 tạo bảng bằng DDL nguyên khối — lấy tên cột từ chính SQL đó.
    cross_sql = (versions / "0005_create_customer_cross_bu_feature.py").read_text(encoding="utf-8")
    cross_cols = {
        name for name in feature_names()
        if name.startswith(("is_active_", "is_cross_bu_", "gsm_spend", "vinfast_spend",
                            "combined_spend", "dominant_business_unit",
                            "cross_bu_engagement_score", "gsm_active_vehicle_owner_flag"))
    }
    from_0008 = set(windows._CROSS_COLUMNS) | set(windows._VF_COLUMNS)
    missing = [c for c in cross_cols - from_0008 if c not in cross_sql]
    assert not missing, f"0005 thiếu cột: {missing}"

    migration_cols = (
        set(sprint1._GSM_FEATURES) | set(sprint1._VINFAST_FEATURES)
        | set(pit._PIT_COLUMNS) | cross_cols | from_0008
    )
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
        for k in ("table", "business_unit", "group", "window", "aggregation", "dtype",
                  "unit", "description_en"):
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
