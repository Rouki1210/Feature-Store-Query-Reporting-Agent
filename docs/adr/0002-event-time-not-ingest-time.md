# ADR 0002 — Point-in-time dùng event time, không dùng ingest time

- Ngày: 2026-07-27
- Trạng thái: đề xuất (Task 2.0)
- Liên quan: `docs/vehicle_owner_semantics.md` mục 3, Task 2.1, 2.2

## Bối cảnh

Sprint 2 thêm `raw.vinfast_order_status_history` và `raw.vinfast_vehicle_handover`, mỗi bản ghi
có hai mốc thời gian:

- **event time** (`status_at`, `handed_over_at`, `reversed_at`) — sự kiện xảy ra lúc nào;
- **ingest time** (`recorded_at`, `ingested_at`) — hệ thống ghi nhận lúc nào.

Sự kiện đến trễ (late-arriving) là chuyện bình thường: bàn giao xe ở đại lý ngày 10, hệ thống
đồng bộ ngày 40.

Sprint 1 hoàn toàn không có vấn đề này vì `raw.vinfast_orders` chỉ có `updated_at` — dùng nó
cho snapshot cũ là rò dữ liệu tương lai, nên Sprint 1 chặn hẳn câu hỏi về owner.

## Lựa chọn

1. **Event time.** Feature phản ánh *thực tế đã xảy ra*. Snapshot cũ có thể **đổi giá trị** khi
   dữ liệu trễ về.
2. **Ingest time.** Snapshot bất biến sau khi tính (reproducible), nhưng số không khớp thực tế:
   khách đã nhận xe ngày 10 mà báo cáo tháng đó nói chưa.

## Quyết định

Chọn **event time**.

Người dùng là quản lý PnL hỏi câu nghiệp vụ ("tháng trước có bao nhiêu khách nhận xe"). Câu trả
lời phải đúng với thực tế kinh doanh, không đúng với lịch trình pipeline dữ liệu.

## Hệ quả

**Tốt**

- Số khớp với cái business tự đếm được.
- Test PIT viết được rõ ràng: cutoff = `snapshot_date 23:59:59.999999`, lọc theo event time.

**Xấu**

- Snapshot **không bất biến**: chạy lại pipeline sau khi dữ liệu trễ về sẽ ra số khác cho cùng
  một `snapshot_date`. Chấp nhận được vì mock data seed lại bằng seed cố định; ở hệ thật cần
  quy ước "báo cáo chốt sau N ngày".
- Không phát hiện được vấn đề chất lượng đường ống bằng chính feature — phải theo dõi độ trễ
  `recorded_at - status_at` riêng nếu cần.
- `recorded_at` vẫn phải lưu (không được bỏ) để về sau còn dựng lại được "tại thời điểm đó hệ
  thống *biết* gì" nếu audit yêu cầu.

## Test bắt buộc (Task 2.2)

- Sự kiện `status_at` ≤ D nhưng `recorded_at` > D ⇒ **vẫn được tính** vào snapshot D.
- Sự kiện `status_at` > D ⇒ **không** được tính (future leak).
- `reversed_at` > D ⇒ tại snapshot D khách **vẫn** là owner.
