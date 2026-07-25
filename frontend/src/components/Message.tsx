import { useState } from "react";
import type { AskResponse, AskStatus, Confidence } from "../types";
import { ResultView } from "./ResultView";
import { SqlPanel } from "./SqlPanel";
import { TechnicalDetails } from "./TechnicalDetails";
import { Icon } from "./Icon";
import { chartable, scalar } from "../lib/table";
import { downloadCsv } from "../lib/csv";

const CONF: Record<Confidence, { label: string; cls: string; icon: string }> = {
  high: { label: "High", cls: "text-success", icon: "check_circle" },
  medium: { label: "Medium", cls: "text-warning", icon: "info" },
  low: { label: "Low", cls: "text-error", icon: "warning" },
};

const STATUS_CHIP: Partial<Record<AskStatus, { label: string; cls: string; icon: string }>> = {
  clarify: { label: "Cần làm rõ", cls: "text-warning", icon: "help" },
  out_of_scope: { label: "Ngoài phạm vi", cls: "text-primary", icon: "block" },
  error: { label: "Lỗi", cls: "text-error", icon: "error" },
};

const QUICK = ["GSM", "VinFast", "Hủy"];

export function Message({
  response: r,
  onQuickReply,
}: {
  response: AskResponse;
  onQuickReply: (t: string) => void;
}) {
  const [view, setView] = useState<"table" | "chart">("table");
  const conf = CONF[r.confidence];
  const chip = STATUS_CHIP[r.status];
  const pct = r.coverage?.non_null_ratio == null ? null : Math.round(r.coverage.non_null_ratio * 1000) / 10;
  const canToggle = r.result != null && scalar(r.result) == null && chartable(r.result);
  const hasRows = !!r.result && r.result.rows.length > 0;

  return (
    <div className="relative flex justify-start">
      <div className="absolute -left-12 top-0 hidden h-8 w-8 items-center justify-center rounded-full border border-border bg-primary/10 text-primary md:flex">
        <Icon name="smart_toy" className="text-[18px]" />
      </div>
      <div
        className="flex w-full flex-col gap-4 border border-border bg-surface p-5 shadow-sm"
        style={{ borderRadius: "16px 16px 16px 4px" }}
      >
        {/* Header badges */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-surface-variant pb-3">
          <span className="flex items-center gap-1.5 rounded-full border border-primary/20 bg-surface-muted px-2.5 py-1 text-[12px] font-medium text-primary">
            <Icon name="auto_awesome" className="text-[14px]" /> AI Generated
          </span>
          {r.status === "ok" ? (
            <span className={`flex items-center gap-1.5 text-[12px] font-medium ${conf.cls}`}>
              <Icon name={conf.icon} className="text-[16px]" /> Confidence: {conf.label}
            </span>
          ) : (
            chip && (
              <span className={`flex items-center gap-1.5 text-[12px] font-medium ${chip.cls}`}>
                <Icon name={chip.icon} className="text-[16px]" /> {chip.label}
              </span>
            )
          )}
        </div>

        {r.answer_vi && <p className="leading-relaxed text-on-surface">{r.answer_vi}</p>}

        {r.status === "clarify" && r.clarifying_question && (
          <div className="space-y-2">
            <div className="rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-on-surface">
              {r.clarifying_question}
            </div>
            <div className="flex flex-wrap gap-2">
              {QUICK.map((q) => (
                <button
                  key={q}
                  onClick={() => onQuickReply(q)}
                  className="rounded-full border border-border bg-surface px-3 py-1 text-xs text-on-surface-variant transition-colors hover:border-primary hover:text-primary"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {r.status === "error" && r.error && (
          <div className="rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-sm text-error">
            {r.error}
          </div>
        )}

        {r.result && <ResultView result={r.result} view={view} />}
        {r.sql && <SqlPanel sql={r.sql} />}

        {(canToggle || hasRows) && (
          <div className="flex flex-wrap gap-3">
            {canToggle && (
              <button
                onClick={() => setView(view === "chart" ? "table" : "chart")}
                className="flex items-center gap-2 rounded-lg border border-primary/30 bg-surface px-4 py-2 text-sm font-medium text-primary transition-all hover:border-primary hover:bg-primary/5"
              >
                <Icon name="monitoring" className="text-[16px]" />
                {view === "chart" ? "Xem bảng" : "View Trends"}
              </button>
            )}
            {hasRows && (
              <button
                onClick={() => downloadCsv(r.result!)}
                className="flex items-center gap-2 rounded-lg border border-border bg-surface px-4 py-2 text-sm text-text-secondary transition-all hover:border-primary/50 hover:text-primary"
              >
                <Icon name="download" className="text-[16px]" /> Export CSV
              </button>
            )}
          </div>
        )}

        {/* Meta: coverage + repairs (gắn cờ độ phủ theo mục 5) */}
        {r.status === "ok" && (pct != null || r.repairs > 0 || r.coverage?.note) && (
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-text-secondary">
            {pct != null && (
              <span
                className={`rounded-full px-2 py-0.5 ${pct < 50 ? "bg-warning/10 text-warning" : "bg-surface-muted"}`}
              >
                {pct < 50 && "⚠ "}Độ phủ: {pct}%
              </span>
            )}
            {r.repairs > 0 && (
              <span className="rounded-full bg-surface-muted px-2 py-0.5">Tự sửa SQL: {r.repairs}</span>
            )}
            {r.coverage?.note && <span>{r.coverage.note}</span>}
          </div>
        )}
        {r.status === "ok" && r.confidence === "low" && (
          <div className="text-xs text-error">
            ⚠ Độ tin cậy thấp — hãy kiểm chứng SQL trước khi dùng.
          </div>
        )}

        <TechnicalDetails retrieved={r.retrieved} trace={r.pipeline_trace} />
      </div>
    </div>
  );
}
