{{ config(tags = ['dev_only']) }}

-- Bộ dữ liệu phải CÓ các ca biên, nếu không mọi test khác pass một cách rỗng nghĩa.
--
-- Đây là bản port của data_quality_errors()/cross_bu_errors() trong
-- scripts/generate_mock_data.py, phần kiểm ĐỘ PHỦ chứ không phải kiểm bất biến.
-- Các bất biến (owner ⊆ buyer, cửa sổ luỹ kế, NULL vs 0) đã có test riêng; test này
-- chỉ trả lời một câu: "những test kia có gì để kiểm không?"
--
-- tag `dev_only` vì nó gắn với BỘ MOCK, không phải với pipeline: warehouse thật hoàn
-- toàn có thể hợp lệ mà thiếu một cohort. Không chạy nó trên dữ liệu thật.
--   dbt build --exclude tag:dev_only

with kiem as (

    select 'không có khách đã mua xe mà chưa nhận' as thieu_ca
     where not exists (
        select 1 from {{ ref('int_vinfast_feature_candidate') }}
         where is_vehicle_buyer and not is_vehicle_owner)

    union all
    -- Nếu ai đó bỏ ánh xạ "canceled" (1 chữ L, tên feature) <-> "cancelled" (2 chữ L,
    -- CHECK constraint của raw) thì MỌI cột canceled_* về 0 và không test nào khác đỏ.
    select 'không khách nào có chuyến GSM bị huỷ (ánh xạ canceled/cancelled hỏng?)'
     where not exists (
        select 1 from {{ ref('int_gsm_feature_candidate') }} where canceled_txn_count_l12m > 0)

    union all
    select 'không khách nào có đơn VinFast bị huỷ (ánh xạ canceled/cancelled hỏng?)'
     where not exists (
        select 1 from {{ ref('int_vinfast_feature_candidate') }} where txn_canceled_count_l12m > 0)

    union all
    -- Cửa sổ `all` tính thẳng từ silver, không phải lấy tạm l12m. Không có khách nào
    -- `all` > `l12m` thì hai cách tính đang cho cùng kết quả và test không phân biệt được.
    select 'không khách nào có chi tiêu ngoài l12m (cửa sổ `all` không được kiểm)'
     where not exists (
        select 1 from {{ ref('int_cross_bu_candidate') }} where gsm_spend_all > gsm_spend_l12m)

    union all
    select 'không có khách hoạt động CẢ HAI đơn vị'
     where not exists (
        select 1 from {{ ref('int_cross_bu_candidate') }} where is_cross_bu_active_l1m)

    union all
    select 'không có khách chỉ hoạt động GSM'
     where not exists (
        select 1 from {{ ref('int_cross_bu_candidate') }}
         where is_active_gsm_l1m and not is_active_vinfast_l1m)

    union all
    select 'không có khách chỉ hoạt động VinFast'
     where not exists (
        select 1 from {{ ref('int_cross_bu_candidate') }}
         where is_active_vinfast_l1m and not is_active_gsm_l1m)

    union all
    -- Không có khách genuine-null thì test phân biệt NULL với 0 là vô nghĩa.
    select 'không có khách chưa từng mua VinFast (NULL semantics không được kiểm)'
     where not exists (
        select 1 from {{ ref('int_cross_bu_candidate') }} where vinfast_spend_l1m is null)

    union all
    -- Sự kiện về trễ (recorded_at >> status_at) là lý do ADR 0002 tồn tại.
    select 'không có sự kiện nào về trễ quá 7 ngày (ADR 0002 không được kiểm)'
     where not exists (
        select 1 from {{ source('raw', 'vinfast_order_status_history') }}
         where recorded_at > status_at + interval '7 days')

    union all
    -- Bàn giao bị đảo: nguồn của ca "đảo sau snapshot vẫn là chủ".
    select 'không có bản ghi bàn giao nào bị đảo'
     where not exists (
        select 1 from {{ source('raw', 'vinfast_vehicle_handover') }} where reversed_at is not null)
)

select * from kiem
