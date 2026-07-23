"""Đặc tả feature — NGUỒN CHÂN LÝ DUY NHẤT.

Cả bộ sinh mock data (derive feature từ raw events) và semantic layer đều đọc
từ đây, nên tên cột trong DB luôn khớp tên feature trong semantic layer.

Ngữ pháp tên feature (CLAUDE.md mục 2):
    {table}_{filter}_{metric}_{aggregation}_{window}

Trọng tâm là `global_loyalty` — cầu nối liên PnL: điểm khách EARN ở GSM và BURN
ở VinFast nằm cùng một bảng, cùng một khách. Đây là năng lực khác biệt của dự án
nên được ưu tiên phủ đầy đủ.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# --- Bảng trong phạm vi (3 bảng, mục 2). gsm_event bị hoãn có chủ đích. ---
TABLES: dict[str, dict[str, str]] = {
    "gsm_transaction": {"unit": "GSM", "vi": "GSM — di chuyển & giao hàng"},
    "vinfast_transaction": {"unit": "VinFast", "vi": "VinFast — xe & phụ kiện"},
    "global_loyalty": {"unit": "Global", "vi": "Điểm thưởng liên PnL (cầu nối)"},
}

# 7 nhóm feature có sẵn trong dữ liệu nguồn (mục 4 — tiered retrieval).
GROUPS = [
    "Giá trị & số dư",
    "Hành trình & trạng thái",
    "Thời gian & gắn kết",
    "Tỷ lệ & xu hướng",
    "Kênh & ngữ cảnh",
    "Sản phẩm & dịch vụ",
    "Hoạt động & tần suất",
]

# Cửa sổ thời gian dùng cho scaffold. Ngữ pháp đầy đủ còn daily/l1w/l2w — mở rộng
# bằng cách thêm vào đây; bộ derive & describer tự sinh theo.
WINDOWS = ["l1m", "l3m", "l6m", "l12m"]
# Feature tỷ lệ TÍNH SẴN — luôn ưu tiên hơn chia hai cột trong SQL (mục 2).
RATIOS = [("l1m", "l3m"), ("l1m", "l12m")]

# 11 PnL trong cầu nối loyalty (mục 2).
PNLS = [
    "gsm", "vinfast", "vinhomes", "vinmec", "vinpearl", "vinschool",
    "vinclub", "vincomretail", "merchant", "vapp", "fgf",
]


@dataclass
class Feature:
    """Một feature đã phân giải thành các thành phần.

    `components` mang đủ thông tin để (a) describer sinh mô tả tiếng Việt và
    (b) bộ mock derive tính đúng cột đó từ raw events.
    """

    name: str
    table: str
    group: str
    dtype: str  # "numeric" | "categorical"
    components: dict[str, Any] = field(default_factory=dict)


# --- Chỉ định base-metric cho hai bảng giao dịch ---
# metric_token: (aggregation_token, group, source_field, vi_metric)
_TXN_METRICS: dict[str, dict[str, tuple[str, str, str, str]]] = {
    "gsm_transaction": {
        "txn": ("count", "Hoạt động & tần suất", "*", "số chuyến hoàn thành"),
        "gmv": ("sum", "Giá trị & số dư", "original_price", "tổng giá trị giao dịch (GMV)"),
        "discount": ("sum", "Giá trị & số dư", "discount", "tổng chiết khấu"),
        "distance_km": ("sum", "Hành trình & trạng thái", "distance_km", "tổng quãng đường (km)"),
    },
    "vinfast_transaction": {
        "txn": ("count", "Hoạt động & tần suất", "*", "số đơn hoàn thành"),
        "gmv": ("sum", "Giá trị & số dư", "original_price", "tổng giá trị đơn hàng (GMV)"),
        "discount": ("sum", "Giá trị & số dư", "discount", "tổng chiết khấu"),
    },
}

# Bảng nguồn (raw events) cho mỗi bảng giao dịch.
_TXN_SOURCE = {
    "gsm_transaction": "gsm_trips",
    "vinfast_transaction": "vinfast_orders",
}


def _txn_features() -> list[Feature]:
    out: list[Feature] = []
    for table, metrics in _TXN_METRICS.items():
        source = _TXN_SOURCE[table]
        for metric, (agg, group, src_field, vi_metric) in metrics.items():
            for w in WINDOWS:
                name = f"{table}_completed_{metric}_{agg}_{w}"
                out.append(Feature(
                    name=name, table=table, group=group, dtype="numeric",
                    components={
                        "kind": "txn_base", "source": source, "metric": metric,
                        "agg": agg, "src_field": src_field, "window": w,
                        "vi_metric": vi_metric, "filter": "completed",
                    },
                ))
            # Feature tỷ lệ tính sẵn.
            for num, den in RATIOS:
                name = f"{table}_completed_{metric}_{agg}_{num}_vs_{den}"
                out.append(Feature(
                    name=name, table=table, group="Tỷ lệ & xu hướng", dtype="numeric",
                    components={
                        "kind": "ratio", "source": source, "metric": metric,
                        "agg": agg, "src_field": src_field,
                        "num_window": num, "den_window": den, "vi_metric": vi_metric,
                    },
                ))
    return out


def _loyalty_features() -> list[Feature]:
    out: list[Feature] = []
    for pnl in PNLS:
        for direction in ("earn", "burn"):
            for metric, agg in (("pts", "sum"), ("txn", "count")):
                group = "Giá trị & số dư" if metric == "pts" else "Hoạt động & tần suất"
                for w in WINDOWS:
                    name = f"global_loyalty_pnl_{pnl}_{direction}_completed_{metric}_{agg}_{w}"
                    out.append(Feature(
                        name=name, table="global_loyalty", group=group, dtype="numeric",
                        components={
                            "kind": "loyalty", "pnl": pnl, "direction": direction,
                            "metric": metric, "agg": agg, "window": w,
                        },
                    ))
    # PnL chủ đạo — CHỈ tồn tại ở l6m/l12m (mục 2, ràng buộc quan trọng).
    for direction in ("earn", "burn"):
        for w in ("l6m", "l12m"):
            name = f"global_loyalty_primary_{direction}_pnl_{w}"
            out.append(Feature(
                name=name, table="global_loyalty", group="Kênh & ngữ cảnh",
                dtype="categorical",
                components={"kind": "loyalty_primary", "direction": direction, "window": w},
            ))
    return out


def all_features() -> list[Feature]:
    """Toàn bộ feature trong phạm vi (đã phân giải thành phần)."""
    return _txn_features() + _loyalty_features()
