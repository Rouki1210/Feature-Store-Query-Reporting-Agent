import type { ReactNode } from "react";

const KEYWORDS = new Set([
  "select", "from", "where", "and", "or", "not", "as", "group", "order", "by", "having",
  "on", "join", "left", "right", "inner", "outer", "with", "distinct", "interval", "desc",
  "asc", "in", "between", "like", "is", "null", "case", "when", "then", "else", "end",
  "union", "all", "limit", "offset",
]);
const FUNCS = new Set([
  "sum", "count", "avg", "max", "min", "date_sub", "current_date", "coalesce", "round",
  "cast", "extract", "now", "date_trunc",
]);

// Tokenizer nhẹ (không phụ thuộc lib): chuỗi 'x' → amber, keyword → tím,
// hàm → cyan, số → cyan. Chỉ để hiển thị SQL đã sinh cho dễ đọc.
export function highlightSql(sql: string): ReactNode[] {
  const re = /('[^']*')|(\b[a-zA-Z_][a-zA-Z0-9_]*\b)|(\d+(?:\.\d+)?)/g;
  const out: ReactNode[] = [];
  let last = 0;
  let k = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(sql)) !== null) {
    if (m.index > last) out.push(sql.slice(last, m.index));
    const tok = m[0];
    if (m[1]) {
      out.push(<span key={k++} className="text-warning">{tok}</span>);
    } else if (m[2]) {
      const lc = tok.toLowerCase();
      if (KEYWORDS.has(lc)) out.push(<span key={k++} className="text-keyword">{tok}</span>);
      else if (FUNCS.has(lc)) out.push(<span key={k++} className="text-accent-cyan">{tok}</span>);
      else out.push(tok);
    } else {
      out.push(<span key={k++} className="text-accent-cyan">{tok}</span>);
    }
    last = m.index + tok.length;
  }
  if (last < sql.length) out.push(sql.slice(last));
  return out;
}
