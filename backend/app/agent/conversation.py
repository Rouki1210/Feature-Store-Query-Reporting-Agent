"""Short-term conversational state — multi-turn clarify (lazy v1).

Bọc ngoài AgentPipeline (giữ pipeline STATELESS). Khi câu hỏi thiếu thông tin,
pipeline trả `clarify`; ta nhớ câu gốc theo session_id, rồi ở lượt sau nối câu
trả lời ngắn ("GSM", "3 tháng"...) vào câu gốc và chạy lại TOÀN pipeline — router
refusal + guards tự áp dụng trên text đã nối nên an toàn được giữ nguyên.

ponytail: `_STORE` là dict in-memory — mất khi restart, không chia sẻ giữa nhiều
worker (upgrade Redis nếu cần); chưa khóa thread (chấp nhận cho prototype 1 instance).
"""
from __future__ import annotations

import time
import unicodedata
from dataclasses import dataclass

from app.config import get_settings
from app.models.schemas import AskResponse


@dataclass
class PendingState:
    original_question: str
    expires_at: float


_STORE: dict[str, PendingState] = {}

# Từ hủy: xóa pending, không chạy query. Không gồm "không" (mơ hồ — "không biết"
# phải giữ pending và hỏi lại, xem spec §13).
_CANCEL = {"huy", "thoi", "bo qua", "dung", "cancel", "stop"}
# Câu trả lời clarify điển hình rất ngắn ("GSM", "3 tháng", "top 10", "cả hai").
# Chỉ dựa vào ĐỘ DÀI: câu dài (dù chứa "VinFast"/"12 tháng") là câu hỏi mới, không
# phải câu trả lời → tránh nối nhầm (spec §11: câu mới thay thế pending).
_SHORT_ANSWER_MAX_TOKENS = 4


def _normalize(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn").lower().strip()


def _is_cancel(message: str) -> bool:
    return _normalize(message) in _CANCEL


def _is_short_answer(message: str) -> bool:
    return len(_normalize(message).split()) <= _SHORT_ANSWER_MAX_TOKENS


def _clear(session_id: str) -> None:
    _STORE.pop(session_id, None)


def ask_with_context(pipeline, session_id: str, message: str) -> AskResponse:
    """Giải quyết message trong ngữ cảnh pending của session_id, rồi cập nhật state."""
    now = time.time()
    pending = _STORE.get(session_id)
    if pending and pending.expires_at < now:  # hết TTL ⇒ coi như không có
        _clear(session_id)
        pending = None

    if _is_cancel(message):
        _clear(session_id)
        return AskResponse(
            status="clarify", session_id=session_id,
            clarifying_question="Đã hủy câu hỏi. Bạn muốn hỏi gì khác?",
        )

    if pending and _is_short_answer(message):
        effective = f"{pending.original_question} {message}".strip()
    else:
        effective = message
        _clear(session_id)  # câu hỏi mới đầy đủ thay thế pending (spec §11)

    resp = pipeline.ask(effective, session_id=session_id)
    resp.session_id = session_id

    if resp.status == "clarify":
        ttl = get_settings().conversation_ttl_seconds
        _STORE[session_id] = PendingState(effective, now + ttl)
    else:  # ok / out_of_scope / error → câu hỏi đã xong
        _clear(session_id)
    return resp
