-- Quan hệ mua / nhận / sở hữu ở tầng feature (docs/vehicle_owner_semantics.md).
--
-- Tầng silver đã kiểm quy tắc trên từng bản ghi bàn giao. Test này kiểm ở tầng đã tổng
-- hợp theo khách — nơi mà một lỗi join hay một `bool_or` đặt sai chỗ mới lộ ra.

select 'là chủ xe nhưng chưa từng mua' as vi_pham,
       customer_id::text || ' @ ' || snapshot_date::text as chi_tiet
  from {{ ref('int_vinfast_feature_candidate') }}
 where is_vehicle_owner and not is_vehicle_buyer

union all
-- Nhận xe rồi thì không thể đang chờ giao ở cùng snapshot.
select 'vừa là chủ xe vừa đang chờ giao', customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_vinfast_feature_candidate') }}
 where is_vehicle_owner and is_vehicle_handover_scheduled
   and vehicle_delivered_count_all = 0

union all
-- Cờ phải khớp số đếm: có xe đã giao thì phải là (hoặc từng là) chủ.
select 'đã nhận xe nhưng cờ chủ xe = false', customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_vinfast_feature_candidate') }}
 where vehicle_delivered_count_all > 0 and not is_vehicle_owner
   and days_since_last_vehicle_handover is null

union all
-- Số xe đã nhận không bao giờ vượt số đơn mua đã hoàn tất.
select 'số xe nhận > số đơn mua hoàn tất', customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_vinfast_feature_candidate') }}
 where vehicle_delivered_count_all > vehicle_purchase_completed_count_all

union all
-- Ngày mua/bàn giao đầu tiên phải đi kèm cờ tương ứng.
select 'có first_vehicle_purchase_date nhưng không phải người mua',
       customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_vinfast_feature_candidate') }}
 where first_vehicle_purchase_date is not null and not is_vehicle_buyer

union all
select 'có first_vehicle_handover_date nhưng chưa nhận xe nào',
       customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_vinfast_feature_candidate') }}
 where first_vehicle_handover_date is not null and vehicle_delivered_count_all = 0
