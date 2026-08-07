-- Trạng thái đơn VinFast TẠI TỪNG SNAPSHOT. Grain: (order_id, snapshot_date).
--
-- Đây là chỗ quy tắc as-of được viết ra tường minh thay vì nằm ẩn trong list
-- comprehension. Tương đương biến `od` trong build_features():
--
--     od = [r for r in orders_by[cid]
--           if r["created_at"].date() <= snapshot and r["updated_at"].date() <= snapshot]
--
-- Vì sao dùng vinfast_orders.status chứ không dựng lại trạng thái từ status history:
-- bộ lọc as-of đã loại mọi đơn có updated_at > snapshot, nên `status` còn lại chính là
-- trạng thái tại thời điểm updated_at <= snapshot. Không rò dữ liệu tương lai.
-- Riêng buyer/owner của XE thì KHÔNG được lấy từ model này: bộ lọc as-of ở đây bao gồm
-- cả updated_at, mà với đơn xe đã giao updated_at = ngày bàn giao. Dùng nó cho tư cách
-- người mua sẽ làm "mua" phụ thuộc vào "nhận".
-- Xem silver_vehicle_purchase và silver_vehicle_ownership.
--
-- MÚI GIỜ: xem ghi chú trong silver_gsm_trip.

select
    o.order_id,
    o.customer_id,
    s.snapshot_date,
    o.order_type,
    o.status,
    o.created_at,
    o.updated_at,
    (o.created_at at time zone '{{ var("business_timezone") }}')::date as created_date,
    (o.updated_at at time zone '{{ var("business_timezone") }}')::date as updated_date,
    o.list_price,
    o.paid_amount,
    o.battery_kwh,

    -- feature `txn_discount_*_count` đếm đơn có giảm giá.
    (o.list_price > o.paid_amount) as has_discount,

    -- feature `*_processing_time_{min,max}`, đơn vị PHÚT.
    extract(epoch from (o.updated_at - o.created_at)) / 60.0 as processing_minutes

from {{ source('raw', 'vinfast_orders') }} o
cross join {{ source('raw', 'feature_snapshot') }} s
-- As-of: cả hai mốc phải <= snapshot. Đơn còn đang chạy tại snapshot bị loại HOÀN
-- TOÀN, đúng như bản Python — không phải chỉ loại phần trạng thái.
where (o.created_at at time zone '{{ var("business_timezone") }}')::date <= s.snapshot_date
  and (o.updated_at at time zone '{{ var("business_timezone") }}')::date <= s.snapshot_date
