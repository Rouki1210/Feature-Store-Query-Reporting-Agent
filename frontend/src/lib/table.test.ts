import { describe, expect, it } from "vitest";
import type { QueryResult } from "../types";
import { chartable, fmt } from "./table";

const qr = (columns: string[], rows: unknown[][]): QueryResult => ({
  columns,
  rows,
  row_count: rows.length,
  truncated: false,
});

describe("fmt", () => {
  it("null → —", () => expect(fmt(null)).toBe("—"));
  it("số → nhóm nghìn vi-VN", () => expect(fmt(1234567)).toBe("1.234.567"));
  it("chuỗi giữ nguyên", () => expect(fmt("GSM")).toBe("GSM"));
});

describe("chartable", () => {
  it("2 cột + cột 2 toàn số → true", () =>
    expect(chartable(qr(["bu", "n"], [["GSM", 5], ["VF", 3]]))).toBe(true));
  it("cột 2 có chuỗi → false", () =>
    expect(chartable(qr(["bu", "x"], [["GSM", "a"]]))).toBe(false));
  it("khác 2 cột → false", () =>
    expect(chartable(qr(["a", "b", "c"], [[1, 2, 3]]))).toBe(false));
  it("không có dòng → false", () => expect(chartable(qr(["a", "b"], []))).toBe(false));
});
