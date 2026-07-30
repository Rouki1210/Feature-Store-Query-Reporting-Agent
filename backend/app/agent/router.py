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


# Chỉ liệt kê cửa sổ mà `conversation._answer_slots` thật sự parse được — hỏi một
# lựa chọn rồi từ chối chính câu trả lời đó là cách nhanh nhất để user bỏ cuộc.
_WINDOW_QUESTION = (
    "Bạn muốn xem trong khoảng nào: 1 tuần, 1 tháng, 3 tháng, 6 tháng, 12 tháng, "
    "hay tổng cộng từ trước đến nay?"
)


class RuleRouter:
    _recent_window = ("gần đây", "gan day", "recent", "recently")
    _trend = ("thay đổi", "thay doi", "xu hướng", "xu huong", "trend")
    _loyalty = ("loyalty", "vinclub")
    _window = ("daily", "l1w", "l2w", "l1m", "l2m", "l3m", "l6m", "l12m", "hôm nay", "ngày", "tuần", "tháng", "month", "week")
    _windowed_metric = ("số chuyến", "số đơn", "hoàn thành", "completed", "bị hủy", "canceled", "chi tiêu", "giá trị", "quãng đường", "hoạt động")
    _cross = ("cross pnl", "liên pnl", "chéo ngành", "chuyển dịch giữa", "earn", "burn", "loyalty", "vinclub")
    _owner = (
        "owner", "ownership", "sở hữu xe", "đứng tên xe", "chủ xe",
        "nhận xe", "bàn giao xe",
    )
    _cross_bu = (
        "cả hai", "ca hai", "đồng thời", "dong thoi", "overlap", "khách chung",
        "khach chung", "vừa đi gsm vừa mua vinfast", "vua di gsm vua mua vinfast",
        "theo từng business unit", "từng business unit", "mỗi business unit",
        "by business unit", "each business unit",
    )
    # 'raw' word-boundary phủ cả raw. / raw data / raw table.
    _raw_pii = ("raw", "pii", "số điện thoại", "phone", "email", "cccd", "địa chỉ", "họ tên", "customer name")
    _out_catalog = ("vinhomes", "vinmec", "vinpearl", "vinschool", "vinclub")
    _unsupported = ("trả xe", "hoàn xe", "dự đoán", "du doan", "tháng sau", "thang sau", "forecast")
    _join_request = ("ghép", "ghep", "join")
    _unsafe_join = ("mọi snapshot", "moi snapshot", "bảng khách hàng", "bang khach hang", "ba bảng", "3 bảng")
    _ambiguous_order = ("đặt xe", "dat xe")
    _unfinished_order = ("chưa hoàn tất", "chua hoan tat")
    _review = ("nvso", "work order", "work_order", "wo")
    # Agent read-only: yêu cầu ghi/xóa/DDL, hoặc "trả toàn bộ cột" (SELECT *) → ngoài phạm vi.
    _unsafe = ("xóa", "xoá", "delete", "drop", "truncate", "insert")
    _selectall = ("toàn bộ cột", "tất cả các cột", "tất cả cột", "mọi cột", "select *")
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
        if _hit(q, self._loyalty):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.98,
                reason="Loyalty/VinClub không thuộc catalog Sprint 1.",
                refusal_code=RefusalCode.out_of_catalog,
            )
        if _hit(q, self._cross):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.99,
                reason="Cross-PnL/loyalty chưa thuộc Sprint 1.",
                refusal_code=RefusalCode.cross_pnl,
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
        if _hit(q, self._unsupported) or (_hit(q, self._join_request) and _hit(q, self._unsafe_join)):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.98,
                reason="Yêu cầu này không thuộc feature snapshot hoặc vượt chính sách join an toàn.",
                refusal_code=RefusalCode.irrelevant,
            )
        if _hit(q, self._ambiguous_order) and _hit(q, self._unfinished_order):
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.9,
                reason="Trạng thái đơn xe chưa có định nghĩa feature rõ ràng.",
                clarifying_question="Bạn muốn xem đơn chưa hoàn tất theo trạng thái nghiệp vụ nào?",
            )
        if _hit(q, self._review):
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.9,
                reason="Thuật ngữ cần business xác nhận trước khi truy vấn.",
                refusal_code=RefusalCode.needs_review,
                clarifying_question="Bạn muốn dùng thuật ngữ này theo định nghĩa nghiệp vụ nào?",
            )
        if _hit(q, self._unsafe) or _hit(q, self._selectall):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.95,
                reason="Agent chỉ đọc (read-only): không ghi/xóa dữ liệu và không trả toàn bộ cột (SELECT *).",
            )

        gsm = bool(re.search(r"\b(gsm|xanh sm|taxi|gọi xe|chuyến)\b", q))
        vf = bool(re.search(r"\b(vinfast|vf|xe điện|phụ kiện|đơn xe)\b", q) or _hit(q, self._owner))
        cross_bu = (gsm and vf) or _hit(q, self._cross_bu) or (gsm and _hit(q, self._owner))
        if cross_bu:
            if _hit(q, self._windowed_metric) and not (_hit(q, self._window) or _hit(q, self._recent_window)):
                return original, RouteDecision(
                    intent=IntentType.clarify, business_unit="CROSS_BU", confidence=0.7,
                    reason="Thiếu time window cho metric xuyên đơn vị.",
                    clarifying_question=_WINDOW_QUESTION,
                    known_slots={"business_unit": "CROSS_BU"}, missing_slots=["window"],
                )
            return original, RouteDecision(
                intent=IntentType.cross_bu, business_unit="CROSS_BU", confidence=0.85,
                known_slots={"business_unit": "CROSS_BU"},
            )
        bu = "GSM" if gsm else ("VINFAST" if vf else None)
        # Lọc câu lạc đề: không BU và không tín hiệu domain → ngoài phạm vi
        # (thay vì hỏi 'GSM hay VinFast?' cho câu chẳng liên quan gì).
        if bu is None and not _hit(q, self._domain):
            return original, RouteDecision(
                intent=IntentType.out_of_scope, confidence=0.7,
                reason="Câu hỏi ngoài phạm vi dữ liệu feature store Sprint 2 (chỉ GSM/VinFast).",
                refusal_code=RefusalCode.irrelevant,
            )
        if bu and _hit(q, self._windowed_metric) and not (_hit(q, self._window) or _hit(q, self._recent_window)):
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.7,
                reason="Thiếu time window cho metric dùng feature snapshot.",
                clarifying_question=_WINDOW_QUESTION,
                known_slots={"business_unit": bu}, missing_slots=["window"],
            )
        if _hit(q, self._cmp) or _hit(q, self._trend):
            intent = IntentType.window_compare
        elif _hit(q, self._agg):
            intent = IntentType.aggregate
        elif _hit(q, self._flt):
            intent = IntentType.filter
        else:
            intent = IntentType.single_bu
        # Thiếu BU thì phải hỏi lại BẤT KỂ intent. Trước đây chỉ chặn `single_bu`, nên
        # "Top 10 khách chi tiêu cao nhất 1 tháng" (intent=aggregate/filter) chạy thẳng
        # và trả về số của MỘT đơn vị mà không nói là đơn vị nào — sai im lặng.
        if bu is None:
            return original, RouteDecision(
                intent=IntentType.clarify, confidence=0.55,
                reason="Chưa xác định được BU.",
                clarifying_question="Bạn muốn xem dữ liệu GSM, VinFast, hay cả hai?",
                missing_slots=["business_unit"],
            )
        return original, RouteDecision(
            intent=intent, business_unit=bu, confidence=0.75,
            known_slots={"business_unit": bu} if bu else {},
        )
