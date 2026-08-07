-- Bất biến của bảng cross-BU (ADR 0001 + docs/join_policy.md §5).
--
-- Ba luật đầu trùng với CHECK constraint của feature.customer_cross_bu_feature — cố ý
-- lặp lại ở đây, vì constraint chặn lúc INSERT còn test này chặn lúc BUILD, kèm theo
-- khoá cụ thể để đi thẳng tới nguyên nhân thay vì chỉ nhận một lỗi ràng buộc.
--
-- Luật 4 và 5 KHÔNG có constraint nào bảo vệ, và chính chúng là lý do bảng này tồn tại:
-- phân biệt "chưa từng có dữ liệu" (NULL) với "có nhưng kỳ này bằng 0".

{% set windows = ['l1m', 'l3m', 'l6m', 'l12m', 'all'] %}

{% for w in windows %}
-- 1. Cờ giao nhau phải bằng tích của hai cờ thành phần.
select 'is_cross_bu_active_{{ w }} != gsm AND vinfast' as vi_pham,
       customer_id::text || ' @ ' || snapshot_date::text as chi_tiet
  from {{ ref('int_cross_bu_candidate') }}
 where is_cross_bu_active_{{ w }} is distinct from (is_active_gsm_{{ w }} and is_active_vinfast_{{ w }})
union all
-- 2. Chi tiêu không âm.
select 'chi tiêu âm ở {{ w }}', customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_cross_bu_candidate') }}
 where gsm_spend_{{ w }} < 0 or vinfast_spend_{{ w }} < 0 or combined_spend_{{ w }} < 0
union all
-- 3. combined phải đúng bằng tổng hai phía (NULL coi như 0), và chỉ NULL khi CẢ HAI NULL.
select 'combined_spend_{{ w }} không khớp tổng', customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_cross_bu_candidate') }}
 where combined_spend_{{ w }} is distinct from (
           case when gsm_spend_{{ w }} is null and vinfast_spend_{{ w }} is null then null
                else coalesce(gsm_spend_{{ w }}, 0) + coalesce(vinfast_spend_{{ w }}, 0) end)
union all
-- 4. Không được im lặng mặc định về GSM khi không có gì để so sánh.
select 'dominant_business_unit_{{ w }} có giá trị dù không có chi tiêu',
       customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_cross_bu_candidate') }}
 where dominant_business_unit_{{ w }} is not null
   and coalesce(combined_spend_{{ w }}, 0) = 0
union all
-- 5. NULL nghĩa là CHƯA TỪNG có dữ liệu ⇒ không thể vừa NULL vừa đang hoạt động.
select 'gsm_spend_{{ w }} NULL nhưng is_active_gsm_{{ w }}',
       customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_cross_bu_candidate') }}
 where gsm_spend_{{ w }} is null and is_active_gsm_{{ w }}
union all
select 'vinfast_spend_{{ w }} NULL nhưng is_active_vinfast_{{ w }}',
       customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_cross_bu_candidate') }}
 where vinfast_spend_{{ w }} is null and is_active_vinfast_{{ w }}
union all
{% endfor %}

-- 6. Điểm gắn kết nằm trong [0, 1], và chỉ NULL khi không có gì để so.
select 'cross_bu_engagement_score ngoài [0,1]', customer_id::text || ' @ ' || snapshot_date::text
  from {{ ref('int_cross_bu_candidate') }}
 where cross_bu_engagement_score < 0 or cross_bu_engagement_score > 1
