# Prompt changelog

Prompt sống trong `backend/app/agent/generator.py::SYSTEM_PROMPT`; `PROMPT_VERSION`
được ghi vào `eval.query_test_run.prompt_version` mỗi lần chạy `run_eval`.

**Luật:** sửa prompt ⇒ bump `PROMPT_VERSION` ⇒ thêm một dòng ở đây kèm **số eval
trước và sau**. Không có số thì không biết lần sửa đó là cải thiện hay hồi quy —
prompt là thứ dễ "cảm thấy tốt hơn" nhất mà không đo được.

Chạy: `python -m scripts.run_eval --tag <version> --split dev`

| Version | Ngày | Đổi gì | dev exec_acc | Ghi chú |
|---|---|---|---:|---|
| `sprint1-v1` | 2026-07-27 | Prompt Sprint 1: single-BU, grain snapshot, cấm raw/PII | **93%** | `reports/eval_sprint1_final_dev.md` |
| `sprint2-v1` | 2026-07-28 | +join_plan, +cross-BU table, +buyer≠owner, +CTE limit | chưa đo | Task 2.7 |
| `sprint2-v2` | 2026-07-28 | Sửa 2 lỗi trong prompt/context (xem dưới) | chưa đo | |
| `sprint2-v3` | 2026-07-29 | Bắt scalar snapshot filter, projection/aggregate tối thiểu, và boolean-state semantics. | `sprint2-prompt-v2` | pending eval |

| `sprint2-v4` | 2026-07-29 | Deterministic Top-N ordering, aggregate guardrails, Cross-BU precomputed-first, trend/max aliases, and transaction-vs-vehicle-purchase mapping. | **86%** | `sprint2-prompt-v4` |
| `sprint2-v5` | 2026-07-29 | V4 baseline restored; Cross-BU activity/spend gets scoped scoring only, without hard retrieval reordering. | **84%** | tag `sprint2-prompt-v5`, model `deepseek-v4-flash` |
| `sprint2-v6` | 2026-07-29 | Cấm COALESCE→0 bóp méo mẫu số; siết population filter phải dùng cờ. Kèm các sửa retrieval/context bên dưới. | **84%** | **Baseline chốt** — tag `sprint2-prompt-v6`, model `deepseek-v4-flash` |
| `sprint2-v7` | 2026-07-29 | Tách revenue/customer count theo từng BU thành hai dòng GSM/VINFAST; đồng bộ state flags giữa context và validator allowlist. | chưa chạy | pending eval, model `deepseek-v4-flash` |

> **Luật mới:** cột "Ghi chú" phải ghi **model**. `sprint2-v5` chạy trên `deepseek-v4-flash`
> trong khi các version trước chạy model khác — latency p95 giảm 21.4s→12.5s và exec_acc
> lệch 2 điểm, không thể quy cho prompt. Đổi một biến một lần.

## sprint2-v6 — chi tiết

**Trong prompt (2 luật):**

1. **Rule 14 mở rộng** — câu hỏi giới hạn tập khách ("khách hoạt động GSM", "chủ xe") thì
   cờ đó phải nằm trong `WHERE`; không được xấp xỉ bằng cột giá trị.
2. **Rule 15 mới** — cấm `COALESCE(feature, 0)` bên trong `AVG`/`SUM`. Với feature
   `no_history_in_unit`, NULL nghĩa là khách **nằm ngoài** tập đang đo; đếm họ thành 0 làm
   đổi mẫu số một cách im lặng. Đây là lỗi S17 lặp lại qua 3 lần chạy.

**Ngoài prompt (5 sửa, ảnh hưởng lớn hơn cả prompt):**

| # | Sửa | Vì sao |
|---|---|---|
| 1 | `evaluator._retrieval_for` gọi đúng như pipeline (truyền `business_unit`, bỏ lọc tiền tố tên bảng) | Thước đo lọc `CROSS_BU` bằng tiền tố nên `customer_cross_bu_feature` không khớp ⇒ **mọi case cross-BU bị chấm 0% retrieval** trong khi pipeline lấy đúng cột ở rank 1 |
| 2 | Retriever: `unit == CROSS_BU` ⇒ bỏ `ratio_window`/`metric_hint=ratio` | Bảng cross-BU có **0/37** cột ratio; câu "so sánh GSM 1 tháng với VinFast 3 tháng" bị lọc sạch rồi báo "câu hỏi chưa đủ rõ" |
| 3 | Filter `compare + value` cho phép thêm `distance` | `value_requested` đã thêm "quãng đường/km" nhưng allow-list quên ⇒ M02 trả 0 feature |
| 4 | `context._with_state_flags`: cờ boolean cùng bảng luôn vào context | Câu cần **chỉ số để tính + cờ để lọc**; retrieval xếp hạng theo độ giống nên cờ luôn rớt top-k. Cả catalog chỉ 19 cột boolean nên gần như không tốn token |
| 5 | Alias `dau tien` cho `days_since_first_*` | Câu thật chèn chữ vào giữa ("giao dịch VinFast hoàn thành **đầu tiên**") nên alias cụm dài không khớp substring |

**Kết quả dev end-to-end đã chốt (`sprint2-prompt-v6`, `deepseek-v4-flash`):**

| | trước | sau |
|---|---:|---:|
| hit@1 | 68% | **74%** |
| hit@3 | 82% | **89%** |
| hit@5 | 84% | **92%** |
| recall@5 | 86% | **95%** |

Các chỉ số chốt: refusal/clarification **100%**, SQL present **38/38**, schema valid
**37/38**, execution accuracy **84%**, task success **89%**, latency p50/p95
**6.429s/17.248s**. Báo cáo end-to-end còn 3 miss hit@5; hai case đã biết là **S11**
(`is_vehicle_owner` rớt hạng sau `is_vehicle_buyer`) và **S17**
(`is_active_gsm_l1m` không vào top-5, nhưng `_with_state_flags` vẫn đưa cờ vào context).
Không tiếp tục tuning trên dev; holdout chỉ dùng để xác nhận khả năng tổng quát hóa.

## sprint2-v2 — chi tiết

1. **Rule 7 nhắc `is_vinfast_buyer`** — cột legacy, `PipelineValidator` reject nếu LLM
   dùng. Prompt đang dạy một tên cột không query được. Đổi sang `is_vehicle_buyer` và
   nêu rõ **ba** nhóm khác nhau: buyer · scheduled · owner.
2. **`context.py` phát biểu tổng quát về NULL** ("no event in the requested window
   unless zero_denominator") — mâu thuẫn với trường `null=` của 40 feature dùng
   `never_event` / `always_present` / `no_history_in_unit` / `no_spend_to_compare`.
   Bỏ câu tổng quát, bảo LLM đọc `null=` từng dòng, và nêu riêng `no_history_in_unit`
   vì nó quyết định mẫu số khi tính trung bình.

Kèm theo (không thuộc prompt nên không bump riêng): `build_feature_context` không còn
lọc bỏ feature nằm trong `join_plan.tables` — trước đó plan cross-BU gồm hai bảng
GSM/VINFAST bị lọc sạch vì `route.business_unit == "CROSS_BU"`, để lại context rỗng.

## Nợ đã biết

- Prompt hardcode *"at most two CTEs"* trong khi `sql_max_ctes` là config. Đổi config
  thì prompt nói dối. Sửa khi có lần chỉnh prompt tiếp theo — hoặc chèn giá trị từ
  settings vào prompt lúc build.
