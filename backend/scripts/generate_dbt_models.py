"""Sinh hai model candidate wide của dbt từ feature_spec.py.

167 cột GSM + 202 cột VinFast. Viết tay là không tưởng và không thể review; sinh ra
thì mỗi quy tắc chỉ nằm ở MỘT chỗ trong file này. Cùng khuôn với
scripts/generate_semantic_layer.py — feature_spec.py là nguồn sự thật duy nhất.

Mỗi hàm `*_metric_sql` dưới đây là bản dịch 1-1 của `gsm_metric` / `vf_metric` trong
scripts/generate_mock_data.py. Thứ tự các nhánh `if` PHẢI giữ nguyên như bản Python:
`txn_discount_accessories_completed_count` khớp nhiều nhánh, nhánh nào chạy trước
quyết định giá trị.

Chạy (từ thư mục backend/):
    python -m scripts.generate_dbt_models
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.semantic.feature_spec import ALL_TIME, RATIO_WINDOWS, WINDOW_DAYS, all_features

OUT_DIR = Path(__file__).resolve().parents[2] / "dbt" / "models" / "int"

HEADER = """\
-- SINH TỰ ĐỘNG — KHÔNG SỬA TAY.
-- Nguồn: backend/app/semantic/feature_spec.py + backend/scripts/generate_dbt_models.py
-- Sinh lại:  cd backend && python -m scripts.generate_dbt_models
--
{doc}
--
-- alias trùng tên bảng gold để `parity_check --source dbt_work` so thẳng candidate với
-- baseline mà không cần bảng ánh xạ tên. Schema thì vẫn là dbt_work — dbt không có
-- quyền DDL trên feature.*, việc ghi sang đó là của publish_gold.py.
{{{{ config(alias='{alias}') }}}}
"""


def _win(alias: str, col: str, window: str) -> str:
    """Bộ lọc cửa sổ — bản dịch của _within() trong generate_mock_data.py.

    `snapshot - (days-1) <= ngày <= snapshot`. Vế phải đã được bảo đảm bởi bộ lọc
    as-of ở tầng silver, nên chỉ cần vế trái.
    """
    if window == ALL_TIME:
        return "true"  # luỹ kế tới snapshot; as-of của silver đã chặn phía sau
    return f"{alias}.{col} >= s.snapshot_date - {WINDOW_DAYS[window] - 1}"


def _ratio(a: str, b: str) -> str:
    """_ratio(a, b) = round(a/b, 4) nếu b khác 0, ngược lại NULL.

    CỐ Ý chia bằng float8 chứ không phải numeric, và cố ý dùng round() MỘT tham số.
    Đây là chỗ duy nhất trong toàn bộ bản port bắt chước một khiếm khuyết thay vì sửa nó,
    nên phải nói rõ vì sao.

    Bản Python tính `round(a / b, 4)`, tức phép chia float64 rồi làm tròn theo quy tắc
    half-to-even của CPython. Hai thứ đó khác numeric của Postgres ở CẢ HAI đầu:

      * numeric chia chính xác, float64 thì không. Double gần nhất với 0.23875 thực ra là
        0.2387499999999999900079… — NẰM DƯỚI điểm hoà, nên Python làm tròn xuống 0.2387
        trong khi numeric thấy đúng 0.23875 và làm tròn lên 0.2388.
      * round(numeric, n) của Postgres làm tròn RA XA SỐ 0; round(float8) một tham số dùng
        rint() của C, tức half-to-even — giống hệt Python. 9/32 = 0.28125 biểu diễn chính
        xác trong nhị phân nên là điểm hoà thật: cả hai cho 0.2812.

    Đo được trên bộ dữ liệu hiện tại: 27 ô lệch nếu dùng numeric, 0 ô nếu dùng float8.
    Chi tiết: docs/eval/parity_buoc5_lech.md.

    Mục tiêu của giai đoạn này là chứng minh bản port KHÔNG đổi hành vi, nên cổng parity
    phải trả 0 tuyệt đối — "0 trừ 27 ô đã biết" thì lần sau lệch 28 ô sẽ không ai nhận ra.
    Đổi sang phép chia decimal đúng chuẩn là việc nên làm SAU cutover, trong một commit
    riêng đo được ảnh hưởng riêng.
    """
    return (f"case when ({b}) <> 0 "
            f"then round((({a})::float8 / ({b})::float8) * 10000) / 10000 end")


# --------------------------------------------------------------------------- GSM

def _gsm_filters(stem: str, window: str) -> list[str]:
    f = [_win("t", "trip_date", window)]
    # canceled_ (1 L, tên feature) -> cancelled (2 L, raw) đã được silver ánh xạ sang
    # status_group. finished_ không có trong raw nên mock coi = completed.
    if stem.startswith("canceled_"):
        f.append("t.status_group = 'canceled'")
    elif stem.startswith(("completed_", "finished_")):
        f.append("t.status_group = 'completed'")
    if "weekday_" in stem:
        f.append("t.is_weekday")
    if "time_daytime_" in stem:
        f.append("t.is_daytime")
    if "_type_" in stem:
        service = stem.split("_type_", 1)[1].split("_txn_", 1)[0]
        f.append(f"t.service_type = '{service}'")
    return f


def gsm_metric_sql(stem: str, window: str) -> str | None:
    # Hai cột này bỏ QUA mọi bộ lọc: bản Python tính trên `tr` (mọi chuyến as-of),
    # không phải trên `rows` (đã lọc cửa sổ + trạng thái).
    if "days_since_first_txn" in stem:
        return "(s.snapshot_date - min(t.trip_date))"
    if "days_since_last_txn" in stem:
        return "(s.snapshot_date - max(t.trip_date))"

    w = " and ".join(_gsm_filters(stem, window))
    # sum([]) của Python bằng 0 còn SUM() của SQL trả NULL ⇒ phải coalesce.
    # max((), default=None) thì cả hai đều NULL ⇒ không coalesce.
    if stem.endswith("_active_day_count"):
        return f"count(distinct t.trip_date) filter (where {w})"
    if stem.endswith("_txn_count"):
        return f"count(*) filter (where {w})"
    if stem.endswith("_original_price_sum"):
        return f"coalesce(sum(t.total_fare) filter (where {w}), 0)"
    if stem.endswith("_original_price_max"):
        return f"max(t.total_fare) filter (where {w})"
    if stem.endswith("_discount_amount_sum"):
        return f"coalesce(sum(t.discount_amount) filter (where {w}), 0)"
    if stem.endswith("_trip_distance_km_sum"):
        return f"round(coalesce(sum(t.distance_km) filter (where {w}), 0), 2)"
    return None


# ----------------------------------------------------------------------- VinFast

def _vf_filters(stem: str, window: str) -> list[str]:
    f = [_win("o", "created_date", window)]
    for candidate in ("canceled", "completed", "delivered"):
        if f"_{candidate}_" in stem:
            status = "cancelled" if candidate == "canceled" else candidate
            f.append(f"o.status = '{status}'")
            break
    if "accessories" in stem:
        f.append("o.order_type = 'accessories'")
    elif "_wo_" in stem:
        f.append("o.order_type = 'work_order'")
    elif "_nvso_" in stem:
        f.append("o.order_type = 'nvso'")
    return f


def vf_metric_sql(stem: str, window: str) -> str | None:
    # Như GSM: hai cột này tính trên `od` (mọi đơn as-of), chỉ lọc trạng thái completed,
    # và đo trên updated_date chứ không phải created_date.
    if "days_since_first_completed_txn_days" in stem:
        return "(s.snapshot_date - min(o.updated_date) filter (where o.status = 'completed'))"
    if "days_since_last_completed_txn_days" in stem:
        return "(s.snapshot_date - max(o.updated_date) filter (where o.status = 'completed'))"

    w = " and ".join(_vf_filters(stem, window))
    if stem.startswith("txn_first_completed_updated_date_min"):
        return f"min(o.updated_date) filter (where {w})"
    if stem.startswith("txn_last_completed_updated_date_max"):
        return f"max(o.updated_date) filter (where {w})"
    if stem.endswith("_active_day_count"):
        return f"count(distinct o.created_date) filter (where {w})"
    if stem.endswith("_count"):
        # txn_discount_* đếm ĐƠN CÓ GIẢM GIÁ, không phải đếm đơn.
        if stem.startswith("txn_discount_"):
            return f"count(*) filter (where {w} and o.has_discount)"
        return f"count(*) filter (where {w})"
    if stem.endswith("_amount_sum"):
        return f"coalesce(sum(o.paid_amount) filter (where {w}), 0)"
    if stem.endswith("_price_sum"):
        return f"coalesce(sum(o.list_price) filter (where {w}), 0)"
    if stem.endswith("_processing_time_max"):
        return f"max(o.processing_minutes) filter (where {w})"
    if stem.endswith("_processing_time_min"):
        return f"min(o.processing_minutes) filter (where {w})"
    if stem.endswith("_battery_sum"):
        # Không coalesce: bản Python trả None khi không có giá trị battery nào.
        return f"round(sum(o.battery_kwh) filter (where {w}), 2)"
    return None


# ----------------------------------------------- VinFast point-in-time (buyer/owner)
# Không đi qua vf_metric: nguồn là silver_vehicle_purchase / silver_vehicle_ownership.
# Grain của hai bảng đó khác nhau (đơn vs bàn giao) nên phải gộp riêng ở hai CTE, nếu
# join chung một lượt thì nhân dòng.

def pit_purchase_sql(name: str) -> str | None:
    if name == "is_vehicle_buyer":
        # bool(purchases) của Python: rỗng là FALSE, không phải NULL.
        return "coalesce(bool_or(p.order_id is not null), false)"
    if name == "first_vehicle_purchase_date":
        return "min(p.completed_date)"
    if name.startswith("vehicle_purchase_completed_count_"):
        window = name[len("vehicle_purchase_completed_count_"):]
        return f"count(*) filter (where p.order_id is not null and {_win('p', 'completed_date', window)})"
    return None


def pit_owner_sql(name: str) -> str | None:
    if name == "is_vehicle_owner":
        return "coalesce(bool_or(h.is_owned), false)"
    if name == "is_vehicle_handover_scheduled":
        return "coalesce(bool_or(h.is_pending), false)"
    if name == "first_vehicle_handover_date":
        return "min(h.handed_over_date) filter (where h.is_handed_over)"
    if name == "days_since_last_vehicle_handover":
        return "(s.snapshot_date - max(h.handed_over_date) filter (where h.is_handed_over))"
    if name.startswith("vehicle_delivered_count_"):
        window = name[len("vehicle_delivered_count_"):]
        # DISTINCT vehicle_id: đếm XE, không đếm bản ghi bàn giao.
        return ("count(distinct h.vehicle_id) filter (where h.is_handed_over and "
                f"{_win('h', 'handed_over_date', window)})")
    return None


# --------------------------------------------------------------------------- render

def _column(name: str, expr: str) -> str:
    return f"    {expr} as {name}"


def _render(feats, metric_fn) -> list[str]:
    """Sinh danh sách biểu thức cột, tách cửa sổ thường và cửa sổ tỷ lệ."""
    cols = []
    for f in sorted(feats, key=lambda x: x.name):
        if f.window in RATIO_WINDOWS:
            left, right = f.window.split("_vs_", 1)
            a, b = metric_fn(f.metric, left), metric_fn(f.metric, right)
            if a is None or b is None:
                raise RuntimeError(f"Không dịch được tỷ lệ cho {f.name}")
            cols.append(_column(f.name, _ratio(a, b)))
            continue
        expr = metric_fn(f.metric, f.window)
        if expr is None:
            raise RuntimeError(f"Không dịch được {f.name} (stem={f.metric}, window={f.window})")
        cols.append(_column(f.name, expr))
    return cols


def build_gsm() -> str:
    feats = [f for f in all_features() if f.table == "feature.gsm_transaction"]
    doc = (
        "-- Bản nháp của feature.gsm_transaction. dbt test chạy TRÊN BẢNG NÀY, trước khi\n"
        "-- publish_gold.py ghi sang feature.* — CHECK constraint của bảng gold sẽ từ chối\n"
        f"-- INSERT trước khi test kịp chạy nếu đặt test ở đó. {len(feats)} cột feature."
    )
    cols = ",\n".join(
        ["    s.customer_id", "    s.snapshot_date"] + _render(feats, gsm_metric_sql)
    )
    return (
        HEADER.format(doc=doc, alias="gsm_transaction")
        + "\nselect\n"
        + cols
        + "\nfrom {{ ref('silver_customer_snapshot') }} s\n"
        "left join {{ ref('silver_gsm_trip') }} t\n"
        "       on t.customer_id = s.customer_id\n"
        # As-of: chỉ chuyến đã xảy ra tính tới snapshot. LEFT JOIN để khách không có
        # chuyến nào vẫn còn dòng (0/NULL là câu trả lời hợp lệ).
        "      and t.trip_date <= s.snapshot_date\n"
        "group by s.customer_id, s.snapshot_date\n"
    )


def build_vinfast() -> str:
    feats = [f for f in all_features() if f.table == "feature.vinfast_transaction"]
    order_feats, purchase_feats, owner_feats = [], [], []
    for f in feats:
        if pit_purchase_sql(f.name):
            purchase_feats.append(f)
        elif pit_owner_sql(f.name):
            owner_feats.append(f)
        else:
            order_feats.append(f)

    doc = (
        "-- Bản nháp của feature.vinfast_transaction. Ba CTE vì ba nguồn có GRAIN KHÁC\n"
        "-- NHAU: đơn hàng, đơn mua xe, bản ghi bàn giao. Join chung một lượt thì nhân dòng.\n"
        f"-- {len(order_feats)} cột đơn hàng + {len(purchase_feats)} cột người mua + "
        f"{len(owner_feats)} cột sở hữu."
    )

    def block(name: str, cols: list[str], join: str) -> str:
        body = ",\n".join(["    s.customer_id", "    s.snapshot_date"] + cols)
        return (f"{name} as (\n  select\n{body}\n"
                "  from {{ ref('silver_customer_snapshot') }} s\n"
                f"{join}"
                "  group by s.customer_id, s.snapshot_date\n)")

    parts = [
        block("don_hang", _render(order_feats, vf_metric_sql),
              "  left join {{ ref('silver_vinfast_order_state') }} o\n"
              "         on o.customer_id = s.customer_id\n"
              "        and o.snapshot_date = s.snapshot_date\n"),
        block("nguoi_mua",
              [_column(f.name, pit_purchase_sql(f.name)) for f in sorted(purchase_feats, key=lambda x: x.name)],
              "  left join {{ ref('silver_vehicle_purchase') }} p\n"
              "         on p.customer_id = s.customer_id\n"
              "        and p.snapshot_date = s.snapshot_date\n"),
        block("so_huu",
              [_column(f.name, pit_owner_sql(f.name)) for f in sorted(owner_feats, key=lambda x: x.name)],
              "  left join {{ ref('silver_vehicle_ownership') }} h\n"
              "         on h.customer_id = s.customer_id\n"
              "        and h.snapshot_date = s.snapshot_date\n"),
    ]
    select_cols = ",\n".join(
        ["    d.customer_id", "    d.snapshot_date"]
        + [f"    d.{f.name}" for f in sorted(order_feats, key=lambda x: x.name)]
        + [f"    m.{f.name}" for f in sorted(purchase_feats, key=lambda x: x.name)]
        + [f"    o.{f.name}" for f in sorted(owner_feats, key=lambda x: x.name)]
    )
    return (
        HEADER.format(doc=doc, alias="vinfast_transaction")
        + "\nwith "
        + ",\n\n".join(parts)
        + "\n\nselect\n"
        + select_cols
        + "\nfrom don_hang d\n"
        # Cả ba CTE đều dựng từ cùng spine nên luôn có đủ dòng — join thường là đủ,
        # không cần full outer.
        "join nguoi_mua m on m.customer_id = d.customer_id and m.snapshot_date = d.snapshot_date\n"
        "join so_huu    o on o.customer_id = d.customer_id and o.snapshot_date = d.snapshot_date\n"
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, table, sql in (
        ("int_gsm_feature_candidate.sql", "feature.gsm_transaction", build_gsm()),
        ("int_vinfast_feature_candidate.sql", "feature.vinfast_transaction", build_vinfast()),
    ):
        path = OUT_DIR / filename
        path.write_text(sql, encoding="utf-8")
        n = sum(1 for f in all_features() if f.table == table)
        print(f"  {n:>3} cột feature -> {path}")


if __name__ == "__main__":
    main()
