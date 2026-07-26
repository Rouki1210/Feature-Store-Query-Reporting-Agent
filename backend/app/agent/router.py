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


def _hit(q: str, terms: tuple[str, ...]) -> bool:
    """Khớp term với word-boundary cho token nguyên tử, substring cho cụm nhiều từ.

    Chặn bug substring: 'earn' ⊄ 'learn', 'burn' ⊄ 'burnout', 'wo' ⊄ 'word',
    'phone' ⊄ 'iphone', 'top' ⊄ 'laptop'. Token nguyên tử đều ASCII nên \\b
    hoạt động; cụm tiếng Việt (có dấu cách) hoặc term có '.' đi đường substring.
    """
    for t in terms:
        if " " in t or "." in t:
            if t in q:
                return True
        elif re.search(rf"\b{re.escape(t)}\b", q):
            return True
    return False


class RuleRouter:
    _cross = ("cross pnl", "liên pnl", "chéo ngành", "chuyển dịch giữa", "earn", "burn", "loyalty", "vinclub")
    _owner = ("owner", "ownership", "sở hữu xe", "đứng tên xe", "chủ xe")
    # 'raw' word-boundary phủ cả raw. / raw data / raw table.
    _raw_pii = ("raw", "pii", "số điện thoại", "phone", "email", "cccd", "địa chỉ", "họ tên", "customer name")
    _out_catalog = ("vinhomes", "vinmec", "vinpearl", "vinschool", "vinclub")
    _review = ("nvso", "work order", "work_order", "wo")
    _cmp = ("so sánh", "vs", "versus", "tăng giảm", "kỳ trước")
    _agg = ("theo", "group by", "tổng", "trung bình", "phân bổ", "bao nhiêu")
    _flt = ("lọc", "lớn hơn", "nhỏ hơn", "trên", "dưới", "top")
    # Danh từ metric/entity của feature store. CỐ Ý không gồm từ thời gian generic
    # ("hôm nay", "tháng") để câu lạc đề như "thời tiết hôm nay" vẫn rớt out_of_scope.
    # ponytail: list keyword — nâng lên dùng retrieval-corpus làm oracle nếu miss nhiều.
    _domain = (
        "chi tiêu", "doanh thu", "số tiền", "giá trị", "số lượng", "tần suất",
        "giảm giá", "discount", "amount", "spend", "revenue", "frequency",
        "chuyến", "gọi xe", "giao hàng", "quãng đường", "cuốc xe", "km",
        "đơn", "đơn hàng", "order", "phụ kiện", "accessories", "pin", "battery",
        "hoàn thành", "completed", "hủy", "canceled", "cancelled",
        "hoạt động", "gắn kết", "active",
        # Vague-nhưng-trong-domain: hỏi "dữ liệu khách hàng" → clarify BU, không loại.
        "khách hàng", "customer", "dữ liệu", "data",
    )

    def route(self, question: str, max_chars: int = 2000) -> tuple[str, RouteDecision]:
        original, q = normalize_question(question, max_chars)
        if _hit(q, self._cross):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Cross-PnL/loyalty chưa thuộc Sprint 1.",
                refusal_code=RefusalCode.cross_pnl,
            )
        if _hit(q, self._owner):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Không được suy diễn vehicle ownership từ order/buyer signal.",
                refusal_code=RefusalCode.vehicle_owner,
            )
        if _hit(q, self._raw_pii):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Raw data và PII không thuộc agent-accessible scope.",
                refusal_code=RefusalCode.raw_or_pii,
            )
        if _hit(q, self._out_catalog):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.98,
                reason="BU ngoài catalog Sprint 1.",
                refusal_code=RefusalCode.out_of_catalog,
            )
        if _hit(q, self._review):
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
        # Lọc câu lạc đề: không BU và không tín hiệu domain → ngoài phạm vi
        # (thay vì hỏi 'GSM hay VinFast?' cho câu chẳng liên quan gì).
        if bu is None and not _hit(q, self._domain):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.7,
                reason="Câu hỏi ngoài phạm vi dữ liệu feature store Sprint 1 (chỉ GSM/VinFast).",
                refusal_code=RefusalCode.irrelevant,
            )
        if _hit(q, self._cmp):
            intent = IntentType.window_compare
        elif _hit(q, self._agg):
            intent = IntentType.aggregate
        elif _hit(q, self._flt):
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
