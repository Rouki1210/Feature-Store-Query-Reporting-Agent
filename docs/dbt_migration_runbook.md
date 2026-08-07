# Runbook — chuyển tầng transform sang dbt

Kế hoạch đầy đủ: `C:\Users\admin\.claude\plans\h-y-l-n-k-ho-ch-inherited-diffie.md`.
File này là checklist thi hành + những cái bẫy đã gặp thật.

Mọi lệnh chạy từ `backend/` bằng `./.venv/Scripts/python.exe`.

---

## Đã xong

### Phase 0 — Freeze + baseline ✅

- Database dựng lại sạch: `docker compose down -v && docker compose up -d db`, alembic `0015`.
- Seed legacy: 600 khách, 15.211 trip, 4.076 đơn, 12.400 status history, 536 handover,
  3× 3.600 dòng feature. Golden set 100 case.
- `pytest` **183 passed**.
- Baseline eval lưu ở `docs/eval/baseline_predbt_offline.txt`. Con số phải giữ nguyên sau port:

  | Chỉ số | Baseline |
  |---|---|
  | `gold_sql_ok` | **72/72 (100%)** ← nhạy nhất với thay đổi dữ liệu |
  | `retrieval_hit@5` | 59/72 (81%), recall 86% |
  | `refusal_accuracy` | 23/28 (82%) |
  | MRR | 0.796 |
  | `gold_sql_execution_rate` | 100% |

- `parity_check.py` + `contract_check.py` đã viết **và đã test ngược** (cố tình phá 1 giá trị
  + 1 comment → cả hai bắt được, exit code 1; khôi phục → exit 0).
- Baseline đã chụp: schema `parity` (dữ liệu) + `backend/db/gold_contract.json` (cấu trúc).

### Phase 1a — Migration 0015 ✅

`backend/migrations/versions/0015_dbt_transform_ownership.py` đã áp. Kiểm chứng least-privilege
**14/14 PASS**:

```
DML feature.* / đọc raw / toàn quyền silver+dbt_work   → OK
DROP TABLE | ALTER TABLE | CREATE TABLE | DROP CONSTRAINT | COMMENT trên feature.*
                                                       → InsufficientPrivilege
metadata.* và agent.*                                  → InsufficientPrivilege
```

ACL thực tế: `dbt_transformer=arwd` trên 3 bảng gold, `U` (không có `C`) trên schema `feature`.
Đây là lớp bảo vệ thật, không phải `full_refresh=false` trong config model.

---

## Bẫy đã gặp — đọc trước khi làm tiếp

1. **`DATABASE_URL` là thứ phải kiểm tra ĐẦU TIÊN khi số liệu bỗng lạ.** Đã dính hai lần:
   một lần trỏ nhầm sang Postgres native ở `localhost:5432` (alembic 0013, golden set thiếu
   14 case) thay vì compose ở `5433`; một lần chuyển sang server từ xa.
   Lưu ý `docker-compose.yml` **ghi đè** `DATABASE_URL` cho service `agent` thành `db:5432`,
   nên sửa `backend/.env` KHÔNG tác động tới agent chạy trong container.

2. **`SNAPSHOT_DATE` phải ghim.** Đã ghim `2026-08-01` trong `backend/.env`. Bỏ trống ⇒
   `date.today()` ⇒ seed lại hôm sau ra bộ snapshot khác ⇒ parity fail giả.
   Generator giờ đọc qua `get_settings().snapshot_date`, **không** `os.getenv` — biến trong
   `.env` không được export ra môi trường nên `os.getenv` sẽ âm thầm rơi về `date.today()`.
   Cùng cái bẫy này áp cho mọi biến mới bạn thêm vào `.env`.

3. **Windows console.** `run_eval` in ký tự `✔`, console cp1258 sẽ crash. Luôn chạy:
   `PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.run_eval ...`

4. **SQLAlchemy `text()`.** `:param::cast` KHÔNG được nhận là bind param (regex loại tên đi
   liền `::`). Viết `CAST(:param AS text[])` thay vì `:param::text[]`.

5. **`db/schema/sprint1_..._postgresql.sql` là file SỐNG** — migration `0001` đọc và áp nó.
   Đừng xoá. Nó chỉ là baseline Sprint 1, không phải schema hiện tại; thêm header cảnh báo thì được.

6. **Sau mỗi lần Alembic đổi DDL có chủ đích**, phải chạy lại `contract_check --snapshot` rồi
   commit `gold_contract.json`. Nếu không, mọi lần `--verify` sau đó sẽ fail.

7. **Đổi `CUSTOMER_COUNT` (hay bất kỳ hằng số nào của generator) là làm hỏng baseline.**
   Đã xảy ra: 600 → 1000 giữa chừng, `parity.*` còn 3600 dòng trong khi `feature.*` thành
   6000 → `parity_check --verify` báo hàng nghìn dòng lệch vô nghĩa. Đổi hằng số ⇒ **phải**
   chạy lại `parity_check --snapshot` và `run_eval` ngay sau đó.
   Chi tiết đáng nhớ: GSM lệch đúng bằng số dòng mới thêm (600 khách cũ giống hệt bản trước),
   nhưng VinFast lệch nhiều hơn thế — trip GSM bốc RNG *trong* vòng lặp khách nên không đổi,
   còn handover bốc *sau* cả vòng lặp nên thêm khách làm lệch toàn bộ chuỗi phía sau.
   Số eval (retrieval/refusal/gold_sql) thì **không** đổi theo khối lượng dữ liệu.

8. **dbt đọc file project bằng encoding của LOCALE, không phải UTF-8.** Trên máy này locale là
   cp1258, nên một dấu tiếng Việt trong `dbt_project.yml` hay trong comment của model là đủ để
   dbt chết `UnicodeDecodeError`. `PYTHONIOENCODING` không cứu được — nó chỉ đổi stdout, không
   đổi `open()`. `run_dbt.py` xử lý sẵn: nó tự `os.execv` lại chính mình với `-X utf8` khi thấy
   `sys.flags.utf8_mode == 0`. **Luôn gọi dbt qua `run_dbt.py`**, đừng gọi `dbt` trực tiếp.
   Hệ quả tiện: không cần tiền tố `PYTHONIOENCODING=utf-8` cho lệnh dbt nữa.

---

9. **`postgresql://` rơi về psycopg2, không phải psycopg3.** URL phải là
   `postgresql+psycopg://`. Bản trần chạy được ở máy dev chỉ vì `dbt-postgres` kéo theo
   `psycopg2-binary`; `requirements.txt` khai `psycopg[binary]>=3.2`, nên image Docker của
   agent (chỉ cài `requirements.txt`) sẽ không kết nối được. Kiểm nhanh:
   `python -c "from app.db import get_engine; e=get_engine(); print(e.dialect.driver)"`
   → phải in `psycopg`, không phải `psycopg2`.

10. **`gold_contract.json` gắn với PHIÊN BẢN PostgreSQL, không chỉ với schema.** Chuyển từ
    PG 16 sang PG 18 báo lệch mà schema không hề đổi: PG 17+ đưa `NOT NULL` vào
    `pg_constraint`, và thêm quyền `MAINTAIN` nên ACL chủ sở hữu là `arwdDxtm` thay vì
    `arwdDxt`. Nhận biết: `columns`, `indexes`, comment vẫn khớp, và quyền của
    `dbt_transformer` vẫn đúng `arwd` → artefact phiên bản, chụp lại. Lệch ở `columns`,
    `indexes`, comment, hay ở quyền `dbt_transformer` thì là thật.

---

## Môi trường hiện tại

Từ 2026-08-07, **server từ xa thay hẳn Postgres local**. Local (`localhost:5433`) không
còn được dùng.

| | |
|---|---|
| Host | `103.173.154.65:5435`, database `warehouse` |
| PostgreSQL | **18.4** (local trước đây là 16) |
| Alembic | `0015` (head) |
| Dữ liệu | 1000 khách × 6 snapshot, `SNAPSHOT_DATE=2026-08-01`, seed `20260723` |
| Golden set | 100 case |

Đã nghiệm thu đầy đủ trên môi trường này:

```
alembic upgrade head            0014 -> 0015
generate_mock_data              1000 khách, 25.505 trip, 6.781 đơn (47 giây)
seed_golden_set                 100 case
run_dbt build                   PASS=85  ERROR=0   (19 giây)
parity --source dbt_work        PARITY OK — đúng 2 ô được tha, y hệt local
contract_check --verify         CONTRACT OK (đã chụp lại theo PG 18)
least-privilege dbt_transformer 7/7 PASS — DROP/ALTER/CREATE trên feature.* đều bị chặn
pytest                          183 passed
run_eval --offline              gold_sql_ok 72/72, retrieval 59/72, refusal 23/28
```

Số eval và cặp ô tỷ lệ được tha **trùng khít bản local** — bằng chứng generator tái tạo
được cùng dữ liệu trên máy khác và phiên bản Postgres khác.

Baseline `parity.*` và `gold_contract.json` đã chụp lại theo server này. Baseline cũ của
local không còn dùng được.

## Việc tiếp theo

### ☐ Bước 1 — Đổ dữ liệu vào `raw.feature_snapshot` (làm ngay, ~5 dòng)

Bảng đã tạo nhưng **đang rỗng**. dbt đọc danh sách ngày snapshot từ đây; rỗng thì mọi model silver
trả 0 dòng.

Trong `backend/scripts/generate_mock_data.py`, hàm `seed()`: sau khi insert `date_dim`, thêm
insert `raw.feature_snapshot` từ hằng `SNAPSHOTS`. Nhớ `DELETE` trước để giữ tính idempotent,
và đặt **sau** `date_dim` vì có FK `snapshot_date → raw.date_dim(date_id)`.

Nghiệm thu:
```bash
./.venv/Scripts/python.exe -m scripts.generate_mock_data
docker compose -f ../docker-compose.yml exec -T db psql -U postgres -d feature_store \
  -c "select count(*), min(snapshot_date), max(snapshot_date) from raw.feature_snapshot;"
# kỳ vọng: 6 | 2026-03-04 | 2026-08-01
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.parity_check --verify   # phải OK
```

### ✅ Bước 2 + 3 — Wrapper và khung dbt project (XONG)

`dbt-core 1.12.0` + `dbt-postgres 1.11.0`, khai báo ở `backend/requirements-pipeline.txt`
(tách khỏi `requirements.txt`: image agent không cần dbt, mà dbt kéo theo ~30 package).
Nó **hạ `protobuf` 7.35 → 6.33**; đã chạy `pytest` xác nhận 183 passed, không ảnh hưởng gì.

Đã có:

| File | Vai trò |
|---|---|
| `backend/scripts/run_dbt.py` | suy DBT_* từ `DATABASE_URL`, ép user `dbt_transformer`, tự bật `-X utf8` |
| `dbt/dbt_project.yml` | `silver/` → view, `int/` → table trong `dbt_work`, tắt telemetry |
| `dbt/profiles.yml` | postgres, đọc env do wrapper nạp |
| `dbt/macros/generate_schema_name.sql` | trả schema literal, không prefix `dbt_work_` |

`run_dbt.py` cố tình **không** lấy `username` từ `DATABASE_URL` — app kết nối bằng superuser,
dbt thì không được phép. Đây là chỗ least-privilege của migration 0015 thực sự có hiệu lực.

Đã nghiệm thu:
```
run_dbt debug                    -> All checks passed, dbt_transformer@localhost:5433
run_dbt run --select <model tạm> -> view đáp vào `silver`, KHÔNG phải `dbt_work_silver`
                                    (chứng minh macro generate_schema_name đúng)
model tạm đọc raw.feature_snapshot -> 6 dòng (chứng minh bước 1 đã cấp dữ liệu cho dbt)
```
Model tạm đã xoá. `dbt/target/`, `dbt/logs/` đã vào `.gitignore`.

Còn thiếu: `dbt/models/sources.yml` khai báo đủ 7 bảng nguồn — làm cùng bước 4.

### ✅ Bước 4 — Tầng silver (XONG)

**5** model chứ không phải 4 — lý do ở dưới.

| Model | Grain | Nội dung |
|---|---|---|
| `silver_customer_snapshot` | (customer_id, snapshot_date) | spine, mọi candidate left-join từ đây |
| `silver_gsm_trip` | (trip_id) | trip chuẩn hoá + `status_group`, `is_weekday`, `is_daytime` |
| `silver_vinfast_order_state` | (order_id, snapshot_date) | trạng thái đơn as-of |
| `silver_vehicle_purchase` | (order_id, snapshot_date) | tư cách NGƯỜI MUA xe |
| `silver_vehicle_ownership` | (handover_id, snapshot_date) | `is_handed_over` / `is_owned` / `is_pending` |

**Vì sao phải tách `silver_vehicle_purchase` khỏi `silver_vinfast_order_state`** — bug thật,
tìm ra bằng cách đối chiếu với bản Python: `order_state` lọc as-of theo cả `updated_at`, mà
`generate_raw()` gán `updated_at = handed_over_at` cho đơn xe đã giao. Đem bộ lọc đó áp cho
tư cách người mua thì đơn `completed` tháng 3 giao tháng 5 không được tính là mua ở snapshot
tháng 4 — làm "mua" phụ thuộc vào "nhận", đúng thứ cả dự án được xây để phân biệt.
Đo được: **257 đơn dính, lệch 59 dòng `is_vehicle_buyer`**.
`tests/assert_purchase_independent_of_delivery.sql` khoá chặt hồi quy này.

**Múi giờ nằm sau biến `business_timezone`** (`dbt_project.yml`), không hardcode. Mặc định
`UTC` để khớp bản Python; warehouse thật đổi **một dòng ở đó**, không sửa 15 chỗ rải rác.
Đã kiểm bằng cách chạy với `Asia/Ho_Chi_Minh`: **9.020/25.505 trip (35%) đổi `trip_date`,
2.528 lật `is_weekday`, 10.434 (41%) lật `is_daytime`**. Đây là số đo, không phải lo xa.

Test: 7 file trong `dbt/tests/` + generic test trong `models/silver/schema.yml` và
`models/sources.yml`. **Đã kiểm chứng ngược**: cố tình cho `is_owned` bỏ qua việc trả xe →
`assert_vehicle_ownership_rules` FAIL 76; bỏ điều kiện as-of → `assert_no_future_events_in_snapshot`
FAIL 585. Test đỏ được, không phải chỉ xanh cho đẹp.

Nghiệm thu đã đạt:
```
run_dbt build --select silver source:raw   -> PASS=57 ERROR=0
đối chiếu 6000 dòng feature.vinfast_transaction do Python sinh:
    is_vehicle_owner              0 lệch
    is_vehicle_buyer              0 lệch
    is_vehicle_handover_scheduled 0 lệch
contract_check --verify -> OK   (dbt không đụng DDL của feature.*)
pytest                  -> 183 passed
```

### ✅ Bước 5 — 3 model candidate (XONG)

`backend/scripts/generate_dbt_models.py` sinh 2 model wide từ `feature_spec.py`
(167 + 202 cột); `int_cross_bu_candidate.sql` viết tay (37 cột). Cả ba đặt `alias` trùng
tên bảng gold nên nằm ở `dbt_work.gsm_transaction`, `dbt_work.vinfast_transaction`,
`dbt_work.customer_cross_bu_feature` — `parity_check --source dbt_work` so thẳng được.

**Phát hiện quan trọng:** `feature_spec` có 406 feature nhưng vật lý có 464 cột. 49 cột
lõi (20 GSM + 29 VinFast) **chưa bao giờ được pipeline ghi vào** — chúng rơi vào DEFAULT
lúc INSERT. Candidate cũng bỏ trống y hệt. `parity_check` chỉ tha cột vắng mặt khi kiểm
chứng được baseline của nó đúng bằng DEFAULT.

**Hai sửa đổi ở `parity_check` — siết chứ không nới:**

1. So `nguồn::<kiểu cột đích>` thay vì so thô. `INSERT` ép kiểu theo cột đích, nên giá trị
   thực sự lưu là giá trị SAU khi ép. Không có bước này thì 28 cột `processing_time` báo
   lệch giả, chỉ vì bảng nháp giữ `2346.9999999833…` còn `numeric(20,4)` lưu `2347.0000`.
2. Khoanh lệch xuống **từng cột** thay vì chỉ in khoá dòng. Biết "12 dòng lệch" trên bảng
   234 cột là vô dụng; biết cột nào là đi thẳng tới nguyên nhân.

**Còn 2 ô lệch, đã chấp nhận có chủ đích** — xem `docs/eval/parity_buoc5_lech.md`.
Ngoại lệ được khai báo tường minh trong `parity_check` (cột tỷ lệ + lệch đúng 0.0001 +
trần 2 ô), in ra mỗi lần chạy, và đã kiểm ngược đủ ba đường phải đỏ.

Nghiệm thu đã đạt:
```
run_dbt build (toàn bộ)                    PASS=85  ERROR=0
parity_check --verify --source dbt_work    PARITY OK (2 ô được tha)
contract_check --verify                    CONTRACT OK
pytest                                     183 passed
```

<details><summary>Kế hoạch gốc của bước 5</summary>

### 3 model candidate trong `dbt_work` (`materialized: table`)

Khớp 1-1 với 3 bảng gold. Hai bảng wide (190 + 234 cột) **không viết tay**: thêm
`backend/scripts/generate_dbt_models.py` sinh `.sql` tĩnh từ `app/semantic/feature_spec.py`
(`TABLES`, `WINDOW_DAYS`, `RATIO_WINDOWS`, `all_features()`), theo đúng khuôn
`generate_semantic_layer.py`, header "KHÔNG sửa tay". SQL tĩnh dễ diff/debug hơn Jinja loop nhiều.
`int_cross_bu_candidate` (40 cột) viết tay theo ADR 0001.

Test trên candidate (đây mới là chỗ bắt lỗi — nếu đặt test trên gold thì CHECK constraint
đã chặn `INSERT` trước khi test kịp chạy):
```
unique(customer_id, snapshot_date) · relationships → raw.customers
snapshot_date ∈ raw.feature_snapshot · feature_build_at not null
count/amount không âm · accepted_values dominant_business_unit_*
l1m <= l3m <= l6m <= l12m <= all
is_cross_bu_active_{w} = is_active_gsm_{w} AND is_active_vinfast_{w}, MỌI window
VinFast spend: NULL = chưa từng có đơn tại snapshot; 0 = có lịch sử nhưng không chi trong window
ownership không bao giờ suy ra từ order status
```
`assert_buyer_not_owner_exists` gắn tag `dev_only` — nó bảo vệ mock dataset khỏi rỗng nghĩa,
không phải bảo vệ pipeline. Dữ liệu thật có thể hợp lệ mà không có cohort này.

</details>

### ✅ Bước 6 — `publish_gold.py` (XONG)

`backend/scripts/publish_gold.py`. Chạy bằng role `dbt_transformer` (suy từ
`DATABASE_URL`, dùng lại `build_env()` của `run_dbt.py`) — không phải superuser của app,
nên ranh giới least-privilege thực sự có hiệu lực. Cả ba bảng trong **một** transaction.

Ba chốt chặn TRƯỚC khi ghi, vì `DELETE` rồi mới `INSERT`:

| Chặn | Lý do |
|---|---|
| nguồn không tồn tại | chưa chạy `run_dbt build` |
| nguồn **rỗng** | một lần dbt lỗi để lại bảng rỗng sẽ xoá sạch gold mà transaction vẫn commit êm |
| nguồn có cột gold không có | cột mới phải đi qua migration Alembic trước |

Cột chỉ có ở gold thì `INSERT` bỏ qua để DB tự điền DEFAULT: 21 / 30 / 1 cột
(49 cột lõi chưa bao giờ được ghi + `feature_build_at`).

Đã nghiệm thu đủ 5 kịch bản:

```
1. chạy sạch          publish -> parity OK (feature.* giờ do dbt sinh)
2. idempotency        publish 3 lần liên tiếp -> parity OK
3. lại cả pipeline    run_dbt build -> publish -> parity OK
4. nguồn rỗng         TỪ CHỐI, exit=1, gold còn nguyên 6000 dòng
5. dữ liệu biên       627 sự kiện về trễ (tối đa 40 ngày);
                      16 bản ghi đảo bàn giao; 76 dòng mất quyền chủ;
                      9 dòng đảo SAU snapshot nên VẪN là chủ (ca của ADR 0002);
                      787 dòng buyer=true owner=false
```

Kết quả cuối, agent chạy trên gold do dbt sinh:

```
parity_check --verify      PARITY OK (2 ô tỷ lệ được tha)
contract_check --verify    CONTRACT OK — publish không đụng DDL
pytest                     183 passed
run_eval --offline         gold_sql_ok 72/72, retrieval 59/72, refusal 23/28  = baseline
```

18.000 dòng × 3 bảng publish trong **1,8 giây** qua kết nối từ xa — `INSERT ... SELECT`
chạy hoàn toàn phía server, không có dữ liệu nào đi qua đường truyền.

<details><summary>Kế hoạch gốc của bước 6</summary>

### `publish_gold.py` + đạt parity

`backend/scripts/publish_gold.py` (~30 dòng), chạy bằng user `dbt_transformer`:
`BEGIN; DELETE FROM feature.x; INSERT INTO feature.x SELECT ... FROM dbt_work.x; COMMIT;`
cho cả 3 bảng trong **một** transaction. Có `--dry-run` chỉ diff không ghi.

Port theo phần, mỗi phần đạt parity rồi mới sang phần sau:
**3A GSM → 3B VinFast order → 3C VinFast PIT/ownership → 3D Cross-BU**

So candidate với baseline mà chưa cần publish:
```bash
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.parity_check --verify --source dbt_work
```
(cờ `--source` đã có sẵn cho đúng việc này)

Parity phải đạt trên **4 kịch bản**, không chỉ một lần chạy sạch:
chạy sạch · chạy lặp lại (idempotency) · có late-arriving event · có reversed handover.

Nghiệm thu Phase 3:
```
parity_check --verify   = 0 dòng lệch
contract_check --verify = 0 (chứng minh publish không đụng DDL)
run_dbt build           = xanh
pytest                  = 183 passed
run_eval --offline      = gold_sql_ok 72/72, retrieval 59/72, refusal 23/28
```

</details>

### ✅ Bước 7 — Cutover

Đã xoá khỏi `generate_mock_data.py` **414 dòng**: `build_features`, `build_cross_bu`,
`_within`, `_ratio`, `_vehicle_pit`, `_cutoff`, `data_quality_errors`, `cross_bu_errors`.
`RNG = random.Random(20260723)` giữ nguyên — seed vẫn sinh đúng 1000 khách / 25.505 trip
/ 6.781 đơn như bộ đã dựng nên baseline `parity`.

`seed()` vẫn XOÁ `feature.*` dù không còn ghi vào đó: gold suy ra từ raw, thay raw mà giữ
gold là để agent trả lời bằng số của bộ dữ liệu cũ. Rỗng là hỏng ồn ào, stale là sai trong
im lặng. `main()` in ra hai lệnh nạp lại.

**Không thêm cờ `--legacy-transform`.** Kế hoạch ban đầu định dùng nó làm đường rollback,
nhưng bước 3-6 đã chạy song song xong và parity đã chốt; giữ 414 dòng sau một cờ nghĩa là
giữ một bản transform thứ hai không ai chạy, không ai test, và sẽ trôi khỏi bản dbt.
Rollback = `git revert` commit cutover, cùng hiệu quả và không để lại nợ.

#### Phần khó không nằm ở việc xoá: 31 test Python sống nhờ đúng đoạn code đó

`test_point_in_time.py` (14), `test_cross_bu_feature.py` phần 1-5b + 7 (17),
`test_agent_pipeline.py` (2). Đây là guard ngữ nghĩa của Sprint 2 — xoá thẳng là **làm yếu
guard để test khỏi đỏ**, đúng thứ CLAUDE.md cấm.

Test singular sẵn có (`assert_vehicle_ownership_rules`, `assert_candidate_cross_bu_rules`…)
**không thay thế được**: chúng chạy trên mock thật nên chỉ bắt được ca nào TÌNH CỜ có trong
dữ liệu. Ba ca dưới đây gần như không bao giờ xuất hiện tự nhiên — và một ca thì không bao
giờ, vì model còn không đọc tới cột đó:

| Ca | Vì sao singular test không thấy |
|---|---|
| lọc theo `recorded_at` thay vì event time | không model nào SELECT `recorded_at` — không có gì để so |
| chi tiêu hai bên bằng nhau ⇒ `TIE` | dữ liệu thật gần như không có tie khác 0 |
| khách chưa từng có dữ liệu ⇒ NULL, khác 0 | phải dựng khách thiếu hẳn một phía |
| khách chỉ có VinFast, không có dòng GSM | mock sinh đủ dòng GSM cho mọi khách |

Nên chuyển sang **dbt unit test** (`given`/`expect`, dữ liệu dựng sẵn, không đọc bảng thật) —
đúng 1-1 với "thuần hàm, không chạm DB" của bản Python:

```
dbt/models/silver/unit_tests.yml
    quyen_so_huu_xe_theo_moc_thoi_gian            4 bản ghi bàn giao × 2 snapshot = 8 dòng
    tu_cach_nguoi_mua_khong_phu_thuoc_ngay_giao   mua không phụ thuộc ngày giao
dbt/models/int/unit_tests.yml
    cross_bu_null_khac_zero_va_dominant           5 khách: chỉ-GSM · chỉ-VF · TIE · 0 · NULL
dbt/tests/assert_mock_dataset_covers_edge_cases.sql   (tag dev_only)
    bản port phần ĐỘ PHỦ của data_quality_errors(): bộ mock có đủ ca biên không
dbt/tests/assert_no_future_events_in_snapshot.sql
    + nhánh days_since_* < 0  ⇒ sự kiện nằm sau snapshot
```

`assert_mock_dataset_covers_edge_cases` mang tag `dev_only` vì nó gắn với BỘ MOCK chứ không
phải pipeline: warehouse thật hoàn toàn có thể hợp lệ mà thiếu một cohort.
Chạy trên dữ liệu thật thì `dbt build --exclude tag:dev_only`.

Python giữ lại đúng phần dbt không thấy được — **ý định của bộ sinh**:
`test_delivered_order_status_agrees_with_handover` và
`test_raw_events_cover_the_edge_cases_dbt_tests_rely_on` (đỏ ngay tại nguồn nếu
generate_raw ngừng sinh handover đảo / sự kiện về trễ, thay vì đỏ sau cả một lần build).

#### Bẫy gặp phải

**`numeric` của Postgres giữ scale RIÊNG cho từng giá trị.** `sum()` ra `600.00`,
`round(x, 4)` ra `0.0000`, literal `1.0` ra `1.0`. YAML parse `600.00` thành float
`600.0` và unit test đỏ vì lệch định dạng. Ghim bằng **chuỗi**: `"600.00"`.

**Partial parse che mất sửa đổi trong file YAML unit test.** Sửa `expect` rồi chạy lại vẫn
thấy giá trị cũ trong diff. Dùng `--no-partial-parse` khi đang chỉnh unit test.

#### Nghiệm thu (đã chạy trên PG 18.4 từ xa)

Mọi guard mới đều đã bị **tiêm bug để kiểm ngược**, không guard nào chỉ "xanh":

| Bug tiêm vào | Guard bắt |
|---|---|
| `is_handed_over` lọc theo `recorded_at` | unit test silver — FAIL |
| `is_owned` dùng `handover_status <> 'reversed'` | unit test silver — FAIL |
| bỏ nhánh `TIE`, đổi `>` thành `>=` | unit test cross-BU — FAIL |
| `coalesce(vinfast_spend, 0)` (NULL thành 0) | unit test cross-BU — FAIL |
| giả vờ không có chuyến bị huỷ | assert_mock_dataset — FAIL |

```
generate_mock_data      1000 khách · 25.505 trip · 6.781 đơn · feature.* để RỖNG
run_dbt build           PASS=89  (5 view, 3 table, 78 data test, 3 unit test)
publish_gold            0 -> 6000 dòng mỗi bảng
parity_check --verify   PARITY OK   (2 ô tỷ lệ được tha)
contract_check --verify CONTRACT OK
pytest                  148 passed
run_eval --offline      gold_sql_ok 72/72 · retrieval 59/72 · refusal 23/28  = baseline
```

`0 -> 6000` là chỗ đáng nhìn: seed đã thực sự dọn sạch `feature.*` và toàn bộ 18.000 dòng
gold hiện tại đến từ dbt, không còn dòng nào sót lại của đường Python.

### ◑ Bước 8 — Dagster: khung xong, phần phụ thuộc nguồn dữ liệu để lại

`backend/orchestration/definitions.py` — 3 asset, 2 job:

```
raw_events  ->  dbt_models  ->  gold_tables      dev_seed_job   bấm tay
                dbt_models  ->  gold_tables      nightly_job    sẽ hẹn giờ
```

`raw_events` xoá sạch `raw.*` + `feature.*` rồi sinh lại, nên **không bao giờ** được nằm
trong job có lịch. Khi cắm dữ liệu thật, nửa trái bị thay bằng nguồn ingest, `nightly_job`
dùng lại nguyên vẹn — đó là toàn bộ lý do tách đôi.

Chạy:

```powershell
cd backend
$env:DAGSTER_HOME = "$PWD\.dagster"     # không đặt thì mất lịch sử chạy
.\.venv\Scripts\dagster.exe dev -m orchestration.definitions
.\.venv\Scripts\dagster.exe job execute -m orchestration.definitions -j nightly_job
```

`seed_metadata` không cần asset riêng: `generate_mock_data.seed()` đã gọi nó. Khi tách khỏi
mock generator thì phải tách ra, và **không** cho chạy hàng đêm — nó đè synonym chỉnh tay.

#### Ba bẫy đã cắn thật

**Tiến trình con của Dagster không import được `scripts.*`.** Gọi thẳng hàm asset trong tiến
trình cha thì chạy tốt; qua executor thì `ModuleNotFoundError`, kể cả sau khi chèn `backend/`
vào `sys.path` ở đầu file định nghĩa. Không gọt sys.path cho vừa — cả ba asset đi bằng
`subprocess` với `cwd=backend/`. Đổi lại còn được hai thứ: `.env` chắc chắn đọc đúng dù chạy
Dagster từ đâu, và `SystemExit` của `publish_gold` thành exit code, tức một lần chạy đỏ gọn.

**`from __future__ import annotations` làm Dagster không nhận ra `AssetExecutionContext`.**
Nó biến annotation thành chuỗi, mà Dagster kiểm kiểu tham số `context` ngay lúc định nghĩa
asset → `DagsterInvalidDefinitionError`. File này cố ý không có dòng đó.

**UTF-8.** `run_dbt.py` chỉ tự re-exec với `-X utf8` khi chạy như `__main__`. Import rồi gọi
`main()` là dbt chết `UnicodeDecodeError` ở comment tiếng Việt. `_chay_script` luôn thêm
`-X utf8`.

#### Nghiệm thu

| Thử | Kết quả |
|---|---|
| `nightly_job` có `raw_events` không | resolve ra `['dbt_models','gold_tables']` — **không có** |
| dbt test đỏ (tiêm 1 test luôn fail) | `dbt_models` FAIL, `gold_tables` **không chạy**, PARITY OK |
| `dev_seed_job` chạy trọn | 3/3 STEP_SUCCESS, 36 giây |
| Tắt Dagster, gõ 3 lệnh tay | vẫn chạy y hệt |
| webserver | HTTP 200, thấy 2 job + 3 asset |
| sau khi chạy | parity OK · contract OK · pytest 148 passed |

#### Cố ý CHƯA làm — vì còn phụ thuộc nguồn dữ liệu

- **Lịch chạy.** `SNAPSHOT_DATE` đang ghim `2026-08-01` nên chạy đêm ra kết quả y hệt. Trước
  khi bật lịch phải trả lời: **ai INSERT ngày snapshot mới vào `raw.feature_snapshot`?** Hiện
  6 ngày đó do Python sinh như hằng số; với dữ liệu thật thì không ai làm việc này.
  `execution_timezone` phải khớp `business_timezone` của dbt (đang UTC).
- **Asset check "raw đã tươi chưa".** Phải biết dữ liệu về bằng đường nào mới viết đúng.
  Không có nó, một đêm nguồn đổ dở sẽ khiến nightly tính ra số thiếu rồi **ghi đè** gold.
- **Retry + khoá đồng thời.** Pool limit 1 phải bao **cả** `dbt_models` lẫn `gold_tables`:
  `dbt build` DROP bảng `dbt_work` mà lần chạy kia đang publish. Một người dùng thì chưa xảy ra.
- **`run_eval` trong `dev_seed_job`.** Nếu thêm, phải ghim `--offline`, không thì mỗi lần
  seed là một lần gọi LLM tốn tiền.
- **Service `dagster` trong docker-compose (profile `orchestration`).** Vướng nợ có sẵn:
  compose ép `DATABASE_URL` về `db:5432` trong khi `.env` trỏ server từ xa.

### ✅ Bước 9 — Cube: **không dùng**

Cổng đã đặt từ đầu là "chỉ triển khai khi chứng minh được ít nhất MỘT trong bốn điều kiện".
Đo ngày 2026-08-07 trên hệ thống thật: **0/4**.

| Điều kiện | Đo được |
|---|---|
| Nhiều dashboard dùng chung metric | không có dashboard nào |
| Nhất quán ngữ nghĩa giữa nhiều consumer | **CÓ 2 consumer** (Metabase nối thẳng `feature.*`) — nhưng ở đây metric là một **CỘT đã tính sẵn**, không phải công thức, nên hai bên không thể ra hai số khác nhau |
| Access control tập trung | rủi ro có thật nhưng chữa bằng **1 dòng SQL** (`metabase_reader IN ROLE feature_agent_reader`), không cần một service |
| Cache / pre-aggregation | 8,8–14,9 ms trên 18.000 dòng. Và `feature.*` **đã là** bản pre-aggregate |

Chi phí nếu làm: mô tả lại 381 feature queryable thành tầng ngữ nghĩa thứ hai, trong khi
`semantic_layer.yaml` được **sinh tự động** từ `feature_spec.py` — bản viết tay sẽ trôi ngay
lần đầu ai thêm feature.

Quyết định đầy đủ, kèm số đo và **ngưỡng cụ thể để mở lại**:
`decisions.md#0005`.

### ☐ Ba việc phát sinh vì Metabase nối thẳng — độc lập với Cube

Đo được ngày 2026-08-07, xếp theo ưu tiên. Chi tiết trong ADR 0005.

| # | Việc | Vì sao |
|---|---|---|
| 1 | `CREATE ROLE metabase_reader ... IN ROLE feature_agent_reader` | superuser thì Metabase thấy `raw.customers` (PII), `silver`, `dbt_work`, `agent.query_log` |
| 2 | View chỉ phơi snapshot mới nhất | quên `where snapshot_date` ⇒ **sai 6,3 lần** (2,12 tỷ thay vì 336 triệu) |
| 3 | Đẩy 381 mô tả tiếng Việt vào `COMMENT ON COLUMN` | hiện **7/464 cột** có mô tả; Metabase lấy mô tả từ đó |

Việc 3 cần migration Alembic (DDL của `feature.*` do Alembic sở hữu) và phải chạy lại
`contract_check --snapshot` sau đó.

### ✅ Bước 10 — Dọn dẹp

**[ADR 0004](decisions.md#0004)** — ranh giới Alembic/dbt, vì sao publish bằng
script chứ không dùng dbt incremental (ba lý do độc lập), vì sao hoãn Airbyte, chiến lược
incremental filter tương lai, và **4 câu còn mở phải trả lời trước khi cắm warehouse thật**.

**`docs/database_structure.md`** — bỏ câu "sinh tự động". Nó trỏ tới
`current_schema_postgresql.sql` và `generate_structure_doc.py`, **cả hai chưa bao giờ tồn
tại**; câu đó làm người đọc tưởng doc tự cập nhật, nên nó đứng ở `0014` trong khi head là
`0015`. Nay ghi rõ là viết tay, và trỏ sang thứ kiểm được bằng máy:
`gold_contract.json` + `contract_check --verify`. Đã cập nhật số: 7 schema, 24 bảng, 6 view.

**`backend/db/schema/sprint1_feature_store_schema_postgresql.sql`** — kế hoạch ghi "lệch 13
revision so với head → thêm cảnh báo hoặc **xoá**". **Không được xoá**: migration `0001` đọc
và thực thi file này nguyên văn, xoá là gãy `alembic upgrade head` từ đầu. Chênh 14 revision
là ĐÚNG — nó là trạng thái đông cứng của Sprint 1. Đã thêm header cấm cập nhật cho khớp head.

**CLAUDE.md §16** — dbt chuyển từ "out of scope" sang trong phạm vi, kèm ranh giới quyền.
Cube và Airbyte vẫn ngoài phạm vi, nay có ADR chống lưng. §14 ghi rõ generator chỉ sinh raw.

---

## Lệnh hay dùng

```bash
cd backend
docker compose -f ../docker-compose.yml up -d db
./.venv/Scripts/python.exe -m alembic upgrade head
./.venv/Scripts/python.exe -m scripts.generate_mock_data
./.venv/Scripts/python.exe -m scripts.seed_golden_set
./.venv/Scripts/python.exe -m pytest -q

PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.parity_check   --verify
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.parity_check   --verify --source dbt_work
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.contract_check --verify
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.run_eval --tag <nhãn> --split all --offline
```

## Quy tắc không thương lượng

- `run_eval` lệch dù **một** case → dừng và diff. **Không sửa golden set cho khớp.**
- `feature.*` giữ nguyên contract vật lý. Phải sửa `app/sql/*`, `app/semantic/retriever.py`,
  `data/semantic_layer.yaml`, `app/agent/*` hay `frontend/` ⇒ bản port đã sai, không phải
  contract cần đổi.
- Chỉ Alembic được đổi DDL của `feature.*`. `contract_check --verify` là bằng chứng.
