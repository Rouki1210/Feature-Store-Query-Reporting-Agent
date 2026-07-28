"""Task 2.6 — slot-based clarification on top of the stateless pipeline."""
from app.agent.conversation import _STORE, ask_with_context
from app.agent.generator import SQLGenerator
from app.agent.llm_client import StaticJSONClient
from app.agent.pipeline import AgentPipeline


PAYLOAD = {
    "sql": "SELECT customer_id, completed_txn_count_l1m FROM feature.gsm_transaction ORDER BY customer_id",
    "selected_features": ["completed_txn_count_l1m"],
    "intent": "single_bu",
}


def setup_function():
    _STORE.clear()


def test_resolves_business_unit_then_window_one_slot_at_a_time():
    pipeline = AgentPipeline(SQLGenerator(StaticJSONClient(PAYLOAD)))
    first = ask_with_context(pipeline, "S1", "số giao dịch hoàn thành")
    assert first.status == "clarify" and "business_unit" in first.missing_slots

    second = ask_with_context(pipeline, "S1", "GSM")
    assert second.status == "clarify" and "window" in second.missing_slots
    assert _STORE["S1"].known_slots["business_unit"] == "GSM"

    final = ask_with_context(pipeline, "S1", "1 tháng")
    assert final.status == "ok"
    assert "S1" not in _STORE


def test_every_offered_window_is_actually_accepted():
    """Câu hỏi làm rõ liệt kê cửa sổ nào thì parser phải nhận đúng cửa sổ đó.

    Trước đây chỉ nhận 1 tuần / 1 tháng / 3 tháng / 12 tháng: user trả lời "6 tháng"
    bị coi là sai và vòng hỏi-lại không thoát được.
    """
    from app.agent.conversation import _answer_slots
    from app.agent.router import _WINDOW_QUESTION

    for phrase, expected in (
        ("1 tuần", "l1w"), ("1 tháng", "l1m"), ("3 tháng", "l3m"),
        ("6 tháng", "l6m"), ("12 tháng", "l12m"), ("tổng cộng", "all"),
    ):
        assert _answer_slots(phrase) == {"window": expected}, phrase
        assert phrase in _WINDOW_QUESTION or expected == "all"


def test_clarify_does_not_reask_a_slot_already_known():
    pipeline = AgentPipeline(SQLGenerator(StaticJSONClient(PAYLOAD)))
    first = ask_with_context(pipeline, "S2", "số giao dịch hoàn thành")
    assert first.missing_slots == ["business_unit"]
    second = ask_with_context(pipeline, "S2", "GSM")
    assert "business_unit" not in second.missing_slots
    assert second.known_slots.get("business_unit") == "GSM"


def test_cross_bu_waits_for_a_window_before_execution():
    pipeline = AgentPipeline(SQLGenerator(StaticJSONClient(PAYLOAD)))
    response = ask_with_context(pipeline, "S1", "khách hoạt động cả GSM và VinFast")
    assert response.status == "clarify"
    assert response.known_slots["business_unit"] == "CROSS_BU"
    assert response.missing_slots == ["window"]
