-- Hồi quy đã từng xảy ra thật: tư cách NGƯỜI MUA không được phụ thuộc vào ngày NHẬN xe.
--
-- generate_raw() gán `vinfast_orders.updated_at = handed_over_at` cho đơn xe đã giao,
-- nên một đơn `completed` tháng 3 mà giao tháng 5 sẽ có updated_at = tháng 5. Bản
-- silver đầu tiên tính buyer từ silver_vinfast_order_state (có lọc as-of trên
-- updated_at) và làm mất 257 đơn, lệch 59 dòng is_vehicle_buyer so với bản Python.
--
-- Test này khẳng định điều ngược lại: MỌI đơn xe chạm 'completed' trước snapshot đều
-- phải có mặt trong silver_vehicle_purchase tại snapshot đó, bất kể updated_at nằm đâu.
-- Nó sẽ đỏ ngay nếu ai đó "gộp lại cho gọn" hai model.

select
    o.order_id,
    s.snapshot_date,
    (h.status_at   at time zone '{{ var("business_timezone") }}')::date as ngay_hoan_tat,
    (o.updated_at  at time zone '{{ var("business_timezone") }}')::date as ngay_cap_nhat_don
from {{ source('raw', 'vinfast_orders') }} o
join {{ source('raw', 'vinfast_order_status_history') }} h
      on h.order_id = o.order_id and h.status = 'completed'
cross join {{ source('raw', 'feature_snapshot') }} s
left join {{ ref('silver_vehicle_purchase') }} p
      on p.order_id = o.order_id and p.snapshot_date = s.snapshot_date
where o.order_type = 'vehicle'
  and (h.status_at at time zone '{{ var("business_timezone") }}')::date <= s.snapshot_date
  and p.order_id is null
