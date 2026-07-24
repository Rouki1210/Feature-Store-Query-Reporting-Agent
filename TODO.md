# TODO — trạng thái hiện tại

Cập nhật: 2026-07-24. Sprint 1 (GSM + VinFast, grain `customer_id + snapshot_date`,
KHÔNG global_loyalty). **pytest 62/62 pass.**

## Đã hoàn thành

### Nền tảng dữ liệu
- [x] Backend scaffold: config (env-only), SQLAlchemy/PostgreSQL, Pydantic schemas.
- [x] PostgreSQL; Alembic `0002 (head)`. `0001` áp `db/schema/*.sql`; `0002` thêm đủ
      353 cột canonical (167 GSM + 186 VinFast), giữ cột legacy vật lý (an toàn dữ liệu).
- [x] `feature_spec` = đúng 353 feature; describer + `semantic_layer.yaml` song ngữ VI+EN.
- [x] **[DUP]** Test khóa `feature_spec` inventory == migration `0002` (bắt drift tên/window,
      không ghép đôi migration vào app code).
- [x] Mock generator 3 lớp, **làm dày 2026-07-24**: **600 customers × 6 snapshot tháng**
      (as-of: mỗi snapshot chỉ tính sự kiện ≤ ngày đó), 18.044 trips, 4.291 orders →
      3.600 dòng/bảng feature. ~75 khách genuine-null VF (cid%8). Biến thiên MoM thật.
- [x] **[VERIFY]** Sửa bug `canceled`(1 L)↔`cancelled`(2 L) — trước đó mọi `canceled_*`
      toàn 0. Ratio/days_since/processing OK. `finished`=`completed` (mock, đã flag).
      Còn 7 dead = `txn_canceled_*_daily` (cửa sổ 1 ngày × đơn hủy — thưa đúng thực tế).

### Semantic layer + nguồn ngữ nghĩa
- [x] **[SEED] rebuild idempotent**: catalog = 353 (DELETE non-canonical, hết 50 orphan);
      seed 2 lần đều 353; 328 queryable (= 353 − 25 NVSO/WO restricted); synonyms 4.537.
- [x] **[NGUỒN NGỮ NGHĨA] chốt**: giữ cả hai — **YAML authoritative** (sinh từ feature_spec,
      version-controlled) → `seed_metadata` chiếu vào **DB catalog** → agent đọc DB
      (`retriever.load_from_db`, 328 queryable). Test `test_db_layer_matches_yaml_projection`
      khóa hai bản không lệch field.
- [x] Retriever song ngữ (BU/metric/status/window/compare/cutoff); NVSO/WO (needs_review)
      bị loại khỏi retrieval (`is_queryable==support_status`).

### Agent pipeline + API
- [x] Pipeline: router → retriever → context → JSON SQL generator → validator →
      repair loop → executor → narrator + trace. Prompt biết snapshot grain (lọc `MAX(snapshot_date)`).
- [x] SQL guard: single SELECT/WITH, schema/table allowlist, deny raw/PII/`SELECT *`/DML/DDL/
      dangerous functions, row limit. Validator chặn feature ngoài context/canonical/legacy.
- [x] **[BUG] câu mơ hồ → clarify**: ngưỡng `retrieval_min_score=2.0`; điểm top < ngưỡng ⇒
      hỏi lại, KHÔNG gọi LLM (trước đó "gọi tất cả").
- [x] Audit `query_log` + `sql_validation_log` (rejected/failed/executed).
- [x] **FastAPI** `app/main.py`: `/health` `/ask` `/features` + CORS + 3 smoke test.
- [x] **Multi-turn clarify (short-term state, lazy v1)**: `app/agent/conversation.py` —
      `ask_with_context` bọc pipeline stateless, nối câu trả lời ngắn (≤4 token) vào câu
      đang chờ rồi chạy lại; hủy/TTL/câu-mới xử lý theo spec; `session_id` round-trip qua
      `/ask`; router nhận `\bvf\b`. +7 test (merge/cancel/replace/invalid/TTL/isolation/refusal-on-merge).
- [x] Streamlit test UI (`app/streamlit_app.py`).
- [x] **[MINOR]** `has_select_star` chính xác (không dính `COUNT(*)`); dọn dead code
      (`WINDOW_DAYS` l2m/l4w/l8w, `_group` param). Audit-INSERT dedup: cố ý bỏ (duplication ổn định).

## Còn lại

- [ ] **Frontend**: React + Vite + Tailwind — hoặc dùng luôn Streamlit đã có (cân nhắc YAGNI).
- [ ] **Golden set + execution accuracy** (CLAUDE.md mục 8): expected SQL/result, nhóm "hard"
      (Vietnamese/business vocab/ambiguous/cross-window); đo hit@k / refusal / repair / latency.
- [ ] Test bổ sung: mock aggregation theo họ stem/window; metadata idempotency trực tiếp trên PG.
- [ ] README (setup/run/seed/test) + docker-compose Postgres + e2e với LLM thật.

## Nợ kỹ thuật (đã biết — shortcut có chủ đích, ghi rõ trần & upgrade path)

- [ ] **`_STORE` in-memory** (`app/agent/conversation.py`): pending state mất khi restart,
      không chia sẻ multi-worker, chưa khóa thread. Trần: prototype 1 instance.
      → Redis + lock khi lên nhiều instance / cần bền qua restart.
- [ ] **Heuristic nối câu length-only** (`conversation.py`): câu-hỏi-mới-NGẮN (≤4 token)
      khi đang có pending có thể bị nối nhầm. → tinh chỉnh bằng golden set / phân loại tốt hơn.
- [ ] **`retrieval_min_score=2.0`** (`config.py`): hằng số calib tay (cụ thể ≥2.75, mơ hồ ≤1.5).
      → re-tune bằng golden set khi có.
- [ ] **Seed mock ~90s** (`scripts/generate_mock_data.py`): O(features×trips), rescan mỗi
      feature × snapshot. Trần: chạy thỉnh thoảng nên chấp nhận. → bucket sự kiện theo window nếu vướng.
- [ ] **Multi-snapshot cách đều 30 ngày** (không phải month-end lịch): MoM xấp xỉ.
      → month-end thật nếu cần khớp lịch.
- [ ] **`finished_*` == `completed_*`** trong mock (raw không có status `finished`): trùng giá trị,
      cột riêng ở store thật. → cần định nghĩa nghiệp vụ `finished`.
- [ ] **7 feature `txn_canceled_*_daily` luôn 0** (cửa sổ 1 ngày × đơn hủy hiếm): thưa ĐÚNG
      thực tế — KHÔNG phải bug, ghi để khỏi nhầm.
- [ ] **`seed_metadata` gán `language_code` theo `ord>127`**: keyword VI không dấu (`taxi`,`gsm`)
      bị gắn `en`. Cosmetic, không ảnh hưởng match.
- [ ] **Audit INSERT lặp 4 chỗ** (`executor.py` ×3 + `pipeline._audit_terminal`): cố ý để inline
      (rõ hơn abstraction). → gom 1 helper nếu số chỗ tăng.
- [ ] **Chưa có pytest DB-idempotency cho seed** (đã verify tay): → thêm test skip-nếu-không-DB nếu muốn CI chặt.

## Câu hỏi cho human (chưa quyết được ở code)

- [ ] Định nghĩa nghiệp vụ `nvso`/`wo` → mới mở 25 feature restricted cho query.
- [ ] Change-control drop cột legacy vật lý (hiện giữ, đã tắt khỏi catalog).
- [ ] Row grain thật: feature store có snapshot_date (time-series) hay chỉ latest state?
      (mock đang giả định có — mục 10 CLAUDE.md).

## Lệnh kiểm tra

```powershell
cd backend
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe -m scripts.generate_semantic_layer
.venv\Scripts\python.exe -m scripts.generate_mock_data   # ~90s: 600×6 snapshot + seed catalog
.venv\Scripts\python.exe -m pytest -q                    # 62 pass
uvicorn app.main:app --reload                            # REST
```
