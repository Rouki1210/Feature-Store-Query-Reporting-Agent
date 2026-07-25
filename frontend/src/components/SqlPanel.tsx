import { useState } from "react";
import { highlightSql } from "../lib/sql";
import { Icon } from "./Icon";

// SQL LUÔN hiển thị (CLAUDE.md mục 5: người dùng phải kiểm chứng được).
export function SqlPanel({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    navigator.clipboard?.writeText(sql).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });

  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <div className="flex items-center justify-between border-b border-border bg-surface-container-high px-4 py-2">
        <div className="flex items-center gap-2 text-text-secondary">
          <Icon name="terminal" className="text-[16px]" />
          <span className="text-[12px] font-medium">Generated SQL</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1 text-[10px] font-medium text-success">
            <Icon name="verified" className="text-[12px]" /> Validated
          </span>
          <button
            onClick={copy}
            className="flex items-center gap-1 rounded border border-border bg-surface px-2 py-1 text-[11px] text-text-secondary transition-colors hover:text-primary"
          >
            <Icon name="content_copy" className="text-[14px]" /> {copied ? "Đã copy" : "Copy SQL"}
          </button>
        </div>
      </div>
      <pre className="overflow-x-auto bg-code-bg p-4 font-mono text-[13px] leading-relaxed text-white/90">
        <code>{highlightSql(sql)}</code>
      </pre>
    </div>
  );
}
