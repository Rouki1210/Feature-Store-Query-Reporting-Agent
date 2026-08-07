-- Giả định mà silver_vinfast_order_state dựa vào để dùng min(status_at).
--
-- 1. `completed` và `cancelled` là hai trạng thái KẾT THÚC loại trừ nhau: một đơn chỉ
--    được có đúng một (docs/vehicle_owner_semantics.md §5). Có cả hai thì "khách này
--    đã mua chưa" không có câu trả lời đúng.
-- 2. Mỗi đơn xe chỉ chạm `completed` MỘT lần. silver_vinfast_order_state lấy
--    min(status_at) cho mỗi order — nếu có nhiều lần completed thì các lần sau bị nuốt
--    và vehicle_purchase_completed_count_* đếm thiếu. Test này là lý do được phép
--    dùng min() ở đó.

select 'đơn có cả completed lẫn cancelled' as vi_pham, order_id::text as chi_tiet
  from {{ source('raw', 'vinfast_order_status_history') }}
 where status in ('completed', 'cancelled')
 group by order_id
having count(distinct status) > 1

union all
select 'đơn xe chạm completed nhiều lần', h.order_id::text
  from {{ source('raw', 'vinfast_order_status_history') }} h
  join {{ source('raw', 'vinfast_orders') }} o on o.order_id = h.order_id
 where h.status = 'completed' and o.order_type = 'vehicle'
 group by h.order_id
having count(*) > 1
