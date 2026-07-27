# ADR 0001 — Tính sẵn bảng cross-BU thay vì để LLM join runtime

- Ngày: 2026-07-27
- Trạng thái: đề xuất (Task 2.0)
- Liên quan: `docs/join_policy.md`, Task 2.3, 2.4

## Bối cảnh

Sprint 2 phải trả lời câu hỏi xuyên GSM ↔ VinFast (overlap khách, so sánh chi tiêu, chủ xe
VinFast có đi GSM không). Hai bảng feature cùng grain `customer_id + snapshot_date`, nên về
kỹ thuật LLM hoàn toàn có thể tự sinh câu JOIN.

## Vấn đề

Join sai `snapshot_date` biến 1:1 thành 1:N với N = số snapshot (hiện 6). Kết quả: mọi
`SUM`/`COUNT` bị nhân 6. Câu SQL vẫn chạy, kết quả vẫn có định dạng đúng, số vẫn "trông hợp lý"
— người dùng phi kỹ thuật không có cách nào phát hiện.

Đây là dạng lỗi tệ nhất với một BI agent: **sai im lặng**.

## Các lựa chọn

1. **LLM tự join, validator kiểm tra.** Linh hoạt nhất, nhưng đúng/sai phụ thuộc mỗi lần sinh SQL,
   và độ khó của validator tăng theo độ phức tạp câu SQL (subquery, CTE, UNION).
2. **Tính sẵn `feature.customer_cross_bu_feature`.** Join xảy ra đúng **một lần**, trong pipeline
   deterministic, có test. Agent chỉ `SELECT` từ một bảng — không có gì để sai.
3. **Chỉ cho join theo view đã định nghĩa sẵn.** Gần như (2) nhưng tính lại mỗi query, và view
   vẫn phải qua guard.

## Quyết định

Chọn **(2)**, có **(1) làm đường dự phòng hẹp**: join runtime chỉ được phép khi cặp bảng nằm
trong `metadata.join_catalog` và điều kiện join có đủ `snapshot_date` (Task 2.4 + 2.8).

Join Planner ưu tiên bảng tính sẵn; chỉ rơi xuống join catalog khi câu hỏi cần cột mà bảng
tính sẵn không có.

## Hệ quả

**Tốt**

- Lỗi nhân dòng bị loại bỏ về mặt cấu trúc, không phụ thuộc chất lượng prompt.
- Có chỗ để chạy data-quality test (`COUNT(*) == COUNT(DISTINCT (customer_id, snapshot_date))`,
  tổng khớp bảng nguồn).
- Prompt ngắn hơn, ít token, ít vòng repair.
- Null/zero semantics chốt được ở một chỗ thay vì mỗi câu SQL một kiểu.

**Xấu**

- Thêm một bảng phải maintain; mỗi feature cross-BU mới cần migration + cập nhật
  `feature_spec.py` + seed lại catalog.
- Câu hỏi cross-BU nằm ngoài các cột đã tính sẵn sẽ bị từ chối thay vì được trả lời sáng tạo.
  **Đây là đánh đổi có chủ đích**: từ chối rõ ràng tốt hơn số sai im lặng (CLAUDE.md mục 5 —
  "agent phải nói được 'tôi không chắc'").
- Bảng tính sẵn phải chạy lại khi feature nguồn đổi; drift bị bắt bởi test tổng-khớp-nguồn.

## Xem lại khi nào

Nếu > 30% câu hỏi cross-BU thật bị từ chối vì thiếu cột, cân nhắc mở rộng cột tính sẵn (rẻ)
trước khi nới join runtime (đắt và rủi ro).
