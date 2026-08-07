-- Cửa sổ dài phải chứa cửa sổ ngắn: l1m <= l3m <= l6m <= l12m.
--
-- Đây là test bắt lỗi cửa sổ hiệu quả nhất. Sai một dấu trong biểu thức
-- `snapshot_date - (days-1)` thì giá trị vẫn "trông hợp lý" — vẫn là số, vẫn không âm,
-- vẫn có phân phối đẹp — nhưng quan hệ bao hàm giữa các cửa sổ sẽ vỡ. Không có test này
-- thì lỗi đó chỉ lộ ra khi có người thắc mắc "sao doanh thu 3 tháng lại nhỏ hơn 1 tháng".
--
-- Chỉ liệt kê stem CỘNG DỒN (count/sum/active_day_count) và stem `_max`. Cố tình bỏ:
--   *_processing_time_min  — min trên tập lớn hơn thì NHỎ đi, chiều ngược lại
--   days_since_*           — không gắn cửa sổ theo nghĩa cộng dồn
--   *_vs_*                 — là tỷ lệ, không phải luỹ kế

{% set gsm_stems = [
    'canceled_original_price_sum', 'canceled_original_price_max',
    'canceled_txn_active_day_count', 'canceled_txn_count',
    'canceled_weekday_original_price_sum', 'canceled_weekday_txn_count',
    'completed_discount_amount_sum', 'completed_original_price_sum',
    'completed_original_price_max', 'completed_trip_distance_km_sum',
    'completed_txn_active_day_count', 'completed_txn_count',
    'completed_weekday_original_price_sum', 'completed_weekday_txn_count',
    'finished_original_price_sum', 'finished_original_price_max',
    'finished_time_daytime_original_price_sum', 'finished_time_daytime_txn_count',
    'finished_txn_active_day_count', 'finished_txn_count',
    'finished_weekday_original_price_sum', 'finished_weekday_txn_count',
] %}

{% set vf_stems = [
    'txn_canceled_active_day_count', 'txn_canceled_amount_sum', 'txn_canceled_count',
    'txn_canceled_price_sum', 'txn_canceled_processing_time_max',
    'txn_completed_active_day_count', 'txn_completed_amount_sum', 'txn_completed_count',
    'txn_completed_price_sum', 'txn_completed_processing_time_max',
    'txn_discount_canceled_count', 'txn_discount_completed_count',
    'txn_discount_delivered_count',
] %}

{% set steps = [('l1m', 'l3m'), ('l3m', 'l6m'), ('l6m', 'l12m')] %}

{% for stem in gsm_stems %}{% for a, b in steps %}
select 'gsm: {{ stem }}  {{ a }} > {{ b }}' as vi_pham,
       customer_id::text || ' @ ' || snapshot_date::text as chi_tiet,
       {{ stem }}_{{ a }}::text as ngan,
       {{ stem }}_{{ b }}::text as dai
  from {{ ref('int_gsm_feature_candidate') }}
 where {{ stem }}_{{ a }} > {{ stem }}_{{ b }}
union all
{% endfor %}{% endfor %}

{% for stem in vf_stems %}{% for a, b in steps %}
select 'vinfast: {{ stem }}  {{ a }} > {{ b }}',
       customer_id::text || ' @ ' || snapshot_date::text,
       {{ stem }}_{{ a }}::text, {{ stem }}_{{ b }}::text
  from {{ ref('int_vinfast_feature_candidate') }}
 where {{ stem }}_{{ a }} > {{ stem }}_{{ b }}
{% if not loop.last %}union all{% endif %}
{% endfor %}{% if not loop.last %}union all{% endif %}{% endfor %}
