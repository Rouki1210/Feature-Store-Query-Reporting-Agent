from __future__ import annotations

import re
import unicodedata

from app.agent.contracts import IntentType, RefusalCode, RouteDecision


def normalize_question(question: str, max_chars: int = 2000) -> tuple[str, str]:
    original = question.strip()
    if not original:
        raise ValueError("Câu hỏi không được để trống.")
    if len(original) > max_chars:
        raise ValueError(f"Câu hỏi vượt quá {max_chars} ký tự.")
    text = unicodedata.normalize("NFC", original)
    return original, " ".join(text.lower().split())


class RuleRouter:
    _cross = ("cross pnl", "liên pnl", "chéo ngành", "chuyển dịch giữa", "earn", "burn", "loyalty", "vinclub")
    _owner = ("owner", "ownership", "sở hữu xe", "đứng tên xe", "chủ xe")
    _raw_pii = ("raw.", "raw data", "raw table", "pii", "số điện thoại", "phone", "email", "cccd", "địa chỉ", "họ tên", "customer name")
    _out_catalog = ("vinhomes", "vinmec", "vinpearl", "vinschool", "vinclub")
    _review = ("nvso", "work order", "work_order", "wo")

    def route(self, question: str, max_chars: int = 2000) -> tuple[str, RouteDecision]:
        original, q = normalize_question(question, max_chars)
        if any(x in q for x in self._cross):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Cross-PnL/loyalty chưa thuộc Sprint 1.",
                refusal_code=RefusalCode.cross_pnl,
            )
        if any(x in q for x in self._owner):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Không được suy diễn vehicle ownership từ order/buyer signal.",
                refusal_code=RefusalCode.vehicle_owner,
            )
        if any(x in q for x in self._raw_pii) or re.search(r"\braw\b", q):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Raw data và PII không thuộc agent-accessible scope.",
                refusal_code=RefusalCode.raw_or_pii,
            )
        if any(x in q for x in self._out_catalog):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.98,
                reason="BU ngoài catalog Sprint 1.",
                refusal_code=RefusalCode.out_of_catalog,
            )
        if any(x in q for x in self._review):
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.9,
                reason="Thuật ngữ cần business xác nhận trước khi truy vấn.",
                refusal_code=RefusalCode.needs_review,
                clarifying_question="Bạn muốn dùng thuật ngữ này theo định nghĩa nghiệp vụ nào?",
            )

        gsm = bool(re.search(r"\b(gsm|xanh sm|taxi|gọi xe|chuyến)\b", q))
        vf = bool(re.search(r"\b(vinfast|vf|xe điện|phụ kiện|đơn xe)\b", q))
        if gsm and vf:
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.82,
                reason="Câu hỏi đồng thời nhắc GSM và VinFast; cần chọn một BU.",
                clarifying_question="Bạn muốn xem riêng GSM hay VinFast?",
            )
        bu = "GSM" if gsm else ("VINFAST" if vf else None)
        if any(x in q for x in ("so sánh", "vs", "versus", "tăng giảm", "kỳ trước")):
            intent = IntentType.window_compare
        elif any(x in q for x in ("theo", "group by", "tổng", "trung bình", "phân bổ", "bao nhiêu")):
            intent = IntentType.aggregate
        elif any(x in q for x in ("lọc", "lớn hơn", "nhỏ hơn", "trên", "dưới", "top")):
            intent = IntentType.filter
        else:
            intent = IntentType.single_bu
        if bu is None and intent == IntentType.single_bu:
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.55,
                reason="Chưa xác định được BU.",
                clarifying_question="Bạn muốn xem dữ liệu GSM hay VinFast?",
            )
        return original, RouteDecision(intent=intent, business_unit=bu, confidence=0.75)
