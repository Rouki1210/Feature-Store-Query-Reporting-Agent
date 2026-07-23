"""Deterministic Vietnamese/English descriptions for the canonical inventory."""
from __future__ import annotations

import re

from app.semantic.feature_spec import Feature, RATIO_WINDOWS

WINDOWS = {
    "daily": ("trong ngày", "daily"),
    "l1w": ("1 tuần gần nhất", "last 1 week"),
    "l2w": ("2 tuần gần nhất", "last 2 weeks"),
    "l4w": ("4 tuần gần nhất", "last 4 weeks"),
    "l1m": ("1 tháng gần nhất", "last 1 month"),
    "l2m": ("2 tháng gần nhất", "last 2 months"),
    "l3m": ("3 tháng gần nhất", "last 3 months"),
    "l6m": ("6 tháng gần nhất", "last 6 months"),
    "l8w": ("8 tuần gần nhất", "last 8 weeks"),
    "l12m": ("12 tháng gần nhất", "last 12 months"),
}

_STATUS = {
    "completed": ("hoàn thành", "completed"),
    "canceled": ("hủy", "canceled"),
    "finished": ("kết thúc", "finished"),
}

_TERM = {
    "txn": ("giao dịch", "transaction"),
    "count": ("số lượng", "count"),
    "amount": ("giá trị tiền", "amount"),
    "price": ("giá", "price"),
    "original_price": ("giá gốc", "original price"),
    "discount": ("chiết khấu", "discount"),
    "active_day_count": ("số ngày phát sinh", "active-day count"),
    "processing_time": ("thời gian xử lý", "processing time"),
    "trip_distance_km": ("quãng đường chuyến đi", "trip distance"),
    "battery": ("dung lượng pin", "battery capacity"),
    "weekday": ("ngày trong tuần", "weekday"),
    "daytime": ("khung giờ ban ngày", "daytime"),
    "type_taxi": ("dịch vụ taxi", "taxi service"),
    "type_bike": ("dịch vụ xe máy", "bike service"),
    "type_express": ("dịch vụ giao nhanh", "express delivery"),
    "type_food": ("dịch vụ giao đồ ăn", "food delivery"),
    "accessories": ("phụ kiện", "accessories"),
    "wo": ("work order", "work order"),
    "nvso": ("NVSO", "NVSO"),
}


def _window_text(window: str | None) -> tuple[str, str]:
    if not window:
        return "", ""
    if window in WINDOWS:
        vi, en = WINDOWS[window]
        return f" trong {vi}", f" over the {en}"
    left, right = window.split("_vs_", 1)
    lvi, len_ = WINDOWS.get(left, (left, left))
    rvi, ren = WINDOWS.get(right, (right, right))
    return f", so sánh {lvi} với {rvi}", f", comparing {len_} with {ren}"


def _human(stem: str, language: str) -> str:
    # Longest tokens first so original_price and active_day_count stay intact.
    text = stem
    for key in sorted(_TERM, key=len, reverse=True):
        vi, en = _TERM[key]
        text = text.replace(key, vi if language == "vi" else en)
    text = re.sub(r"_+", " ", text).strip()
    return text


def describe(feat: Feature) -> tuple[str, str, list[str]]:
    table_vi = "GSM" if "gsm_transaction" in feat.table else "VinFast"
    table_en = table_vi
    stem = feat.metric
    base_vi = _human(stem, "vi")
    base_en = _human(stem, "en")

    if feat.agg == "ratio":
        vi = f"Tỷ lệ xu hướng {base_vi}"
        en = f"Trend ratio of {base_en}"
    elif feat.agg == "count":
        vi = f"Số {base_vi}"
        en = f"{base_en.title()}"
    elif feat.agg == "derived":
        vi = f"{base_vi}"
        en = f"{base_en}"
    else:
        vi = f"{base_vi}"
        en = f"{base_en}"

    wvi, wen = _window_text(feat.window)
    vi = f"{table_vi}: {vi}{wvi}."
    en = f"{table_en}: {en}{wen}."

    notes: list[str] = []
    if "nvso" in feat.name:
        notes.append("NVSO: thuật ngữ nghiệp vụ cần xác minh.")
        vi += " NVSO chưa có định nghĩa nghiệp vụ đã xác minh."
        en += " NVSO business meaning is not verified."
    if "_wo_" in feat.name:
        notes.append("work_order: không suy diễn thành chủ sở hữu xe.")
        vi += " Work order không đồng nghĩa chủ sở hữu xe."
        en += " A work order does not imply vehicle ownership."
    if "completed" in feat.name or "finished" in feat.name:
        vi += " Completed/finished chỉ phản ánh trạng thái giao dịch."
        en += " Completed/finished describes transaction status only."
    if feat.null_meaning_key == "zero_denominator":
        vi += " NULL khi mẫu số bằng 0."
        en += " NULL when the denominator is zero."
    else:
        vi += " NULL khi không có sự kiện trong cửa sổ."
        en += " NULL when no event exists in the window."

    keywords = {
        feat.name,
        feat.name.replace("_", " "),
        stem.replace("_", " "),
        table_vi.lower(),
        table_en.lower(),
        feat.group.lower(),
        base_vi.lower(),
        base_en.lower(),
    }
    if "gsm" in feat.table:
        keywords.update({"gsm", "xanh sm", "trip", "ride", "delivery", "chuyến", "giao hàng"})
    else:
        keywords.update({"vinfast", "vf", "order", "vehicle", "car", "đơn xe", "giao dịch"})
    if "buyer" in feat.name or "owner" in feat.name:
        keywords.update({"buyer", "owner", "chủ sở hữu", "người mua"})
    keywords.update(notes)
    return vi, en, sorted(k for k in keywords if k)
