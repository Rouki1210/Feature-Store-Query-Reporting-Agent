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


def _group(stem: str, agg: str) -> str:
    if agg == "ratio":
        return "Tỷ lệ & xu hướng"
    if any(x in stem for x in ("date", "days_since", "active_day", "weekday", "daytime", "processing_time")):
        return "Thời gian & gắn kết"
    if any(x in stem for x in ("amount", "price", "discount", "battery")):
        return "Giá trị & số dư"
    if any(x in stem for x in ("accessories", "wo_", "type_")):
        return "Sản phẩm & dịch vụ"
    if "count" in stem:
        return "Hoạt động & tần suất"
    return "Hành trình & trạng thái"


def _dtype(stem: str, window: str) -> str:
    if "_date_" in stem:
        return "date"
    if window in RATIO_WINDOWS:
        return "ratio"
    if "count" in stem or "days_since" in stem or "active_day_count" in stem:
        return "integer"
    return "numeric"


def _agg(stem: str, window: str) -> str:
    if window in RATIO_WINDOWS:
        return "ratio"
    if "count" in stem:
        return "count"
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
    if "distance_km" in stem:
        return "km"
    if "processing_time" in stem:
        return "minutes"
    if "battery" in stem:
        return "kWh"
    if dtype in {"numeric", "ratio"}:
        return "VND" if any(x in stem for x in ("amount", "price")) else None
    return "transactions" if dtype == "integer" and "count" in stem else None


def _build(table: str, stems: dict[str, tuple[str, ...]]) -> list[Feature]:
    out: list[Feature] = []
    for stem, windows in stems.items():
        for window in windows:
            agg = _agg(stem, window)
            dtype = _dtype(stem, window)
            null_key = "zero_denominator" if agg == "ratio" else (
                "never_event" if "days_since" in stem else "no_event_in_window"
            )
            out.append(
                Feature(
                    name=f"{stem}_{window}",
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
    features = _build("feature.gsm_transaction", _GSM_STEMS) + _build(
        "feature.vinfast_transaction", _VF_STEMS
    )
    if len(features) != 353:
        raise RuntimeError(f"Canonical inventory must contain 353 features, got {len(features)}")
    return features


def feature_names() -> set[str]:
    return {f.name for f in all_features()}
