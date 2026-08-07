-- Spine: một dòng cho mỗi khách × mỗi ngày snapshot.
--
-- Mọi model candidate LEFT JOIN từ đây. Không có spine thì khách không có event nào
-- trong cửa sổ sẽ biến mất khỏi kết quả, trong khi feature.* phải có đủ 600 khách ở
-- mọi snapshot — NULL/0 của họ chính là câu trả lời cho "khách chưa từng mua VinFast".
--
-- Tương đương vòng lặp `for customer in customers` trong build_features().

select
    c.customer_id,
    s.snapshot_date
from {{ source('raw', 'customers') }} c
cross join {{ source('raw', 'feature_snapshot') }} s
