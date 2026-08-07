# Parity bước 5 — báo cáo lệch

So `dbt_work.*` (candidate do dbt sinh) với `parity.*` (bản chụp output của đường Python).
Dữ liệu: 1000 khách × 6 snapshot = 6000 dòng mỗi bảng.

## Tổng quan

| Bảng | Số cột so | Cột lệch | Ô lệch | Trạng thái |
|---|---:|---:|---:|---|
| `customer_cross_bu_feature` | 37 | 0 | 0 | ✅ khớp tuyệt đối |
| `vinfast_transaction` | 202 | 0 | 0 | ✅ khớp tuyệt đối |
| `gsm_transaction` | 167 | 5 | **27** | ⚠️ cần bạn quyết |

27 ô trên tổng ~2 triệu giá trị GSM = **0,0013%**. Toàn bộ nằm ở cột tỷ lệ, và mọi ô đều
lệch đúng **0,0001**.

---

## Loại A — báo động giả, đã xử lý xong

Lần chạy đầu báo VinFast lệch **28 cột** (`txn_*_processing_time_min/max_*`). Không phải bug.

`processing_minutes` được tính từ `updated_at - created_at`. Generator gán
`updated_at = time.max` (`23:59:59.999999`) cho một số đơn, nên khoảng cách thật là
`140819.999999` giây → `2346.9999999833…` phút. **Cả Python lẫn SQL đều tính ra đúng con
số này.**

Khác nhau chỉ vì nơi lưu:

| | giá trị |
|---|---|
| `feature.vinfast_transaction` khai `numeric(20,4)` → làm tròn lúc INSERT | `2347.0000` |
| bảng `dbt_work` không có ràng buộc kiểu → giữ nguyên | `2346.9999999833333333` |

`publish_gold.py` khi `INSERT INTO feature.* SELECT … FROM dbt_work.*` sẽ ép đúng kiểu đó,
nên chênh lệch **tự biến mất**. Phép so mới là sai, không phải model.

Đã sửa `parity_check`: so `nguồn::<kiểu của cột đích>` thay vì so thô — tức so đúng thứ mà
`INSERT` sẽ lưu. Sau khi sửa, VinFast còn **0 cột lệch**.

> Cũng đã siết `parity_check` ở chỗ khác: 49 cột chỉ-toàn-DEFAULT (20 GSM + 29 VinFast) mà
> pipeline chưa bao giờ ghi vào được bỏ qua **chỉ khi** kiểm chứng được baseline của chúng
> đúng bằng DEFAULT. Cột nào có dữ liệu thật mà candidate không sinh ra thì vẫn báo lệch.

---

## Loại B — lệch thật, cần bạn quyết

### 5 cột, 27 ô

Tất cả đều là cột tỷ lệ `{stem}_{cửa sổ A}_vs_{cửa sổ B}` = `A / B`.

#### `finished_txn_count_l3m_vs_l12m` — 21 ô

| customer_id | snapshot | phép chia | thương chính xác | dbt | python |
|---:|---|---|---|---|---|
| 56 | 2026-05-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 88 | 2026-06-02 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 126 | 2026-03-04 | 13/32 | 0.40625 | 0.4063 | 0.4062 |
| 168 | 2026-06-02 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 176 | 2026-05-03 | 5/32 | 0.15625 | 0.1563 | 0.1562 |
| 176 | 2026-08-01 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 178 | 2026-08-01 | 5/32 | 0.15625 | 0.1563 | 0.1562 |
| 230 | 2026-05-03 | 5/32 | 0.15625 | 0.1563 | 0.1562 |
| 309 | 2026-05-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 451 | 2026-05-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 716 | 2026-04-03 | 5/32 | 0.15625 | 0.1563 | 0.1562 |
| 716 | 2026-06-02 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 781 | 2026-06-02 | 13/32 | 0.40625 | 0.4063 | 0.4062 |
| 836 | 2026-03-04 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 872 | 2026-04-03 | 5/32 | 0.15625 | 0.1563 | 0.1562 |
| 872 | 2026-05-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 891 | 2026-08-01 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 911 | 2026-04-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 911 | 2026-06-02 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 959 | 2026-04-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |
| 991 | 2026-05-03 | 9/32 | 0.28125 | 0.2813 | 0.2812 |

#### `completed_trip_distance_km_sum_l1m_vs_l3m` — 3 ô

| customer_id | snapshot | phép chia | thương | dbt | python |
|---:|---|---|---|---|---|
| 77 | 2026-08-01 | 95.72/160.00 | 0.59825 | 0.5983 | 0.5982 |
| 156 | 2026-08-01 | 24.25/40.00 | 0.60625 | 0.6063 | 0.6062 |
| 548 | 2026-07-02 | 32.62/112.00 | 0.29125 | 0.2913 | 0.2912 |

#### 3 cột còn lại — mỗi cột 1 ô

| cột | customer_id | snapshot | phép chia | thương | dbt | python |
|---|---:|---|---|---|---|---|
| `completed_original_price_sum_l1m_vs_l3m` | 84 | 2026-04-03 | 418000/1600000 | 0.26125 | 0.2613 | 0.2612 |
| `completed_original_price_sum_l1m_vs_l6m` | 208 | 2026-05-03 | 573000/2400000 | 0.23875 | 0.2388 | 0.2387 |
| `completed_trip_distance_km_sum_l1m_vs_l6m` | 587 | 2026-03-04 | 115.46/400.00 | 0.28865 | 0.2887 | 0.2886 |

### Nguyên nhân — hai cơ chế chồng nhau

**27/27 ô đều có chữ số thứ 5 sau dấu phẩy đúng bằng 5**, tức mọi ô đều rơi đúng điểm hoà
của phép làm tròn 4 chữ số. Không có ô nào lệch vì lý do khác. Nhưng *vì sao* Python luôn
làm tròn xuống thì có hai nguyên nhân khác nhau:

**1. Python làm tròn về số chẵn, Postgres làm tròn ra xa số 0.**

`9/32 = 0.28125` biểu diễn CHÍNH XÁC trong nhị phân (32 = 2⁵). Đây là điểm hoà thật.
`round()` của Python dùng half-to-even → `0.2812` (2 là số chẵn).
`round(numeric, 4)` của Postgres dùng half-away-from-zero → `0.2813`.

**2. Python chia bằng float64, Postgres chia bằng decimal chính xác.**

Ô `0.23875` chứng minh cơ chế thứ nhất chưa đủ: nếu chỉ là half-to-even thì `0.2387|5` phải
lên `0.2388` (7 là số lẻ), nhưng Python cho `0.2387`. Lý do là số double gần nhất với
`0.23875` thực ra **nhỏ hơn** nó:

```
0.23875  -> double thực tế = 0.2387499999999999900079…   (DƯỚI điểm hoà)
0.60625  -> double thực tế = 0.6062499999999999555910…   (DƯỚI điểm hoà)
0.28125  -> double thực tế = 0.28125                     (ĐÚNG điểm hoà)
```

Postgres chia `numeric/numeric` nên không có sai số biểu diễn — nó thấy đúng `0.23875` và
làm tròn lên.

Nói gọn: **giá trị của dbt đúng hơn về mặt toán học; giá trị của Python là sản phẩm phụ của
float64 + quy tắc làm tròn của CPython.**

---

## Các lựa chọn

| | Cách làm | Được | Mất |
|---|---|---|---|
| **A** | Bắt chước Python trong SQL: chia bằng `float8` rồi `round()` một tham số (Postgres dùng half-to-even cho float) | Parity về 0 tuyệt đối, không phải sửa gì ngoài hàm `_ratio` trong generator | Cố tình chép lại một khiếm khuyết. Về sau ai đọc SQL sẽ không hiểu vì sao lại ép float |
| **B** | Chấp nhận 27 ô, ghi vào ADR như khác biệt đã hiểu rõ | Giữ SQL sạch và đúng toán học | Phá nguyên tắc "parity phải bằng 0". Lần sau có lệch thật sẽ khó phân biệt với 27 ô này |
| **C** | Sửa bản Python dùng `Decimal` + half-up, chụp lại baseline | Cả hai phía cùng đúng, parity về 0 | Đổi output của đường legacy — phải chạy lại `run_eval` để chứng minh không ảnh hưởng |

---

## Đã chốt: phương án A, chấp nhận 2 ô còn lại

`_ratio` trong `generate_dbt_models.py` chia bằng `float8` rồi `round()` một tham số
(Postgres dùng `rint()` = half-to-even, giống CPython). **25/27 ô hết lệch.**

Hai ô cuối không cứu được bằng bất kỳ SQL nào:

| | `cid=132` @ 2026-04-03 | `cid=208` @ 2026-05-03 |
|---|---|---|
| phép chia | 397000 / 800000 | 573000 / 2400000 |
| thương chính xác | `0.49625` (điểm hoà) | `0.23875` (điểm hoà) |
| double thực tế | `0.4962500000000000244…` **trên** hoà | `0.2387499999999999900…` **dưới** hoà |
| Python | `0.4963` (lên) | `0.2387` (xuống) |
| SQL cho ra | `0.4962` | `0.2388` |

Python quyết định theo **hướng sai số của float64**, nhưng phép nhân `q * 10000` làm mất
đúng cái sai số đó — cả hai đều snap về `4962.5` / `2387.5` rồi half-to-even cho ra kết quả
sai theo hai hướng ngược nhau. Không quy tắc làm tròn nào cứu được cả hai: một ô cần lên,
một ô cần xuống, mà trong hệ thập phân chúng giống hệt nhau. Chỉ bit của float64 phân biệt
được, và Postgres không cho truy cập giá trị nhị phân chính xác của `float8`
(`::numeric` trả biểu diễn ngắn nhất, mất luôn thông tin đó).

### Ngoại lệ được khai báo, không phải "nhớ mà trừ"

`parity_check.py` tha đúng loại chênh lệch này và chỉ loại này. Ba điều kiện, thiếu một là đỏ:

1. cột phải chứa `_vs_` (cột tỷ lệ);
2. chênh lệch phải đúng `0.0001` — một đơn vị ở chữ số thứ 4;
3. tổng số ô được tha không vượt `RATIO_MAX_CELLS = 2`.

Hai ô được **in ra mỗi lần chạy**, nên chúng không thể lặng lẽ tích tụ.

Đã kiểm ngược cả ba đường — mỗi đường phải làm cổng đỏ:

| Tiêm lỗi | Kết quả |
|---|---|
| lệch một cột **không** phải tỷ lệ | `exit=1` — "1 cột KHÔNG phải tỷ lệ" |
| ô tỷ lệ **thứ ba** lệch 0.0001 | `exit=1` — "3 ô tỷ lệ, vượt trần 2" |
| ô tỷ lệ lệch **0.05** | `exit=1` — "1 ô tỷ lệ lệch QUÁ 0.0001" |
| khôi phục | `exit=0` |

### Việc nên làm sau cutover

Khi đường Python bị xoá ở Phase 4, đổi `_ratio` sang phép chia decimal đúng chuẩn và bỏ
luôn ngoại lệ này. Lúc đó không còn gì để giữ parity với, nên `numeric` đúng toán học là
lựa chọn hiển nhiên. Nên là một commit riêng để đo được ảnh hưởng riêng.

---

## Cách tự kiểm chứng

```bash
cd backend
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m scripts.parity_check --verify --source dbt_work
```

Xem một ô bất kỳ trong bảng trên:

```sql
select a.finished_txn_count_l3m,
       a.finished_txn_count_l12m,
       a.finished_txn_count_l3m_vs_l12m as dbt,
       b.finished_txn_count_l3m_vs_l12m as python
  from dbt_work.gsm_transaction a
  join parity.gsm_transaction  b using (customer_id, snapshot_date)
 where customer_id = 56 and snapshot_date = '2026-05-03';
```
