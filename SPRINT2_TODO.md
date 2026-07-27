# Sprint 2 — Checklist thực thi

Nguồn: `SPRINT_2_TASK_TRACKER_CODEX.md`. File này là bản **đã map vào code thật** của repo:
mỗi task ghi rõ chạm file nào, làm gì, test gì mới coi là xong.

Trạng thái đầu sprint: Sprint 1 xong (103/106 test pass — 3 đỏ vì thiếu GRANT, xem `TODO.md`).
Task **2.5 và 2.10 đã có sẵn từ Sprint 1** — chỉ bổ sung, không viết lại.

**Quy ước chung của repo (theo đúng thứ này, đừng phát minh cấu trúc mới):**

| Việc | Chỗ đặt |
|---|---|
| DDL | `backend/migrations/versions/000N_*.py` (Alembic, `revision`/`down_revision` chuỗi) |
| Nguồn sự thật feature | `backend/app/semantic/feature_spec.py` → sinh `data/semantic_layer.yaml` → seed vào DB |
| Sinh dữ liệu | `backend/scripts/generate_mock_data.py` |
| Logic agent | `backend/app/agent/*.py` (router, generator, validator, pipeline, conversation) |
| Guard SQL | `backend/app/sql/guards.py` (AST `sqlglot`) |
| Test | `backend/tests/test_*.py` — pytest phẳng, không fixture nặng |
| Config | `backend/app/config.py` (env-only, không hardcode) |

**Thứ tự bắt buộc:** 2.0 → 2.1 → 2.2 → 2.3 → 2.4 → 2.7 → 2.8 → 2.9 → 2.11.
Nhánh 2.5 → 2.6 chạy song song được.

---

## Task 2.0 — Scope freeze & contracts ✅ soạn xong, CHỜ XÁC NHẬN

**Mục tiêu:** chốt định nghĩa TRƯỚC khi viết SQL, vì buyer/owner sai nghĩa là làm lại từ 2.1.

- [x] Tạo thư mục `docs/`.
- [x] `docs/vehicle_owner_semantics.md` — chốt 3 định nghĩa, mỗi cái 1 câu SQL mẫu:
      - `buyer` = có ≥1 order `order_type='vehicle'` đạt trạng thái completed **theo status history**.
      - `owner` = có ≥1 bản ghi handover `completed` và **chưa** bị `reversed_at`.
      - `delivered vehicle` = handover completed, đếm theo `vehicle_id` không phải order.
- [x] `docs/join_policy.md` — join chuẩn duy nhất:
      `gsm.customer_id = vf.customer_id AND gsm.snapshot_date = vf.snapshot_date`.
      Ghi rõ: thiếu vế `snapshot_date` ⇒ reject, không phải cảnh báo.
- [x] `docs/short_term_state_contract.md` — viết lại đúng hành vi `app/agent/conversation.py`
      hiện có (nối câu ngắn ≤4 token, TTL từ `conversation_ttl_seconds`, cancel-words),
      cộng phần bổ sung ở Task 2.5.
- [x] `docs/sprint2_definition_of_done.md` — scope + 6 use case + DoD + bảng metric + gate.
- [x] `docs/adr/0001-cross-bu-precomputed-table.md` — quyết định: tính sẵn
      `feature.customer_cross_bu_feature` thay vì để LLM tự join runtime. Lý do: join sai
      = nhân dòng = số sai, mà số sai thì user không phát hiện được.
- [x] `docs/adr/0002-event-time-not-ingest-time.md` — PIT lọc theo event time
      (`status_at`/`handed_over_at`), không theo `recorded_at`/`updated_at`.

**Còn lại của 2.0 — cần con người, không code được:**

- [x] 3 câu hỏi mở đã chốt 2026-07-27 (`docs/vehicle_owner_semantics.md` mục 5):
      `completed` là trạng thái cuối · `reversed` không tách lý do · không xử lý sang tên.
- [ ] Xác nhận join policy và short-term state contract (TTL 15 phút, không Redis).
- [ ] Duyệt 2 ADR.
- [ ] Sửa 3 test đỏ (thiếu GRANT) + chạy `run_eval --tag sprint1_final --split dev` lấy mốc.

**Xong khi:** đủ 4 dòng trên. Không có xác nhận thì **không** bắt đầu 2.1.

**Bỏ bớt so với tracker:** gộp `sprint2_scope.md` + `cross_bu_query_contract.md` vào
`sprint2_definition_of_done.md`. 6 file docs cho 1 sprint là giấy tờ, không phải thiết kế.

---

## Task 2.1 — `raw.vinfast_order_status_history` + `raw.vinfast_vehicle_handover`

**Mục tiêu:** có event time thật để dựng trạng thái tại thời điểm bất kỳ.
Hiện `raw.vinfast_orders` chỉ có `status` + `updated_at` — không dựng lại quá khứ được.

**File:** `backend/migrations/versions/0003_vinfast_event_history.py`

- [ ] `raw.vinfast_order_status_history`:
      grain = **1 dòng / (order_id, status, status_at)**.
      ```
      status_history_id BIGSERIAL PK
      order_id          BIGINT NOT NULL REFERENCES raw.vinfast_orders(order_id)
      status            VARCHAR(20) NOT NULL   -- CHECK cùng tập với vinfast_orders
      status_at         TIMESTAMPTZ NOT NULL   -- sự kiện xảy ra lúc nào (dùng cho PIT)
      recorded_at       TIMESTAMPTZ NOT NULL   -- hệ thống ghi nhận lúc nào (late-arriving)
      UNIQUE (order_id, status, status_at)
      INDEX (order_id, status_at)
      ```
- [ ] `raw.vinfast_vehicle_handover`:
      grain = **1 dòng / (order_id, vehicle_id)**.
      ```
      handover_id    BIGSERIAL PK
      order_id       BIGINT NOT NULL REFERENCES raw.vinfast_orders(order_id)
      customer_id    BIGINT NOT NULL REFERENCES raw.customers(customer_id)
      vehicle_id     VARCHAR(50) NOT NULL
      handover_status VARCHAR(20) NOT NULL   -- scheduled | completed | reversed
      handed_over_at TIMESTAMPTZ            -- NULL nếu chưa completed
      reversed_at    TIMESTAMPTZ
      recorded_at    TIMESTAMPTZ NOT NULL
      UNIQUE (order_id, vehicle_id)
      INDEX (customer_id, handed_over_at)
      CONSTRAINT chk_handover_completed_needs_time
          CHECK (handover_status <> 'completed' OR handed_over_at IS NOT NULL)
      CONSTRAINT chk_handover_reversed_needs_time
          CHECK (handover_status <> 'reversed' OR reversed_at IS NOT NULL)
      ```
- [ ] `downgrade()` drop 2 bảng — Alembic bắt buộc, đừng để `pass`.
- [ ] REVOKE cho `feature_agent_reader` là **tự động** (schema `raw` đã revoke ở
      `db/schema/*.sql` mục 7 + default privileges). Chỉ cần verify, không thêm GRANT.
- [ ] `tests/test_vinfast_event_history.py`: insert handover `completed` thiếu
      `handed_over_at` ⇒ `IntegrityError`; insert trùng `(order_id, vehicle_id)` ⇒ lỗi;
      `test_no_order_has_two_terminal_statuses` — không `order_id` nào có cả `completed`
      và `cancelled` trong history (`completed` là trạng thái cuối, chốt ở
      `docs/vehicle_owner_semantics.md` mục 5).

**Không làm:** view `current_status` (migration 008 trong tracker). Feature pipeline đọc
history trực tiếp; view chỉ phục vụ người vận hành xem tay — thêm khi có người hỏi.

---

## Task 2.2 — Point-in-time VinFast features

**Mục tiêu:** snapshot ngày D chỉ nhìn sự kiện `event_time <= D 23:59:59`.

**File:** `backend/migrations/versions/0004_extend_vinfast_transaction.py`,
`backend/app/semantic/feature_spec.py`, `backend/scripts/generate_mock_data.py`

- [ ] Sinh mock cho 2 bảng mới trong `generate_raw()`:
      - Mỗi order sinh chuỗi status hợp lệ `created → processing → completed`, mỗi bước
        cách nhau vài ngày, `status_at` nằm trong `EVENT_DAYS_BACK`.
      - Chỉ order `order_type='vehicle'` + completed mới **có thể** có handover, và cố ý
        cho **~30% chưa bàn giao** → buyer ≠ owner mới quan sát được.
      - `handed_over_at` = `completed_at` + 5..60 ngày ⇒ có customer là buyer ở snapshot
        này nhưng chỉ thành owner ở snapshot sau. Đây là case chứng minh PIT chạy đúng.
      - Cho ~2% handover `reversed` (trả xe) và ~3% event `recorded_at` trễ 10–40 ngày.
- [ ] Thêm 7 feature vào `feature_spec.py` (mục VinFast), rồi
      `python -m scripts.generate_semantic_layer` để cập nhật YAML + mô tả VI/EN:
      `vehicle_purchase_completed_count_l1m`, `vehicle_delivered_count_l1m`,
      `is_vehicle_buyer`, `is_vehicle_owner`, `first_vehicle_purchase_date`,
      `first_vehicle_handover_date`, `days_since_last_vehicle_handover`.
- [ ] Migration `0004` thêm đúng 7 cột đó vào `feature.vinfast_transaction`.
      **Test `test_feature_spec_matches_migration` sẽ đỏ nếu lệch** — đó là điểm quan trọng,
      giữ nguyên cơ chế đó.
- [ ] Trong `build_features()`, tính theo cutoff:
      ```python
      cutoff = datetime.combine(snapshot, time.max, UTC)
      completed = [h for h in status_hist[oid] if h["status"]=="completed" and h["status_at"] <= cutoff]
      owned = [h for h in handovers[cid]
               if h["handover_status"]=="completed" and h["handed_over_at"] <= cutoff
               and not (h["reversed_at"] and h["reversed_at"] <= cutoff)]
      ```
      Chú ý: reversed **sau** cutoff thì ở snapshot đó khách VẪN là owner.
- [ ] Thêm vào `data_quality_errors()` 3 invariant:
      `vehicle_delivered_count_l1m <= vehicle_purchase_completed_count_l1m`;
      `is_vehicle_owner=1 ⇒ is_vehicle_buyer=1`;
      `first_vehicle_handover_date >= first_vehicle_purchase_date`.
- [ ] `tests/test_point_in_time.py`:
      - future-leak: dựng 1 handover ở ngày D+10, build snapshot D ⇒ `is_vehicle_owner=0`.
      - late-arriving: `status_at` ≤ D nhưng `recorded_at` > D ⇒ **vẫn tính** (ta dùng
        event time, không dùng ingest time).
      - reversed: reverse trước D ⇒ mất owner; reverse sau D ⇒ giữ owner.
      - buyer ≠ owner: tồn tại ≥1 customer `is_vehicle_buyer=1 AND is_vehicle_owner=0`.

**Xong khi:** 4 test trên pass 100% và `data_quality_errors()` trả rỗng sau khi seed.

---

## Task 2.3 — `feature.customer_cross_bu_feature`

**Mục tiêu:** trả lời cross-BU bằng **1 bảng đã tính sẵn**, không để LLM tự join.

**File:** `backend/migrations/versions/0005_create_customer_cross_bu_feature.py`,
`feature_spec.py`, `generate_mock_data.py`

- [ ] Bảng, grain `PRIMARY KEY (customer_id, snapshot_date)` — trùng grain 2 bảng hiện có:
      ```
      is_active_gsm_l1m           BOOLEAN
      is_active_vinfast_l1m       BOOLEAN
      is_cross_bu_active_l1m      BOOLEAN   -- AND của 2 cờ trên
      gsm_spend_l1m               NUMERIC(18,2)
      vinfast_spend_l1m           NUMERIC(18,2)
      combined_spend_l1m          NUMERIC(18,2)
      dominant_business_unit_l1m  VARCHAR(10)  -- 'GSM' | 'VINFAST' | 'TIE' | NULL
      cross_bu_engagement_score   NUMERIC(5,4)
      is_vehicle_owner            BOOLEAN
      gsm_active_vehicle_owner_flag BOOLEAN
      ```
- [ ] **Chốt null/zero semantics và ghi vào `null_meaning` của catalog** (cột này đã có sẵn,
      frontend đang hiển thị):
      - khách chưa từng có đơn VF ⇒ `vinfast_spend_l1m = NULL` (không phải 0) — "không có
        dữ liệu" khác "chi tiêu bằng 0".
      - `combined_spend_l1m = COALESCE(gsm,0) + COALESCE(vf,0)`, NULL chỉ khi cả hai NULL.
      - `dominant_business_unit_l1m = NULL` khi combined = 0 hoặc NULL. Bằng nhau ⇒ `'TIE'`,
        đừng lặng lẽ chọn GSM.
- [ ] `cross_bu_engagement_score`: chốt công thức đơn giản, ghi vào description —
      `min(gsm, vf) / max(gsm, vf)` trên spend đã chuẩn hóa (0 = một phía, 1 = cân bằng).
      Đừng bịa công thức phức tạp không giải thích được cho business.
- [ ] Build bằng **FULL OUTER JOIN** trên `(customer_id, snapshot_date)` — INNER JOIN sẽ
      mất khách một-BU, đúng cái nhóm cần đếm nhất.
- [ ] Thêm synonyms VI: "khách dùng cả hai", "vừa đi GSM vừa mua VinFast", "chủ xe đi GSM",
      "khách chung", "overlap" (`feature_describer.SYNONYMS`, không hand-write description).
- [ ] `tests/test_cross_bu_feature.py`:
      - `COUNT(*) == COUNT(DISTINCT (customer_id, snapshot_date))` — không nhân dòng.
      - Tổng `gsm_spend_l1m` khớp tổng từ `feature.gsm_transaction` cùng snapshot.
      - Khách VF-only (mock `cid % 20 == 3`) có mặt trong bảng với `gsm_spend_l1m IS NULL`.

---

## Task 2.4 — Join catalog + Join Planner

**Mục tiêu:** mọi join đều nằm trong danh sách được duyệt; join lạ bị chặn.

**File:** `backend/migrations/versions/0006_create_join_catalog.py`,
`backend/app/agent/join_planner.py` (**một module, không phải package**),
`backend/scripts/seed_metadata.py`

- [ ] `metadata.join_catalog`:
      ```
      join_id SERIAL PK
      left_table  TEXT, right_table TEXT
      join_keys   TEXT[]      -- ['customer_id','snapshot_date']
      join_type   TEXT        -- inner | left | full
      cardinality TEXT        -- '1:1'
      requires_snapshot_key BOOLEAN NOT NULL DEFAULT TRUE
      allowed_intents TEXT[]
      is_active   BOOLEAN DEFAULT TRUE
      ```
- [ ] Seed đúng **1 dòng** lúc đầu: gsm_transaction ⋈ vinfast_transaction, 1:1,
      keys `[customer_id, snapshot_date]`. Thêm dòng khi có nhu cầu thật.
- [ ] `join_planner.plan(intent, tables) -> JoinPlan | None`:
      - Nếu câu hỏi cross-BU mà **`customer_cross_bu_feature` phủ được** → trả plan
        "single table", KHÔNG join. Đây là đường mặc định.
      - Chỉ khi cần cột không có trong bảng cross-BU mới tra `join_catalog`.
      - Trả kèm `explanation` tiếng Việt (hiện lên UI).
- [ ] `tests/test_join_planner.py`: positive (cặp trong catalog) + negative
      (bảng ngoài catalog, thiếu `snapshot_date`, `is_active=FALSE`).

**Bỏ bớt:** `configs/join_policy.yaml` — catalog đã ở DB, thêm YAML là 2 nguồn sự thật cho
cùng 1 thứ. Cấu hình thật (`sql_max_joins`) để trong `config.py` như mọi setting khác.

---

## Task 2.5 — Short-term clarification state (bổ sung, không viết lại)

**Đã có:** `app/agent/conversation.py` — TTL, cancel, replace-on-new-question, isolation
theo `session_id`, 7 test. Chỉ thêm phần Sprint 2 thiếu:

- [ ] Slot tường minh trong `PendingState`: `known_slots` / `missing_slots`
      (`business_unit`, `window`, `top_n`) thay vì chỉ giữ `original_question`.
      Lý do làm bây giờ: 2.6 cần biết **slot nào còn thiếu** để hỏi tiếp, chứ không phải
      nối chuỗi rồi chạy lại mù.
- [ ] Slot validator: "GSM"/"VF"/"cả hai" → `business_unit`; "3 tháng"/"l3m" → `window`;
      "top 10" → `top_n`. Trả lời KHÔNG hợp lệ ⇒ **giữ nguyên state**, hỏi lại (đã có test).
- [ ] Giữ `_STORE` in-memory. **Không thêm Redis** ở sprint này (1 instance, TTL 15 phút,
      mất state khi restart = user hỏi lại 1 câu). Nợ đã ghi trong `TODO.md`.
- [ ] Test bổ sung: resolve từng slot một khi thiếu 2 slot (BU rồi window).

---

## Task 2.6 — Multi-turn orchestrator

**File:** `app/agent/conversation.py` + `app/agent/pipeline.py`

- [ ] `pipeline.ask()` nhận thêm `join_plan` (optional) và truyền vào generator context.
- [ ] Thứ tự xử lý mỗi lượt: check pending → validate slot → merge → **revalidate intent**
      (chạy lại router trên text đã merge — hiện đã làm thế, giữ) → retriever →
      join planner nếu intent cross-BU → generator.
- [ ] Ghi `state_transition` vào `agent.query_log` (cột JSONB, cần
      `ALTER TABLE` trong migration `0006`): `{from, to, resolved_slot}`.
- [ ] **Không** đẩy toàn bộ chat history vào prompt — chỉ câu đã merge. Giữ nguyên nguyên tắc
      pipeline stateless.
- [ ] `tests/test_multi_turn.py`: UC2-01 end-to-end (thiếu BU → hỏi → "GSM" → chạy → state
      bị xóa), + cross-BU chỉ chạy khi đủ slot.

---

## Task 2.7 — Generator v2

**File:** `app/agent/generator.py`, prompt trong cùng file (đang inline — giữ vậy)

- [ ] Thêm vào prompt: bảng `customer_cross_bu_feature` + **quy tắc buyer ≠ owner**
      ("`is_vehicle_owner` chỉ từ handover; KHÔNG suy ra từ `status='completed'`").
- [ ] Truyền `join_plan.explanation` vào context khi có; cấm LLM tự chế join key —
      validator sẽ chặn, nhưng nói trước ở prompt để giảm vòng repair.
- [ ] Cho phép CTE (`WITH`) — guard đã chấp nhận `WITH`, kiểm tra lại giới hạn số CTE.
- [ ] `assumptions` (đã có trong `GenerationResponse`) dùng để trả partial answer:
      trả lời được phần nào thì nói rõ phần nào thiếu.
- [ ] Version prompt: thêm `prompts/CHANGELOG.md` ghi 1 dòng/lần đổi + số eval trước/sau.
      **Đây là file duy nhất đáng thêm** trong nhóm "prompt versioning" của tracker.
- [ ] Regression: toàn bộ 40 case dev của Sprint 1 phải giữ nguyên kết quả.

---

## Task 2.8 — Validator/guard v2

**File:** `app/sql/guards.py` (đã là AST `sqlglot` — đúng nền để làm tiếp), `app/config.py`

- [ ] Thêm `feature.customer_cross_bu_feature` vào `_FEATURE_TABLES` (nợ đã ghi trong `TODO.md`).
- [ ] Từ AST, trích mọi `exp.Join` → so với `join_catalog`:
      - cặp bảng không có trong catalog ⇒ reject;
      - điều kiện join thiếu `snapshot_date` ⇒ reject;
      - `JOIN` không có `ON` (Cartesian) ⇒ reject.
- [ ] `sql_max_joins` (mặc định 2) vào `config.py`.
- [ ] `statement_timeout` đã enforce ở `executor._prepare_query_connection` — chỉ thêm test
      là query chậm bị cắt, không viết lại.
- [ ] Log mọi lần reject vào `agent.sql_validation_log` (đã có bảng).
- [ ] `tests/test_sql_validator_v2.py` — adversarial, mỗi case 1 dòng:
      join theo mỗi `customer_id`; `CROSS JOIN`; join `raw.*`; join 3 bảng;
      subquery lồng chạm `raw`; UNION với bảng ngoài allowlist.

**Xong khi:** safety rejection = 100%, và test guard Sprint 1 vẫn xanh.

---

## Task 2.9 — Result interpretation & visualization

**Đã có:** `ResultChart.tsx` (bar), `ResultView.tsx` (toggle bảng/chart), `SqlPanel`,
coverage + confidence + warning trong `AskResponse`. Việc còn lại:

- [ ] Phân loại result shape ở **backend** (`app/agent/pipeline.py`, ~15 dòng):
      1 dòng × 1 cột ⇒ `scalar`; cột 1 là date ⇒ `time_series`;
      cột 1 text + cột 2 số ⇒ `category`; còn lại ⇒ `table`.
      Trả `result_shape` trong `AskResponse` + mirror sang `frontend/src/types.ts`.
- [ ] Frontend map shape → view: `scalar` → KPI card (component mới ~20 dòng),
      `time_series` → `LineChart` (recharts đã cài), `category` → bar (đã có),
      `table` → bảng (đã có).
- [ ] Cảnh báo hiển thị rõ (đã có chỗ, cần thêm nội dung):
      low coverage (`non_null_ratio < 0.3`), partial answer (có `assumptions`),
      cross-BU coverage thấp (UC2-06).
- [ ] `tests/test_result_shape.py` — 4 case, thuần hàm, không cần DB.

**Bỏ bớt:** `metadata.visualization_config` (bảng DB) và `chart_spec.schema.json`. Quy tắc
chọn chart là 4 dòng `if`; đưa vào DB nghĩa là mỗi lần đổi chart phải chạy migration.
→ Thêm bảng khi business thật sự muốn tự cấu hình mà không deploy.

---

## Task 2.10 — Chat UI (bổ sung nhỏ)

**Đã có:** chat, table/chart, SQL + copy, confidence/coverage, technical details, CSV,
`session_id` giữ qua lượt.

- [ ] Nút **hủy câu hỏi đang chờ** (gửi "hủy" — backend đã hiểu từ này).
- [ ] Hiển thị `join_explanation` khi câu trả lời dùng cross-BU (user cần biết dữ liệu ghép
      thế nào mới tin được số).
- [ ] Nút trả lời nhanh "GSM" / "VinFast" khi backend trả `clarify` về BU.

---

## Task 2.11 — Benchmark Sprint 2

**File:** `data/golden_set.yaml`, `scripts/golden_dataset.py`, `scripts/run_eval.py` (dùng lại
nguyên hạ tầng Sprint 1 — chỉ thêm case và category).

- [ ] Chạy `run_eval --split dev --tag sprint1_final` **TRƯỚC** khi sửa gì → có mốc so sánh.
      Hiện chưa có số baseline nào được ghi lại; không có mốc thì không chứng minh được
      Sprint 2 không làm hỏng Sprint 1.
- [ ] Thêm ~30 case vào `golden_set.yaml`, category mới: `cross_bu`, `buyer_vs_owner`,
      `point_in_time`, `multi_turn`, `join_safety`. Chia dev/holdout theo tỉ lệ cũ (2:1).
- [ ] Cập nhật `scripts/golden_dataset.py`: hiện nó **báo lỗi nếu có case cross-BU**
      (`expected_business_unit not in (GSM, VINFAST)`) — đổi thành cho phép `CROSS_BU`.
- [ ] Sinh lại `HOLDOUT_CHECKSUM` + `HOLDOUT_VERSION` sau khi thêm case, rồi **không đụng nữa**.
- [ ] Chạy dev → sửa → chạy dev. Holdout **chạy đúng 1 lần** ở cuối sprint.
- [ ] `reports/sprint2_evaluation.md` + failure analysis (mỗi case fail: 1 dòng nguyên nhân
      thuộc tầng nào — retrieval / join / generation / execution).

### Bảng metric (Definition of Done)

| Metric | Target | Đo bằng |
|---|---:|---|
| Cross-BU table selection | ≥ 90% | retrieval recall trong `run_eval` |
| Join-plan accuracy | ≥ 90% | `test_join_planner` + eval category `cross_bu` |
| PIT correctness | 100% | `tests/test_point_in_time.py` |
| Buyer/owner accuracy | 100% | eval category `buyer_vs_owner` |
| Multi-turn resolution | ≥ 95% | eval category `multi_turn` |
| State isolation | 100% | `test_conversation.py` (đã pass) |
| SQL executable rate | ≥ 90% | `run_eval` |
| Result accuracy | ≥ 85% | execution accuracy (comparator) |
| Safety rejection | 100% | `test_sql_validator_v2.py` |
| Visualization selection | ≥ 85% | `test_result_shape.py` |
| Raw/PII access | 0 case | guard test + reader role |

---

## Bước cuối — gỡ refusal (làm SAU CÙNG, sau khi 2.1–2.4 xanh)

`app/agent/router.py` đang chặn cross-BU và handover. Gỡ theo đúng thứ tự này:

- [ ] [router.py:74](backend/app/agent/router.py#L74) `_vehicle_handover` — bỏ refusal, đổi
      thành route bình thường (chỉ được làm khi `is_vehicle_owner` đã có dữ liệu thật).
- [ ] [router.py:86](backend/app/agent/router.py#L86) `_owner` — như trên.
- [ ] [router.py:119-125](backend/app/agent/router.py#L119-L125) `gsm and vf` — đổi từ
      `out_of_scope` thành `IntentType.cross_bu` (thêm enum vào `contracts.py`).
- [ ] **Giữ nguyên** refusal `_loyalty`, `_cross` (cross-PnL/VinClub), `_out_catalog`,
      `_raw_pii` — vẫn ngoài scope Sprint 2.
- [ ] Sửa các case golden set Sprint 1 đang kỳ vọng `expected_refusal: vehicle_owner`
      (`data/golden_set.yaml:439,449,545`) — chúng sẽ đỏ, và đó là **đúng**: đổi kỳ vọng
      có chủ đích, đừng xóa case.

---

## Rủi ro đã biết

1. **Quên `snapshot_date` trong join** → nhân dòng theo số snapshot (hiện 6) → mọi số ×6 mà
   nhìn vẫn "hợp lý". Đây là lỗi nguy hiểm nhất của sprint. Chặn ở guard (2.8), không tin prompt.
2. **Suy owner từ `status='completed'`** → sai định nghĩa nghiệp vụ, không lỗi kỹ thuật nào
   bắt được. Chặn bằng test buyer≠owner ở 2.2 + prompt ở 2.7.
3. **Mock không có case buyer≠owner** → mọi test PIT pass giả. Bắt buộc ~30% vehicle order
   chưa handover ở 2.2.
4. **Thêm bảng nhưng quên `feature_spec.py`** → test inventory đỏ. Đó là tính năng, sửa spec
   chứ đừng sửa test.
