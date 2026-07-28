# Join policy — Cross-BU

**Trạng thái: ĐỀ XUẤT — cần xác nhận cùng Task 2.0.**

## 1. Join hợp lệ duy nhất

```sql
FROM feature.gsm_transaction      g
JOIN feature.vinfast_transaction  v
  ON  g.customer_id   = v.customer_id
  AND g.snapshot_date = v.snapshot_date
```

Cả hai bảng có grain `customer_id + snapshot_date` ⇒ cardinality **1:1**. Bỏ vế
`snapshot_date` ⇒ 1:N với N = số snapshot (hiện **6**) ⇒ mọi tổng bị nhân 6 mà kết quả vẫn
trông hợp lý. Đây là lỗi nguy hiểm nhất của Sprint 2 và phải bị chặn ở tầng thực thi.

## 2. Thứ tự ưu tiên khi trả lời câu hỏi cross-BU

1. **`feature.customer_cross_bu_feature`** — nếu bảng tính sẵn phủ được câu hỏi thì dùng, KHÔNG join.
   Đây là đường mặc định (lý do: `docs/adr/0001-cross-bu-precomputed-table.md`).
2. Join theo `metadata.join_catalog` — chỉ khi cần cột không có trong bảng tính sẵn.
3. Không thuộc 1 và 2 ⇒ **từ chối**, trả lời "chưa hỗ trợ", không tự chế join.

## 3. Luật chặn (enforce ở `app/sql/guards.py`, không phải ở prompt)

| Trường hợp | Xử lý |
|---|---|
| Cặp bảng không có trong `join_catalog` (hoặc `is_active = FALSE`) | reject |
| Điều kiện join thiếu `snapshot_date` | reject |
| `JOIN` không có `ON` / `CROSS JOIN` (Cartesian) | reject |
| Số join > `sql_max_joins` (mặc định 2) hoặc CTE > `sql_max_ctes` (mặc định 2) | reject |
| Join chạm schema `raw` hoặc bảng ngoài allowlist | reject |
| Join key tự chế (cột không nằm trong `join_keys` của catalog) | reject |

Prompt được nhắc trước các luật này để giảm vòng repair, nhưng **prompt không phải là chốt chặn**.
Mọi reject ghi vào `agent.sql_validation_log`.

## 4. Join type và khách một-BU

Khi build `customer_cross_bu_feature`: **FULL OUTER JOIN**. INNER JOIN sẽ loại khách chỉ có một
BU — đúng nhóm cần đếm nhất trong câu hỏi overlap.

Khi agent join runtime (đường số 2), join type phải khớp đúng `metadata.join_catalog`.
Rule Sprint 2 hiện tại là **INNER JOIN**; thêm hoặc đổi loại join phải cập nhật catalog kèm test.

## 5. Null semantics sau join

| Tình huống | Giá trị | Ý nghĩa |
|---|---|---|
| Khách chưa từng có đơn VF | `vinfast_spend_l1m = NULL` | không có dữ liệu |
| Khách có đơn VF nhưng kỳ này không chi | `vinfast_spend_l1m = 0` | có dữ liệu, bằng 0 |
| `combined_spend_l1m` | `COALESCE(gsm,0) + COALESCE(vf,0)` | NULL chỉ khi cả hai NULL |
| `dominant_business_unit_l1m` | `NULL` khi combined = 0/NULL, `'TIE'` khi bằng nhau | không tự chọn GSM |

Phân biệt NULL vs 0 là bắt buộc: trung bình chi tiêu VF tính trên cả khách chưa từng mua xe
là con số sai mà SQL vẫn đúng. Coverage warning (`non_null_ratio`) phải hiện lên UI.

Quy ước này phải nằm trong **mô tả catalog**, không chỉ trong doc — LLM chỉ đọc mô tả để chọn
cột. Ba cột spend dùng `null_meaning = no_history_in_unit`; `dominant_business_unit_l1m` và
`cross_bu_engagement_score` dùng `no_spend_to_compare`.

### Quy ước đặt tên cột trong bảng cross-BU

Bảng có **9 cột** và **không lặp lại `is_vehicle_owner`** — tên đó đã thuộc
`feature.vinfast_transaction`. Trùng tên giữa hai bảng làm SQL generator không biết chọn bảng
nào, trong khi validator khớp theo tên nên không phát hiện được. Câu hỏi "chủ xe có hoạt động
GSM không" dùng `gsm_active_vehicle_owner_flag`.

Nhãn `business_unit` của bảng là **`CROSS_BU`** (không phải VINFAST) — retriever định tuyến
theo nhãn này.

## 6. `metadata.join_catalog` — nguồn sự thật

Catalog nằm trong DB, **không** có bản YAML song song (2 nguồn cho 1 sự thật = drift).
Seed qua `scripts/seed_metadata.py`. Sprint 2 bắt đầu với đúng **1 dòng**:

| left | right | keys | type | cardinality | snapshot bắt buộc |
|---|---|---|---|---|---|
| `feature.gsm_transaction` | `feature.vinfast_transaction` | `customer_id`, `snapshot_date` | inner | 1:1 | ✅ |

Thêm dòng khi có nhu cầu thật, kèm test positive + negative.
