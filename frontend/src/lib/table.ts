const NF = new Intl.NumberFormat("vi-VN");

/** Format 1 ô: số → nhóm nghìn vi-VN, null → "—", còn lại → String. */
export function fmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return NF.format(v);
  return String(v);
}

// `chartable`/`scalar` đã bỏ: backend trả `result_shape`. Hai nơi cùng phán quyết
// cách hiển thị là cách sinh bug im lặng (xem vụ `SLOT_CHOICES` mời sai slot).
