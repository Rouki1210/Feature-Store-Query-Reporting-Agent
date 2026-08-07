-- Ba luật của quyền sở hữu xe (docs/vehicle_owner_semantics.md).
--
-- 1. Đã trả xe tính tới snapshot thì KHÔNG còn là chủ tại snapshot đó.
--    (Đảo SAU snapshot thì vẫn là chủ — đó là ca ngược lại, test ở dưới.)
-- 2. Chủ xe phải là người đứng đơn. Handover ghi customer_id riêng, lệch với đơn là
--    dữ liệu hỏng và mọi câu hỏi "khách nào đang sở hữu xe" đều sai.
-- 3. "Đã hẹn lịch" và "đã nhận" loại trừ nhau tại cùng một snapshot: hẹn không phải
--    là sở hữu, và đã nhận rồi thì không còn đang chờ.

select 'đã trả xe nhưng vẫn tính là chủ' as vi_pham,
       handover_id::text || ' @ ' || snapshot_date::text as chi_tiet
  from {{ ref('silver_vehicle_ownership') }}
 where is_owned
   and reversed_at is not null
   and (reversed_at at time zone '{{ var("business_timezone") }}')::date <= snapshot_date

union all
select 'chủ xe không khớp khách của đơn', o.handover_id::text || ' @ ' || o.snapshot_date::text
  from {{ ref('silver_vehicle_ownership') }} o
  join {{ source('raw', 'vinfast_orders') }} v on v.order_id = o.order_id
 where v.customer_id <> o.customer_id

union all
select 'vừa đang chờ giao vừa đã nhận', handover_id::text || ' @ ' || snapshot_date::text
  from {{ ref('silver_vehicle_ownership') }}
 where is_pending and is_handed_over

union all
-- Ca ngược: đảo SAU snapshot thì tại snapshot đó VẪN phải là chủ. Không có test này
-- thì một bộ lọc `handover_status <> 'reversed'` (sai, vì dùng trạng thái hiện tại)
-- vẫn lọt qua ba luật trên.
select 'đảo sau snapshot mà đã mất quyền chủ', handover_id::text || ' @ ' || snapshot_date::text
  from {{ ref('silver_vehicle_ownership') }}
 where is_handed_over
   and reversed_at is not null
   and (reversed_at at time zone '{{ var("business_timezone") }}')::date > snapshot_date
   and not is_owned
