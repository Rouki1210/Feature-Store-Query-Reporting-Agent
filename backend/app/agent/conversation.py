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
import re
from dataclasses import dataclass

from app.agent.breakdown import BreakdownPlanner, strip_metric_phrases, strip_phrases
from app.agent.router import RuleRouter
from app.config import get_settings
from app.models.schemas import AskResponse


@dataclass
class PendingState:
    # Câu GỐC, không bao giờ nối thêm: mỗi lượt ghép lại từ đây + toàn bộ slot đã
    # biết. Lưu câu đã ghép sẽ làm câu hỏi dài thêm mỗi lượt và lặp "cả hai".
    original_question: str
    expires_at: float
    known_slots: dict[str, str | int] | None = None
    missing_slots: tuple[str, ...] = ()


_STORE: dict[str, PendingState] = {}
_BREAKDOWNS = BreakdownPlanner()
ORDER_STATUS_OPTIONS = ({"value": "Đã hủy", "label": "Đã hủy"},)

# Từ hủy: xóa pending, không chạy query. Không gồm "không" (mơ hồ — "không biết"
# phải giữ pending và hỏi lại, xem spec §13).
_CANCEL = {"huy", "thoi", "bo qua", "dung", "cancel", "stop"}
# Câu trả lời clarify điển hình rất ngắn ("GSM", "3 tháng", "top 10", "cả hai").
# Chỉ dựa vào ĐỘ DÀI: câu dài (dù chứa "VinFast"/"12 tháng") là câu hỏi mới, không
# phải câu trả lời → tránh nối nhầm (spec §11: câu mới thay thế pending).
_SHORT_ANSWER_MAX_TOKENS = 4

# Cửa sổ agent thật sự có (feature_spec.WINDOW_DAYS + ALL_TIME). Danh sách này phải
# khớp với các lựa chọn nêu trong câu hỏi làm rõ — hỏi cái mình không nhận là bẫy user.
_WINDOW_PHRASES: dict[str, str] = {
    "hom nay": "daily", "trong ngay": "daily", "daily": "daily",
    "1 tuan": "l1w", "l1w": "l1w",
    "2 tuan": "l2w", "l2w": "l2w",
    "1 thang": "l1m", "l1m": "l1m", "thang gan nhat": "l1m",
    "3 thang": "l3m", "l3m": "l3m", "quy": "l3m",
    "6 thang": "l6m", "l6m": "l6m", "nua nam": "l6m",
    "12 thang": "l12m", "l12m": "l12m", "1 nam": "l12m", "nam gan nhat": "l12m",
    "tong cong": "all", "toan thoi gian": "all", "tu truoc den nay": "all",
    "luy ke": "all", "all": "all",
}


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


def _answer_slots(message: str) -> dict[str, str | int]:
    """Parse only the small, explicit clarification vocabulary for Sprint 2."""
    text = _normalize(message)
    slots: dict[str, str | int] = {}
    if text in {"gsm", "xanh sm"}:
        slots["business_unit"] = "GSM"
    elif text in {"vf", "vinfast", "vin fast"}:
        slots["business_unit"] = "VINFAST"
    elif text in {"ca hai", "both", "cross bu", "cross-bu"}:
        slots["business_unit"] = "CROSS_BU"
    # Phải phủ ĐỦ cửa sổ có thật trong feature store, nếu không câu trả lời hợp lệ
    # ("6 tháng") bị coi là sai và vòng hỏi-lại không thoát được.
    # Duyệt theo cụm dài trước: "12 thang" phải thắng "2 thang".
    for phrase, window in sorted(_WINDOW_PHRASES.items(), key=lambda kv: -len(kv[0])):
        if phrase in text:
            slots["window"] = window
            break
    match = re.fullmatch(r"top\s+(\d+)", text)
    if match:
        slots["top_n"] = int(match.group(1))
    dimension = _BREAKDOWNS.dimension_from_answer(message)
    if dimension:
        slots["breakdown_dimension"] = dimension
    if text in {"independent", "nhom doc lap", "doc lap"}:
        slots["group_semantics"] = "independent"
    elif text in {"exclusive", "nhom loai tru", "loai tru"}:
        slots["group_semantics"] = "exclusive"
    if text in {
        "so luong khach hang", "tong doanh thu", "so giao dich",
        "customer count", "total revenue", "transaction count",
    }:
        slots["metric"] = message
    # Chỉ nhận lựa chọn thay thế có cùng grain giao dịch. "Đã bàn giao" là vehicle
    # handover của VinFast, không phải trạng thái giao dịch GSM.
    order_status = {
        "da huy": "đã hủy", "huy": "đã hủy", "canceled": "đã hủy",
    }.get(text)
    if order_status:
        slots["order_status"] = order_status
    return slots


def _merged_question(question: str, slots: dict[str, str | int]) -> str:
    if "metric" in slots:
        question = strip_metric_phrases(question)
    if "order_status" in slots:
        # Giữ lại "chưa hoàn thành" thì router lại clarify chính câu vừa được trả lời.
        question = strip_phrases(question, RuleRouter._unfinished_order)
    dimension_phrases = {
        "none": "không chia nhóm",
        "business_unit": "theo business unit",
        "service_type": "theo dịch vụ",
        "customer_state": "theo trạng thái khách hàng",
        "window": "theo cửa sổ thời gian",
        "snapshot_date": "theo snapshot_date",
    }
    semantics = {
        "independent": "nhóm độc lập",
        "exclusive": "nhóm loại trừ",
    }
    values = [
        "cả hai" if name == "business_unit" and slots[name] == "CROSS_BU"
        else f"top {slots[name]}" if name == "top_n"
        else dimension_phrases.get(str(slots[name]), str(slots[name]))
        if name == "breakdown_dimension"
        else semantics.get(str(slots[name]), str(slots[name]))
        if name == "group_semantics"
        else str(slots[name])
        for name in (
            "business_unit", "window", "top_n", "breakdown_dimension",
            "group_semantics", "metric", "order_status",
        ) if name in slots
    ]
    return " ".join([question, *values]).strip()


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

    transition = {"from": "none", "to": "executing", "resolved_slot": None}
    slots: dict[str, str | int] = {}
    base = message
    if pending and _is_short_answer(message):
        parsed = _answer_slots(message)
        expected = set(pending.missing_slots)
        resolved = next((name for name in expected if name in parsed), None)
        if expected and resolved is None:
            return AskResponse(
                status="clarify", session_id=session_id,
                clarifying_question=(
                    "Câu trả lời chưa khớp thông tin cần bổ sung. "
                    "Bạn hãy trả lời: " + ", ".join(sorted(expected)) + "."
                ),
                known_slots=pending.known_slots or {}, missing_slots=sorted(expected),
                clarification_options=list(ORDER_STATUS_OPTIONS) if expected == {"order_status"} else [],
            )
        slots = {**(pending.known_slots or {}), **parsed}
        base = pending.original_question
        effective = _merged_question(base, slots)
        transition = {"from": "pending", "to": "executing", "resolved_slot": resolved}
    else:
        effective = message
        _clear(session_id)  # câu hỏi mới đầy đủ thay thế pending (spec §11)

    resp = pipeline.ask(effective, session_id=session_id, state_transition=transition)
    resp.session_id = session_id

    if resp.status == "clarify":
        ttl = get_settings().conversation_ttl_seconds
        _STORE[session_id] = PendingState(
            base, now + ttl, {**slots, **resp.known_slots}, tuple(resp.missing_slots),
        )
    else:  # ok / out_of_scope / error → câu hỏi đã xong
        _clear(session_id)
    return resp
