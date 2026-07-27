"""Multi-turn clarify (short-term conversational state) — lazy v1.

Dùng StaticJSONClient (LLM stub) + AgentPipeline thật (chạm DB retrieval/exec như
các test pipeline khác). Mỗi test clear _STORE để cô lập.
"""
from __future__ import annotations

import time

from app.agent.conversation import PendingState, _STORE, ask_with_context
from app.agent.generator import SQLGenerator
from app.agent.llm_client import StaticJSONClient
from app.agent.pipeline import AgentPipeline

# Câu gốc thiếu BU → router clarify (tránh mọi trigger gsm/vf như "chuyến"/"taxi").
# Nối "GSM" ⇒ retrieve completed_discount_amount_sum_l1m (top hit), stub chọn đúng nó.
AMBIGUOUS = "số giao dịch hoàn thành trong tháng gần nhất"
GSM_PAYLOAD = {
    # ORDER BY customer_id là bắt buộc với list per-customer (validator.py:74) — stub phải
    # sinh SQL hợp lệ, nếu không test state lại đỏ vì lý do chẳng liên quan tới state.
    "sql": (
        "SELECT customer_id, completed_discount_amount_sum_l1m "
        "FROM feature.gsm_transaction ORDER BY customer_id"
    ),
    "selected_features": ["completed_discount_amount_sum_l1m"],
    "intent": "single_bu",
    "confidence": 0.95,
}


def _pipe(payload=None):
    return AgentPipeline(SQLGenerator(StaticJSONClient(payload or GSM_PAYLOAD)))


def setup_function():
    _STORE.clear()


def test_merge_short_answer_resolves_and_clears():
    p = _pipe()
    r1 = ask_with_context(p, "S1", AMBIGUOUS)
    assert r1.status == "clarify" and r1.session_id == "S1"
    assert "S1" in _STORE
    r2 = ask_with_context(p, "S1", "GSM")
    assert r2.status == "ok" and r2.sql
    assert "S1" not in _STORE  # đã resolve → xóa pending


def test_cancel_clears_without_calling_pipeline():
    client = StaticJSONClient(GSM_PAYLOAD)
    p = AgentPipeline(SQLGenerator(client))
    ask_with_context(p, "S1", AMBIGUOUS)  # clarify (router, chưa gọi LLM)
    r = ask_with_context(p, "S1", "hủy")
    assert r.status == "clarify" and "hủy" in (r.clarifying_question or "").lower()
    assert "S1" not in _STORE
    assert client.calls == []  # cancel không chạy pipeline/LLM


def test_new_full_question_replaces_pending():
    p = _pipe()
    ask_with_context(p, "S1", AMBIGUOUS)
    # Câu mới đầy đủ (>4 token) phải THAY THẾ, không nối vào câu cũ (spec §11).
    new_q = "tổng chi tiêu VinFast trong ba tháng gần nhất là bao nhiêu"
    ask_with_context(p, "S1", new_q)
    # Dù turn2 kết thúc thế nào, câu cũ KHÔNG được sống sót trong pending.
    assert "S1" not in _STORE or AMBIGUOUS not in _STORE["S1"].original_question


def test_invalid_answer_keeps_pending():
    p = _pipe()
    ask_with_context(p, "S1", AMBIGUOUS)
    r = ask_with_context(p, "S1", "không biết")  # ngắn, không phải từ hủy
    assert r.status == "clarify"
    assert "S1" in _STORE  # vẫn giữ pending để hỏi lại


def test_expired_pending_treated_as_new():
    p = _pipe()
    _STORE["S1"] = PendingState(AMBIGUOUS, time.time() - 1)  # đã hết hạn
    ask_with_context(p, "S1", "GSM")
    # Không được nối vào câu cũ đã hết hạn.
    assert "S1" not in _STORE or AMBIGUOUS not in _STORE["S1"].original_question


def test_session_isolation():
    p = _pipe()
    ask_with_context(p, "A", AMBIGUOUS)  # A có pending
    original_a = _STORE["A"].original_question
    ask_with_context(p, "B", "GSM")       # B trả lời — không được đụng A
    assert _STORE["A"].original_question == original_a


def test_refusal_applies_on_merged_text():
    # Nối câu trả lời chứa "chủ xe" → refusal owner vẫn kích hoạt trên text đã nối.
    p = _pipe()
    ask_with_context(p, "S1", AMBIGUOUS)
    r = ask_with_context(p, "S1", "chủ xe VinFast")
    assert r.status == "out_of_scope"
    assert "S1" not in _STORE
