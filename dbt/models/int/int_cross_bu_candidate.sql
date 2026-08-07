-- Bản nháp của feature.customer_cross_bu_feature. Viết tay (không sinh tự động):
-- 37 cột nhưng logic không đều nhau — dominant/score là dẫn xuất, không phải tổng hợp.
--
-- Nguồn logic: build_cross_bu() trong scripts/generate_mock_data.py.
--
-- Bảng TÍNH SẴN theo ADR 0001: agent đọc thẳng bảng này thay vì tự join GSM với VinFast,
-- nên lỗi nhân dòng không thể xảy ra. Vì vậy nó đọc lại cột đã tính của hai candidate
-- kia — đúng như bản Python đọc lại gsm_rows/vf_rows.
--
-- NULL vs 0 (docs/join_policy.md §5) là toàn bộ lý do bảng này tồn tại:
--   NULL = khách CHƯA TỪNG có dữ liệu ở đơn vị đó
--   0    = có dữ liệu nhưng kỳ này không phát sinh
-- Trộn hai thứ này thì mọi AVG đều sai trong khi SQL vẫn chạy.

-- alias trùng tên bảng gold để `parity_check --source dbt_work` so thẳng với baseline.
{{ config(alias='customer_cross_bu_feature') }}

{% set windows = ['l1m', 'l3m', 'l6m', 'l12m'] %}

with gsm_lich_su as (
    -- ever_gsm: đã từng có chuyến (MỌI trạng thái) tính tới snapshot.
    -- gsm_*_all: luỹ kế, chỉ chuyến completed. Hai bảng BU dừng ở l12m nên cửa sổ
    -- `all` phải tính thẳng từ tầng silver.
    select
        s.customer_id,
        s.snapshot_date,
        count(t.trip_id) > 0 as ever_gsm,
        coalesce(sum(t.total_fare) filter (where t.status_group = 'completed'), 0) as spend_all,
        count(*) filter (where t.status_group = 'completed') as cnt_all
    from {{ ref('silver_customer_snapshot') }} s
    left join {{ ref('silver_gsm_trip') }} t
           on t.customer_id = s.customer_id
          and t.trip_date <= s.snapshot_date
    group by s.customer_id, s.snapshot_date
),

vf_lich_su as (
    -- ever_vf đọc THẲNG raw chứ không qua silver_vinfast_order_state: bản Python chỉ
    -- lọc `created_at <= snapshot`, trong khi order_state lọc cả `updated_at`. Dùng
    -- order_state ở đây sẽ coi khách có đơn đang chạy là "chưa từng có VinFast" và
    -- biến 0 thành NULL — sai đúng chỗ mà bảng này sinh ra để phân biệt.
    select
        s.customer_id,
        s.snapshot_date,
        count(o.order_id) > 0 as ever_vf
    from {{ ref('silver_customer_snapshot') }} s
    left join {{ source('raw', 'vinfast_orders') }} o
           on o.customer_id = s.customer_id
          and (o.created_at at time zone '{{ var("business_timezone") }}')::date <= s.snapshot_date
    group by s.customer_id, s.snapshot_date
),

vf_luy_ke as (
    -- Luỹ kế `all` cho VinFast: đơn completed, đã qua bộ lọc as-of của order_state.
    select
        s.customer_id,
        s.snapshot_date,
        coalesce(sum(o.paid_amount) filter (where o.status = 'completed'), 0) as spend_all,
        count(*) filter (where o.status = 'completed') as cnt_all
    from {{ ref('silver_customer_snapshot') }} s
    left join {{ ref('silver_vinfast_order_state') }} o
           on o.customer_id = s.customer_id
          and o.snapshot_date = s.snapshot_date
    group by s.customer_id, s.snapshot_date
),

chi_tieu as (
    -- Tách riêng tầng này để `combined` và `dominant` bên dưới không phải lặp lại
    -- biểu thức CASE của từng cửa sổ.
    select
        s.customer_id,
        s.snapshot_date,
        {% for w in windows %}
        case when gl.ever_gsm then g.completed_original_price_sum_{{ w }} end as gsm_spend_{{ w }},
        case when vl.ever_vf  then v.txn_completed_amount_sum_{{ w }} end as vinfast_spend_{{ w }},
        coalesce(g.completed_txn_count_{{ w }}, 0) <> 0 as is_active_gsm_{{ w }},
        coalesce(v.txn_completed_count_{{ w }}, 0) <> 0 as is_active_vinfast_{{ w }},
        {% endfor %}
        case when gl.ever_gsm then gl.spend_all end as gsm_spend_all,
        case when vl.ever_vf  then vk.spend_all end as vinfast_spend_all,
        gl.cnt_all > 0 as is_active_gsm_all,
        vk.cnt_all > 0 as is_active_vinfast_all,
        coalesce(v.is_vehicle_owner, false) as is_vehicle_owner
    from {{ ref('silver_customer_snapshot') }} s
    join gsm_lich_su gl on gl.customer_id = s.customer_id and gl.snapshot_date = s.snapshot_date
    join vf_lich_su  vl on vl.customer_id = s.customer_id and vl.snapshot_date = s.snapshot_date
    join vf_luy_ke   vk on vk.customer_id = s.customer_id and vk.snapshot_date = s.snapshot_date
    join {{ ref('int_gsm_feature_candidate') }}     g on g.customer_id = s.customer_id and g.snapshot_date = s.snapshot_date
    join {{ ref('int_vinfast_feature_candidate') }} v on v.customer_id = s.customer_id and v.snapshot_date = s.snapshot_date
)

select
    customer_id,
    snapshot_date,
    {% for w in windows + ['all'] %}
    is_active_gsm_{{ w }},
    is_active_vinfast_{{ w }},
    is_active_gsm_{{ w }} and is_active_vinfast_{{ w }} as is_cross_bu_active_{{ w }},
    gsm_spend_{{ w }},
    vinfast_spend_{{ w }},
    -- NULL chỉ khi CẢ HAI phía đều chưa từng có dữ liệu; một phía có thì bên kia coi là 0.
    case
        when gsm_spend_{{ w }} is null and vinfast_spend_{{ w }} is null then null
        else coalesce(gsm_spend_{{ w }}, 0) + coalesce(vinfast_spend_{{ w }}, 0)
    end as combined_spend_{{ w }},
    -- Không có gì để so sánh thì để NULL, KHÔNG mặc định về GSM.
    case
        when coalesce(coalesce(gsm_spend_{{ w }}, 0) + coalesce(vinfast_spend_{{ w }}, 0), 0) = 0 then null
        when coalesce(gsm_spend_{{ w }}, 0) = coalesce(vinfast_spend_{{ w }}, 0) then 'TIE'
        when coalesce(gsm_spend_{{ w }}, 0) >  coalesce(vinfast_spend_{{ w }}, 0) then 'GSM'
        else 'VINFAST'
    end as dominant_business_unit_{{ w }},
    {% endfor %}
    -- Score chốt trên l1m (kỳ gần nhất) để đọc là "đang cân bằng hay đang dồn một phía",
    -- không phải trung bình cả năm. 0 = một phía, 1 = cân bằng hoàn toàn.
    case
        when coalesce(gsm_spend_l1m, 0) + coalesce(vinfast_spend_l1m, 0) = 0 then null
        when coalesce(gsm_spend_l1m, 0) = coalesce(vinfast_spend_l1m, 0) then 1.0
        else round(
            least(coalesce(gsm_spend_l1m, 0), coalesce(vinfast_spend_l1m, 0))
          / greatest(coalesce(gsm_spend_l1m, 0), coalesce(vinfast_spend_l1m, 0)), 4)
    end as cross_bu_engagement_score,
    -- "Chủ xe VinFast có đang đi GSM không" — dùng cột này thay vì join sang bảng VF.
    is_active_gsm_l1m and is_vehicle_owner as gsm_active_vehicle_owner_flag
from chi_tieu
