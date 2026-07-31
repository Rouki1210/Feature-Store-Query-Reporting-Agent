# Sprint 2 evaluation

Ngày rà soát: 2026-07-30. Trạng thái: **dev LLM đã chạy; chưa chạy holdout**.

## Dataset và kiểm tra cục bộ

- Golden set: 86 case, gồm 57 dev và 29 holdout.
- Holdout checksum `1033c4b8755f...` đã được xác nhận còn nguyên vẹn.
- `pytest -q`: **180 passed, 3 skipped**. Ba skip phụ thuộc quyền raw DB đúng thiết kế.

## Dev offline — `sprint2-retrieval-v2-offline`

| Metric | Kết quả |
|---|---:|
| retrieval hit@5 / recall@5 | 38/38 (100%) / 100% |
| refusal accuracy | 19/19 (100%) |
| gold SQL executes | 38/38 (100%) |
| execution/result accuracy | n/a — LLM tắt có chủ đích |

## Dev LLM — tag `sprint2-v7`

Tag là nhãn run; audit ghi nhận prompt thực tế là `sprint2-v8`, model
`deepseek-v4-flash`.

| Metric | Kết quả |
|---|---:|
| retrieval hit@5 / recall@5 | 38/38 (100%) / 100% |
| refusal accuracy | 19/19 (100%) |
| SQL present / schema valid / execution success | 38/38 / 38/38 / 38/38 |
| execution accuracy | 33/38 (86%) |
| task success | 91% |
| latency p50 / p95 | 5.361s / 10.655s |

## Gate trước holdout

Kết quả đã vượt gate cho retrieval, refusal, Cross-BU, PIT, safety, SQL executable và
result accuracy chung. Holdout chưa chạy vì còn 5 mismatch dev: 2 case `buyer_vs_owner`
(execution 2/4) và 3 case `single_feature` (21/24). Buyer/owner có target 100%, nên phải
phân tích các case này trên dev trước; không tuning theo holdout.

## Failure analysis đã xử lý

| Tầng | Vấn đề | Xử lý |
|---|---|---|
| Retrieval | `vehicle_purchase_*` bị phạt hẹp hai lần. | Bỏ penalty riêng trùng với `_NARROWING_PENALTY`. |
| Retrieval | Owner bị status filter `nhận bàn giao` loại khỏi kết quả. | Cho `is_vehicle_owner` là mapping hợp lệ của handover. |
| Retrieval | So sánh buyer/owner ép toàn bộ feature theo một trạng thái. | Không áp hard status filter khi có cả completed và handover. |
| Retrieval | `is_active_gsm_*` bị loại khỏi truy vấn spend dù là population filter. | Cho phép cờ active được truy hồi theo population GSM/VinFast. |
| Breakdown | “theo từng khách” bị hiểu nhầm là generic breakdown. | Loại danh sách per-customer khỏi clarify breakdown. |

## Việc còn lại

1. Trích và sửa 5 dev result mismatch theo SQL/semantic mapping.
2. Chạy lại dev với tag mới, giữ model/prompt cố định.
3. Khi buyer/owner đạt 4/4, chạy holdout đúng một lần và bổ sung kết quả vào báo cáo này.
