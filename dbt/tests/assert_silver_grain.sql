-- Grain của cả 4 model silver trong một test. Gộp lại vì cùng một loại lỗi: model
-- nhân dòng do join sai. Gộp cũng tránh phải kéo về dbt_utils chỉ để dùng
-- unique_combination_of_columns.
--
-- Trả về dòng nào là model đó sai grain.

select 'silver_customer_snapshot: (customer_id, snapshot_date)' as grain_bi_pha,
       customer_id::text || ' | ' || snapshot_date::text as khoa,
       count(*) as so_dong
  from {{ ref('silver_customer_snapshot') }}
 group by 1, 2 having count(*) > 1

union all
select 'silver_gsm_trip: (trip_id)', trip_id::text, count(*)
  from {{ ref('silver_gsm_trip') }}
 group by 1, 2 having count(*) > 1

union all
select 'silver_vinfast_order_state: (order_id, snapshot_date)',
       order_id::text || ' | ' || snapshot_date::text, count(*)
  from {{ ref('silver_vinfast_order_state') }}
 group by 1, 2 having count(*) > 1

union all
select 'silver_vehicle_ownership: (handover_id, snapshot_date)',
       handover_id::text || ' | ' || snapshot_date::text, count(*)
  from {{ ref('silver_vehicle_ownership') }}
 group by 1, 2 having count(*) > 1

union all
select 'silver_vehicle_purchase: (order_id, snapshot_date)',
       order_id::text || ' | ' || snapshot_date::text, count(*)
  from {{ ref('silver_vehicle_purchase') }}
 group by 1, 2 having count(*) > 1

union all
-- vehicle_id là khoá nghiệp vụ mà tầng feature dùng để đếm xe đã giao
-- (vehicle_delivered_count_* đếm DISTINCT vehicle_id). Trùng ở đây là đếm sai.
select 'silver_vehicle_ownership: (vehicle_id, snapshot_date)',
       vehicle_id || ' | ' || snapshot_date::text, count(*)
  from {{ ref('silver_vehicle_ownership') }}
 group by 1, 2 having count(*) > 1
