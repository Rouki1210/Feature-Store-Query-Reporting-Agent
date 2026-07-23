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
        "sql": "SELECT customer_id, completed_txn_count_l1m FROM feature.gsm_transaction",
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
