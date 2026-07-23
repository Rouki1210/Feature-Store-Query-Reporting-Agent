"""Lớp ngữ nghĩa SONG NGỮ — sinh mô tả + keyword tiếng Việt VÀ tiếng Anh.

Tồn tại vì mô tả nguồn không dùng được: mọi feature `_pnl_*` chia sẻ đúng một
chuỗi template, không phân biệt PnL lẫn cửa sổ — LLM đọc vào không chọn nổi cột.

Nguyên tắc (CLAUDE.md mục 3):
- KHÔNG viết tay mô tả feature. Mở rộng các từ điển dưới đây rồi tái sinh
  (scripts/generate_semantic_layer.py). Một entry từ điển sửa cho MỌI feature
  dùng token đó.
- `SYNONYMS_VI` / `SYNONYMS_EN` (từ vựng nghiệp vụ) là lớp duy nhất không suy ra
  được từ tên — đây là thứ đáng nuôi lớn nhất. Người dùng thật nói "khách sắp
  rời bỏ" / "churn risk", không nói `days_since_last_txn`.
- Token chưa xác minh (`wo`, `nvso`): gắn cờ, KHÔNG bịa nghĩa.
"""
from __future__ import annotations

from app.semantic.feature_spec import Feature

# ====================== Từ điển cửa sổ thời gian ======================
WINDOWS_VI = {
    "l1m": "1 tháng gần nhất",
    "l3m": "3 tháng gần nhất",
    "l6m": "6 tháng gần nhất",
    "l12m": "12 tháng gần nhất",
    "l1w": "1 tuần gần nhất",
    "l2w": "2 tuần gần nhất",
    "daily": "trong ngày",
}
WINDOWS_EN = {
    "l1m": "last 1 month",
    "l3m": "last 3 months",
    "l6m": "last 6 months",
    "l12m": "last 12 months",
    "l1w": "last 1 week",
    "l2w": "last 2 weeks",
    "daily": "daily",
}

# ====================== Tên PnL ======================
PNL_VI = {
    "gsm": "GSM (di chuyển)",
    "vinfast": "VinFast (ô tô/xe máy điện)",
    "vinhomes": "Vinhomes (bất động sản)",
    "vinmec": "Vinmec (y tế)",
    "vinpearl": "Vinpearl (nghỉ dưỡng)",
    "vinschool": "Vinschool (giáo dục)",
    "vinclub": "VinClub (thẻ thành viên)",
    "vincomretail": "Vincom Retail (TTTM)",
    "merchant": "Merchant (đối tác)",
    "vapp": "VinApp (ứng dụng)",
    "fgf": "FGF (giới thiệu bạn bè)",
}
PNL_EN = {
    "gsm": "GSM (ride-hailing)",
    "vinfast": "VinFast (EV & accessories)",
    "vinhomes": "Vinhomes (real estate)",
    "vinmec": "Vinmec (healthcare)",
    "vinpearl": "Vinpearl (hospitality)",
    "vinschool": "Vinschool (education)",
    "vinclub": "VinClub (membership)",
    "vincomretail": "Vincom Retail (malls)",
    "merchant": "Merchant (partners)",
    "vapp": "VinApp (app)",
    "fgf": "FGF (friend-get-friend)",
}

# ====================== Chiều điểm / trạng thái ======================
DIRECTION_VI = {"earn": "tích điểm", "burn": "tiêu điểm"}
DIRECTION_EN = {"earn": "points earned", "burn": "points burned"}
STATUS_VI = {"completed": "đã hoàn thành"}
STATUS_EN = {"completed": "completed"}

# ====================== Metric (EN) — bổ sung cho vi_metric trong spec ======================
METRIC_EN = {
    "txn": "transaction count",
    "gmv": "gross merchandise value (GMV)",
    "discount": "total discount",
    "distance_km": "total distance (km)",
    "pts": "loyalty points",
}

# ====================== Nhóm feature (EN) ======================
GROUP_EN = {
    "Giá trị & số dư": "Value & balance",
    "Hành trình & trạng thái": "Journey & status",
    "Thời gian & gắn kết": "Recency & engagement",
    "Tỷ lệ & xu hướng": "Ratio & trend",
    "Kênh & ngữ cảnh": "Channel & context",
    "Sản phẩm & dịch vụ": "Product & service",
    "Hoạt động & tần suất": "Activity & frequency",
}

# ====================== SYNONYMS — lớp giá trị nhất, nuôi lớn dần ======================
SYNONYMS_VI: dict[str, list[str]] = {
    "gmv": ["doanh thu", "giá trị giao dịch", "chi tiêu", "tổng tiền", "gmv", "doanh số"],
    "txn": ["số giao dịch", "số lần", "tần suất", "số đơn", "số chuyến", "lượt"],
    "discount": ["chiết khấu", "giảm giá", "khuyến mãi", "ưu đãi"],
    "distance_km": ["quãng đường", "số km", "khoảng cách"],
    "pts": ["điểm", "điểm thưởng", "point", "số dư điểm"],
    "earn": ["tích điểm", "kiếm điểm", "nhận điểm", "cộng điểm"],
    "burn": ["tiêu điểm", "dùng điểm", "đổi điểm", "trừ điểm"],
    "primary": ["chủ đạo", "chủ yếu", "nơi tiêu nhiều nhất", "nơi hoạt động chính"],
    "gsm": ["gsm", "xanh sm", "taxi", "gọi xe", "giao hàng"],
    "vinfast": ["vinfast", "ô tô điện", "xe điện", "xe máy điện", "phụ kiện xe"],
    "loyalty": ["loyalty", "vinclub", "điểm thành viên", "chương trình khách hàng thân thiết"],
    "cross_pnl": ["liên pnl", "chéo ngành", "chuyển dịch giữa các mảng", "cross pnl"],
}
SYNONYMS_EN: dict[str, list[str]] = {
    "gmv": ["revenue", "spend", "spending", "transaction value", "gmv", "sales"],
    "txn": ["transactions", "orders", "trips", "frequency", "number of times", "count"],
    "discount": ["discount", "promotion", "promo", "voucher"],
    "distance_km": ["distance", "kilometers", "km traveled"],
    "pts": ["points", "loyalty points", "point balance", "rewards"],
    "earn": ["earn", "earned", "accrue", "collect points"],
    "burn": ["burn", "redeem", "spend points", "use points"],
    "primary": ["primary", "dominant", "main", "top pnl"],
    "gsm": ["gsm", "xanh sm", "ride-hailing", "taxi", "delivery"],
    "vinfast": ["vinfast", "ev", "electric vehicle", "e-scooter", "car accessories"],
    "loyalty": ["loyalty", "vinclub", "membership", "rewards program"],
    "cross_pnl": ["cross pnl", "cross-business", "cross unit", "shift between units"],
}

# ====================== Token chưa xác minh — gắn cờ, KHÔNG bịa (mục 3) ======================
UNVERIFIED_TOKENS = {
    "wo": "GIẢ ĐỊNH 'work order' — cần xác nhận / ASSUMED 'work order' — needs confirmation",
    "nvso": "CHƯA RÕ NGHĨA — cần xác nhận / MEANING UNKNOWN — needs confirmation",
}


def _syn(*keys: str) -> list[str]:
    out: list[str] = []
    for k in keys:
        out.extend(SYNONYMS_VI.get(k, []))
        out.extend(SYNONYMS_EN.get(k, []))
    return out


def describe(feat: Feature) -> tuple[str, str, list[str]]:
    """Trả về (mô_tả_vi, description_en, keywords) — keywords gộp cả VI lẫn EN.

    Sinh hoàn toàn từ các thành phần đã phân giải — không viết tay.
    """
    c = feat.components
    kind = c["kind"]
    keywords: set[str] = set()

    if kind in ("txn_base", "ratio"):
        table_vi = "GSM" if feat.table.startswith("gsm") else "VinFast"
        metric = c["metric"]
        vi_metric = c["vi_metric"]
        en_metric = METRIC_EN.get(metric, metric)
        keywords.update(_syn(metric, feat.table.split("_")[0]))
        if kind == "txn_base":
            w = c["window"]
            desc_vi = f"{vi_metric.capitalize()} tại {table_vi}, {STATUS_VI['completed']}, {WINDOWS_VI[w]}."
            desc_en = f"{en_metric.capitalize()} at {table_vi}, {STATUS_EN['completed']}, {WINDOWS_EN[w]}."
            keywords.update({WINDOWS_VI[w], WINDOWS_EN[w]})
        else:  # ratio
            num, den = c["num_window"], c["den_window"]
            desc_vi = (
                f"Tỷ lệ xu hướng {vi_metric} tại {table_vi}: "
                f"{WINDOWS_VI[num]} so với {WINDOWS_VI[den]} (tính sẵn)."
            )
            desc_en = (
                f"Trend ratio of {en_metric} at {table_vi}: "
                f"{WINDOWS_EN[num]} vs {WINDOWS_EN[den]} (pre-computed)."
            )
            keywords.update(_syn("cross_pnl"))
            keywords.update({"xu hướng", "tăng giảm", "so với kỳ trước", "tỷ lệ",
                             "trend", "ratio", "growth", "vs previous period"})

    elif kind == "loyalty":
        pnl, direction, metric, w = c["pnl"], c["direction"], c["metric"], c["window"]
        vi_metric = "điểm" if metric == "pts" else "số giao dịch"
        en_metric = "points" if metric == "pts" else "transaction count"
        desc_vi = (
            f"{DIRECTION_VI[direction].capitalize()} — {vi_metric} tại {PNL_VI[pnl]}, "
            f"{STATUS_VI['completed']}, {WINDOWS_VI[w]}."
        )
        desc_en = (
            f"{DIRECTION_EN[direction].capitalize()} — {en_metric} at {PNL_EN[pnl]}, "
            f"{STATUS_EN['completed']}, {WINDOWS_EN[w]}."
        )
        keywords.update(_syn(metric, direction, pnl, "loyalty", "cross_pnl"))
        keywords.update({WINDOWS_VI[w], WINDOWS_EN[w]})

    elif kind == "loyalty_primary":
        direction, w = c["direction"], c["window"]
        desc_vi = (
            f"PnL {DIRECTION_VI[direction]} chủ đạo của khách trong {WINDOWS_VI[w]} "
            f"(chỉ có ở l6m/l12m — không có l1m)."
        )
        desc_en = (
            f"Customer's primary {('earning' if direction == 'earn' else 'burning')} PnL "
            f"over the {WINDOWS_EN[w]} (exists ONLY at l6m/l12m — no l1m)."
        )
        keywords.update(_syn("primary", direction, "loyalty", "cross_pnl"))
        keywords.update({WINDOWS_VI[w], WINDOWS_EN[w]})
    else:
        desc_vi = desc_en = feat.name
        keywords.add(feat.name)

    # Gắn cờ token chưa xác minh nếu lỡ xuất hiện trong tên.
    for tok, note in UNVERIFIED_TOKENS.items():
        if f"_{tok}_" in feat.name or feat.name.endswith(f"_{tok}"):
            desc_vi += f"  [⚠ {tok}: {note}]"
            desc_en += f"  [⚠ {tok}: {note}]"

    keywords.add(feat.group.lower())
    keywords.add(GROUP_EN.get(feat.group, feat.group).lower())
    return desc_vi, desc_en, sorted(keywords)
