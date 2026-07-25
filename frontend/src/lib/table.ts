import type { QueryResult } from "../types";

const NF = new Intl.NumberFormat("vi-VN");

/** Format 1 ô: số → nhóm nghìn vi-VN, null → "—", còn lại → String. */
export function fmt(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return NF.format(v);
  return String(v);
}

/** Vẽ được bar chart khi đúng 2 cột và cột thứ 2 toàn số hữu hạn. */
export function chartable(r: QueryResult): boolean {
  return (
    r.columns.length === 2 &&
    r.rows.length > 0 &&
    r.rows.every((row) => typeof row[1] === "number" && Number.isFinite(row[1] as number))
  );
}

/** Kết quả tổng hợp 1 giá trị (1 dòng × 1 cột số) → hiển thị thẻ số lớn. */
export function scalar(r: QueryResult): number | null {
  if (r.rows.length === 1 && r.columns.length === 1 && typeof r.rows[0][0] === "number") {
    return r.rows[0][0] as number;
  }
  return null;
}
