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
    # Luỹ kế tới ngày snapshot, không giới hạn cửa sổ (feature_spec.ALL_TIME).
    "all": ("toàn thời gian tính tới ngày snapshot", "all time up to the snapshot date"),
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
    # Sprint 2 — khóa nguyên stem, KHÔNG map token "delivered" chung: trạng thái đơn
    # `delivered` không đồng nghĩa bàn giao xe (docs/vehicle_owner_semantics.md).
    "vehicle_purchase_completed_count": ("số đơn mua xe hoàn tất", "completed vehicle purchase count"),
    "vehicle_delivered_count": ("số xe đã bàn giao", "delivered vehicle count"),
    "is_vehicle_buyer": ("khách đã mua xe", "is vehicle buyer"),
    "is_vehicle_owner": ("khách đang là chủ xe", "is vehicle owner"),
    "first_vehicle_purchase_date": ("ngày mua xe đầu tiên", "first vehicle purchase date"),
    "first_vehicle_handover_date": ("ngày nhận xe đầu tiên", "first vehicle handover date"),
    "days_since_last_vehicle_handover": (
        "số ngày kể từ lần nhận xe gần nhất", "days since last vehicle handover",
    ),
    "is_vehicle_handover_scheduled": (
        "đã hẹn lịch giao xe nhưng chưa nhận", "vehicle handover scheduled but not completed",
    ),
    # Sprint 2 Task 2.3 — cross-BU (khóa nguyên stem, tránh đụng token chung).
    "is_active_gsm": ("có hoạt động GSM", "active on GSM"),
    "is_active_vinfast": ("có hoạt động VinFast", "active on VinFast"),
    "is_cross_bu_active": ("hoạt động ở CẢ GSM và VinFast", "active on both GSM and VinFast"),
    "gsm_spend": ("chi tiêu GSM", "GSM spend"),
    "vinfast_spend": ("chi tiêu VinFast", "VinFast spend"),
    "combined_spend": ("tổng chi tiêu cả hai đơn vị", "combined spend across both units"),
    "dominant_business_unit": (
        "đơn vị chi tiêu nhiều hơn", "business unit with the larger spend",
    ),
    "cross_bu_engagement_score": (
        "mức cân bằng chi tiêu giữa hai đơn vị", "cross-BU spend balance score",
    ),
    "gsm_active_vehicle_owner_flag": (
        "chủ xe VinFast đang hoạt động GSM", "VinFast owner active on GSM",
    ),
}


def _business_aliases(stem: str) -> set[str]:
    """Business phrases that do not follow the physical column naming."""
    aliases: set[str] = set()
    if stem.startswith("days_since_last"):
        aliases.update({"chua quay lai", "lau khong su dung", "lan cuoi"})
    if stem.startswith("days_since_first"):
        # "dau tien" phải đứng riêng: câu thật hay chèn chữ vào giữa ("giao dịch
        # VinFast hoàn thành ĐẦU TIÊN"), nên alias cả cụm dài không khớp substring.
        aliases.update({"bat dau su dung", "giao dich dau tien", "lan dau", "dau tien"})
    if "active_day_count" in stem:
        aliases.update({"hoat dong thuong xuyen", "so ngay hoat dong"})
    if "discount" in stem:
        aliases.update({"ap dung giam gia", "giao dich giam gia"})
    if "handover_scheduled" in stem:
        aliases.update({"da hen giao", "hen lich giao xe", "cho nhan xe", "sap nhan xe"})
    elif "vehicle_owner" in stem or "vehicle_handover" in stem:
        aliases.update({"chu xe", "da nhan xe", "nhan xe", "dung ten xe", "so huu xe", "ban giao xe"})
    if stem == "vehicle_delivered_count":
        aliases.update({"khach nhan xe", "nhan xe", "xe da nhan", "da ban giao xe"})
    if "cross_bu" in stem or stem in ("combined_spend", "dominant_business_unit"):
        aliases.update({
            "ca hai don vi", "ca gsm va vinfast", "vua di gsm vua mua vinfast",
            "khach dung ca hai", "khach chung", "overlap", "xuyen don vi",
        })
    if "vehicle_buyer" in stem or "vehicle_purchase" in stem:
        aliases.update({"da mua xe", "chot don xe", "don xe hoan tat", "khach mua xe"})
    if "discount" in stem and "completed" in stem and "count" in stem:
        aliases.update({
            "giao dich hoan thanh duoc ap dung giam gia",
            "hoan thanh duoc ap dung giam gia",
        })
    return aliases


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
    if "gsm_transaction" in feat.table:
        table_vi = table_en = "GSM"
    elif "cross_bu" in feat.table:
        table_vi, table_en = "GSM + VinFast", "GSM + VinFast"
    else:
        table_vi = table_en = "VinFast"
    stem = feat.metric
    base_vi = _human(stem, "vi")
    base_en = _human(stem, "en")

    if feat.agg == "flag":
        vi = f"Cờ {base_vi}"
        en = f"Flag: {base_en}"
    elif feat.agg == "ratio":
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
    # Buyer ≠ owner là lỗi nghiệp vụ không test kỹ thuật nào bắt được — nói thẳng
    # trong chính mô tả mà LLM đọc (docs/vehicle_owner_semantics.md).
    if "vehicle_owner" in feat.name or "vehicle_handover" in feat.name:
        notes.append("owner: chỉ từ bản ghi bàn giao, không suy từ trạng thái đơn.")
        vi += " Chủ xe chỉ tính từ bản ghi bàn giao, KHÔNG suy từ đơn hoàn tất."
        en += " Ownership comes from handover records only, never from order status."
    if "vehicle_buyer" in feat.name or "vehicle_purchase" in feat.name:
        vi += " Mua xe KHÔNG đồng nghĩa đã nhận xe."
        en += " Buying a vehicle does not mean it has been handed over."
    # Công thức phải nằm trong mô tả: LLM đọc mô tả để quyết định dùng cột nào, và
    # "điểm gắn kết" không tự nói lên nó được tính thế nào.
    if feat.name == "cross_bu_engagement_score":
        vi += " Công thức: min(chi tiêu hai đơn vị) / max(chi tiêu hai đơn vị) — 0 là dồn hết một phía, 1 là cân bằng."
        en += " Formula: min(spend of the two units) / max(spend of the two units) - 0 is one-sided, 1 is balanced."
    if feat.name == "dominant_business_unit_l1m":
        vi += " Giá trị: GSM, VINFAST hoặc TIE khi bằng nhau."
        en += " Values: GSM, VINFAST, or TIE when equal."

    if feat.null_meaning_key == "always_present":
        vi += " Luôn có giá trị: FALSE nghĩa là không phải, không phải thiếu dữ liệu."
        en += " Always populated: FALSE means not applicable, not missing data."
    elif feat.null_meaning_key == "no_history_in_unit":
        vi += (" NULL nghĩa là khách CHƯA TỪNG có dữ liệu ở đơn vị đó; 0 nghĩa là có"
               " dữ liệu nhưng kỳ này không phát sinh. Tính trung bình phải chọn rõ"
               " mẫu số là nhóm nào.")
        en += (" NULL means the customer has NEVER had data in that unit; 0 means they"
               " have history but nothing in this window. Averages must state which"
               " denominator they use.")
    elif feat.null_meaning_key == "no_spend_to_compare":
        vi += " NULL khi không có chi tiêu ở cả hai đơn vị để so sánh."
        en += " NULL when there is no spend on either unit to compare."
    elif feat.null_meaning_key == "zero_denominator":
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
    if "cross_bu" in feat.table:
        keywords.update({
            "gsm", "vinfast", "vf", "cross bu", "xuyên đơn vị", "cả hai", "đồng thời",
            "vừa", "overlap", "chung",
        })
    elif "gsm" in feat.table:
        keywords.update({"gsm", "xanh sm", "trip", "ride", "delivery", "chuyến", "giao hàng"})
    else:
        keywords.update({"vinfast", "vf", "order", "vehicle", "car", "đơn xe", "giao dịch"})
    if "buyer" in feat.name or "owner" in feat.name:
        keywords.update({"buyer", "owner", "chủ sở hữu", "người mua"})
    keywords.update(_business_aliases(stem))
    keywords.update(notes)
    return vi, en, sorted(k for k in keywords if k)
