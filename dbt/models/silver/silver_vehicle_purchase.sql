-- Tư cách NGƯỜI MUA xe tại từng snapshot. Grain: (order_id, snapshot_date).
--
-- Vì sao tách khỏi silver_vinfast_order_state thay vì thêm một cột vào đó:
-- order_state lọc as-of theo CẢ created_at LẪN updated_at của đơn. Với đơn xe đã giao,
-- generate_raw() gán `updated_at = handed_over_at` (bàn giao xảy ra sau khi đơn hoàn tất
-- 5–60 ngày). Đem bộ lọc đó áp cho tư cách người mua thì một đơn đã `completed` từ
-- tháng 3 nhưng giao tháng 5 sẽ KHÔNG được tính là mua ở snapshot tháng 4 — sai, và
-- sai đúng theo kiểu nguy hiểm nhất: nó làm "mua" phụ thuộc vào "nhận", trong khi cả
-- dự án được xây trên chỗ phân biệt hai thứ đó (docs/vehicle_owner_semantics.md).
--
-- Đo được: 257 đơn dính, làm lệch 59 dòng is_vehicle_buyer so với bản Python.
--
-- Ở đây chỉ có MỘT bộ lọc point-in-time duy nhất: status_at <= snapshot.
-- Không recorded_at (ADR 0002), không vinfast_orders.status, không updated_at.

with purchase as (
    select
        h.order_id,
        o.customer_id,
        -- Mỗi đơn xe chỉ chạm 'completed' đúng một lần — được bảo đảm bằng
        -- tests/assert_order_status_history_terminal.sql. min() ở đây an toàn nhờ
        -- test đó, không phải nhờ may mắn.
        min(h.status_at) as completed_at
    from {{ source('raw', 'vinfast_order_status_history') }} h
    join {{ source('raw', 'vinfast_orders') }} o on o.order_id = h.order_id
    where h.status = 'completed'
      and o.order_type = 'vehicle'
    group by h.order_id, o.customer_id
)

select
    p.order_id,
    p.customer_id,
    s.snapshot_date,
    p.completed_at,
    (p.completed_at at time zone '{{ var("business_timezone") }}')::date as completed_date
from purchase p
cross join {{ source('raw', 'feature_snapshot') }} s
where (p.completed_at at time zone '{{ var("business_timezone") }}')::date <= s.snapshot_date
