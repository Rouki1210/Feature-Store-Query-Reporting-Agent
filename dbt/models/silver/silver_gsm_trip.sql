-- Trip GSM đã chuẩn hoá: giữ nguyên grain 1 dòng / trip, chỉ thêm các cờ mà tầng
-- tổng hợp cần. Không cross join snapshot ở đây — candidate lọc theo cửa sổ khi join.
--
-- Nguồn logic: gsm_metric() trong scripts/generate_mock_data.py.
--
-- MÚI GIỜ: Postgres extract() trên timestamptz dùng timezone của SESSION — cùng một
-- truy vấn chạy ở hai máy cấu hình khác nhau cho ra ngày và giờ khác nhau, và parity
-- fail mà không rõ vì sao. Nên mọi chỗ đều ép múi giờ tường minh qua biến
-- `business_timezone` (dbt_project.yml), không bao giờ để mặc định.
-- Hiện là UTC để khớp bản Python (nó gọi .date()/.hour/.isoweekday() trên datetime
-- UTC-aware). Warehouse thật đổi biến đó, không sửa file này.

with trip as (
    select
        trip_id,
        customer_id,
        trip_start_time,
        trip_start_time at time zone '{{ var("business_timezone") }}' as start_local,
        status,
        service_type,
        distance_km,
        duration_min,
        -- Giá gốc trước giảm giá: feature `*_original_price_*` đọc total_fare.
        total_fare,
        discount_amount,
        paid_amount
    from {{ source('raw', 'gsm_trips') }}
)

select
    trip_id,
    customer_id,
    trip_start_time,
    start_local::date as trip_date,
    status,

    -- Tên feature dùng "canceled" (1 chữ L, theo workbook) còn raw status là
    -- "cancelled" (2 chữ L, theo CHECK constraint). "finished" không tồn tại trong
    -- raw nên mock coi nó = completed. Ánh xạ ở một chỗ duy nhất tại đây; thiếu nó
    -- thì mọi feature canceled_* bằng 0.
    case
        when status = 'cancelled' then 'canceled'
        when status = 'completed' then 'completed'
        else 'other'
    end as status_group,

    -- Thứ 2..6. isoweekday() < 6 của Python == isodow < 6 của Postgres.
    extract(isodow from start_local) < 6 as is_weekday,
    -- 6 <= hour < 18.
    extract(hour from start_local) >= 6 and extract(hour from start_local) < 18 as is_daytime,

    service_type,
    distance_km,
    duration_min,
    total_fare,
    discount_amount,
    paid_amount
from trip
