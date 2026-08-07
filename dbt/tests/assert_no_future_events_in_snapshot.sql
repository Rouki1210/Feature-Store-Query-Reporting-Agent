-- Không sự kiện nào của tương lai được lọt vào snapshot. Đây là test quan trọng nhất
-- của tầng silver: rò dữ liệu tương lai làm feature "đẹp lên" một cách không thể phát
-- hiện bằng mắt, và mọi con số lịch sử đều sai theo.
--
-- Mốc so sánh luôn là EVENT TIME (created_at / updated_at / status_at / handed_over_at),
-- không bao giờ là recorded_at (ADR 0002).

select 'order_state: created_at sau snapshot' as vi_pham,
       order_id::text || ' @ ' || snapshot_date::text as chi_tiet
  from {{ ref('silver_vinfast_order_state') }}
 where created_date > snapshot_date

union all
select 'order_state: updated_at sau snapshot', order_id::text || ' @ ' || snapshot_date::text
  from {{ ref('silver_vinfast_order_state') }}
 where updated_date > snapshot_date

union all
select 'vehicle_purchase: mua xe ghi nhận sau snapshot',
       order_id::text || ' @ ' || snapshot_date::text
  from {{ ref('silver_vehicle_purchase') }}
 where completed_date > snapshot_date

union all
select 'ownership: đã nhận xe sau snapshot mà vẫn tính là đã nhận',
       handover_id::text || ' @ ' || snapshot_date::text
  from {{ ref('silver_vehicle_ownership') }}
 where is_handed_over and handed_over_date > snapshot_date
