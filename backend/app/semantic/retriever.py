
"""Deterministic bilingual semantic retriever for the canonical inventory."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

_TABLE_HINTS = {
    "gsm_transaction": (
        "gsm", "xanh sm", "taxi", "gọi xe", "giao hàng", "chuyến", "ride",
        "ride hailing", "trip", "delivery",
    ),
    "vinfast_transaction": (
        "vinfast", "vf", "ô tô", "oto", "xe điện", "phụ kiện", "đơn xe",
        "ev", "electric vehicle", "car", "scooter", "accessories", "order",
    ),
    # Cross-BU: chỉ khớp khi câu hỏi thật sự nói tới CẢ HAI đơn vị. Không đưa "gsm"
    # hay "vinfast" đơn lẻ vào đây, nếu không câu single-BU nào cũng bị cộng điểm.
    "customer_cross_bu_feature": (
        "cả hai", "ca hai", "đồng thời", "dong thoi", "vừa", "vua ",
        "cross bu", "cross-bu", "xuyên đơn vị", "xuyen don vi", "overlap",
        "khách chung", "khach chung", "both",
    ),
}

# "30 ngày gần nhất", "7 ngày qua", "90 ngay" — cách nói phổ biến nhất mà bảng alias
# cố định không phủ nổi. Chỉ nhận khi con số RẤT GẦN một cửa sổ có thật (±10%): đủ rộng
# cho mọi cách nói một cửa sổ ĐANG CÓ (7/14/30/90/180/365 ngày, 4 tuần ≈ 1 tháng,
# 12 tuần ≈ 3 tháng) nhưng từ chối cái mơ hồ — "5 tháng" (150 ngày) lệch l6m 20%, "60
# ngày" nằm giữa l1m và l3m. Thà hỏi lại còn hơn tự làm tròn rồi trả sai kỳ.
_WINDOW_TOLERANCE = 0.1
_WINDOW_DAYS = {"daily": 1, "l1w": 7, "l2w": 14, "l1m": 30, "l3m": 90, "l6m": 180, "l12m": 365}
_UNIT_DAYS = {
    "ngay": 1, "tuan": 7, "thang": 30, "nam": 365,
    "day": 1, "week": 7, "month": 30, "year": 365,
}
# Cả hai ngôn ngữ: "30 ngày" và "last 30 days" phải cho cùng kết quả. Số nhiều tiếng
# Anh gộp bằng `s?` để không phải liệt kê hai lần.
_NUMERIC_WINDOW = re.compile(r"(\d+)\s*(ngay|tuan|thang|nam|days?|weeks?|months?|years?)\b")
# Alias đứng NGAY SAU một con số là mảnh của cụm có số, không phải cửa sổ riêng:
# "5 tháng gần nhất" chứa alias "tháng gần nhất" (l1m) nhưng nghĩa là 5 tháng, không
# phải 1 tháng. Chỉ áp cho alias — hit numeric vốn bắt đầu bằng chính con số đó.
_DIGIT_BEFORE = re.compile(r"\d+\s*$")
# Với chỉ số "tuổi" (days_since_*), con số ngày là NGƯỠNG trên giá trị cột, KHÔNG phải
# cửa sổ feature. Golden H10: "giao dịch hoàn thành ĐẦU TIÊN trong vòng 30 ngày" phải ra
# `days_since_first_completed_txn_days_l12m <= 30` — khách mới. Nếu đọc "30 ngày" thành
# cửa sổ l1m thì được `..._l1m`, cột này ≤30 với BẤT KỲ ai có giao dịch tháng qua, tức
# mất hẳn nghĩa "khách mới".
_AGE_METRIC = (
    "dau tien", "lan dau", "chua quay lai", "chua tro lai", "bao lau", "lau nhat",
    "ke tu", "days since", "khach moi",
)


def _numeric_windows(q_norm: str) -> list[tuple[int, int, str]]:
    """(vị trí, độ dài, cửa sổ) cho mỗi cụm `N ngày|tuần|tháng|năm` (VI hoặc EN)."""
    if any(term in q_norm for term in _AGE_METRIC):
        return []
    hits: list[tuple[int, int, str]] = []
    for match in _NUMERIC_WINDOW.finditer(q_norm):
        days = int(match.group(1)) * _UNIT_DAYS[match.group(2).rstrip("s")]
        window = min(_WINDOW_DAYS, key=lambda name: abs(_WINDOW_DAYS[name] - days))
        if abs(_WINDOW_DAYS[window] - days) <= _WINDOW_TOLERANCE * days:
            hits.append((match.start(), match.end() - match.start(), window))
    return hits


def has_time_reference(q_norm: str) -> bool:
    """Router có đủ mốc thời gian để chạy, hay phải hỏi lại?

    Đủ trong ĐÚNG hai trường hợp:
      1. Phân giải được về một cửa sổ có thật ("30 ngày" → l1m).
      2. Con số là NGƯỠNG trên chỉ số tuổi ("đầu tiên trong vòng 30 ngày" → golden H10
         dùng `..._l12m <= 30`), lúc đó không cần cửa sổ nào.

    KHÔNG đủ khi con số không khớp cửa sổ nào: "8 tuần" (56 ngày) nằm giữa l1m và l3m,
    "60 ngày" cũng vậy. Nhận những câu đó là "đã có mốc" thì router bỏ qua clarify, và
    retrieval không có hint sẽ mặc định lấy cột rộng nhất — user hỏi 8 tuần, agent trả
    luỹ kế mà không báo. Đó đúng là bug ban đầu, chỉ đổi đường vào.
    """
    if SemanticLayer._window_hints(q_norm):
        return True
    return bool(_NUMERIC_WINDOW.search(q_norm)) and any(
        term in q_norm for term in _AGE_METRIC
    )


# CHỈ những cửa sổ CÓ THẬT trong inventory (daily/l1w/l2w/l1m/l3m/l6m/l12m/all).
# `l4w`, `l2m`, `l8w` từng có ở đây nhưng KHÔNG feature nào dùng chúng, nên chúng chỉ
# sinh hint rỗng: "4 tuần" ra `l4w` rồi bị lọc sạch. Số ngày tương đương do
# `_numeric_windows` quy về cửa sổ thật (4 tuần ≈ 28 ngày → l1m).
_WINDOW_ALIASES = {
    "daily": ("daily", "hôm nay", "hom nay", "trong ngày", "today"),
    "l1w": ("l1w", "1 tuần", "1 tuan", "tuần gần nhất", "last 1 week", "last week"),
    "l2w": ("l2w", "2 tuần", "2 tuan", "last 2 weeks"),
    "l1m": (
        "l1m", "1 tháng", "1 thang", "tháng gần nhất", "tháng trước", "thang truoc",
        "last 1 month", "last month",
    ),
    "l3m": ("l3m", "3 tháng", "3 thang", "last 3 months"),
    "l6m": ("l6m", "6 tháng", "6 thang", "last 6 months"),
    "l12m": ("l12m", "12 tháng", "12 thang", "last 12 months"),
    # Luỹ kế: "tổng cộng bao nhiêu xe đã bàn giao" phải ra cột _all, không phải _l1m.
    "all": (
        "toàn thời gian", "toan thoi gian", "tổng cộng", "tong cong", "luỹ kế", "luy ke",
        "từ trước đến nay", "tu truoc den nay", "từ trước tới nay", "tu truoc toi nay",
        "all time", "cumulative", "tất cả các kỳ", "tat ca cac ky",
    ),
}

# Feature MANG NGỮ NGHĨA HẸP HƠN câu hỏi thì phải bị phạt: "số đơn VinFast hoàn thành"
# là mọi đơn, không phải riêng đơn mua xe / phụ kiện / có giảm giá. Không phạt thì các
# cột hẹp thắng nhờ trùng token, và agent trả lời một tập con mà người hỏi không hề biết.
# Mỗi dòng: (mảnh trong TÊN cột, những từ trong CÂU HỎI cho phép mảnh đó xuất hiện).
_NARROWING: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("vehicle", ("xe", "vehicle", "car", "oto", "o to", "chu xe", "ban giao")),
    ("accessories", ("phu kien", "accessories")),
    ("discount", ("giam gia", "chiet khau", "discount")),
    ("battery", ("pin", "battery")),
    ("type_taxi", ("taxi",)),
    ("type_bike", ("xe may", "bike")),
    ("type_express", ("giao nhanh", "express")),
    ("type_food", ("do an", "food")),
    ("_wo_", ("work order", "work_order", "wo")),
    ("nvso", ("nvso",)),
)
# Đủ lớn để lật thứ hạng khi các cột chỉ hơn nhau ~0.5 điểm trùng token, nhưng vẫn
# để cột hẹp nằm trong top-k (giảm điểm, không loại) phòng khi retrieval hiểu sai.
_NARROWING_PENALTY = 3.0

_RISK_TERMS = {
    "nvso", "work order", "work_order", "wo", "owner", "ownership",
    "chủ sở hữu", "sở hữu", "buyer", "người mua", "completed order",
    "đơn hoàn thành",
}


def _strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9_]+", _strip_accents(text)) if len(t) >= 2}


# Phủ định phải ĐẢO filter trạng thái, không phải chỉ bỏ qua nó. "Số đơn VinFast CHƯA
# hoàn thành" mà vẫn đòi tên chứa "completed" thì agent trả về đúng cái ngược lại với
# câu hỏi — kiểu sai tệ nhất, vì con số trông hoàn toàn hợp lý và user không có cách nào
# nhận ra ngoài việc đọc SQL.
_NEGATION_CUES = frozenset({"chua", "khong", "chang", "chua he", "not", "non", "never"})
_NEGATION_LOOKBEHIND = 24
# Nhóm token tên cột đi cùng nhau: phủ định "hoàn thành" phải loại cả `finished`.
_STATUS_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("completed", "finished"), ("completed", "finished", "hoan thanh", "hoan tat")),
    (("canceled",), ("canceled", "cancelled", "cancel", "huy")),
    (("delivered",), ("delivered", "ban giao", "nhan xe")),
)


def _is_negated(q_norm: str, term: str) -> bool:
    """`term` có đứng ngay sau một từ phủ định không?"""
    start = q_norm.find(term)
    while start != -1:
        prefix = q_norm[max(0, start - _NEGATION_LOOKBEHIND):start].split()
        if set(prefix[-2:]) & _NEGATION_CUES:
            return True
        start = q_norm.find(term, start + 1)
    return False


# Câu trả lời clarify về trạng thái phải RÀNG BUỘC vào token tên cột. Nối prose vào câu
# hỏi là không đủ: "... đã bàn giao" thêm vào "Số đơn VinFast trong 1 tháng" vẫn để
# `txn_completed_count_l1m` thắng bằng keyword — trả sai metric ngay sau khi user vừa
# chọn đúng trạng thái.
_REQUIRED_STATUS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("ban giao", "nhan xe", "delivered"), ("delivered", "handover")),
)


def _required_status_tokens(q_norm: str) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tokens
        for terms, tokens in _REQUIRED_STATUS
        if any(term in q_norm and not _is_negated(q_norm, term) for term in terms)
    )


def _negated_status_tokens(q_norm: str) -> frozenset[str]:
    """Token tên cột bị phủ định ⇒ feature chứa chúng phải bị LOẠI, không phải ưu tiên."""
    return frozenset(
        token
        for tokens, terms in _STATUS_GROUPS
        if any(_is_negated(q_norm, term) for term in terms)
        for token in tokens
    )


_WINDOW_SUFFIX = re.compile(r"_(daily|l1w|l2w|l4w|l1m|l2m|l3m|l6m|l8w|l12m|all)$")


def _stem_of(name: str) -> str:
    return _WINDOW_SUFFIX.sub("", name)


# Câu hỏi không nêu kỳ ⇒ hỏi về trạng thái tổng thể của khách, không phải hôm nay.
# Nên đại diện của mỗi stem là cửa sổ RỘNG NHẤT có thật; `daily` gần như không bao giờ
# là ý người hỏi. Không có bảng này thì đại diện rơi vào cửa sổ đầu bảng chữ cái
# ("daily") và câu "khách lâu nhất chưa giao dịch" trả về số của đúng một ngày.
_WINDOW_PREFERENCE = ("all", "l12m", "l6m", "l3m", "l1m", "l2w", "l1w", "l4w", "l2m", "l8w", "daily")


def _window_rank(name: str) -> int:
    match = _WINDOW_SUFFIX.search(name)
    window = match.group(1) if match else None
    return _WINDOW_PREFERENCE.index(window) if window in _WINDOW_PREFERENCE else len(_WINDOW_PREFERENCE)


def _one_window_per_stem(scored: list["ScoredFeature"]) -> list["ScoredFeature"]:
    """Câu hỏi không nêu cửa sổ ⇒ mỗi stem chỉ giữ MỘT đại diện trong top-k.

    Mỗi stem có tới 5-8 cửa sổ; khi câu hỏi không nêu cửa sổ nào thì chúng điểm bằng
    nhau và chiếm trọn top-k — context 8 dòng nhưng chỉ nói về 2 khái niệm, còn cột
    đúng thì rơi ra ngoài. Giữ một đại diện mỗi stem trước, phần dư xếp sau để LLM
    vẫn đổi được cửa sổ nếu cần.
    """
    by_stem: dict[str, list[ScoredFeature]] = {}
    for item in scored:                      # scored đã sắp giảm dần theo điểm
        by_stem.setdefault(_stem_of(item.name), []).append(item)
    best: list[ScoredFeature] = []
    rest: list[ScoredFeature] = []
    for group in by_stem.values():
        top_score = group[0].score
        tied = [item for item in group if item.score == top_score]
        chosen = min(tied, key=lambda item: _window_rank(item.name))
        best.append(chosen)
        rest.extend(item for item in group if item is not chosen)
    best.sort(key=lambda item: (-item.score, item.name))
    return best + rest


def _unrequested_narrowing(name_norm: str, q_norm: str) -> int:
    """Đếm số mảnh thu hẹp có trong TÊN cột mà câu hỏi không hề nhắc tới."""
    return sum(
        1 for fragment, terms in _NARROWING
        if fragment in name_norm and not _has_term(q_norm, terms)
    )


def _has_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(
        re.search(
            rf"(?<![a-z0-9_]){re.escape(_strip_accents(term))}(?![a-z0-9_])",
            text,
        )
        for term in terms
    )


@dataclass
class ScoredFeature:
    name: str
    table: str
    group: str
    description_vi: str
    description_en: str
    keywords: list[str]
    score: float
    support_status: str = "queryable"
    dtype: str | None = None
    unit: str | None = None
    null_meaning: str | None = None
    business_unit: str | None = None


class SemanticLayer:
    def __init__(self, features: list[dict]):
        self.features = [
            f for f in features
            if f.get("is_active", True) and f.get("is_queryable", True)
        ]
        self._norm: list[tuple[dict, str, set[str]]] = []
        for f in self.features:
            searchable = " ".join(
                [
                    f.get("name", ""),
                    f.get("group", ""),
                    f.get("description_vi", ""),
                    f.get("description_en", ""),
                    " ".join(f.get("keywords", [])),
                ]
            )
            self._norm.append((f, _strip_accents(searchable), _tokens(searchable)))

    @classmethod
    def load(cls, path: str) -> "SemanticLayer":
        import yaml

        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(data.get("features", []))

    @classmethod
    def load_from_db(cls) -> "SemanticLayer":
        """Đọc catalog (seed từ YAML authoritative) — nguồn runtime của agent."""
        from sqlalchemy import text

        from app.db import get_engine

        sql = text("""
            SELECT fc.feature_name, fc.table_schema, fc.table_name, fc.business_unit,
                   fc.feature_group,
                   fc.description_vi, fc.description_en, fc.data_type, fc.aggregation_type,
                   fc.time_window, fc.unit, fc.null_meaning,
                   COALESCE(array_agg(fs.synonym_text)
                            FILTER (WHERE fs.synonym_text IS NOT NULL), '{}') AS keywords
            FROM metadata.feature_catalog fc
            LEFT JOIN metadata.feature_synonyms fs
              ON fs.feature_id = fc.feature_id AND fs.is_active
            WHERE fc.table_schema = 'feature' AND fc.is_active AND fc.is_queryable
            GROUP BY fc.feature_id
        """)
        with get_engine().connect() as conn:
            rows = conn.execute(sql).mappings().all()
        features = [{
            "name": r["feature_name"],
            "table": f'{r["table_schema"]}.{r["table_name"]}',
            "business_unit": r["business_unit"],
            "group": r["feature_group"],
            "description_vi": r["description_vi"] or "",
            "description_en": r["description_en"] or "",
            "dtype": r["data_type"],
            "aggregation": r["aggregation_type"],
            "window": r["time_window"],
            "unit": r["unit"],
            "null_meaning": r["null_meaning"],
            "keywords": list(r["keywords"]),
            "support_status": "queryable",  # WHERE is_queryable đã loại NVSO/WO
        } for r in rows]
        return cls(features)

    def __len__(self) -> int:
        return len(self.features)

    def is_cross_pnl(self, question: str) -> bool:
        q = _strip_accents(question)
        return any(
            term in q
            for term in (
                "cross pnl", "cross-pnl", "lien pnl", "cheo nganh", "earn",
                "burn", "tich diem", "tieu diem", "redeem", "loyalty",
            )
        )

    @staticmethod
    def _table_scores(q_norm: str) -> dict[str, float]:
        return {
            table: sum(1.0 for hint in hints if _strip_accents(hint) in q_norm)
            for table, hints in _TABLE_HINTS.items()
        }

    @staticmethod
    def _window_hint(q_norm: str) -> str | None:
        matches = SemanticLayer._window_hints(q_norm)
        return matches[0] if matches else None

    @staticmethod
    def _window_hints(q_norm: str) -> list[str]:
        """Các cửa sổ user nêu, theo thứ tự xuất hiện.

        MỘT cụm chỉ được nêu MỘT cửa sổ. Trước đây "4 tuần gần nhất" sinh ba hint
        chồng nhau — `l4w` ("4 tuan"), `l1w` ("tuan gan nhat") và `l1m` (28 ngày ≈ 30)
        — rồi `matches.sort()` chọn theo thứ tự chữ cái, nên cửa sổ thắng là chuyện
        may rủi và `ratio_window` ghép ra cặp không tồn tại ("l1m_vs_l4w").
        """
        spans: list[tuple[int, int, str]] = [
            (start, len(needle), window)
            for window, aliases in _WINDOW_ALIASES.items()
            for needle in {_strip_accents(alias) for alias in aliases}
            if (start := q_norm.find(needle)) != -1
            and not _DIGIT_BEFORE.search(q_norm[:start])
        ]
        spans.extend(_numeric_windows(q_norm))
        if not spans and any(alias in q_norm for alias in ("gan day", "recent", "recently")):
            return ["l1m"]
        # Cụm dài nhất bắt đầu sớm nhất thắng; mọi cụm chồng lấn phía sau bị bỏ.
        spans.sort(key=lambda span: (span[0], -span[1]))
        hints: list[str] = []
        consumed = -1
        for start, length, window in spans:
            if start < consumed:
                continue
            consumed = start + length
            if window not in hints:
                hints.append(window)
        return hints

    @staticmethod
    def _metric_hint(q_norm: str) -> str | None:
        if _has_term(q_norm, ("ty le", "ratio", "rate", "trend", "xu huong", "thay doi", "so sanh", "compare")):
            return "ratio"
        if _has_term(q_norm, ("tong tien", "chi tieu", "doanh thu", "amount", "spend", "value", "price", "gia", "quang duong", "distance", "km")):
            return "value"
        if _has_term(
            q_norm,
            (
                "so chuyen", "so don", "so giao dich", "so luong giao dich", "bao nhieu", "count", "frequency",
                "number of", "trip", "trips", "order", "orders",
            ),
        ):
            return "count"
        return None

    @staticmethod
    def _is_compare(q_norm: str) -> bool:
        return _has_term(
            q_norm, ("so sanh", "compare", "versus", "vs", "tang giam", "thay doi", "xu huong", "trend")
        )

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        *,
        business_unit: str | None = None,
        group: str | None = None,
    ) -> list[ScoredFeature]:
        if top_k is None:
            from app.config import get_settings

            top_k = get_settings().retrieval_top_k
        q_norm = _strip_accents(question)
        q_tokens = _tokens(question)
        table_scores = self._table_scores(q_norm)
        window_hints = self._window_hints(q_norm)
        window_hint = window_hints[0] if window_hints else None
        metric_hint = self._metric_hint(q_norm)
        compare = self._is_compare(q_norm)
        value_requested = _has_term(
            q_norm,
            (
                "tong tien", "chi tieu", "doanh thu", "amount", "spend",
                "value", "price", "gia", "quang duong", "distance", "km",
            ),
        )
        discount_requested = _has_term(q_norm, ("discount", "chiet khau", "giam gia"))
        negated_status = _negated_status_tokens(q_norm)
        required_status = _required_status_tokens(q_norm)
        # "So sánh đơn xe hoàn tất với khách đã nhận xe" cần cả buyer lẫn owner.
        # Ép vế "đã nhận xe" lên mọi feature sẽ làm buyer biến mất trước khi xếp hạng.
        if self._is_compare(q_norm) and _has_term(
            q_norm, ("completed", "finished", "hoan thanh", "hoan tat")
        ):
            required_status = ()
        count_requested = not value_requested and _has_term(
            q_norm,
            (
                "so chuyen", "so don", "so giao dich", "so luong giao dich", "bao nhieu", "count", "frequency",
                "number of", "trip", "trips", "order", "orders",
            ),
        )
        ratio_window = (
            f"{window_hints[0]}_vs_{window_hints[1]}"
            if compare and len(window_hints) >= 2
            else ("l1m_vs_l3m" if compare and window_hint == "l1m" else None)
        )
        unit = business_unit.upper() if business_unit else None
        if unit == "CROSS_BU":
            # "So sánh chi tiêu GSM 1 tháng với VinFast 3 tháng" là so HAI ĐƠN VỊ, không
            # phải so hai cửa sổ của cùng một chỉ số. Bảng cross-BU không có cột ratio
            # nào (0/37), nên ép ratio_window/metric_hint=ratio sẽ lọc sạch và agent
            # báo "câu hỏi chưa đủ rõ" cho một câu rất rõ.
            ratio_window = None
            if metric_hint == "ratio":
                metric_hint = None
        cross_both_requested = unit == "CROSS_BU" and _has_term(
            q_norm,
            (
                "ca hai", "ca gsm va vinfast", "dong thoi", "dung ca",
                "khach dung ca", "cross bu", "cross-bu", "overlap", "both",
            ),
        )
        per_bu_breakdown = unit == "CROSS_BU" and _has_term(
            q_norm,
            (
                "theo tung business unit", "tung business unit", "moi business unit",
                "by business unit", "each business unit",
            ),
        )

        scored: list[ScoredFeature] = []
        for f, searchable, feature_tokens in self._norm:
            table = f.get("table", "").split(".", 1)[-1]
            # So theo nhãn business_unit của feature, KHÔNG theo tiền tố tên bảng:
            # tiền tố chỉ tình cờ đúng với gsm_/vinfast_ và trượt hẳn với CROSS_BU
            # (bảng tên customer_cross_bu_feature).
            if unit and (f.get("business_unit") or "").upper() != unit:
                continue
            if group and f.get("group") != group:
                continue
            feature_window = f.get("window")
            if window_hint and not compare and feature_window not in (window_hint, None):
                continue
            if ratio_window and feature_window != ratio_window:
                continue
            # Trạng thái user nêu rõ (kể cả khi vừa chọn qua chip clarify) là ràng buộc
            # CỨNG: áp cho cả cờ boolean, vì "đã bàn giao" mà trả `is_vehicle_buyer` thì
            # cũng sai như trả `txn_completed_count`.
            allows_owner_for_handover = (
                f.get("name") == "is_vehicle_owner"
                and any("delivered" in tokens or "handover" in tokens for tokens in required_status)
            )
            if not allows_owner_for_handover and any(
                not any(token in f.get("name", "") for token in tokens)
                for tokens in required_status
            ):
                continue
            # Cờ boolean (is_vehicle_owner, is_cross_bu_active…) và cột cross-BU không
            # mang token count/completed trong tên — phép đếm nằm ở SQL. Bộ filter
            # "tên phải chứa X" bên dưới sẽ loại sạch chúng, nên miễn trừ ở đây.
            # Không miễn thì "bao nhiêu khách đang là chủ xe" trượt sang cột BUYER,
            # đúng cái nhầm mà cả Sprint 2 dựng ra để tránh.
            is_cross = table == "customer_cross_bu_feature"
            if is_cross or f.get("aggregation") == "flag":
                # Khi router ĐÃ định tuyến cross_bu (unit == CROSS_BU) thì không đòi
                # thêm từ khóa "cả hai/đồng thời" nữa — hai điều kiện cộng dồn từng
                # làm "Khách GSM nào đang là chủ xe VinFast" trả về 0 feature rồi
                # báo "câu hỏi chưa đủ rõ", trong khi câu hỏi rất rõ.
                # Gate từ khóa chỉ còn cần khi CHƯA biết BU, để cross-BU không lọt
                # vào câu single-BU.
                if is_cross and unit is None and not table_scores.get(table):
                    continue
                # Cờ boolean không bao giờ là câu trả lời cho câu hỏi về TIỀN.
                if (
                    f.get("aggregation") == "flag"
                    and metric_hint == "value"
                    and not (
                        cross_both_requested
                        and f.get("name", "").startswith("is_cross_bu_active_")
                    )
                    and not (
                        is_cross
                        and f.get("name", "").startswith("is_active_gsm_")
                        and _has_term(q_norm, ("hoat dong gsm", "active gsm"))
                    )
                    and not (
                        is_cross
                        and f.get("name", "").startswith("is_active_vinfast_")
                        and _has_term(q_norm, ("hoat dong vinfast", "active vinfast"))
                    )
                ):
                    continue
                name = f.get("name", "")
            else:
                has_count = bool(re.search(r"(?:^|_)count(?:_|$)", f.get("name", "")))
                if metric_hint == "count" and not has_count and "active_day" not in f.get("name", ""):
                    continue
                if metric_hint == "value" and not any(
                    x in f.get("name", "") for x in ("amount", "price", "discount", "battery", "distance")
                ):
                    continue
                if metric_hint == "ratio" and f.get("aggregation") != "ratio":
                    continue
                name = f.get("name", "")
                if compare and count_requested and not has_count:
                    continue
                # Danh sách này phải phủ MỌI token đã đưa vào `value_requested`, nếu không
                # câu so sánh về chỉ số đó bị lọc sạch: thêm "quang duong/distance/km" vào
                # value_requested mà quên ở đây đã làm M02 trả về 0 feature.
                if compare and value_requested and not any(
                    x in name for x in ("amount", "price", "discount", "battery", "distance")
                ):
                    continue
                # Trạng thái bị phủ định: LOẠI feature mang token đó. Phải đứng TRƯỚC
                # hai filter "đòi token" bên dưới, vì chính chúng biến "chưa hoàn thành"
                # thành "hoàn thành".
                if negated_status and any(token in name for token in negated_status):
                    continue
                if (
                    "canceled" not in negated_status
                    and _has_term(q_norm, ("cancel", "canceled", "cancelled", "huy"))
                    and "canceled" not in name
                ):
                    continue
                if (
                    "completed" not in negated_status
                    and _has_term(q_norm, ("completed", "finished", "hoan thanh"))
                    and not any(x in name for x in ("completed", "finished"))
                ):
                    continue
                if discount_requested and "discount" not in name:
                    continue
                if value_requested and not discount_requested:
                    if "discount" in name:
                        continue
                if _has_term(q_norm, ("distance", "quang duong", "km")) and "distance" not in name:
                    continue
                if _has_term(q_norm, ("active day", "ngay hoat dong")) and "active_day" not in name:
                    continue
                if _has_term(q_norm, ("processing time", "thoi gian xu ly")) and "processing_time" not in name:
                    continue
                if _has_term(q_norm, ("amount",)):
                    if table == "gsm_transaction":
                        if "original_price" not in name or "discount" in name:
                            continue
                    elif "amount" not in name:
                        continue
                if _has_term(q_norm, ("price",)) and "price" not in name:
                    continue
                if value_requested and not _has_term(q_norm, ("max", "maximum", "highest", "lon nhat")):
                    if name.endswith("_max_" + str(feature_window)) or "_max_" in name:
                        continue
                if value_requested and not _has_term(q_norm, ("min", "minimum", "lowest", "nho nhat")):
                    if name.endswith("_min_" + str(feature_window)) or "_min_" in name:
                        continue
                if metric_hint == "count" and not _has_term(q_norm, ("active day", "ngay hoat dong")):
                    if "active_day" in name:
                        continue
                if not _has_term(q_norm, ("weekday", "ngay trong tuan")) and "weekday" in name:
                    continue
                if not _has_term(q_norm, ("daytime", "ban ngay")) and "daytime" in name:
                    continue

            score = 0.0
            name_norm = _strip_accents(name)
            if name_norm in q_norm:
                score += 8.0
            for kw in f.get("keywords", []):
                kw_norm = _strip_accents(kw)
                if kw_norm and kw_norm in q_norm:
                    score += 1.5 + min(len(kw_norm.split()), 4) * 0.25
            score += 0.25 * len(q_tokens & feature_tokens)
            score += 1.25 * table_scores.get(table, 0)
            if window_hint and feature_window == window_hint:
                score += 2.0
            if compare and f.get("aggregation") == "ratio":
                score += 2.5
            if is_cross and per_bu_breakdown:
                target_window = window_hint or "all"
                if name_norm in {f"gsm_spend_{target_window}", f"vinfast_spend_{target_window}"}:
                    score += 8.0
                elif name_norm.startswith("combined_spend_"):
                    score -= 3.0
            if is_cross and cross_both_requested:
                if name_norm.startswith("is_cross_bu_active_") and _has_term(
                    q_norm, ("hoat dong", "active", "ca hai", "dong thoi", "dung ca")
                ):
                    score += 3.0
                if name_norm.startswith("combined_spend_") and value_requested:
                    score += 3.0
            if is_cross and _has_term(q_norm, ("hoat dong gsm", "active gsm")):
                if name_norm.startswith("is_active_gsm_"):
                    score += 2.0
            if is_cross and _has_term(q_norm, ("hoat dong vinfast", "active vinfast")):
                if name_norm.startswith("is_active_vinfast_"):
                    score += 2.0
            if "txn_completed_count" in name_norm and _has_term(
                q_norm, ("hoan thanh", "completed", "giao dich", "don")
            ) and not _has_term(q_norm, ("mua xe", "don xe", "vehicle purchase")):
                score += 2.0
            if "nvso" in q_norm and "nvso" in name_norm:
                score += 3.0
            if any(term in q_norm for term in ("work order", "work_order", "wo")) and "_wo_" in name_norm:
                score += 3.0
            score -= _NARROWING_PENALTY * _unrequested_narrowing(name_norm, q_norm)
            if score <= 0:
                continue
            scored.append(
                ScoredFeature(
                    name=f["name"],
                    table=f["table"],
                    group=f.get("group", ""),
                    description_vi=f.get("description_vi", ""),
                    description_en=f.get("description_en", ""),
                    keywords=f.get("keywords", []),
                    score=round(score, 3),
                    support_status=f.get("support_status", "queryable"),
                    dtype=f.get("dtype"),
                    unit=f.get("unit"),
                    null_meaning=f.get("null_meaning"),
                    business_unit=f.get("business_unit"),
                )
            )
        scored.sort(key=lambda item: (-item.score, item.name))
        if not scored:
            return []
        if not window_hints:
            scored = _one_window_per_stem(scored)
        return scored[: max(1, top_k)]


@lru_cache
def get_semantic_layer() -> SemanticLayer:
    # Agent đọc DB catalog (đã seed từ YAML authoritative). Tests dùng trực tiếp
    # SemanticLayer.load(yaml_path) khi cần chạy offline không có DB.
    return SemanticLayer.load_from_db()
