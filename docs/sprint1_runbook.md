# Sprint 1 release runbook

1. Database admin chạy migration, regenerate semantic layer, mock seed và golden seed.
2. Cấp `feature_agent_reader`, `feature_agent_logger` và quyền `eval` cho runtime user.
3. Chạy `python -m pytest -q`; chỉ tiếp tục khi toàn bộ test pass.
4. Chạy `python -m scripts.run_eval --tag sprint1-final-dev --split dev` và lưu output vào
   `backend/reports/` cùng model, prompt version và retriever version.
5. Chỉ tune bằng dev set. Khi đạt target, chạy `python -m scripts.golden_dataset verify`.
6. Chạy duy nhất `python -m scripts.run_eval --tag sprint1-final-holdout --split holdout`.
7. Ghi report holdout, kiểm tra `git diff --check`, commit release và tạo tag `sprint1-v1.0.0`.

Không sửa semantic layer, prompt, validator, retriever hoặc golden holdout sau bước 6.
