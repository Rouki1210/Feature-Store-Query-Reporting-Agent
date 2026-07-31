import { lazy, Suspense } from "react";
import type { QueryResult, ResultShape } from "../types";
import { fmt } from "../lib/table";

const ResultChart = lazy(() =>
  import("./ResultChart").then((m) => ({ default: m.ResultChart })),
);

const NF = new Intl.NumberFormat("vi-VN");

function BentoNumber({ label, value }: { label: string; value: number }) {
  return (
    <div className="relative overflow-hidden rounded-xl border border-border bg-surface p-6 shadow-sm">
      <div className="absolute right-0 top-0 -z-0 h-32 w-32 rounded-bl-full bg-primary/5" />
      <div className="relative z-10 flex flex-col">
        <span className="mb-1 font-mono text-xs text-text-secondary">{label}</span>
        <div className="text-[36px] font-bold leading-tight tracking-tight text-primary">
          {NF.format(value)}
        </div>
      </div>
    </div>
  );
}

function Table({ result }: { result: QueryResult }) {
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-border">
      <table className="min-w-full text-left text-sm">
        <thead className="sticky top-0 bg-surface-container-high text-xs uppercase text-text-secondary">
          <tr>
            {result.columns.map((c) => (
              <th key={c} className="px-3 py-2 font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {result.rows.map((row, i) => (
            <tr key={i} className="hover:bg-surface-muted">
              {row.map((cell, j) => (
                <td key={j} className="px-3 py-1.5 tabular-nums text-on-surface">{fmt(cell)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Chỉ hiển thị kết quả (bento / bảng / chart). Actions + toggle do Message giữ.
export function ResultView({
  result,
  shape,
  view,
}: {
  result: QueryResult;
  shape: ResultShape;
  view: "table" | "chart";
}) {
  if (result.rows.length === 0)
    return <p className="text-sm text-text-secondary">Không có dòng nào khớp.</p>;
  if (shape === "scalar")
    return <BentoNumber label={result.columns[0]} value={result.rows[0][0] as number} />;
  if (view === "chart" && (shape === "category" || shape === "time_series"))
    return (
      <Suspense
        fallback={<div className="py-8 text-center text-xs text-text-secondary">Đang tải biểu đồ…</div>}
      >
        <ResultChart result={result} shape={shape} />
      </Suspense>
    );
  return <Table result={result} />;
}
