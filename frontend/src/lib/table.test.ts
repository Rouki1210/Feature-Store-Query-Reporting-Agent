import { describe, expect, it } from "vitest";
import { fmt } from "./table";

// `chartable` đã bỏ cùng hàm nó kiểm: shape do backend quyết định, xem
// backend/tests/test_result_shape.py.
describe("fmt", () => {
  it("null → —", () => expect(fmt(null)).toBe("—"));
  it("số → nhóm nghìn vi-VN", () => expect(fmt(1234567)).toBe("1.234.567"));
  it("chuỗi giữ nguyên", () => expect(fmt("GSM")).toBe("GSM"));
});
