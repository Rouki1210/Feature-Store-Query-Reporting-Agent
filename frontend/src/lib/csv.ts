import type { QueryResult } from "../types";

function esc(v: unknown): string {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(r: QueryResult): string {
  const lines = [r.columns.map(esc).join(",")];
  for (const row of r.rows) lines.push(row.map(esc).join(","));
  return lines.join("\n");
}

export function downloadCsv(r: QueryResult, filename = "ket-qua.csv"): void {
  // BOM ﻿ để Excel đọc đúng tiếng Việt UTF-8.
  const blob = new Blob(["﻿" + toCsv(r)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
