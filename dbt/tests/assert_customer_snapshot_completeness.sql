-- Spine phải ĐỦ: mọi khách × mọi snapshot, không thiếu dòng nào.
--
-- Thiếu dòng ở đây là loại lỗi im lặng nguy hiểm nhất của cả pipeline: feature.* vẫn
-- chạy, vẫn có số, chỉ là thiếu khách. Trung bình tính trên 400 khách thay vì 600 mà
-- không ai biết. Test grain bắt được dòng THỪA; test này bắt dòng THIẾU.

with mong_doi as (
    select (select count(*) from {{ source('raw', 'customers') }})
         * (select count(*) from {{ source('raw', 'feature_snapshot') }}) as n
),
thuc_te as (
    select count(*) as n from {{ ref('silver_customer_snapshot') }}
)
select mong_doi.n as so_dong_mong_doi, thuc_te.n as so_dong_thuc_te
from mong_doi, thuc_te
where mong_doi.n <> thuc_te.n
