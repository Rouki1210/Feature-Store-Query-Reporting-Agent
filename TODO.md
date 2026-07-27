# TODO — trạng thái hiện tại

Cập nhật: 2026-07-27. **Sprint 1 gần đóng** (GSM + VinFast, grain `customer_id + snapshot_date`,
KHÔNG global_loyalty). **Sprint 2 chưa bắt đầu phần dữ liệu** (xem mục riêng bên dưới).

**pytest: 103 pass / 3 fail** — cả 3 fail do THIẾU GRANT trên Postgres local, không phải lỗi code.
Xem "Chặn ngay" bên dưới.

## Đã hoàn thành

### Nền tảng dữ liệu
- [x] Backend scaffold: config (env-only), SQLAlchemy/PostgreSQL, Pydantic schemas.
- [x] PostgreSQL; Alembic `0002 (head)`. `0001` áp `db/schema/*.sql`; `0002` thêm đủ
      353 cột canonical (167 GSM + 186 VinFast), giữ cột legacy vật lý (an toàn dữ liệu).
- [x] `feature_spec` = đúng 353 feature; describer + `semantic_layer.yaml` song ngữ VI+EN.
- [x] **[DUP]** Test khóa `feature_spec` inventory == migration `0002` (bắt drift tên/window,
      không ghép đôi migration vào app code).
- [x] Mock generator 3 lớp: **600 customers × 6 snapshot tháng** (as-of: mỗi snapshot chỉ
      tính sự kiện ≤ ngày đó), ~18k trips, ~4.3k orders → 3.600 dòng/bảng feature.
      Có khách inactive (cid%20), VF-only (cid%20==3), genuine-null VF (cid%8).
- [x] **[MỚI] Data-quality gate cho mock**: `data_quality_errors()` +
      `tests/test_mock_data_quality.py` — kiểm invariant (l1m ≤ l3m ≤ l12m, ratio khớp
      thành phần, as-of không rò sự kiện tương lai). Trước đây chỉ verify tay.
- [x] **[VERIFY]** Sửa bug `canceled`(1 L)↔`cancelled`(2 L). `finished`=`completed` (mock, đã flag).
      Còn 7 dead = `txn_canceled_*_daily` (cửa sổ 1 ngày × đơn hủy — thưa đúng thực tế).

### Semantic layer + nguồn ngữ nghĩa
- [x] **[SEED] rebuild idempotent**: catalog = 353; 328 queryable (= 353 − 25 NVSO/WO
      restricted); synonyms 4.537.
- [x] **[NGUỒN NGỮ NGHĨA] chốt**: **YAML authoritative** → `seed_metadata` chiếu vào DB
      catalog → agent đọc DB (`retriever.load_from_db`). Test khóa hai bản không lệch field.
- [x] Retriever song ngữ (BU/metric/status/window/compare/cutoff); NVSO/WO (needs_review)
      bị loại khỏi retrieval.

### Agent pipeline + API
- [x] Pipeline: router → retriever → context → JSON SQL generator → validator →
      repair loop → executor → narrator + trace. Prompt biết snapshot grain.
- [x] **[MỚI] SQL guard viết lại theo AST (`sqlglot`)** thay cho regex: single SELECT/WITH,
      schema/table allowlist, deny raw/PII/`SELECT *`/DML/DDL/hàm nguy hiểm, row limit.
      Bỏ hẳn `_FORBIDDEN` keyword-match (nguồn của false positive/negative). +24 dòng test.
- [x] **[MỚI] Enforce ở tầng DB**: `SET LOCAL ROLE feature_agent_reader` +
      `SET LOCAL statement_timeout` mỗi query (`executor._prepare_query_connection`),
      config `SQL_TIMEOUT_MS`. Test `test_executor_security.py`.
- [x] **[BUG] câu mơ hồ → clarify**: ngưỡng `retrieval_min_score=2.0`; điểm top < ngưỡng ⇒
      hỏi lại, KHÔNG gọi LLM.
- [x] Audit `query_log` + `sql_validation_log` (rejected/failed/executed).
- [x] **FastAPI** `app/main.py`: `/health` `/ask` `/features` + CORS + smoke test.
- [x] **Multi-turn clarify (short-term state, lazy v1)**: `app/agent/conversation.py` —
      nối câu trả lời ngắn (≤4 token) vào câu đang chờ rồi chạy lại; hủy/TTL/câu-mới theo
      spec; `session_id` round-trip qua `/ask`. +7 test.
- [x] Streamlit test UI (`app/streamlit_app.py`).
- [x] Router matching test riêng (`test_router_matching.py`), `\bvf\b`.

### Golden set + đo lường (CLAUDE.md mục 8) — **XONG**
- [x] `data/golden_set.yaml` → 60 case: **dev 40 / holdout 20 disjoint**, có nhóm `hard`
      (7 dev / 3 holdout) + guardrail/out_of_scope/restricted/ambiguous.
- [x] Holdout **khóa bằng checksum** (`HOLDOUT_CHECKSUM`, `HOLDOUT_VERSION`) +
      `test_golden_set_integrity.py` (chống tuning trên holdout).
- [x] `app/eval/comparator.py` — so result set order- & column-name-insensitive, chỉ stdlib.
- [x] `app/eval/evaluator.py` + `scripts/run_eval.py --tag --split`: execution accuracy,
      retrieval recall@5, refusal accuracy, SQL-parse rate, repair count, latency p50/p95;
      LLM-optional (thiếu key → vẫn đo retrieval + refusal). Ghi `eval.query_test_run`.
- [x] `reports/golden_dataset_coverage.md` (sinh bằng `scripts/golden_dataset.py`).

### Frontend — **XONG (React thay Streamlit)**
- [x] React + Vite + Tailwind + Recharts: chat, table/bar-chart toggle, SQL panel + copy,
      confidence/coverage/warning, technical details (trace, retrieved features), export CSV,
      `session_id` giữ qua lượt. `types.ts` mirror `schemas.py`.

## Chặn ngay (3 test đỏ — chỉ cần chạy SQL, không sửa code)

- [ ] **`permission denied to set role "feature_agent_reader"`** → app user chưa là member:
      `GRANT feature_agent_reader TO <db_user>;` (làm 2 test `test_agent_pipeline` /
      `test_conversation` đỏ vì mọi query thật đều fail).
- [ ] **`permission denied for table eval.query_test_case`** → schema `eval` chưa có grant cho
      app user: `GRANT USAGE ON SCHEMA eval TO <db_user>; GRANT ALL ON ALL TABLES IN SCHEMA eval TO <db_user>;`
      (làm `test_golden_set_integrity::test_seed_matches_yaml_count` đỏ).
- [ ] Sau khi grant: chạy lại `pytest -q` kỳ vọng **106/106**, rồi commit khối đang dirty
      (guards AST, reader role, mock quality gate, 4 file test mới, `HOLDOUT_*`, `reports/`).

## Sprint 2 — tiến độ theo tracker

| Task | Trạng thái |
|---|---|
| 2.0 Scope freeze, ADR, contracts | 🟡 5 doc + 2 ADR đã soạn (`docs/`), chờ business xác nhận |
| 2.1 `raw.vinfast_order_status_history` + `vehicle_handover` | ❌ |
| 2.2 PIT VinFast feature pipeline | ❌ (mock có as-of snapshot nhưng không dựng từ event history) |
| 2.3 `feature.customer_cross_bu_feature` | ❌ |
| 2.4 Join catalog + Join Planner | ❌ |
| 2.5 Short-term clarification state | ✅ v1 (lazy) — còn thiếu slot model tường minh |
| 2.6 Multi-turn orchestrator | 🟡 merge-and-rerun chạy; chưa có join plan / revalidate sau merge |
| 2.7 Generator v2 | ❌ vẫn v1 |
| 2.8 Validator v2 | 🟡 guard đã lên AST + reader role + timeout; thiếu join-vs-catalog, max joins, cost |
| 2.9 Visualization | 🟡 bar chart + coverage/warning; chưa có result-shape classifier / `chart_spec` |
| 2.10 Chat UI | ✅ |
| 2.11 Sprint 2 benchmark | 🟡 hạ tầng eval dùng lại được; benchmark hiện **0 case cross-BU** |

Cross-BU và vehicle handover đang bị **chủ động refuse** trong `app/agent/router.py`
(đúng scope Sprint 1). Mở khóa là bước cuối sau 2.1→2.3, không phải bước đầu.

**Đường ngắn nhất vào Sprint 2:** 2.1 → 2.2 → 2.3 → 2.4, rồi gỡ refusal ở
[router.py:120](backend/app/agent/router.py#L120) và [router.py:74](backend/app/agent/router.py#L74).
2.5 và 2.10 coi như xong — đừng làm lại.

## Còn lại (Sprint 1)

- [x] README (setup/run/seed/test), Docker Compose Postgres và Sprint 1 runbook.
- [ ] Chạy e2e với LLM thật + ghi số baseline `run_eval --split dev` vào `reports/`
      (hiện chưa có bản ghi before/after nào).
- [ ] Test metadata idempotency trực tiếp trên PG (đã verify tay).

## Nợ kỹ thuật (shortcut có chủ đích — ghi rõ trần & upgrade path)

- [ ] **`_STORE` in-memory** (`conversation.py`): pending state mất khi restart, không chia sẻ
      multi-worker, chưa khóa thread. Trần: prototype 1 instance. → Redis + lock.
- [ ] **Heuristic nối câu length-only** (`conversation.py`): câu-hỏi-mới-NGẮN (≤4 token) có thể
      bị nối nhầm. → tinh chỉnh bằng golden set.
- [ ] **Comparator align cột bằng value-signature** (`app/eval/comparator.py`): 2 cột cùng
      multiset giá trị có thể hoán đổi mà vẫn "bằng". → permutation-match nếu đo sai.
- [ ] **`retrieval_min_score=2.0`** (`config.py`): hằng số calib tay. → re-tune bằng dev set
      (giờ ĐÃ có golden set — việc này làm được rồi).
- [ ] **Seed mock ~90s** (`generate_mock_data.py`): O(features×trips). Chấp nhận.
- [ ] **Multi-snapshot cách đều 30 ngày** (không phải month-end lịch): MoM xấp xỉ.
- [ ] **`finished_*` == `completed_*`** trong mock (raw không có status `finished`).
- [ ] **7 feature `txn_canceled_*_daily` luôn 0**: thưa ĐÚNG thực tế — KHÔNG phải bug.
- [ ] **`seed_metadata` gán `language_code` theo `ord>127`**: keyword VI không dấu bị gắn `en`.
      Cosmetic.
- [ ] **Audit INSERT lặp 4 chỗ** (`executor.py` ×3 + `pipeline._audit_terminal`): cố ý inline.
- [ ] **`_FEATURE_TABLES` hardcode 2 bảng** (`guards.py`): phải mở rộng khi thêm
      `feature.customer_cross_bu_feature` ở Task 2.3.

## Câu hỏi cho human (chưa quyết được ở code)

- [ ] Định nghĩa nghiệp vụ `nvso`/`wo` → mới mở 25 feature restricted cho query.
- [ ] Change-control drop cột legacy vật lý (hiện giữ, đã tắt khỏi catalog).
- [ ] Row grain thật: feature store có snapshot_date (time-series) hay chỉ latest state?
- [ ] Sprint 2: chốt định nghĩa buyer vs owner + TTL clarification trước khi code 2.1.

## Lệnh kiểm tra

```powershell
cd backend
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m scripts.generate_semantic_layer
.venv\Scripts\python.exe -m scripts.generate_mock_data   # ~90s: 600×6 snapshot + seed catalog
.venv\Scripts\python.exe -m scripts.seed_golden_set      # 60 case → eval.query_test_case
.venv\Scripts\python.exe -m pytest -q                    # 106 pass SAU khi grant (nay 103/3)
.venv\Scripts\python.exe -m scripts.run_eval --tag baseline --split dev
uvicorn app.main:app --reload                            # REST
cd ..\frontend; npm run dev                              # UI
```
