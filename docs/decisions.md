# Sổ quyết định kiến trúc (ADR)

Gộp từ `docs/adr/0001…0005`. Mỗi mục là một quyết định đã chốt, kèm bối cảnh và cái giá
phải trả — **không phải hướng dẫn sử dụng**. Đổi hành vi liên quan thì đọc mục tương ứng
trước, và nếu đổi ngược lại quyết định thì sửa **tại chỗ** kèm ngày và lý do.

Trong code và test, các quyết định được nhắc bằng tên ("ADR 0002"), không bằng đường dẫn —
đánh số ở đây phải giữ nguyên vĩnh viễn kể cả khi một quyết định bị thay thế.

| # | Quyết định | Ngày | Trạng thái |
|---|---|---|---|
| [0001](#0001) | Tính sẵn bảng cross-BU thay vì để LLM join runtime | 2026-07-27 | chấp nhận |
| [0002](#0002) | Point-in-time dùng event time, không dùng ingest time | 2026-07-27 | chấp nhận |
| [0003](#0003) | Không thêm tầng feature global ở Sprint 2 | 2026-07-28 | chấp nhận |
| [0004](#0004) | dbt là tầng transform; Alembic vẫn sở hữu DDL | 2026-08-07 | chấp nhận |
| [0005](#0005) | Không dùng Cube làm tầng ngữ nghĩa | 2026-08-07 | chấp nhận |

---

<a id="0001"></a>

## 0001 — Tính sẵn bảng cross-BU thay vì để LLM join runtime

- Ngày: 2026-07-27 · Trạng thái: chấp nhận (Task 2.0)
- Liên quan: `join_policy.md`, Task 2.3, 2.4

### Bối cảnh

Sprint 2 phải trả lời câu hỏi xuyên GSM ↔ VinFast (overlap khách, so sánh chi tiêu, chủ xe
VinFast có đi GSM không). Hai bảng feature cùng grain `customer_id + snapshot_date`, nên về
kỹ thuật LLM hoàn toàn có thể tự sinh câu JOIN.

### Vấn đề

Join sai `snapshot_date` biến 1:1 thành 1:N với N = số snapshot (hiện 6). Kết quả: mọi
`SUM`/`COUNT` bị nhân 6. Câu SQL vẫn chạy, kết quả vẫn đúng định dạng, số vẫn "trông hợp lý"
— người dùng phi kỹ thuật không có cách nào phát hiện.

Đây là dạng lỗi tệ nhất với một BI agent: **sai im lặng**.

### Các lựa chọn

1. **LLM tự join, validator kiểm tra.** Linh hoạt nhất, nhưng đúng/sai phụ thuộc mỗi lần sinh
   SQL, và độ khó của validator tăng theo độ phức tạp câu SQL (subquery, CTE, UNION).
2. **Tính sẵn `feature.customer_cross_bu_feature`.** Join xảy ra đúng **một lần**, trong
   pipeline deterministic, có test. Agent chỉ `SELECT` từ một bảng — không có gì để sai.
3. **Chỉ cho join theo view định nghĩa sẵn.** Gần như (2) nhưng tính lại mỗi query, và view
   vẫn phải qua guard.

### Quyết định

Chọn **(2)**, có **(1) làm đường dự phòng hẹp**: join runtime chỉ được phép khi cặp bảng nằm
trong `metadata.join_catalog` và điều kiện join có đủ `snapshot_date` (Task 2.4 + 2.8).

Join Planner ưu tiên bảng tính sẵn; chỉ rơi xuống join catalog khi câu hỏi cần cột mà bảng
tính sẵn không có.

### Hệ quả

**Tốt**

- Lỗi nhân dòng bị loại bỏ về mặt cấu trúc, không phụ thuộc chất lượng prompt.
- Có chỗ chạy data-quality test (`COUNT(*) == COUNT(DISTINCT (customer_id, snapshot_date))`,
  tổng khớp bảng nguồn).
- Prompt ngắn hơn, ít token, ít vòng repair.
- Null/zero semantics chốt được ở một chỗ thay vì mỗi câu SQL một kiểu.

**Xấu**

- Thêm một bảng phải maintain; mỗi feature cross-BU mới cần migration + cập nhật
  `feature_spec.py` + seed lại catalog.
- Câu hỏi cross-BU nằm ngoài các cột đã tính sẵn sẽ bị từ chối thay vì được trả lời sáng tạo.
  **Đây là đánh đổi có chủ đích**: từ chối rõ ràng tốt hơn số sai im lặng.
- Bảng tính sẵn phải chạy lại khi feature nguồn đổi; drift bị bắt bởi test tổng-khớp-nguồn.

### Xem lại khi nào

Nếu > 30% câu hỏi cross-BU thật bị từ chối vì thiếu cột, cân nhắc mở rộng cột tính sẵn (rẻ)
trước khi nới join runtime (đắt và rủi ro).

---

<a id="0002"></a>

## 0002 — Point-in-time dùng event time, không dùng ingest time

- Ngày: 2026-07-27 · Trạng thái: chấp nhận (Task 2.0)
- Liên quan: `vehicle_owner_semantics.md` mục 3, Task 2.1, 2.2

### Bối cảnh

Sprint 2 thêm `raw.vinfast_order_status_history` và `raw.vinfast_vehicle_handover`, mỗi bản
ghi có hai mốc thời gian:

- **event time** (`status_at`, `handed_over_at`, `reversed_at`) — sự kiện xảy ra lúc nào;
- **ingest time** (`recorded_at`, `ingested_at`) — hệ thống ghi nhận lúc nào.

Sự kiện đến trễ (late-arriving) là chuyện bình thường: bàn giao xe ở đại lý ngày 10, hệ thống
đồng bộ ngày 40.

Sprint 1 không có vấn đề này vì `raw.vinfast_orders` chỉ có `updated_at` — dùng nó cho snapshot
cũ là rò dữ liệu tương lai, nên Sprint 1 chặn hẳn câu hỏi về owner.

### Lựa chọn

1. **Event time.** Feature phản ánh *thực tế đã xảy ra*. Snapshot cũ có thể **đổi giá trị** khi
   dữ liệu trễ về.
2. **Ingest time.** Snapshot bất biến sau khi tính (reproducible), nhưng số không khớp thực tế:
   khách đã nhận xe ngày 10 mà báo cáo tháng đó nói chưa.

### Quyết định

Chọn **event time**.

Người dùng là quản lý PnL hỏi câu nghiệp vụ ("tháng trước có bao nhiêu khách nhận xe"). Câu
trả lời phải đúng với thực tế kinh doanh, không đúng với lịch trình pipeline dữ liệu.

### Hệ quả

**Tốt**

- Số khớp với cái business tự đếm được.
- Test PIT viết được rõ ràng: cutoff = `snapshot_date 23:59:59.999999`, lọc theo event time.

**Xấu**

- Snapshot **không bất biến**: chạy lại pipeline sau khi dữ liệu trễ về sẽ ra số khác cho cùng
  một `snapshot_date`. Chấp nhận được vì mock seed lại bằng seed cố định; ở hệ thật cần quy
  ước "báo cáo chốt sau N ngày".
- Không phát hiện được vấn đề chất lượng đường ống bằng chính feature — phải theo dõi độ trễ
  `recorded_at - status_at` riêng nếu cần.
- `recorded_at` vẫn phải lưu (không được bỏ) để về sau còn dựng lại được "tại thời điểm đó hệ
  thống *biết* gì" nếu audit yêu cầu.

### Test bắt buộc

- `status_at` ≤ D nhưng `recorded_at` > D ⇒ **vẫn được tính** vào snapshot D.
- `status_at` > D ⇒ **không** được tính (future leak).
- `reversed_at` > D ⇒ tại snapshot D khách **vẫn** là owner.

Ba ca này nay được canh bằng dữ liệu dựng sẵn trong
`dbt/models/silver/unit_tests.yml::quyen_so_huu_xe_theo_moc_thoi_gian`, cộng với
`dbt/tests/assert_no_future_events_in_snapshot.sql` chạy trên toàn bộ dữ liệu.

---

<a id="0003"></a>

## 0003 — Không thêm tầng feature global (toàn công ty) ở Sprint 2

- Ngày: 2026-07-28 · Trạng thái: chấp nhận
- Liên quan: Task 2.3, [0001](#0001), Sprint 3 backlog

### Bối cảnh

Có đề xuất thêm tầng `global_aggregate`: **56 feature** ở mức toàn công ty, grain
**1 dòng / ngày** (không có `customer_id`), gồm 5 nhóm:

| Nhóm | Số | Ví dụ |
|---|---:|---|
| Quy mô tổng hợp | 21 | `global_total_revenue_sum_l1m` |
| Tỷ trọng đóng góp | 16 | `global_share_gsm_revenue_pct_l1m` |
| Chênh lệch tăng trưởng | 6 | `global_growth_gap_revenue_gsm_vs_vinfast_l1m_vs_l3m` |
| Chất lượng vận hành | 9 | `global_cancel_rate_gsm_pct_l1m` |
| Tương quan liên đơn vị | 4 | `global_corr_revenue_gsm_vinfast_l1m` |

Câu hỏi: bộ này có phải là Task 2.3 không?

### Quyết định

**Không.** Task 2.3 giữ nguyên phạm vi: `feature.customer_cross_bu_feature`, grain
`customer_id + snapshot_date`. Tầng global hoãn sang Sprint 3.

### Lý do

**1. Sai grain, khác bảng.** 2.3 trả lời câu hỏi *về khách hàng* ("bao nhiêu khách vừa đi GSM
vừa mua VinFast"). Bộ global trả lời câu hỏi *về công ty* ("tổng doanh thu tháng này"). Hai
grain khác nhau ⇒ hai bảng khác nhau, không gộp được.

**2. Không use case nào của Sprint 2 cần nó.** Cả 6 use case bắt buộc (UC2-01…UC2-06) đều ở
mức khách hàng.

**3. 52/56 feature là SQL một dòng.** Số toàn công ty = `SUM(...)` trên bảng feature
per-customer đã có; tỷ trọng = hai `SUM` chia nhau; chênh lệch tăng trưởng = hiệu hai cột ratio
sẵn có; cancel rate = tỷ số hai cột sẵn có. Precompute thứ agent tự viết được là speculative.

**4. Chi phí thật là retrieval, không phải storage.** Thêm 56 feature mang từ khóa "tổng doanh
thu", "số khách hoạt động" sẽ cạnh tranh trực tiếp với feature per-customer cùng nghĩa: câu
"khách nào chi tiêu nhiều nhất" rất dễ trúng `global_total_revenue_sum_l1m` và trả về một con
số duy nhất thay vì danh sách khách.

**5. Bốn feature tương quan phải bỏ, vì hai lý do độc lập:**

- **Không đủ dữ liệu.** `CORR(gsm.revenue_daily, vinfast.revenue_daily)` cần chuỗi doanh thu
  **theo ngày**. Feature store có 6 snapshot cách nhau 30 ngày — 6 điểm quan sát. Hệ số tương
  quan trên 6 điểm là số vô nghĩa nhưng trông y hệt số thật.
- **Mời gọi suy diễn nhân quả**, thứ Sprint 2 cấm rõ. Đưa hệ số tương quan cho quản lý PnL thì
  câu hỏi tiếp theo luôn là "vậy GSM giảm là do VinFast tăng à?".

### Hệ quả

**Tốt**

- 2.3 giữ phạm vi nhỏ, đo được, đúng use case.
- Retrieval surface không phình thêm 15% ngay trước lúc benchmark Sprint 2.
- Câu hỏi mức công ty vẫn trả lời được — bằng `SUM` trên bảng hiện có, không cần cột mới.

**Xấu**

- Câu hỏi mức công ty tốn một vòng LLM sinh SQL aggregate thay vì đọc thẳng một cột. Chấp nhận:
  đây là câu hỏi hiếm ở use case on-demand, và là việc của reporter đêm.
- Khi Sprint 3 làm reporter, phải dựng bảng global rồi mới narrate được.

### Sprint 3 làm gì (khi tới đó)

Dựng `feature.global_daily` bằng **~6 stem × window**, sinh bằng vòng lặp, không liệt kê tay
56 cột:

```
global_txn_completed_count_{window}      global_share_{bu}_revenue_pct_{window}
global_revenue_sum_{window}              global_cancel_rate_{bu}_pct_{window}
global_active_customer_count_{window}    global_avg_txn_value_{bu}_{window}
```

Hai điều kiện tiên quyết:

1. **Grain ngày thật.** Reporter cần chuỗi theo ngày, không phải 6 snapshot cách 30 ngày.
2. `global_active_customer_count` là cột **đáng** precompute duy nhất trong bộ đề xuất:
   `COUNT(DISTINCT customer_id)` qua hai bảng dễ bị LLM viết thành tổng hai count, tính trùng
   khách dùng cả hai BU. Nhóm còn lại vẫn nên để SQL tự tính nếu chỉ hỏi on-demand.

### Xem lại khi nào

Nếu benchmark Sprint 2 cho thấy > 20% câu hỏi thật là câu mức công ty, hoặc reporter đêm được
ưu tiên lên trước Sprint 3.

---

<a id="0004"></a>

## 0004 — dbt là tầng transform; Alembic vẫn sở hữu DDL

- Ngày: 2026-08-07 · Trạng thái: chấp nhận
- Liên quan: `dbt_migration_runbook.md`, migration `0015`, `backend/scripts/publish_gold.py`,
  [0002](#0002), [0005](#0005)

### Bối cảnh

CLAUDE.md từng ghi "dbt và Cube — ngoài phạm vi, mở lại thì phải qua ADR". Đây là ADR đó.

Trước khi port, toàn bộ tầng transform nằm trong `backend/scripts/generate_mock_data.py`:
~350 dòng Python nhảy thẳng từ event thô sang 3 bảng feature. Hai quy tắc nghiệp vụ quan trọng
nhất — buyer-vs-owner và event-time-vs-ingest-time ([0002](#0002)) — nằm chôn trong một hàm 45
dòng (`_vehicle_pit`), không có tên trong lineage, không test độc lập được, và quality gate là
hàm tự viết `raise RuntimeError` chỉ chạy khi seed.

Quan trọng hơn: **toàn bộ tầng đó là artefact của mock data**. Gặp warehouse thật phải viết lại
bằng SQL từ đầu.

### Quyết định

#### 1. Medallion đặt lên schema đã có, không đổi tên gì

```
raw  ->  silver  ->  dbt_work  ->  feature
bronze   (mới)       (mới)         gold, giữ nguyên contract vật lý
```

Không đổi `feature.*` thành `gold_*`: Agent, SQL guard, retriever, `semantic_layer.yaml` và
golden set đều neo vào tên đó. Đổi tên là phá contract để đổi lấy con số không.

#### 2. Alembic sở hữu MỌI DDL. dbt chỉ có DML trên `feature.*`

Migration `0015` cấp quyền như sau, và chỗ **không** cấp mới là điều quan trọng:

```sql
GRANT ALL ON SCHEMA silver, dbt_work TO dbt_transformer;   -- toàn quyền ở sân nhà
GRANT USAGE ON SCHEMA feature TO dbt_transformer;          -- USAGE, KHÔNG phải CREATE
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA feature TO dbt_transformer;
```

Không có `CREATE` trên schema `feature` ⇒ dbt và `publish_gold` **không thể** DROP hay ALTER
bảng gold, kể cả khi có người viết code sai. Đây là ranh giới ở tầng Postgres, không phải quy
ước trong tài liệu.

`backend/scripts/contract_check.py` + `backend/db/gold_contract.json` là bằng chứng chạy được:
cột, constraint, index, ACL, comment của `feature.*` phải khớp bản đã chốt.

#### 3. dbt **không** ghi thẳng vào `feature.*`; một script publish làm việc đó

Đây là điểm then chốt, và là chỗ bản kế hoạch đầu tiên đã sai. Bản đầu cho dbt
`materialized='incremental'` ghi thẳng vào bảng do Alembic tạo. Không dùng được, vì ba lý do
độc lập nhau:

| | |
|---|---|
| `delete+insert` của dbt tạo relation tạm `__dbt_tmp` **ngay trong schema đích** | ⇒ bắt buộc phải có `CREATE` trên `feature`, mâu thuẫn trực tiếp với quyết định 2 |
| một lần `--full-refresh` sơ ý | ⇒ dbt DROP rồi CREATE lại bảng: mất PK, CHECK, index, comment và GRANT do Alembic tạo |
| test của dbt chạy **sau** khi model đã ghi | ⇒ CHECK constraint của gold "cướp lời" test, báo lỗi ràng buộc thay vì một test đỏ có tên |

Thay bằng:

```
silver (view)  ->  dbt_work.int_*_candidate (table)
                        |
                   dbt test chạy Ở ĐÂY — đỏ thì dừng, feature.* chưa bị đụng
                        |
                   publish_gold.py:  BEGIN; DELETE feature.x; INSERT SELECT dbt_work.x; COMMIT;
                        |
                   feature.*
```

Đánh đổi: 424 cột được materialize hai lần. Ở 18.000 dòng chi phí thực đo là **1,8 giây** cho
cả ba bảng (`INSERT ... SELECT` chạy phía server). Rẻ hơn nhiều so với gọt cho dbt incremental
sống chung với Alembic.

`publish_gold` có ba chốt chặn **trước** khi ghi, vì nó DELETE rồi mới INSERT: nguồn không tồn
tại · **nguồn rỗng** · nguồn có cột gold không có. Chốt thứ hai quan trọng nhất và không hiển
nhiên: một lần dbt lỗi để lại bảng rỗng sẽ xoá sạch gold **mà transaction vẫn commit êm**.

#### 4. Hoãn Airbyte

Chưa có nguồn ngoài nào. Generator hiện ghi thẳng vào `raw.*` bằng SQLAlchemy, không đi qua
file hay OLTP riêng — không có gì cho Airbyte kết nối. Cắm khi có nguồn thật.

#### 5. Full recompute, chưa làm incremental filter

Mỗi lần chạy tính lại toàn bộ 6 snapshot rồi thay nguyên khối trong một transaction. Nhờ vậy
**late-arriving event tự đúng**: sự kiện về trễ vẫn thuộc snapshot mà nó xảy ra ([0002](#0002)),
và vì tính lại hết nên không có snapshot nào bị bỏ sót.

Khi dữ liệu lớn lên, thay `DELETE ALL` bằng recompute có lọc:

```
earliest_affected = min(status_at, handed_over_at, reversed_at, trip_start_time)
                    của các event mới ingest
⇒ chỉ tính lại snapshot_date >= earliest_affected
```

**Lọc theo event time, không phải `recorded_at`** — dùng ingest time ở đây là tái tạo lại đúng
lỗi mà [0002](#0002) cấm. Chưa implement; đây là thiết kế đã chốt, không phải gợi ý.

### Hệ quả

Đo được, không phải kỳ vọng:

| | Trước | Sau |
|---|---|---|
| Transform | 414 dòng Python | 5 model silver + 3 candidate SQL |
| Quy tắc PIT / buyer-owner | 1 hàm 45 dòng, không test riêng được | model có tên + 3 dbt unit test dữ liệu dựng sẵn |
| Quality gate | `raise RuntimeError` khi seed | 78 data test + 3 unit test, chạy **trước** khi ghi gold |
| Parity với bản Python | — | 0 dòng lệch / 3 bảng (2 ô tỷ lệ được tha) |
| Contract `feature.*` | — | khớp tuyệt đối, `contract_check --verify` |
| Eval | gold_sql_ok 72/72 · retrieval 59/72 · refusal 23/28 | **không đổi** |

**Hai ô tỷ lệ được tha.** Python chia bằng float64 rồi làm tròn half-to-even; Postgres `numeric`
chia chính xác rồi làm tròn half-away-from-zero. 25/27 ô lệch đã khử được bằng cách ép `float8`
+ `round()` một tham số; 2 ô còn lại lệch đúng `0.0001` do sai số biểu diễn float64 tại điểm
hoà. `parity_check` chỉ tha khi **cả ba** điều kiện đúng: là cột `_vs_`, lệch đúng `0.0001`, và
tổng số ô được tha ≤ 2.

**`parity` là bản chụp cuối cùng.** Sau cutover đường Python không còn tồn tại, nên schema
`parity` không tái tạo được. Xoá nó là mất thước đo vĩnh viễn.

**49 cột không bao giờ được ghi.** 20 GSM + 29 VinFast rơi vào DEFAULT ở cả bản Python lẫn bản
dbt. Candidate cố ý bỏ chúng; `publish_gold` để DB tự điền DEFAULT, và `parity_check` chỉ tha
khi đã xác minh baseline bằng đúng DEFAULT.

**Múi giờ là một biến, không phải hằng số rải rác.** `dbt_project.yml` có `business_timezone`,
hiện `UTC` để khớp bản Python. Warehouse thật gần như chắc chắn cắt ngày theo giờ Việt Nam —
đã lượng hoá: đổi sang `Asia/Ho_Chi_Minh` làm **35%** `trip_date` và **41%** `is_daytime` đổi
giá trị. Đổi một dòng ở đó, không sửa 15 chỗ.

### Câu còn mở — phải trả lời TRƯỚC khi cắm warehouse thật

Bốn mục dưới đây **chưa được quyết**; ghi ở đây để không rơi mất, không phải để chốt.

**1. Ai tạo `snapshot_date` mới?** `raw.feature_snapshot` hiện có 6 ngày do Python sinh như
hằng số. Với dữ liệu thật, mỗi kỳ phải có ai đó INSERT một ngày mới **trước khi** dbt chạy.
Chưa có chủ. Đây cũng là thứ chặn việc bật lịch chạy cho `nightly_job` của Dagster.

**2. `silver_vinfast_order_state` đọc `vinfast_orders.status`** thay vì dựng lại trạng thái từ
status history. Với mock thì hai nguồn nhất quán (generator sinh theo đúng chiều đó, và
`assert_order_status_history_terminal.sql` canh). Với dữ liệu thật thì `status` là trạng thái
**hiện tại** — dùng nó ở snapshot cũ là rò dữ liệu tương lai, đúng thứ [0002](#0002) cấm. Lưu ý
`silver_vehicle_purchase` **đã** dựng từ status history và không dính vấn đề này.

**3. `finished_*` đang ánh xạ thành `completed`.** Raw không có trạng thái `finished`; mock coi
hai cái là một. Nếu hệ thống nguồn phân biệt, mọi feature `finished_*` (22 stem × 5 cửa sổ)
đang trả lời sai câu hỏi.

**4. `wo` và `nvso` chưa được xác minh.** Ánh xạ sang `order_type IN ('work_order','nvso')` là
suy đoán từ tên. CLAUDE.md đã đánh dấu hai từ này là chưa xác nhận và yêu cầu không tự đặt nghĩa.

Mục 3 và 4 là **ngữ nghĩa của feature**, không phải của tầng transform — bản port giữ nguyên
hành vi cũ một cách có chủ ý, vì đổi nghĩa trong lúc port thì parity mất tác dụng làm thước đo.

---

<a id="0005"></a>

## 0005 — Cube is not adopted as the semantic layer

- Date: 2026-08-07 · Status: accepted
- Related: `dbt_migration_runbook.md` step 9, [0004](#0004), `backend/data/semantic_layer.yaml`
- **Language note:** this decision is recorded in English at the project owner's request;
  the other four are in Vietnamese.

### Context

The "Modern Data Platform" architecture this project follows places Cube as a semantic layer
between the warehouse and BI. During planning, Cube's scope was fixed to **serving Metabase/BI
only**; the Agent keeps its own `semantic_layer.yaml`.

Planning also set an explicit gate: *spike first, adopt only if at least ONE of four conditions
can be demonstrated*.

### Decision

**Do not adopt Cube.** No new service, no new compose profile, no new config files. Metabase
connects directly to `feature.*` through a read-only role.

### Evidence — four conditions, measured on the real system

Measured 2026-08-07 on PostgreSQL 18.4, `feature.*` = **18,000 rows** across 3 tables.

#### 1. Multiple dashboards sharing one metric — NO

There are no dashboards. The `metabase` service in `docker-compose.yml` sits behind its own
profile and only carries H2 for its internal metadata; no metric definition is stored, shared,
or duplicated anywhere.

Cube solves "the same metric is redefined in 5 dashboards, each one slightly differently." That
problem does not exist yet.

#### 2. Semantic consistency across consumers — TWO consumers exist, but Cube is still not the answer

**Correction (2026-08-07, after this was first written):** the first draft stated that Metabase
reaches the data through `POST /ask`. **That was wrong.** The project owner confirmed Metabase
will connect **directly to `feature.*`**. This trips one of the reopening thresholds listed
below, so condition 2 was re-evaluated from scratch. The conclusion is unchanged, but the
reasoning is entirely different — and it produces three required follow-ups.

So there really are two consumers: the Agent (via `semantic_layer.yaml`) and Metabase (direct
SQL).

But in this warehouse, **a metric is a COLUMN, not a formula**. "GSM revenue, last month" is not
an expression over fact tables — it is
`feature.gsm_transaction.completed_original_price_sum_l1m`, already computed. If Metabase and
the Agent read the same column, they **cannot** produce two different numbers. Preventing
exactly that is what Cube exists for, and the gold layer already prevents it.

What actually breaks with direct access is not the formula — it is **grain and NULL semantics**:

| Trap | Measured consequence |
|---|---|
| Forgetting `where snapshot_date = ...` | 2,121,503,000 instead of 336,396,000 — **6.3× too high** |
| `avg(coalesce(x, 0))` on a cross-BU column | 57,106,124 instead of 67,183,676 — **15% off** |
| Columns carry no description in Postgres | only **7 of 464** columns have a COMMENT. Metabase sources descriptions from there, so a user sees `finished_time_daytime_original_price_sum_l3m_vs_l12m` with nothing explaining it |

All three have fixes far cheaper than Cube, and Cube **cannot fix two of them** anyway — anyone
writing raw SQL inside Metabase bypasses Cube entirely:

| Trap | Fix |
|---|---|
| Snapshot double-counting | a **view** exposing only the latest snapshot — the trap disappears structurally |
| Undescribed columns | push the 381 existing Vietnamese descriptions from YAML into `COMMENT ON COLUMN`; Metabase surfaces them automatically |
| NULL vs 0 | state it in the column description. This is where Cube would help most, but it still cannot stop raw SQL |

The cost side is unchanged either way: a Cube schema would have to re-describe 381 queryable
features, while `semantic_layer.yaml` is **generated** from
`backend/app/semantic/feature_spec.py`. A hand-written Cube schema drifts from the source the
first time anyone adds a feature.

#### 3. Centralized access control — NO (and Cube is not the cheapest fix)

The risk is real, but it comes from Metabase connecting as a superuser: it would then see
`raw.customers` (`birth_date`, `gender`, `residence_province`), `silver`, `dbt_work`, and
`agent.query_log` — bypassing every guard the Agent must obey.

The fix reuses the boundary migration 0015 already established:

```sql
CREATE ROLE metabase_reader LOGIN PASSWORD '<choose separately>' IN ROLE feature_agent_reader;
```

`feature_agent_reader` has been verified: it sees exactly `feature.*` (3 tables) and
`metadata.*` (7 tables), nothing else. One line of SQL, versus a service to run, upgrade, and
re-implement authentication in.

#### 4. Caching / pre-aggregation — NO

Latency, mean of 5 runs after discarding a cold first run:

| Query | |
|---|---:|
| Single-number KPI (total spend, l1m) | 11.2 ms |
| Time series across 6 snapshots | 14.9 ms |
| Top 50 cross-BU customers | 8.8 ms |
| Full scan grouped by `dominant_business_unit` | 12.5 ms |

Cube's pre-aggregation exists for queries taking **seconds to minutes**, not 12 ms.

More importantly, `feature.*` **is already the pre-aggregate**. That is the definition of a
feature store — numbers precomputed per `customer_id + snapshot_date`. Putting Cube on top
would be pre-aggregating a pre-aggregate.

### Consequences

- `semantic_layer.yaml` remains the **only** semantic layer, still generated from
  `feature_spec.py`. There is no second copy to keep in sync by hand.
- The acceptance criterion "with Cube switched off, everything still runs" holds trivially,
  because there is nothing to switch off.

#### Three follow-ups caused by Metabase connecting directly — independent of Cube

In priority order. All three are cheaper than Cube, and **none is made redundant by Cube**.

**1. Read-only role for Metabase (security — do this first).** Without it, a superuser
connection exposes `raw.customers` (`birth_date`, `gender`, `residence_province`), `silver`,
`dbt_work`, and `agent.query_log`. See the SQL under condition 3.

**2. A view exposing only the latest snapshot.** Removes the 6.3× double-counting trap
structurally, instead of relying on everyone remembering the filter. Anyone who genuinely needs
a time series still queries the base table — deliberately, rather than by accident.

**3. Push the Vietnamese descriptions into `COMMENT ON COLUMN`.** 381 descriptions already
exist in `semantic_layer.yaml` and are simply unused for this purpose. DDL on `feature.*` is
owned by Alembic, so this needs a migration, followed by re-snapshotting
`backend/db/gold_contract.json` (`contract_check --snapshot`).

This has the highest value-to-effort ratio of the three: it turns an unreadable 190-column table
into a browsable one, reusing something already generated.

### When to reopen

Reopen when **any** of the following becomes true — not when someone "feels like there should be
a semantic layer":

| Signal | Concrete threshold |
|---|---|
| Dashboards redefining the same metric | ≥ 3 dashboards, with at least one observed number mismatch |
| A third consumer reading gold directly | some other application reading `feature.*` outside `/ask` and outside Metabase |
| BI queries genuinely slow | p95 > 2 seconds on gold |
| Row- or column-level permissions needed | e.g. each region may only see its own customers |

The first three will almost certainly arrive together with a real warehouse. Measure again at
that point — do not guess.

If reopened: the Cube schema must be **generated** from `feature_spec.py`, the same way
`generate_semantic_layer.py` works today, never hand-written. And the Agent still does not go
through Cube — Vietnamese retrieval over a 400-column table is a different problem from the one
Cube solves.
