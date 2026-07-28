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
