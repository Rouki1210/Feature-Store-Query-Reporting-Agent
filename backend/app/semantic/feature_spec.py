"""Canonical Sprint 1 feature inventory.

The workbook names are table-prefixed; physical columns and SQL generation use
the unprefixed feature name.  This module is the single source for the 167 GSM
and 186 VinFast retained features.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TABLES = {
    "feature.gsm_transaction": {
        "unit": "GSM",
        "vi": "GSM — chuyến đi và giao hàng",
        "en": "GSM — rides and delivery",
    },
    "feature.vinfast_transaction": {
        "unit": "VINFAST",
        "vi": "VinFast — giao dịch xe, phụ kiện và dịch vụ",
        "en": "VinFast — vehicle, accessories and service transactions",
    },
    # Sprint 2 (Task 2.3) — bảng TÍNH SẴN cho câu hỏi xuyên BU. Agent đọc bảng này
    # thay vì tự join, để lỗi nhân dòng không thể xảy ra (ADR 0001).
    "feature.customer_cross_bu_feature": {
        "unit": "CROSS_BU",
        "vi": "Xuyên đơn vị — khách dùng cả GSM và VinFast",
        "en": "Cross-BU — customers active in both GSM and VinFast",
    },
}

GROUPS = [
    "Giá trị & số dư",
    "Hành trình & trạng thái",
    "Thời gian & gắn kết",
    "Tỷ lệ & xu hướng",
    "Sản phẩm & dịch vụ",
    "Hoạt động & tần suất",
]

WINDOW_DAYS = {
    "daily": 1,
    "l1w": 7,
    "l2w": 14,
    "l1m": 30,
    "l3m": 90,
    "l6m": 180,
    "l12m": 365,
}

# Cửa sổ "toàn thời gian tính tới snapshot" — KHÔNG có trong WINDOW_DAYS vì nó không
# phải một số ngày. Cần cho câu hỏi luỹ kế: "tổng cộng bao nhiêu xe đã bàn giao"
# (UC2-10) mà cửa sổ l1m trả lời sai kỳ.
ALL_TIME = "all"
# Bộ cửa sổ tiêu chuẩn cho feature Sprint 2 (PIT + cross-BU). Không dùng daily/l1w/l2w:
# grain snapshot cách nhau 30 ngày nên cửa sổ dưới tháng không thêm thông tin.
SPRINT2_WINDOWS = ("l1m", "l3m", "l6m", "l12m", ALL_TIME)

RATIO_WINDOWS = (
    "l1m_vs_l3m",
    "l1m_vs_l6m",
    "l1m_vs_l12m",
    "l3m_vs_l12m",
)
GSM_RATIO_WINDOWS = ("l1m_vs_l3m", "l1m_vs_l6m", "l3m_vs_l12m")


@dataclass(frozen=True)
class Feature:
    name: str
    table: str
    group: str
    dtype: str
    metric: str
    window: str | None = None
    agg: str = "sum"
    unit: str | None = None
    null_meaning_key: str | None = "no_event_in_window"
    components: dict[str, Any] = field(default_factory=dict)


_GSM_STEMS: dict[str, tuple[str, ...]] = {
    "canceled_original_price_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "canceled_original_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "canceled_txn_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "canceled_txn_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "canceled_weekday_original_price_sum": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "canceled_weekday_txn_count": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "completed_discount_amount_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "completed_original_price_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "completed_original_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m", *GSM_RATIO_WINDOWS),
    "completed_trip_distance_km_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m", *GSM_RATIO_WINDOWS),
    "completed_txn_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "completed_txn_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "completed_weekday_original_price_sum": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "completed_weekday_txn_count": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "days_since_first_txn": ("l12m",),
    "days_since_last_txn": ("l12m",),
    "finished_original_price_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "finished_original_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "finished_time_daytime_original_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "finished_time_daytime_txn_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "finished_txn_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "finished_txn_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m", *GSM_RATIO_WINDOWS),
    "finished_type_bike_txn_count": ("l1w", "l2w"),
    "finished_type_express_txn_count": ("l1w", "l2w"),
    "finished_type_food_txn_count": ("l1w", "l2w"),
    "finished_type_taxi_txn_count": ("l1w", "l2w"),
    "finished_weekday_original_price_sum": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "finished_weekday_txn_count": ("l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
}

_VF_STEMS: dict[str, tuple[str, ...]] = {
    "days_since_first_completed_txn_days": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "days_since_last_completed_txn_days": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_accessories_canceled_amount_sum": RATIO_WINDOWS,
    "txn_accessories_canceled_count": RATIO_WINDOWS,
    "txn_accessories_canceled_price_sum": RATIO_WINDOWS,
    "txn_accessories_completed_amount_sum": RATIO_WINDOWS,
    "txn_accessories_completed_count": ("l12m", *RATIO_WINDOWS),
    "txn_accessories_completed_price_sum": ("l12m", *RATIO_WINDOWS),
    "txn_canceled_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_canceled_amount_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_canceled_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_canceled_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_canceled_processing_time_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_canceled_processing_time_min": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_completed_active_day_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_completed_amount_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_completed_battery_sum": ("l12m",),
    "txn_completed_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_completed_price_sum": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_completed_processing_time_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_completed_processing_time_min": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_discount_accessories_completed_count": ("l12m",),
    "txn_discount_canceled_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_discount_completed_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_discount_delivered_count": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_discount_nvso_completed_count": ("l12m",),
    "txn_first_completed_updated_date_min": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_last_completed_updated_date_max": ("daily", "l1w", "l2w", "l1m", "l3m", "l6m", "l12m"),
    "txn_wo_canceled_amount_sum": RATIO_WINDOWS,
    "txn_wo_canceled_count": RATIO_WINDOWS,
    "txn_wo_canceled_price_sum": RATIO_WINDOWS,
    "txn_wo_completed_amount_sum": RATIO_WINDOWS,
    "txn_wo_completed_count": RATIO_WINDOWS,
    "txn_wo_completed_price_sum": RATIO_WINDOWS,
}


# Sprint 2 (Task 2.2) — buyer/owner point-in-time.
# window=None: trạng thái TẠI snapshot, không phải tổng hợp theo cửa sổ. Owner chỉ
# đến từ raw.vinfast_vehicle_handover — xem docs/vehicle_owner_semantics.md.
_VF_PIT_STEMS: dict[str, tuple[str | None, ...]] = {
    "vehicle_purchase_completed_count": SPRINT2_WINDOWS,
    "vehicle_delivered_count": SPRINT2_WINDOWS,
    # Cờ luỹ kế: "đã từng mua / đang sở hữu" không phụ thuộc cửa sổ.
    "is_vehicle_buyer": (None,),
    "is_vehicle_owner": (None,),
    # Đã hẹn giao nhưng CHƯA có handed_over_at ⇒ chưa phải chủ xe (UC2-09).
    # Không có cột này thì "đã hẹn giao chưa nhận" bị gộp chung với "mua chưa hẹn".
    "is_vehicle_handover_scheduled": (None,),
    "first_vehicle_purchase_date": (None,),
    "first_vehicle_handover_date": (None,),
    "days_since_last_vehicle_handover": (None,),
}


# Sprint 2 (Task 2.3) — cross-BU, grain customer_id + snapshot_date như hai bảng nguồn.
# CỐ Ý không có `is_vehicle_owner` ở đây: tên đó đã thuộc feature.vinfast_transaction,
# trùng tên giữa hai bảng làm SQL generator không biết chọn bảng nào. Câu hỏi "chủ xe có
# đi GSM không" dùng `gsm_active_vehicle_owner_flag`; câu "bao nhiêu chủ xe" dùng bảng VF.
_CROSS_BU_STEMS: dict[str, tuple[str | None, ...]] = {
    "is_active_gsm": SPRINT2_WINDOWS,
    "is_active_vinfast": SPRINT2_WINDOWS,
    "is_cross_bu_active": SPRINT2_WINDOWS,
    "gsm_spend": SPRINT2_WINDOWS,
    "vinfast_spend": SPRINT2_WINDOWS,
    "combined_spend": SPRINT2_WINDOWS,
    "dominant_business_unit": SPRINT2_WINDOWS,
    # Hai cột dưới luỹ kế theo bản chất, không gắn cửa sổ.
    "cross_bu_engagement_score": (None,),
    "gsm_active_vehicle_owner_flag": (None,),
}


def _group(stem: str, agg: str) -> str:
    if agg == "ratio":
        return "Tỷ lệ & xu hướng"
    if "spend" in stem:
        return "Giá trị & số dư"
    if stem.startswith("is_") or stem.endswith("_flag") or "dominant" in stem or "score" in stem:
        return "Hành trình & trạng thái"
    if any(x in stem for x in ("date", "days_since", "active_day", "weekday", "daytime", "processing_time")):
        return "Thời gian & gắn kết"
    if any(x in stem for x in ("amount", "price", "discount", "battery")):
        return "Giá trị & số dư"
    if any(x in stem for x in ("accessories", "wo_", "type_")):
        return "Sản phẩm & dịch vụ"
    if "count" in stem:
        return "Hoạt động & tần suất"
    return "Hành trình & trạng thái"


def _dtype(stem: str, window: str | None) -> str:
    if stem.startswith("is_") or stem.endswith("_flag"):
        return "boolean"
    if stem == "dominant_business_unit":
        return "text"
    if stem.endswith("_score") or stem.endswith("_spend"):
        return "numeric"
    if "_date_" in stem or stem.endswith("_date"):
        return "date"
    if window in RATIO_WINDOWS:
        return "ratio"
    if "count" in stem or "days_since" in stem or "active_day_count" in stem:
        return "integer"
    return "numeric"


def _agg(stem: str, window: str | None) -> str:
    if window in RATIO_WINDOWS:
        return "ratio"
    if stem.startswith("is_") or stem.endswith("_flag"):
        return "flag"
    if stem in ("dominant_business_unit", "cross_bu_engagement_score"):
        return "derived"
    if stem.endswith("_spend"):
        return "sum"
    if "count" in stem:
        return "count"
    if stem.startswith("first_"):
        return "min"
    if stem.endswith("_max"):
        return "max"
    if stem.endswith("_min"):
        return "min"
    if "days_since" in stem:
        return "derived"
    return "sum"


def _unit(stem: str, dtype: str) -> str | None:
    if dtype == "integer" and "days" in stem:
        return "days"
    if "vehicle_purchase" in stem or "vehicle_delivered" in stem:
        return "vehicles"
    if stem.endswith("_spend"):
        return "VND"
    if "distance_km" in stem:
        return "km"
    if "processing_time" in stem:
        return "minutes"
    if "battery" in stem:
        return "kWh"
    if dtype in {"numeric", "ratio"}:
        return "VND" if any(x in stem for x in ("amount", "price")) else None
    return "transactions" if dtype == "integer" and "count" in stem else None


def _build(table: str, stems: dict[str, tuple[str | None, ...]]) -> list[Feature]:
    out: list[Feature] = []
    for stem, windows in stems.items():
        for window in windows:
            agg = _agg(stem, window)
            dtype = _dtype(stem, window)
            null_key = "zero_denominator" if agg == "ratio" else (
                # Cờ buyer/owner luôn có giá trị: FALSE nghĩa là "không phải", không
                # phải "không biết". Phân biệt này quyết định cách đọc COUNT/AVG.
                "always_present" if agg == "flag" else
                # Cross-BU: NULL = chưa từng có dữ liệu ở đơn vị đó, KHÁC hẳn "kỳ này
                # không phát sinh" (= 0). Trung bình tính lẫn hai thứ này là số sai mà
                # SQL vẫn đúng — chính là thứ Task 2.3 sinh ra để phân biệt.
                "no_history_in_unit" if stem.endswith("_spend") else
                "no_spend_to_compare" if stem in (
                    "dominant_business_unit", "cross_bu_engagement_score") else
                "never_event" if "days_since" in stem or stem.startswith("first_") else
                "no_event_in_window"
            )
            out.append(
                Feature(
                    name=f"{stem}_{window}" if window else stem,
                    table=table,
                    group=_group(stem, agg),
                    dtype=dtype,
                    metric=stem,
                    window=window,
                    agg=agg,
                    unit=_unit(stem, dtype),
                    null_meaning_key=null_key,
                    components={"stem": stem, "window": window, "table": table},
                )
            )
    return out


def all_features() -> list[Feature]:
    features = (
        _build("feature.gsm_transaction", _GSM_STEMS)
        + _build("feature.vinfast_transaction", _VF_STEMS)
        + _build("feature.vinfast_transaction", _VF_PIT_STEMS)  # Sprint 2: +16
        + _build("feature.customer_cross_bu_feature", _CROSS_BU_STEMS)  # Sprint 2: +37
    )
    if len(features) != 406:
        raise RuntimeError(f"Canonical inventory must contain 406 features, got {len(features)}")
    names = {f.name for f in features}
    if len(names) != len(features):
        # Trùng tên giữa hai bảng ⇒ generator không biết chọn bảng nào, validator lại
        # khớp theo tên nên không bắt được. Chặn ngay ở đây.
        dupes = sorted(n for n in names if sum(f.name == n for f in features) > 1)
        raise RuntimeError(f"Feature names must be unique across tables: {dupes}")
    return features


def feature_names() -> set[str]:
    return {f.name for f in all_features()}
