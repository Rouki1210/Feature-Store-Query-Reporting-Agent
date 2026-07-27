# Eval baseline — Sprint 1 final (dev split)

- Lệnh: `python -m scripts.run_eval --tag sprint1_final --split dev`
- Ngày: 2026-07-27 · Model: `levuphong2909/gpt-5.6-sol` · LLM: on
- Dev 30 case answerable + 10 case guardrail. **Holdout không dùng.**
- Điều kiện: sau khi cấp quyền DB (`docs/db_roles.md`) và pytest 106/106.

Đây là **mốc so sánh cho Sprint 2**. Mọi thay đổi prompt/retriever/validator phải chạy lại
lệnh trên và so với bảng dưới.

## Tổng quan

| Metric | Giá trị |
|---|---:|
| retrieval_hit@5 | 27/30 (90%) |
| retrieval_recall@5 | 90% |
| refusal_accuracy | 10/10 (100%) |
| **execution_acc** | **28/30 (93%)** |
| gold_sql_ok | 30/30 (100%) |
| task_success_rate | 95% |
| latency p50 / p95 | 4.517ms / 8.024ms |

## Theo độ khó

| nhóm | retrieval | refusal | exec_acc | gold_ok |
|---|---|---|---|---|
| easy | 8/8 (100%) | 5/5 (100%) | 8/8 (100%) | 8/8 (100%) |
| medium | 13/15 (86%) | 5/5 (100%) | 14/15 (93%) | 15/15 (100%) |
| hard | 6/7 (85%) | n/a | 6/7 (85%) | 7/7 (100%) |

Nhóm `hard` chỉ kém easy 15 điểm — semantic layer đang gánh được phần từ vựng nghiệp vụ.

## Theo category

| nhóm | retrieval | refusal | exec_acc |
|---|---|---|---|
| single_feature | 22/24 (91%) | n/a | 23/24 (95%) |
| service_breakdown | 3/3 (100%) | n/a | 3/3 (100%) |
| **time_comparison** | **2/3 (66%)** | n/a | **2/3 (66%)** |
| out_of_scope | n/a | 6/6 (100%) | n/a |
| sql_safety | n/a | 2/2 (100%) | n/a |
| restricted_data | n/a | 1/1 (100%) | n/a |
| ambiguous_question | n/a | 1/1 (100%) | n/a |

## Phễu sinh SQL

| Bước | Tỉ lệ |
|---|---:|
| SQL present | 28/30 (93%) |
| Parse success \| SQL present | 28/28 (100%) |
| Schema valid \| parsed | 28/28 (100%) |
| Execution success \| valid | 28/28 (100%) |
| Result match \| executed | 28/28 (100%) |

**Đọc phễu:** mất mát duy nhất nằm ở bước đầu — 2 case không sinh được SQL. Sinh được rồi thì
đúng 100% suốt phần còn lại. Nghĩa là điểm yếu ở **retrieval/hiểu câu hỏi**, không phải ở
sinh SQL hay guard.

## Retrieval

| Metric | Giá trị |
|---|---:|
| hit@1 | 60% |
| hit@3 | 83% |
| hit@5 | 90% |
| MRR | 0.728 |
| selected_context_accuracy | 93% |

hit@1 60% vs hit@5 90%: feature đúng thường có trong top-5 nhưng **không đứng đầu**. Đây là
chỗ đáng cải thiện nhất (ranking, không phải recall).

## Clarification / refusal

| Metric | Giá trị |
|---|---:|
| clarification_precision | 50% |
| clarification_recall | 100% |
| refusal_precision | 100% |
| refusal_recall | 100% |
| over_refusal_rate | 0% |

`clarification_precision = 50%` — agent hỏi lại nhiều hơn cần thiết (hỏi cả câu đủ thông tin).
Recall 100% nên không bỏ sót câu mơ hồ. Ngưỡng `retrieval_min_score=2.0` là chỗ chỉnh.

## Việc rút ra cho Sprint 2

1. **`time_comparison` 66%** — nhóm yếu nhất. Sprint 2 thêm câu hỏi PIT/so sánh snapshot nên
   phải chỉnh trước, không thì lỗi lan sang benchmark mới.
2. **hit@1 60%** — chỉnh ranking retriever (trọng số window/BU) rẻ hơn chỉnh prompt.
3. **clarification_precision 50%** — re-tune `retrieval_min_score` bằng chính dev set này.
4. **llm_latency_p95 8.0s** chiếm ~99% tổng latency; retrieval 19ms, SQL 24ms. Tối ưu DB là
   vô nghĩa, tối ưu số vòng gọi LLM mới có tác dụng.

## Lưu ý về lần chạy trước (đã bỏ)

Có một lần chạy trước cho `execution_acc = 0/30`, `Execution success | valid = 0/28`.
Đó **không** phải chất lượng model — lúc đó user `agent` chưa được `GRANT feature_agent_reader`
nên mọi query chết ở `SET LOCAL ROLE`. Retrieval và refusal của lần đó (90% / 100%) trùng khớp
với lần này vì hai tầng đó không chạm DB thực thi.

Bài học: đọc số eval mà thấy **một tầng bằng 0 tuyệt đối** thì nghi hạ tầng trước, đừng nghi model.
