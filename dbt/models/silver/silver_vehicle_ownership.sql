-- Quyền sở hữu xe TẠI TỪNG SNAPSHOT. Grain: (handover_id, snapshot_date).
--
-- Nguồn DUY NHẤT của ownership là raw.vinfast_vehicle_handover. Không bao giờ suy ra
-- từ vinfast_orders.status: mua không phải là nhận (docs/vehicle_owner_semantics.md).
-- Tương đương _vehicle_pit() trong scripts/generate_mock_data.py.
--
-- Ba trạng thái phân biệt rạch ròi, đây là toàn bộ giá trị của model này:
--
--   is_handed_over  đã nhận xe tính tới snapshot
--   is_owned        đã nhận VÀ chưa bị đảo tính tới snapshot
--   is_pending      đã hẹn lịch nhưng chưa nhận tính tới snapshot
--
-- Đảo bàn giao XẢY RA SAU snapshot không ảnh hưởng snapshot đó — lúc ấy khách vẫn là
-- chủ xe. Đây chính là chỗ dễ sai nhất nếu lọc bằng trạng thái hiện tại thay vì mốc
-- thời gian (ADR 0002).
--
-- Python so `handed_over_at <= datetime.combine(snapshot, time.max, UTC)`, tức "trong
-- hoặc trước ngày snapshot theo UTC". Viết bằng so sánh ngày cho khỏi dính chuyện
-- microsecond của time.max.

with handover as (
    select
        handover_id,
        order_id,
        customer_id,
        vehicle_id,
        handover_status,
        scheduled_at,
        handed_over_at,
        reversed_at,
        (scheduled_at  at time zone '{{ var("business_timezone") }}')::date as scheduled_date,
        (handed_over_at at time zone '{{ var("business_timezone") }}')::date as handed_over_date,
        (reversed_at   at time zone '{{ var("business_timezone") }}')::date as reversed_date
    from {{ source('raw', 'vinfast_vehicle_handover') }}
),

as_of as (
    select
        h.*,
        s.snapshot_date,
        (h.handed_over_date is not null and h.handed_over_date <= s.snapshot_date) as is_handed_over,
        (h.reversed_date   is not null and h.reversed_date   <= s.snapshot_date) as is_reversed
    from handover h
    cross join {{ source('raw', 'feature_snapshot') }} s
)

select
    handover_id,
    order_id,
    customer_id,
    vehicle_id,
    snapshot_date,
    handover_status,
    scheduled_at,
    handed_over_at,
    reversed_at,
    handed_over_date,
    is_handed_over,
    is_handed_over and not is_reversed as is_owned,
    -- Đã hẹn nhưng chưa giao tính tới snapshot. Bao gồm cả bản ghi ĐÃ giao sau
    -- snapshot: tại thời điểm đó nó vẫn đang là lịch hẹn.
    (scheduled_date is not null and scheduled_date <= snapshot_date
        and not is_handed_over) as is_pending
from as_of
