# ADR 0003 — Không thêm tầng feature global (toàn công ty) ở Sprint 2

- Ngày: 2026-07-28
- Trạng thái: chấp nhận
- Liên quan: Task 2.3, `docs/adr/0001-cross-bu-precomputed-table.md`, Sprint 3 backlog

## Bối cảnh

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

## Quyết định

**Không.** Task 2.3 giữ nguyên phạm vi: `feature.customer_cross_bu_feature`, grain
`customer_id + snapshot_date`, 10 cột. Tầng global hoãn sang Sprint 3.

## Lý do

**1. Sai grain, khác bảng.** 2.3 trả lời câu hỏi *về khách hàng* ("bao nhiêu khách vừa
đi GSM vừa mua VinFast"). Bộ global trả lời câu hỏi *về công ty* ("tổng doanh thu tháng
này"). Hai grain khác nhau ⇒ hai bảng khác nhau, không gộp được.

**2. Không use case nào của Sprint 2 cần nó.** Cả 6 use case bắt buộc (UC2-01…UC2-06,
`sprint2_definition_of_done.md` §3) đều ở mức khách hàng.

**3. 52/56 feature là SQL một dòng.** Số toàn công ty = `SUM(...)` trên bảng feature
per-customer đã có; tỷ trọng = hai `SUM` chia nhau; chênh lệch tăng trưởng = hiệu hai cột
ratio sẵn có; cancel rate = tỷ số hai cột sẵn có. Precompute thứ agent tự viết được là
speculative (CLAUDE.md §5 — config only, không dựng sẵn thứ chưa ai hỏi).

**4. Chi phí thật là retrieval, không phải storage.** Catalog hiện 360 feature, `hit@1`
mới 60% (`reports/eval_sprint1_final_dev.md`). Thêm 56 feature mang từ khóa "tổng doanh
thu", "số khách hoạt động" sẽ cạnh tranh trực tiếp với feature per-customer cùng nghĩa:
câu "khách nào chi tiêu nhiều nhất" rất dễ trúng `global_total_revenue_sum_l1m` và trả về
một con số duy nhất thay vì danh sách khách.

**5. Bốn feature tương quan phải bỏ, vì hai lý do độc lập:**

- **Không đủ dữ liệu.** `CORR(gsm.revenue_daily, vinfast.revenue_daily)` cần chuỗi doanh
  thu **theo ngày**. Feature store có 6 snapshot cách nhau 30 ngày — 6 điểm quan sát.
  Hệ số tương quan trên 6 điểm là số vô nghĩa nhưng trông y hệt số thật.
- **Mời gọi suy diễn nhân quả**, thứ Sprint 2 cấm rõ (Task 2.7). Đưa hệ số tương quan cho
  quản lý PnL thì câu hỏi tiếp theo luôn là "vậy GSM giảm là do VinFast tăng à?".

## Hệ quả

**Tốt**

- 2.3 giữ phạm vi nhỏ, đo được, đúng use case.
- Retrieval surface không phình thêm 15% ngay trước lúc benchmark Sprint 2.
- Câu hỏi mức công ty vẫn trả lời được — bằng `SUM` trên bảng hiện có, không cần cột mới.

**Xấu**

- Câu hỏi mức công ty tốn một vòng LLM sinh SQL aggregate thay vì đọc thẳng một cột.
  Chấp nhận: đây là câu hỏi hiếm ở use case on-demand, và là việc của reporter đêm.
- Khi Sprint 3 làm reporter, phải dựng bảng global rồi mới narrate được.

## Sprint 3 làm gì (khi tới đó)

Dựng `feature.global_daily` bằng **~6 stem × window**, sinh bằng vòng lặp như `_GSM_STEMS`,
không liệt kê tay 56 cột:

```
global_txn_completed_count_{window}
global_revenue_sum_{window}
global_active_customer_count_{window}
global_share_{bu}_revenue_pct_{window}
global_cancel_rate_{bu}_pct_{window}
global_avg_txn_value_{bu}_{window}
```

Hai điều kiện tiên quyết:

1. **Grain ngày thật.** Reporter cần chuỗi theo ngày, không phải 6 snapshot cách 30 ngày.
   Đây cũng là câu hỏi số 10.1 còn treo trong CLAUDE.md (row grain thật của feature store).
2. `global_active_customer_count` là cột **đáng** precompute duy nhất trong bộ đề xuất:
   `COUNT(DISTINCT customer_id)` qua hai bảng dễ bị LLM viết thành tổng hai count, tính
   trùng khách dùng cả hai BU. Nhóm còn lại vẫn nên để SQL tự tính nếu chỉ hỏi on-demand.

## Xem lại khi nào

Nếu benchmark Sprint 2 cho thấy > 20% câu hỏi thật là câu mức công ty, hoặc reporter đêm
được ưu tiên lên trước Sprint 3, mở lại ADR này.
