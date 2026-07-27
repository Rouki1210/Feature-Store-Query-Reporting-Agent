# Sprint 2 — Scope & Definition of Done

Checklist thực thi chi tiết: `SPRINT2_TODO.md` (ở gốc repo).
Contracts: `vehicle_owner_semantics.md`, `join_policy.md`, `short_term_state_contract.md`.
Quyết định: `adr/0001-cross-bu-precomputed-table.md`, `adr/0002-event-time-not-ingest-time.md`.

---

## 1. Mục tiêu sprint

Agent trả lời được câu hỏi **xuyên GSM ↔ VinFast**, phân biệt đúng **người mua xe** và
**người đã nhận xe**, join dữ liệu chỉ theo đường đã duyệt, và giữ nguyên toàn bộ guardrail
của Sprint 1.

## 2. Phạm vi

**Trong scope**

| Nhóm | Hạng mục |
|---|---|
| Raw | `raw.vinfast_order_status_history`, `raw.vinfast_vehicle_handover` |
| Feature | `feature.customer_cross_bu_feature`; 7 cột buyer/owner thêm vào `feature.vinfast_transaction` |
| Metadata | `metadata.join_catalog`; mở rộng `agent.query_log` (join_plan, state_transition, coverage_warning) |
| Agent | Join Planner, Generator v2, Guard v2 (join-vs-catalog), slot model cho clarification, result-shape |
| UI | KPI card / line chart, nút hủy, hiển thị join explanation |
| Đo lường | ~30 case benchmark mới (cross-BU, buyer/owner, PIT, multi-turn, join safety) |

**Ngoài scope** (không làm, không bàn lại trong sprint này)

Memory dài hạn · user preference · nightly scanner / anomaly detection / proactive report ·
causal inference · BU ngoài GSM và VinFast · `global_loyalty` và cross-PnL · Redis cho state ·
`metadata.visualization_config` · sang tên xe.

## 3. Câu hỏi bắt buộc trả lời được (use case nghiệm thu)

| Mã | Câu hỏi | Kỳ vọng |
|---|---|---|
| UC2-01 | "Có bao nhiêu khách hoạt động tháng gần nhất?" | hỏi lại GSM hay VinFast → "GSM" → chạy → xóa pending |
| UC2-02 | "Bao nhiêu khách hoạt động GSM và đồng thời có đơn VinFast hoàn tất?" | dùng `customer_cross_bu_feature`, không join tay |
| UC2-03 | "Bao nhiêu khách GSM đang là chủ xe VinFast?" | dùng feature từ handover, KHÔNG dùng `status='completed'` |
| UC2-04 | "So sánh số khách có đơn xe hoàn tất với số khách đã nhận xe." | hai số khác nhau, giải thích được vì sao |
| UC2-05 | "Ghép mọi snapshot GSM với mọi snapshot VinFast theo customer_id." | **reject** (thiếu `snapshot_date`) |
| UC2-06 | "Phân tích hành vi GSM của nhóm chủ xe VinFast." | trả lời + cảnh báo coverage nếu nhóm quá nhỏ |

## 4. Definition of Done

Sprint 2 xong khi **tất cả** dòng dưới đúng:

- [ ] 6 use case UC2-01…UC2-06 chạy đúng kỳ vọng trên UI thật.
- [ ] Buyer và owner cho ra hai con số khác nhau, và tồn tại khách `buyer=1, owner=0`.
- [ ] Point-in-time test pass **100%** (future leak, late-arriving, reversed).
- [ ] Join ngoài `join_catalog` hoặc thiếu `snapshot_date` bị reject **100%**.
- [ ] Pending clarification: resolve đúng, xóa sau resolve, không rò giữa session, hết hạn đúng TTL.
- [ ] SQL, confidence và warning hiển thị đầy đủ trên UI.
- [ ] Raw/PII access: **0** case thành công.
- [ ] Regression Sprint 1: 40 case dev không tụt so với mốc `sprint1_final`.
- [ ] Holdout chạy **đúng 1 lần**, đạt target bảng mục 5, không dùng để tuning.
- [ ] Có `reports/sprint2_evaluation.md` kèm failure analysis theo tầng.

## 5. Metric target

| Metric | Target | Đo bằng |
|---|---:|---|
| Cross-BU table selection | ≥ 90% | retrieval recall trong `run_eval` |
| Join-plan accuracy | ≥ 90% | `test_join_planner` + eval category `cross_bu` |
| PIT correctness | 100% | `tests/test_point_in_time.py` |
| Buyer/owner accuracy | 100% | eval category `buyer_vs_owner` |
| Multi-turn resolution | ≥ 95% | eval category `multi_turn` |
| State isolation | 100% | `test_conversation.py` |
| SQL executable rate | ≥ 90% | `run_eval` |
| Result accuracy | ≥ 85% | execution accuracy (comparator) |
| Safety rejection | 100% | `test_sql_validator_v2.py` |
| Visualization selection | ≥ 85% | `test_result_shape.py` |
| Raw/PII access | 0 case | guard test + `feature_agent_reader` |

## 6. Điều kiện khởi động (gate của Task 2.0)

Không bắt đầu Task 2.1 khi còn dòng nào chưa tick:

- [ ] 3 định nghĩa buyer / owner / delivered được business xác nhận
      (`vehicle_owner_semantics.md` mục 5).
- [ ] Join policy được xác nhận: join chuẩn + luật reject (`join_policy.md`).
- [ ] Short-term state contract được xác nhận, gồm TTL 15 phút và "không Redis"
      (`short_term_state_contract.md`).
- [ ] Hai ADR được duyệt.
- [ ] **3 test đỏ hiện tại đã xanh** (thiếu GRANT — xem `TODO.md` mục "Chặn ngay").
      Bắt đầu sprint trên nền test đỏ là tự làm mù chính mình.
- [ ] Đã chạy `run_eval --split dev --tag sprint1_final` và lưu số vào `backend/reports/`.
      Không có mốc thì cuối sprint không chứng minh được là không làm hỏng Sprint 1.

## 7. Không có mâu thuẫn schema / catalog / prompt

Kiểm tra cuối Task 2.0 — mỗi nguồn phải nói cùng một điều:

| Nguồn | Hiện nói gì | Sau Sprint 2 phải nói gì |
|---|---|---|
| `db/schema/*.sql` comment | "completed ≠ handover" | giữ nguyên, thêm comment 2 bảng mới |
| `app/agent/router.py` | refuse owner + cross-BU | mở đúng 3 chỗ, giữ refuse loyalty/PnL khác |
| `app/agent/generator.py` prompt | không nhắc owner | thêm luật buyer ≠ owner |
| `feature_spec.py` | 353 feature | 353 + 7 (VF) + cross-BU |
| `golden_set.yaml` | 3 case kỳ vọng refuse owner/cross-BU | đổi kỳ vọng có chủ đích, không xóa case |
