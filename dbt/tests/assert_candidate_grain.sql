-- Grain của cả ba candidate: đúng 1 dòng / khách / snapshot.
--
-- feature.* có PRIMARY KEY (customer_id, snapshot_date), nên nhân dòng ở đây sẽ bị
-- publish_gold.py từ chối bằng lỗi khoá trùng — muộn hơn và khó đọc hơn nhiều so với
-- một test đỏ có tên.

{% set candidates = [
    'int_gsm_feature_candidate',
    'int_vinfast_feature_candidate',
    'int_cross_bu_candidate',
] %}

{% for model in candidates %}
select '{{ model }}' as model_sai_grain,
       customer_id::text || ' | ' || snapshot_date::text as khoa,
       count(*) as so_dong
  from {{ ref(model) }}
 group by 1, 2 having count(*) > 1
{% if not loop.last %}union all{% endif %}
{% endfor %}
