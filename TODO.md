# TODO — trạng thái hiện tại

Cập nhật: 2026-07-23.

## Đã hoàn thành

- [x] Backend scaffold: config, SQLAlchemy/PostgreSQL, Pydantic schemas.
- [x] PostgreSQL 17.2; Alembic ở revision `0002 (head)`.
- [x] Schema Sprint 1 ban đầu từ `db/schema/*.sql` qua migration `0001`.
- [x] Đối soát inventory workbook với DB cho hai bảng:
  - GSM: 167/167 retained feature.
  - VinFast: 186/186 retained feature.
  - Không thiếu và không trùng tên canonical.
- [x] Migration `0002` bổ sung đủ 353 cột canonical. Cột legacy được giữ vật lý
      để an toàn dữ liệu nhưng bị tắt khỏi catalog/query surface.
- [x] Canonical `feature_spec` gồm đúng 353 feature.
- [x] Semantic describer và YAML song ngữ VI+EN cho 353 feature.
- [x] Metadata seed idempotent:
  - 353 feature active.
  - 328 feature queryable.
  - 25 feature NVSO/WO restricted và needs-review.
  - 4.537 synonym canonical được seed trong lượt hiện tại.
- [x] Mock generator theo `raw.customers`, `raw.date_dim`, `raw.gsm_trips`,
      `raw.vinfast_orders` và snapshot grain `customer_id + snapshot_date`.
- [x] Mock data hiện tại: 120 customers, 731 dates, 3.721 trips, 440 orders,
      120 GSM snapshots và 120 VinFast snapshots.
- [x] Retriever song ngữ VI+EN: lọc BU, metric, status, window, compare-window,
      support status và adaptive score cutoff.
- [x] Context builder chỉ đưa retrieved canonical feature, dtype, unit,
      null meaning, VI/EN description và policy vào generator.
- [x] Agent pipeline core: router, retriever, context, JSON SQL generator,
      validator, repair loop, executor, narrator và pipeline trace.
- [x] System prompt generator bằng tiếng Anh và JSON parser chịu được code fence,
      trailing text, assumptions/selected_features dạng string.
- [x] SQL guard: single SELECT/WITH, schema/table allowlist, deny raw/PII,
      deny SELECT *, DML/DDL, dangerous functions và áp row limit.
- [x] Validator chặn feature ngoài retrieved context, ngoài canonical inventory
      và cột legacy không queryable.
- [x] Audit vào `agent.query_log` và `agent.sql_validation_log`.
- [x] Streamlit test UI hiển thị pipeline trace, retrieved features, SQL,
      result, confidence và repair count.
- [x] Offline tests: 45/45 pass.

## Còn lại

- [ ] Bổ sung test mock aggregation theo từng họ stem/window và metadata
      idempotency trực tiếp trên PostgreSQL.
- [ ] Bổ sung golden set VI+EN cho GSM, VinFast, aggregate, filter,
      window comparison, refusal và ambiguous question.
- [ ] Đo retrieval hit@k, execution accuracy, refusal accuracy, repair success
      và latency.
- [ ] Chốt định nghĩa nghiệp vụ NVSO/WO để quyết định mở query cho 25 feature.
- [ ] Quyết định change-control để drop các cột legacy vật lý sau khi hết thời
      gian tương thích.
- [ ] FastAPI app: `/ask`, `/features`, `/health`.
- [ ] React + Vite + Tailwind frontend.
- [ ] README hướng dẫn setup/run/seed/test.
- [ ] Docker Compose/PostgreSQL bootstrap hoàn chỉnh.
- [ ] Final end-to-end verification với LLM thật và golden set.

## Lệnh kiểm tra

```powershell
cd backend
.venv\Scripts\alembic.exe current
.venv\Scripts\python.exe -m scripts.generate_semantic_layer
.venv\Scripts\python.exe -m scripts.generate_mock_data
.venv\Scripts\python.exe -m pytest -q
```
