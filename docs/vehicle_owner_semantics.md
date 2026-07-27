# Ngữ nghĩa Buyer / Owner / Delivered vehicle

**Trạng thái: ĐỀ XUẤT — cần business xác nhận trước khi bắt đầu Task 2.1.**
Sai 3 định nghĩa này thì Task 2.1–2.3 phải làm lại từ đầu.

Lý do phải viết ra: `raw.vinfast_orders.status = 'completed'` hiện chỉ có nghĩa **đơn hàng
hoàn tất**, không phải **xe đã đến tay khách**. Sprint 1 đã ghi rõ điều này trong
`COMMENT ON TABLE raw.vinfast_orders` và chặn mọi câu hỏi về owner ở router.

---

## 1. Ba định nghĩa

### 1.1 Vehicle buyer

> Khách có ≥ 1 đơn `order_type = 'vehicle'` đạt trạng thái `completed` trong
> `raw.vinfast_order_status_history`, tính đến hết ngày snapshot.

```sql
-- is_vehicle_buyer tại snapshot D
SELECT DISTINCT o.customer_id
FROM raw.vinfast_orders o
JOIN raw.vinfast_order_status_history h ON h.order_id = o.order_id
WHERE o.order_type = 'vehicle'
  AND h.status = 'completed'
  AND h.status_at <= :snapshot_end;   -- D 23:59:59.999999+TZ
```

Ghi chú: đọc từ **status history**, không đọc `vinfast_orders.status`. Cột `status` là trạng
thái *hiện tại*, dùng nó ở snapshot cũ là rò dữ liệu tương lai.

### 1.2 Vehicle owner

> Khách có ≥ 1 bản ghi bàn giao `handover_status = 'completed'` với `handed_over_at` ≤ hết ngày
> snapshot, **và** bản ghi đó chưa bị đảo (`reversed_at` NULL hoặc `reversed_at` > hết ngày snapshot).

```sql
-- is_vehicle_owner tại snapshot D
SELECT DISTINCT hv.customer_id
FROM raw.vinfast_vehicle_handover hv
WHERE hv.handover_status = 'completed'
  AND hv.handed_over_at <= :snapshot_end
  AND (hv.reversed_at IS NULL OR hv.reversed_at > :snapshot_end);
```

**Cấm suy diễn owner từ bất kỳ nguồn nào khác** — không từ `status = 'completed'`, không từ
`status = 'delivered'`, không từ việc có `battery_kwh`. Không có bản ghi handover ⇒ không phải owner.

### 1.3 Delivered vehicle

> Đếm theo `vehicle_id` (không phải `order_id`, không phải `customer_id`), trên các bản ghi
> handover completed chưa bị đảo tại snapshot.

```sql
SELECT COUNT(DISTINCT hv.vehicle_id) ...  -- cùng điều kiện 1.2
```

Một đơn có thể bàn giao nhiều xe; một khách có thể sở hữu nhiều xe. Đếm nhầm đơn vị là lỗi
im lặng — số vẫn "hợp lý" nên không ai phát hiện.

---

## 2. Quan hệ bắt buộc (dùng làm invariant test)

```
owner ⊆ buyer          -- không thể nhận xe mà chưa từng mua
buyer \ owner ≠ ∅      -- đã mua, chưa nhận xe (đang chờ giao)
delivered_count ≤ purchase_completed_count
first_handover_date ≥ first_purchase_date
```

`buyer \ owner ≠ ∅` là điều kiện **bắt buộc có trong mock data** (~30% đơn xe completed chưa
bàn giao). Không có nhóm này thì mọi test buyer-vs-owner pass giả.

---

## 3. Point-in-time policy

Feature tại `snapshot_date = D` chỉ được dùng sự kiện có **event time** ≤ `D 23:59:59.999999`.

| Cột | Vai trò | Dùng cho PIT? |
|---|---|---|
| `status_at`, `handed_over_at`, `reversed_at` | sự kiện xảy ra lúc nào | ✅ **có** |
| `recorded_at`, `ingested_at` | hệ thống ghi nhận lúc nào | ❌ không |
| `updated_at` | trạng thái mới nhất | ❌ tuyệt đối không |

Hệ quả — **late-arriving event vẫn được tính**: sự kiện xảy ra ngày 10 nhưng ghi nhận ngày 40
vẫn thuộc snapshot ngày 30. Lý do và đánh đổi: xem `docs/adr/0002-event-time-not-ingest-time.md`.

Hệ quả — **reversed sau snapshot không ảnh hưởng snapshot đó**: khách trả xe ngày 40 thì tại
snapshot ngày 30 họ **vẫn là owner**. Snapshot là ảnh quá khứ, không phải trạng thái hiện tại.

---

## 4. Câu hỏi user sẽ hỏi và cột phải dùng

| Câu hỏi (VI) | Feature đúng | Sai nếu dùng |
|---|---|---|
| "Bao nhiêu khách đã mua xe?" | `is_vehicle_buyer` | handover |
| "Bao nhiêu khách đã nhận xe?" | `is_vehicle_owner` | `status='completed'` |
| "Khách GSM nào đang là chủ xe VinFast?" | `gsm_active_vehicle_owner_flag` | join tay |
| "Bao nhiêu xe đã bàn giao?" | `vehicle_delivered_count_l1m` | đếm `customer_id` |
| "Mua rồi mà chưa nhận xe?" | `is_vehicle_buyer=1 AND is_vehicle_owner=0` | — |

Synonym VI phải seed vào `feature_describer.SYNONYMS`: *chủ xe, đứng tên xe, đã nhận xe,
đã bàn giao, sở hữu xe* → owner; *đã mua xe, chốt đơn xe, đơn xe hoàn tất* → buyer.

---

## 5. Đã chốt (2026-07-27)

- [x] **`completed` là trạng thái CUỐI — không thể `cancelled` sau đó.**
      `completed` và `cancelled` đều là trạng thái kết thúc; một `order_id` chỉ được có **một**
      trạng thái kết thúc trong `raw.vinfast_order_status_history`.
      Chuỗi hợp lệ: `created → processing → {completed | cancelled}`.
      Có cả hai ⇒ **dữ liệu lỗi**, không phải nghiệp vụ cần xử lý.
      Trả hàng / hoàn tiền sau khi hoàn tất **không** biểu diễn bằng `cancelled` — nếu là xe thì
      biểu diễn bằng handover `reversed` (mục 1.2); nếu là phụ kiện thì ngoài scope Sprint 2.
      → Enforce: mock generator chỉ sinh chuỗi hợp lệ + test
      `test_vinfast_event_history.py::test_no_order_has_two_terminal_statuses`.
      `ponytail:` kiểm ở tầng app, không dùng trigger DB — thêm trigger nếu warehouse thật vi phạm.
- [x] **Handover `reversed` không tách "trả hẳn" vs "đổi xe".** Cả hai đều mất owner với
      `vehicle_id` đó. Đổi xe = 1 bản ghi `reversed` + 1 bản ghi handover mới, nên khách vẫn là
      owner qua `vehicle_id` mới — không cần cột phân loại.
- [x] **Xe sang tên cho người khác: ngoài scope Sprint 2.** Không mô hình hóa chuyển quyền sở
      hữu. Nếu warehouse thật có, xử lý ở sprint sau.
